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

from core.address import _parse_address_sort

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

# ── realtor.ca structure (the one place to fix on breakage) ──
#
# Strategy: the residential search box is the wrong door for commercial property.
# realtor.ca files commercial listings under a per-city page:
#     https://www.realtor.ca/{province}/{city-slug}/commercial-real-estate
# Each listing card links to /real-estate/{id}/{address-slug} and shows a price,
# so we load the city page once (cached & reused across that city's properties)
# and match our stored address against the cards by street number + name.
BASE_URL = "https://www.realtor.ca"
HOME_URL = BASE_URL + "/"

# Pages of listings to scan per city before giving up (cities like Toronto have
# many; most have one or two).
MAX_CITY_PAGES = 25

# "Next page" control on a city listings page. Tried in order; first match wins.
NEXT_PAGE_SELECTORS = [
    "a[rel='next']",
    "a[aria-label*='Next']",
    ".paginationLinkForward",
    "a.lnkNextResultsPage",
]

# Extracts {id, href, price} for every listing card on the current city page.
# Climbs from each listing link to the nearest ancestor that contains a dollar
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

# Text fragments that signal an anti-bot challenge rather than a real result.
BLOCK_MARKERS = ("just a moment", "checking your browser", "captcha",
                 "cf-challenge", "access denied", "unusual traffic")

# Outcome values for FetchResult.outcome.
OUTCOME_FOUND     = "found"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_BLOCKED   = "blocked"

_PRICE_RE = re.compile(r"\$\s?([\d][\d,]{2,})")
_NONWORD_RE = re.compile(r"[^a-z0-9]+")


def city_url(province: str, city: str) -> str:
    """Build the commercial-listings URL for a city, e.g.
    ('ON', 'The Nation') -> https://www.realtor.ca/on/the-nation/commercial-real-estate
    """
    prov = (province or "").strip().lower()
    slug = _NONWORD_RE.sub("-", (city or "").strip().lower()).strip("-")
    return f"{BASE_URL}/{prov}/{slug}/commercial-real-estate"


def _slug_address(href: str):
    """Parse (street_name, number) from a /real-estate/{id}/{address-slug} href."""
    m = re.search(r"/real-estate/\d+/([^/?#]+)", href or "")
    if not m:
        return "", 0
    return _parse_address_sort(m.group(1).replace("-", " "))


def address_matches(address: str, href: str) -> bool:
    """True if a stored address matches a listing card's URL slug.

    Matches on exact street number plus the first significant street-name word
    (as a whole word) — enough to disambiguate within one city without tripping
    on shared house numbers or common tokens like directionals.
    """
    t_name, t_num = _parse_address_sort(address or "")
    s_name, s_num = _slug_address(href)
    if not t_name or t_num != s_num:
        return False
    t_tokens = t_name.split()
    s_tokens = set(s_name.split())
    return bool(t_tokens) and t_tokens[0] in s_tokens


@dataclass
class FetchResult:
    price:       Optional[float] = None
    outcome:     str             = OUTCOME_BLOCKED
    listing_url: str             = ""


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
        # (province, city-slug) -> list of {id, href, price} listing cards, or
        # None when that city page was blocked. Reused across the city's
        # properties so we load each city page only once per run.
        self._city_cache     = {}

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
        """Human-like pause between page loads (skipped for the very first)."""
        if self._first:
            self._first = False
            return
        time.sleep(random.uniform(self._min_delay, self._max_delay))

    def fetch_price(self, address: str, city: str = "",
                    province: str = "") -> FetchResult:
        """Find a commercial listing by address and return its current price.

        Loads the property's city commercial page (cached/reused across that
        city), then matches the address among the listing cards. Never raises:
        any failure maps to OUTCOME_BLOCKED so one bad lookup cannot abort a batch.
        """
        try:
            listings = self._get_city_listings(province, city)
        except Exception:
            return FetchResult(outcome=OUTCOME_BLOCKED)

        if listings is None:           # city page was blocked
            return FetchResult(outcome=OUTCOME_BLOCKED)

        for card in listings:
            if address_matches(address, card.get("href", "")):
                url   = BASE_URL + card["href"] if card["href"].startswith("/") else card["href"]
                price = _parse_price(card.get("price") or "")
                # A matched card with no readable price still counts as found;
                # the comparator flags the missing price rather than a 404.
                return FetchResult(price=price, outcome=OUTCOME_FOUND, listing_url=url)

        # City page loaded fine but the address isn't among its commercial
        # listings → genuinely not listed (delisted / sold).
        return FetchResult(outcome=OUTCOME_NOT_FOUND)

    def _get_city_listings(self, province: str, city: str):
        """Return cached listing cards for a city, scraping it once on first use.

        Returns a list of {id, href, price} dicts, or None if the city page was
        blocked.
        """
        key = ((province or "").strip().lower(),
               _NONWORD_RE.sub("-", (city or "").strip().lower()).strip("-"))
        if key not in self._city_cache:
            self._city_cache[key] = self._scrape_city(province, city)
        return self._city_cache[key]

    def _scrape_city(self, province: str, city: str):
        """Load a city's commercial pages and return all listing cards (or None
        if blocked)."""
        self._throttle()
        self._page.goto(city_url(province, city), wait_until="domcontentloaded")
        time.sleep(random.uniform(1.5, 3.0))
        if self._is_blocked():
            return None

        cards, seen = [], set()
        for _ in range(MAX_CITY_PAGES):
            for card in (self._page.evaluate(LISTINGS_JS) or []):
                if card["id"] not in seen:
                    seen.add(card["id"])
                    cards.append(card)
            if not self._go_next_page():
                break
            if self._is_blocked():
                break
        return cards

    def _go_next_page(self) -> bool:
        """Click the 'next page' control if present; return whether it advanced."""
        for sel in NEXT_PAGE_SELECTORS:
            loc = self._page.locator(sel).first
            try:
                if loc.count() and loc.is_visible():
                    loc.click()
                    self._page.wait_for_load_state("domcontentloaded")
                    time.sleep(random.uniform(1.5, 3.0))
                    return True
            except Exception:
                continue
        return False

    def _is_blocked(self) -> bool:
        try:
            title = (self._page.title() or "").lower()
            body  = (self._page.content() or "").lower()
        except Exception:
            return True
        return any(m in title or m in body for m in BLOCK_MARKERS)
