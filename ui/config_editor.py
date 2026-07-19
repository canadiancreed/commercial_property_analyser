"""Config editor mixin — scoring weights, city distances, and demographics."""
import os

from analysis.financing_config import load_financing_config, save_financing_config


class ConfigEditorMixin:
    """Mix-in providing score/city config editing methods for PropertyMenu."""

    def _edit_financing_defaults(self):
        """Edit the global financing defaults (down payment / rate / amortization).

        These are house-wide settings applied to every property, not entered per
        listing. Stored records keep a snapshot of the values used at their last
        analysis, so a change here only moves the numbers once properties are
        re-analyzed — which this method offers to do on exit.
        """
        changed = False
        while True:
            cfg = load_financing_config()
            dp  = cfg["down_payment_pct"]
            ir  = cfg["interest_rate"]
            tm  = cfg["term_years"]
            hy  = cfg["hold_years"]
            print(f"\n{'GLOBAL FINANCING DEFAULTS':^75}")
            print(self.DIVIDER)
            print("  Applied to every property — not entered per listing.")
            print("  Change a value, then re-analyze so stored results pick it up.")
            print(self.DIVIDER)
            print(f"  1  Down payment %       {dp * 100:>8.2f}%")
            print(f"  2  Interest rate %      {ir * 100:>8.2f}%")
            print(f"  3  Amortization (years) {tm:>8}")
            print(f"  4  Hold period (years)  {hy:>8}")
            print(self.DIVIDER)
            print("  Note: expense ratio is set globally by property type/lease")
            print("        (models/constants.py), not here — one number would be wrong.")
            print(self.DIVIDER)
            print("  0  Back")
            print(self.DIVIDER)
            choice = input("  Edit # (0 to finish): ").strip()
            if choice == "0":
                break
            if choice == "1":
                raw = input(f"  Down payment % (e.g. 20 or 0.20, currently {dp * 100:.2f}%, Enter to keep): ").strip()
                if raw:
                    try:
                        v = float(raw)
                        v = v / 100 if v > 1 else v
                        if not (0 <= v < 1):
                            print("  Invalid — must be ≥ 0 and < 100%.")
                            continue
                        save_financing_config(v, ir, tm, hy)
                        changed = True
                        print(f"  Saved — {v * 100:.2f}% down.")
                    except ValueError:
                        print("  Invalid number.")
            elif choice == "2":
                raw = input(f"  Interest rate % (e.g. 4.5, currently {ir * 100:.2f}%, Enter to keep): ").strip()
                if raw:
                    try:
                        v = float(raw)
                        v = v / 100 if v > 1 else v
                        if v < 0:
                            print("  Invalid — rate cannot be negative.")
                            continue
                        save_financing_config(dp, v, tm, hy)
                        changed = True
                        print(f"  Saved — {v * 100:.2f}% rate.")
                    except ValueError:
                        print("  Invalid number.")
            elif choice == "3":
                raw = input(f"  Amortization years (currently {tm}, Enter to keep): ").strip()
                if raw:
                    try:
                        v = int(raw)
                        if v <= 0:
                            raise ValueError
                        save_financing_config(dp, ir, v, hy)
                        changed = True
                        print(f"  Saved — {v}-year amortization.")
                    except ValueError:
                        print("  Invalid — enter a positive whole number of years.")
            elif choice == "4":
                raw = input(f"  Hold period years (currently {hy}, Enter to keep): ").strip()
                if raw:
                    try:
                        v = int(raw)
                        if v <= 0:
                            raise ValueError
                        save_financing_config(dp, ir, tm, v)
                        changed = True
                        print(f"  Saved — {v}-year hold period.")
                    except ValueError:
                        print("  Invalid — enter a positive whole number of years.")
            else:
                print("  Invalid choice.")

        if changed:
            apply = input("\n  Re-analyze all properties now to apply the new financing? (y/n): ").strip().lower()
            if apply in ("y", "yes"):
                self._reanalyze_all()
            else:
                print("  Not applied yet — run 'r' (re-analyze all) when ready.")

    def _edit_score_config(self):
        DESCRIPTIONS = {
            "Cap Rate":        "NOI / (asking + construction)  —  higher is better",
            "CoCR":            "Annual cash flow / cash invested  —  higher is better",
            "DSCR":            "NOI / annual mortgage payment  —  higher is better",
            "IRR":             "Internal rate of return over hold period  —  higher is better",
            "Equity Multiple": "Total return / cash invested  —  higher is better",
            "Cash Flow":       "Annual cash flow ($)  —  higher is better",
            "Price Drop":      "% reduction from original list price  —  higher is better",
            "DOM":             "Days on market  —  more days = more seller motivation",
            "Location":        "km to nearest regional centre  —  closer is better",
        }
        while True:
            cfg        = self._scorer.load_config()
            weights    = cfg["weights"]
            thresholds = cfg["thresholds"]
            total_w    = sum(w for w in weights.values() if w > 0)
            print(f"\n{'SCORING FORMULA':^75}")
            print(self.DIVIDER)
            print(f"  Weights must sum to 1.0.  Currently: {total_w:.2f}")
            print("  Scores normalized automatically — set a weight to 0 to disable a component.")
            print(self.DIVIDER)
            print(f"  {'#':<3} {'COMPONENT':<18} {'WEIGHT':>7}  {'FLOOR':>9}  {'CEILING':>9}  DESCRIPTION")
            print(self.DIVIDER)
            keys = list(weights.keys())
            for i, k in enumerate(keys, 1):
                w      = weights[k]
                lo, hi = thresholds.get(k, [0, 1])
                pct    = f"{w*100:.0f}%"
                print(f"  {i:<3} {k:<18} {pct:>7}  {lo:>9}  {hi:>9}  {DESCRIPTIONS.get(k,'')}")
            print(self.DIVIDER)
            print("  d  Edit city distances to regional centres")
            print("  c  Edit city opportunity score weights")
            print("  m  Edit city demographics (population / growth)")
            print("  0  Back")
            print(self.DIVIDER)
            choice = input("  Edit # (or d/c/m/0): ").strip().lower()
            if choice == "0":
                break
            if choice == "d":
                self._edit_city_distances()
                continue
            if choice == "c":
                self._edit_city_weights()
                continue
            if choice == "m":
                self._edit_city_demographics()
                continue
            try:
                idx = int(choice) - 1
                if not (0 <= idx < len(keys)):
                    raise ValueError
            except ValueError:
                print("  Invalid choice.")
                continue
            k      = keys[idx]
            lo, hi = thresholds[k]
            w      = weights[k]
            print(f"\n  Editing: {k}")
            print(f"  {DESCRIPTIONS.get(k,'')}")
            print(self.THIN_DIVIDER)
            raw = input(f"  Weight % (currently {w*100:.0f}%, Enter to keep): ").strip()
            if raw:
                try:
                    new_w = float(raw)
                    new_w = new_w / 100 if new_w > 1 else new_w
                    weights[k] = round(new_w, 4)
                except ValueError:
                    print("  Invalid — weight unchanged.")
            raw = input(f"  Floor (currently {lo}, score=0 at this value, Enter to keep): ").strip()
            if raw:
                try:
                    thresholds[k][0] = float(raw)
                except ValueError:
                    print("  Invalid — floor unchanged.")
            raw = input(f"  Ceiling (currently {hi}, score=10 at this value, Enter to keep): ").strip()
            if raw:
                try:
                    thresholds[k][1] = float(raw)
                except ValueError:
                    print("  Invalid — ceiling unchanged.")
            cfg["weights"]    = weights
            cfg["thresholds"] = thresholds
            self._scorer.save_config(cfg)
            print("  Saved.")

    def _edit_city_weights(self):
        DESCRIPTIONS = {
            "act_cap":         "Avg cap rate of active listings  (higher yield environment)",
            "act_coc":         "Avg cash-on-cash return of active listings  (income quality)",
            "act_irr":         "Avg IRR of active listings  (projected return)",
            "act_dscr":        "Avg debt-service coverage of active listings  (financing safety)",
            "act_cf":          "Avg annual cash flow of active listings  (income level)",
            "act_drop":        "Avg % price reduction from original list  (seller motivation)",
            "act_dom":         "Avg days on market  (higher = softer market = more leverage)",
            "inact_cap":       "Avg cap rate of inactive (≈ sold) listings  (achieved yield)",
            "cap_trend":       "Active minus inactive cap rate  (market direction)",
            "absorption_rate": "Share of listings gone off-market (≈ sold)  (demand — higher = clearing)",
            "price_trend":     "Active asking vs inactive (≈ sold) price  (appreciation signal)",
            "best_score":      "Single best deal score in the city  (upside ceiling)",
            "pop_score":       "City population (log-scaled)  (market size)",
            "growth_score":    "Annual population growth %  (demand trajectory)",
        }
        while True:
            cfg   = self._scorer.load_config()
            cw    = cfg.get("city_score_weights",    {})
            ct    = cfg.get("city_score_thresholds", {})
            total = sum(cw.values())
            keys  = list(cw.keys())
            depth_exp = cfg.get("opportunity_depth_exp", 0.4)
            print(f"\n{'CITY OPPORTUNITY SCORE FORMULA':^75}")
            print(self.DIVIDER)
            print(f"  These are relative QUALITY weights (auto-normalised) for the deal-quality")
            print(f"  sub-score. Opportunity = quality^{1-depth_exp:.2f} x depth^{depth_exp:.2f} "
                  f"(geometric — needs both). Depth knobs: opportunity_depth_exp / _ref in json.")
            print(self.DIVIDER)
            print(f"  {'#':<3} {'SIGNAL':<16} {'WEIGHT':>7}  {'FLOOR':>9}  {'CEILING':>9}  DESCRIPTION")
            print(self.DIVIDER)
            for i, k in enumerate(keys, 1):
                pct      = f"{cw[k]*100:.0f}%"
                lo, hi   = ct.get(k, [0, 1])
                print(f"  {i:<3} {k:<16} {pct:>7}  {lo:>9}  {hi:>9}  {DESCRIPTIONS.get(k,'')}")
            print(self.DIVIDER)
            depth_ref = cfg.get("opportunity_depth_ref", 50)
            max_cap   = cfg.get("outlier_max_cap_rate", 12.0)
            max_coc   = cfg.get("outlier_max_coc", 25.0)
            print("  MODEL KNOBS")
            print(f"  D  Depth weight (exponent)  {depth_exp:>6.2f}   (quality gets {1-depth_exp:.2f})")
            print(f"  R  Depth reference          {depth_ref:>6.0f}   active listings for ~full depth")
            print(f"  C  Outlier cap-rate ceiling {max_cap:>6.1f}%  active listings above are screened out")
            print(f"  K  Outlier CoCR ceiling     {max_coc:>6.1f}%  active listings above are screened out")
            print(self.DIVIDER)
            print("  0  Back")
            print(self.DIVIDER)
            choice = input("  Edit # / D / R / C / K (or 0): ").strip()
            if choice == "0":
                break

            low = choice.lower()
            if low in ("d", "r", "c", "k"):
                if low == "d":
                    raw = input(f"  Depth weight 0..1 (currently {depth_exp:.2f}, Enter to keep): ").strip()
                    if raw:
                        try:
                            v = float(raw)
                            if 0 <= v < 1: cfg["opportunity_depth_exp"] = round(v, 3)
                            else: print("  Invalid — must be ≥ 0 and < 1.")
                        except ValueError:
                            print("  Invalid — unchanged.")
                elif low == "r":
                    raw = input(f"  Depth reference active count (currently {depth_ref:.0f}, Enter to keep): ").strip()
                    if raw:
                        try:
                            v = float(raw)
                            if v > 1: cfg["opportunity_depth_ref"] = round(v, 2)
                            else: print("  Invalid — must be > 1.")
                        except ValueError:
                            print("  Invalid — unchanged.")
                elif low == "c":
                    raw = input(f"  Cap-rate outlier ceiling % (currently {max_cap:.1f}, Enter to keep): ").strip()
                    if raw:
                        try: cfg["outlier_max_cap_rate"] = round(float(raw), 2)
                        except ValueError: print("  Invalid — unchanged.")
                elif low == "k":
                    raw = input(f"  CoCR outlier ceiling % (currently {max_coc:.1f}, Enter to keep): ").strip()
                    if raw:
                        try: cfg["outlier_max_coc"] = round(float(raw), 2)
                        except ValueError: print("  Invalid — unchanged.")
                self._scorer.save_config(cfg)
                print("  Saved.")
                continue

            try:
                idx = int(choice) - 1
                if not (0 <= idx < len(keys)):
                    raise ValueError
            except ValueError:
                print("  Invalid choice.")
                continue
            k      = keys[idx]
            lo, hi = ct.get(k, [0, 1])
            raw = input(f"  Weight % (currently {cw[k]*100:.0f}%, Enter to keep): ").strip()
            if raw:
                try:
                    v = float(raw)
                    cw[k] = round(v / 100 if v > 1 else v, 4)
                except ValueError:
                    print("  Invalid — weight unchanged.")
            raw = input(f"  Floor (currently {lo}, Enter to keep): ").strip()
            if raw:
                try:
                    ct[k][0] = float(raw)
                except ValueError:
                    print("  Invalid — floor unchanged.")
            raw = input(f"  Ceiling (currently {hi}, Enter to keep): ").strip()
            if raw:
                try:
                    ct[k][1] = float(raw)
                except ValueError:
                    print("  Invalid — ceiling unchanged.")
            cfg["city_score_weights"]    = cw
            cfg["city_score_thresholds"] = ct
            self._scorer.save_config(cfg)
            print(f"  Saved. New total: {sum(cw.values()):.2f}")

    def _edit_city_distances(self):
        path      = "json/city_distances.json"
        distances = {}
        if os.path.exists(path):
            try:
                distances = self._store._read(path)
            except Exception:
                pass
        for p in self._store.load_properties():
            city = (p.get("city") or "").strip()
            if city and city not in distances:
                distances[city] = {"distance_km": None, "nearest_centre": ""}
        while True:
            cities = sorted(distances.keys(), key=str.lower)
            print(f"\n{'CITY DISTANCES TO REGIONAL CENTRES':^75}")
            print(self.DIVIDER)
            print(f"  {'#':<3} {'CITY':<22} {'NEAREST CENTRE':<22} {'KM':>6}")
            print(self.DIVIDER)
            for i, city in enumerate(cities, 1):
                d  = distances[city]
                km = d.get("distance_km")
                nc = d.get("nearest_centre") or "—"
                print(f"  {i:<3} {city:<22} {nc:<22} {str(km) if km is not None else '—':>6}")
            print(self.DIVIDER)
            print("  Enter # to edit   a = add city   0 = back")
            print(self.THIN_DIVIDER)
            choice = input("  Select: ").strip().lower()
            if choice == "0":
                break
            if choice == "a":
                city = input("  City name: ").strip().title()
                if not city:
                    continue
                if city not in distances:
                    distances[city] = {"distance_km": None, "nearest_centre": ""}
                cities = sorted(distances.keys(), key=str.lower)
            try:
                idx  = int(choice) - 1
                city = cities[idx]
            except (ValueError, IndexError):
                print("  Invalid.")
                continue
            nc = input(f"  Nearest regional centre (currently '{distances[city].get('nearest_centre') or ''}', Enter to keep): ").strip()
            if nc:
                distances[city]["nearest_centre"] = nc
            km_raw = input(f"  Distance in km (currently {distances[city].get('distance_km')}, Enter to keep): ").strip()
            if km_raw:
                try:
                    distances[city]["distance_km"] = float(km_raw)
                except ValueError:
                    print("  Invalid km — unchanged.")
            os.makedirs("json", exist_ok=True)
            self._store._write(path, distances)
            print(f"  Saved {city}.")

    def _edit_city_demographics(self):
        DEMO_PATH = "json/city_demographics.json"
        os.makedirs("json", exist_ok=True)

        def load():
            if os.path.exists(DEMO_PATH):
                try:
                    return self._store._read(DEMO_PATH)
                except Exception:
                    pass
            return {}

        def save(data):
            self._store._write(DEMO_PATH, data)

        while True:
            data          = load()
            cities_sorted = sorted(data.keys())
            print(self.DIVIDER)
            print("  CITY DEMOGRAPHICS — population & growth data")
            print(self.DIVIDER)
            if cities_sorted:
                print(f"  {'City':<25} {'Population':>12}  {'Growth/yr':>10}  {'Source'}")
                print(f"  {'-'*25} {'-'*12}  {'-'*10}  {'-'*30}")
                for i, city in enumerate(cities_sorted, 1):
                    d      = data[city]
                    pop    = d.get("population", "—")
                    growth = d.get("growth_pct_annual")
                    src    = d.get("source", "")[:35]
                    g_str  = f"{growth:+.2f}%" if growth is not None else "—"
                    pop_str = f"{pop:,}" if isinstance(pop, int) else str(pop)
                    print(f"  {i:<3} {city.title():<25} {pop_str:>12}  {g_str:>10}  {src}")
            else:
                print("  No demographic data on file.")
            print(self.DIVIDER)
            print("  a  Add / update a city")
            print("  x  Delete a city entry")
            print("  0  Back")
            print(self.DIVIDER)
            choice = input("  Choice: ").strip().lower()
            if choice == "0":
                break
            if choice == "a":
                city_raw = input("  City name (e.g. Cobourg): ").strip()
                if not city_raw:
                    continue
                city_key = city_raw.lower()
                existing = data.get(city_key, {})
                print(f"  Editing: {city_raw}")
                pop_str   = input(f"  Population 2021 [{existing.get('population','')}]: ").strip()
                pop16_str = input(f"  Population 2016 [{existing.get('population_2016','')}]: ").strip()
                src_str   = input(f"  Source [{existing.get('source','Stats Canada 2021 Census')}]: ").strip()
                notes_str = input(f"  Notes [{existing.get('notes','')}]: ").strip()
                try:
                    pop    = int(pop_str)   if pop_str   else existing.get("population", 0)
                    pop16  = int(pop16_str) if pop16_str else existing.get("population_2016", 0)
                    source = src_str   if src_str   else existing.get("source", "Stats Canada 2021 Census")
                    notes  = notes_str if notes_str else existing.get("notes", "")
                except ValueError:
                    print("  Invalid number — skipping.")
                    continue
                if pop and pop16:
                    growth = round(((pop / pop16) ** (1/5) - 1) * 100, 2)
                    print(f"  Calculated annualised growth (2016→2021): {growth:+.2f}%/yr")
                else:
                    growth = existing.get("growth_pct_annual", None)
                data[city_key] = {
                    "population":        pop,
                    "population_2016":   pop16,
                    "growth_pct_annual": growth,
                    "source":            source,
                    "notes":             notes,
                }
                save(data)
                print(f"  Saved {city_raw.title()}.")
            elif choice == "x":
                city_raw = input("  City name to delete: ").strip().lower()
                if city_raw in data:
                    del data[city_raw]
                    save(data)
                    print(f"  Deleted {city_raw.title()}.")
                else:
                    print("  Not found.")
