import copy
import os
from analysis.metrics.returns import METRIC_MARKET_STALENESS
from analysis.metrics.income import INCOME_METRIC_NAMES
from analysis.underwriting_config import load_underwriting_config
from analysis.screener_config import load_screener_config
from analysis.financing_config import resolve_financing, mixed_use_commercial_gfa_share

METRIC_SELLER_BLEED = "Seller Bleed"

SCORE_CONFIG_PATH = "json/score_weights.json"
CITY_DISTANCES_PATH  = "json/city_distances.json"
CITY_DEMOGRAPHICS_PATH = "json/city_demographics.json"


def _dom_band(dom: float, cfg: dict) -> str:
    if dom <= cfg["dom_normal_days"]:
        return "normal"
    if dom <= cfg["dom_stale_days"]:
        return "aging"
    return "stale"


def _drop_band(drop_pct: float, cfg: dict) -> str:
    if drop_pct >= cfg["drop_severe_pct"]:
        return "severe"
    if drop_pct >= cfg["drop_large_pct"]:
        return "large"
    if drop_pct >= cfg["drop_modest_pct"]:
        return "modest"
    return "none"


def _liquidity_band(dist_km, demo: dict, cfg: dict) -> tuple:
    """Config-weighted market-thinness proxy from distance to the nearest major
    centre and city population/growth. Missing inputs default to the moderate
    midpoint (0.5) rather than assuming either liquid or thin."""
    dist_component = (
        max(0.0, min(1.0, dist_km / cfg["liquidity_distance_reference_km"]))
        if dist_km is not None else 0.5
    )
    population = demo.get("population") if demo else None
    pop_component = (
        max(0.0, min(1.0, (cfg["liquidity_population_reference"] - population)
                     / cfg["liquidity_population_reference"]))
        if population else 0.5
    )
    growth = demo.get("growth_pct_annual") if demo else None
    growth_component = 1.0 if (growth is not None and growth < 0) else 0.0
    thinness = (
        cfg["liquidity_weight_distance"] * dist_component +
        cfg["liquidity_weight_population"] * pop_component +
        cfg["liquidity_weight_growth"] * growth_component
    )
    if thinness >= cfg["liquidity_thin_threshold"]:
        band = "thin"
    elif thinness <= cfg["liquidity_liquid_threshold"]:
        band = "liquid"
    else:
        band = "moderate"
    return band, thinness


def price_drop_velocity(price_drop_pct: float, dom_days: float):
    """% reduction per day on market. None when there's no elapsed time to divide by."""
    return (price_drop_pct / dom_days) if dom_days and dom_days > 0 else None


def _motivated_seller_read(price_drop_pct: float, dom_days: float,
                           monthly_bleed, cfg: dict):
    """Fast-price-cut read — fires when a large reduction lands early in the
    listing (regardless of staleness), then reads the seller's carrying-cost
    pressure to distinguish circumstantial motivation from financial distress."""
    if cfg is None or dom_days is None or dom_days <= 0:
        return None
    if not (price_drop_pct >= cfg["motivated_price_drop_pct"]
            and dom_days <= cfg["motivated_max_dom_days"]):
        return None
    if monthly_bleed is not None and monthly_bleed < cfg["low_monthly_bleed_threshold"]:
        return ("Large fast price reduction with minimal carrying-cost pressure "
                "suggests circumstantial motivation (estate/retirement/relocation); "
                "aggressive offers may be entertained.")
    return ("Large fast price reduction alongside significant monthly carrying costs "
            "points to financial pressure on the seller; the discount likely reflects "
            "urgency to exit and is more defensible in negotiation.")


def _staleness_read(dom_band: str, drop_band: str, liquidity_band: str,
                    is_high_income_conf: bool):
    """Neutral, factual synthesis of the time-on-market / large-discount signals —
    states what they imply, never a buy/pass recommendation. Returns None when
    neither a stale listing nor a notable (large/severe) reduction is present."""
    dom_stale    = dom_band == "stale"
    drop_notable = drop_band in ("large", "severe")
    if not (dom_stale or drop_notable):
        return None

    if dom_stale and drop_notable:
        signal_desc = "Extended time on market combined with a significant price reduction"
    elif dom_stale:
        signal_desc = "Extended time on market"
    else:
        signal_desc = f"A {drop_band} price reduction"

    if is_high_income_conf and liquidity_band == "liquid":
        return (f"{signal_desc} is consistent with a motivated seller in a liquid market; "
                f"this may represent a genuine negotiating opportunity.")

    reasons = []
    if not is_high_income_conf:
        reasons.append("unverified or imputed income")
    if liquidity_band == "thin":
        reasons.append("limited market liquidity")
    reason_desc = " and ".join(reasons) if reasons else "unverified underlying fundamentals"
    return (f"{signal_desc} warrants further diligence given {reason_desc}; "
            f"the discount should not be assumed favourable without verification.")


