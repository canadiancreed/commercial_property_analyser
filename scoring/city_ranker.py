import math
from collections import defaultdict


class CityRanker:
    """
    Aggregates per-property scores into per-city opportunity rankings.

    Produces the list of city dicts consumed by CityReportGenerator.
    """

    def __init__(self, scorer):
        self._scorer = scorer

    @staticmethod
    def _avg(lst, key):
        v = [e[key] for e in lst if e.get(key) is not None]
        return round(sum(v) / len(v), 2) if v else None

    @staticmethod
    def _norm(v, lo, hi):
        if hi == lo:
            return 0.0
        return max(0.0, min(1.0, (v - lo) / (hi - lo)))

    def rank(self, properties: list) -> list:
        """
        Score every property and aggregate by city.
        Returns a list of city dicts sorted by opportunity score (desc).
        """
        cfg          = self._scorer.load_config()
        demographics = self._scorer.load_city_demographics()

        city_data: dict = defaultdict(list)
        for p in properties:
            scored = self._scorer.score_property(p)
            city   = (p.get("city") or "Unknown").strip()
            prov   = (p.get("province") or "").strip()
            key    = f"{city}, {prov}" if prov else city
            city_data[key].append({
                "score":      scored.get("score"),
                "cap_rate":   scored.get("cap_rate"),    # None = not computed
                "coc":        scored.get("coc"),
                "irr":        scored.get("irr"),
                "dscr":       scored.get("dscr"),
                "cf_annual":  scored.get("cf_annual"),
                "price_drop": scored.get("price_drop"),  # 0 = no reduction (valid)
                "dom":        scored.get("dom"),          # 0 = listed today (valid)
                "asking":     p.get("asking_price") or None,
                "status":     (p.get("status") or "active").lower(),
                "address":    p.get("address", ""),
                "type":       p.get("property_type", ""),
            })

        k  = cfg.get("confidence_k", 5)
        cities = []

        for key, entries in city_data.items():
            active    = [e for e in entries if e["status"] == "active"]
            inactive  = [e for e in entries if e["status"] != "active"]
            n_active  = len(active)
            n_total   = len(entries)

            act_cap   = self._avg(active,   "cap_rate")
            act_coc   = self._avg(active,   "coc")
            act_irr   = self._avg(active,   "irr")
            act_dscr  = self._avg(active,   "dscr")
            act_cf    = self._avg(active,   "cf_annual")
            act_drop  = self._avg(active,   "price_drop")
            act_dom   = self._avg(active,   "dom")
            act_price = self._avg(active,   "asking")
            act_scored = [e for e in active if e["score"] is not None]
            act_score  = self._avg(act_scored, "score")

            inact_cap   = self._avg(inactive, "cap_rate")
            inact_coc   = self._avg(inactive, "coc")
            inact_price = self._avg(inactive, "asking")
            inact_scored = [e for e in inactive if e["score"] is not None]
            inact_score  = self._avg(inact_scored, "score")

            all_scored = [e for e in entries if e["score"] is not None]
            best_score = max((e["score"] for e in all_scored), default=0)
            cap_trend  = (act_cap - inact_cap) if (act_cap is not None and inact_cap is not None) else 0

            absorption_rate = len(inactive) / n_total if n_total else 0
            # positive = active prices higher than sold (appreciation signal)
            price_trend = ((act_price - inact_price) / inact_price * 100
                           if (act_price is not None and inact_price) else 0)

            city_lookup = key.split(",")[0].strip().lower()
            demo        = demographics.get(city_lookup, {})
            pop         = demo.get("population", 0) or 0
            pop_growth  = demo.get("growth_pct_annual", None)
            has_demo    = bool(pop)

            confidence  = n_total / (n_total + k)

            cw  = cfg.get("city_score_weights",    {})
            ct  = cfg.get("city_score_thresholds", {})

            def _w(key, default):  return cw.get(key, default)
            def _t(key, lo, hi):   return ct.get(key, [lo, hi])

            pop_lo,    pop_hi    = _t("pop_score",    3.0, 5.7)
            growth_lo, growth_hi = _t("growth_score", -1.0, 3.0)
            pop_score    = self._norm(math.log10(max(pop, 1)), pop_lo, pop_hi) if has_demo else 0
            growth_score = self._norm(pop_growth, growth_lo, growth_hi) if pop_growth is not None else 0

            def _scored(key, value, lo, hi):
                lo_c, hi_c = _t(key, lo, hi)
                return self._norm(value, lo_c, hi_c) * _w(key, 0) * 100

            raw = round(
                _scored("act_cap",         act_cap    or 0,  3,    10) +
                _scored("act_coc",         act_coc    or 0,  0,    15) +
                _scored("act_irr",         act_irr    or 0,  8,    20) +
                _scored("act_dscr",        act_dscr   or 0,  1,   1.5) +
                _scored("act_cf",          act_cf     or 0,  0, 50000) +
                _scored("n_active",        n_active,         1,    10) +
                _scored("act_drop",        act_drop   or 0,  0,    15) +
                _scored("act_dom",         act_dom    or 0, 30,   180) +
                _scored("inact_cap",       inact_cap  or 0,  3,   10) +
                _scored("cap_trend",       cap_trend,       -3,    3) +
                _scored("absorption_rate", absorption_rate,  0,  0.8) +
                _scored("price_trend",     price_trend,    -10,   15) +
                _scored("best_score",      best_score,       0,  100) +
                pop_score    * _w("pop_score",    0) * 100 +
                growth_score * _w("growth_score", 0) * 100,
                1,
            )

            opp = round(raw * confidence + 50 * (1 - confidence), 1)

            type_counts: dict = defaultdict(int)
            for e in entries:
                t = (e.get("type") or "Unknown").strip()
                if t:
                    type_counts[t] += 1

            cities.append(dict(
                city=key, total=n_total,
                active=n_active, inactive=len(inactive),
                confidence=round(confidence, 2),
                act_score=round(act_score or 0, 1),
                act_cap=act_cap, act_coc=act_coc, act_irr=act_irr,
                act_dscr=act_dscr, act_cf=int(act_cf or 0),
                act_drop=act_drop, act_dom=int(act_dom or 0),
                act_price=int(act_price or 0),
                inact_score=round(inact_score or 0, 1),
                inact_cap=inact_cap, inact_coc=inact_coc,
                inact_price=int(inact_price or 0),
                best_score=round(best_score, 1),
                cap_trend=round(cap_trend, 2),
                absorption_rate=round(absorption_rate, 3),
                price_trend=round(price_trend, 2),
                population=pop,
                pop_growth=round(pop_growth, 2) if pop_growth is not None else None,
                has_demo=has_demo,
                opportunity=opp,
                type_counts=dict(type_counts),
            ))

        cities.sort(key=lambda c: c["opportunity"], reverse=True)
        return cities
