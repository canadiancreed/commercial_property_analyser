"""Rate editor mixin — commercial and residential rent rate management."""


class RateEditorMixin:
    """Mix-in providing commercial/residential rate editing methods for PropertyMenu."""

    def _edit_commercial_rates(self):
        try:
            raw = self._store._read(self._store._commercial_path)
        except FileNotFoundError:
            print("\n  No commercial rent data file found — add rates via option 7 after saving a property first.")
            return
        cities = sorted(raw["cities"].keys(), key=str.lower)
        if not cities:
            print("\n  No commercial rate data found.")
            return
        COMM_TYPES = ["Office", "Retail", "Industrial", "Mixed-Use"]
        col_n = 3; col_city = 20; col_prov = 4; col_rate = 12
        header  = f"  {'#':<{col_n}} {'CITY':<{col_city}} {'PROV':<{col_prov}}" + \
                  "".join(f"  {t:>{col_rate}}" for t in COMM_TYPES)
        divider = "-" * len(header)
        print(f"\n{'COMMERCIAL RENT RATES ($/sq ft/yr)':^{len(header)}}")
        print(divider); print(header); print(divider)
        for i, c in enumerate(cities, 1):
            d = raw["cities"][c]
            row = f"  {i:<{col_n}} {c:<{col_city}} {d['province']:<{col_prov}}"
            for t in COMM_TYPES:
                val  = d["types"].get(t)
                cell = f"${val}" if val is not None else "—"
                row += f"  {cell:>{col_rate}}"
            print(row)
        print(divider)
        print(f"  {'N':<{col_n}} {'Add new city':}")
        print()
        choice = input("  Select city to edit, or N to add: ").strip()
        if choice.lower() == "n":
            city     = input("  City name: ").strip()
            province = input("  Province: ").strip().upper()
            self._enter_commercial_rates(city, province)
            return
        try:
            idx = int(choice) - 1
            if not (0 <= idx < len(cities)):
                print("  Invalid."); return
        except ValueError:
            print("  Invalid."); return
        city_name    = cities[idx]
        city_data    = raw["cities"][city_name]
        province     = city_data["province"]
        current_types = city_data["types"]
        print(f"\n  Editing: {city_name}, {province}")
        print(self.THIN_DIVIDER)
        for i, t in enumerate(COMM_TYPES, 1):
            cur = current_types.get(t, "—")
            print(f"  {i}  {t:<14} (current: ${cur}/sq ft)")
        print("  0  Done")
        updated = dict(current_types)
        while True:
            c = input("  Field to edit (0 done): ").strip()
            if c == "0":
                break
            try:
                fi = int(c) - 1
                if not (0 <= fi < len(COMM_TYPES)):
                    print("  Invalid."); continue
            except ValueError:
                print("  Invalid."); continue
            t       = COMM_TYPES[fi]
            raw_val = input(f"  New rate for {t} ($/sq ft/yr): ").strip()
            if not raw_val:
                continue
            try:
                updated[t] = float(raw_val)
                print(f"  Set {t} = ${updated[t]}/sq ft")
            except ValueError:
                print("  Invalid number.")
        self._store.save_commercial_city(city_name, province, updated)
        print(f"  Saved commercial rates for {city_name}, {province}.")
        self._reanalyze_city(city_name, province)

    def _edit_residential_rates(self):
        try:
            raw = self._store._read(self._store._residential_path)
        except FileNotFoundError:
            print("\n  No residential rent data file found — add rates via option 8 after saving a property first.")
            return
        cities = sorted(raw["cities"].keys(), key=str.lower)
        if not cities:
            print("\n  No residential rate data found.")
            return
        RES_FIELDS  = [("bachelor","Bachelor"),("one_br","1BR"),("two_br","2BR"),
                       ("three_br","3BR"),("four_br","4BR"),("unknown","Unknown")]
        RES_LABELS  = [("bachelor","Bach"),("one_br","1BR"),("two_br","2BR"),
                       ("three_br","3BR"),("four_br","4BR"),("unknown","Unk")]
        col_n = 3; col_city = 20; col_prov = 4; col_rate = 8
        header  = f"  {'#':<{col_n}} {'CITY':<{col_city}} {'PROV':<{col_prov}}" + \
                  "".join(f"  {lbl:>{col_rate}}" for _, lbl in RES_LABELS)
        divider = "-" * len(header)
        print(f"\n{'RESIDENTIAL RENT RATES ($/mo)':^{len(header)}}")
        print(divider); print(header); print(divider)
        for i, c in enumerate(cities, 1):
            d   = raw["cities"][c]
            row = f"  {i:<{col_n}} {c:<{col_city}} {d['province']:<{col_prov}}"
            for key, _ in RES_LABELS:
                val  = d["units"].get(key)
                cell = f"${int(val)}" if val is not None else "—"
                row += f"  {cell:>{col_rate}}"
            print(row)
        print(divider)
        print(f"  {'N':<{col_n}} {'Add new city':}")
        print()
        choice = input("  Select city to edit, or N to add: ").strip()
        if choice.lower() == "n":
            city     = input("  City name: ").strip()
            province = input("  Province: ").strip().upper()
            self._enter_residential_rates(city, province)
            return
        try:
            idx = int(choice) - 1
            if not (0 <= idx < len(cities)):
                print("  Invalid."); return
        except ValueError:
            print("  Invalid."); return
        city_name = cities[idx]
        city_data = raw["cities"][city_name]
        province  = city_data["province"]
        current   = city_data["units"]
        print(f"\n  Editing: {city_name}, {province}")
        print(self.THIN_DIVIDER)
        for i, (key, label) in enumerate(RES_FIELDS, 1):
            cur = current.get(key, "—")
            print(f"  {i}  {label:<12} (current: ${cur}/mo)")
        print("  0  Done")
        updated = dict(current)
        while True:
            c = input("  Field to edit (0 done): ").strip()
            if c == "0":
                break
            try:
                fi = int(c) - 1
                if not (0 <= fi < len(RES_FIELDS)):
                    print("  Invalid."); continue
            except ValueError:
                print("  Invalid."); continue
            key, label = RES_FIELDS[fi]
            raw_val    = input(f"  New monthly rent for {label}: $").strip()
            if not raw_val:
                continue
            try:
                updated[key] = float(raw_val)
                print(f"  Set {label} = ${updated[key]}/mo")
            except ValueError:
                print("  Invalid number.")
        known_vals = [updated[k] for k in ("bachelor","one_br","two_br","three_br","four_br") if k in updated]
        if known_vals:
            updated["unknown"] = round(sum(known_vals) / len(known_vals), 2)
        self._store.save_residential_city(city_name, province, updated)
        print(f"  Saved residential rates for {city_name}, {province}.")
        print(f"  Unknown rate set to average: ${updated.get('unknown','—')}/mo")
        self._reanalyze_city(city_name, province)

    def _enter_commercial_rates(self, city: str, province: str):
        COMM_TYPES = ["Office", "Retail", "Industrial", "Mixed-Use"]
        print(f"\n  Enter commercial rates for {city}, {province} ($/sq ft/yr):")
        rates = {}
        for t in COMM_TYPES:
            while True:
                raw = input(f"    {t:<14}: $").strip()
                if not raw:
                    print(f"    Skipping {t}.")
                    break
                try:
                    rates[t] = float(raw)
                    break
                except ValueError:
                    print("    Invalid number.")
        if rates:
            self._store.save_commercial_city(city, province, rates)
            print(f"  Saved commercial rates for {city}, {province}.")
            self._reanalyze_city(city, province)

    def _enter_residential_rates(self, city: str, province: str):
        RES_FIELDS = [("bachelor","Bachelor"),("one_br","1BR"),("two_br","2BR"),
                      ("three_br","3BR"),("four_br","4BR"),("unknown","Unknown")]
        print(f"\n  Enter residential rates for {city}, {province} ($/mo):")
        units = {}
        for key, label in RES_FIELDS:
            while True:
                raw = input(f"    {label:<12}: $").strip()
                if not raw:
                    print(f"    Skipping {label}.")
                    break
                try:
                    units[key] = float(raw)
                    break
                except ValueError:
                    print("    Invalid number.")
        if units:
            known_vals = [units[k] for k in ("bachelor","one_br","two_br","three_br","four_br") if k in units]
            if known_vals:
                units["unknown"] = round(sum(known_vals) / len(known_vals), 2)
            self._store.save_residential_city(city, province, units)
            print(f"  Saved residential rates for {city}, {province}.")
            print(f"  Unknown rate set to average: ${units.get('unknown','—')}/mo")
            self._reanalyze_city(city, province)
