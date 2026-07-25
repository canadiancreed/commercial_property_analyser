"""
Financing robustness (Fix 6) + break-even financing diagnostic (Fix 5).

Both read the same break-even maths, so they live together. The premise: a deal's
financing FRAGILITY is a property of the deal, not a footnote — a deal that only
pencils at a low rate and a stretched amortization is worse than one that pencils
at a higher rate and a shorter one, even if today they look identical.

Two *separate* exposures are measured, never blended into one number:

  • Rate risk — SCHEDULED and CERTAIN. The term matures on a known date and renews
    at the market rate. Weighted more.
  • Amortization risk — CONDITIONAL. Only bites on a forced refinance into a
    shorter schedule. Weighted less.

For each exposure two break-even points are found:

  1. Covenant breach — the move at which DSCR falls to the per-type covenant.
  2. Cash-flow zero — the move at which annual cash flow hits 0 (DSCR 1.00).

Covenant breach usually arrives first, while cash flow is still positive: the
lender acts before the owner feels pain. The reverse ordering means the owner can
fund the shortfall out of pocket while still in good standing. Both margins and
the spread between them are reported.

The margins are THRESHOLD-INDEPENDENT: "breaks at +180 bps" is an absolute fact
about the deal, comparable across asset classes, price bands and financing
regimes, and valid regardless of whether the other scoring ramps are calibrated.
That is why this factor takes weight from the collinear CoCR/DSCR/Cash-Flow group.
"""
from models.report_row import ReportRow
from analysis.metrics.grader import Grader
from analysis.mortgage import amortization_payment

_MINUS = "−"   # real minus sign, matches the rest of the reports


