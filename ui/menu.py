from datetime import date

from core.address import _display_address, _parse_address_sort
from models.property_input import PropertyInput, UnitMix
from models.constants import PROP_SHORTCUTS, PROPERTY_TYPES, COMMERCIAL_TYPES_LOWER, CANADIAN_PROVINCES
from data.store import DataStore
from analysis.rent_resolver import RentResolver
from analysis.analyzer import CommercialPropertyAnalyzer, build_partial_record
from analysis.metrics.income import INCOME_METRIC_NAMES
from reporting.printer import ReportPrinter
from reporting.property_report import PropertyReportGenerator
from reporting.city_report import CityReportGenerator
from reporting.price_check_report import PriceCheckReportGenerator
from scraping.realtor_scraper import RealtorScraper
from scraping.price_comparator import compare
from scoring.scorer import PropertyScorer
from scoring.city_ranker import CityRanker
from ui.rate_editor import RateEditorMixin
from ui.config_editor import ConfigEditorMixin
from ui.csv_handler import CsvHandlerMixin


def _parse_city_province(addr: str):
    """Parse city and province from an address string.

    Accepts two formats:
      '123 Main St, Ottawa, ON'   — trailing comma-separated province
      '123 Main St, Ottawa ON'    — province appended to city token
    Returns (city, province) or (None, None) if not parseable.
    """
    if not addr or "," not in addr:
        return None, None
    parts = [p.strip() for p in addr.split(",")]
    last  = parts[-1].strip()
    if last.upper() in CANADIAN_PROVINCES:
        province = last.upper()
        city     = parts[-2].strip() if len(parts) >= 2 else None
    else:
        tokens   = last.split()
        province = tokens[-1].upper() if tokens and tokens[-1].upper() in CANADIAN_PROVINCES else None
        city     = " ".join(tokens[:-1]).strip() if province else None
    return city or None, province or None


def _parse_listing_date(raw: str) -> str:
    """Return a valid ISO date string from user input, defaulting to today."""
    default = date.today().isoformat()
    raw = raw.strip()
    if not raw:
        return default
    try:
        date.fromisoformat(raw)
        return raw
    except ValueError:
        return default


