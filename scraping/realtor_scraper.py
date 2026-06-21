"""realtor.ca listing price scraper, driven by Playwright.

realtor.ca's own search is unreliable (wrong matches, missing listings, heavy
JS), so instead we **Google the address, open the first realtor.ca listing link,
and read the price straight off that listing's detail page**. Google sends us
directly to the right listing, which sidesteps realtor.ca's map/search entirely.

To survive realtor.ca's Akamai bot defences this drives Firefox with a persistent
on-disk profile, suppresses the automation fingerprint (Firefox prefs + an init
script), and relies on a one-time human warm-up (``open_home``) to clear the
initial challenge — the resulting cookie carries the batch.

Memory: each lookup runs in its own page that is closed afterwards, and the whole
browser context is recycled every ``recycle_every`` lookups, so a long sweep does
not grow until it hangs.

When realtor.ca (or Google) changes its markup, the selectors below are the single
place to fix.
"""

import os
import random
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

from core.address import _display_address, _parse_address_sort

# Persistent browser profile — cookies and any solved challenge survive between
# runs, which makes realtor.ca's Akamai bot manager (and Google consent) less
# likely to re-challenge us. Lives outside the repo.
USER_DATA_DIR = os.path.join(os.path.expanduser("~"),
                             ".commercial_property_analyser", "realtor_firefox_profile")

# Firefox prefs that suppress the automation fingerprint Akamai keys on.
FIREFOX_PREFS = {
    "dom.webdriver.enabled": False,      # hides navigator.webdriver at the engine level
    "useAutomationExtension": False,
    "media.peerconnection.enabled": False,
    "intl.accept_languages": "en-CA, en",
}

# Injected before any page script runs as a belt-and-braces mask over the
# automation fingerprint (navigator.webdriver / plugins / languages).
STEALTH_INIT_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-CA', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""

# ── realtor.ca / Google markup (the one place to fix on breakage) ──
BASE_URL = "https://www.realtor.ca"
HOME_URL = BASE_URL + "/"
GOOGLE_SEARCH_URL = "https://www.google.com/search?q="

# Google's cookie-consent buttons (first visible is clicked).
GOOGLE_CONSENT_SELECTORS = [
    "button#L2AGLb",
    "button:has-text('Accept all')",
    "button:has-text('I agree')",
    "button:has-text('Reject all')",
    "form[action*='consent'] button",
]

# Collects every realtor.ca result link from a Google results page, unwrapping
# Google's /url?q= redirect form when present.
REALTOR_LINKS_JS = r"""
() => {
  const out = [];
  document.querySelectorAll('a[href]').forEach(a => {
    let h = a.getAttribute('href') || '';
    if (h.startsWith('/url?')) {
      const m = h.match(/[?&]q=([^&]+)/);
      if (m) h = decodeURIComponent(m[1]);
    }
    if (h.indexOf('http') === 0 && h.indexOf('realtor.ca') !== -1) out.push(h);
  });
  return out;
}
"""

# Blocking overlays on a realtor.ca listing page — feedback survey (answer No)
# and the cookie banner (Dismiss). Each visible match is clicked.
DISMISS_SELECTORS = [
    "button:text-is('No')",
    "a:text-is('No')",
    "button:has-text('Dismiss')",
    "a:has-text('Dismiss')",
    "[aria-label='Close']",
    "[aria-label='close']",
]

# Price element on a listing detail page.
PRICE_SELECTORS = [
    "#listingPriceValue",
    "[data-testid='listing-price']",
    "[class*='listingDetailsPrice']",
    "[class*='ListingPrice']",
    "h1 [class*='price']",
]

# realtor.ca anti-bot challenge markers (kept specific so a bare 'captcha' in the
# site-wide reCAPTCHA script can't flag a good page as blocked).
BLOCK_MARKERS = ("access denied", "you don't have permission to access",
                 "pardon our interruption", "request unsuccessful",
                 "unusual traffic", "/cdn-cgi/challenge", "just a moment",
                 "verify you are a human")

# Google's own "are you a robot" interstitial.
GOOGLE_BLOCK_MARKERS = ("unusual traffic", "detected unusual",
                        "/sorry/index", "before you continue to google")

# The listing detail page is no longer live (sold / expired / removed).
NOT_FOUND_MARKERS = ("no longer available", "listing has expired",
                     "listing not found", "page not found",
                     "has been sold", "property not found")

# Outcome values for FetchResult.outcome.
OUTCOME_FOUND     = "found"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_BLOCKED   = "blocked"