def _deal_context_read(dom_band: str, drop_band: str, liquidity_band: str,
                       is_high_income_conf: bool, price_drop_pct: float = 0.0,
                       dom_days: float = 0.0, monthly_bleed=None,
                       screener_cfg: dict = None) -> str:
    """Combined Deal Context read. The fast-price-cut (velocity) trigger and the
    staleness/large-discount trigger are independent — both can fire, and their
    sentences are concatenated. Falls back to a neutral no-signal line."""
    reads = [
        r for r in (
            _motivated_seller_read(price_drop_pct, dom_days, monthly_bleed, screener_cfg),
            _staleness_read(dom_band, drop_band, liquidity_band, is_high_income_conf),
        ) if r
    ]
    return " ".join(reads) if reads else "No notable time-on-market or price-reduction signal."


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

    def score_property(self, p: dict, _compute_select: bool = True,
                       _covenant_override=None) -> dict:
        """
        Score a saved property record (0-100).
        Returns {"score": float|None, "breakdown": {}, "weights": {}, ...metrics}.

        For a CMHC MLI-eligible record the primary score is **MLI Standard** (the
        ranking basis) and an **MLI Select** upside score is computed from
        ``select_results`` (Fix 3); ``_compute_select`` / ``_covenant_override`` are
        internal knobs used when recursively scoring that Select variant.
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
        # Fix 2: score cash flow as a SIZE-RELATIVE measure (% of asking price),
        # not absolute dollars. Absolute $ let a $20M deal trivially clear a $50k
        # bar a $5M deal never could — the factor rewarded size, not performance.
        # The ramp [-6, 8]% is symmetric enough to preserve rank order for the
        # negative (money-losing) tail instead of clamping it all to one 0.
        asking_price = p.get("asking_price") or 0
        cf_pct_price = (cf_annual / asking_price * 100.0) if asking_price else 0.0
        price_drop = val("Price Drop %")
        dom        = val(METRIC_MARKET_STALENESS, 0)

        city      = (p.get("city") or "").lower()
        distances = self.load_city_distances()
        dist_info = distances.get(city)
        dist_km   = dist_info["distance_km"] if dist_info else None
        s_loc     = component("Location", dist_km, invert=True) if dist_km is not None else 0.0

        # Financing Robustness (Fix 6): a pre-normalised 0-100 sub-score computed
        # in the analyzer (rate + amortization break-even margins vs the per-type
        # covenant), stored top-level. It takes the scoring weight vacated by DSCR
        # and Cash Flow — CoCR / DSCR / Cash Flow are three views of the same
        # NOI-minus-debt-service relationship, so the model scores CoCR and this
        # robustness factor and DISPLAYS DSCR / Cash Flow (weight 0).
        #
        # A record analysed BEFORE this factor existed has NO stored value. That is
        # "not yet measured", not a real 0 — substituting 0 would silently dock the
        # deal ~20%. When it is absent (pending) we DROP the factor and renormalise
        # the remaining ones to their original relative weights (see active_w
        # below), and flag it so the breakdown reads "Pending re-analysis" instead
        # of a fake 0.0 bar. A stored 0.0 is a genuine measurement and is kept.
        robustness = p.get("financing_robustness")
        robustness_pending = robustness is None
        s_robust = 0.0 if robustness_pending else clamp(robustness / 10.0, 0, 10)

        scores = {
            "Cap Rate":        component("Cap Rate",        cap_rate),
            "CoCR":            component("CoCR",            coc),
            "DSCR":            component("DSCR",            dscr),
            "IRR":             component("IRR", irr) if irr is not None else 0.0,
            "Equity Multiple": component("Equity Multiple", em),
            "Cash Flow":       component("Cash Flow",       cf_pct_price),
            "Financing Robustness": s_robust,
            "Price Drop":      component("Price Drop",      price_drop),
            "DOM":             component("DOM",             dom),
            "Location":        s_loc,
        }

        active_w = {k: w for k, w in weights.items() if w > 0}
        if robustness_pending:
            # Un-measured factor excluded; the weighted average over what remains
            # renormalises the other factors to their original relative weights,
            # so the stale record scores on the factors it actually has.
            active_w.pop("Financing Robustness", None)
        total_w  = sum(active_w.values())
        score    = 0.0
        if total_w > 0:
            score = sum(scores[k] * (w / total_w) for k, w in active_w.items()) * 10

        # Data-confidence axis (Issue 2): a separate, bounded haircut for income
        # built on imputed (city-average) rents vs. stated/measured ones. Applied
        # to the overall score only — every graded row above is unaffected.
        confidence_multiplier = p.get("confidence_multiplier")
        raw_score = round(score, 1)

        # Market/listing-signal confidence axis: DOM and Price Drop carry no
        # fixed sign (a stale/discounted listing can be an opportunity or a
        # warning) so they are NOT weighted into the raw score above (see
        # json/score_weights.json — both weights are 0). Instead they AMPLIFY
        # whatever confidence haircut already exists from income/cap-rate —
        # they never create one on their own. That's what keeps a clean,
        # liquid, fully-verified deal's score untouched even with a long DOM
        # or a big price cut.
        underwriting_cfg = load_underwriting_config()
        verified_income_pct = p.get("verified_income_pct")
        cap_rate_risk_threshold = underwriting_cfg["cap_rate_risk_threshold_pct"]
        cap_rate_flagged = cap_rate > cap_rate_risk_threshold
        # Income confidence is an INCOME-only axis — it must not be gated on cap
        # rate. Cap-rate risk already gets its own direct, graduated haircut
        # (see IncomeConfidenceMetrics); folding it in here would penalize it a
        # second time by proxy, via the DOM/price-drop amplifier below.
        is_high_income_conf = (
            verified_income_pct is not None
            and verified_income_pct >= underwriting_cfg["market_signal_verified_income_threshold_pct"]
        )
        demographics = self.load_city_demographics()
        demo = demographics.get(city)
        liquidity_band, liquidity_thinness = _liquidity_band(dist_km, demo, underwriting_cfg)
        dom_band = _dom_band(dom, underwriting_cfg)
        drop_band = _drop_band(price_drop, underwriting_cfg)
        dom_stale = dom_band == "stale"
        drop_triggered = drop_band in ("large", "severe")

        # The market-signal amplifier only engages on genuine low confidence:
        # either income itself is unverified/imputed below threshold, or at
        # least `amplifier_engage_min_signals` independent risk signals stack
        # up (e.g. high cap rate AND a thin market). A lone cap-rate flag by
        # itself must not open the amplifier — that would double-count it.
        risk_signal_count = int(cap_rate_flagged) + int(liquidity_band == "thin")
        amplifier_should_engage = (
            (underwriting_cfg["low_income_conf_always_engages_amplifier"] and not is_high_income_conf)
            or risk_signal_count >= underwriting_cfg["amplifier_engage_min_signals"]
        )

        market_signal_multiplier = 1.0
        if (dom_stale or drop_triggered) and amplifier_should_engage:
            factor = 1.0
            if dom_stale:
                factor *= underwriting_cfg["dom_stale_confidence_factor"]
            if drop_triggered:
                factor *= underwriting_cfg["price_drop_confidence_factor"]
            if dom_stale and drop_triggered:
                factor *= underwriting_cfg["joint_signal_confidence_factor"]
            if liquidity_band == "thin":
                factor *= underwriting_cfg["thin_market_confidence_factor"]
            market_signal_multiplier = max(underwriting_cfg["market_signal_confidence_floor"], factor)

        if confidence_multiplier is None and market_signal_multiplier == 1.0:
            adjusted_score = raw_score
        else:
            combined_multiplier = (confidence_multiplier if confidence_multiplier is not None else 1.0) \
                * market_signal_multiplier
            adjusted_score = round(score * combined_multiplier, 1)

        # Monthly seller bleed = the per-month carrying cost of the vacant share,
        # recovered from the stored cumulative "Seller Bleed" (which spans the full
        # DOM) so the Read can gauge financial pressure. None when DOM is 0.
        seller_bleed_total = val(METRIC_SELLER_BLEED, 0.0)
        monthly_bleed = (seller_bleed_total * 30.0 / dom) if dom > 0 else None
        screener_cfg = load_screener_config()
        deal_context_read = _deal_context_read(
            dom_band, drop_band, liquidity_band, is_high_income_conf,
            price_drop_pct=price_drop, dom_days=dom, monthly_bleed=monthly_bleed,
            screener_cfg=screener_cfg,
        )

        # ── Covenant score cap (post-hoc GATE, applied LAST) ─────────────────
        # Covenant compliance is a gate, not a factor strong returns can outweigh:
        # a deal whose current (unstressed) DSCR is below its per-asset-type
        # covenant cannot cover debt service at today's rates, so its final score
        # is capped — it must not present as mid-tier-or-better on projected IRR/EM.
        # This is NOT a return to weighted DSCR scoring (DSCR stays display-only,
        # weight 0 — the collinearity fix is intact); it only clamps the ceiling.
        # The covenant is resolved from config (financing.json per-type
        # `covenant_dscr`), never hardcoded. The cap FLOORS nothing (min only). A
        # missing / "N/A (no debt)" DSCR reads as None and is skipped, so an absent
        # value can never trigger a false cap on a pending/stale record.
        covenant_cap = cfg.get("covenant_score_cap", 60.0)
        _dscr_row = results.get("DSCR")
        current_dscr = None
        if _dscr_row:
            _dc = "".join(c for c in str(_dscr_row.get("value", "")) if c.isdigit() or c in ".-")
            current_dscr = float(_dc) if _dc else None

        # Resolve financing once — reused for the covenant cap AND the MLI Select
        # covenant (dual scoring). Skipped when a covenant override is supplied
        # (the recursive Select pass) or nothing needs it.
        _fin = None
        if _covenant_override is None and (current_dscr is not None or p.get("select_results")):
            _um = p.get("unit_mix") or {}
            _units = sum(_um.get(k, 0) or 0 for k in
                         ("bachelor", "one_br", "two_br", "three_br", "four_br", "unknown"))
            _share = mixed_use_commercial_gfa_share(
                p.get("property_type"), _um.get("floors", p.get("floors", 1)))
            _fin = resolve_financing(p.get("asking_price") or 0, p.get("property_type"),
                                     _units, commercial_gfa_share=_share)

        covenant_dscr = (_covenant_override if _covenant_override is not None
                         else (_fin.get("covenant_dscr") if _fin else None))
        covenant_capped = False
        if (current_dscr is not None and covenant_dscr is not None
                and current_dscr < covenant_dscr and adjusted_score > covenant_cap):
            adjusted_score = covenant_cap
            covenant_capped = True

        # ── Fix 3: MLI Select UPSIDE score (dual scoring) ────────────────────
        # Rank on the Standard score above; also score the Select variant of the
        # results (same income/cap — only debt-side rows differ) against the 1.10
        # Select covenant, and report the gap as a financing-upside signal.
        select_score = select_gap = None
        if _compute_select and p.get("select_results"):
            sel_cov = (_fin.get("select") or {}).get("covenant_dscr") if _fin else None
            sel_variant = {**p, "results": p["select_results"],
                           "financing_robustness": p.get("select_financing_robustness")}
            sel_scored = self.score_property(sel_variant, _compute_select=False,
                                             _covenant_override=sel_cov)
            select_score = sel_scored.get("score")
            if select_score is not None and adjusted_score is not None:
                select_gap = round(select_score - adjusted_score, 1)

        # A pending robustness factor is rendered as None (not 0.0) so the score
        # breakdown can show "Pending re-analysis" instead of a fake zero bar.
        breakdown = {k: round(scores[k] * 10, 1) for k in scores}
        if robustness_pending:
            breakdown["Financing Robustness"] = None

        return {
            "score":       adjusted_score,
            "raw_score":   raw_score,
            "confidence_multiplier": confidence_multiplier,
            "verified_income_pct":   verified_income_pct,
            "breakdown":   breakdown,
            "robustness_pending": robustness_pending,
            "covenant_capped": covenant_capped,
            "covenant_dscr":   covenant_dscr,
            # Fix 3 dual scoring: MLI Select upside score + gap over the Standard
            # (ranking) score. None for deals that are not CMHC MLI-eligible.
            "mli_eligible":    p.get("select_results") is not None,
            "select_score":    select_score,
            "select_gap":      select_gap,
            "weights":     weights,
            "income_confidence": p.get("income_confidence"),
            "cap_rate":    cap_rate,
            "coc":         coc,
            "dscr":        dscr,
            "irr":         irr,
            "em":          em,
            "cf_annual":   cf_annual,
            "cf_pct_price": round(cf_pct_price, 4),
            "price_drop":  price_drop,
            "dom":         int(dom),
            "dist_km":     dist_km,
            "dist_centre": dist_info["nearest_centre"] if dist_info else None,
            "dom_band":                dom_band,
            "price_drop_band":         drop_band,
            "liquidity_band":          liquidity_band,
            "market_signal_multiplier": round(market_signal_multiplier, 4),
            "deal_context_read":       deal_context_read,
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
                # Carry BOTH the re-scored results and the recomputed robustness
                # sub-score (Fix 6) so the lever search reflects financing fragility.
                rec.update({k: v for k, v in new_rec.items()
                            if k in ("results", "financing_robustness")})
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
