"""CSV import/export mixin for PropertyMenu."""
import csv as _csv
import os
from datetime import date

from models.property_input import PropertyInput, UnitMix
from analysis.analyzer import CommercialPropertyAnalyzer, build_partial_record


class CsvHandlerMixin:
    """Mix-in providing CSV import and template-export methods for PropertyMenu."""

    def _import_csv(self):
        print(f"\n  CSV IMPORT")
        print(self.THIN_DIVIDER)
        print("  Enter path to CSV file, or 'template' to save a sample CSV:")
        path = input("  > ").strip()
        if path.lower() == "template":
            self._save_csv_template()
            return
        if not path:
            print("  Cancelled.")
            return
        if not os.path.exists(path):
            print(f"  File not found: {path}")
            return
        rows = None
        enc  = None
        tried = []
        for enc in ("utf-8", "utf-8-sig", "cp1252", "iso-8859-1", "latin-1"):
            tried.append(enc)
            try:
                with open(path, newline="", encoding=enc) as f:
                    reader = _csv.DictReader(f)
                    rows = list(reader)
                break
            except UnicodeDecodeError:
                continue
            except Exception as e:
                print(f"  Could not read file: {e}")
                return
        if rows is None:
            print(f"  Could not decode file (tried: {', '.join(tried)}).")
            return
        if not rows:
            print("  File is empty.")
            return

        EXPECTED_HEADERS = [
            "address", "mls_number", "status", "original_price", "property_type",
            "commercial_rent", "floors", "total_sq_ft",
            "bachelor", "one_br", "two_br", "three_br", "four_br", "unknown",
            "residential_rent", "property_taxes", "down_payment_pct",
            "interest_rate", "term_years", "hold_years", "expense_ratio", "lease_type",
            "hotel_rooms", "hotel_adr", "hotel_occupancy",
            "ind_warehouse_sqft", "ind_office_sqft", "ind_yard_sqft",
            "ind_dock_doors", "ind_drive_in_doors", "ind_clear_height_ft",
            "ind_office_rate", "ind_yard_rate",
        ]
        first_keys = [k.strip().lower() for k in rows[0].keys()]
        has_header = "address" in first_keys
        if not has_header:
            with open(path, newline="", encoding=enc) as f:
                plain_rows = list(_csv.reader(f))
            rows = []
            for r in plain_rows:
                padded = r + [""] * (len(EXPECTED_HEADERS) - len(r))
                rows.append(dict(zip(EXPECTED_HEADERS, padded[:len(EXPECTED_HEADERS)])))
            print(f"  No header row detected — using default column order ({len(rows)} rows).")

        def cell(row, key, default=None):
            val = row.get(key, "").strip()
            return val if val else default

        def to_int(row, key, default=0):
            try:
                return int(float(cell(row, key, default)))
            except (TypeError, ValueError):
                return default

        def to_float(row, key, default=None):
            try:
                v = cell(row, key)
                return float(v) if v else default
            except ValueError:
                return default

        def to_pct(row, key, default_pct):
            v = to_float(row, key)
            if v is None:
                return default_pct / 100
            return v / 100 if v > 1 else v

        PROVINCES = {"AB","BC","MB","NB","NL","NS","NT","NU","ON","PE","QC","SK","YT"}
        COMMERCIAL_TYPES = {"office", "retail", "industrial", "mixed-use", "retail-office", "hotel"}

        def parse_city_province(addr):
            if not addr:
                return None, None
            parts = [p.strip() for p in addr.split(",")]
            last  = parts[-1].strip()
            if last.upper() in PROVINCES:
                return (parts[-2].strip() if len(parts) >= 2 else None), last.upper()
            tokens = last.split()
            if tokens and tokens[-1].upper() in PROVINCES:
                province = tokens[-1].upper()
                city     = " ".join(tokens[:-1]).strip() or None
                return city, province
            dot_idx = addr.rfind(". ")
            if dot_idx != -1:
                candidate = addr[dot_idx + 2:].strip()
                if candidate:
                    c_tokens = candidate.split()
                    if c_tokens and c_tokens[-1].upper() in PROVINCES:
                        province = c_tokens[-1].upper()
                        city     = " ".join(c_tokens[:-1]).strip() or None
                        return city, province
                    return candidate, None
            city = last if last else None
            return city, None

        saved = 0
        errors = []

        for row_num, row in enumerate(rows, start=2):
            try:
                address = cell(row, "address", "")
                if not address:
                    errors.append(f"  Row {row_num}: missing address — skipped")
                    continue
                mls = cell(row, "mls_number", "")
                if not mls:
                    errors.append(f"  Row {row_num} ({address}): missing MLS # — skipped")
                    continue
                status_raw = cell(row, "status", "active").lower()
                status = {"a":"active","i":"inactive"}.get(status_raw, status_raw)
                if status not in ("active","inactive"):
                    status = "active"
                original_price = to_float(row, "original_price")
                if original_price is None:
                    errors.append(f"  Row {row_num} ({address}): missing original_price — skipped")
                    continue
                property_type_raw = cell(row, "property_type", "")
                is_commercial     = property_type_raw.strip().lower() in COMMERCIAL_TYPES
                prop_type_field   = property_type_raw if is_commercial else None
                city, province    = parse_city_province(address)
                if province is None:
                    province = "ON"
                commercial_rent = to_float(row, "commercial_rent")
                floors          = to_int(row, "floors", 1)
                total_sq_ft     = to_float(row, "total_sq_ft")
                if not total_sq_ft:
                    errors.append(f"  Row {row_num} ({address}): missing total_sq_ft — skipped")
                    continue
                bachelor = to_int(row, "bachelor", 0)
                one_br   = to_int(row, "one_br",   0)
                two_br   = to_int(row, "two_br",   0)
                three_br = to_int(row, "three_br", 0)
                four_br  = to_int(row, "four_br",  0)
                unknown  = to_int(row, "unknown",  0)
                total_units      = bachelor + one_br + two_br + three_br + four_br + unknown
                residential_rent = to_float(row, "residential_rent")
                construction_cost = to_float(row, "construction_cost", 0)
                hotel_rooms     = int(to_float(row, "hotel_rooms", 0) or 0)
                _hotel_adr      = to_float(row, "hotel_adr")
                hotel_adr       = _hotel_adr if _hotel_adr else None
                _occ            = to_float(row, "hotel_occupancy")
                hotel_occupancy = (_occ / 100 if _occ and _occ > 1 else _occ) if _occ else None
                ind_warehouse_sqft  = to_float(row, "ind_warehouse_sqft")  or 0.0
                ind_office_sqft     = to_float(row, "ind_office_sqft")     or 0.0
                ind_yard_sqft       = to_float(row, "ind_yard_sqft")       or 0.0
                ind_dock_doors      = int(to_float(row, "ind_dock_doors")  or 0)
                ind_drive_in_doors  = int(to_float(row, "ind_drive_in_doors") or 0)
                ind_clear_height_ft = to_float(row, "ind_clear_height_ft") or 0.0
                ind_office_rate     = to_float(row, "ind_office_rate")     or None
                ind_yard_rate       = to_float(row, "ind_yard_rate")       or None
                property_taxes   = to_float(row, "property_taxes", 0)
                down_payment_pct = to_pct(row, "down_payment_pct", 20)
                interest_rate    = to_pct(row, "interest_rate",    4.5)
                term_years       = to_int(row, "term_years",  25)
                hold_years       = to_int(row, "hold_years",  30)
                _er_raw = to_float(row, "expense_ratio")
                expense_ratio = (_er_raw / 100 if _er_raw > 1 else _er_raw) if _er_raw is not None else None
                lease_type_raw   = cell(row, "lease_type", "Normal").lower()
                lease_type = {"no":"Normal","n":"Normal","normal":"Normal","nn":"NNN","nnn":"NNN"}.get(lease_type_raw, "Normal")
                has_units = total_units > 0
                unit_mix  = None
                if has_units:
                    unit_mix = UnitMix(
                        bachelor=bachelor, one_br=one_br, two_br=two_br,
                        three_br=three_br, four_br=four_br, unknown=unknown,
                        floors=floors,
                    )
                    if is_commercial:
                        prop_type_field = property_type_raw
                if unit_mix is None:
                    unit_mix = UnitMix(floors=floors)
                prop = PropertyInput(
                    address=address, mls_number=mls, status=status,
                    original_price=int(original_price), asking_price=int(original_price),
                    total_sq_ft=int(total_sq_ft), property_taxes=property_taxes or 0,
                    down_payment_pct=down_payment_pct, interest_rate=interest_rate,
                    term_years=term_years, hold_years=hold_years,
                    expense_ratio=expense_ratio, lease_type=lease_type,
                    listing_date=date.today().isoformat(), annual_rent=None,
                    commercial_rent=commercial_rent or None,
                    residential_rent=residential_rent or None,
                    commercial_rent_user_entered=bool(commercial_rent),
                    residential_rent_user_entered=bool(residential_rent),
                    city=city, province=province, property_type=prop_type_field,
                    unit_mix=unit_mix, construction_cost=construction_cost,
                    hotel_rooms=hotel_rooms, hotel_adr=hotel_adr, hotel_occupancy=hotel_occupancy,
                    ind_warehouse_sqft=ind_warehouse_sqft, ind_office_sqft=ind_office_sqft,
                    ind_yard_sqft=ind_yard_sqft, ind_dock_doors=ind_dock_doors,
                    ind_drive_in_doors=ind_drive_in_doors, ind_clear_height_ft=ind_clear_height_ft,
                    ind_office_rate=ind_office_rate, ind_yard_rate=ind_yard_rate,
                )
                try:
                    analyzer = CommercialPropertyAnalyzer(prop, self._resolver)
                    self._store.save_property(analyzer.to_record())
                    if city and province:
                        self._store.ensure_city_in_rates(city, province)
                    saved += 1
                    print(f"  ✓ Imported: {address} [{mls}]")
                except ValueError as e:
                    self._store.save_property(build_partial_record(prop))
                    if city and province:
                        self._store.ensure_city_in_rates(city, province)
                    saved += 1
                    print(f"  ✓ Imported (no analysis): {address} [{mls}] — {e}")
            except Exception as e:
                errors.append(f"  Row {row_num} ({row.get('address','?')}): {e}")

        print(f"\n  Done — {saved} imported, {len(errors)} skipped.")
        if errors:
            print("  Issues:")
            for e in errors:
                print(e)

    def _save_csv_template(self):
        path = "property_import_template.csv"
        headers = [
            "address", "mls_number", "status", "original_price", "property_type",
            "commercial_rent", "floors", "total_sq_ft",
            "bachelor", "one_br", "two_br", "three_br", "four_br", "unknown",
            "residential_rent", "property_taxes", "down_payment_pct",
            "interest_rate", "term_years", "hold_years", "expense_ratio", "lease_type",
            "hotel_rooms", "hotel_adr", "hotel_occupancy",
        ]
        placeholder = [
            "123 Example St, City, ON", "MLS-XXX", "active", "500000", "Retail",
            "", "1", "3000", "0", "0", "0", "0", "0", "0",
            "", "6000", "20", "4.5", "25", "30", "40", "Normal",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(headers)
            w.writerow(placeholder)
        print(f"  Template saved to: {path}")