class PropertyMenu(RateEditorMixin, ConfigEditorMixin, CsvHandlerMixin):
    """Interactive terminal menu for managing and analyzing saved property records."""

    DIVIDER      = "-" * 75
    THIN_DIVIDER = "-" * 40

    PROP_SHORTCUTS = PROP_SHORTCUTS
    VALID_TYPES    = PROPERTY_TYPES

    def __init__(self, store: DataStore, resolver: RentResolver):
        self._store    = store
        self._resolver = resolver
        self._scorer   = PropertyScorer(store)
        self._ranker   = CityRanker(self._scorer)
        self._prop_rpt = PropertyReportGenerator()
        self._city_rpt = CityReportGenerator()
        self._scan_existing_cities()

    def _scan_existing_cities(self):
        for p in self._store.load_properties():
            city     = (p.get("city") or "").strip()
            province = (p.get("province") or "").strip()
            if city and province:
                self._store.ensure_city_in_rates(city, province)

    # ── Menu loop ─────────────────────────────────────────────────────────

    def run(self):
        while True:
            print(f"\n{'PROPERTY MANAGER':^{75}}")
            print(self.DIVIDER)
            print("  1  List all properties")
            print("  2  View analysis for a property")
            print("  3  Add a new property")
            print("  4  Edit a property")
            print("  5  Delete a property")
            print("  6  Open investment report in browser")
            print("  c  Open city opportunity report")
            print("  p  Check realtor.ca prices (all properties)")
            print("  7  Edit commercial rent rates")
            print("  8  Edit residential rent rates")
            print("  9  Import properties from CSV")
            print("  r  Re-analyze all properties")
            print("  s  Scoring formula & weights")
            print("  0  Exit")
            print(self.DIVIDER)

            choice = input("  Select: ").strip().lower()

            if   choice == "1": self._list()
            elif choice == "2": self._view()
            elif choice == "3": self._add()
            elif choice == "4": self._edit()
            elif choice == "5": self._delete()
            elif choice == "6": self._open_report()
            elif choice == "c": self._open_city_report()
            elif choice == "p": self._price_check()
            elif choice == "7": self._edit_commercial_rates()
            elif choice == "8": self._edit_residential_rates()
            elif choice == "9": self._import_csv()
            elif choice == "r": self._reanalyze_all()
            elif choice == "s": self._edit_score_config()
            elif choice == "0":
                print("  Goodbye.\n")
                break
            else:
                print("  Invalid option — try again.")

    # ── Actions ───────────────────────────────────────────────────────────

    def _list(self):
        ReportPrinter.list_properties(self._store)

    def _view(self):
        props = self._sorted_props()
        if not props:
            print("\n  No properties on file.")
            return
        self._list()
        idx = self._pick_index(props, "View analysis for #")
        if idx is None:
            return
        p = props[idx]
        results = p.get("results", [])
        if not results:
            print("  No analysis results saved for this property.")
            return
        city     = p.get("city",     "")
        province = p.get("province", "")
        ptype    = p.get("property_type", "")
        has_income = any(r.get("metric", "") in INCOME_METRIC_NAMES for r in results)
        print(f"\n  Analysis: {_display_address(p.get('address','')) or '—'}  (analyzed {p.get('analyzed_on', '—')})")
        if not has_income and (city or ptype):
            if ptype and ptype.lower() in COMMERCIAL_TYPES_LOWER:
                print(f"  ⚠  Partial results — no commercial rent rates for {city}, {province}.")
                print(f"     Use menu option 7 to add rates for {city}, then re-edit to refresh analysis.")
            else:
                print(f"  ⚠  Partial results — no residential rent rates for {city}, {province}.")
                print(f"     Use menu option 8 to add rates for {city}, then re-edit to refresh analysis.")
        print(self.DIVIDER)
        print(f"  {'METRIC':<25} {'VALUE':<22} EVALUATION")
        print(self.DIVIDER)
        for r in results:
            print(f"  {r['metric']:<25} {r['value']:<22} {r['grade']}")
        print(self.DIVIDER)
        notes = p.get("notes")
        if notes:
            print("\n  NOTES")
            print(self.THIN_DIVIDER)
            for line in notes.splitlines():
                print(f"  {line}")
            print()

    def _add(self):
        print(f"\n  ADD NEW PROPERTY")
        print(self.THIN_DIVIDER)
        try:
            prop = self._prompt_property()
        except KeyboardInterrupt:
            print("\n  Cancelled.")
            return
        except ValueError as e:
            print(f"\n  Error: {e}")
            return
        try:
            analyzer = CommercialPropertyAnalyzer(prop, self._resolver)
        except ValueError as e:
            # No market rate for this city yet — save the property without
            # analysis so the entry isn't lost, and register the city so rates
            # can be added (option 7/8) and the property re-analyzed later.
            print(f"  No analysis — {e}")
            record = build_partial_record(prop)
            notes  = input("  Notes (Enter to skip): ").strip()
            if notes:
                record["notes"] = notes
            self._store.save_property(record)
            if prop.city and prop.province:
                self._store.ensure_city_in_rates(prop.city, prop.province)
            print(f"  Saved (no analysis): {_display_address(prop.address)}")
            return
        except Exception as e:
            print(f"  Unexpected error: {e}")
            return
        show = input("  Print full analysis? (y/n): ").strip().lower() in ("y", "yes")
        ReportPrinter.print_report(analyzer, show=show)
        record = analyzer.to_record()
        notes  = input("  Notes (Enter to skip): ").strip()
        if notes:
            record["notes"] = notes
        self._store.save_property(record)
        if prop.city and prop.province:
            self._store.ensure_city_in_rates(prop.city, prop.province)
        print(f"  Saved: {_display_address(prop.address)}")

    def _edit(self):
        props = self._sorted_props()
        if not props:
            print("\n  No properties on file.")
            return
        self._list()
        idx = self._pick_index(props, "Edit property #")
        if idx is None:
            return

        p = props[idx]
        raw_props = self._store.load_properties()
        _key      = (p.get("address",""), p.get("listing_date",""))
        raw_idx   = next(
            (i for i, r in enumerate(raw_props)
             if (r.get("address",""), r.get("listing_date","")) == _key),
            idx,
        )

        FIELDS = [
            ( 1, "Address",                    "address",          str,   None),
            ( 2, "MLS #",                      "mls_number",       str,   None),
            ( 3, "Status",                     "status",           str,   "status"),
            ( 4, "Original price",             "original_price",   int,   "nodec"),
            ( 5, "Asking price",               "asking_price",     int,   "nodec"),
            ( 6, "Property type",              "property_type",    str,   "proptype"),
            ( 7, "Commercial rent / year",     "commercial_rent",  float, "optional"),
            ( 8, "Floors",                     "floors",           int,   "floors"),
            ( 9, "Total sq ft",                "total_sq_ft",      int,   "nodec"),
            (10, "Bachelor units",             "bachelor",         int,   "unit"),
            (11, "1BR units",                  "one_br",           int,   "unit"),
            (12, "2BR units",                  "two_br",           int,   "unit"),
            (13, "3BR units",                  "three_br",         int,   "unit"),
            (14, "4BR units",                  "four_br",          int,   "unit"),
            (15, "Unknown residential units",  "unknown",          int,   "unit"),
            (16, "Residential rent / year",    "residential_rent", float, "optional"),
            (17, "Annual property taxes",      "property_taxes",   float, None),
            (18, "Construction cost",          "construction_cost",float, "optional"),
            (19, "Down payment %",             "down_payment_pct", float, "pct"),
            (20, "Interest rate %",            "interest_rate",    float, "pct"),
            (21, "Loan term (years)",          "term_years",       int,   None),
            (22, "Hold years",                 "hold_years",       int,   None),
            (23, "Expense ratio %",            "expense_ratio",    float, "pct"),
            (24, "Lease type (Normal/NNN)",    "lease_type",       str,   None),
            (25, "Listing date (YYYY-MM-DD)", "listing_date",     str,   "date"),
            (26, "Notes",                      "notes",            str,   "notes"),
            (27, "Hotel rooms",                "hotel_rooms",      int,   "hotel"),
            (28, "Hotel ADR ($/night)",        "hotel_adr",        float, "hotel"),
            (29, "Hotel occupancy %",          "hotel_occupancy",  float, "hotel_pct"),
            (30, "Industrial: warehouse sqft", "ind_warehouse_sqft", float, "optional"),
            (31, "Industrial: office sqft",    "ind_office_sqft",    float, "optional"),
            (32, "Industrial: yard sqft",      "ind_yard_sqft",      float, "optional"),
            (33, "Industrial: dock doors",     "ind_dock_doors",     int,   "hotel"),
            (34, "Industrial: drive-in doors", "ind_drive_in_doors", int,   "hotel"),
            (35, "Industrial: clear height ft","ind_clear_height_ft",float, "optional"),
            (36, "Industrial: office rate $/sqft","ind_office_rate", float, "optional"),
            (37, "Industrial: yard rate $/sqft",  "ind_yard_rate",   float, "optional"),
        ]

        def current_display(key, special):
            if special == "unit":
                mix = p.get("unit_mix") or {}
                val = mix.get(key, 0) if isinstance(mix, dict) else 0
            else:
                val = p.get(key)
            if val is None:
                return "—"
            if special in ("pct", "hotel_pct"):
                return f"{val * 100:.2f}%"
            if special == "hotel":
                return str(val) if val else "—"
            if special == "nodec":
                try:
                    return f"{int(val):,}"
                except (ValueError, TypeError):
                    return str(val)
            return str(val)

        while True:
            print(f"\n  Editing: {_display_address(p.get('address','')) or '—'}  [MLS: {p.get('mls_number','—')}]")
            created  = p.get("created_at",    p.get("listing_date", "—"))
            modified = p.get("last_modified", p.get("analyzed_on",  "—"))
            print(f"  Created: {created}   Last modified: {modified}")
            print(self.THIN_DIVIDER)
            for num, label, key, _, special in FIELDS:
                cur = current_display(key, special)
                print(f"  {num:>2}  {label:<30} (current: {cur})")
            print(f"   0  Done")
            print(self.THIN_DIVIDER)

            choice = input("  Field to edit (0 to finish): ").strip()
            if choice == "0":
                break

            match = next((f for f in FIELDS if str(f[0]) == choice), None)
            if not match:
                print("  Invalid — enter a number from the list.")
                continue

            num, label, key, cast, special = match
            cur = current_display(key, special)
            print(f"  Current: {cur}")

            if special == "status":
                while True:
                    raw = input(f"  New {label} (a=active / i=inactive): ").strip().lower()
                    resolved = {"a": "active", "i": "inactive"}.get(raw, raw)
                    if resolved in ("active", "inactive"):
                        self._store.update_property(raw_idx, {key: resolved, "last_modified": date.today().isoformat()})
                        p[key] = resolved
                        print(f"  Updated to: {resolved}")
                        break
                    elif raw == "":
                        print("  No change made.")
                        break
                    else:
                        print("  Invalid — enter 'a' or 'i'.")
                continue

            if special == "pct":
                raw = input(f"  New {label} (e.g. 20 or 0.20, Enter to skip): ").strip()
                if not raw:
                    print("  No change made.")
                    continue
                try:
                    val = float(raw)
                    val = val / 100 if val > 1 else val
                    self._store.update_property(raw_idx, {key: val, "last_modified": date.today().isoformat()})
                    p[key] = val
                    print(f"  Updated to {val * 100:.2f}%")
                except ValueError:
                    print("  Invalid number.")
                continue

            if special == "unit":
                raw = input(f"  New {label} (Enter to skip): ").strip()
                if not raw:
                    print("  No change made.")
                    continue
                try:
                    val = int(raw)
                    mix = p.get("unit_mix") or {}
                    mix[key] = val
                    self._store.update_property(raw_idx, {"unit_mix": mix})
                    p["unit_mix"] = mix
                    print(f"  Updated.")
                except ValueError:
                    print("  Invalid number.")
                continue

            if special == "optional":
                raw = input(f"  New {label} (Enter to clear): ").strip()
                try:
                    val = cast(raw) if raw else None
                except ValueError:
                    print("  Invalid number.")
                    continue
                update = {key: val}
                if key == "commercial_rent":
                    update["commercial_rent_user_entered"] = val is not None
                elif key == "residential_rent":
                    update["residential_rent_user_entered"] = val is not None
                self._store.update_property(raw_idx, update)
                p.update(update)
                print(f"  Updated to: {val if val is not None else '(cleared)'}")
                continue

            if key == "lease_type":
                while True:
                    raw = input(f"  New {label} (no=Normal / nn=NNN, Enter to skip): ").strip().lower()
                    if not raw:
                        print("  No change made.")
                        break
                    resolved_lt = {"no":"Normal","n":"Normal","normal":"Normal","nn":"NNN","nnn":"NNN"}.get(raw)
                    if resolved_lt:
                        self._store.update_property(raw_idx, {key: resolved_lt, "expense_ratio": None})
                        p[key] = resolved_lt
                        p["expense_ratio"] = None
                        print(f"  Updated to: {resolved_lt}")
                        break
                    print("  Invalid — enter 'no' for Normal or 'nn' for NNN.")
                continue

            if special == "nodec":
                raw = input(f"  New {label} (Enter to skip): ").strip()
                if not raw:
                    print("  No change made.")
                    continue
                try:
                    val = int(float(raw.replace(",", "")))
                    self._store.update_property(raw_idx, {key: val})
                    p[key] = val
                    print(f"  Updated to: {val:,}")
                except ValueError:
                    print(f"  Invalid number.")
                continue

            if special == "proptype":
                print("  o=Office  r=Retail  i=Industrial  m=Mixed-Use  re=Residential  mu=Multi-Family  h=Hotel  ro=Retail-Office")
                while True:
                    raw = input(f"  New {label} (Enter to skip): ").strip()
                    if not raw:
                        print("  No change made.")
                        break
                    resolved = self.PROP_SHORTCUTS.get(raw.lower()) or \
                               next((v for v in self.VALID_TYPES if v.lower() == raw.lower()), None)
                    if not resolved:
                        print(f"  Invalid — must be one of: {', '.join(sorted(self.VALID_TYPES))}.")
                        continue
                    self._store.update_property(raw_idx, {key: resolved, "expense_ratio": None, "vacancy_rate": None, "last_modified": date.today().isoformat()})
                    p[key] = resolved
                    p["expense_ratio"] = None
                    p["vacancy_rate"] = None
                    print(f"  Updated to: {resolved}")
                    break
                continue

            if special == "date":
                while True:
                    raw = input(f"  New {label} (YYYY-MM-DD, Enter to skip): ").strip()
                    if not raw:
                        print("  No change made.")
                        break
                    try:
                        date.fromisoformat(raw)
                        self._store.update_property(raw_idx, {key: raw, "last_modified": date.today().isoformat()})
                        p[key] = raw
                        print(f"  Updated to: {raw}")
                        break
                    except ValueError:
                        print("  Invalid date — use YYYY-MM-DD format (e.g. 2025-06-15).")
                continue

            if special == "notes":
                cur_notes = p.get("notes") or ""
                if cur_notes:
                    print(f"  Current notes:")
                    for line in cur_notes.splitlines():
                        print(f"    {line}")
                raw = input("  New notes (Enter to keep current, 'clear' to delete): ").strip()
                if raw.lower() == "clear":
                    self._store.update_property(raw_idx, {"notes": None, "last_modified": date.today().isoformat()})
                    p["notes"] = None
                    print("  Notes cleared.")
                elif raw:
                    self._store.update_property(raw_idx, {"notes": raw, "last_modified": date.today().isoformat()})
                    p["notes"] = raw
                    print("  Notes updated.")
                else:
                    print("  No change made.")
                continue

            if special == "floors":
                raw = input(f"  New {label} (Enter to skip): ").strip()
                if not raw:
                    print("  No change made.")
                    continue
                try:
                    val = int(raw)
                    mix = p.get("unit_mix") or {}
                    mix["floors"] = val
                    self._store.update_property(raw_idx, {"floors": val, "unit_mix": mix, "last_modified": date.today().isoformat()})
                    p["floors"] = val
                    p["unit_mix"] = mix
                    print(f"  Updated to: {val}")
                except ValueError:
                    print("  Invalid number.")
                continue

            if special == "hotel":
                raw = input(f"  New {label} (Enter to skip): ").strip()
                if not raw:
                    print("  No change made.")
                    continue
                try:
                    val = int(float(raw.replace(",", "")))
                    self._store.update_property(raw_idx, {key: val, "last_modified": date.today().isoformat()})
                    p[key] = val
                    print(f"  Updated to: {val}")
                except ValueError:
                    print("  Invalid number.")
                continue

            if special == "hotel_pct":
                raw = input(f"  New {label} (e.g. 65 for 65%, Enter to skip): ").strip()
                if not raw:
                    print("  No change made.")
                    continue
                try:
                    val = float(raw.replace("%", ""))
                    val = val / 100 if val > 1 else val
                    self._store.update_property(raw_idx, {key: val, "last_modified": date.today().isoformat()})
                    p[key] = val
                    print(f"  Updated to: {val*100:.1f}%")
                except ValueError:
                    print("  Invalid number.")
                continue

            # Standard fields
            raw = input(f"  New {label} (Enter to skip): ").strip()
            if not raw:
                print("  No change made.")
                continue
            try:
                val = cast(raw)
                self._store.update_property(raw_idx, {key: val})
                p[key] = val
                print(f"  Updated to: {val}")
            except ValueError:
                print(f"  Invalid value for {label}.")

        # Re-run analysis with updated record
        p = self._store.load_properties()[raw_idx]
        try:
            prop     = self._record_to_prop(p)
            analyzer = CommercialPropertyAnalyzer(prop, self._resolver)
            record   = analyzer.to_record(existing=p)
            self._store.update_property(raw_idx, record)
            if analyzer._has_rent:
                print(f"  Analysis updated (full).")
            else:
                city     = p.get("city",     "unknown city")
                province = p.get("province", "ON")
                ptype    = p.get("property_type")
                if ptype and ptype.lower() in COMMERCIAL_TYPES_LOWER:
                    print(f"  Partial analysis only — no commercial rent rates for {city}, {province}.")
                    print(f"  Use menu option 7 to add {city} commercial rates.")
                else:
                    print(f"  Partial analysis only — no residential rent rates for {city}, {province}.")
                    print(f"  Use menu option 8 to add {city} residential rates.")
        except ValueError as e:
            print(f"  Analysis could not be run: {e}")
        except Exception as e:
            print(f"  Unexpected error during analysis: {e}")
        print(f"  Edit complete.")

    def _delete(self):
        props = self._sorted_props()
        if not props:
            print("\n  No properties on file.")
            return
        self._list()
        idx = self._pick_index(props, "Delete property #")
        if idx is None:
            return
        p       = props[idx]
        addr    = _display_address(p.get("address", ""))
        confirm = input(f"  Delete '{addr}'? This cannot be undone. (y/n): ").strip().lower()
        if confirm in ("y", "yes"):
            raw_props = self._store.load_properties()
            key       = (p.get("address",""), p.get("listing_date",""))
            raw_idx   = next((i for i, r in enumerate(raw_props)
                              if (r.get("address",""), r.get("listing_date","")) == key), None)
            if raw_idx is not None:
                self._store.delete_property(raw_idx)
                print(f"  Deleted: {addr}")
            else:
                print("  Error: could not locate record.")
        else:
            print("  Cancelled.")

    # ── HTML Reports ──────────────────────────────────────────────────────

    def _open_report(self):
        props = self._store.load_properties()
        if not props:
            print("\n  No properties on file.")
            return
        print("  Building report", end="", flush=True)
        rows = []
        for p in props:
            scored  = self._scorer.score_property(p)
            targets = self._scorer.solve_targets(p, self._record_to_prop, CommercialPropertyAnalyzer, self._resolver)
            print(".", end="", flush=True)
            rows.append(self._build_report_row(p, scored, targets))
        print(" done.")
        self._prop_rpt.open_in_browser(rows)

    def _open_city_report(self):
        props = self._store.load_properties()
        if not props:
            print("\n  No properties on file.")
            return
        print("  Building city investment report", end="", flush=True)
        cities = self._ranker.rank(props)
        print(" done.")
        self._city_rpt.open_in_browser(cities)

    @staticmethod
    def _price_check_key(p: dict) -> str:
        """Checkpoint key for a property — address + listing date, matching the
        record identity used by DataStore.save_property."""
        return f"{p.get('address', '')}||{p.get('listing_date', '')}"

    def _price_check(self):
        """Look stored properties up on realtor.ca and report price changes.

        Drives a real Firefox browser (slow, and realtor.ca may rate-limit a
        large sweep), so it confirms before starting and checkpoints every result
        to disk — an interrupted run can be resumed instead of restarted. Read-only
        on properties.json; results go to an HTML report, nothing is written back.
        """
        props = self._store.load_properties()
        if not props:
            print("\n  No properties on file.")
            return

        key_of   = self._price_check_key
        progress = self._store.load_price_check_progress()

        # If a previous run exists, let the user resume / retry failures / restart.
        if progress:
            done   = sum(1 for p in props if key_of(p) in progress)
            failed = sum(1 for p in props
                         if progress.get(key_of(p), {}).get("status") == "error")
            print(f"\n  A previous run is saved: {done}/{len(props)} checked "
                  f"({failed} not checked).")
            print("    r  Resume   — check only properties not done yet")
            print("    f  Retry    — re-check only the 'not checked' failures")
            print("    s  Start fresh — discard the previous run")
            sel = input("  Choose (r/f/s, Enter to cancel): ").strip().lower()
            if sel == "r":
                todo = [p for p in props if key_of(p) not in progress]
            elif sel == "f":
                todo = [p for p in props
                        if progress.get(key_of(p), {}).get("status") == "error"]
            elif sel == "s":
                self._store.clear_price_check_progress()
                progress = {}
                todo = list(props)
            else:
                print("  Cancelled.")
                return
        else:
            todo = list(props)

        if todo:
            raw = input(f"  How many to check this run? ({len(todo)} pending, "
                        "Enter = all): ").strip()
            if raw.isdigit() and int(raw) > 0:
                todo = todo[:int(raw)]

            print(f"\n  This opens a browser and checks {len(todo)} listings on "
                  "realtor.ca one\n  by one. It can take a long time and may be "
                  "rate-limited. Progress is\n  saved after each — Ctrl-C to stop "
                  "and resume later.")
            if input("  Continue? (y/N): ").strip().lower() != "y":
                print("  Cancelled.")
                return

            try:
                with RealtorScraper() as scraper:
                    # Warm-up: let the user clear any Akamai/CAPTCHA challenge by
                    # hand once; the persistent profile carries it for the batch.
                    print("\n  Opening realtor.ca in the browser window...")
                    if scraper.open_home():
                        input("  realtor.ca is challenging the browser. In the "
                              "window, solve any\n  CAPTCHA / 'Access Denied' page "
                              "and accept cookies, then press Enter\n  to continue "
                              "(or Enter anyway to try): ")
                    print("  Checking", end="", flush=True)
                    for p in todo:
                        address  = p.get("address", "")
                        city     = p.get("city") or ""
                        province = p.get("province") or ""
                        result   = scraper.fetch_price(address, city, province)
                        row      = compare(p.get("asking_price"), result)
                        row.update({
                            "address":  address or "—",
                            "city":     city,
                            "province": province,
                            "mls":      p.get("mls_number", ""),
                        })
                        self._store.save_price_check_result(key_of(p), row)
                        progress[key_of(p)] = row
                        print(".", end="", flush=True)
            except KeyboardInterrupt:
                print("\n  Stopped. Progress saved — choose Resume next time.")
            except Exception as exc:
                print(f"\n  Browser error: {exc}")
                print("  Is Playwright installed?  pip install playwright && "
                      "python -m playwright install firefox")
            else:
                print(" done.")
        else:
            print("  Nothing left to check.")

        # Report over everything checked so far (this run plus any prior runs).
        rows = [progress[key_of(p)] for p in props if key_of(p) in progress]
        if not rows:
            print("  No results to report yet.")
            return
        PriceCheckReportGenerator().open_in_browser(rows)

        if all(key_of(p) in progress for p in props):
            if input("  All properties checked. Clear saved progress? "
                     "(y/N): ").strip().lower() == "y":
                self._store.clear_price_check_progress()
                print("  Progress cleared.")

    @staticmethod
    def _build_report_row(p: dict, scored: dict, targets: dict) -> dict:
        return {
            "address":      p.get("address", "—"),
            "mls":          p.get("mls_number", "—"),
            "status":       p.get("status", "—"),
            "city":         p.get("city") or "",
            "province":     p.get("province") or "",
            "type":         p.get("property_type") or "—",
            "asking":       p.get("asking_price", 0),
            "sqft":         p.get("total_sq_ft", 0),
            "listed":       p.get("listing_date", "—"),
            "analyzed":     p.get("analyzed_on") or "—",
            "notes":        p.get("notes") or "",
            "construction": p.get("construction_cost") or 0,
            "dist_km":      scored.get("dist_km"),
            "dist_centre":  scored.get("dist_centre") or "",
            "comm_rent":    p.get("commercial_rent") or 0,
            "res_rent":     p.get("residential_rent") or 0,
            "score":        scored.get("score"),
            "breakdown":    scored.get("breakdown", {}),
            "weights":      scored.get("weights", {}),
            "cap_rate":     scored.get("cap_rate", 0),
            "coc":          scored.get("coc", 0),
            "dscr":         scored.get("dscr", 0),
            "irr":          scored.get("irr", 0),
            "em":           scored.get("em", 0),
            "cf_annual":    scored.get("cf_annual", 0),
            "price_drop":   scored.get("price_drop", 0),
            "dom":          scored.get("dom", 0),
            "original":     p.get("original_price", 0),
            "taxes":        p.get("property_taxes", 0),
            "down_pct":     p.get("down_payment_pct", 0),
            "rate":         p.get("interest_rate", 0),
            "term":         p.get("term_years", 0),
            "hold":         p.get("hold_years", 0),
            "expense_ratio":p.get("expense_ratio", 0),
            "lease_type":   p.get("lease_type", ""),
            "results":      p.get("results", []),
            "income_confidence": p.get("income_confidence"),
            "income_size_band":  p.get("income_size_band"),
            "targets":      targets,
            "hotel_rooms":  p.get("hotel_rooms", 0) or 0,
            "hotel_adr":    p.get("hotel_adr") or 0,
            "hotel_occ":    p.get("hotel_occupancy") or 0,
            "rent_breakdown": p.get("rent_breakdown", []),
        }

    # ── Bulk re-analysis ──────────────────────────────────────────────────

    def _reanalyze_all(self):
        props = self._store.load_properties()
        if not props:
            print("\n  No properties on file.")
            return
        updated = skipped = errors = 0
        for i, p in enumerate(props):
            try:
                prop     = self._record_to_prop(p)
                analyzer = CommercialPropertyAnalyzer(prop, self._resolver)
                record   = analyzer.to_record(existing=p)
                if p.get("notes"):
                    record["notes"] = p["notes"]
                self._store.update_property(i, record)
                updated += 1
            except ValueError:
                skipped += 1
            except Exception:
                errors += 1
        total = len(props)
        print(f"\n  Re-analysis complete — {updated}/{total} updated", end="")
        if skipped: print(f", {skipped} skipped (missing rates)", end="")
        if errors:  print(f", {errors} errors", end="")
        print(".")

    def _reanalyze_city(self, city: str, province: str):
        props   = self._store.load_properties()
        updated = 0
        for i, p in enumerate(props):
            if (p.get("city","").lower() != city.lower() or
                    p.get("province","").upper() != province.upper()):
                continue
            try:
                prop     = self._record_to_prop(p)
                analyzer = CommercialPropertyAnalyzer(prop, self._resolver)
                record   = analyzer.to_record(existing=p)
                self._store.update_property(i, record)
                updated += 1
            except Exception:
                pass
        if updated:
            print(f"  ✓ Re-analyzed {updated} propert{'y' if updated == 1 else 'ies'} in {city}, {province}.")

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _sort_key(p):
        city    = p.get("city")
        addr    = p.get("address") or ""
        st_name, st_num = _parse_address_sort(addr)
        if city:
            return (0, city.lower(), st_name, st_num)
        return (1, st_name, st_num, "")

    def _sorted_props(self) -> list:
        return sorted(self._store.load_properties(), key=self._sort_key)

    def _pick_index(self, sorted_props: list, prompt: str):
        try:
            n = int(input(f"  {prompt} (1-{len(sorted_props)}): ").strip())
            if 1 <= n <= len(sorted_props):
                return n - 1
            print("  Number out of range.")
            return None
        except (ValueError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return None

    def _prompt_property(self) -> PropertyInput:
        def ask(label, cast=str, default=None, optional=False):
            parts = [f"  {label}"]
            if optional:
                parts.append(" (optional, Enter to skip)")
            if default is not None:
                parts.append(f" [{default}]")
            parts.append(": ")
            raw = input("".join(parts)).strip()
            if not raw:
                if default is not None:
                    return default
                if optional:
                    return None
            return cast(raw) if raw else None

        def ask_pct(label, default_pct):
            raw = ask(label, float, default_pct)
            return raw / 100 if raw > 1 else raw

        print()
        while True:
            address = ask("Address")
            city, province = _parse_city_province(address)
            if city:
                break
            print("  ⚠  Could not parse city from that address.")
            print("     Expected: '123 Main St, Ottawa ON'  or  '123 Main St, Ottawa, ON'")
            print("     Please re-enter.")

        while True:
            _op_raw = input("  Original price (required): ").strip()
            if not _op_raw:
                print("  Required — enter the original listing price.")
                continue
            try:
                original_price = int(float(_op_raw.replace(",", "")))
                break
            except ValueError:
                print("  Invalid number.")

        while True:
            mls_number = input("  MLS # (required): ").strip()
            if not mls_number:
                print("  Required — enter the MLS number.")
                continue
            break

        while True:
            status_raw = input("  Status (a=active / i=inactive): ").strip().lower()
            resolved   = {"a":"active","i":"inactive"}.get(status_raw, status_raw)
            if resolved in ("active","inactive"):
                status = resolved
                break
            print("  Invalid — enter 'a' or 'i'.")

        print("  Property type:  o=Office  r=Retail  i=Industrial  m=Mixed-Use  re=Residential  mu=Multi-Family  h=Hotel  ro=Retail-Office")
        while True:
            _pt_raw = input("  Property type: ").strip()
            if not _pt_raw:
                print("  Required — enter a type or shorthand.")
                continue
            _resolved = self.PROP_SHORTCUTS.get(_pt_raw.lower()) or \
                        next((v for v in self.VALID_TYPES if v.lower() == _pt_raw.lower()), None)
            if not _resolved:
                print(f"  Invalid — must be one of: {', '.join(sorted(self.VALID_TYPES))}.")
                continue
            property_type_raw = _resolved
            break

        is_commercial_type = property_type_raw.strip().lower() in COMMERCIAL_TYPES_LOWER
        commercial_rent    = ask("Commercial rent income / year", float, optional=True)
        floors             = ask("Floors", int, 1)
        while True:
            _sqft_raw = input("  Total sq ft [5000]: ").strip()
            if not _sqft_raw:
                total_sq_ft = 5000
                break
            try:
                total_sq_ft = int(float(_sqft_raw.replace(",", "")))
                break
            except ValueError:
                print("  Invalid number.")
        bachelor           = ask("Bachelor units", int, 0)
        one_br             = ask("1BR units",      int, 0)
        two_br             = ask("2BR units",      int, 0)
        three_br           = ask("3BR units",      int, 0)
        four_br            = ask("4BR units",      int, 0)
        unknown            = ask("Unknown residential units", int, 0)
        total_units        = bachelor + one_br + two_br + three_br + four_br + unknown
        residential_rent   = ask("Residential rent income / year", float, optional=True) if total_units > 0 else None
        while True:
            _tax_raw = input("  Annual property taxes: ").strip()
            if not _tax_raw:
                print("  Required — enter the annual property tax amount.")
                continue
            try:
                property_taxes = float(_tax_raw.replace(",", ""))
                break
            except ValueError:
                print("  Invalid number.")
        construction_cost  = ask("Construction cost (renos/build-out)", float, optional=True) or 0.0
        down_payment_pct   = ask_pct("Down payment %", 20)
        interest_rate      = ask_pct("Interest rate %", 4.5)
        term_years         = ask("Loan term (years)", int, 25)
        hold_years         = ask("Hold years", int, 30)
        while True:
            _lt_raw = input("  Lease type (no=Normal / nn=NNN) [Normal]: ").strip().lower()
            if not _lt_raw:
                lease_type = "Normal"
                break
            resolved_lt = {"no":"Normal","n":"Normal","normal":"Normal","nn":"NNN","nnn":"NNN"}.get(_lt_raw)
            if resolved_lt:
                lease_type = resolved_lt
                break
            print("  Invalid — enter 'no' for Normal or 'nn' for NNN.")

        _ld_raw = input(f"  Listing date [YYYY-MM-DD, Enter for today ({date.today().isoformat()})]: ")
        listing_date = _parse_listing_date(_ld_raw)
        hotel_rooms     = 0
        hotel_adr       = None
        hotel_occupancy = None
        if property_type_raw.strip().lower() == "hotel":
            print("  ── Hotel Details ──")
            while True:
                _rooms_raw = input("  Number of rooms [0]: ").strip()
                if not _rooms_raw:
                    hotel_rooms = 0
                    break
                try:
                    hotel_rooms = int(_rooms_raw)
                    break
                except ValueError:
                    print("  Invalid number.")
            _adr = input("  Average Daily Rate / room (ADR $, Enter to skip): ").strip()
            if _adr:
                try:
                    hotel_adr = float(_adr.replace(",","").replace("$",""))
                except ValueError:
                    pass
            _occ = input("  Target occupancy % (e.g. 65, Enter to skip): ").strip()
            if _occ:
                try:
                    v = float(_occ.replace("%",""))
                    hotel_occupancy = v / 100 if v > 1 else v
                except ValueError:
                    pass

        ind_warehouse_sqft = ind_office_sqft = ind_yard_sqft = 0.0
        ind_dock_doors = ind_drive_in_doors  = 0
        ind_clear_height_ft = 0.0
        ind_office_rate = ind_yard_rate = None
        if property_type_raw.strip().lower() == "industrial":
            print("  ── Industrial Details (Enter to skip any field) ──")
            _v = ask("Warehouse/storage sq ft",   float, optional=True)
            if _v: ind_warehouse_sqft = _v
            _v = ask("Office component sq ft",    float, optional=True)
            if _v: ind_office_sqft = _v
            _v = ask("Yard/outdoor storage sq ft", float, optional=True)
            if _v: ind_yard_sqft = _v
            _v = ask("Dock-level doors (count)",   int,   optional=True)
            if _v: ind_dock_doors = int(_v)
            _v = ask("Drive-in doors (count)",     int,   optional=True)
            if _v: ind_drive_in_doors = int(_v)
            _v = ask("Clear ceiling height (ft)",  float, optional=True)
            if _v: ind_clear_height_ft = _v
            _raw = input("  Office component rate $/sqft/yr (Enter to use 140% of base): ").strip()
            if _raw:
                try: ind_office_rate = float(_raw)
                except ValueError: pass
            _raw = input("  Yard rate $/sqft/yr (Enter to use 15% of base): ").strip()
            if _raw:
                try: ind_yard_rate = float(_raw)
                except ValueError: pass

        has_units = total_units > 0
        unit_mix  = None
        if has_units:
            unit_mix = UnitMix(
                bachelor=bachelor, one_br=one_br, two_br=two_br,
                three_br=three_br, four_br=four_br, unknown=unknown,
                floors=floors,
            )
        else:
            unit_mix = UnitMix(floors=floors)

        return PropertyInput(
            address=address, mls_number=mls_number, status=status,
            original_price=original_price, asking_price=original_price,
            total_sq_ft=total_sq_ft, property_taxes=property_taxes,
            down_payment_pct=down_payment_pct, interest_rate=interest_rate,
            term_years=term_years, expense_ratio=None, lease_type=lease_type,
            listing_date=listing_date, hold_years=hold_years,
            annual_rent=None, commercial_rent=commercial_rent,
            residential_rent=residential_rent,
            commercial_rent_user_entered=bool(commercial_rent),
            residential_rent_user_entered=bool(residential_rent),
            city=city, province=province,
            property_type=property_type_raw, unit_mix=unit_mix,
            construction_cost=construction_cost,
            hotel_rooms=hotel_rooms, hotel_adr=hotel_adr, hotel_occupancy=hotel_occupancy,
            ind_warehouse_sqft=ind_warehouse_sqft, ind_office_sqft=ind_office_sqft,
            ind_yard_sqft=ind_yard_sqft, ind_dock_doors=ind_dock_doors,
            ind_drive_in_doors=ind_drive_in_doors, ind_clear_height_ft=ind_clear_height_ft,
            ind_office_rate=ind_office_rate, ind_yard_rate=ind_yard_rate,
        )

    @staticmethod
    def _record_to_prop(p: dict) -> PropertyInput:
        um_data   = p.get("unit_mix") or {}
        has_units = any(um_data.get(k, 0) for k in
                        ("bachelor","one_br","two_br","three_br","four_br","unknown"))
        if has_units:
            unit_mix = UnitMix(
                bachelor  = um_data.get("bachelor",  0),
                one_br    = um_data.get("one_br",    0),
                two_br    = um_data.get("two_br",    0),
                three_br  = um_data.get("three_br",  0),
                four_br   = um_data.get("four_br",   0),
                unknown   = um_data.get("unknown",   0),
                floors    = um_data.get("floors",    p.get("floors", 1)),
            )
        else:
            unit_mix = UnitMix(floors=um_data.get("floors", p.get("floors", 1)))
        return PropertyInput(
            address          = p["address"],
            mls_number       = p.get("mls_number", ""),
            status           = p.get("status", "active"),
            original_price   = p.get("original_price", p.get("asking_price", 0)),
            asking_price     = p.get("asking_price", 0),
            total_sq_ft      = p.get("total_sq_ft", 0),
            property_taxes   = p.get("property_taxes", 0),
            down_payment_pct = p.get("down_payment_pct", 0.20),
            interest_rate    = p.get("interest_rate",    0.045),
            term_years       = p.get("term_years",       25),
            hold_years       = p.get("hold_years",       30),
            expense_ratio    = p.get("expense_ratio",    None),
            lease_type       = p.get("lease_type",       "Normal"),
            construction_cost = p.get("construction_cost", 0) or 0,
            listing_date     = p.get("listing_date",     date.today().isoformat()),
            commercial_rent  = p.get("commercial_rent") or None,
            residential_rent = p.get("residential_rent") or None,
            annual_rent      = (p.get("annual_rent") or None) if not (
                p.get("commercial_rent") or p.get("residential_rent")
            ) else None,
            city             = p.get("city"),
            province         = p.get("province"),
            property_type    = p.get("property_type"),
            unit_mix         = unit_mix,
            hotel_rooms      = p.get("hotel_rooms", 0) or 0,
            hotel_adr        = p.get("hotel_adr"),
            hotel_occupancy  = p.get("hotel_occupancy"),
            ind_warehouse_sqft  = p.get("ind_warehouse_sqft",  0) or 0,
            ind_office_sqft     = p.get("ind_office_sqft",     0) or 0,
            ind_yard_sqft       = p.get("ind_yard_sqft",       0) or 0,
            ind_dock_doors      = p.get("ind_dock_doors",      0) or 0,
            ind_drive_in_doors  = p.get("ind_drive_in_doors",  0) or 0,
            ind_clear_height_ft = p.get("ind_clear_height_ft", 0) or 0,
            ind_office_rate     = p.get("ind_office_rate"),
            ind_yard_rate          = p.get("ind_yard_rate"),
            vacancy_rate           = p.get("vacancy_rate"),
            noi_growth_rate        = p.get("noi_growth_rate"),
            commercial_rent_user_entered  = p.get("commercial_rent_user_entered",
                                               p.get("rent_manually_entered", False)),
            residential_rent_user_entered = p.get("residential_rent_user_entered",
                                               p.get("rent_manually_entered", False)),
        )
