import copy
import os
from analysis.metrics.returns import METRIC_MARKET_STALENESS
from analysis.metrics.income import INCOME_METRIC_NAMES

SCORE_CONFIG_PATH = "json/score_weights.json"
CITY_DISTANCES_PATH  = "json/city_distances.json"
CITY_DEMOGRAPHICS_PATH = "json/city_demographics.json"


class PropertyScorer:
    """
    Computes 0-100 investment scores from saved analysis result records.

    All state is derived from the DataStore JSON files on each call — no
    in-memory caching.  Accepts a DataStore instance for JSON I/O.
    """

    def __init__(self, store):
        self._store = store

    # ── Config persistence ────────────────────────────────────────────────

    def load_config(self) -> dict:
        return self._store._read(SCORE_CONFIG_PATH)

    def save_config(self, cfg: dict):
        os.makedirs(
            os.path.dirname(SCORE_CONFIG_PATH) if os.path.dirname(SCORE_CONFIG_PATH) else ".",
            exist_ok=True,
        )
        self._store._write(SCORE_CONFIG_PATH, cfg)

    # ── Geo / demographic data ─────────────────────────────────────────────

    def load_city_distances(self) -> dict:
        """Returns {city_lower: {distance_km, nearest_centre}}."""
        if os.path.exists(CITY_DISTANCES_PATH):
            try:
                return {k.lower(): v for k, v in self._store._read(CITY_DISTANCES_PATH).items()}
            except Exception:
                pass
        return {}

    def load_city_demographics(self) -> dict:
        """Returns {city_lower: {population, growth_pct_annual, ...}}."""
        if os.path.exists(CITY_DEMOGRAPHICS_PATH):
            try:
                return {k.lower(): v for k, v in self._store._read(CITY_DEMOGRAPHICS_PATH).items()}
            except Exception:
                pass
        return {}

    # ── Scoring ────────────────────────────────────────────────────────────

    def score_property(self, p: dict) -> dict:
        """
        Score a saved property record (0-100).
        Returns {"score": float|None, "breakdown": {}, "weights": {}, ...metrics}.
        """
        results = {r["metric"]: r for r in (p.get("results") or [])}
        INCOME  = INCOME_METRIC_NAMES
        if not any(m in results for m in INCOME):
            return {"score": None, "breakdown": {}, "weights": {},
                    "income_confidence": p.get("income_confidence")}

        cfg        = self.load_config()
        weights    = cfg["weights"]
        thresholds = cfg["thresholds"]

        def val(metric, default=0.0):
            row     = results.get(metric)
            if not row:
                return default
            raw     = row.get("value", "0")
            cleaned = "".join(c for c in str(raw) if c.isdigit() or c in ".-")
            return float(cleaned) if cleaned else default

        def val_prefix(prefix, default=0.0):
            key = next((k for k in results if k.startswith(prefix)), None)
            return val(key, default) if key else default

        def clamp(v, lo, hi):
            return max(lo, min(hi, v))

        def component(key, raw_value, invert=False):
            lo, hi = thresholds.get(key, [0, 1])
            if hi == lo:
                return 0.0
            s = ((lo - raw_value) / (lo - hi)) if invert else ((raw_value - lo) / (hi - lo))
            return clamp(s * 10, 0, 10)

        cap_rate   = val("Cap Rate")
        coc        = val("CoCR")
        dscr       = val("DSCR")
        # "IRR not meaningful" (no real IRR root) has no digits, so it parses
        # to the default; keep that None so reports show "—" instead of a fake 0%.
        irr        = val_prefix("IRR (", default=None)
        em         = val("Equity Multiple")
        cf_annual  = val("Annual Cash Flow")
        price_drop = val("Price Drop %")
        dom        = val(METRIC_MARKET_STALENESS, 0)

        city      = (p.get("city") or "").lower()
        distances = self.load_city_distances()
        dist_info = distances.get(city)
        dist_km   = dist_info["distance_km"] if dist_info else None
        s_loc     = component("Location", dist_km, invert=True) if dist_km is not None else 0.0

        scores = {
            "Cap Rate":        component("Cap Rate",        cap_rate),
            "CoCR":            component("CoCR",            coc),
            "DSCR":            component("DSCR",            dscr),
            "IRR":             component("IRR", irr) if irr is not None else 0.0,
            "Equity Multiple": component("Equity Multiple", em),
            "Cash Flow":       component("Cash Flow",       cf_annual),
            "Price Drop":      component("Price Drop",      price_drop),
            "DOM":             component("DOM",             dom),
            "Location":        s_loc,
        }

        active_w = {k: w for k, w in weights.items() if w > 0}
        total_w  = sum(active_w.values())
        score    = 0.0
        if total_w > 0:
            score = sum(scores[k] * (w / total_w) for k, w in active_w.items()) * 10

        return {
            "score":       round(score, 1),
            "breakdown":   {k: round(scores[k] * 10, 1) for k in scores},
            "weights":     weights,
            "income_confidence": p.get("income_confidence"),
            "cap_rate":    cap_rate,
            "coc":         coc,
            "dscr":        dscr,
            "irr":         irr,
            "em":          em,
            "cf_annual":   cf_annual,
            "price_drop":  price_drop,
            "dom":         int(dom),
            "dist_km":     dist_km,
            "dist_centre": dist_info["nearest_centre"] if dist_info else None,
        }

    def solve_targets(self, p: dict, record_to_prop_fn, analyzer_class, resolver) -> dict:
        """
        Binary-search each lever (price, rent, rate, down_pct) for the value
        that would push the score to 100.  Returns {lever: target_value}.

        Requires callbacks for property construction and analysis since those
        live in ui and analysis layers respectively.
        """
        base = self.score_property(p)
        if base["score"] is None or base["score"] >= 99.5:
            return {}

        def score_with(overrides: dict) -> float:
            rec = copy.deepcopy(p)
            rec.update(overrides)
            if "annual_rent" in overrides:
                rec["commercial_rent"]  = None
                rec["residential_rent"] = None
            try:
                prop     = record_to_prop_fn(rec)
                analyzer = analyzer_class(prop, resolver)
                new_rec  = analyzer.to_record(existing=rec)
                rec.update({k: v for k, v in new_rec.items() if k == "results"})
                return self.score_property(rec).get("score") or 0.0
            except Exception:
                return 0.0

        def bisect_lever(key, lo, hi, n=60, invert=False):
            for _ in range(n):
                mid = (lo + hi) / 2
                s   = score_with({key: mid})
                if s >= 99.5:
                    lo = mid if invert else (lo, hi := mid)[0]
                else:
                    hi = mid if invert else (lo := mid, hi)[1]
            return (lo + hi) / 2

        base_price = p.get("asking_price", 0)
        base_rent  = (p.get("commercial_rent") or 0) + (p.get("residential_rent") or 0)
        base_rate  = p.get("interest_rate", 0.045)
        base_dp    = p.get("down_payment_pct", 0.20)
        targets    = {}

        if base_price > 0:
            lo_p, hi_p = base_price * 0.10, base_price
            if score_with({"asking_price": lo_p}) >= 99.5:
                t = bisect_lever("asking_price", lo_p, hi_p, invert=True)
                if t < base_price * 0.999:
                    targets["price"] = round(t / 1000) * 1000

        if base_rent > 0:
            lo_r, hi_r = base_rent, base_rent * 5
            if score_with({"annual_rent": hi_r}) >= 99.5:
                t = bisect_lever("annual_rent", lo_r, hi_r)
                if t > base_rent * 1.001:
                    targets["rent"] = round(t / 100) * 100

        if base_rate > 0:
            lo_i, hi_i = 0.005, base_rate
            if score_with({"interest_rate": lo_i}) >= 99.5:
                t = bisect_lever("interest_rate", lo_i, hi_i, invert=True)
                if t < base_rate * 0.999:
                    targets["rate"] = round(t * 10000) / 10000

        if base_dp < 0.95:
            lo_d, hi_d = base_dp, 0.95
            if score_with({"down_payment_pct": hi_d}) >= 99.5:
                t = bisect_lever("down_payment_pct", lo_d, hi_d)
                if t > base_dp * 1.001:
                    targets["down_pct"] = round(t * 1000) / 1000

        return targets
