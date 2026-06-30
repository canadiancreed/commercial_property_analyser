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

        # Plausibility screen: an estimated rent can imply an impossible cap rate
        # or cash-on-cash (e.g. a 27% cap or 100%+ CoCR). Those figures are not
        # real deals — exclude them from the city averages (like LOW-confidence
        # income) so they can't inflate a city, but keep the listing in inventory.
        max_cap = cfg.get("outlier_max_cap_rate", 12.0)
        max_coc = cfg.get("outlier_max_coc",      25.0)

        city_data: dict = defaultdict(list)
        for p in properties:
            scored = self._scorer.score_property(p)
            city   = (p.get("city") or "Unknown").strip()
            prov   = (p.get("province") or "").strip()
            key    = f"{city}, {prov}" if prov else city
            # LOW-confidence income (undetailed industrial on an estimated rate)
            # is a fabricated figure; an implausible cap/CoCR is a bad estimate.
            # Keep the property in inventory (n_total) but drop its income-derived
            # metrics from the city averages.
            low         = (p.get("income_confidence") or "").upper() == "LOW"
            _cap, _coc  = scored.get("cap_rate"), scored.get("coc")
            implausible = ((_cap is not None and _cap > max_cap) or
                           (_coc is not None and _coc > max_coc))
            drop_income = low or implausible
            city_data[key].append({
                "score":      None if drop_income else scored.get("score"),
                "cap_rate":   None if drop_income else scored.get("cap_rate"),  # None = not computed
                "coc":        None if drop_income else scored.get("coc"),
                "irr":        None if drop_income else scored.get("irr"),
                "dscr":       None if drop_income else scored.get("dscr"),
                "cf_annual":  None if drop_income else scored.get("cf_annual"),
                "price_drop": scored.get("price_drop"),  # 0 = no reduction (valid)
                "dom":        scored.get("dom"),          # 0 = listed today (valid)
                "asking":     p.get("asking_price") or None,
                "status":     (p.get("status") or "active").lower(),
                "address":    p.get("address", ""),
                "type":       p.get("property_type", ""),
            })

        # Opportunity rewards being good on BOTH axes at once: profitable deals
        # (quality) AND enough of them to concentrate on (depth). It is the
        # weighted geometric mean of the two, each 0..1:
        #   opportunity = 100 · quality**quality_exp · depth**depth_exp
        # Because it is multiplicative, neither axis can carry the other: a huge
        # market full of weak deals scores low (quality≈0), and a single great
        # listing scores low (depth≈0). `confidence_k` is display-only now.
        k          = cfg.get("confidence_k", 5)
        depth_ref  = cfg.get("opportunity_depth_ref", 50)
        depth_exp  = cfg.get("opportunity_depth_exp", 0.4)
        quality_exp = 1.0 - depth_exp
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
            # Individual active asking prices, so the report's price filter can
            # match a city on whether ANY listing fits the range — not just the
            # city average (which hid cities that did have in-range listings).
            active_prices         = sorted(e["asking"] for e in active if e["asking"])
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

            # Quality factors: each a normalised 0..1 strength paired with the
            # config key for its weight/threshold and a label + source. Listing
            # volume is NOT here — depth is a separate premium (below) so a city's
            # quality is judged independently of its size.
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
                ("act_drop",        "Price Drop (Active)",  "active",
                 self._norm(active_price_drop   or 0, *_t("act_drop",  0,    15))),
                ("act_dom",         "Days Listed (Active)", "active",
                 self._norm(active_days_on_market or 0, *_t("act_dom", 30,  180))),
                ("inact_cap",       "Inactive Cap Rate",    "inactive",
                 self._norm(inactive_cap_rate   or 0, *_t("inact_cap", 3,    10))),
                ("cap_trend",       "Cap Rate Trend",       "cross",
                 self._norm(cap_rate_trend,           *_t("cap_trend", -3,    3))),
                ("absorption_rate", "Absorption (Inactive Share)", "cross",
                 self._norm(absorption_rate,          *_t("absorption_rate", 0, 0.8))),
                ("price_trend",     "Price Trend (Ask vs Inactive)", "cross",
                 self._norm(price_trend,              *_t("price_trend", -10, 15))),
                ("best_score",      "Best Deal Score",      "structure",
                 self._norm(best_score,               *_t("best_score", 0,  100))),
                ("pop_score",       "Population Size",      "demo", pop_norm),
                ("growth_score",    "Pop. Growth Rate",     "demo", growth_norm),
            ]

            # Quality (0..1): renormalised weighted blend of the deal/market
            # factors, independent of city size. The factor "points" sum to the
            # quality sub-score (0..100), so the report renders the real
            # breakdown of what makes a market's deals good.
            qw_sum = sum(_w(name, 0) for name, *_rest in factor_specs) or 1.0

            factors = []
            quality_score = 0.0
            for name, label, source, normalised in factor_specs:
                share  = _w(name, 0) / qw_sum          # weights total 1.0
                points = normalised * share * 100
                quality_score += points
                factors.append({
                    "key":    name,
                    "label":  label,
                    "source": source,
                    "weight": round(share, 4),
                    "points": round(points, 2),
                })
            quality_score = round(quality_score, 1)
            quality_norm  = quality_score / 100.0

            # Depth (0..1): log-scaled active inventory. depth_ref is the active
            # count that earns (about) full depth.
            depth_norm = (math.log10(n_active + 1) / math.log10(depth_ref + 1)
                          if depth_ref and depth_ref > 0 else 0)
            depth_norm = max(0.0, min(1.0, depth_norm))
            depth_score = round(depth_norm * 100, 1)

            # Geometric mean: a city must be good on BOTH axes — neither a big
            # weak market nor a tiny strong one can score high alone.
            opportunity_score = round(
                100 * (quality_norm ** quality_exp) * (depth_norm ** depth_exp), 1
            )

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
                active_prices=[int(p) for p in active_prices],
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
                # The two geometric inputs (each 0–100): deal quality and market
                # depth. factors[] is the breakdown of the quality sub-score.
                quality_score=quality_score,
                depth_score=depth_score,
                factors=factors,
                type_counts=dict(type_counts),
            ))

        cities.sort(key=lambda c: c["opportunity"], reverse=True)
        return cities
