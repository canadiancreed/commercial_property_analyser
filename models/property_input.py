from dataclasses import dataclass, field
from typing import Optional
from models.constants import EXPENSE_RATIO_DEFAULTS, VACANCY_RATE_DEFAULTS


@dataclass
class UnitMix:
    """
    Describes the residential unit composition of a property.
    Counts per unit type are required. Monthly rent overrides are optional —
    if omitted, the city market rate from residential_rents.json is used.
    """
    bachelor:      int            = 0
    one_br:        int            = 0
    two_br:        int            = 0
    three_br:      int            = 0
    four_br:       int            = 0
    unknown:       int            = 0

    bachelor_rent:  Optional[float] = None
    one_br_rent:    Optional[float] = None
    two_br_rent:    Optional[float] = None
    three_br_rent:  Optional[float] = None
    four_br_rent:   Optional[float] = None
    unknown_rent:   Optional[float] = None

    floors:        int             = 1

    @property
    def total_units(self) -> int:
        return self.bachelor + self.one_br + self.two_br + self.three_br + self.four_br + self.unknown

    def unit_types(self) -> list:
        return [
            ("bachelor",  self.bachelor,  self.bachelor_rent),
            ("one_br",    self.one_br,    self.one_br_rent),
            ("two_br",    self.two_br,    self.two_br_rent),
            ("three_br",  self.three_br,  self.three_br_rent),
            ("four_br",   self.four_br,   self.four_br_rent),
            ("unknown",   self.unknown,   self.unknown_rent),
        ]


@dataclass
class PropertyInput:
    original_price:   float
    asking_price:     float
    total_sq_ft:      float
    property_taxes:   float
    down_payment_pct: float             # e.g. 0.25 for 25%
    interest_rate:    float             # e.g. 0.0725 for 7.25%
    term_years:       int
    annual_rent:      Optional[float]   = None
    commercial_rent:  Optional[float]   = None
    residential_rent: Optional[float]   = None
    city:             Optional[str]     = None
    province:         Optional[str]     = None
    property_type:    Optional[str]     = None
    unit_mix:         Optional[UnitMix] = None
    address:          str               = ""
    mls_number:       str               = ""
    status:           str               = "active"
    expense_ratio:    Optional[float]   = None
    lease_type:       str               = "Normal"
    exit_cap_rate:    Optional[float]   = None
    market_cap_rate:  Optional[float]   = None
    listing_date:     str               = ""
    hold_years:       int               = 5
    noi_growth_rate:  Optional[float]   = None  # None = resolve from city demographics
    construction_cost: float            = 0.0
    hotel_rooms:      int               = 0
    hotel_adr:        Optional[float]   = None
    hotel_occupancy:  Optional[float]   = None
    ind_warehouse_sqft:   float         = 0.0
    ind_office_sqft:      float         = 0.0
    ind_yard_sqft:        float         = 0.0
    ind_dock_doors:       int           = 0
    ind_drive_in_doors:   int           = 0
    ind_clear_height_ft:  float         = 0.0
    ind_office_rate:      Optional[float] = None
    ind_yard_rate:        Optional[float] = None
    vacancy_rate:              Optional[float] = None  # None = resolve from property type
    commercial_rent_user_entered:  bool        = False
    residential_rent_user_entered: bool        = False
    # Optional commercial-tenant lease expiry (mixed-use / commercial). Passthrough
    # only — populated from listing data if present, never fetched externally. When
    # absent the card renders "unknown ⚠" (an unknown single-tenant term is itself a
    # binary-vacancy signal).
    commercial_lease_expiry:   Optional[str]   = None

    @property
    def rent_manually_entered(self) -> bool:
        return self.commercial_rent_user_entered or self.residential_rent_user_entered

    # Residential asset classes whose maintenance obligations are non-waivable
    # (Ontario RTA 2006): a net/NNN lease tag can only describe a commercial lease,
    # so it must NOT collapse a residential property's expense ratio to the NNN
    # near-zero default. (Mixed-use handles this per-component in MixedUseComponents.)
    _RESIDENTIAL_TYPES = frozenset({"multi-family", "residential"})

    def __post_init__(self):
        ptype = (self.property_type or "").strip().lower()
        if self.expense_ratio is None:
            if self.lease_type.upper() == "NNN" and ptype not in self._RESIDENTIAL_TYPES:
                self.expense_ratio = EXPENSE_RATIO_DEFAULTS["nnn"]
            else:
                self.expense_ratio = EXPENSE_RATIO_DEFAULTS.get(ptype, 0.40)