_PRICE_RE = re.compile(r"\$\s?([\d][\d,]{2,})")


@dataclass
class FetchResult:
    price:       Optional[float] = None
    outcome:     str             = OUTCOME_BLOCKED
    listing_url: str             = ""


def build_query(address: str, city: str = "", province: str = "") -> str:
    """Build the address text used in the Google query.

    Stored addresses often omit the province (e.g. ``"24-26 Main St S,
    Alexandria"``); this appends city/province only when not already present.
    """
    addr = _display_address(address or "").strip().rstrip(",").strip()
    parts = [addr] if addr else []
    if city and city.strip().lower() not in addr.lower():
        parts.append(city.strip())
    prov = (province or "").strip().upper()
    if prov and not re.search(rf"\b{prov}\b", addr.upper()):
        parts.append(prov)
    return ", ".join(p for p in parts if p)


def google_query(address: str, city: str = "", province: str = "") -> str:
    """Full Google query string, restricted to realtor.ca."""
    return build_query(address, city, province) + " site:realtor.ca"


def _parse_price(text: str) -> Optional[float]:
    """Pull the first dollar amount out of a price string like '$1,250,000'."""
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _slug_address(href: str):
    """Parse (street_name, number) from a /real-estate/{id}/{address-slug} href."""
    m = re.search(r"/real-estate/\d+/([^/?#]+)", href or "")
    if not m:
        return "", 0
    return _parse_address_sort(m.group(1).replace("-", " "))


def address_matches(address: str, href: str) -> bool:
    """True if a stored address matches a listing-URL slug.

    Matches on exact street number plus the first significant street-name word,
    used to prefer the right Google result when several realtor.ca links appear.
    """
    t_name, t_num = _parse_address_sort(address or "")
    s_name, s_num = _slug_address(href)
    if not t_name or t_num != s_num:
        return False
    t_tokens = t_name.split()
    s_tokens = set(s_name.split())
    return bool(t_tokens) and t_tokens[0] in s_tokens


def pick_listing(links, address: str):
    """Choose the best realtor.ca listing link from Google results.

    Prefers a /real-estate/ link whose slug matches the address; otherwise the
    first /real-estate/ link. Returns None if no listing link is present.
    """
    real = [h for h in links if "/real-estate/" in h]
    if not real:
        return None
    for h in real:
        if address_matches(address, h):
            return h
    return real[0]


