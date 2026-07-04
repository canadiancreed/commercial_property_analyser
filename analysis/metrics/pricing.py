from models.report_row import ReportRow
from models.constants import PROPERTY_TYPES
from analysis.metrics.grader import Grader


class PricingMetrics:

    _SQFT_THRESHOLDS = {
        "office":      (150, 300),
        "retail":      (200, 400),
        "industrial":  (80,  200),
        "mixed-use":   (175, 350),
        "retail-office": (175, 375),
        "multi-family":(100, 250),
        "residential": (150, 300),
    }
    _SQFT_DEFAULT = (150, 350)

    # GRM thresholds vary materially by asset class (Canadian market benchmarks).
    # Keys must cover every type in models.constants.PROPERTY_TYPES.
    # Hotel GRM is a weak signal — hotels trade on NOI/RevPAR — so thresholds are wide.
    _GRM_THRESHOLDS = {
        "office":        (14, 20),   # cap-rate driven; GRM 14–18 normal
        "retail":        (12, 18),
        "industrial":    (10, 16),
        "mixed-use":     (12, 18),   # blended office + retail
        "retail-office": (12, 18),
        "multi-family":  (14, 20),   # CMHC: trades ~14–18× gross rent
        "residential":   (9,  12),
        "hotel":         (18, 28),   # wide range; RevPAR/NOI is the primary metric
    }
    _GRM_DEFAULT = (9, 12)

    assert set(_GRM_THRESHOLDS) == {t.lower() for t in PROPERTY_TYPES}, (
        "GRM_THRESHOLDS keys must match PROPERTY_TYPES"
    )

    def __init__(self, prop, loan_amount: float, annual_rent: float,
                 city_rent_per_sqft: float | None = None,
                 comm_sq_ft: float | None = None):
        self._cost_basis    = prop.asking_price + (prop.construction_cost or 0)
        sqft_denominator    = comm_sq_ft if comm_sq_ft else prop.total_sq_ft
        # Square footage is mandatory — a zero here would crash or (via a silent
        # fallback) fabricate a Price/Sq Ft. Fail loudly instead.
        if not sqft_denominator or sqft_denominator <= 0:
            raise ValueError(
                f"total square footage is required and must be > 0 (got {sqft_denominator!r})"
            )
        self.pp_sqft        = self._cost_basis / sqft_denominator
        # GRM needs rent. When rent is unresolved (partial analysis for a city
        # with no rates yet) leave it as None and flag the row — never divide by
        # a silent stand-in like 1, which used to print GRM == cost basis.
        self.grm            = self._cost_basis / annual_rent if annual_rent and annual_rent > 0 else None
        self.price_drop_pct = ((prop.original_price - prop.asking_price) / prop.original_price) * 100
        self.tax_load       = (prop.property_taxes / prop.asking_price) * 100
        # Loan-to-Value is the ORIGINATION ratio (loan advanced / price), which
        # is what "LTV" means in underwriting and what the 70/80 grading below is
        # calibrated to. It must NOT be fed the amortized-down remaining balance:
        # when hold_years >= term_years the mortgage is fully paid off, the
        # remaining balance is a genuine 0, and LTV would read a misleading 0.00%
        # for the whole portfolio. Origination LTV keeps the ltv + down/price == 1
        # identity holding for every property.
        self.ltv_ratio      = (loan_amount / prop.asking_price) * 100
        ptype               = (prop.property_type or "").strip().lower()
        self._grm_good,  self._grm_poor  = self._GRM_THRESHOLDS.get(ptype, self._GRM_DEFAULT)
        if city_rent_per_sqft and city_rent_per_sqft > 0:
            self._sqft_good = self._grm_good * city_rent_per_sqft
            self._sqft_poor = self._grm_poor * city_rent_per_sqft
        else:
            self._sqft_good, self._sqft_poor = self._SQFT_THRESHOLDS.get(ptype, self._SQFT_DEFAULT)
        self._ptype_label   = prop.property_type or "Property"
        self._show_sqft     = ptype not in {"hotel", "residential", "multi-family"}

    def rows(self) -> list:
        rows = []
        if self._show_sqft:
            rows.append(ReportRow(f"Price/Sq Ft ({self._ptype_label})",
                                  f"${self.pp_sqft:.2f}",
                                  Grader.grade(self.pp_sqft, self._sqft_good, self._sqft_poor,
                                               higher_is_better=False,
                                               labels=("GOOD", "FAIR", "POOR/PREMIUM"))))
        grm_value = "N/A (no rent)" if self.grm is None else f"{self.grm:.2f}"
        grm_grade = ("WARN — no rent resolved" if self.grm is None else
                     Grader.grade(self.grm, self._grm_good, self._grm_poor,
                                  higher_is_better=False))
        rows += [
            ReportRow("GRM",           grm_value, grm_grade),
            ReportRow("Tax Load",      f"{self.tax_load:.2f}%",
                      Grader.grade(self.tax_load, 2.0, 3.0, higher_is_better=False)),
            ReportRow("Price Drop %",  f"{self.price_drop_pct:.2f}%",
                      Grader.grade(self.price_drop_pct, 10, 0)),
            ReportRow("Loan to Value", f"{self.ltv_ratio:.2f}%",
                      Grader.grade(self.ltv_ratio, 70, 80, higher_is_better=False,
                                   labels=("GOOD", "FAIR", "POOR/RISKY"))),
        ]
        return rows
