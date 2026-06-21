"""realtor.ca listing price scraper, driven by Playwright.

realtor.ca has no usable public API and aggressively blocks automated access
(Akamai bot manager + reCAPTCHA), so prices are read by driving a browser with
human-like pacing. To survive the bot defences this drives Firefox with a
persistent on-disk profile, suppresses the automation fingerprint (Firefox prefs
+ an init script), and relies on a one-time human warm-up (``open_home``) to
clear the initial challenge — the resulting cookie carries the batch.

Lookup flow: open realtor.ca, **select the Commercial tab**, type the address
into the search bar, open the matching listing, and read its price. This is
inherently brittle: when realtor.ca changes its markup, the selectors below are
the single place to fix.
"""

import os
import random
import re
import time
from dataclasses import dataclass
from typing import Optional

from core.address import _display_address, _parse_address_sort

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
BASE_URL = "https://www.realtor.ca"
HOME_URL = BASE_URL + "/"

# Blocking overlays that appear on load — a feedback survey ("Would you be
# willing to share your feedback…", answer No) and the cookie banner (Dismiss).
# Each visible match is clicked to clear it; tried after every navigation.
DISMISS_SELECTORS = [
    "button:text-is('No')",        # feedback survey — answer No
    "a:text-is('No')",
    "button:has-text('Dismiss')",  # cookie banner
    "a:has-text('Dismiss')",
    "[aria-label='Close']",
    "[aria-label='close']",
]

# The Commercial tab/toggle next to the search bar. Tried in order; first match
# wins. Selecting it is what makes the search return commercial listings.
COMMERCIAL_TAB_SELECTORS = [
    "a#commercialTab",
    "button:has-text('Commercial')",
    "a:has-text('Commercial')",
    "label:has-text('Commercial')",
    "[class*='commercial' i] a",
    "img[src*='commercial']",
]

# The address search box.
SEARCH_INPUT_SELECTORS = [
    "#homeSearchInput",
    "input#smallSearchBox",
    "input[name='searchBox']",
    "input[placeholder*='Address' i]",
    "input[placeholder*='city' i]",
    "input[type='search']",
]

# Autocomplete suggestion rows that appear as you type an address.
AUTOCOMPLETE_SELECTORS = [
    "#autoCompleteContainerNS .autocompleteResult",
    ".autocompleteResult",
    "[class*='autocomplete'] li",
    "ul[role='listbox'] li",
]

# A search lands on a map + results-list page, not a single listing. Each result
# card in the left sidebar links to /real-estate/{id}/{address-slug} and shows a
# price, so we read {id, href, price} from every card and match our address.
# Climbs from each listing link to the nearest ancestor containing a dollar
# amount, so it does not depend on exact card class names.
LISTINGS_JS = r"""
() => {
  const out = [], seen = new Set();
  document.querySelectorAll("a[href*='/real-estate/']").forEach(a => {
    const href = a.getAttribute('href') || '';
    const m = href.match(/\/real-estate\/(\d+)\//);
    if (!m || seen.has(m[1])) return;
    let el = a, price = null;
    for (let i = 0; i < 6 && el; i++) {
      const pm = (el.textContent || '').match(/\$[\d,]{4,}/);
      if (pm) { price = pm[0]; break; }
      el = el.parentElement;
    }
    seen.add(m[1]);
    out.push({id: m[1], href: href, price: price});
  });
  return out;
}
"""

# Price element when a search resolves straight to a single listing detail page.
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

