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
            # LOW-confidence income (undetailed industrial on an estimated rate)
            # is a fabricated figure — keep the property in inventory (n_total)
            # but exclude its income-derived metrics from the city averages.
            low = (p.get("income_confidence") or "").upper() == "LOW"
            city_data[key].append({
                "score":      None if low else scored.get("score"),
                "cap_rate":   None if low else scored.get("cap_rate"),  # None = not computed
                "coc":        None if low else scored.get("coc"),
                "irr":        None if low else scored.get("irr"),
                "dscr":       None if low else scored.get("dscr"),
                "cf_annual":  None if low else scored.get("cf_annual"),
                "price_drop": scored.get("price_drop"),  # 0 = no reduction (valid)
                "dom":        scored.get("dom"),          # 0 = listed today (valid)
                "asking":     p.get("asking_price") or None,
                "status":     (p.get("status") or "active").lower(),
                "address":    p.get("address", ""),
                "type":       p.get("property_type", ""),
            })

        # Shrinkage toward a prior anchor: a city's raw score is trusted in
        # proportion to its sample size (confidence = n/(n+k)); the rest pulls
        # toward `prior`. A higher k demands more listings before a city's own
        # numbers are believed (market-depth focus — thin markets stay near the
        # prior no matter how good a single listing is). `prior` set below the
        # typical-city score makes an unproven market rank below a deep, known
        # one rather than being assumed average.
        k     = cfg.get("confidence_k", 5)
        prior = cfg.get("opportunity_prior", 50)
        cities = []

        for key, entries in city_data.items():
            active    = [e for e in entries if e["status"] == "active"]
            inactive  = [e for e in entries if e["status"] != "active"]
            n_active  = len(active)
            n_total   = len(entries)

            active_cap_rate       = self._avg(active, "cap_rate")
            active_cash_on_cash   = self._avg(active, "coc")
            active_irr            = self._avg(active, "irr")
            active_dscr           = self._avg(active, "dscr")
            active_cash_flow      = self._avg(active, "cf_annual")
            active_price_drop     = self._avg(active, "price_drop")
            active_days_on_market = self._avg(active, "dom")
            active_avg_price      = self._avg(active, "asking")
            active_scored         = [e for e in active if e["score"] is not None]
            active_deal_score     = self._avg(active_scored, "score")

            inactive_cap_rate     = self._avg(inactive, "cap_rate")
            inactive_cash_on_cash = self._avg(inactive, "coc")
            inactive_avg_price    = self._avg(inactive, "asking")
            inactive_scored       = [e for e in inactive if e["score"] is not None]
            inactive_deal_score   = self._avg(inactive_scored, "score")

            all_scored = [e for e in entries if e["score"] is not None]
            best_score = max((e["score"] for e in all_scored), default=0)
            # A trend needs both an active and an inactive cap rate to compare;
            # without both it is undefined (None), not "flat" (0). Scoring still
            # treats the missing case as a neutral 0 below — only the displayed
            # value distinguishes "flat" from "no basis to compare".
            cap_trend_known = active_cap_rate is not None and inactive_cap_rate is not None
            cap_rate_trend  = (active_cap_rate - inactive_cap_rate) if cap_trend_known else 0

            # Absorption rate: share of this city's tracked listings that have
            # gone off-market. The data is binary (active vs inactive); an
            # off-market listing is treated as SOLD (assumption: not-for-sale ≈
            # transacted). So a high inactive share means inventory is clearing —
            # a demand signal (higher = better).
            absorption_rate = len(inactive) / n_total if n_total else 0
            # Price trend: average asking price of active listings vs the average
            # price of inactive (≈ sold) listings. Treating inactive as sold, an
            # active level above the sold level approximates a rising market
            # (positive = appreciation signal).
            price_trend = ((active_avg_price - inactive_avg_price) / inactive_avg_price * 100
                           if (active_avg_price is not None and inactive_avg_price) else 0)

            city_lookup = key.split(",")[0].strip().lower()
            demo        = demographics.get(city_lookup, {})
            pop         = demo.get("population", 0) or 0
            pop_growth  = demo.get("growth_pct_annual", None)
            has_demo    = bool(pop)

            confidence  = n_total / (n_total + k)

            cw  = cfg.get("city_score_weights",    {})
            ct  = cfg.get("city_score_thresholds", {})

            def _w(name, default):  return cw.get(name, default)
            def _t(name, lo, hi):   return ct.get(name, [lo, hi])

            pop_lo,    pop_hi    = _t("pop_score",    3.0, 5.7)
            growth_lo, growth_hi = _t("growth_score", -1.0, 3.0)
            pop_norm    = self._norm(math.log10(max(pop, 1)), pop_lo, pop_hi) if has_demo else 0
            growth_norm = self._norm(pop_growth, growth_lo, growth_hi) if pop_growth is not None else 0

            # Each factor's normalised 0..1 strength, paired with the config key
            # used for its weight/threshold and a human-readable label + source.
            # points = normalised * weight * 100, and the factors sum to raw_score,
            # so the report can render the real breakdown instead of recomputing it
            # from a hardcoded (and drift-prone) copy of the weights.
            factor_specs = [
                ("act_cap",         "Cap Rate (Active)",    "active",
                 self._norm(active_cap_rate     or 0, *_t("act_cap",   3,    10))),
                ("act_coc",         "CoCR (Active)",        "active",
                 self._norm(active_cash_on_cash or 0, *_t("act_coc",   0,    15))),
                ("act_irr",         "IRR (Active)",         "active",
                 self._norm(active_irr          or 0, *_t("act_irr",   8,    20))),
                ("act_dscr",        "DSCR (Active)",        "active",
                 self._norm(active_dscr         or 0, *_t("act_dscr",  1,   1.5))),
                ("act_cf",          "Cash Flow (Active)",   "active",
                 self._norm(active_cash_flow    or 0, *_t("act_cf",    0, 50000))),
                ("n_active",        "Active Volume",        "structure",
                 self._norm(n_active,                 *_t("n_active",  1,    10))),
                ("act_drop",        "Price Drop (Active)",  "active",
                 self._norm(active_price_drop   or 0, *_t("act_drop",  0,    15))),
                ("act_dom",         "Days Listed (Active)", "active",
                 self._norm(active_days_on_market or 0, *_t("act_dom", 30,  180))),
                ("inact_cap",       "Sold Cap Rate",        "sold",
                 self._norm(inactive_cap_rate   or 0, *_t("inact_cap", 3,    10))),
                ("cap_trend",       "Cap Rate Trend",       "cross",
                 self._norm(cap_rate_trend,           *_t("cap_trend", -3,    3))),
                ("absorption_rate", "Absorption (Sold Share)", "cross",
                 self._norm(absorption_rate,          *_t("absorption_rate", 0, 0.8))),
                ("price_trend",     "Price Trend (Ask vs Sold)", "cross",
                 self._norm(price_trend,              *_t("price_trend", -10, 15))),
                ("best_score",      "Best Deal Score",      "structure",
                 self._norm(best_score,               *_t("best_score", 0,  100))),
                ("pop_score",       "Population Size",      "demo", pop_norm),
                ("growth_score",    "Pop. Growth Rate",     "demo", growth_norm),
            ]

            factors   = []
            raw_score = 0.0
            for name, label, source, normalised in factor_specs:
                weight  = _w(name, 0)
                points  = normalised * weight * 100
                raw_score += points
                factors.append({
                    "key":    name,
                    "label":  label,
                    "source": source,
                    "weight": round(weight, 4),
                    "points": round(points, 2),
                })
            raw_score = round(raw_score, 1)

            opportunity_score = round(raw_score * confidence + prior * (1 - confidence), 1)

            type_counts: dict = defaultdict(int)
            for e in entries:
                t = (e.get("type") or "Unknown").strip()
                if t:
                    type_counts[t] += 1

            cities.append(dict(
                city=key, total=n_total,
                active=n_active, inactive=len(inactive),
                confidence=round(confidence, 2),
                active_deal_score=round(active_deal_score or 0, 1),
                # True when no active property had a scorable income figure, so
                # consumers can render "n/a" instead of a misleading 0.
                active_deal_score_na=(active_deal_score is None),
                active_cap_rate=active_cap_rate,
                active_cash_on_cash=active_cash_on_cash,
                active_irr=active_irr,
                active_dscr=active_dscr,
                active_cash_flow=int(active_cash_flow or 0),
                active_price_drop=active_price_drop,
                # None = no active listings to average (renders "—"); 0 = listed
                # today (renders "0d"). int() only when a real average exists.
                active_days_on_market=(int(active_days_on_market)
                                       if active_days_on_market is not None else None),
                active_avg_price=int(active_avg_price or 0),
                inactive_deal_score=round(inactive_deal_score or 0, 1),
                inactive_cap_rate=inactive_cap_rate,
                inactive_cash_on_cash=inactive_cash_on_cash,
                inactive_avg_price=int(inactive_avg_price or 0),
                best_score=round(best_score, 1),
                # None = no active+inactive cap pair to compare (renders "—").
                cap_trend=round(cap_rate_trend, 2) if cap_trend_known else None,
                absorption_rate=round(absorption_rate, 3),
                price_trend=round(price_trend, 2),
                population=pop,
                pop_growth=round(pop_growth, 2) if pop_growth is not None else None,
                has_demo=has_demo,
                opportunity=opportunity_score,
                factors=factors,
                type_counts=dict(type_counts),
            ))

        cities.sort(key=lambda c: c["opportunity"], reverse=True)
        return cities
