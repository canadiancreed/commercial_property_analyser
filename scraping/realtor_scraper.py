"""realtor.ca listing price scraper, driven by Playwright.

realtor.ca has no usable public API and aggressively blocks automated access
(Akamai bot manager + reCAPTCHA), so prices are read by driving a browser with
human-like pacing. To survive the bot defences this drives Firefox with a
persistent on-disk profile, suppresses the automation fingerprint (Firefox prefs
+ an init script), and relies on a one-time human warm-up (``open_home``) to
clear the initial challenge — the resulting cookie carries the batch. This is
inherently brittle: when realtor.ca changes its markup, the selectors below are
the single place to fix.

Listings are looked up by **address** rather than MLS number — relisted
properties get a new MLS number, so the address is the durable key.

Network/Playwright imports are lazy so this module (and ``build_query``) can be
imported and unit-tested without Playwright installed.
"""

import os
import random
import re
import time
from dataclasses import dataclass
from typing import Optional

from core.address import _display_address

# Persistent browser profile — cookies and any solved challenge survive between
# runs, which makes realtor.ca's Akamai bot manager less likely to re-block us.
# Lives outside the repo.
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

# ── realtor.ca markup-dependent selectors (the one place to fix on breakage) ──
HOME_URL = "https://www.realtor.ca/"

# Search box on the homepage. Tried in order; first match wins.
SEARCH_INPUT_SELECTORS = [
    "#homeSearchInput",
    "input#smallSearchBox",
    "input[name='searchBox']",
    "input[placeholder*='Address']",
    "input[type='search']",
]

# Autocomplete suggestion rows that appear as you type an address.
AUTOCOMPLETE_SELECTORS = [
    "#autoCompleteContainerNS .autocompleteResult",
    ".autocompleteResult",
    "[class*='autocomplete'] li",
    "ul[role='listbox'] li",
]

# Price element on a listing detail page.
PRICE_SELECTORS = [
    "#listingPriceValue",
    "[data-testid='listing-price']",
    "[class*='listingDetailsPrice']",
    "[class*='ListingPrice']",
    "h1 [class*='price']",
]

# Text fragments that signal an anti-bot challenge rather than a real result.
BLOCK_MARKERS = ("just a moment", "checking your browser", "captcha",
                 "cf-challenge", "access denied", "unusual traffic")

# Text fragments that signal a genuinely empty search (delisted / 404).
NOT_FOUND_MARKERS = ("no results", "we couldn't find", "0 listings",
                     "no properties found", "page not found")

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
    """Build a realtor.ca search string from a stored property's location.

    Stored addresses often omit the province (e.g. ``"24-26 Main St S,
    Alexandria"``); this appends city/province only when not already present so
    the query reads like a human would type it.
    """
    addr = _display_address(address or "").strip().rstrip(",").strip()
    parts = [addr] if addr else []
    if city and city.strip().lower() not in addr.lower():
        parts.append(city.strip())
    prov = (province or "").strip().upper()
    if prov and not re.search(rf"\b{prov}\b", addr.upper()):
        parts.append(prov)
    return ", ".join(p for p in parts if p)


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


class RealtorScraper:
    """Drives one persistent Firefox context across many lookups.

    Re-launching the browser per property is a fast route to getting blocked, so
    a single context is reused for the whole batch. Use as a context manager::

        with RealtorScraper() as scraper:
            result = scraper.fetch_price(address, city, province)
    """

    def __init__(self, headless: bool = False, min_delay: float = 3.0,
                 max_delay: float = 8.0, nav_timeout_ms: int = 30000,
                 user_data_dir: str = USER_DATA_DIR):
        self._headless       = headless
        self._min_delay      = min_delay
        self._max_delay      = max_delay
        self._nav_timeout_ms = nav_timeout_ms
        self._user_data_dir  = user_data_dir
        self._pw             = None
        self._context        = None
        self._page           = None
        self._first          = True

    # ── lifecycle ─────────────────────────────────────────────────────────
    def _launch_context(self):
        """Launch a stealthy persistent Firefox context.

        A persistent context (real on-disk profile, so cookies and a solved
        challenge survive) plus Firefox's native user-agent and webdriver pref
        looks far more human to Akamai than a fresh automated Chromium context.
        """
        os.makedirs(self._user_data_dir, exist_ok=True)
        return self._pw.firefox.launch_persistent_context(
            user_data_dir=self._user_data_dir,
            headless=self._headless,
            firefox_user_prefs=FIREFOX_PREFS,
            locale="en-CA",
            timezone_id="America/Toronto",
            viewport={"width": 1366, "height": 900},
        )

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._context = self._launch_context()
        self._context.set_default_timeout(self._nav_timeout_ms)
        self._context.add_init_script(STEALTH_INIT_JS)
        # A persistent context opens with one blank page; reuse it.
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

    def open_home(self) -> bool:
        """Navigate to the realtor.ca homepage; return True if it shows a block.

        Used as a warm-up: with a headful, persistent-profile browser the user can
        solve the Akamai/CAPTCHA challenge once by hand and the cookie carries the
        rest of the batch.
        """
        try:
            self._page.goto(HOME_URL, wait_until="domcontentloaded")
            time.sleep(random.uniform(1.0, 2.0))
            return self._is_blocked()
        except Exception:
            return True

    # ── fetching ──────────────────────────────────────────────────────────
    def _throttle(self):
        """Human-like pause between lookups (skipped for the first)."""
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

    def fetch_price(self, address: str, city: str = "",
                    province: str = "") -> FetchResult:
        """Look a listing up by address and return its current price.

        Never raises: any failure is mapped to ``OUTCOME_BLOCKED`` so a single
        bad lookup cannot abort a batch sweep.
        """
        self._throttle()
        query = build_query(address, city, province)
        try:
            self._page.goto(HOME_URL, wait_until="domcontentloaded")

            if self._is_blocked():
                return FetchResult(outcome=OUTCOME_BLOCKED)

            box = self._first_visible(SEARCH_INPUT_SELECTORS)
            if box is None:
                # Couldn't even find the search box → treat as a block, not a 404.
                return FetchResult(outcome=OUTCOME_BLOCKED)

            box.click()
            box.fill("")
            box.type(query, delay=random.randint(40, 110))
            time.sleep(random.uniform(1.0, 2.0))

            suggestion = self._first_visible(AUTOCOMPLETE_SELECTORS)
            if suggestion is None:
                # No autocomplete match → fall back to submitting the query.
                box.press("Enter")
            else:
                suggestion.click()

            self._page.wait_for_load_state("domcontentloaded")
            time.sleep(random.uniform(1.0, 2.0))

            if self._is_blocked():
                return FetchResult(outcome=OUTCOME_BLOCKED)

            url  = self._page.url
            body = (self._page.content() or "").lower()

            price = self._read_price()
            if price is not None:
                return FetchResult(price=price, outcome=OUTCOME_FOUND,
                                   listing_url=url)

            if any(m in body for m in NOT_FOUND_MARKERS):
                return FetchResult(outcome=OUTCOME_NOT_FOUND, listing_url=url)

            # Reached a page but found no price and no explicit "no results" —
            # most likely a challenge or an unexpected layout: report as blocked
            # so it is never miscounted as a genuine delisting.
            return FetchResult(outcome=OUTCOME_BLOCKED, listing_url=url)

        except Exception:
            return FetchResult(outcome=OUTCOME_BLOCKED)

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