# realtor.ca sometimes rejects a free-typed search and demands you pick from the
# autocomplete dropdown. These fragments flag that prompt so we can retry.
SELECT_ADDRESS_MARKERS = ("select an address", "select a location",
                          "choose an address", "select one of the",
                          "from the list", "from those presented")

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
    """Build the search-bar text from a stored property's location.

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


def _slug_address(href: str):
    """Parse (street_name, number) from a /real-estate/{id}/{address-slug} href."""
    m = re.search(r"/real-estate/\d+/([^/?#]+)", href or "")
    if not m:
        return "", 0
    return _parse_address_sort(m.group(1).replace("-", " "))


def address_matches(address: str, href: str) -> bool:
    """True if a stored address matches a result card's listing-URL slug.

    Matches on exact street number plus the first significant street-name word
    (as a whole word) — enough to pick the right card out of a results list
    without tripping on shared house numbers or common tokens like directionals.
    """
    t_name, t_num = _parse_address_sort(address or "")
    s_name, s_num = _slug_address(href)
    if not t_name or t_num != s_num:
        return False
    t_tokens = t_name.split()
    s_tokens = set(s_name.split())
    return bool(t_tokens) and t_tokens[0] in s_tokens


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
        """Open realtor.ca, select the Commercial tab, return True if blocked.

        Used as a warm-up: with a headful, persistent-profile browser the user can
        solve the Akamai/CAPTCHA challenge once by hand and the cookie carries the
        rest of the batch. Leaves the Commercial tab selected.
        """
        try:
            self._page.goto(HOME_URL, wait_until="domcontentloaded")
            time.sleep(random.uniform(1.0, 2.0))
            self._dismiss_overlays()
            self._select_commercial()
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

    def _select_commercial(self):
        """Click the Commercial tab so the search returns commercial listings."""
        tab = self._first_visible(COMMERCIAL_TAB_SELECTORS)
        if tab is not None:
            try:
                tab.click()
                time.sleep(random.uniform(0.6, 1.4))
            except Exception:
                pass

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

    def _autocomplete_pick(self, retries: int = 5) -> bool:
        """Click the first autocomplete suggestion once it appears; True if clicked.

        realtor.ca expects you to pick from the dropdown rather than submit raw
        text, so this is preferred over pressing Enter.
        """
        for _ in range(retries):
            time.sleep(random.uniform(0.6, 1.1))
            s = self._first_visible(AUTOCOMPLETE_SELECTORS)
            if s is not None:
                try:
                    s.click()
                    return True
                except Exception:
                    return False
        return False

    def _run_search(self, box, query: str, force_pick: bool = False):
        """Type the query and submit by picking an autocomplete suggestion.

        Falls back to Enter only when no suggestion appears and ``force_pick`` is
        not set. Waits for the results page to settle.
        """
        box.click()
        box.fill("")
        box.type(query, delay=random.randint(40, 110))
        if not self._autocomplete_pick() and not force_pick:
            box.press("Enter")
        try:
            self._page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass
        time.sleep(random.uniform(2.0, 3.5))

    def _needs_address_selection(self) -> bool:
        """True if realtor.ca is showing the 'pick an address from the list' prompt."""
        try:
            body = (self._page.content() or "").lower()
        except Exception:
            return False
        return any(m in body for m in SELECT_ADDRESS_MARKERS)

    def fetch_price(self, address: str, city: str = "",
                    province: str = "") -> FetchResult:
        """Search realtor.ca (Commercial tab) for an address and return its price.

        A search lands on a map + results-list page, so we match the address
        against the result cards. Never raises: any failure maps to
        OUTCOME_BLOCKED so a single bad lookup cannot abort a batch sweep.
        """
        self._throttle()
        query = build_query(address, city, province)
        try:
            self._page.goto(HOME_URL, wait_until="domcontentloaded")
            self._dismiss_overlays()
            if self._is_blocked():
                return FetchResult(outcome=OUTCOME_BLOCKED)

            # Switch to Commercial before searching.
            self._select_commercial()

            box = self._first_visible(SEARCH_INPUT_SELECTORS)
            if box is None:
                # Couldn't find the search box → treat as a block, not a 404.
                return FetchResult(outcome=OUTCOME_BLOCKED)

            self._run_search(box, query)
            self._dismiss_overlays()

            # realtor.ca sometimes rejects a free-typed search with a "select an
            # address from those presented" prompt. Satisfy it by retyping and
            # picking from the autocomplete dropdown; if it still insists, move on.
            if self._needs_address_selection():
                box = self._first_visible(SEARCH_INPUT_SELECTORS)
                if box is not None:
                    self._run_search(box, query, force_pick=True)
                    self._dismiss_overlays()

            if self._is_blocked():
                return FetchResult(outcome=OUTCOME_BLOCKED)

            # The search resolves to a map + results list. Match our address
            # against the result cards and read that card's price.
            cards = self._page.evaluate(LISTINGS_JS) or []
            for card in cards:
                if address_matches(address, card.get("href", "")):
                    href  = card["href"]
                    url   = BASE_URL + href if href.startswith("/") else href
                    price = _parse_price(card.get("price") or "")
                    return FetchResult(price=price, outcome=OUTCOME_FOUND,
                                       listing_url=url)

            # If the search jumped straight to a single listing detail page,
            # there are no cards — read the detail price instead.
            price = self._read_price()
            if price is not None:
                return FetchResult(price=price, outcome=OUTCOME_FOUND,
                                   listing_url=self._page.url)

            # Results loaded but our address isn't among them (or an explicit
            # "no results") → genuinely not listed.
            body = (self._page.content() or "").lower()
            if cards or any(m in body for m in NOT_FOUND_MARKERS):
                return FetchResult(outcome=OUTCOME_NOT_FOUND, listing_url=self._page.url)

            # No cards, no price, no "no results" text → most likely a challenge
            # or unexpected layout; never miscount it as a genuine delisting.
            return FetchResult(outcome=OUTCOME_BLOCKED, listing_url=self._page.url)

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
