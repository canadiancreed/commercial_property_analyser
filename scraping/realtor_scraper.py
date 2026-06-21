"""realtor.ca listing price scraper, driven by Playwright.

realtor.ca's own search is unreliable (wrong matches, missing listings, heavy
JS), so instead we **web-search the address, open the first realtor.ca listing
link, and read the price straight off that listing's detail page**. The search
sends us directly to the right listing, sidestepping realtor.ca's map/search
entirely. We search with DuckDuckGo's HTML endpoint — Google and Bing both
CAPTCHA automated queries, DuckDuckGo does not.

To survive realtor.ca's Akamai bot defences this drives Firefox with a persistent
on-disk profile, suppresses the automation fingerprint (Firefox prefs + an init
script), and relies on a one-time human warm-up (``open_home``) to clear the
initial challenge — the resulting cookie carries the batch.

Memory: each lookup runs in its own page that is closed afterwards, and the whole
browser context is recycled every ``recycle_every`` lookups, so a long sweep does
not grow until it hangs.

When realtor.ca (or the search engine) changes its markup, the selectors below are the single
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
# runs, which makes realtor.ca's Akamai bot manager (and search-engine consent) less
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

# ── realtor.ca / search-engine markup (the one place to fix on breakage) ──
BASE_URL = "https://www.realtor.ca"
HOME_URL = BASE_URL + "/"

# Web-search entry point. Google and Bing both CAPTCHA automated queries;
# DuckDuckGo's HTML endpoint serves plain results without a robot wall and returns
# the current realtor.ca listing links (verified against live listings).
SEARCH_URL  = "https://html.duckduckgo.com/html/?q="
SEARCH_HOME = "https://duckduckgo.com/"

# Search-engine cookie/consent buttons (first visible is clicked). DuckDuckGo's
# HTML endpoint has none; kept harmless for other engines.
CONSENT_SELECTORS = [
    "button:has-text('Accept')",
    "button:has-text('I agree')",
]

# Collects every realtor.ca result link from a search results page, unwrapping
# the redirect wrappers search engines use (DuckDuckGo's /l/?uddg= and Google's
# /url?q=).
REALTOR_LINKS_JS = r"""
() => {
  const out = [];
  const add = (u) => { if (u && u.indexOf('realtor.ca') !== -1) out.push(u); };
  document.querySelectorAll('a[href]').forEach(a => {
    const h = a.getAttribute('href') || '';
    let m = h.match(/[?&]uddg=([^&]+)/);          // DuckDuckGo redirect
    if (m) { add(decodeURIComponent(m[1])); return; }
    m = h.match(/^\/url\?.*[?&]q=([^&]+)/);         // Google redirect
    if (m) { add(decodeURIComponent(m[1])); return; }
    if (h.indexOf('http') === 0) add(h);            // direct link
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

# Search-engine "are you a robot" interstitial.
SEARCH_BLOCK_MARKERS = ("unusual traffic", "detected unusual",
                        "/sorry/index", "verify you are a human",
                        "are you a robot")

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
    """Build the address text used in the search query.

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


def search_query(address: str, city: str = "", province: str = "") -> str:
    """Full web-search query string, restricted to realtor.ca."""
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


# Street-word abbreviations expanded on both the stored address and the listing
# slug so matching is consistent (St↔Street, W↔West, etc.). Directionals are
# included because "King St W" must NOT match "King St E".
_ADDR_ABBR = {
    "st": "street", "str": "street", "ave": "avenue", "av": "avenue",
    "rd": "road", "dr": "drive", "blvd": "boulevard", "cres": "crescent",
    "crt": "court", "ct": "court", "pl": "place", "ln": "lane",
    "pkwy": "parkway", "hwy": "highway", "ter": "terrace", "sq": "square",
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
}


def _norm_tokens(text: str):
    """Lowercase, strip punctuation, and expand street abbreviations to tokens."""
    cleaned = re.sub(r"[^a-z0-9]+", " ", (text or "").lower())
    return [_ADDR_ABBR.get(w, w) for w in cleaned.split()]


def _listing_slug(href: str) -> str:
    """The {address-slug} portion of a /real-estate/{id}/{slug} href, hyphens→spaces."""
    m = re.search(r"/real-estate/\d+/([^/?#]+)", href or "")
    return m.group(1).replace("-", " ") if m else ""


def _slug_address(href: str):
    """Parse (street_name, number) from a listing href (kept for diagnostics)."""
    slug = _listing_slug(href)
    return _parse_address_sort(slug) if slug else ("", 0)


def address_matches(address: str, href: str) -> bool:
    """True only if the listing slug is the SAME street address as ``address``.

    Strict on purpose: requires the exact street number and every street-name
    word — name, type, and directional — to appear in the slug (abbreviations
    normalised on both sides). So 'King St W' won't match 'King St E', and
    'Main St' won't match 'Main Ave'. City is not required (realtor.ca groups
    some towns under regions), only the street.
    """
    slug_tokens = _norm_tokens(_listing_slug(href))
    if not slug_tokens:
        return False

    # Street portion only (before the first comma), so the city doesn't dilute it.
    a = _norm_tokens((address or "").split(",")[0])
    num_idx = next((i for i, w in enumerate(a) if w.isdigit()), None)
    if num_idx is None:
        return False
    number = a[num_idx]
    street = [w for w in a[num_idx + 1:] if not w.isdigit()]   # name + direction
    if not street:
        return False

    slug_set = set(slug_tokens)
    if number not in slug_set:
        return False
    return all(w in slug_set for w in street)


def listing_candidates(links, address: str):
    """realtor.ca listing links whose address matches, in result order.

    Only exact street matches are returned — never a 'close enough' listing.
    Several may match (relistings reuse the address under new IDs and the stale
    ones 404), so the caller tries them in turn. Duplicates removed, order kept.
    """
    ordered, seen = [], set()
    for h in links:
        if "/real-estate/" in h and address_matches(address, h) and h not in seen:
            seen.add(h)
            ordered.append(h)
    return ordered


class RealtorScraper:
    """Drives a persistent Firefox context, one page per lookup.

    Use as a context manager::

        with RealtorScraper() as scraper:
            result = scraper.fetch_price(address, city, province)
    """

    def __init__(self, headless: bool = False, min_delay: float = 6.0,
                 max_delay: float = 14.0, nav_timeout_ms: int = 30000,
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
        """Open the search engine; return True if it shows a robot check.

        Warm-up: with a headful, persistent-profile browser the user can clear any
        consent/CAPTCHA once by hand and the cookie carries the batch. We warm up
        on the search engine (the lookup's entry point), not realtor.ca.
        """
        try:
            self._page.goto(SEARCH_HOME, wait_until="domcontentloaded")
            time.sleep(random.uniform(1.0, 2.0))
            self._dismiss_consent()
            body = (self._page.content() or "").lower()
            return any(m in body for m in SEARCH_BLOCK_MARKERS)
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

    def _dismiss_consent(self):
        btn = self._first_visible(CONSENT_SELECTORS)
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
        """Search the address, open the first realtor.ca listing, read its price.

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
            # 1) Web-search the address (restricted to realtor.ca).
            page.goto(SEARCH_URL + quote_plus(search_query(address, city, province)),
                      wait_until="domcontentloaded")
            self._dismiss_consent()
            time.sleep(random.uniform(1.0, 2.0))

            body = (page.content() or "").lower()
            if any(m in body for m in SEARCH_BLOCK_MARKERS):
                return FetchResult(outcome=OUTCOME_BLOCKED)

            candidates = listing_candidates(page.evaluate(REALTOR_LINKS_JS) or [], address)
            if not candidates:
                # No realtor.ca listing surfaced → not currently listed.
                return FetchResult(outcome=OUTCOME_NOT_FOUND)

            # 2) Try the candidate listings in turn. Relistings leave stale IDs
            #    that 404, so fall through to the next until one yields a price.
            #    A search referer makes the deep-link load look natural.
            saw_live = False
            for listing in candidates[:3]:
                resp = page.goto(listing, wait_until="domcontentloaded", referer=SEARCH_HOME)
                time.sleep(random.uniform(1.5, 2.5))
                self._dismiss_overlays()
                if self._is_blocked():
                    return FetchResult(outcome=OUTCOME_BLOCKED, listing_url=listing)
                if resp is not None and resp.status >= 400:
                    continue                      # stale relisting → next candidate

                saw_live = True
                price = self._read_price()
                if price is not None:
                    return FetchResult(price=price, outcome=OUTCOME_FOUND, listing_url=listing)
                body = (page.content() or "").lower()
                if any(m in body for m in NOT_FOUND_MARKERS):
                    continue                      # delisted page → try next candidate

            # Live listing page(s) loaded but no price parsed → unexpected layout
            # (flag for a selector fix); if every candidate 404'd → not listed.
            return FetchResult(
                outcome=OUTCOME_BLOCKED if saw_live else OUTCOME_NOT_FOUND,
                listing_url=candidates[0],
            )

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