class FinancingRobustness:
    """Break-even financing analysis for one deal.

    ``noi`` is Year-1 NOI; ``loan_amount`` the mortgage principal; ``annual_rate``
    the contract rate; ``amort_years`` the amortization; ``covenant_dscr`` the
    per-type covenant (resolve_financing → ``covenant_dscr``). ``rate_low`` /
    ``rate_high`` are the type's realistic rate band, used to categorise a deal as
    passing / conditional / failing-under-all-realistic-terms.
    """

    def __init__(self, noi, loan_amount, annual_rate, amort_years, covenant_dscr,
                 compounding="semi-annual", rate_low=None, rate_high=None,
                 rate_ref_bps=250.0, amort_ref_years=10.0, rate_weight=0.7):
        self._noi   = noi or 0.0
        self._loan  = loan_amount or 0.0
        self._rate  = annual_rate or 0.0
        self._amort = amort_years or 0
        self._cov   = covenant_dscr or 1.0
        self._comp  = compounding
        self._rate_low  = rate_low
        self._rate_high = rate_high
        self._rate_ref_bps    = rate_ref_bps
        self._amort_ref_years = amort_ref_years
        self._rate_weight     = rate_weight

        self.has_debt = self._loan > 0 and self._amort > 0
        self.current_ads  = self._ads(self._rate, self._amort) if self.has_debt else 0.0
        self.current_dscr = (self._noi / self.current_ads) if self.current_ads > 0 else None
        self.current_cf   = self._noi - self.current_ads

        # ── Rate margins (bps the CONTRACT rate can rise) ────────────────────
        self.rate_cov_bps = self._rate_margin_bps(self._cov)   # to covenant breach
        self.rate_cf0_bps = self._rate_margin_bps(1.0)         # to cash-flow zero
        # ── Amortization margins (years the amortization can SHORTEN) ────────
        self.amort_cov_yr = self._amort_margin_yr(self._cov)
        self.amort_cf0_yr = self._amort_margin_yr(1.0)

        # Spread: covenant breach vs cash-flow zero on the rate axis. Positive =
        # the lender acts first (covenant breach arrives while CF is still +).
        self.rate_spread_bps = (
            None if (self.rate_cov_bps is None or self.rate_cf0_bps is None)
            else self.rate_cf0_bps - self.rate_cov_bps
        )

        self.score    = self._robustness_score()
        self.verdict  = self._verdict()

    # ── core maths ───────────────────────────────────────────────────────────

    def _ads(self, rate, amort_years):
        """Annual debt service on the fixed principal at (rate, amortization)."""
        return amortization_payment(self._loan, rate, int(round(amort_years * 12)),
                                    self._comp) * 12

    def _rate_margin_bps(self, target_dscr):
        """Basis points the contract rate can RISE before DSCR falls to
        ``target_dscr`` (negative if the deal is already below it). None when the
        deal has no debt or no income to cover it."""
        if not self.has_debt or self._noi <= 0:
            return None
        target_ads = self._noi / target_dscr
        # ADS rises monotonically with rate → find the rate where ADS == target.
        lo, hi = 0.0, 1.0
        if self._ads(lo, self._amort) >= target_ads:
            be_rate = 0.0                       # fails even at a 0% rate
        elif self._ads(hi, self._amort) <= target_ads:
            be_rate = hi                        # survives even at 100%
        else:
            for _ in range(80):
                mid = (lo + hi) / 2
                if self._ads(mid, self._amort) < target_ads:
                    lo = mid
                else:
                    hi = mid
            be_rate = (lo + hi) / 2
        return (be_rate - self._rate) * 10000.0

    def _amort_margin_yr(self, target_dscr):
        """Years the amortization can SHORTEN before DSCR falls to ``target_dscr``
        (negative if the deal is already below it at the current amortization)."""
        if not self.has_debt or self._noi <= 0:
            return None
        target_ads = self._noi / target_dscr
        # ADS falls monotonically as amortization lengthens → find the amort where
        # ADS == target; below it (shorter) the deal fails.
        lo, hi = 1.0, 60.0
        if self._ads(self._rate, hi) >= target_ads:
            be_amort = hi                       # fails even at a 60-yr stretch
        elif self._ads(self._rate, lo) <= target_ads:
            be_amort = lo                       # survives even at 1 yr
        else:
            for _ in range(80):
                mid = (lo + hi) / 2
                if self._ads(self._rate, mid) > target_ads:   # too short → fails
                    lo = mid
                else:
                    hi = mid
            be_amort = (lo + hi) / 2
        return self._amort - be_amort

    def _robustness_score(self):
        """0..100. Rate margin weighted more than amortization margin because rate
        risk is scheduled/certain and amortization risk is only conditional. Scored
        on the COVENANT-breach margins (the binding constraint the lender enforces).
        A no-debt deal has no financing fragility → full marks."""
        if not self.has_debt:
            return 100.0
        if self.rate_cov_bps is None:
            return 0.0
        rate_s  = max(0.0, min(1.0, self.rate_cov_bps / self._rate_ref_bps))
        amort_s = (0.0 if self.amort_cov_yr is None
                   else max(0.0, min(1.0, self.amort_cov_yr / self._amort_ref_years)))
        return round(100.0 * (self._rate_weight * rate_s
                              + (1.0 - self._rate_weight) * amort_s), 1)

    def _verdict(self):
        """Category for Fix 5: does the deal pass now, only at favourable
        obtainable terms, or under NO realistic terms?"""
        if not self.has_debt:
            return "no debt — no financing risk"
        passes_now = (self.current_dscr is not None and self.current_dscr >= self._cov
                      and self.current_cf > 0)
        if passes_now:
            return "passes at current terms"
        # Best realistic terms for the asset class: the low end of the rate band
        # at the current amortization. If it still fails there, no realistic
        # financing rescues it.
        best_rate = self._rate_low if self._rate_low is not None else self._rate
        best_rate = min(best_rate, self._rate)
        best_ads  = self._ads(best_rate, self._amort)
        best_dscr = (self._noi / best_ads) if best_ads > 0 else None
        if best_dscr is not None and best_dscr >= self._cov and (self._noi - best_ads) > 0:
            return "conditional — passes only at favourable obtainable terms"
        return "fails under all realistic terms"

    # ── rendering ────────────────────────────────────────────────────────────

    @staticmethod
    def _bps(v):
        if v is None:
            return "n/a"
        sign = "+" if v >= 0 else _MINUS
        return f"{sign}{abs(v):.0f}bps"

    @staticmethod
    def _yr(v):
        if v is None:
            return "n/a"
        sign = "+" if v >= 0 else _MINUS
        return f"{sign}{abs(v):.1f}yr"

    def glance(self):
        """One-line, at-a-glance summary (Fix 6 output format)."""
        if not self.has_debt:
            return "no debt — no rate or amortization risk"
        return (f"covenant breach {self._bps(self.rate_cov_bps)} · "
                f"cash flow zero {self._bps(self.rate_cf0_bps)} · "
                f"amortization tolerance {self._yr(self.amort_cov_yr)}")

    def _break_even_string(self):
        """Fix 5 diagnostic: the terms the deal needs, in the spirit of
        'positive at 5.50% / 30yr; negative at 6.50% / 25yr'."""
        if not self.has_debt:
            return "no debt"
        cov_rate = self._rate + (self.rate_cov_bps or 0) / 10000.0
        cf0_rate = self._rate + (self.rate_cf0_bps or 0) / 10000.0
        return (f"DSCR≥{self._cov:.2f} up to {cov_rate*100:.2f}% · "
                f"cash-flow-positive up to {cf0_rate*100:.2f}% (at {self._amort:.0f}yr)")

    def _robustness_grade(self):
        return Grader.grade(self.score, 60, 30,
                            labels=("ROBUST", "MODERATE", "FRAGILE"))

    def _verdict_grade(self):
        if self.verdict.startswith("passes"):
            return "GOOD"
        if self.verdict.startswith("conditional"):
            return "CAUTION"
        if self.verdict.startswith("no debt"):
            return "INFO"
        return "FAIL: fails all realistic terms"

    def rows(self):
        if not self.has_debt:
            return [ReportRow("Financing Robustness", "N/A (no debt)", "INFO")]
        return [
            ReportRow("Rate Risk (scheduled)",
                      f"covenant {self._bps(self.rate_cov_bps)} · "
                      f"CF-zero {self._bps(self.rate_cf0_bps)}",
                      Grader.grade(self.rate_cov_bps or 0, 150, 50)),
            ReportRow("Amortization Risk (conditional)",
                      f"covenant {self._yr(self.amort_cov_yr)} · "
                      f"CF-zero {self._yr(self.amort_cf0_yr)}",
                      Grader.grade(self.amort_cov_yr or 0, 5, 2)),
            ReportRow("Rate Margin Spread",
                      "n/a" if self.rate_spread_bps is None
                      else f"{self._bps(self.rate_spread_bps)} between covenant & CF-zero",
                      "INFO"),
            ReportRow("Break-Even Financing", self._break_even_string(),
                      self._verdict_grade()),
            ReportRow("Financing Verdict", self.verdict, self._verdict_grade()),
            ReportRow("Financing Robustness",
                      f"{self.score:.0f}/100 — {self.glance()}",
                      self._robustness_grade()),
        ]
