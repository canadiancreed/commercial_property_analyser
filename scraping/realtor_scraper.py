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
from datetime import date, timedelta
from typing import Optional
from urllib.parse import quote_plus

from core.address import _display_address, _parse_address_sort
from models.constants import CANADIAN_PROVINCES, PROVINCE_NAME_TO_CODE

_PROVINCE_TOKENS = {p.lower() for p in CANADIAN_PROVINCES}

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

# Address element on a listing detail page.
ADDRESS_SELECTORS = [
    "#listingAddress",
    "[data-testid='listing-address']",
    "[class*='listingAddress']",
    "h1[class*='address']",
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


# Square footage used when a listing does not post a floor/building area.
DEFAULT_SQFT = 5000.0


@dataclass
class ListingData:
    """Basic data parsed from a single realtor.ca listing detail page.

    Populated by ``RealtorScraper.fetch_listing``. Fields that aren't posted on
    the listing stay None (except ``total_sq_ft``, which defaults to DEFAULT_SQFT).
    Units, unit type, and property type are deliberately absent — they can't be
    read reliably, so the imported record is saved incomplete for manual entry.
    """
    outcome:        str             = OUTCOME_BLOCKED
    address:        str             = ""
    asking_price:   Optional[float] = None
    mls_number:     str             = ""
    floors:         Optional[int]   = None
    property_taxes: Optional[float] = None
    total_sq_ft:    float           = DEFAULT_SQFT
    listing_date:   str             = ""
    listing_url:    str             = ""


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


# ── Listing-detail parsers (pure, no network — used by fetch_listing) ──────────
# realtor.ca renders detail fields as a label followed by its value. These read
# the page's body text (not brittle CSS paths), so a layout reshuffle that keeps
# the same labels keeps working. Each returns None/absent when the label is gone.

_MLS_RE     = re.compile(r"MLS\s*®?\s*(?:Number|No\.?|#)?\s*[:#]?\s*([A-Za-z]?\d[\dA-Za-z\-]{4,})",
                         re.IGNORECASE)
_STOREYS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\n?\s*Storeys?|Storeys?\s*[:#]?\s*(\d+(?:\.\d+)?)",
                         re.IGNORECASE)
_TAXES_RE   = re.compile(r"Annual\s+Property\s+Tax(?:es)?\s*[:#]?\s*\$?\s*([\d][\d,]*)",
                         re.IGNORECASE)
# Floor/building area, optionally a range "1,000 - 2,000 sqft". The label may be
# followed by "(approx)", a colon, etc. — [^\d\n]* skips that up to the first digit.
_SQFT_RE    = re.compile(
    r"(?:Floor\s+Space|Building\s+Area|Size|Square\s+Footage)[^\d\n]*"
    r"([\d][\d,]*)(?:\s*-\s*([\d][\d,]*))?\s*(?:sq|ft)",
    re.IGNORECASE)
# "Time on REALTOR.ca" — a number plus a unit (hour/day/week/month).
_TIME_ON_RE = re.compile(
    r"Time\s+on\s+REALTOR\.?ca\s*[:#]?\s*(\d+)\s*(hour|day|week|month)s?",
    re.IGNORECASE)
# Canadian postal code, e.g. "K0A 2M0" / "K0A2M0".
_POSTAL_RE  = re.compile(r"\b[A-Za-z]\d[A-Za-z]\s*\d[A-Za-z]\d\b")


def _to_float(s: str) -> Optional[float]:
    try:
        return float((s or "").replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _parse_mls(text: str) -> str:
    """The listing's MLS® number, or '' if not present."""
    m = _MLS_RE.search(text or "")
    return m.group(1).strip() if m else ""


def _parse_storeys(text: str) -> Optional[int]:
    """Number of storeys (→ floors), rounded down, or None if not present."""
    m = _STOREYS_RE.search(text or "")
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    val = _to_float(raw)
    return int(val) if val else None


def _parse_taxes(text: str) -> Optional[float]:
    """Annual property taxes in dollars, or None if not present."""
    m = _TAXES_RE.search(text or "")
    return _to_float(m.group(1)) if m else None


def _parse_sqft(text: str) -> float:
    """Floor/building area in sq ft.

    Returns the midpoint when given as a range ('A - B'); falls back to
    DEFAULT_SQFT when no area is posted.
    """
    m = _SQFT_RE.search(text or "")
    if not m:
        return DEFAULT_SQFT
    lo = _to_float(m.group(1))
    if lo is None:
        return DEFAULT_SQFT
    hi = _to_float(m.group(2)) if m.group(2) else None
    return (lo + hi) / 2 if hi is not None else lo


def _parse_time_on_realtor(text: str, today: date = None) -> str:
    """Derive the listing date from realtor.ca's 'Time on REALTOR.ca' field.

    Hours → today (listed today); days/weeks/months → counted backwards from
    today (weeks×7, months×30). Falls back to today when the field is absent or
    unparseable. Returns an ISO date string.
    """
    today = today or date.today()
    m = _TIME_ON_RE.search(text or "")
    if not m:
        return today.isoformat()
    n    = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "hour":
        return today.isoformat()
    days = {"day": 1, "week": 7, "month": 30}.get(unit, 1) * n
    return (today - timedelta(days=days)).isoformat()


def _clean_listing_address(raw: str) -> str:
    """Normalise a realtor.ca address to '<street>, <city>, <CODE>'.

    Strips the postal code and converts a spelled-out province name to its
    2-letter code, so the result parses cleanly through menu._parse_city_province.
    A province already in code form is left as-is.
    """
    addr = _POSTAL_RE.sub("", raw or "").strip()
    addr = re.sub(r"\s+,", ",", addr).strip().strip(",").strip()
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    if parts:
        last = parts[-1]
        code = PROVINCE_NAME_TO_CODE.get(last.lower())
        if code:
            parts[-1] = code
        elif last.upper() in CANADIAN_PROVINCES:
            parts[-1] = last.upper()
    return ", ".join(parts)


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


def _listing_id(href: str) -> int:
    """The numeric {id} from a /real-estate/{id}/ href (higher = more recent)."""
    m = re.search(r"/real-estate/(\d+)/", href or "")
    return int(m.group(1)) if m else -1


def _slug_address(href: str):
    """Parse (street_name, number) from a listing href (kept for diagnostics)."""
    slug = _listing_slug(href)
    return _parse_address_sort(slug) if slug else ("", 0)


def _city_tokens(address: str, city: str) -> list:
    """City words to require in the slug, from an explicit city or the address.

    Uses the ``city`` argument when given, else everything after the first comma
    of the address. Province codes (ON, QC…) and digits are dropped.
    """
    src = city if (city or "").strip() else ",".join((address or "").split(",")[1:])
    return [w for w in _norm_tokens(src)
            if not w.isdigit() and w not in _PROVINCE_TOKENS]


def address_matches(address: str, href: str, city: str = "") -> bool:
    """True only if the listing slug is the SAME full address as ``address``.

    Strict on purpose: requires the exact street number, every street-name word
    (name, type, and directional), AND the city to appear in the slug, with
    abbreviations normalised on both sides. So 'King St W' won't match 'King St E',
    'Main St' won't match 'Main Ave', and '9 Main St, Athens' won't match
    '9 Main St, Uxbridge'.
    """
    slug_set = set(_norm_tokens(_listing_slug(href)))
    if not slug_set:
        return False

    # Street portion (before the first comma).
    a = _norm_tokens((address or "").split(",")[0])
    num_idx = next((i for i, w in enumerate(a) if w.isdigit()), None)
    if num_idx is None:
        return False
    number = a[num_idx]
    street = [w for w in a[num_idx + 1:] if not w.isdigit()]   # name + direction
    if not street:
        return False

    if number not in slug_set or not all(w in slug_set for w in street):
        return False

    # City must also be present, so the same street number/name in a different
    # town can't match (a wrong town is what produces absurd price deltas).
    city_words = _city_tokens(address, city)
    if city_words and not all(w in slug_set for w in city_words):
        return False
    return True


def listing_candidates(links, address: str, city: str = ""):
    """realtor.ca listing links whose full address matches, newest first.

    Only exact street+city matches are returned — never a 'close enough' listing
    or the same address in another town. Several may match (relistings reuse the
    address under new IDs), so they are ordered by listing ID descending — the
    highest ID is the most recent listing, whose price we want. Duplicates removed.
    """
    matches, seen = [], set()
    for h in links:
        if "/real-estate/" in h and address_matches(address, h, city) and h not in seen:
            seen.add(h)
            matches.append(h)
    matches.sort(key=_listing_id, reverse=True)
    return matches


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

    def _read_address(self) -> str:
        """Read the listing's address element, or '' if not found."""
        loc = self._first_visible(ADDRESS_SELECTORS)
        if loc is not None:
            try:
                return (loc.inner_text() or "").strip()
            except Exception:
                pass
        return ""

    def fetch_listing(self, url: str) -> ListingData:
        """Open a pasted realtor.ca listing URL and parse its basic data.

        Reuses the same overlay/block plumbing as ``fetch_price`` and reads the
        page's body text once, running the pure parsers over it. Never raises:
        any failure maps to OUTCOME_BLOCKED. Units, unit type, and property type
        are NOT parsed (they can't be read reliably) — the caller saves an
        incomplete record for manual completion.
        """
        page = self._context.new_page()
        self._page = page
        try:
            resp = page.goto(url, wait_until="domcontentloaded", referer=SEARCH_HOME)
            time.sleep(random.uniform(1.5, 2.5))
            self._dismiss_overlays()
            if self._is_blocked():
                return ListingData(outcome=OUTCOME_BLOCKED, listing_url=url)
            if resp is not None and resp.status >= 400:
                return ListingData(outcome=OUTCOME_NOT_FOUND, listing_url=url)

            body = ""
            try:
                body = page.inner_text("body") or ""
            except Exception:
                body = (page.content() or "")
            if any(m in body.lower() for m in NOT_FOUND_MARKERS):
                return ListingData(outcome=OUTCOME_NOT_FOUND, listing_url=url)

            address = _clean_listing_address(self._read_address())
            if not address:
                # Fall back to the URL slug (street + locality words).
                address = _clean_listing_address(_listing_slug(url))

            return ListingData(
                outcome        = OUTCOME_FOUND,
                address        = address,
                asking_price   = self._read_price(),
                mls_number     = _parse_mls(body),
                floors         = _parse_storeys(body),
                property_taxes = _parse_taxes(body),
                total_sq_ft    = _parse_sqft(body),
                listing_date   = _parse_time_on_realtor(body),
                listing_url    = url,
            )
        except Exception:
            return ListingData(outcome=OUTCOME_BLOCKED, listing_url=url)
        finally:
            try:
                page.close()
            except Exception:
                pass

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

            candidates = listing_candidates(page.evaluate(REALTOR_LINKS_JS) or [], address, city)
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
