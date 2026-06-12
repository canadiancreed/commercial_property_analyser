# Sources:
#   Expense ratio defaults and ranges:
#     - BOMA International Experience Exchange Report (EER) 2023 — office, industrial
#     - REALPAC Annual Income & Expense Study 2023 — Canadian commercial benchmarks
#     - CBRE Canada Market Outlook 2023/2024 — retail, mixed-use, hotel
#     - CMHC Rental Market Report 2023 — multi-family residential
#     - STR / CoStar Hotel Operating Statistics 2023 — hotel OER benchmarks
#   NNN vs. gross lease split:
#     - NAIOP Research Foundation, "Net Lease Market Update" 2023
#   Vacancy rate defaults (Canadian markets):
#     - CBRE Canada Office Figures Q4 2025 — office ~14%
#       https://www.cbre.ca/insights/figures/canada-office-figures-q4-2025
#     - Colliers / JLL Canada Q1 2026 — industrial ~4–5%
#       https://www.jll.com/en-ca/insights/market-outlook/canada-real-estate
#     - CMHC 2025 Rental Market Report — multi-family/residential ~3%
#       https://www.cmhc-schl.gc.ca/media-newsroom/news-releases/2025/canadas-vacancy-rate-rises-amid-historically-high-rental-construction
#     - Mixed-use/retail-office blended (office + retail average): ~9%
#     - Hotel excluded: uses occupancy rate (RevPAR/ADR model), not vacancy

# Default vacancy rate by property type (Canadian market, 2025/Q1 2026).
# Hotel is 0.0 — it uses occupancy rate (RevPAR/ADR model), not vacancy.
# NNN leases share the underlying property-type vacancy; tenant absorbs the
# income impact via lease structure, but the asset still faces market vacancy.
VACANCY_RATE_DEFAULTS = {
    "office":        0.14,   # CBRE Canada Q4 2025: national avg ~13.6%
    "retail":        0.05,   # CBRE/Colliers Canada 2025: ~4–6%
    "industrial":    0.05,   # JLL/Colliers Canada Q1 2026: ~3.5–5.2%
    "mixed-use":     0.09,   # Blended office + retail average
    "retail-office": 0.09,   # Blended office + retail average
    "multi-family":  0.03,   # CMHC 2025 Rental Market Report: ~3.1%
    "residential":   0.03,   # CMHC 2025 Rental Market Report: ~3.1%
    "hotel":         0.00,   # Excluded — modelled via occupancy rate instead
}

PROP_SHORTCUTS = {
    "o":  "Office",
    "r":  "Retail",
    "i":  "Industrial",
    "m":  "Mixed-Use",
    "re": "Residential",
    "mu": "Multi-Family",
    "h":  "Hotel",
    "ro": "Retail-Office",
}

PROPERTY_TYPES = set(PROP_SHORTCUTS.values())

# Commercial types that are resolved via $/sqft market rates.
# Residential and Multi-Family are excluded — they use unit-mix rent resolution.
COMMERCIAL_TYPES = {"Office", "Retail", "Industrial", "Mixed-Use", "Hotel", "Retail-Office"}
COMMERCIAL_TYPES_LOWER = {t.lower() for t in COMMERCIAL_TYPES}

# Default expense ratio (as a decimal) used when the user does not supply one.
# Represents the mid-point of the typical operating range for each asset class.
# NNN lease types override the property-type default (owner expenses near zero).
EXPENSE_RATIO_DEFAULTS = {
    # BOMA EER 2023: gross-lease office OER typically 38–45%
    "office":       0.42,
    # CBRE Canada 2023: gross-lease retail OER typically 35–42%
    "retail":       0.38,
    # BOMA EER 2023: industrial (gross lease) OER typically 28–38%
    "industrial":   0.33,
    # REALPAC 2023: mixed-use blended OER typically 38–45%
    "mixed-use":    0.42,
    # REALPAC / CMHC 2023: retail-office blended OER typically 38–44%
    "retail-office":0.41,
    # CMHC Rental Market Report 2023: multi-family OER typically 40–50%
    "multi-family": 0.45,
    # CMHC 2023: single-family residential rental OER typically 35–45%
    "residential":  0.40,
    # STR / CoStar 2023: full-service hotel OER typically 60–68%; limited-service 55–62%
    "hotel":        0.63,
    # NNN leases — tenant covers most operating costs; owner retains ~5–12%
    # NAIOP 2023: NNN retail/office landlord expenses typically 5–12%
    "nnn":          0.08,
}

# Plausible (min, max) range for expense ratio by property type.
# Values outside this range trigger a warning in the analysis report.
EXPENSE_RATIO_RANGES = {
    # BOMA EER 2023
    "office":        (0.32, 0.50),
    # CBRE Canada 2023
    "retail":        (0.28, 0.48),
    # BOMA EER 2023
    "industrial":    (0.22, 0.42),
    # REALPAC 2023
    "mixed-use":     (0.35, 0.52),
    # REALPAC 2023
    "retail-office": (0.32, 0.50),
    # CMHC 2023
    "multi-family":  (0.38, 0.55),
    # CMHC 2023
    "residential":   (0.30, 0.50),
    # STR / CoStar 2023
    "hotel":         (0.55, 0.72),
    # NAIOP 2023
    "nnn":           (0.04, 0.15),
}
