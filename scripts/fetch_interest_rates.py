#!/usr/bin/env python3
"""
Fetch + rebuild json/interest_rates.json from the Bank of Canada Valet API.

The sourced BASE rate behind commercial-mortgage pricing: the Government of
Canada 5-year benchmark bond yield. Everything per-type is priced as
``base + credit spread`` (see analysis/financing_config.py), so this is the one
number that must come from a real, refreshable source rather than a hand guess.

SOURCE
    Bank of Canada — Valet API (open, no key). Group bond_yields_benchmark,
    series BD.CDN.5YR.DQ.YLD, plus V39079 (policy rate) for context.

REFRESH
    Re-run this script. Government bond yields move daily, so it can be run as
    often as wanted; the desktop app also refreshes on boot (once/day). After a
    refresh, Re-analyze to push the new rates into stored results.

    python scripts/fetch_interest_rates.py            # fetch + write
    python scripts/fetch_interest_rates.py --check     # show current file, fetch nothing

Never fabricates figures and never clobbers the existing file on failure.
"""
import argparse
import json
import os
import sys

# Allow running as `python scripts/fetch_interest_rates.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.rate_feed import OUT_PATH, fetch_base_rate, write_interest_rates


def _show(path):
    if not os.path.exists(path):
        print(f"  {path} does not exist yet — run without --check to create it.")
        return
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    print(f"  {path}")
    print(f"    base_rate   : {data.get('base_rate')}  "
          f"({(data.get('base_rate') or 0)*100:.3g}% GoC 5yr)")
    print(f"    as_of       : {data.get('as_of')}")
    print(f"    fetched_at  : {data.get('fetched_at')}")
    print(f"    status      : {data.get('status')}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Rebuild json/interest_rates.json from the Bank of Canada.")
    ap.add_argument("--check", action="store_true", help="Print the current file and exit (no fetch).")
    ap.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout seconds (default 30).")
    args = ap.parse_args()

    if args.check:
        _show(OUT_PATH)
        return 0

    print("  Fetching GoC 5-year benchmark yield from the Bank of Canada Valet API ...")
    try:
        payload = fetch_base_rate(timeout=args.timeout)
    except Exception as e:
        print(f"  ERROR fetching Bank of Canada rate: {e}", file=sys.stderr)
        print(f"  The existing {OUT_PATH} was left untouched.", file=sys.stderr)
        return 1

    write_interest_rates(payload, OUT_PATH)
    print(f"  Wrote {OUT_PATH}: GoC 5yr = {payload['base_rate']*100:.3g}% "
          f"(as of {payload.get('as_of')}). Re-analyze to apply.")
    pol = payload.get("context", {}).get("policy_rate")
    if pol is not None:
        print(f"  (context: BoC policy rate {pol*100:.3g}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
