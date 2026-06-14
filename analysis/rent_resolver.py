from models.property_input import PropertyInput, UnitMix
from data.store import CommercialRentLoader, ResidentialRentLoader
from models.constants import COMMERCIAL_TYPES_LOWER
from analysis.industrial_config import resolve_size_band


class RentResolver:
    """
    Resolves annual gross rent from whichever input mode is used:

    Mode 1 — Direct:       annual_rent provided explicitly
    Mode 2 — Commercial:   city + province + property_type → $/sqft × total_sq_ft
    Mode 3 — Residential:  unit_mix with counts (and optional per-type rent overrides)
    Mode 4 — Mixed-Use:    property_type + unit_mix + floors
    """

    UNIT_LABELS = {
        "bachelor": "Bachelor", "one_br": "1BR", "two_br": "2BR",
        "three_br": "3BR",      "four_br": "4BR", "unknown": "Unknown",
    }

    def __init__(self, commercial_loader: CommercialRentLoader,
                 residential_loader: ResidentialRentLoader,
                 data_store=None):
        self._commercial  = commercial_loader
        self._residential = residential_loader
        self._store       = data_store

    def resolve(self, prop: PropertyInput) -> tuple:
        """Returns (annual_rent: float, breakdown: list[str])."""
        self._city_rent_per_sqft: float | None = None
        self._comm_sq_ft: float | None = None
        # Industrial provenance (set only when an industrial market rate is used).
        self._industrial_base_rate: float | None = None
        self._industrial_size_band: str | None = None
        self._industrial_size_multiplier: float | None = None
        self._industrial_size_downgrade: bool = False
        self._industrial_rate_source: str | None = None
        has_units = prop.unit_mix is not None and prop.unit_mix.total_units > 0
        residential_income_recorded = prop.residential_rent is not None and prop.residential_rent > 0
        needs_residential_recalc = has_units and not residential_income_recorded

        comm_frozen = prop.commercial_rent_user_entered and prop.commercial_rent is not None
        res_frozen  = prop.residential_rent_user_entered and prop.residential_rent is not None \
                      and not needs_residential_recalc

        # Both components user-entered (or flagged with no residential value) — full short-circuit.
        if prop.commercial_rent_user_entered and prop.residential_rent_user_entered \
                and not needs_residential_recalc:
            comm = prop.commercial_rent or 0.0
            res  = prop.residential_rent or 0.0
            self._comm_rent = comm
            self._res_rent  = res
            parts = []
            if comm: parts.append(f"Commercial rent provided directly: ${comm:,.2f}/yr")
            if res:  parts.append(f"Residential rent provided directly: ${res:,.2f}/yr")
            return comm + res, parts or ["Rent provided directly"]

        if prop.annual_rent is not None:
            self._comm_rent = prop.annual_rent
            self._res_rent  = 0.0
            return prop.annual_rent, ["Rent provided directly"]

        ptype           = (prop.property_type or "").strip().lower()
        has_commercial  = ptype in COMMERCIAL_TYPES_LOWER
        has_residential = prop.unit_mix is not None and prop.unit_mix.total_units > 0

        is_mixed = has_commercial and has_residential

        if ptype == "hotel":
            if comm_frozen:
                self._comm_rent = prop.commercial_rent
                self._res_rent  = 0.0
                return prop.commercial_rent, [f"Commercial rent provided directly: ${prop.commercial_rent:,.2f}/yr"]
            rooms     = prop.hotel_rooms or 0
            adr       = prop.hotel_adr or 0.0
            occupancy = prop.hotel_occupancy or 0.0
            if rooms and adr and occupancy:
                revenue   = rooms * adr * occupancy * 365
                breakdown = [
                    f"Hotel: {rooms} rooms × ${adr:.0f} ADR × {occupancy*100:.0f}% occ × 365 = ${revenue:,.0f}/yr"
                ]
                self._comm_rent = revenue
                self._res_rent  = 0.0
                return revenue, breakdown
            elif prop.annual_rent:
                self._comm_rent = prop.annual_rent
                self._res_rent  = 0.0
                return prop.annual_rent, ["Hotel revenue provided directly"]
            else:
                raise ValueError(
                    "Hotel requires hotel_rooms, hotel_adr, and hotel_occupancy "
                    "(or annual_rent as fallback)."
                )

        if not has_commercial and not has_residential:
            raise ValueError(
                "Provide annual_rent, property_type, unit_mix, or both (mixed-use)."
            )
        if not comm_frozen and not res_frozen and not all([prop.city, prop.province]):
            raise ValueError("city and province required for market-rate lookup.")
        if (has_commercial and not comm_frozen) or (has_residential and not res_frozen):
            if not all([prop.city, prop.province]):
                raise ValueError("city and province required for market-rate lookup.")
        city     = prop.city
        province = prop.province

        breakdown  = []
        comm_total = 0.0
        res_total  = 0.0

        if is_mixed:
            mix         = prop.unit_mix
            floor_sq_ft = prop.total_sq_ft / mix.floors
            if comm_frozen:
                comm_total = prop.commercial_rent
                breakdown.append(f"Commercial rent provided directly: ${comm_total:,.2f}/yr")
            else:
                comm_rate = self._commercial.get_rent_per_sqft(city, province, prop.property_type)
                if comm_rate is None:
                    self._log_missing(city, province, "commercial", [prop.property_type])
                    if self._residential.get_rates(city, province) is None:
                        self._log_missing(city, province, "residential")
                    breakdown.append(f"  ⚠ Commercial rate missing for {city} ({prop.property_type}) — skipped")
                else:
                    comm_total = comm_rate * floor_sq_ft
                    self._city_rent_per_sqft = comm_rate
                    self._comm_sq_ft = floor_sq_ft
                    breakdown.append(
                        f"Commercial (ground floor {floor_sq_ft:,.0f} sq ft "
                        f"@ ${comm_rate}/sq ft): ${comm_total:,.2f}/yr"
                    )
            if res_frozen:
                res_total = prop.residential_rent
                breakdown.append(f"Residential rent provided directly: ${res_total:,.2f}/yr")
            else:
                res_total, res_lines = self._resolve_residential(city, province, mix)
                breakdown.extend(res_lines)

        elif has_residential:
            if res_frozen:
                res_total = prop.residential_rent
                breakdown.append(f"Residential rent provided directly: ${res_total:,.2f}/yr")
            else:
                res_total, res_lines = self._resolve_residential(city, province, prop.unit_mix)
                breakdown.extend(res_lines)

        elif ptype == "retail-office":
            if comm_frozen:
                comm_total = prop.commercial_rent
                breakdown.append(f"Commercial rent provided directly: ${comm_total:,.2f}/yr")
            else:
                floors      = (prop.unit_mix.floors if prop.unit_mix else 1) or 1
                floor_sq_ft = prop.total_sq_ft / floors
                retail_rate = self._commercial.get_rent_per_sqft(city, province, "Retail")
                office_rate = self._commercial.get_rent_per_sqft(city, province, "Office")
                missing = []
                if retail_rate is None: missing.append("Retail")
                if office_rate is None: missing.append("Office")
                if missing:
                    self._log_missing(city, province, "commercial", missing)
                    raise ValueError(
                        f"No {' or '.join(missing)} rate for {city}, {province}. "
                        "Use menu option 7 to add rates."
                    )
                ground_total  = retail_rate * floor_sq_ft
                office_floors = floors - 1
                office_total  = office_rate * floor_sq_ft * office_floors if office_floors > 0 else 0
                comm_total    = ground_total + office_total
                breakdown.append(
                    f"Ground floor Retail ({floor_sq_ft:,.0f} sq ft @ ${retail_rate}/sq ft): ${ground_total:,.2f}/yr"
                )
                if office_floors > 0:
                    breakdown.append(
                        f"Upper {office_floors} floor{'s' if office_floors > 1 else ''} Office "
                        f"({floor_sq_ft * office_floors:,.0f} sq ft @ ${office_rate}/sq ft): ${office_total:,.2f}/yr"
                    )

        else:
            if comm_frozen:
                comm_total = prop.commercial_rent
                breakdown.append(f"Commercial rent provided directly: ${comm_total:,.2f}/yr")
            else:
                rate = self._commercial.get_rent_per_sqft(city, province, prop.property_type)
                if rate is None:
                    self._log_missing(city, province, "commercial", [prop.property_type])
                    if self._residential.get_rates(city, province) is None:
                        self._log_missing(city, province, "residential")
                    raise ValueError(
                        f"No commercial rate for {city}, {province} ({prop.property_type}). "
                        f"Use menu option 7 to add rates."
                    )
                if ptype == "industrial":
                    band, mult, downgrade = resolve_size_band(
                        prop.total_sq_ft, prop.ind_dock_doors,
                        prop.ind_drive_in_doors, prop.ind_office_sqft,
                    )
                    effective = rate * mult
                    self._industrial_base_rate       = rate
                    self._industrial_size_band        = band
                    self._industrial_size_multiplier  = mult
                    self._industrial_size_downgrade   = downgrade
                    self._industrial_rate_source      = self._commercial.get_rate_source(city, province)
                    self._city_rent_per_sqft          = effective
                    comm_total = effective * prop.total_sq_ft
                    note = " — multi-tenant signal, confidence lowered" if downgrade else ""
                    breakdown.append(
                        f"Industrial {band}: ${rate}/sq ft × {mult:.2f} = ${effective:.2f}/sq ft "
                        f"× {prop.total_sq_ft:,.0f} sq ft{note}"
                    )
                else:
                    self._city_rent_per_sqft = rate
                    breakdown.append(f"{prop.property_type} @ ${rate}/sq ft × {prop.total_sq_ft:,.0f} sq ft")
                    comm_total = rate * prop.total_sq_ft

        self._comm_rent = comm_total
        self._res_rent  = res_total
        return comm_total + res_total, breakdown

    def _log_missing(self, city, province, missing_type, property_types=None):
        if self._store:
            self._store.log_missing_city(city, province, missing_type, property_types)

    def _resolve_residential(self, city: str, province: str, mix: UnitMix) -> tuple:
        market = self._residential.get_rates(city, province)
        if market is None:
            self._log_missing(city, province, "residential")
            total, lines = 0.0, []
            for unit_key, count, override in mix.unit_types():
                if count == 0:
                    continue
                if override is not None:
                    annual = override * count * 12
                    total += annual
                    lines.append(
                        f"{self.UNIT_LABELS[unit_key]} × {count} @ ${override:,.0f}/mo (specified): ${annual:,.2f}/yr"
                    )
                else:
                    lines.append(
                        f"{self.UNIT_LABELS[unit_key]} × {count} — ⚠ no rate for {city} (skipped)"
                    )
            return total, lines

        note = f"{city} market"
        # Exclude None stubs and explicit zeros — only real positive rates count.
        known_rates   = [v for v in market.values() if isinstance(v, (int, float)) and v > 0]
        city_avg_rate = sum(known_rates) / len(known_rates) if known_rates else None

        total, lines = 0.0, []
        for unit_key, count, override in mix.unit_types():
            if count == 0:
                continue
            if override is not None:
                monthly = override
                source  = "specified"
            elif unit_key in market and market[unit_key] is not None and market[unit_key] > 0:
                monthly = market[unit_key]
                source  = note
            elif city_avg_rate is not None:
                monthly = city_avg_rate
                source  = f"{city} avg (no {self.UNIT_LABELS[unit_key]} rate)"
            else:
                lines.append(
                    f"{self.UNIT_LABELS[unit_key]} × {count} — ⚠ no rate for {city} (skipped)"
                )
                continue
            annual  = monthly * count * 12
            total  += annual
            lines.append(
                f"{self.UNIT_LABELS[unit_key]} × {count} @ ${monthly:,.0f}/mo ({source}): ${annual:,.2f}/yr"
            )
        return total, lines