class RealtorScraper:
    """Drives a persistent Firefox context, one page per lookup.

    Use as a context manager::

        with RealtorScraper() as scraper:
            result = scraper.fetch_price(address, city, province)
    """

    def __init__(self, headless: bool = False, min_delay: float = 3.0,
                 max_delay: float = 8.0, nav_timeout_ms: int = 30000,
                 user_data_dir: str = USER_DATA_DIR, recycle_every: int = 40):
        self._headless       = headless
        self._min_delay      = min_delay
        self._max_delay      = max_delay
        self._nav_timeout_ms = nav_timeout_ms
        self._user_data_dir  = user_data_dir
        self._recycle_every  = recycle_every
        self._pw             = None
        self._context        = None
        self._page           = None
        self._first          = True
        self._fetch_count    = 0

    # ── lifecycle ─────────────────────────────────────────────────────────
    def _launch_context(self):
        """Launch a stealthy persistent Firefox context."""
        os.makedirs(self._user_data_dir, exist_ok=True)
        ctx = self._pw.firefox.launch_persistent_context(
            user_data_dir=self._user_data_dir,
            headless=self._headless,
            firefox_user_prefs=FIREFOX_PREFS,
            locale="en-CA",
            timezone_id="America/Toronto",
            viewport={"width": 1366, "height": 900},
        )
        ctx.set_default_timeout(self._nav_timeout_ms)
        ctx.add_init_script(STEALTH_INIT_JS)
        return ctx

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._context = self._launch_context()
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        return False

    def _recycle(self):
        """Close and relaunch the browser context to release accumulated memory.

        Cookies persist via the on-disk profile, so no re-challenge is needed.
        """
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        self._context = self._launch_context()
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

    def open_home(self) -> bool:
        """Open realtor.ca; return True if it shows a block.

        Warm-up: with a headful, persistent-profile browser the user can solve the
        Akamai/CAPTCHA challenge once by hand and the cookie carries the batch.
        """
        try:
            self._page.goto(HOME_URL, wait_until="domcontentloaded")
            time.sleep(random.uniform(1.0, 2.0))
            self._dismiss_overlays()
            return self._is_blocked()
        except Exception:
            return True

    # ── fetching ──────────────────────────────────────────────────────────
    def _throttle(self):
        """Human-like pause between lookups (skipped for the very first)."""
        if self._first:
            self._first = False
            return
        time.sleep(random.uniform(self._min_delay, self._max_delay))

    def _first_visible(self, selectors):
        """Return the first matching visible locator, or None."""
        for sel in selectors:
            loc = self._page.locator(sel).first
            try:
                if loc.count() and loc.is_visible():
                    return loc
            except Exception:
                continue
        return None

    def _dismiss_overlays(self):
        """Close blocking pop-ups (feedback survey 'No', cookie 'Dismiss')."""
        for _ in range(2):
            acted = False
            for sel in DISMISS_SELECTORS:
                loc = self._page.locator(sel).first
                try:
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=2000)
                        acted = True
                        time.sleep(random.uniform(0.3, 0.7))
                except Exception:
                    continue
            if not acted:
                break

    def _dismiss_google_consent(self):
        btn = self._first_visible(GOOGLE_CONSENT_SELECTORS)
        if btn is not None:
            try:
                btn.click(timeout=3000)
                time.sleep(random.uniform(0.6, 1.2))
            except Exception:
                pass

    def _is_blocked(self) -> bool:
        try:
            title = (self._page.title() or "").lower()
            body  = (self._page.content() or "").lower()
        except Exception:
            return True
        return any(m in title or m in body for m in BLOCK_MARKERS)

    def _read_price(self) -> Optional[float]:
        loc = self._first_visible(PRICE_SELECTORS)
        if loc is not None:
            try:
                price = _parse_price(loc.inner_text())
                if price is not None:
                    return price
            except Exception:
                pass
        return None

    def fetch_price(self, address: str, city: str = "",
                    province: str = "") -> FetchResult:
        """Google the address, open the first realtor.ca listing, read its price.

        Runs in its own page (closed afterwards) and recycles the browser every
        ``recycle_every`` lookups to bound memory. Never raises: any failure maps
        to OUTCOME_BLOCKED so a single bad lookup cannot abort a batch sweep.
        """
        self._throttle()
        self._fetch_count += 1
        if self._recycle_every and self._fetch_count % self._recycle_every == 0:
            self._recycle()

        page = self._context.new_page()
        self._page = page
        try:
            # 1) Google the address (restricted to realtor.ca).
            page.goto(GOOGLE_SEARCH_URL + quote_plus(google_query(address, city, province)),
                      wait_until="domcontentloaded")
            self._dismiss_google_consent()
            time.sleep(random.uniform(1.0, 2.0))

            body = (page.content() or "").lower()
            if any(m in body for m in GOOGLE_BLOCK_MARKERS):
                return FetchResult(outcome=OUTCOME_BLOCKED)

            listing = pick_listing(page.evaluate(REALTOR_LINKS_JS) or [], address)
            if not listing:
                # Google surfaced no realtor.ca listing → not currently listed.
                return FetchResult(outcome=OUTCOME_NOT_FOUND)

            # 2) Open the listing detail page and read the price.
            page.goto(listing, wait_until="domcontentloaded")
            time.sleep(random.uniform(1.5, 2.5))
            self._dismiss_overlays()
            if self._is_blocked():
                return FetchResult(outcome=OUTCOME_BLOCKED, listing_url=listing)

            price = self._read_price()
            if price is not None:
                return FetchResult(price=price, outcome=OUTCOME_FOUND, listing_url=listing)

            body = (page.content() or "").lower()
            if any(m in body for m in NOT_FOUND_MARKERS):
                return FetchResult(outcome=OUTCOME_NOT_FOUND, listing_url=listing)

            # Loaded a listing page but found no price — unexpected layout/challenge.
            return FetchResult(outcome=OUTCOME_BLOCKED, listing_url=listing)

        except Exception:
            return FetchResult(outcome=OUTCOME_BLOCKED)
        finally:
            try:
                page.close()
            except Exception:
                pass

    def save_debug(self, path_prefix: str):
        """Write the current page's HTML and a screenshot for diagnosis."""
        try:
            with open(path_prefix + ".html", "w", encoding="utf-8") as f:
                f.write(self._page.content() or "")
        except Exception:
            pass
        try:
            self._page.screenshot(path=path_prefix + ".png", full_page=True)
        except Exception:
            pass
