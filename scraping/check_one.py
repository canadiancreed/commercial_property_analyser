"""Standalone single-address price check — a safe way to test the scraper.

Hits realtor.ca for ONE address and prints the result. Touches no database,
no menu, no saved progress, nothing in master — just the scraper. Use it to
confirm Playwright works and to tune the selectors in realtor_scraper.py before
trusting the full batch sweep.

    python -m scraping.check_one "24-26 Main St S" --city Alexandria --province ON
    python -m scraping.check_one "1 Fake Rd" --city Ottawa --province ON --stored 500000

Optionally pass --stored PRICE to see the same/dropped/risen comparison.
"""

import argparse

from scraping.realtor_scraper import RealtorScraper, build_query
from scraping.price_comparator import compare


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check one realtor.ca listing price.")
    ap.add_argument("address", help="Street address, e.g. '24-26 Main St S'")
    ap.add_argument("--city", default="", help="City name")
    ap.add_argument("--province", default="", help="Province code, e.g. ON")
    ap.add_argument("--stored", type=float, default=None,
                    help="Stored asking price to compare against (optional)")
    ap.add_argument("--headless", action="store_true",
                    help="Run the browser without a visible window")
    args = ap.parse_args(argv)

    query = build_query(args.address, args.city, args.province)
    print(f"  Query     : {query}")
    print("  Launching browser (Ctrl-C to abort)...")

    with RealtorScraper(headless=args.headless) as scraper:
        if scraper.open_home():
            input("  realtor.ca is challenging the browser. Solve any CAPTCHA / "
                  "'Access Denied'\n  page in the window, then press Enter: ")
        result = scraper.fetch_price(args.address, args.city, args.province)

    print(f"  Outcome   : {result.outcome}")
    print(f"  Price     : {result.price}")
    print(f"  Listing   : {result.listing_url or '—'}")

    if args.stored is not None:
        row = compare(args.stored, result)
        print(f"  Stored    : {args.stored:,.0f}")
        print(f"  Status    : {row['status']}")
        if row["delta"] is not None:
            print(f"  Delta     : {row['delta']:+,.0f} ({row['delta_pct']:+.1f}%)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
