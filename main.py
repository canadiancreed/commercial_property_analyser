from collections import defaultdict
from dataclasses import dataclass
from typing import Optional
from datetime import date

import copy
import csv as _csv
import json
import os
import re as _re
import webbrowser
import tempfile

def _display_address(address: str) -> str:
    """Strip trailing province code from address for display (e.g. ', ON' or ' ON')."""
    return _re.sub(r",?\s+[A-Z]{2}\s*$", "", (address or "").strip())


def _parse_address_sort(address: str):
    """Returns (street_name, street_number) for sorting. Handles '123 Main St' and '123-45 Main St'."""
    addr = (address or "").strip()
    m = _re.match(r"^([\d\-]+)\s+(.*)", addr)
    if m:
        num_str  = _re.sub(r"[^0-9]", "", m.group(1).split("-")[0])
        num      = int(num_str) if num_str else 0
        name     = m.group(2).lower()
    else:
        num  = 0
        name = addr.lower()
    return name, num

# ---------------------------------------------------------------------------
# DataStore — all file I/O lives here
# ---------------------------------------------------------------------------

class DataStore:
    """
    Owns all JSON file loading and saving.
    All other classes call DataStore; none touch the filesystem directly.

    Files managed:
      commercial_rents.json      — commercial $/sq ft rates by city + property type
      residential_rents.json — avg monthly residential rents by city + unit type
      properties.json        — saved property analyses
    """

    COMMERCIAL_PATH  = "json/commercial_rents.json"
    RESIDENTIAL_PATH = "json/residential_rents.json"
    PROPERTIES_PATH  = "properties.json"
    MISSING_PATH        = "json/missing_cities.json"
    MISSING_RENT_PATH   = "json/missing_rent_data.json"

    def __init__(self,
                 commercial_path:  str = COMMERCIAL_PATH,
                 residential_path: str = RESIDENTIAL_PATH,
                 properties_path:  str = PROPERTIES_PATH,
                 missing_path:     str = MISSING_PATH):
        self._commercial_path  = commercial_path
        self._residential_path = residential_path
        self._properties_path  = properties_path
        self._missing_path     = missing_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read(path: str) -> dict:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Data file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write(path: str, data: dict):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Commercial rates
    # ------------------------------------------------------------------

    def load_commercial_rates(self) -> dict:
        """Returns {city_lower: {type_lower: rate}} for fast lookup."""
        raw = self._read(self._commercial_path)
        index = {}
        for city, city_data in raw["cities"].items():
            city_key = city.strip().lower()
            index[city_key] = {
                t.strip().lower(): rate
                for t, rate in city_data["types"].items()
            }
        return index

    def save_commercial_rates(self, city: str, province: str, rates: dict):
        """
        Adds or updates a city entry in market_rents.json.
        rates = {"Office": 28.50, "Retail": 32.00, ...}
        """
        data = self._read(self._commercial_path)
        data["cities"][city] = {"province": province, "types": rates}
        self._write(self._commercial_path, data)

    # ------------------------------------------------------------------
    # Residential rates
    # ------------------------------------------------------------------

    def load_residential_rates(self) -> dict:
        """Returns {city_lower: {unit_type: monthly_rent}} for fast lookup."""
        raw = self._read(self._residential_path)
        index = {}
        for city, city_data in raw["cities"].items():
            city_key = city.strip().lower()
            index[city_key] = {k: float(v) for k, v in city_data["units"].items()}
        return index

    def save_residential_rates(self, city: str, province: str, units: dict):
        """
        Adds or updates a city entry in residential_rents.json.
        units = {"bachelor": 1250, "one_br": 1650, ...}
        """
        data = self._read(self._residential_path)
        data["cities"][city] = {"province": province, "units": units}
        self._write(self._residential_path, data)

    # ------------------------------------------------------------------
    # Property analyses
    # ------------------------------------------------------------------

    def load_properties(self) -> list:
        """Returns list of saved property analysis records."""
        if not os.path.exists(self._properties_path):
            return []
        return self._read(self._properties_path).get("properties", [])

    def save_property(self, record: dict):
        """
        Appends a property analysis record to properties.json.
        Replaces existing record if same address + listing_date.
        """
        if os.path.exists(self._properties_path):
            data = self._read(self._properties_path)
        else:
            data = {"properties": []}

        key = (record.get("address", ""), record.get("listing_date", ""))
        data["properties"] = [
            p for p in data["properties"]
            if (p.get("address", ""), p.get("listing_date", "")) != key
        ]
        data["properties"].append(record)
        self._write(self._properties_path, data)

    def delete_property(self, index: int) -> bool:
        """
        Deletes a property by its 0-based index in the saved list.
        Returns True if deleted, False if index out of range.
        """
        data = self._read(self._properties_path) if os.path.exists(self._properties_path) else {"properties": []}
        props = data.get("properties", [])
        if index < 0 or index >= len(props):
            return False
        del props[index]
        data["properties"] = props
        self._write(self._properties_path, data)
        return True

    def update_property(self, index: int, fields: dict) -> bool:
        """
        Updates specific fields on a saved property record by 0-based index.
        fields = {"address": "New Address", ...}
        Returns True if updated, False if index out of range.
        """
        data = self._read(self._properties_path) if os.path.exists(self._properties_path) else {"properties": []}
        props = data.get("properties", [])
        if index < 0 or index >= len(props):
            return False
        props[index].update(fields)
        data["properties"] = props
        self._write(self._properties_path, data)
        return True


    # ------------------------------------------------------------------
    # Missing cities report
    # ------------------------------------------------------------------

    def load_missing_cities(self) -> dict:
        """Returns the missing cities report, or empty dict if none."""
        if not os.path.exists(self._missing_path):
            return {}
        raw = self._read(self._missing_path)
        # Deduplicate keys that differ only by case/spacing — merge and rewrite
        seen, result = {}, {}
        for k, v in raw.items():
            norm = k.strip().lower()
            if norm in seen:
                existing = result[seen[norm]]
                for m in v.get("missing", []):
                    if m not in existing["missing"]:
                        existing["missing"].append(m)
                for pt in v.get("property_types", []):
                    if pt not in existing.get("property_types", []):
                        existing.setdefault("property_types", []).append(pt)
            else:
                seen[norm] = k
                result[k]  = v
        if len(result) != len(raw):
            self._write(self._missing_path, result)
        return result

    def log_missing_city(self, city: str, province: str, missing_type: str,
                         property_types: list = None):
        """
        Records a city that is missing rent data.
        missing_type: "commercial", "residential", or "both"
        property_types: list of commercial types needed (e.g. ["Retail", "Office"])
        """
        city     = city.strip().title()
        province = province.strip().upper()
        data     = self.load_missing_cities()
        # Normalize key and collapse any legacy duplicates
        norm_key = f"{city}, {province}"
        for old_key in [k for k in data if k.lower() == norm_key.lower() and k != norm_key]:
            data[norm_key] = data.pop(old_key)
        key   = norm_key
        entry = data.get(key, {
            "city":           city,
            "province":       province,
            "missing":        [],
            "property_types": [],
            "first_seen":     date.today().isoformat(),
        })
        if missing_type not in entry["missing"]:
            entry["missing"].append(missing_type)
        if property_types:
            for pt in property_types:
                if pt not in entry["property_types"]:
                    entry["property_types"].append(pt)
        entry["last_seen"] = date.today().isoformat()
        data[key] = entry
        os.makedirs(os.path.dirname(self._missing_path), exist_ok=True)
        self._write(self._missing_path, data)

    def ensure_city_in_rates(self, city: str, province: str):
        """
        Checks whether city exists in commercial_rents.json and residential_rents.json.
        For any file where it is absent, adds a zero-filled entry and records the
        city in missing_rent_data.json so it can be filled in later.
        Does nothing if the city already exists in both files.
        """
        city     = city.strip().title()
        province = province.strip().upper()
        key      = f"{city}, {province}"

        comm_data = self._read(self._commercial_path)
        res_data  = self._read(self._residential_path)

        comm_cities = {k.strip().lower() for k in comm_data.get("cities", {})}
        res_cities  = {k.strip().lower() for k in res_data.get("cities", {})}
        city_lower  = city.lower()

        needs_update = False

        if city_lower not in comm_cities:
            comm_data.setdefault("cities", {})[city] = {
                "province": province,
                "types": {"Office": 0, "Retail": 0, "Industrial": 0, "Mixed-Use": 0}
            }
            self._write(self._commercial_path, comm_data)
            needs_update = True

        if city_lower not in res_cities:
            res_data.setdefault("cities", {})[city] = {
                "province": province,
                "units": {"bachelor": 0, "one_br": 0, "two_br": 0,
                          "three_br": 0, "four_br": 0, "unknown": 0}
            }
            self._write(self._residential_path, res_data)
            needs_update = True

        if needs_update:
            # Record in missing_rent_data.json
            missing = {}
            if os.path.exists(self.MISSING_RENT_PATH):
                try:
                    missing = self._read(self.MISSING_RENT_PATH)
                except Exception:
                    missing = {}
            if key not in missing:
                missing[key] = {
                    "city":       city,
                    "province":   province,
                    "first_seen": date.today().isoformat(),
                }
            missing[key]["last_seen"] = date.today().isoformat()
            os.makedirs(os.path.dirname(self.MISSING_RENT_PATH), exist_ok=True)
            self._write(self.MISSING_RENT_PATH, missing)

    def clear_missing_city(self, key: str):
        """Remove a city from the missing report once data has been added."""
        data = self.load_missing_cities()
        if key in data:
            del data[key]
            self._write(self._missing_path, data)

    def save_commercial_city(self, city: str, province: str, rates: dict):
        """Saves commercial rates AND removes city from missing report if all needed types are now present."""
        city     = city.strip().title()
        province = province.strip().upper()
        self.save_commercial_rates(city, province, rates)
        missing  = self.load_missing_cities()
        # Find key case-insensitively
        norm     = f"{city}, {province}".lower()
        key      = next((k for k in missing if k.lower() == norm), None)
        if key is None:
            return
        entry        = missing[key]
        needed_types = entry.get("property_types", [])
        if needed_types:
            still_missing = [t for t in needed_types if t not in rates]
            if still_missing:
                entry["property_types"] = still_missing
                missing[key] = entry
                self._write(self._missing_path, missing)
                return
        if "commercial" in entry["missing"]:
            entry["missing"].remove("commercial")
        entry["property_types"] = []
        if not entry["missing"]:
            del missing[key]
        else:
            missing[key] = entry
        self._write(self._missing_path, missing)

    def save_residential_city(self, city: str, province: str, units: dict):
        """Saves residential rates AND removes city from missing report if complete."""
        city     = city.strip().title()
        province = province.strip().upper()
        self.save_residential_rates(city, province, units)
        missing  = self.load_missing_cities()
        norm     = f"{city}, {province}".lower()
        key      = next((k for k in missing if k.lower() == norm), None)
        if key is None:
            return
        entry = missing[key]
        if "residential" in entry["missing"]:
            entry["missing"].remove("residential")
        if not entry["missing"]:
            del missing[key]
        else:
            missing[key] = entry
        self._write(self._missing_path, missing)


# ---------------------------------------------------------------------------
# Property Input
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Residential Unit Mix
# ---------------------------------------------------------------------------

@dataclass
class UnitMix:
    """
    Describes the residential unit composition of a property.
    Counts per unit type are required. Monthly rent overrides are optional —
    if omitted, the city market rate from residential_rents.json is used.

    For mixed-use: set floors > 1. Ground floor = commercial sq ft,
    upper floors = residential.
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


# ---------------------------------------------------------------------------
# Property Input
# ---------------------------------------------------------------------------

@dataclass
class PropertyInput:
    original_price:   float
    asking_price:     float
    total_sq_ft:      float
    property_taxes:   float
    down_payment_pct: float             # e.g. 0.25 for 25%
    interest_rate:    float             # e.g. 0.0725 for 7.25%
    term_years:       int
    # Rent — provide ONE of:
    annual_rent:      Optional[float]   = None  # Direct flat rent
    city:             Optional[str]     = None  # For market-rate lookup
    province:         Optional[str]     = None  # Parsed from address
    property_type:    Optional[str]     = None  # Commercial type or ground floor type
    unit_mix:         Optional[UnitMix] = None  # Residential / mixed-use
    # Defaults
    address:          str               = ""
    mls_number:       str               = ""
    status:           str               = "active"  # "active" or "inactive"
    expense_ratio:    float             = 0.40
    lease_type:       str               = "Normal"
    exit_cap_rate:    Optional[float]   = None
    market_cap_rate:  Optional[float]   = None
    listing_date:     str               = ""    # YYYY-MM-DD
    hold_years:       int               = 5
    construction_cost: float            = 0.0  # cash paid at purchase for renos/build-out
    # Hotel-specific fields
    hotel_rooms:      int               = 0    # total rentable rooms
    hotel_adr:        Optional[float]   = None # Average Daily Rate ($)
    hotel_occupancy:  Optional[float]   = None # occupancy rate e.g. 0.65 for 65%
    # Industrial-specific fields (all optional — omit any component not present)
    ind_warehouse_sqft:   float         = 0.0  # sq ft of warehouse/storage space
    ind_office_sqft:      float         = 0.0  # sq ft of office component
    ind_yard_sqft:        float         = 0.0  # sq ft of outdoor yard/storage
    ind_dock_doors:       int           = 0    # number of dock-level doors
    ind_drive_in_doors:   int           = 0    # number of drive-in doors
    ind_clear_height_ft:  float         = 0.0  # clear ceiling height (affects rate)
    ind_office_rate:      Optional[float] = None  # $/sqft/yr override for office component
    ind_yard_rate:        Optional[float] = None  # $/sqft/yr override for yard


# ---------------------------------------------------------------------------
# Mortgage Calculator
# ---------------------------------------------------------------------------

class MortgageCalculator:

    def __init__(self, asking_price: float, down_payment_pct: float,
                 interest_rate: float, term_years: int, hold_years: int,
                 construction_cost: float = 0.0):
        self._construction_cost = construction_cost or 0
        self.down_payment = asking_price * down_payment_pct
        self.loan_amount  = asking_price - self.down_payment

        monthly_rate = interest_rate / 12
        n_payments   = term_years * 12

        if monthly_rate == 0:
            self.monthly_payment = self.loan_amount / n_payments
        else:
            self.monthly_payment = (
                self.loan_amount
                * (monthly_rate * (1 + monthly_rate) ** n_payments)
                / ((1 + monthly_rate) ** n_payments - 1)
            )

        self.annual_mortgage = self.monthly_payment * 12

        payments_made = hold_years * 12
        if payments_made >= n_payments:
            self.loan_balance = 0.0
        elif monthly_rate == 0:
            self.loan_balance = self.loan_amount - (self.monthly_payment * payments_made)
        else:
            self.loan_balance = (
                self.loan_amount
                * ((1 + monthly_rate) ** n_payments - (1 + monthly_rate) ** payments_made)
                / ((1 + monthly_rate) ** n_payments - 1)
            )

    def rows(self) -> list:
        rows = [
            ReportRow("Loan Amount",     f"${self.loan_amount:,.2f}",     "INFO"),
            ReportRow("Down Payment",    f"${self.down_payment:,.2f}",    "INFO"),
        ]
        if self._construction_cost:
            rows.append(ReportRow("Construction Cost", f"${self._construction_cost:,.2f}", "INFO"))
            rows.append(ReportRow("Total Cash In",     f"${self.down_payment + self._construction_cost:,.2f}", "INFO"))
        rows += [
            ReportRow("Monthly Payment", f"${self.monthly_payment:,.2f}", "INFO"),
            ReportRow("Annual Debt Svc", f"${self.annual_mortgage:,.2f}", "INFO"),
        ]
        return rows


# ---------------------------------------------------------------------------
# Days on Market Calculator
# ---------------------------------------------------------------------------

class DaysOnMarketCalculator:

    def __init__(self, listing_date: str):
        listed    = date.fromisoformat(listing_date)
        self.days = (date.today() - listed).days

    @property
    def count(self) -> int:
        return self.days


# ---------------------------------------------------------------------------
# Commercial Rent Loader
# ---------------------------------------------------------------------------

class CommercialRentLoader:
    """Wraps the commercial rate index from DataStore for clean lookups."""

    def __init__(self, data_store: DataStore):
        self._store = data_store

    def get_rent_per_sqft(self, city: str, province: str, property_type: str):
        """Returns rate float, or None if city/type not found. Reads fresh from disk each call."""
        index    = self._store.load_commercial_rates()
        city_key = city.strip().lower()
        type_key = property_type.strip().lower()
        if city_key not in index or type_key not in index[city_key]:
            return None
        return index[city_key][type_key]


# ---------------------------------------------------------------------------
# Residential Rent Loader
# ---------------------------------------------------------------------------

class ResidentialRentLoader:
    """Wraps the residential rate index from DataStore for clean lookups."""

    def __init__(self, data_store: DataStore):
        self._store = data_store

    def get_rates(self, city: str, province: str):
        """Returns rate dict, or None if city not found. Reads fresh from disk each call."""
        index = self._store.load_residential_rates()
        key   = city.strip().lower()
        return index.get(key)


# ---------------------------------------------------------------------------
# Rent Resolver
# ---------------------------------------------------------------------------

class RentResolver:
    """
    Resolves annual gross rent from whichever input mode is used:

    Mode 1 — Direct:       annual_rent provided explicitly
    Mode 2 — Commercial:   city + province + property_type → $/sqft × total_sq_ft
    Mode 3 — Residential:  unit_mix with counts (and optional per-type rent overrides)
    Mode 4 — Mixed-Use:    property_type + unit_mix + floors
                           ground floor = commercial sq ft × $/sqft
                           upper floors = residential units × monthly rent × 12
    """

    UNIT_LABELS = {
        "bachelor": "Bachelor", "one_br": "1BR", "two_br": "2BR",
        "three_br": "3BR",      "four_br": "4BR", "unknown": "Unknown",
    }

    def __init__(self, commercial_loader: CommercialRentLoader,
                 residential_loader: ResidentialRentLoader,
                 data_store: "DataStore" = None):
        self._commercial  = commercial_loader
        self._residential = residential_loader
        self._store       = data_store

    def resolve(self, prop: PropertyInput) -> tuple:
        """Returns (annual_rent: float, breakdown: list[str])."""
        if prop.annual_rent is not None:
            self._comm_rent = prop.annual_rent
            self._res_rent  = 0.0
            return prop.annual_rent, ["Rent provided directly"]

        COMMERCIAL_TYPES = {"office", "retail", "industrial", "mixed-use", "hotel", "retail-office"}
        ptype            = (prop.property_type or "").strip().lower()
        has_commercial  = ptype in COMMERCIAL_TYPES
        has_residential = prop.unit_mix is not None and prop.unit_mix.total_units > 0

        is_mixed        = has_commercial and has_residential
        # Hotel: revenue from rooms × ADR × occupancy, no rate lookup needed
        if ptype == "hotel":
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
        if not all([prop.city, prop.province]):
            raise ValueError("city and province required for market-rate lookup.")
        city     = prop.city
        province = prop.province

        breakdown    = []
        comm_total   = 0.0
        res_total    = 0.0

        if is_mixed:
            mix         = prop.unit_mix
            floor_sq_ft = prop.total_sq_ft / mix.floors
            comm_rate   = self._commercial.get_rent_per_sqft(
                              city, province, prop.property_type)
            if comm_rate is None:
                self._log_missing(city, province, "commercial", [prop.property_type])
                # Also log residential if city is absent from both
                if self._residential.get_rates(city, province) is None:
                    self._log_missing(city, province, "residential")
                breakdown.append(f"  ⚠ Commercial rate missing for {city} ({prop.property_type}) — skipped")
            else:
                comm_total = comm_rate * floor_sq_ft
                breakdown.append(
                    f"Commercial (ground floor {floor_sq_ft:,.0f} sq ft "
                    f"@ ${comm_rate}/sq ft): ${comm_total:,.2f}/yr"
                )
            res_total, res_lines = self._resolve_residential(city, province, mix)
            breakdown.extend(res_lines)

        elif has_residential:
            res_total, res_lines = self._resolve_residential(
                city, province, prop.unit_mix)
            breakdown.extend(res_lines)

        elif ptype == "retail-office":
            # Ground floor @ Retail rate, upper floors @ Office rate
            floors       = (prop.unit_mix.floors if prop.unit_mix else getattr(prop, "floors", 1)) or 1
            floor_sq_ft  = prop.total_sq_ft / floors
            retail_rate  = self._commercial.get_rent_per_sqft(city, province, "Retail")
            office_rate  = self._commercial.get_rent_per_sqft(city, province, "Office")
            missing = []
            if retail_rate is None: missing.append("Retail")
            if office_rate is None: missing.append("Office")
            if missing:
                self._log_missing(city, province, "commercial", missing)
                raise ValueError(
                    f"No {' or '.join(missing)} rate for {city}, {province}. "
                    "Use menu option 7 to add rates."
                )
            # Ground floor Retail + upper floors Office
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
            rate = self._commercial.get_rent_per_sqft(city, province, prop.property_type)
            if rate is None:
                self._log_missing(city, province, "commercial", [prop.property_type])
                if self._residential.get_rates(city, province) is None:
                    self._log_missing(city, province, "residential")
                raise ValueError(
                    f"No commercial rate for {city}, {province} ({prop.property_type}). "
                    f"Use menu option 7 to add rates."
                )
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
            # No market data — only count units with explicit overrides
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
        # Average of all known rates — used as fallback for unit types with no specific rate
        known_rates   = [v for v in market.values() if isinstance(v, (int, float))]
        city_avg_rate = sum(known_rates) / len(known_rates) if known_rates else None

        total, lines = 0.0, []
        for unit_key, count, override in mix.unit_types():
            if count == 0:
                continue
            if override is not None:
                monthly = override
                source  = "specified"
            elif unit_key in market:
                monthly = market[unit_key]
                source  = note
            elif city_avg_rate is not None:
                # No rate for this specific type — use city average as best estimate
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


# ---------------------------------------------------------------------------
# Report Row
# ---------------------------------------------------------------------------

@dataclass
class ReportRow:
    metric: str
    value:  str
    grade:  str

    def __str__(self):
        return f"{self.metric:<25} | {self.value:<30} | {self.grade}"

    def to_dict(self) -> dict:
        return {"metric": self.metric, "value": self.value, "grade": self.grade}


# ---------------------------------------------------------------------------
# Grader
# ---------------------------------------------------------------------------

class Grader:

    @staticmethod
    def grade(value, good_thresh, fair_thresh, *,
              higher_is_better=True, labels=("GOOD", "FAIR", "POOR")) -> str:
        g, f, poor = labels
        if higher_is_better:
            return g if value >= good_thresh else f if value >= fair_thresh else poor
        else:
            return g if value <= good_thresh else f if value <= fair_thresh else poor


# ---------------------------------------------------------------------------
# Metric Groups
# ---------------------------------------------------------------------------

class PricingMetrics:

    # Price/sq ft thresholds by property type (good_ceiling, poor_floor)
    # Values reflect typical Canadian secondary-market commercial pricing.
    # Below good_ceiling = GOOD, above poor_floor = POOR/PREMIUM, in between = FAIR.
    _SQFT_THRESHOLDS = {
        "office":      (150, 300),
        "retail":      (200, 400),
        "industrial":  (80,  200),
        "mixed-use":   (175, 350),
        "retail-office": (175, 375),
        "multi-family":(100, 250),
        "residential": (150, 300),   # fallback for unlabelled
    }
    _SQFT_DEFAULT    = (150, 350)    # generic fallback

    def __init__(self, prop: PropertyInput, loan_balance: float, annual_rent: float):
        self._cost_basis    = prop.asking_price + (prop.construction_cost or 0)
        self.pp_sqft        = self._cost_basis / prop.total_sq_ft
        self.grm            = self._cost_basis / annual_rent
        self.price_drop_pct = ((prop.original_price - prop.asking_price) / prop.original_price) * 100
        self.tax_load       = (prop.property_taxes / prop.asking_price) * 100
        self.ltv_ratio      = (loan_balance / prop.asking_price) * 100
        ptype               = (prop.property_type or "").strip().lower()
        self._sqft_good, self._sqft_poor = self._SQFT_THRESHOLDS.get(ptype, self._SQFT_DEFAULT)
        self._ptype_label   = prop.property_type or "Property"

    def rows(self) -> list:
        return [
            ReportRow(f"Price/Sq Ft ({self._ptype_label})",
                      f"${self.pp_sqft:.2f}",
                      Grader.grade(self.pp_sqft, self._sqft_good, self._sqft_poor,
                                   higher_is_better=False,
                                   labels=("GOOD", "FAIR", "POOR/PREMIUM"))),
            ReportRow("GRM",           f"{self.grm:.2f}",
                      Grader.grade(self.grm, 9, 12, higher_is_better=False)),
            ReportRow("Tax Load",      f"{self.tax_load:.2f}%",
                      Grader.grade(self.tax_load, 2.0, 3.0, higher_is_better=False)),
            ReportRow("Price Drop %",  f"{self.price_drop_pct:.2f}%",
                      Grader.grade(self.price_drop_pct, 10, 0)),
            ReportRow("Loan to Value", f"{self.ltv_ratio:.2f}%",
                      Grader.grade(self.ltv_ratio, 70, 80, higher_is_better=False,
                                   labels=("GOOD", "FAIR", "POOR/RISKY"))),
        ]


class IncomeMetrics:

    def __init__(self, prop: PropertyInput, annual_rent: float, rent_breakdown: list):
        self.annual_rent    = annual_rent
        self.rent_breakdown = rent_breakdown
        self.est_expenses   = annual_rent * prop.expense_ratio
        self.est_noi        = annual_rent - self.est_expenses
        self._cost_basis    = prop.asking_price + (prop.construction_cost or 0)
        self.cap_rate       = (self.est_noi / self._cost_basis) * 100
        self.oer_ratio      = (self.est_expenses / annual_rent) * 100
        self.entry_cap      = self.est_noi / self._cost_basis
        self._prop          = prop

    def _expense_grade(self) -> str:
        p = self._prop
        if p.lease_type.upper() == "NNN":
            return "GOOD" if p.expense_ratio <= 0.20 else "WARNING: High for NNN"
        return "GOOD" if p.expense_ratio >= 0.35 else "WARNING: Low for Gross"

    def _oer_grade(self) -> str:
        if self._prop.lease_type.upper() == "NNN":
            return "GOOD" if self.oer_ratio <= 15 else "FAIR" if self.oer_ratio <= 25 else "POOR"
        return "GOOD" if 35 <= self.oer_ratio <= 45 else "FAIR" if 30 <= self.oer_ratio <= 50 else "POOR"

    def rows(self) -> list:
        p    = self._prop
        rows = [ReportRow("  Rent Detail", line, "") for line in self.rent_breakdown]
        rows += [
            ReportRow("Annual Rent",      f"${self.annual_rent:,.2f}",    "INFO"),
            ReportRow("Expense Ratio",    f"{p.expense_ratio * 100}%",   self._expense_grade()),
            ReportRow("NOI",              f"${self.est_noi:,.2f}",
                      Grader.grade(self.entry_cap, 0.07, 0.05)),
            ReportRow("Cap Rate",         f"{self.cap_rate:.2f}%",
                      Grader.grade(self.cap_rate, 7.5, 5.5)),
            ReportRow("Op Expense Ratio", f"{self.oer_ratio:.2f}%",      self._oer_grade()),
            ReportRow("Entry Cap Rate",   f"{self.entry_cap * 100:.2f}%",
                      Grader.grade(self.entry_cap, 0.075, 0.055)),
        ]
        return rows


class ExitCapEstimator:

    AGING_BPS_PER_YEAR = 10   # cap rate drift per year of hold
    MARKET_DRIFT_BPS   = 25   # one-time market drift assumption (reduced from 50)
    MAX_HOLD_FOR_AGING = 10   # cap aging at 10 years — beyond that, NOI growth offsets aging

    def __init__(self, entry_cap: float, hold_years: int, market_cap_rate: Optional[float] = None):
        self.entry_cap       = entry_cap
        self.hold_years      = hold_years
        self.market_cap_rate = market_cap_rate

    def estimate(self) -> float:
        # Cap aging horizon — long hold periods have NOI growth that offsets cap rate drift
        effective_hold = min(self.hold_years, self.MAX_HOLD_FOR_AGING)
        aging_spread = (self.AGING_BPS_PER_YEAR * effective_hold) / 10000
        drift_spread = self.MARKET_DRIFT_BPS / 10000
        formula_exit = self.entry_cap + aging_spread + drift_spread
        if self.market_cap_rate is not None:
            return round((formula_exit + self.market_cap_rate) / 2, 4)
        return round(formula_exit, 4)


class ExitMetrics:

    def __init__(self, prop: PropertyInput, entry_cap: float, est_noi: float,
                 loan_balance: float = 0.0):
        self.exit_cap = (prop.exit_cap_rate if prop.exit_cap_rate is not None
                         else ExitCapEstimator(entry_cap, prop.hold_years, prop.market_cap_rate).estimate())
        self.exit_cap_ratio = entry_cap / self.exit_cap if self.exit_cap else 0
        self.exit_price     = est_noi / self.exit_cap if self.exit_cap else 0
        self._entry_cap     = entry_cap
        self._cost_basis    = prop.asking_price + (prop.construction_cost or 0)
        self._loan_balance  = loan_balance

    def _exit_cap_grade(self) -> str:
        # Grade based on spread above entry cap — up to +150bps is normal, +250bps is fair
        spread_bps = (self.exit_cap - self._entry_cap) * 10000
        if spread_bps <= 150: return "GOOD"
        if spread_bps <= 250: return "FAIR"
        return "POOR"

    def rows(self) -> list:
        # Exit price grade: can we cover the loan balance? (real solvency test)
        if self._loan_balance > 0:
            exit_price_grade = ("GOOD" if self.exit_price >= self._loan_balance * 1.20 else
                                "FAIR" if self.exit_price >= self._loan_balance else "POOR")
        else:
            exit_price_grade = ("GOOD" if self.exit_price >= self._cost_basis else
                                "FAIR" if self.exit_price >= self._cost_basis * 0.85 else "POOR")
        return [
            ReportRow("Exit Cap Rate",  f"{self.exit_cap * 100:.2f}%",  self._exit_cap_grade()),
            ReportRow("Exit Cap Ratio", f"{self.exit_cap_ratio:.2f}",
                      Grader.grade(self.exit_cap_ratio, 0.90, 0.75)),
            ReportRow("Exit Price",     f"${self.exit_price:,.2f}", exit_price_grade),
        ]


class CashFlowMetrics:

    def __init__(self, est_noi: float, annual_mortgage: float, down_payment: float,
                 construction_cost: float = 0.0):
        self.cash_invested     = down_payment + (construction_cost or 0)
        self.annual_cash_flow  = est_noi - annual_mortgage
        self.monthly_cash_flow = self.annual_cash_flow / 12
        self.coc_return        = (self.annual_cash_flow / self.cash_invested) * 100 if self.cash_invested else 0

    def _cf_grade(self) -> str:
        if self.annual_cash_flow <= 0: return "POOR/BLEEDING"
        if self.coc_return >= 8.0:     return "GOOD"
        return "FAIR (Thin Margin)"

    def rows(self) -> list:
        return [
            ReportRow("Annual Cash Flow",  f"${self.annual_cash_flow:,.2f}",  self._cf_grade()),
            ReportRow("Monthly Cash Flow", f"${self.monthly_cash_flow:,.2f}",
                      Grader.grade(self.coc_return, 8.0, 0,
                                   labels=("GOOD", "FAIR", "POOR/BLEEDING"))),
            ReportRow("CoCR",              f"{self.coc_return:.2f}%",
                      Grader.grade(self.coc_return, 10, 5)),
        ]


class DebtMetrics:

    STRESS_DEBT_ADD = 9000

    def __init__(self, est_noi: float, est_expenses: float,
                 annual_mortgage: float, annual_rent: float):
        self.dscr             = est_noi / annual_mortgage if annual_mortgage else float('inf')
        self.be_ratio         = (annual_mortgage / est_noi) * 100 if est_noi else 1
        self.break_even_point = ((est_expenses + annual_mortgage) / annual_rent) * 100 if annual_rent else 0
        stressed_debt         = annual_mortgage + self.STRESS_DEBT_ADD
        self.stressed_dscr    = est_noi / stressed_debt if stressed_debt else 0
        self._annual_mortgage = annual_mortgage

    def rows(self) -> list:
        stress_status = "PASS" if self.stressed_dscr >= 1.20 else "FAIL: High Rate Risk"
        return [
            ReportRow("DSCR",                   f"{self.dscr:.2f}",
                      Grader.grade(self.dscr, 1.5, 1.25,
                                   labels=("GOOD", "FAIR", "POOR/UNBANKABLE"))),
            ReportRow("Break-Even NOI",         f"${self._annual_mortgage:,.2f}",
                      Grader.grade(self.be_ratio, 65, 80, higher_is_better=False)),
            ReportRow("Break-Even NOI %",       f"{self.be_ratio:.2f}%",
                      Grader.grade(self.break_even_point, 75, 85, higher_is_better=False)),
            ReportRow("Break-Even Occupancy %", f"{self.break_even_point:.2f}%",
                      Grader.grade(self.be_ratio, 75, 85, higher_is_better=False)),
            ReportRow("Stress Test (+2%)",      f"{self.stressed_dscr:.2f} DSCR", stress_status),
        ]


class ReturnMetrics:

    APPRECIATION_RATE = 0.02

    @staticmethod
    def _calc_irr(cash_flows: list, guess: float = 0.10, iterations: int = 1000) -> float:
        """Newton-Raphson IRR on a list of cash flows (index 0 = year 0 outflow, negative)."""
        rate = guess
        for _ in range(iterations):
            npv  = sum(cf / (1 + rate) ** t for t, cf in enumerate(cash_flows))
            dnpv = sum(-t * cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cash_flows))
            if dnpv == 0:
                break
            new_rate = rate - npv / dnpv
            if abs(new_rate - rate) < 1e-7:
                rate = new_rate
                break
            rate = new_rate
        return rate

    def __init__(self, prop: PropertyInput, annual_cash_flow: float, cash_invested: float):
        exit_price           = prop.asking_price * (1 + self.APPRECIATION_RATE) ** prop.hold_years
        total_appreciation   = exit_price - prop.asking_price
        total_cash_flow      = annual_cash_flow * prop.hold_years
        self.equity_multiple = ((total_cash_flow + total_appreciation + cash_invested) / cash_invested
                                if cash_invested else 0)

        # IRR: year-0 outflow, annual cash flows, terminal sale proceeds at exit
        if cash_invested > 0 and prop.hold_years > 0:
            flows = [-cash_invested]
            for yr in range(1, prop.hold_years + 1):
                flows.append(annual_cash_flow)
            flows[-1] += exit_price   # add sale proceeds in final year
            try:
                r = self._calc_irr(flows)
                self.irr = r * 100 if -1 < r < 10 else -100.0
            except Exception:
                self.irr = -100.0
        else:
            self.irr = -100.0

    def _em_grade(self) -> str:
        if self.equity_multiple >= 2.0: return "EXCELLENT"
        if self.equity_multiple >= 1.5: return "GOOD"
        if self.equity_multiple >= 1.2: return "FAIR"
        return "POOR (Underperforming)"

    def rows(self) -> list:
        return [
            ReportRow("IRR (5-Yr)",      f"{self.irr:.2f}%",
                      Grader.grade(self.irr, 15.0, 10.0)),
            ReportRow("Equity Multiple", f"{self.equity_multiple:.2f}x", self._em_grade()),
        ]


class MarketMetrics:

    VACANCY_PCT = 0.10

    def __init__(self, est_noi: float, cash_invested: float, est_expenses: float,
                 annual_mortgage: float, days_on_market: int):
        self.celoc_score        = (est_noi / cash_invested) * 100 if cash_invested else 0
        monthly_carry           = (est_expenses + annual_mortgage) / 12
        self.total_seller_bleed = monthly_carry * (days_on_market / 30) * self.VACANCY_PCT
        self._days_on_market    = days_on_market

    def _celoc_grade(self) -> str:
        if self.celoc_score >= 80: return "FAST CELOC"
        if self.celoc_score >= 60: return "CELOC POSSIBLE"
        if self.celoc_score >= 40: return "LENDER FRICTION"
        return "NO CELOC"

    def rows(self) -> list:
        return [
            ReportRow("CELOC Speed Score", f"{self.celoc_score:.2f}",         self._celoc_grade()),
            ReportRow("Market Staleness",  f"{self._days_on_market} Days",
                      Grader.grade(self._days_on_market, 150, 90)),
            ReportRow("Seller Bleed",      f"${self.total_seller_bleed:,.2f}",
                      Grader.grade(self.total_seller_bleed, 25000, 5000)),
        ]


class HotelMetrics:
    """Hotel-specific operating metrics: RevPAR, ADR, Occupancy, GOP, NRevPAR."""

    FF_E_RESERVE_RATIO  = 0.04   # FF&E reserve as % of revenue

    def __init__(self, prop: "PropertyInput", annual_revenue: float):
        rooms       = prop.hotel_rooms or 0
        adr         = prop.hotel_adr or 0.0
        occupancy   = prop.hotel_occupancy or 0.0
        self.rooms      = rooms
        self.adr        = adr
        self.occupancy  = occupancy * 100  # store as % for display

        # RevPAR = ADR x Occupancy
        self.revpar     = adr * occupancy
        # NRevPAR = RevPAR minus ~15% distribution/booking costs
        self.nrevpar    = self.revpar * 0.85
        # Revenue per room per year
        self.rev_per_room = (annual_revenue / rooms) if rooms else 0
        # Gross Operating Profit
        self.gop_amount  = annual_revenue * (1 - prop.expense_ratio)
        self.gop_margin  = (1 - prop.expense_ratio) * 100
        # FF&E capital replacement reserve
        self.ffe_reserve = annual_revenue * self.FF_E_RESERVE_RATIO
        # CPOR — Cost Per Occupied Room
        occupied_nights  = rooms * occupancy * 365 if rooms else 0
        total_expenses   = annual_revenue * prop.expense_ratio
        self.cpor        = (total_expenses / occupied_nights) if occupied_nights else 0

    def _revpar_grade(self) -> str:
        if self.revpar >= 120: return "EXCELLENT"
        if self.revpar >= 80:  return "GOOD"
        if self.revpar >= 50:  return "FAIR"
        return "POOR"

    def _occ_grade(self) -> str:
        if self.occupancy >= 70: return "GOOD"
        if self.occupancy >= 55: return "FAIR"
        return "POOR"

    def _gop_grade(self) -> str:
        if self.gop_margin >= 35: return "GOOD"
        if self.gop_margin >= 25: return "FAIR"
        return "POOR"

    def rows(self) -> list:
        rows = []
        if self.rooms:
            rows.append(ReportRow("Hotel Rooms",     f"{self.rooms}",                   ""))
        if self.adr:
            rows.append(ReportRow("ADR",             f"${self.adr:,.2f}/night",         ""))
        if self.occupancy:
            rows.append(ReportRow("Occupancy Rate",  f"{self.occupancy:.1f}%",          self._occ_grade()))
        if self.revpar:
            rows.append(ReportRow("RevPAR",          f"${self.revpar:,.2f}",            self._revpar_grade()))
            rows.append(ReportRow("NRevPAR",         f"${self.nrevpar:,.2f}",           ""))
        if self.rooms:
            rows.append(ReportRow("Rev/Room/Yr",     f"${self.rev_per_room:,.0f}",      ""))
        rows.append(    ReportRow("GOP Margin",      f"{self.gop_margin:.1f}%",         self._gop_grade()))
        rows.append(    ReportRow("GOP Amount",      f"${self.gop_amount:,.0f}",        ""))
        if self.cpor:
            rows.append(ReportRow("CPOR",            f"${self.cpor:,.2f}/night",        ""))
        rows.append(    ReportRow("FF&E Reserve",    f"${self.ffe_reserve:,.0f}/yr",    ""))
        return rows


class IndustrialMetrics:
    """
    Industrial property income breakdown by component.
    Warehouse/storage at base rate, office premium, yard at discounted rate.
    Clear height and dock doors affect the warehouse rate.
    """

    # Clear height rate premiums (above base industrial rate)
    # Each foot above 18ft adds roughly 2-3% to the warehouse rate
    CLEAR_HEIGHT_BASE_FT = 18
    CLEAR_HEIGHT_PREMIUM_PER_FT = 0.02   # 2% per foot above base

    # Office component typically commands a premium over warehouse rate
    OFFICE_PREMIUM_RATIO = 1.40   # office sqft @ 140% of warehouse rate by default

    # Yard/outdoor storage at a deep discount to covered space
    YARD_RATE_RATIO      = 0.15   # yard sqft @ 15% of warehouse rate by default

    # Dock door value: each dock door adds annual income potential
    DOCK_DOOR_ANNUAL     = 1200   # $/door/yr premium indicator
    DRIVE_IN_DOOR_ANNUAL = 600    # $/door/yr premium indicator

    def __init__(self, prop: "PropertyInput", base_industrial_rate: float):
        """
        base_industrial_rate: $/sqft/yr from city commercial rate table for Industrial.
        Adjusts for clear height, then breaks down income by component.
        """
        self.base_rate = base_industrial_rate

        # Clear height adjustment to warehouse rate
        height = prop.ind_clear_height_ft or 0
        if height > self.CLEAR_HEIGHT_BASE_FT:
            premium = (height - self.CLEAR_HEIGHT_BASE_FT) * self.CLEAR_HEIGHT_PREMIUM_PER_FT
            self.warehouse_rate = base_industrial_rate * (1 + premium)
        else:
            self.warehouse_rate = base_industrial_rate

        # Effective office and yard rates
        self.office_rate = prop.ind_office_rate if prop.ind_office_rate else (
            self.warehouse_rate * self.OFFICE_PREMIUM_RATIO)
        self.yard_rate   = prop.ind_yard_rate if prop.ind_yard_rate else (
            self.warehouse_rate * self.YARD_RATE_RATIO)

        # Sqft breakdown — infer warehouse from total if not broken out
        total = prop.total_sq_ft or 0
        office_sqft  = prop.ind_office_sqft  or 0
        yard_sqft    = prop.ind_yard_sqft    or 0
        wh_sqft      = prop.ind_warehouse_sqft or max(0, total - office_sqft)

        self.warehouse_sqft = wh_sqft
        self.office_sqft    = office_sqft
        self.yard_sqft      = yard_sqft
        self.dock_doors     = prop.ind_dock_doors or 0
        self.drive_in_doors = prop.ind_drive_in_doors or 0
        self.clear_height   = height

        # Income components
        self.warehouse_income = wh_sqft    * self.warehouse_rate
        self.office_income    = office_sqft * self.office_rate
        self.yard_income      = yard_sqft   * self.yard_rate
        self.total_income     = self.warehouse_income + self.office_income + self.yard_income

        # Blended effective rate across all covered sqft
        covered_sqft = wh_sqft + office_sqft
        self.blended_rate = (self.warehouse_income + self.office_income) / covered_sqft if covered_sqft else 0

    def _height_grade(self) -> str:
        if not self.clear_height: return ""
        if self.clear_height >= 28: return "EXCELLENT"
        if self.clear_height >= 22: return "GOOD"
        if self.clear_height >= 18: return "FAIR"
        return "POOR"

    def rows(self) -> list:
        rows = []
        if self.clear_height:
            rows.append(ReportRow("Clear Height",
                                  f"{self.clear_height:.0f} ft",
                                  self._height_grade()))
        if self.dock_doors:
            rows.append(ReportRow("Dock Doors",
                                  f"{self.dock_doors}",
                                  "GOOD" if self.dock_doors >= 2 else "FAIR"))
        if self.drive_in_doors:
            rows.append(ReportRow("Drive-In Doors",
                                  f"{self.drive_in_doors}", ""))
        rows.append(ReportRow("Warehouse Sqft",
                               f"{self.warehouse_sqft:,.0f} sq ft @ ${self.warehouse_rate:.2f}/sq ft",
                               ""))
        rows.append(ReportRow("Warehouse Income",
                               f"${self.warehouse_income:,.0f}/yr", ""))
        if self.office_sqft:
            rows.append(ReportRow("Office Component",
                                  f"{self.office_sqft:,.0f} sq ft @ ${self.office_rate:.2f}/sq ft",
                                  ""))
            rows.append(ReportRow("Office Income",
                                  f"${self.office_income:,.0f}/yr", ""))
        if self.yard_sqft:
            rows.append(ReportRow("Yard/Storage",
                                  f"{self.yard_sqft:,.0f} sq ft @ ${self.yard_rate:.2f}/sq ft",
                                  ""))
            rows.append(ReportRow("Yard Income",
                                  f"${self.yard_income:,.0f}/yr", ""))
        rows.append(ReportRow("Total Industrial Rev",
                               f"${self.total_income:,.0f}/yr",
                               "GOOD" if self.total_income > 0 else "POOR"))
        if self.blended_rate:
            rows.append(ReportRow("Blended Rate",
                                  f"${self.blended_rate:.2f}/sq ft/yr", ""))
        return rows


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class CommercialPropertyAnalyzer:

    def __init__(self, prop: PropertyInput, rent_resolver: RentResolver):
        self.prop       = prop
        self._has_rent  = False
        annual_rent, breakdown = rent_resolver.resolve(prop)
        self._comm_rent = getattr(rent_resolver, "_comm_rent", None)
        self._res_rent  = getattr(rent_resolver, "_res_rent",  None)

        self.mortgage = MortgageCalculator(
            prop.asking_price, prop.down_payment_pct,
            prop.interest_rate, prop.term_years, prop.hold_years,
            prop.construction_cost or 0
        )
        self.dom     = DaysOnMarketCalculator(prop.listing_date)
        self.pricing = PricingMetrics(prop, self.mortgage.loan_balance,
                                      annual_rent if annual_rent else 1)  # avoid /0

        if annual_rent and annual_rent > 0:
            self._has_rent = True
            self.income   = IncomeMetrics(prop, annual_rent, breakdown)
            self.exit     = ExitMetrics(prop, self.income.entry_cap, self.income.est_noi, self.mortgage.loan_balance)
            self.cashflow = CashFlowMetrics(
                self.income.est_noi, self.mortgage.annual_mortgage, self.mortgage.down_payment,
                prop.construction_cost or 0
            )
            self.debt     = DebtMetrics(
                self.income.est_noi, self.income.est_expenses,
                self.mortgage.annual_mortgage, annual_rent
            )
            self.returns  = ReturnMetrics(prop, self.cashflow.annual_cash_flow,
                                          self.cashflow.cash_invested)
            self.market   = MarketMetrics(
                self.income.est_noi, self.cashflow.cash_invested,
                self.income.est_expenses, self.mortgage.annual_mortgage, self.dom.count
            )
            # Hotel-specific metrics
            is_hotel = (prop.property_type or "").strip().lower() == "hotel"
            self.hotel = HotelMetrics(prop, annual_rent) if is_hotel else None

            # Industrial breakdown metrics
            is_industrial = (prop.property_type or "").strip().lower() == "industrial"
            if is_industrial:
                base_rate = (annual_rent / prop.total_sq_ft) if prop.total_sq_ft else 0
                self.industrial = IndustrialMetrics(prop, base_rate)
            else:
                self.industrial = None
        else:
            self.income = self.exit = self.cashflow = self.debt = self.returns = self.market = None
            self.hotel       = None
            self.industrial  = None

    def report(self) -> list:
        rows = []
        for group in (self.mortgage, self.pricing, self.income, self.exit,
                      self.cashflow, self.debt, self.returns, self.market, self.hotel,
                      self.industrial):
            if group is not None:
                rows.extend(group.rows())
        return rows

    def to_record(self, existing: dict = None) -> dict:
        """Serializes the full analysis to a dict suitable for saving via DataStore.
        Pass existing record to preserve created_at and other non-analysis fields."""
        p = self.prop
        now = date.today().isoformat()
        record = {
            "address":          p.address,
            "mls_number":       p.mls_number,
            "status":           p.status,
            "listing_date":     p.listing_date,
            "created_at":       (existing or {}).get("created_at", now),
            "last_modified":    now,
            "analyzed_on":      now,
            "asking_price":     p.asking_price,
            "original_price":   p.original_price,
            "total_sq_ft":      p.total_sq_ft,
            "city":             p.city,
            "province":         p.province,
            "property_type":    p.property_type,
            # All fields needed to re-run analysis
            "property_taxes":   p.property_taxes,
            "down_payment_pct": p.down_payment_pct,
            "interest_rate":    p.interest_rate,
            "term_years":       p.term_years,
            "hold_years":       p.hold_years,
            "expense_ratio":    p.expense_ratio,
            "lease_type":       p.lease_type,
            "construction_cost": p.construction_cost or 0,
            "annual_rent":      self.income.annual_rent if self.income else p.annual_rent,
            "commercial_rent":  self._comm_rent if self._comm_rent else 0.0,
            "residential_rent": self._res_rent  if self._res_rent  else 0.0,
            "rent_breakdown":   self.income.rent_breakdown if self.income else [],
            "unit_mix":         {
                "bachelor":  p.unit_mix.bachelor  if p.unit_mix else 0,
                "one_br":    p.unit_mix.one_br     if p.unit_mix else 0,
                "two_br":    p.unit_mix.two_br     if p.unit_mix else 0,
                "three_br":  p.unit_mix.three_br   if p.unit_mix else 0,
                "four_br":   p.unit_mix.four_br    if p.unit_mix else 0,
                "unknown":   p.unit_mix.unknown    if p.unit_mix else 0,
                "floors":    p.unit_mix.floors     if p.unit_mix else (p.floors if hasattr(p, "floors") else 1),
            },
            "floors":           p.unit_mix.floors if p.unit_mix else 1,
            "hotel_rooms":      p.hotel_rooms or 0,
            "hotel_adr":        p.hotel_adr,
            "hotel_occupancy":  p.hotel_occupancy,
            "ind_warehouse_sqft":  p.ind_warehouse_sqft or 0,
            "ind_office_sqft":     p.ind_office_sqft    or 0,
            "ind_yard_sqft":       p.ind_yard_sqft      or 0,
            "ind_dock_doors":      p.ind_dock_doors     or 0,
            "ind_drive_in_doors":  p.ind_drive_in_doors or 0,
            "ind_clear_height_ft": p.ind_clear_height_ft or 0,
            "ind_office_rate":     p.ind_office_rate,
            "ind_yard_rate":       p.ind_yard_rate,
            "results":          [row.to_dict() for row in self.report()
                                 if row.grade != ""],
        }
        return record


# ---------------------------------------------------------------------------
# Report Printer
# ---------------------------------------------------------------------------

class ReportPrinter:

    DIVIDER = "-" * 75

    @classmethod
    def print_report(cls, analyzer: CommercialPropertyAnalyzer, show: bool = True):
        """Prints the full analysis table. Set show=False to suppress output."""
        if not show:
            return
        print(f"\n{'METRIC':<25} | {'VALUE':<30} | {'EVALUATION'}")
        print(cls.DIVIDER)
        for row in analyzer.report():
            print(row)
        print(cls.DIVIDER)
        print()

    @classmethod
    def list_properties(cls, store: DataStore):
        """Prints a summary table of all saved properties from the DataStore."""
        properties = store.load_properties()
        if not properties:
            print("\nNo saved properties found.")
            return

        col_num    = 3
        col_addr   = 30
        col_mls    = 12
        col_status = 8
        col_price  = 13
        col_sqft   = 8
        col_type   = 13
        col_list   = 12
        col_ana    = 12
        col_ok     = 2
        header = (
            f"{'#':<{col_num}} "
            f"{'ADDRESS':<{col_addr}} "
            f"{'MLS #':<{col_mls}} "
            f"{'STATUS':<{col_status}} "
            f"{'ASKING PRICE':>{col_price}} "
            f"{'SQ FT':>{col_sqft}} "
            f"{'TYPE':<{col_type}} "
            f"{'LISTED':<{col_list}} "
            f"{'ANALYZED':<{col_ana}} "
            f"{'A':<{col_ok}}"
        )
        divider = "-" * len(header)

        print(f"\n{'SAVED PROPERTIES':^{len(header)}}")
        print(divider)
        print(header)
        print(divider)

        def _sort_key(p):
            city    = p.get("city")
            addr    = p.get("address") or ""
            st_name, st_num = _parse_address_sort(addr)
            if city:
                return (0, city.lower(), st_name, st_num)
            return (1, st_name, st_num, "")

        properties = sorted(properties, key=_sort_key)
        for i, p in enumerate(properties, start=1):
            addr     = _display_address(p.get("address") or "")[:col_addr] or "\u2014"
            mls      = (p.get("mls_number") or "\u2014")[:col_mls]
            status   = (p.get("status") or "\u2014")[:col_status]
            price    = f"${p.get('asking_price', 0):,.0f}"
            sqft     = f"{p.get('total_sq_ft', 0):,.0f}"
            ptype    = (p.get("property_type") or "Residential")[:col_type]
            listed   = p.get("listing_date", "\u2014")
            analyzed = p.get("analyzed_on") or "\u2014"
            _income_keys = {"NOI", "Cap Rate", "Gross Rent", "Effective Gross", "Annual Revenue"}
            has_analysis = any(r.get("metric") in _income_keys for r in (p.get("results") or []))
            ana_flag = "\u2713" if has_analysis else "\u2014"
            print(
                f"{i:<{col_num}} "
                f"{addr:<{col_addr}} "
                f"{mls:<{col_mls}} "
                f"{status:<{col_status}} "
                f"{price:>{col_price}} "
                f"{sqft:>{col_sqft}} "
                f"{ptype:<{col_type}} "
                f"{listed:<{col_list}} "
                f"{analyzed:<{col_ana}} "
                f"{ana_flag:<{col_ok}}"
            )

        print(divider)
        print(f"  {len(properties)} propert{'y' if len(properties) == 1 else 'ies'} on file\n")


# ---------------------------------------------------------------------------
# Property Menu — interactive terminal UI for managing saved properties
# ---------------------------------------------------------------------------

class PropertyMenu:
    """
    Interactive terminal menu for listing, creating, editing,
    and deleting saved property records.
    """

    DIVIDER     = "-" * 75
    THIN_DIVIDER = "-" * 40

    def __init__(self, store: DataStore, resolver: RentResolver):
        self._store    = store
        self._resolver = resolver
        self._scan_existing_cities()

    def _scan_existing_cities(self):
        """On startup, ensure every city in saved properties exists in both rate files."""
        seen = set()
        for p in self._store.load_properties():
            city     = (p.get("city") or "").strip()
            province = (p.get("province") or "").strip()
            if city and province:
                key = (city.lower(), province.upper())
                if key not in seen:
                    seen.add(key)
                    self._store.ensure_city_in_rates(city, province)

    # ------------------------------------------------------------------
    # Menu loop
    # ------------------------------------------------------------------

    def run(self):
        while True:
            print(f"\n{'PROPERTY MANAGER':^{75}}")
            print(self.DIVIDER)
            print("  1  List all properties")
            print("  2  View analysis for a property")
            print("  3  Add a new property")
            print("  4  Edit a property")
            print("  5  Delete a property")
            print("  6  Open investment report in browser")
            print("  c  Open city opportunity report")
            print("  7  Edit commercial rent rates")
            print("  8  Edit residential rent rates")
            print("  9  Import properties from CSV")
            print("  r  Re-analyze all properties")
            print("  s  Scoring formula & weights")
            print("  0  Exit")
            print(self.DIVIDER)

            choice = input("  Select: ").strip()

            if   choice == "1": self._list()
            elif choice == "2": self._view()
            elif choice == "3": self._add()
            elif choice == "4": self._edit()
            elif choice == "5": self._delete()
            elif choice == "7": self._edit_commercial_rates()
            elif choice == "8": self._edit_residential_rates()
            elif choice == "9": self._import_csv()
            elif choice == "6": self._open_report()
            elif choice == "c": self._open_city_report()
            elif choice == "r": self._reanalyze_all()
            elif choice == "s": self._edit_score_config()
            elif choice == "0":
                print("  Goodbye.\n")
                break
            else:
                print("  Invalid option — try again.")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _list(self):
        ReportPrinter.list_properties(self._store)

    def _view(self):
        props = self._sorted_props()
        if not props:
            print("\n  No properties on file.")
            return
        self._list()
        idx = self._pick_index(props, "View analysis for #")
        if idx is None:
            return
        p = props[idx]
        results = p.get("results", [])
        if not results:
            print("  No analysis results saved for this property.")
            return
        city     = p.get("city",     "")
        province = p.get("province", "")
        ptype    = p.get("property_type", "")

        # Detect partial analysis (mortgage/pricing saved but no income rows)
        income_metrics = {"NOI", "Cap Rate", "Gross Rent", "Effective Gross", "Annual Revenue"}
        has_income = any(r.get("metric", "") in income_metrics for r in results)

        print(f"\n  Analysis: {_display_address(p.get('address','')) or '—'}  (analyzed {p.get('analyzed_on', '—')})")
        if not has_income and (city or ptype):
            if ptype and ptype.lower() in ("office","retail","industrial","mixed-use"):
                print(f"  ⚠  Partial results — no commercial rent rates for {city}, {province}.")
                print(f"     Use menu option 7 to add rates for {city}, then re-edit to refresh analysis.")
            else:
                print(f"  ⚠  Partial results — no residential rent rates for {city}, {province}.")
                print(f"     Use menu option 8 to add rates for {city}, then re-edit to refresh analysis.")
        print(self.DIVIDER)
        print(f"  {'METRIC':<25} {'VALUE':<22} EVALUATION")
        print(self.DIVIDER)
        for r in results:
            print(f"  {r['metric']:<25} {r['value']:<22} {r['grade']}")
        print(self.DIVIDER)
        notes = p.get("notes")
        if notes:
            print("\n  NOTES")
            print(self.THIN_DIVIDER)
            for line in notes.splitlines():
                print(f"  {line}")
            print()

    def _add(self):
        print(f"\n  ADD NEW PROPERTY")
        print(self.THIN_DIVIDER)
        try:
            prop = self._prompt_property()
        except KeyboardInterrupt:
            print("\n  Cancelled.")
            return
        except ValueError as e:
            print(f"\n  Error: {e}")
            return

        try:
            analyzer = CommercialPropertyAnalyzer(prop, self._resolver)
        except ValueError as e:
            print(f"  Error during analysis: {e}")
            return
        except Exception as e:
            print(f"  Unexpected error: {e}")
            return

        show = input("  Print full analysis? (y/n): ").strip().lower() in ("y", "yes")
        ReportPrinter.print_report(analyzer, show=show)
        record = analyzer.to_record()
        notes  = input("  Notes (Enter to skip): ").strip()
        if notes:
            record["notes"] = notes
        self._store.save_property(record)
        if prop.city and prop.province:
            self._store.ensure_city_in_rates(prop.city, prop.province)
        print(f"  Saved: {_display_address(prop.address)}")


    def _edit(self):
        props = self._sorted_props()
        if not props:
            print("\n  No properties on file.")
            return
        self._list()
        idx = self._pick_index(props, "Edit property #")
        if idx is None:
            return

        p = props[idx]
        # Find raw storage index (display order != storage order)
        raw_props = self._store.load_properties()
        _key      = (p.get("address",""), p.get("listing_date",""))
        raw_idx   = next((i for i,r in enumerate(raw_props)
                          if (r.get("address",""),r.get("listing_date","")) == _key), idx)

        # All editable fields: (menu_number, label, json_key, type, special)
        # special: "pct" = stored as decimal, display/input as %, "status" = validated choice
        FIELDS = [
            ( 1, "Address",                    "address",          str,   None),
            ( 2, "MLS #",                      "mls_number",       str,   None),
            ( 3, "Status",                     "status",           str,   "status"),
            ( 4, "Original price",             "original_price",   int,   "nodec"),
            ( 5, "Asking price",               "asking_price",     int,   "nodec"),
            ( 6, "Property type",              "property_type",    str,   "proptype"),
            ( 7, "Commercial rent / year",     "commercial_rent",  float, "optional"),
            ( 8, "Floors",                     "floors",           int,   "floors"),
            ( 9, "Total sq ft",                "total_sq_ft",      int,   "nodec"),
            (10, "Bachelor units",             "bachelor",         int,   "unit"),
            (11, "1BR units",                  "one_br",           int,   "unit"),
            (12, "2BR units",                  "two_br",           int,   "unit"),
            (13, "3BR units",                  "three_br",         int,   "unit"),
            (14, "4BR units",                  "four_br",          int,   "unit"),
            (15, "Unknown residential units",  "unknown",          int,   "unit"),
            (16, "Residential rent / year",    "residential_rent", float, "optional"),
            (17, "Annual property taxes",      "property_taxes",   float, None),
            (18, "Construction cost",          "construction_cost",float, "optional"),
            (19, "Down payment %",             "down_payment_pct", float, "pct"),
            (20, "Interest rate %",            "interest_rate",    float, "pct"),
            (21, "Loan term (years)",          "term_years",       int,   None),
            (22, "Hold years",                 "hold_years",       int,   None),
            (23, "Expense ratio %",            "expense_ratio",    float, "pct"),
            (24, "Lease type (Normal/NNN)",    "lease_type",       str,   None),
            (25, "Listing date (YYYY-MM-DD)", "listing_date",     str,   "date"),
            (26, "Notes",                      "notes",            str,   "notes"),
            (27, "Hotel rooms",                "hotel_rooms",      int,   "hotel"),
            (28, "Hotel ADR ($/night)",        "hotel_adr",        float, "hotel"),
            (29, "Hotel occupancy %",          "hotel_occupancy",  float, "hotel_pct"),
            (30, "Industrial: warehouse sqft", "ind_warehouse_sqft", float, "optional"),
            (31, "Industrial: office sqft",    "ind_office_sqft",    float, "optional"),
            (32, "Industrial: yard sqft",      "ind_yard_sqft",      float, "optional"),
            (33, "Industrial: dock doors",     "ind_dock_doors",     int,   "hotel"),
            (34, "Industrial: drive-in doors", "ind_drive_in_doors", int,   "hotel"),
            (35, "Industrial: clear height ft","ind_clear_height_ft",float, "optional"),
            (36, "Industrial: office rate $/sqft","ind_office_rate", float, "optional"),
            (37, "Industrial: yard rate $/sqft",  "ind_yard_rate",   float, "optional"),
        ]

        def current_display(key, special):
            """Returns a readable string of the current stored value."""
            if special == "unit":
                mix = p.get("unit_mix") or {}
                val = mix.get(key, 0) if isinstance(mix, dict) else 0
            else:
                val = p.get(key)
            if val is None:
                return "—"
            if special in ("pct", "hotel_pct"):
                return f"{val * 100:.2f}%"
            if special == "hotel":
                return str(val) if val else "—"
            if special == "nodec":
                try:
                    return f"{int(val):,}"
                except (ValueError, TypeError):
                    return str(val)
            return str(val)

        while True:
            print(f"\n  Editing: {_display_address(p.get('address','')) or '—'}  [MLS: {p.get('mls_number', '—')}]")
            created  = p.get("created_at",    p.get("listing_date", "—"))
            modified = p.get("last_modified", p.get("analyzed_on",  "—"))
            print(f"  Created: {created}   Last modified: {modified}")
            print(self.THIN_DIVIDER)
            for num, label, key, _, special in FIELDS:
                cur = current_display(key, special)
                print(f"  {num:>2}  {label:<30} (current: {cur})")
            print(f"   0  Done")
            print(self.THIN_DIVIDER)

            choice = input("  Field to edit (0 to finish): ").strip()
            if choice == "0":
                break

            # Find matching field
            match = next((f for f in FIELDS if str(f[0]) == choice), None)
            if not match:
                print("  Invalid — enter a number from the list.")
                continue

            num, label, key, cast, special = match

            cur = current_display(key, special)
            print(f"  Current: {cur}")

            # ── Status: validated choice ──────────────────────────────
            if special == "status":
                while True:
                    raw = input(f"  New {label} (a=active / i=inactive): ").strip().lower()
                    resolved = {"a": "active", "i": "inactive"}.get(raw, raw)
                    if resolved in ("active", "inactive"):
                        self._store.update_property(raw_idx, {key: resolved, "last_modified": date.today().isoformat()})
                        p[key] = resolved
                        print(f"  Updated to: {resolved}")
                        break
                    elif raw == "":
                        print("  No change made.")
                        break
                    else:
                        print("  Invalid — enter 'a' or 'i'.")
                continue

            # ── Percentage fields ─────────────────────────────────────
            if special == "pct":
                raw = input(f"  New {label} (e.g. 20 or 0.20, Enter to skip): ").strip()
                if not raw:
                    print("  No change made.")
                    continue
                try:
                    val = float(raw)
                    val = val / 100 if val > 1 else val
                    self._store.update_property(raw_idx, {key: val, "last_modified": date.today().isoformat()})
                    p[key] = val
                    print(f"  Updated to {val * 100:.2f}%")
                except ValueError:
                    print("  Invalid number.")
                continue

            # ── Unit counts: nested in unit_mix ──────────────────────
            if special == "unit":
                raw = input(f"  New {label} (Enter to skip): ").strip()
                if not raw:
                    print("  No change made.")
                    continue
                try:
                    val = int(raw)
                    # Update nested unit_mix dict in the record
                    mix = p.get("unit_mix") or {}
                    mix[key] = val
                    self._store.update_property(raw_idx, {"unit_mix": mix})
                    p["unit_mix"] = mix
                    print(f"  Updated.")
                except ValueError:
                    print("  Invalid number.")
                continue

            # ── Optional fields (can be cleared) ─────────────────────
            if special == "optional":
                raw = input(f"  New {label} (Enter to clear): ").strip()
                val = cast(raw) if raw else None
                self._store.update_property(raw_idx, {key: val})
                p[key] = val
                print(f"  Updated to: {val if val is not None else '(cleared)'}")
                continue

            # ── Lease type shorthand ─────────────────────────────────
            if key == "lease_type":
                while True:
                    raw = input(f"  New {label} (no=Normal / nn=NNN, Enter to skip): ").strip().lower()
                    if not raw:
                        print("  No change made.")
                        break
                    resolved_lt = {"no": "Normal", "n": "Normal", "normal": "Normal",
                                   "nn": "NNN", "nnn": "NNN"}.get(raw)
                    if resolved_lt:
                        self._store.update_property(raw_idx, {key: resolved_lt})
                        p[key] = resolved_lt
                        print(f"  Updated to: {resolved_lt}")
                        break
                    print("  Invalid — enter 'no' for Normal or 'nn' for NNN.")
                continue

            # ── No-decimal integer fields ─────────────────────────────
            if special == "nodec":
                raw = input(f"  New {label} (Enter to skip): ").strip()
                if not raw:
                    print("  No change made.")
                    continue
                try:
                    val = int(float(raw.replace(",", "")))
                    self._store.update_property(raw_idx, {key: val})
                    p[key] = val
                    print(f"  Updated to: {val:,}")
                except ValueError:
                    print(f"  Invalid number.")
                continue

            # ── Property type with shorthand ──────────────────────────
            if special == "proptype":
                PROP_SHORTCUTS = {
                    "o": "Office", "r": "Retail", "i": "Industrial",
                    "m": "Mixed-Use", "re": "Residential", "mu": "Multi-Family", "h": "Hotel", "ro": "Retail-Office"
                }
                VALID_TYPES = set(PROP_SHORTCUTS.values())
                print("  o=Office  r=Retail  i=Industrial  m=Mixed-Use  re=Residential  mu=Multi-Family  h=Hotel  ro=Retail-Office")
                while True:
                    raw = input(f"  New {label} (Enter to skip): ").strip()
                    if not raw:
                        print("  No change made.")
                        break
                    resolved = PROP_SHORTCUTS.get(raw.lower())
                    if not resolved:
                        resolved = next((v for v in VALID_TYPES if v.lower() == raw.lower()), None)
                    if not resolved:
                        print(f"  Invalid — must be one of: {', '.join(sorted(VALID_TYPES))}.")
                        continue
                    self._store.update_property(raw_idx, {key: resolved, "last_modified": date.today().isoformat()})
                    p[key] = resolved
                    print(f"  Updated to: {resolved}")
                    break
                continue

            # ── Date fields (YYYY-MM-DD) ──────────────────────────────
            if special == "date":
                while True:
                    raw = input(f"  New {label} (YYYY-MM-DD, Enter to skip): ").strip()
                    if not raw:
                        print("  No change made.")
                        break
                    try:
                        date.fromisoformat(raw)   # validate format
                        self._store.update_property(raw_idx, {key: raw, "last_modified": date.today().isoformat()})
                        p[key] = raw
                        print(f"  Updated to: {raw}")
                        break
                    except ValueError:
                        print("  Invalid date — use YYYY-MM-DD format (e.g. 2025-06-15).")
                continue

            # ── Notes: free-text, multiline allowed via \n ────────────────
            if special == "notes":
                cur_notes = p.get("notes") or ""
                if cur_notes:
                    print(f"  Current notes:")
                    for line in cur_notes.splitlines():
                        print(f"    {line}")
                raw = input("  New notes (Enter to keep current, 'clear' to delete): ").strip()
                if raw.lower() == "clear":
                    self._store.update_property(raw_idx, {"notes": None, "last_modified": date.today().isoformat()})
                    p["notes"] = None
                    print("  Notes cleared.")
                elif raw:
                    self._store.update_property(raw_idx, {"notes": raw, "last_modified": date.today().isoformat()})
                    p["notes"] = raw
                    print("  Notes updated.")
                else:
                    print("  No change made.")
                continue

            # ── Floors: update both top-level and unit_mix.floors ────────
            if special == "floors":
                raw = input(f"  New {label} (Enter to skip): ").strip()
                if not raw:
                    print("  No change made.")
                    continue
                try:
                    val = int(raw)
                    mix = p.get("unit_mix") or {}
                    mix["floors"] = val
                    self._store.update_property(raw_idx, {"floors": val, "unit_mix": mix, "last_modified": date.today().isoformat()})
                    p["floors"] = val
                    p["unit_mix"] = mix
                    print(f"  Updated to: {val}")
                except ValueError:
                    print("  Invalid number.")
                continue

            # ── Hotel numeric fields ──────────────────────────────────
            if special == "hotel":
                raw = input(f"  New {label} (Enter to skip): ").strip()
                if not raw:
                    print("  No change made.")
                    continue
                try:
                    val = int(float(raw.replace(",", "")))
                    self._store.update_property(raw_idx, {key: val, "last_modified": date.today().isoformat()})
                    p[key] = val
                    print(f"  Updated to: {val}")
                except ValueError:
                    print("  Invalid number.")
                continue

            if special == "hotel_pct":
                raw = input(f"  New {label} (e.g. 65 for 65%, Enter to skip): ").strip()
                if not raw:
                    print("  No change made.")
                    continue
                try:
                    val = float(raw.replace("%", ""))
                    val = val / 100 if val > 1 else val
                    self._store.update_property(raw_idx, {key: val, "last_modified": date.today().isoformat()})
                    p[key] = val
                    print(f"  Updated to: {val*100:.1f}%")
                except ValueError:
                    print("  Invalid number.")
                continue

            # ── Standard fields ───────────────────────────────────────
            raw = input(f"  New {label} (Enter to skip): ").strip()
            if not raw:
                print("  No change made.")
                continue
            try:
                val = cast(raw)
                self._store.update_property(raw_idx, {key: val})
                p[key] = val
                print(f"  Updated to: {val}")
            except ValueError:
                print(f"  Invalid value for {label}.")

        # Re-run analysis with updated record
        p = self._store.load_properties()[raw_idx]   # reload with all edits applied
        try:
            prop     = self._record_to_prop(p)
            analyzer = CommercialPropertyAnalyzer(prop, self._resolver)
            record   = analyzer.to_record(existing=p)
            self._store.update_property(raw_idx, record)
            if analyzer._has_rent:
                print(f"  Analysis updated (full).")
            else:
                city     = p.get("city",     "unknown city")
                province = p.get("province", "ON")
                ptype    = p.get("property_type")
                if ptype and ptype.lower() in ("office","retail","industrial","mixed-use","hotel","retail-office"):
                    print(f"  Partial analysis only — no commercial rent rates for {city}, {province}.")
                    print(f"  Use menu option 7 to add {city} commercial rates, then income/cashflow/returns metrics will appear.")
                else:
                    print(f"  Partial analysis only — no residential rent rates for {city}, {province}.")
                    print(f"  Use menu option 8 to add {city} residential rates, then income/cashflow/returns metrics will appear.")
        except ValueError as e:
            print(f"  Analysis could not be run: {e}")
        except Exception as e:
            print(f"  Unexpected error during analysis: {e}")

        print(f"  Edit complete.")


    # ------------------------------------------------------------------
    # Investment Report
    # ------------------------------------------------------------------

    # Default scoring config — saved to / loaded from json/score_weights.json
    DEFAULT_SCORE_CONFIG = {
        "weights": {
            "Cap Rate":        0.25,
            "CoCR":            0.20,
            "DSCR":            0.15,
            "IRR":             0.15,
            "Equity Multiple": 0.10,
            "Cash Flow":       0.10,
            "Price Drop":      0.03,
            "DOM":             0.02,
            "Location":        0.00,   # disabled by default until distances are set
        },
        "thresholds": {
            # (floor, ceiling) — floor = score 0, ceiling = score 10
            "Cap Rate":        [3,   8],
            "CoCR":            [0,  10],
            "DSCR":            [1,   1.5],
            "IRR":             [5,  15],
            "Equity Multiple": [1,   2.0],
            "Cash Flow":       [0,  20000],
            "Price Drop":      [0,  10],
            "DOM":             [30, 150],
            # Location: distance in km to nearest regional centre (closer = better)
            # floor=max bad distance, ceiling=ideal distance (0 = in a centre)
            "Location":        [200, 0],
        },
        "location_penalty": True,   # True = closer is better (lower distance = higher score)
        "city_weights": {
            "avg_score":  0.30,   # average investment score of deals in city
            "best_score": 0.10,   # best single deal available
            "volume":     0.15,   # number of active listings
            "cap_rate":   0.15,   # avg cap rate environment
            "price_drop": 0.10,   # avg seller price reduction
            "dom":        0.10,   # avg days on market (market softness)
            "coc":        0.10,   # avg cash-on-cash return
        },
    }
    SCORE_CONFIG_PATH = "json/score_weights.json"

    def _load_score_config(self) -> dict:
        if os.path.exists(self.SCORE_CONFIG_PATH):
            try:
                cfg = self._store._read(self.SCORE_CONFIG_PATH)
                # Merge with defaults so new keys are always present
                out = copy.deepcopy(self.DEFAULT_SCORE_CONFIG)
                for section in ("weights", "thresholds", "city_weights"):
                    if section in cfg:
                        out[section].update(cfg[section])
                return out
            except Exception:
                pass
        return copy.deepcopy(self.DEFAULT_SCORE_CONFIG)

    def _save_score_config(self, cfg: dict):
        os.makedirs(os.path.dirname(self.SCORE_CONFIG_PATH) if os.path.dirname(self.SCORE_CONFIG_PATH) else ".", exist_ok=True)
        self._store._write(self.SCORE_CONFIG_PATH, cfg)

    def _load_city_distances(self) -> dict:
        """Returns dict of city_lower -> {distance_km, nearest_centre}."""
        path = "json/city_distances.json"
        if os.path.exists(path):
            try:
                return {k.lower(): v for k, v in self._store._read(path).items()}
            except Exception:
                pass
        return {}

    def _score_property(self, p: dict) -> dict:
        """
        Compute a 0-100 investment score from saved analysis results.
        Weights and thresholds are loaded from json/score_weights.json.
        Only properties with full income analysis are scored.
        """
        results = {r["metric"]: r for r in (p.get("results") or [])}
        INCOME = {"NOI", "Cap Rate", "Gross Rent", "Effective Gross", "Annual Revenue"}
        if not any(m in results for m in INCOME):
            return {"score": None, "breakdown": {}}

        cfg       = self._load_score_config()
        weights   = cfg["weights"]
        thresholds = cfg["thresholds"]

        def val(metric, default=0.0):
            row = results.get(metric)
            if not row:
                return default
            raw = row.get("value", "0")
            cleaned = "".join(c for c in str(raw) if c.isdigit() or c in ".-")
            return float(cleaned) if cleaned else default

        def clamp(v, lo, hi): return max(lo, min(hi, v))

        def component(key, raw_value, invert=False):
            lo, hi = thresholds.get(key, [0, 1])
            if hi == lo:
                return 0.0
            if invert:  # lower raw_value = better (e.g. distance)
                s = (lo - raw_value) / (lo - hi)
            else:
                s = (raw_value - lo) / (hi - lo)
            return clamp(s * 10, 0, 10)

        cap_rate   = val("Cap Rate")
        coc        = val("CoCR")
        dscr       = val("DSCR")
        irr        = val("IRR (5-Yr)")
        em         = val("Equity Multiple")
        cf_annual  = val("Annual Cash Flow")
        price_drop = val("Price Drop %")
        dom        = val("Market Staleness", 0)

        # Location score
        city = (p.get("city") or "").lower()
        distances = self._load_city_distances()
        dist_info = distances.get(city)
        dist_km   = dist_info["distance_km"] if dist_info else None
        s_location = component("Location", dist_km, invert=True) if dist_km is not None else 0.0

        scores = {
            "Cap Rate":        component("Cap Rate",        cap_rate),
            "CoCR":            component("CoCR",            coc),
            "DSCR":            component("DSCR",            dscr),
            "IRR":             component("IRR",             irr),
            "Equity Multiple": component("Equity Multiple", em),
            "Cash Flow":       component("Cash Flow",       cf_annual),
            "Price Drop":      component("Price Drop",      price_drop),
            "DOM":             component("DOM",             dom),
            "Location":        s_location,
        }

        # Normalize weights so they always sum to 1.0
        active_w = {k: w for k, w in weights.items() if w > 0}
        total_w  = sum(active_w.values())
        score    = 0.0
        if total_w > 0:
            score = sum(scores[k] * (w / total_w) for k, w in active_w.items()) * 10

        return {
            "score":      round(score, 1),
            "breakdown":  {k: round(scores[k] * 10, 1) for k in scores},
            "weights":    weights,
            "cap_rate":   cap_rate,
            "coc":        coc,
            "dscr":       dscr,
            "irr":        irr,
            "em":         em,
            "cf_annual":  cf_annual,
            "price_drop": price_drop,
            "dom":        int(dom),
            "dist_km":    dist_km,
            "dist_centre": dist_info["nearest_centre"] if dist_info else None,
        }


    def _solve_targets(self, p: dict) -> dict:
        """
        For each lever (price, rent, interest rate, down payment),
        binary-search the value that would push the investment score to 100.
        Returns a dict of {lever: target_value} or None if already at 100 / unsolvable.
        """
        base_scored = self._score_property(p)
        if base_scored["score"] is None:
            return {}
        if base_scored["score"] >= 99.5:
            return {}  # already perfect

        def score_with(overrides: dict) -> float:
            """Re-run analyzer on a modified record and return the investment score."""
            rec = copy.deepcopy(p)
            rec.update(overrides)
            # Rebuild rent fields so the resolver uses the overridden annual_rent
            if "annual_rent" in overrides:
                rec["commercial_rent"] = None
                rec["residential_rent"] = None
            try:
                prop     = self._record_to_prop(rec)
                analyzer = CommercialPropertyAnalyzer(prop, self._resolver)
                new_rec  = analyzer.to_record(existing=rec)
                rec.update({k: v for k, v in new_rec.items() if k == "results"})
                return self._score_property(rec).get("score") or 0.0
            except Exception:
                return 0.0

        def bisect_lever(override_key, lo, hi, n=60, invert=False):
            """Binary search for the value of override_key that yields score >= 99.5."""
            # invert=True means lower value is better (e.g. price, interest rate)
            for _ in range(n):
                mid = (lo + hi) / 2
                s   = score_with({override_key: mid})
                if s >= 99.5:
                    if invert:
                        lo = mid   # can we go even higher (worse)?  no — keep tightening
                    else:
                        hi = mid
                else:
                    if invert:
                        hi = mid   # need to go lower
                    else:
                        lo = mid
            return (lo + hi) / 2

        base_price   = p.get("asking_price", 0)
        base_rent    = (p.get("commercial_rent") or 0) + (p.get("residential_rent") or 0)
        base_rate    = p.get("interest_rate", 0.045)
        base_dp      = p.get("down_payment_pct", 0.20)

        targets = {}

        # ── Asking price ── lower is better; search down to 10% of current
        if base_price > 0:
            lo_p, hi_p = base_price * 0.10, base_price
            lo_score   = score_with({"asking_price": lo_p})
            if lo_score >= 99.5:
                t = bisect_lever("asking_price", lo_p, hi_p, invert=True)
                if t < base_price * 0.999:
                    targets["price"] = round(t / 1000) * 1000   # round to nearest $1K

        # ── Annual rent ── higher is better; search up to 5x current
        if base_rent > 0:
            lo_r, hi_r = base_rent, base_rent * 5
            hi_score   = score_with({"annual_rent": hi_r})
            if hi_score >= 99.5:
                t = bisect_lever("annual_rent", lo_r, hi_r)
                if t > base_rent * 1.001:
                    targets["rent"] = round(t / 100) * 100       # round to nearest $100

        # ── Interest rate ── lower is better; search down to 0.5%
        if base_rate > 0:
            lo_i, hi_i = 0.005, base_rate
            lo_score   = score_with({"interest_rate": lo_i})
            if lo_score >= 99.5:
                t = bisect_lever("interest_rate", lo_i, hi_i, invert=True)
                if t < base_rate * 0.999:
                    targets["rate"] = round(t * 10000) / 10000   # 4 decimal places

        # ── Down payment ── higher reduces debt load; search up to 95%
        if base_dp < 0.95:
            lo_d, hi_d = base_dp, 0.95
            hi_score   = score_with({"down_payment_pct": hi_d})
            if hi_score >= 99.5:
                t = bisect_lever("down_payment_pct", lo_d, hi_d)
                if t > base_dp * 1.001:
                    targets["down_pct"] = round(t * 1000) / 1000  # 0.1% precision

        return targets


    def _open_city_report(self):
        """Build and open a standalone city investment ranking page."""
        props = self._store.load_properties()
        if not props:
            print("\n  No properties on file.")
            return

        cfg = self._load_score_config()
        print("  Building city investment report", end="", flush=True)

        city_data = defaultdict(list)
        for p in props:
            scored = self._score_property(p)
            city   = (p.get("city") or "Unknown").strip()
            prov   = (p.get("province") or "").strip()
            key    = f"{city}, {prov}" if prov else city
            city_data[key].append({
                "score":      scored.get("score"),
                "cap_rate":   scored.get("cap_rate",  0) or 0,
                "coc":        scored.get("coc",        0) or 0,
                "irr":        scored.get("irr",        0) or 0,
                "dscr":       scored.get("dscr",       0) or 0,
                "cf_annual":  scored.get("cf_annual",  0) or 0,
                "price_drop": scored.get("price_drop", 0) or 0,
                "dom":        scored.get("dom",         0) or 0,
                "asking":     p.get("asking_price", 0) or 0,
                "status":     (p.get("status") or "active").lower(),
                "address":    p.get("address", ""),
                "type":       p.get("property_type", ""),
            })
            print(".", end="", flush=True)
        print(" done.")

        def avg(lst, k):
            v = [e[k] for e in lst if e.get(k) is not None and e[k] != 0]
            return round(sum(v) / len(v), 2) if v else 0

        def norm(v, lo, hi):
            if hi == lo: return 0
            return max(0.0, min(1.0, (v - lo) / (hi - lo)))

        cw = cfg.get("city_weights", {})
        cities = []
        for key, entries in city_data.items():
            active    = [e for e in entries if e["status"] == "active"]
            inactive  = [e for e in entries if e["status"] != "active"]
            scored_e  = [e for e in entries if e["score"] is not None]
            n_active  = len(active)
            n_inactive= len(inactive)
            as_       = avg(scored_e, "score")
            bs        = max((e["score"] for e in scored_e), default=0)
            ac        = avg(entries,  "cap_rate")
            acoc      = avg(entries,  "coc")
            airr      = avg(entries,  "irr")
            adscr     = avg(entries,  "dscr")
            acf       = avg(entries,  "cf_annual")
            ad        = avg(entries,  "price_drop")   # active + inactive
            adom      = avg(active,   "dom")
            ap_active = avg(active,   "asking")
            ap_inact  = avg(inactive, "asking")
            opp = round(
                norm(as_,   0,   100) * cw.get("avg_score",  0.30) * 100 +
                norm(bs,    0,   100) * cw.get("best_score", 0.10) * 100 +
                norm(n_active, 1, 10) * cw.get("volume",     0.15) * 100 +
                norm(ac,    3,   9)   * cw.get("cap_rate",   0.15) * 100 +
                norm(ad,    0,   15)  * cw.get("price_drop", 0.10) * 100 +
                norm(adom, 30,  180)  * cw.get("dom",        0.10) * 100 +
                norm(acoc,  0,   12)  * cw.get("coc",        0.10) * 100, 1)

            # Collect property type breakdown
            type_counts = defaultdict(int)
            for e in entries:
                t = (e.get("type") or "Unknown").strip()
                if t:
                    type_counts[t] += 1

            cities.append(dict(
                city=key, total=len(entries),
                active=n_active, inactive=n_inactive,
                avg_score=as_, best_score=round(bs, 1),
                avg_cap=ac, avg_coc=acoc, avg_irr=airr,
                avg_dscr=adscr, avg_cf=int(acf),
                avg_drop=ad, avg_dom=int(adom),
                avg_price_active=int(ap_active),
                avg_price_inactive=int(ap_inact),
                opportunity=opp,
                type_counts=dict(type_counts),
                props_active=[e for e in active],
                props_inactive=[e for e in inactive],
            ))

        cities.sort(key=lambda c: c["opportunity"], reverse=True)

        # ── Build standalone HTML ──────────────────────────────────────────
        import json as _json

        def _fm(n):
            if not n: return "—"
            if n >= 1_000_000: return f"${n/1_000_000:.1f}M"
            if n >= 1_000:     return f"${n/1_000:.0f}K"
            return f"${n:,.0f}"

        cities_json = _json.dumps([{
            k: v for k, v in c.items()
            if k not in ("props_active", "props_inactive")
        } for c in cities], indent=2)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>City Investment Rankings</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink:   #0f0f0f;
    --paper: #f5f0e8;
    --cream: #ede8dc;
    --rule:  #c8bfaa;
    --gold:  #b8960c;
    --green: #2d6a4f;
    --red:   #8b1a1a;
    --amber: #c17f24;
    --muted: #6b6355;
    --mono:  'DM Mono', monospace;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--paper);
    color: var(--ink);
    font-family: 'DM Sans', sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }}
  header {{
    background: var(--cream);
    border-bottom: 3px double var(--rule);
    padding: 2rem 2.5rem 1.5rem;
  }}
  header h1 {{
    font-family: 'DM Serif Display', serif;
    font-size: 2.4rem;
    letter-spacing: -0.02em;
    line-height: 1;
  }}
  header h1 em {{ font-style: italic; color: var(--gold); }}
  .header-meta {{
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    margin-top: 0.4rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}
  .page-wrap {{
    max-width: 860px;
    margin: 0 auto;
    padding: 2rem 2rem 4rem;
  }}
  /* ── Ranked list ── */
  .city-list {{
    display: flex;
    flex-direction: column;
    gap: 0;
  }}
  .city-row {{
    border: 1px solid var(--rule);
    border-top: none;
    background: white;
    transition: background 0.1s;
    cursor: pointer;
  }}
  .city-row:first-child {{ border-top: 1px solid var(--rule); border-radius: 2px 2px 0 0; }}
  .city-row:last-child  {{ border-radius: 0 0 2px 2px; }}
  .city-row:hover .city-row-main {{ background: #fffdf5; }}
  .city-row-main {{
    display: grid;
    grid-template-columns: 48px 1fr auto 180px;
    align-items: center;
    padding: 1rem 1.2rem;
    gap: 1rem;
    border-left: 5px solid var(--rule);
    transition: border-color 0.15s;
  }}
  .city-row.rank-1 .city-row-main  {{ border-left-color: #b8960c; }}
  .city-row.rank-2 .city-row-main  {{ border-left-color: #9aa0a6; }}
  .city-row.rank-3 .city-row-main  {{ border-left-color: #cd7f32; }}
  .city-row.excellent .city-row-main {{ border-left-color: var(--green); }}
  .city-row.good      .city-row-main {{ border-left-color: #8db87a; }}
  .city-row.fair      .city-row-main {{ border-left-color: var(--amber); }}
  .city-row.poor      .city-row-main {{ border-left-color: var(--red); }}
  .rank-num {{
    font-family: var(--mono);
    font-size: 1.2rem;
    font-weight: 500;
    color: var(--muted);
    text-align: center;
  }}
  .city-info {{ min-width: 0; }}
  .city-name {{
    font-family: 'DM Serif Display', serif;
    font-size: 1.35rem;
    line-height: 1.1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .city-pills {{
    display: flex;
    gap: 0.5rem;
    margin-top: 0.25rem;
    flex-wrap: wrap;
  }}
  .pill {{
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    padding: 0.1rem 0.5rem;
    border: 1px solid var(--rule);
    border-radius: 2px;
    color: var(--muted);
    background: var(--cream);
  }}
  .pill.active {{ color: var(--green); border-color: var(--green); background: #edf7f1; }}
  .pill.inactive {{ color: var(--muted); border-color: var(--rule); }}
  /* Score column */
  .city-score-col {{
    text-align: right;
  }}
  .city-opp-num {{
    font-family: var(--mono);
    font-size: 1.6rem;
    font-weight: 500;
    line-height: 1;
  }}
  .city-opp-label {{
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    margin-top: 0.1rem;
  }}
  /* Bar + metrics strip */
  .city-metrics {{
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }}
  .opp-bar-track {{
    height: 6px;
    background: var(--cream);
    border: 1px solid var(--rule);
    border-radius: 0;
    overflow: hidden;
  }}
  .opp-bar-fill {{ height: 100%; transition: width 0.3s; }}
  .mini-stats {{
    display: flex;
    gap: 0.8rem;
    font-family: var(--mono);
    font-size: 10px;
    color: var(--muted);
    flex-wrap: wrap;
  }}
  .mini-stat span {{ font-weight: 500; }}
  .mini-stat span.good {{ color: var(--green); }}
  .mini-stat span.fair {{ color: var(--amber); }}
  .mini-stat span.poor {{ color: var(--red); }}
  /* Expand chevron */
  .chevron {{
    display: inline-block;
    transition: transform 0.2s;
    font-size: 0.7rem;
    color: var(--muted);
    margin-left: 0.4rem;
  }}
  .city-row.open .chevron {{ transform: rotate(180deg); }}
  /* Detail panel */
  .city-detail {{
    display: none;
    padding: 1.2rem 1.5rem 1.5rem 1.5rem;
    border-top: 1px dashed var(--rule);
    background: var(--cream);
  }}
  .city-row.open .city-detail {{ display: block; }}
  .detail-verdict {{
    font-size: 13.5px;
    line-height: 1.65;
    color: var(--ink);
    padding: 0.8rem 1rem;
    background: white;
    border-left: 3px solid var(--gold);
    margin-bottom: 1.2rem;
  }}
  .detail-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.7rem;
    margin-bottom: 1.2rem;
  }}
  .detail-card {{
    background: white;
    border: 1px solid var(--rule);
    padding: 0.65rem 0.8rem;
  }}
  .detail-card-label {{
    font-family: var(--mono);
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
    margin-bottom: 0.2rem;
  }}
  .detail-card-val {{
    font-family: var(--mono);
    font-size: 1.05rem;
    font-weight: 500;
  }}
  .detail-card-val.good {{ color: var(--green); }}
  .detail-card-val.fair {{ color: var(--amber); }}
  .detail-card-val.poor {{ color: var(--red); }}
  .detail-card-val.info {{ color: var(--ink); }}
  .detail-card-sub {{
    font-size: 10px;
    color: var(--muted);
    margin-top: 0.15rem;
  }}
  /* Factor bars */
  .factor-section-title {{
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.3rem;
    margin-bottom: 0.6rem;
    margin-top: 1rem;
  }}
  .factor-bar-row {{
    display: flex;
    align-items: center;
    gap: 0.7rem;
    padding: 0.2rem 0;
    font-size: 12px;
  }}
  .factor-bar-label {{ width: 160px; color: var(--muted); flex-shrink: 0; font-size: 11px; }}
  .factor-bar-track {{
    flex: 1;
    height: 7px;
    background: white;
    border: 1px solid var(--rule);
    overflow: hidden;
  }}
  .factor-bar-fill {{ height: 100%; background: var(--gold); }}
  .factor-bar-right {{
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    width: 100px;
    text-align: right;
    flex-shrink: 0;
  }}
  .good {{ color: var(--green); }}
  .fair {{ color: var(--amber); }}
  .poor {{ color: var(--red); }}
</style>
</head>
<body>
<header>
  <h1>City <em>Investment</em> Rankings</h1>
  <div class="header-meta" id="report-date"></div>
</header>

<div class="page-wrap">
  <div class="city-list" id="city-list">
  </div>
</div>

<script>
const CITIES = {cities_json};

function fp(n)  {{ return n ? n.toFixed(1) + '%' : '—'; }}
function fi(n)  {{ return (n !== null && n !== undefined && n !== 0) ? n.toFixed(0) : '—'; }}
function fm(n)  {{
  if (!n) return '—';
  if (n >= 1e6) return '$' + (n/1e6).toFixed(1) + 'M';
  if (n >= 1e3) return '$' + (n/1e3).toFixed(0) + 'K';
  return '$' + n.toLocaleString('en-CA');
}}
function gc(metric, v) {{
  if (!v && v !== 0) return 'info';
  if (metric === 'cap')   return v >= 7   ? 'good' : v >= 5   ? 'fair' : 'poor';
  if (metric === 'coc')   return v >= 10  ? 'good' : v >= 5   ? 'fair' : 'poor';
  if (metric === 'irr')   return v >= 15  ? 'good' : v >= 10  ? 'fair' : 'poor';
  if (metric === 'dscr')  return v >= 1.5 ? 'good' : v >= 1.25? 'fair' : 'poor';
  if (metric === 'score') return v >= 70  ? 'good' : v >= 45  ? 'fair' : 'poor';
  if (metric === 'drop')  return v > 2    ? 'good' : v > 0    ? 'fair' : 'info';
  if (metric === 'dom')   return v >= 90  ? 'good' : v >= 60  ? 'fair' : 'info';
  return 'info';
}}

function gradeOf(opp) {{
  if (opp >= 75) return ['excellent', 'Excellent'];
  if (opp >= 55) return ['good',      'Good'];
  if (opp >= 35) return ['fair',      'Fair'];
  return ['poor', 'Weak'];
}}

function oppColor(opp) {{
  if (opp >= 65) return 'var(--green)';
  if (opp >= 35) return 'var(--amber)';
  return 'var(--red)';
}}

function buildVerdict(c, rank) {{
  const strengths = [], weaknesses = [];
  if (c.avg_score >= 60)  strengths.push(`average deal score of ${{fi(c.avg_score)}}/100`);
  else if (c.avg_score > 0 && c.avg_score < 40) weaknesses.push(`low average deal score (${{fi(c.avg_score)}}/100)`);
  if (c.avg_cap >= 7)     strengths.push(`strong cap rate of ${{fp(c.avg_cap)}}`);
  else if (c.avg_cap > 0 && c.avg_cap < 5) weaknesses.push(`below-target cap rate (${{fp(c.avg_cap)}})`);
  if (c.avg_coc >= 10)    strengths.push(`solid cash-on-cash return (${{fp(c.avg_coc)}})`);
  else if (c.avg_coc > 0 && c.avg_coc < 5)  weaknesses.push(`low cash-on-cash (${{fp(c.avg_coc)}})`);
  if (c.avg_irr >= 15)    strengths.push(`high avg IRR of ${{fp(c.avg_irr)}}`);
  if (c.avg_drop > 3)     strengths.push(`avg price reduction of ${{fp(c.avg_drop)}} signals motivated sellers`);
  else if (c.avg_drop === 0) weaknesses.push(`no price reductions on record`);
  if (c.avg_dom >= 90)    strengths.push(`properties averaging ${{c.avg_dom}} days listed`);
  else if (c.avg_dom > 0 && c.avg_dom < 30) weaknesses.push(`fast-moving market (${{c.avg_dom}}d avg DOM)`);
  if (c.active >= 5)      strengths.push(`healthy supply with ${{c.active}} active listings`);
  else if (c.active === 0) weaknesses.push(`no active listings — limited deal flow`);
  if (c.inactive > 0)     weaknesses.push(`${{c.inactive}} inactive propert${{c.inactive===1?'y':'ies'}} reducing current options`);

  let out = `Ranked <strong>#${{rank}}</strong> out of ${{CITIES.length}} cities`;
  if (strengths.length)  out += ` — driven by ${{strengths.join('; ')}}.`;
  else                   out += ` with no standout metrics.`;
  if (weaknesses.length) out += ` Key headwinds: ${{weaknesses.join('; ')}}.`;
  return out;
}}

function renderCity(c, i) {{
  const rank       = i + 1;
  const [grade, gradeLabel] = gradeOf(c.opportunity);
  const barColor   = oppColor(c.opportunity);
  const barW       = Math.min(100, c.opportunity);
  const rankClass  = rank <= 3 ? `rank-${{rank}}` : grade;

  // Mini stats strip
  const miniStats = [
    c.avg_cap  ? `Cap <span class="${{gc('cap', c.avg_cap)}}">${{fp(c.avg_cap)}}</span>` : '',
    c.avg_coc  ? `CoCR <span class="${{gc('coc', c.avg_coc)}}">${{fp(c.avg_coc)}}</span>` : '',
    c.avg_irr  ? `IRR <span class="${{gc('irr', c.avg_irr)}}">${{fp(c.avg_irr)}}</span>` : '',
    c.avg_score? `Avg Score <span class="${{gc('score', c.avg_score)}}">${{fi(c.avg_score)}}</span>` : '',
  ].filter(Boolean).map(s => `<span class="mini-stat">${{s}}</span>`).join('');

  // Type breakdown
  const typeStr = Object.entries(c.type_counts || {{}})
    .sort((a,b) => b[1]-a[1])
    .map(([t,n]) => `${{n}}× ${{t}}`).join(', ');

  // Detail cards
  const cards = [
    {{ label:'Avg Deal Score',   val: c.avg_score ? fi(c.avg_score)+'/100' : '—', cls: gc('score',c.avg_score), sub:'all properties' }},
    {{ label:'Best Deal Score',  val: c.best_score? fi(c.best_score)+'/100':'—',  cls: gc('score',c.best_score),sub:'top property' }},
    {{ label:'Avg Cap Rate',     val: fp(c.avg_cap),   cls: gc('cap',c.avg_cap),   sub:'≥7% = strong' }},
    {{ label:'Avg CoCR',         val: fp(c.avg_coc),   cls: gc('coc',c.avg_coc),   sub:'≥10% = strong' }},
    {{ label:'Avg IRR',          val: fp(c.avg_irr),   cls: gc('irr',c.avg_irr),   sub:'≥15% = strong' }},
    {{ label:'Avg DSCR',         val: c.avg_dscr ? c.avg_dscr.toFixed(2):'—', cls: gc('dscr',c.avg_dscr), sub:'≥1.5 = strong' }},
    {{ label:'Avg Price Drop',   val: fp(c.avg_drop),  cls: gc('drop',c.avg_drop), sub:'from original list' }},
    {{ label:'Avg Days Listed',  val: c.avg_dom ? c.avg_dom+'d':'—', cls: gc('dom',c.avg_dom), sub:'active only' }},
    {{ label:'Active Listings',  val: c.active,        cls: c.active>=3?'good':c.active>=1?'fair':'poor', sub:`of ${{c.total}} total` }},
    {{ label:'Inactive Props',   val: c.inactive || '0', cls:'info', sub:'sold/off market' }},
    {{ label:'Avg Active Price', val: fm(c.avg_price_active),   cls:'info', sub:'active listings' }},
    {{ label:'Avg Inactive Price',val: fm(c.avg_price_inactive),cls:'info', sub:'inactive listings' }},
  ];
  const cardsHtml = cards.map(cd => `
    <div class="detail-card">
      <div class="detail-card-label">${{cd.label}}</div>
      <div class="detail-card-val ${{cd.cls}}">${{cd.val}}</div>
      <div class="detail-card-sub">${{cd.sub}}</div>
    </div>`).join('');

  // Factor contribution bars
  const W = {{ 'Avg Deal Score':0.30, 'Best Deal Score':0.10, 'Active Volume':0.15,
               'Avg Cap Rate':0.15,   'Avg Price Drop':0.10,  'Avg DOM':0.10, 'Avg CoCR':0.10 }};
  function norm(v, lo, hi) {{ return hi===lo ? 0 : Math.max(0, Math.min(1, (v-lo)/(hi-lo))); }}
  const contributions = {{
    'Avg Deal Score':  norm(c.avg_score, 0,   100) * W['Avg Deal Score']  * 100,
    'Best Deal Score': norm(c.best_score,0,   100) * W['Best Deal Score'] * 100,
    'Active Volume':   norm(c.active,    1,   10)  * W['Active Volume']   * 100,
    'Avg Cap Rate':    norm(c.avg_cap,   3,   9)   * W['Avg Cap Rate']    * 100,
    'Avg Price Drop':  norm(c.avg_drop,  0,   15)  * W['Avg Price Drop']  * 100,
    'Avg DOM':         norm(c.avg_dom,   30,  180) * W['Avg DOM']         * 100,
    'Avg CoCR':        norm(c.avg_coc,   0,   12)  * W['Avg CoCR']        * 100,
  }};
  const maxC = Math.max(...Object.values(contributions), 1);
  const factorBars = Object.entries(contributions)
    .sort((a,b) => b[1]-a[1])
    .map(([k,v]) => {{
      const w = (W[k]*100).toFixed(0);
      const pct = (v/maxC*100).toFixed(0);
      const rawVal = contributions[k];
      return `<div class="factor-bar-row">
        <span class="factor-bar-label">${{k}} <span style="color:var(--gold);font-size:9px">(${{w}}% weight)</span></span>
        <div class="factor-bar-track"><div class="factor-bar-fill" style="width:${{pct}}%"></div></div>
        <span class="factor-bar-right">${{rawVal.toFixed(1)}} pts</span>
      </div>`;
    }}).join('');

  return `<div class="city-row ${{rankClass}}" id="city-${{i}}">
    <div class="city-row-main" onclick="toggleCity(${{i}})">
      <div class="rank-num">#${{rank}}</div>
      <div class="city-info">
        <div class="city-name">${{c.city}} <span class="chevron">▼</span></div>
        <div class="city-pills">
          <span class="pill active">${{c.active}} active</span>
          ${{c.inactive ? `<span class="pill inactive">${{c.inactive}} inactive</span>` : ''}}
          ${{typeStr ? `<span class="pill">${{typeStr}}</span>` : ''}}
        </div>
      </div>
      <div class="city-score-col">
        <div class="city-opp-num" style="color:${{barColor}}">${{c.opportunity.toFixed(0)}}</div>
        <div class="city-opp-label">/ 100 · ${{gradeLabel}}</div>
      </div>
      <div class="city-metrics">
        <div class="opp-bar-track">
          <div class="opp-bar-fill" style="width:${{barW}}%;background:${{barColor}}"></div>
        </div>
        <div class="mini-stats">${{miniStats}}</div>
      </div>
    </div>
    <div class="city-detail">
      <div class="detail-verdict">${{buildVerdict(c, rank)}}</div>
      <div class="detail-grid">${{cardsHtml}}</div>
      <div class="factor-section-title">What drove this ranking</div>
      ${{factorBars}}
    </div>
  </div>`;
}}

function toggleCity(i) {{
  const row = document.getElementById('city-' + i);
  row.classList.toggle('open');
}}

document.getElementById('report-date').textContent =
  'Generated ' + new Date().toLocaleDateString('en-CA', {{year:'numeric',month:'long',day:'numeric'}})
  + ' · ' + CITIES.length + ' cit' + (CITIES.length===1?'y':'ies') + ' · '
  + CITIES.reduce((s,c)=>s+c.total,0) + ' properties';

document.getElementById('city-list').innerHTML = CITIES.map((c,i) => renderCity(c,i)).join('');
</script>
</body>
</html>"""

        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.html', delete=False,
            prefix='city_report_', encoding='utf-8'
        )
        tmp.write(html)
        tmp.close()
        webbrowser.open(f'file://{tmp.name}')
        print(f"\n  City report opened in browser.")
        print(f"  File saved to: {tmp.name}")

    def _open_report(self):
        props = self._store.load_properties()
        if not props:
            print("\n  No properties on file.")
            return

        # Build enriched dataset
        rows = []
        print("  Building report", end="", flush=True)
        for p in props:
            scored  = self._score_property(p)
            targets = self._solve_targets(p)
            print(".", end="", flush=True)
            rows.append({
                "address":      p.get("address", "—"),
                "mls":          p.get("mls_number", "—"),
                "status":       p.get("status", "—"),
                "city":         p.get("city") or "",
                "province":     p.get("province") or "",
                "type":         p.get("property_type") or "—",
                "asking":       p.get("asking_price", 0),
                "sqft":         p.get("total_sq_ft", 0),
                "listed":       p.get("listing_date", "—"),
                "analyzed":     p.get("analyzed_on") or "—",
                "notes":        p.get("notes") or "",
                "construction": p.get("construction_cost") or 0,
                "dist_km":      scored.get("dist_km"),
                "dist_centre":  scored.get("dist_centre") or "",
                "comm_rent":    p.get("commercial_rent") or 0,
                "res_rent":     p.get("residential_rent") or 0,
                "score":        scored.get("score"),
                "breakdown":    scored.get("breakdown", {}),
                "weights":      scored.get("weights", {}),
                "cap_rate":     scored.get("cap_rate", 0),
                "coc":          scored.get("coc", 0),
                "dscr":         scored.get("dscr", 0),
                "irr":          scored.get("irr", 0),
                "em":           scored.get("em", 0),
                "cf_annual":    scored.get("cf_annual", 0),
                "price_drop":   scored.get("price_drop", 0),
                "dom":          scored.get("dom", 0),
                "original":     p.get("original_price", 0),
                "taxes":        p.get("property_taxes", 0),
                "down_pct":     p.get("down_payment_pct", 0),
                "rate":         p.get("interest_rate", 0),
                "term":         p.get("term_years", 0),
                "hold":         p.get("hold_years", 0),
                "expense_ratio":p.get("expense_ratio", 0),
                "lease_type":   p.get("lease_type", ""),
                "results":      p.get("results", []),
                "targets":      targets,
                "hotel_rooms":  p.get("hotel_rooms", 0) or 0,
                "hotel_adr":    p.get("hotel_adr") or 0,
                "hotel_occ":    p.get("hotel_occupancy") or 0,
                "rent_breakdown": p.get("rent_breakdown", []),
            })

        print(" done.")
        data_json = json.dumps(rows, indent=2)

        # ── City rankings panel (only when called from _open_city_report) ────
        city_table_html = ""
        if hasattr(self, '_city_rankings') and self._city_rankings:
            cr = self._city_rankings
            self._city_rankings = None  # consume so normal _open_report calls are clean

            def _sc(v): return "good" if v and v>=70 else ("fair" if v and v>=45 else ("poor" if v else ""))
            def _cc(v): return "good" if v and v>=7  else ("fair" if v and v>=5  else ("poor" if v else ""))
            def _fm(n):
                if not n: return "&mdash;"
                if n>=1_000_000: return f"${n/1_000_000:.1f}M"
                if n>=1_000:     return f"${n/1_000:.0f}K"
                return f"${n:,.0f}"
            def _fp(n): return f"{n:.1f}%" if n else "&mdash;"

            rows_html = ""
            for i, c in enumerate(cr):
                bw  = min(100, int(c["opportunity"]))
                bc  = "#2d6a4f" if c["opportunity"]>=65 else ("#8b1a1a" if c["opportunity"]<35 else "#b8960c")
                sub = f'<span class="city-sub">{c["dist_km"]}km</span>' if c["dist_km"] is not None else ""
                inactive = c["total"] - c["active"]
                if inactive: sub += f'<span class="city-sub">({inactive} inactive)</span>'
                as_str = f'{c["avg_score"]:.0f}' if c["avg_score"] else "&mdash;"
                bs_str = f'{c["best_score"]:.0f}' if c["best_score"] else "&mdash;"
                dc   = "good" if c["avg_drop"] > 0 else ""
                domc = "good" if c["avg_dom"]>=90 else ("fair" if c["avg_dom"]>=60 else "")
                rows_html += (
                    f'<tr class="cr-row" data-city="{c["city"]}">'
                    f'<td style="text-align:left"><b style="color:var(--muted);font-family:var(--mono);font-size:11px">#{i+1}</b>'
                    f' <span class="cr-city">{c["city"]}</span>{sub}</td>'
                    f'<td><span style="font-family:var(--mono);font-size:13px;font-weight:500">{c["opportunity"]:.0f}</span>'
                    f'&nbsp;<span class="cr-bar-wrap"><span class="cr-bar" style="width:{bw}%;background:{bc}"></span></span></td>'
                    f'<td>{c["active"]}</td>'
                    f'<td class="{_sc(c["avg_score"])}">{as_str}</td>'
                    f'<td class="{_sc(c["best_score"])}">{bs_str}</td>'
                    f'<td class="{_cc(c["avg_cap"])}">{_fp(c["avg_cap"])}</td>'
                    f'<td class="{_cc(c["avg_coc"])}">{_fp(c["avg_coc"])}</td>'
                    f'<td class="{dc}">{_fp(c["avg_drop"])}</td>'
                    f'<td class="{domc}">{c["avg_dom"] or "&mdash;"}d</td>'
                    f'<td>{_fm(c["avg_price"])}</td>'
                    f'</tr>\n'
                )

            city_table_html = f"""<div id="city-panel">
  <div class="city-panel-header">
    <span style="font-family:'DM Serif Display',serif;font-size:1.3rem">City <em style="color:var(--gold)">Opportunity</em> Rankings</span>
    <span style="font-family:var(--mono);font-size:11px;color:var(--muted)">click a city to filter properties below</span>
    <button onclick="document.getElementById('city-panel').style.display='none'" style="background:none;border:none;cursor:pointer;color:var(--muted);font-size:1rem">&#x2715;</button>
  </div>
  <div style="overflow-x:auto;padding:0 1.5rem 1rem">
    <table class="cr-table">
      <thead><tr>
        <th style="text-align:left">City</th>
        <th>Score</th><th>Active</th><th>Avg Deal</th><th>Best Deal</th>
        <th>Avg Cap</th><th>CoCR</th><th>Price Drop</th><th>DOM</th><th>Avg Price</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
</div>"""

        cities    = sorted({r["city"] for r in rows if r["city"]})
        provinces = sorted({r["province"] for r in rows if r["province"]})
        types     = sorted({r["type"] for r in rows if r["type"] != "—"})

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Property Investment Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink:     #0f0f0f;
    --paper:   #f5f0e8;
    --cream:   #ede8dc;
    --rule:    #c8bfaa;
    --gold:    #b8960c;
    --green:   #2d6a4f;
    --red:     #8b1a1a;
    --amber:   #c17f24;
    --muted:   #6b6355;
    --col-w:   1200px;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--paper);
    color: var(--ink);
    font-family: 'DM Sans', sans-serif;
    font-size: 14px;
    line-height: 1.5;
    min-height: 100vh;
  }}

  /* ── Header ── */
  header {{
    border-bottom: 3px double var(--rule);
    padding: 2rem 2.5rem 1.5rem;
    background: var(--cream);
  }}
  header h1 {{
    font-family: 'DM Serif Display', serif;
    font-size: 2.6rem;
    letter-spacing: -0.02em;
    line-height: 1;
  }}
  header h1 em {{
    font-style: italic;
    color: var(--gold);
  }}
  .header-meta {{
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    color: var(--muted);
    margin-top: 0.4rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}

  /* ── Filter bar ── */
  .filters {{
    background: var(--cream);
    border-bottom: 1px solid var(--rule);
    padding: 1rem 2.5rem;
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    align-items: flex-end;
  }}
  .filter-group {{
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }}
  .filter-group label {{
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
  }}
  .filter-group select,
  .filter-group input {{
    background: var(--paper);
    border: 1px solid var(--rule);
    padding: 0.4rem 0.6rem;
    font-family: 'DM Sans', sans-serif;
    font-size: 13px;
    color: var(--ink);
    border-radius: 2px;
    min-width: 140px;
    appearance: none;
    -webkit-appearance: none;
  }}
  .filter-group select:focus,
  .filter-group input:focus {{
    outline: 2px solid var(--gold);
    outline-offset: -1px;
  }}
  .filter-group.range-group {{
    flex-direction: row;
    align-items: flex-end;
    gap: 0.4rem;
  }}
  .filter-group.range-group label {{ align-self: flex-start; }}
  .range-inputs {{ display: flex; gap: 0.4rem; align-items: center; }}
  .range-inputs span {{ color: var(--muted); font-size: 12px; }}
  .filter-group input[type=number] {{ min-width: 100px; }}
  .filter-actions {{
    display: flex;
    align-items: flex-end;
    gap: 0.5rem;
    margin-left: auto;
  }}
  button {{
    background: var(--ink);
    color: var(--paper);
    border: none;
    padding: 0.45rem 1.1rem;
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
    border-radius: 2px;
    transition: background 0.15s;
  }}
  button:hover {{ background: #333; }}
  button.ghost {{
    background: transparent;
    color: var(--muted);
    border: 1px solid var(--rule);
  }}
  button.ghost:hover {{ border-color: var(--ink); color: var(--ink); }}

  /* ── Summary strip ── */
  .summary-strip {{
    padding: 0.6rem 2.5rem;
    border-bottom: 1px solid var(--rule);
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    color: var(--muted);
    display: flex;
    justify-content: space-between;
    align-items: center;
    letter-spacing: 0.05em;
  }}
  .sort-controls {{
    display: flex;
    gap: 0.5rem;
    align-items: center;
  }}
  .sort-btn {{
    background: none;
    border: none;
    color: var(--muted);
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    cursor: pointer;
    padding: 0.2rem 0.5rem;
    border-radius: 2px;
    transition: all 0.1s;
  }}
  .sort-btn:hover {{ background: var(--cream); color: var(--ink); }}
  .sort-btn.active {{ background: var(--ink); color: var(--paper); }}

  /* ── Main grid ── */
  main {{ padding: 1.5rem 2.5rem 3rem; max-width: var(--col-w); }}
  #cards {{ display: flex; flex-direction: column; gap: 1.2rem; }}

  /* ── Property card ── */
  .card {{
    background: white;
    border: 1px solid var(--rule);
    border-left: 4px solid var(--rule);
    display: grid;
    grid-template-columns: 220px 1fr auto;
    transition: border-color 0.15s, box-shadow 0.15s;
  }}
  .card:hover {{
    border-color: var(--gold);
    box-shadow: 4px 4px 0 var(--gold);
  }}
  .card.score-excellent {{ border-left-color: var(--green); }}
  .card.score-good      {{ border-left-color: #4a9e72; }}
  .card.score-fair      {{ border-left-color: var(--amber); }}
  .card.score-poor      {{ border-left-color: var(--red); }}
  .card.score-none      {{ border-left-color: var(--rule); opacity: 0.75; }}

  /* Score panel */
  .card-score {{
    background: var(--cream);
    border-right: 1px solid var(--rule);
    padding: 1.2rem 1rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: 0.4rem;
  }}
  .score-num {{
    font-family: 'DM Serif Display', serif;
    font-size: 3rem;
    line-height: 1;
    color: var(--ink);
  }}
  .score-num.no-score {{
    font-size: 1.2rem;
    color: var(--muted);
    font-family: 'DM Mono', monospace;
  }}
  .score-label {{
    font-family: 'DM Mono', monospace;
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--muted);
  }}
  .score-grade {{
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 0.15rem 0.5rem;
    border-radius: 1px;
  }}
  .score-grade.excellent {{ background: #d4edda; color: var(--green); }}
  .score-grade.good      {{ background: #d9eedf; color: #2d6a4f; }}
  .score-grade.fair      {{ background: #fef3cd; color: var(--amber); }}
  .score-grade.poor      {{ background: #f8d7da; color: var(--red); }}
  .score-grade.none      {{ background: var(--cream); color: var(--muted); }}

  /* Card body */
  .card-body {{ padding: 1rem 1.2rem; }}
  .card-address {{
    font-family: 'DM Serif Display', serif;
    font-size: 1.1rem;
    margin-bottom: 0.2rem;
  }}
  .card-meta {{
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-bottom: 0.75rem;
    display: flex;
    gap: 0.8rem;
    flex-wrap: wrap;
  }}
  .card-meta .pill {{
    background: var(--cream);
    padding: 0.1rem 0.4rem;
    border-radius: 1px;
    border: 1px solid var(--rule);
  }}
  .metrics-row {{
    display: flex;
    gap: 1.2rem;
    flex-wrap: wrap;
    margin-top: 0.3rem;
  }}
  .metric-chip {{
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }}
  .metric-chip .m-label {{
    font-family: 'DM Mono', monospace;
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
  }}
  .metric-chip .m-value {{
    font-family: 'DM Mono', monospace;
    font-size: 13px;
    font-weight: 500;
  }}
  .metric-chip .m-value.good  {{ color: var(--green); }}
  .metric-chip .m-value.fair  {{ color: var(--amber); }}
  .metric-chip .m-value.poor  {{ color: var(--red); }}
  .metric-chip .m-value.info  {{ color: var(--ink); }}

  /* Card right panel */
  .card-right {{
    padding: 1rem 1.2rem;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    justify-content: space-between;
    min-width: 160px;
    border-left: 1px solid var(--rule);
  }}
  .asking-price {{
    font-family: 'DM Serif Display', serif;
    font-size: 1.4rem;
    text-align: right;
  }}
  .price-meta {{
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    color: var(--muted);
    text-align: right;
    margin-top: 0.15rem;
  }}
  .card-notes {{
    font-size: 11px;
    color: var(--muted);
    font-style: italic;
    max-width: 120px;
    text-align: right;
    line-height: 1.4;
    margin-top: 0.5rem;
  }}
  .status-badge {{
    font-family: 'DM Mono', monospace;
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    padding: 0.15rem 0.45rem;
    border-radius: 1px;
    margin-top: auto;
  }}
  .status-badge.active   {{ background: #d4edda; color: var(--green); }}
  .status-badge.inactive {{ background: #f8d7da; color: var(--red); }}
  .status-badge.sold     {{ background: var(--cream); color: var(--muted); }}

  .no-results {{
    text-align: center;
    padding: 4rem;
    color: var(--muted);
    font-family: 'DM Serif Display', serif;
    font-style: italic;
    font-size: 1.3rem;
  }}

  /* ── Modal ── */
  .modal-overlay {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(15,15,15,0.65);
    z-index: 1000;
    overflow-y: auto;
    padding: 2rem 1rem;
  }}
  .modal-overlay.open {{ display: flex; justify-content: center; align-items: flex-start; }}
  .modal {{
    background: var(--paper);
    border: 1px solid var(--rule);
    max-width: 900px;
    width: 100%;
    position: relative;
    animation: modalIn 0.18s ease;
  }}
  @keyframes modalIn {{
    from {{ opacity: 0; transform: translateY(12px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
  }}
  .modal-close {{
    position: absolute;
    top: 1rem; right: 1rem;
    background: none; border: none;
    font-size: 1.4rem; cursor: pointer;
    color: var(--muted); line-height: 1;
    padding: 0.2rem 0.4rem;
  }}
  .modal-close:hover {{ color: var(--ink); }}
  .modal-photo {{
    width: 100%; height: 420px;
    object-fit: cover;
    display: block;
    background: var(--cream);
  }}
  .modal-map-frame {{
    width: 100%;
    height: 420px;
    border: none;
    display: block;
    box-sizing: border-box;
    background: var(--cream);
  }}
  #modal-content {{
    display: block;
    width: 100%;
    box-sizing: border-box;
  }}
  .modal-map-bar {{
    background: var(--cream);
    border-bottom: 1px solid var(--rule);
    padding: 0.35rem 1rem;
    display: flex; justify-content: space-between; align-items: center;
    font-family: 'DM Mono', monospace; font-size: 10px; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.07em;
  }}
  .modal-map-bar a {{
    color: var(--gold); text-decoration: none; font-weight: 500;
  }}
  .modal-map-bar a:hover {{ text-decoration: underline; }}
  .modal-photo-fallback {{
    width: 100%; height: 420px;
    background: var(--cream);
    display: flex; align-items: center; justify-content: center;
    font-family: 'DM Mono', monospace;
    font-size: 11px; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.1em;
  }}
  .modal-body {{ padding: 1.5rem 2rem 2rem; }}
  .modal-header {{ margin-bottom: 1.2rem; }}
  .modal-address {{
    font-family: 'DM Serif Display', serif;
    font-size: 1.6rem; line-height: 1.1;
  }}
  .modal-sub {{
    font-family: 'DM Mono', monospace; font-size: 11px;
    color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.07em; margin-top: 0.35rem;
    display: flex; gap: 1rem; flex-wrap: wrap;
  }}
  .modal-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem;
    margin-top: 1.2rem;
  }}
  .modal-section h3 {{
    font-family: 'DM Mono', monospace;
    font-size: 10px; text-transform: uppercase;
    letter-spacing: 0.12em; color: var(--muted);
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.3rem; margin-bottom: 0.6rem;
  }}
  .modal-metric-row {{
    display: flex; justify-content: space-between;
    align-items: baseline;
    padding: 0.2rem 0;
    border-bottom: 1px dotted var(--cream);
    font-size: 13px;
  }}
  .modal-metric-row:last-child {{ border-bottom: none; }}
  .modal-metric-name {{ color: var(--muted); font-size: 12px; }}
  .modal-metric-val  {{ font-family: 'DM Mono', monospace; font-weight: 500; }}
  .modal-metric-val.good  {{ color: var(--green); }}
  .modal-metric-val.fair  {{ color: var(--amber); }}
  .modal-metric-val.poor  {{ color: var(--red); }}
  .modal-metric-val.info  {{ color: var(--ink); }}
  .score-bar-row {{
    display: flex; align-items: center; gap: 0.6rem;
    padding: 0.25rem 0; font-size: 12px;
  }}
  .score-bar-label {{ width: 120px; color: var(--muted); flex-shrink: 0; font-size: 11px; }}
  .score-bar-track {{
    flex: 1; height: 6px; background: var(--cream);
    border-radius: 0; overflow: hidden; border: 1px solid var(--rule);
  }}
  .score-bar-fill {{
    height: 100%; background: var(--gold);
    transition: width 0.3s ease;
  }}
  .score-bar-num {{
    font-family: 'DM Mono', monospace; font-size: 11px;
    color: var(--muted); width: 28px; text-align: right; flex-shrink: 0;
  }}
  .modal-notes {{
    margin-top: 1rem; padding: 0.8rem 1rem;
    background: var(--cream); border-left: 3px solid var(--gold);
    font-style: italic; font-size: 13px; color: var(--ink); line-height: 1.5;
  }}
  .card {{ cursor: pointer; }}
  #city-panel {{ background:var(--cream); border-bottom:3px double var(--rule); }}
  .city-panel-header {{ padding:0.8rem 1.5rem; display:flex; align-items:center; gap:1.5rem; }}
  .cr-table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  .cr-table th {{ font-family:var(--mono); font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); padding:0.4rem 0.7rem; text-align:right; border-bottom:2px solid var(--rule); white-space:nowrap; }}
  .cr-table td {{ padding:0.4rem 0.7rem; border-bottom:1px solid var(--rule); text-align:right; vertical-align:middle; }}
  .cr-row {{ cursor:pointer; }}
  .cr-row:hover td {{ background:#faf0d0; }}
  .cr-row.active td {{ background:#fdf5d0; }}
  .cr-city {{ font-family:'DM Serif Display',serif; font-size:1rem; }}
  .city-sub {{ font-family:var(--mono); font-size:10px; color:var(--muted); margin-left:0.5rem; }}
  .cr-bar-wrap {{ display:inline-block; width:50px; height:5px; background:var(--paper); border:1px solid var(--rule); vertical-align:middle; }}
  .cr-bar {{ display:block; height:100%; }}
</style>
</head>
<body>

{city_table_html}

<div class="modal-overlay" id="modal-overlay" onclick="handleOverlayClick(event)">
  <div class="modal" id="modal">
    <button class="modal-close" onclick="closeModal()">✕</button>
    <div id="modal-content"></div>
  </div>
</div>

<header>
  <h1>Property <em>Investment</em> Report</h1>
  <div class="header-meta" id="report-date"></div>
</header>

<div class="filters">
  <div class="filter-group">
    <label>Province</label>
    <select id="f-province">
      <option value="">All Provinces</option>
      {''.join(f'<option value="{p}">{p}</option>' for p in provinces)}
    </select>
  </div>
  <div class="filter-group">
    <label>City</label>
    <select id="f-city">
      <option value="">All Cities</option>
      {''.join(f'<option value="{c}">{c}</option>' for c in cities)}
    </select>
  </div>
  <div class="filter-group">
    <label>Property Type</label>
    <select id="f-type">
      <option value="">All Types</option>
      {''.join(f'<option value="{t}">{t}</option>' for t in types)}
    </select>
  </div>
  <div class="filter-group">
    <label>Status</label>
    <select id="f-status">
      <option value="">All Statuses</option>
      <option value="active">Active</option>
      <option value="inactive">Inactive</option>
    </select>
  </div>
  <div class="filter-group range-group">
    <label>Price Range</label>
    <div class="range-inputs">
      <input type="number" id="f-price-min" placeholder="Min $" step="50000">
      <span>–</span>
      <input type="number" id="f-price-max" placeholder="Max $" step="50000">
    </div>
  </div>
  <div class="filter-group">
    <label>Analysis</label>
    <select id="f-analysis">
      <option value="">All Properties</option>
      <option value="scored">Scored Only</option>
      <option value="partial">Partial Only</option>
    </select>
  </div>
  <div class="filter-actions">
    <button onclick="applyFilters()">Apply</button>
    <button class="ghost" onclick="resetFilters()">Reset</button>
  </div>
</div>

<div class="summary-strip">
  <span id="result-count"></span>
  <div class="sort-controls">
    <span style="margin-right:0.3rem">Sort:</span>
    <button class="sort-btn active" data-sort="score" onclick="setSort('score')">Score ↓</button>
    <button class="sort-btn" data-sort="cap_rate" onclick="setSort('cap_rate')">Cap Rate</button>
    <button class="sort-btn" data-sort="coc" onclick="setSort('coc')">CoCR</button>
    <button class="sort-btn" data-sort="irr" onclick="setSort('irr')">IRR</button>
    <button class="sort-btn" data-sort="cf_annual" onclick="setSort('cf_annual')">Cash Flow</button>
    <button class="sort-btn" data-sort="asking" onclick="setSort('asking')">Price ↑</button>
    <button class="sort-btn" data-sort="dom" onclick="setSort('dom')">Days Listed</button>
  </div>
</div>

<main>
  <div id="cards"></div>
</main>

<script>
const DATA = {data_json};

let currentSort = 'score';
let sortAsc = false;
let filteredData = [...DATA];
let SORTED_CACHE  = [...DATA];

function fmt(n, decimals=2, prefix='') {{
  if (n === null || n === undefined || isNaN(n)) return '—';
  return prefix + n.toLocaleString('en-CA', {{minimumFractionDigits: decimals, maximumFractionDigits: decimals}});
}}
function fmtMoney(n) {{
  if (!n && n !== 0) return '—';
  if (n >= 1e6) return '$' + (n/1e6).toFixed(2) + 'M';
  if (n >= 1e3) return '$' + (n/1e3).toFixed(0) + 'K';
  return '$' + n.toLocaleString('en-CA');
}}
function scoreGradeLabel(s) {{
  if (s === null || s === undefined) return ['none', 'No Analysis'];
  if (s >= 75) return ['excellent', 'Excellent'];
  if (s >= 55) return ['good', 'Good'];
  if (s >= 35) return ['fair', 'Fair'];
  return ['poor', 'Weak'];
}}
function metricClass(metric, value) {{
  if (value === null || value === undefined) return 'info';
  if (metric === 'cap_rate') return value >= 7.5 ? 'good' : value >= 5.5 ? 'fair' : 'poor';
  if (metric === 'coc')      return value >= 10  ? 'good' : value >= 5   ? 'fair' : 'poor';
  if (metric === 'dscr')     return value >= 1.5 ? 'good' : value >= 1.25? 'fair' : 'poor';
  if (metric === 'irr')      return value >= 15  ? 'good' : value >= 10  ? 'fair' : 'poor';
  if (metric === 'em')       return value >= 2.0 ? 'good' : value >= 1.5 ? 'fair' : 'poor';
  if (metric === 'cf_annual')return value > 0    ? (value >= 10000 ? 'good' : 'fair') : 'poor';
  return 'info';
}}

function renderCard(p) {{
  const [gradeClass, gradeLabel] = scoreGradeLabel(p.score);
  const scoreCardClass = p.score !== null ? `score-${{gradeClass}}` : 'score-none';
  const hasIncome = p.score !== null;

  const scoreDisplay = p.score !== null
    ? `<div class="score-num">${{p.score.toFixed(0)}}</div>`
    : `<div class="score-num no-score">No<br>Analysis</div>`;

  const metricsHtml = hasIncome ? `
    <div class="metrics-row">
      <div class="metric-chip">
        <span class="m-label">Cap Rate</span>
        <span class="m-value ${{metricClass('cap_rate', p.cap_rate)}}">${{fmt(p.cap_rate)}}%</span>
      </div>
      <div class="metric-chip">
        <span class="m-label">CoCR</span>
        <span class="m-value ${{metricClass('coc', p.coc)}}">${{fmt(p.coc)}}%</span>
      </div>
      <div class="metric-chip">
        <span class="m-label">DSCR</span>
        <span class="m-value ${{metricClass('dscr', p.dscr)}}">${{fmt(p.dscr)}}</span>
      </div>
      <div class="metric-chip">
        <span class="m-label">IRR</span>
        <span class="m-value ${{metricClass('irr', p.irr)}}">${{fmt(p.irr)}}%</span>
      </div>
      <div class="metric-chip">
        <span class="m-label">Equity ×</span>
        <span class="m-value ${{metricClass('em', p.em)}}">${{fmt(p.em)}}x</span>
      </div>
      <div class="metric-chip">
        <span class="m-label">Annual CF</span>
        <span class="m-value ${{metricClass('cf_annual', p.cf_annual)}}">${{fmtMoney(p.cf_annual)}}</span>
      </div>
      ${{p.price_drop > 0 ? `<div class="metric-chip">
        <span class="m-label">Price Drop</span>
        <span class="m-value good">${{fmt(p.price_drop)}}%</span>
      </div>` : ''}}
    </div>` : `<div style="color:#6b6355;font-style:italic;font-size:12px;margin-top:0.5rem">Partial analysis only — income metrics unavailable</div>`;

  const statusClass = (p.status || '').toLowerCase();
  const ppSqft = p.sqft > 0 ? (p.asking / p.sqft) : null;

  const idx = SORTED_CACHE.indexOf(p);
  return `<div class="card ${{scoreCardClass}}" data-idx="${{idx}}" title="Click for full report">
    <div class="card-score">
      ${{scoreDisplay}}
      <div class="score-label">Investment Score</div>
      <div class="score-grade ${{gradeClass}}">${{gradeLabel}}</div>
    </div>
    <div class="card-body">
      <div class="card-address">${{p.address}}</div>
      <div class="card-meta">
        <span class="pill">${{p.type}}</span>
        <span>${{p.mls}}</span>
        <span>${{p.sqft > 0 ? p.sqft.toLocaleString() + ' sq ft' : ''}}</span>
        ${{ppSqft ? `<span>${{fmt(ppSqft, 0, '$')}}/sq ft</span>` : ''}}
      ${{p.construction > 0 ? `<span class=\"pill\" style=\"color:#b8960c\">+${{fmtMoney(p.construction)}} reno</span>` : ''}}
      ${{p.dist_km !== null && p.dist_km !== undefined ? `<span class=\"pill\">${{p.dist_km}}km to ${{p.dist_centre || 'centre'}}</span>` : ''}}
        <span>${{p.dom > 0 ? p.dom + ' days listed' : ''}}</span>
      </div>
      ${{metricsHtml}}
    </div>
    <div class="card-right">
      <div>
        <div class="asking-price">${{fmtMoney(p.asking)}}</div>
        <div class="price-meta">${{p.city}}${{p.province ? ', ' + p.province : ''}}</div>
        ${{p.price_drop > 0 ? `<div class="price-meta" style="color:#2d6a4f">▼ ${{fmt(p.price_drop)}}% from list</div>` : ''}}
      </div>
      ${{p.notes ? `<div class="card-notes">${{p.notes.slice(0, 80)}}${{p.notes.length > 80 ? '…' : ''}}</div>` : ''}}
      <div class="status-badge ${{statusClass}}">${{p.status}}</div>
    </div>
  </div>`;
}}

function applyFilters() {{
  const province = document.getElementById('f-province').value;
  const city     = document.getElementById('f-city').value;
  const type     = document.getElementById('f-type').value;
  const status   = document.getElementById('f-status').value;
  const priceMin = parseFloat(document.getElementById('f-price-min').value) || 0;
  const priceMax = parseFloat(document.getElementById('f-price-max').value) || Infinity;
  const analysis = document.getElementById('f-analysis').value;

  filteredData = DATA.filter(p => {{
    if (province && p.province !== province) return false;
    if (city     && p.city     !== city)     return false;
    if (type     && p.type     !== type)     return false;
    if (status   && p.status   !== status)   return false;
    if (p.asking < priceMin || p.asking > priceMax) return false;
    if (analysis === 'scored'  && p.score === null)    return false;
    if (analysis === 'partial' && p.score !== null)    return false;
    return true;
  }});

  renderAll();
}}

function resetFilters() {{
  ['f-province','f-city','f-type','f-status','f-analysis'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('f-price-min').value = '';
  document.getElementById('f-price-max').value = '';
  filteredData = [...DATA];
  renderAll();
}}

function setSort(field) {{
  if (currentSort === field) {{
    sortAsc = !sortAsc;
  }} else {{
    currentSort = field;
    sortAsc = field === 'asking';
  }}
  document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
  document.querySelector(`[data-sort="${{field}}"]`).classList.add('active');
  renderAll();
}}

function renderAll() {{
  const sorted = [...filteredData].sort((a, b) => {{
    let va = a[currentSort], vb = b[currentSort];
    if (va === null || va === undefined) va = sortAsc ? Infinity : -Infinity;
    if (vb === null || vb === undefined) vb = sortAsc ? Infinity : -Infinity;
    return sortAsc ? va - vb : vb - va;
  }});

  const container = document.getElementById('cards');
  if (sorted.length === 0) {{
    container.innerHTML = '<div class="no-results">No properties match the current filters</div>';
  }} else {{
    SORTED_CACHE = sorted;
    container.innerHTML = sorted.map(renderCard).join('');
  }}
  document.getElementById('result-count').textContent =
    `${{sorted.length}} of ${{DATA.length}} properties`;
}}

// Event delegation — card clicks
document.getElementById('cards').addEventListener('click', function(e) {{
  const card = e.target.closest('.card[data-idx]');
  if (!card) return;
  const idx = parseInt(card.getAttribute('data-idx'), 10);
  if (!isNaN(idx) && SORTED_CACHE[idx]) openModal(SORTED_CACHE[idx]);
}});

// City panel click-to-filter
document.querySelectorAll('.cr-row').forEach(function(row) {{
  row.addEventListener('click', function() {{
    var city = this.getAttribute('data-city');
    document.querySelectorAll('.cr-row').forEach(function(r) {{ r.classList.remove('active'); }});
    this.classList.add('active');
    var sel = document.getElementById('f-city');
    if (sel) {{
      sel.value = city;
      applyFilters();
      document.querySelector('.filters').scrollIntoView({{behavior:'smooth'}});
    }}
  }});
}});

// Init
document.getElementById('report-date').textContent =
  'Generated ' + new Date().toLocaleDateString('en-CA', {{year:'numeric',month:'long',day:'numeric'}});
renderAll();

// ── Modal ──────────────────────────────────────────────────────────────────
function gradeClass(metric, value) {{
  return metricClass(metric, value);
}}

function gradeFromLabel(label) {{
  const l = (label || '').toLowerCase();
  if (l.includes('good') || l.includes('excellent') || l.includes('pass') || l.includes('celoc')) return 'good';
  if (l.includes('fair') || l.includes('friction')) return 'fair';
  if (l.includes('poor') || l.includes('bleed') || l.includes('fail') || l.includes('risk') || l.includes('no celoc')) return 'poor';
  return 'info';
}}

function openModal(p) {{
  const addrEnc       = encodeURIComponent(p.address);
  const mapEmbedUrl   = `https://www.google.com/maps?q=${{addrEnc}}&layer=c&output=svembed`;
  const mapsSearchUrl = `https://www.google.com/maps/search/?api=1&query=${{addrEnc}}`;

  // Group results by section
  const SECTIONS = [
    {{ label: "Mortgage & Financing", keys: ["Loan Amount","Down Payment","Construction Cost","Total Cash In","Monthly Payment","Annual Debt Svc"] }},
    {{ label: "Pricing",              keys: ["Price/Sq Ft","GRM","Tax Load","Price Drop %","Loan to Value"] }},
    {{ label: "Income",               keys: ["Annual Rent","Expense Ratio","NOI","Cap Rate","Op Expense Ratio","Entry Cap Rate"] }},
    {{ label: "Exit",                 keys: ["Exit Cap Rate","Exit Cap Ratio","Exit Price"] }},
    {{ label: "Cash Flow",            keys: ["Annual Cash Flow","Monthly Cash Flow","CoCR"] }},
    {{ label: "Debt",                 keys: ["DSCR","Break-Even NOI","Break-Even NOI %","Break-Even Occupancy %","Stress Test (+2%)"] }},
    {{ label: "Returns",              keys: ["IRR (5-Yr)","Equity Multiple"] }},
    {{ label: "Market",               keys: ["CELOC Speed Score","Market Staleness","Seller Bleed"] }},
    {{ label: "Hotel Operations",     keys: ["Hotel Rooms","ADR","Occupancy Rate","RevPAR","NRevPAR","Rev/Room/Yr","GOP Margin","GOP Amount","CPOR","FF&E Reserve"] }},
  ];

  const resultMap = {{}};
  (p.results || []).forEach(r => {{ resultMap[r.metric] = r; }});

  const rentLines = (p.rent_breakdown || []).filter(l => l && !l.startsWith('  ⚠'));

  const [gradeClass_, gradeLabel_] = scoreGradeLabel(p.score);
  const ppSqft = p.sqft > 0 ? (p.asking / p.sqft) : null;

  // Build sections HTML
  const sectionsHtml = SECTIONS.map(sec => {{
    const rows = sec.keys
      .filter(k => resultMap[k])
      .map(k => {{
        const r = resultMap[k];
        const gc = gradeFromLabel(r.grade);
        return `<div class="modal-metric-row">
          <span class="modal-metric-name">${{r.metric}}</span>
          <span class="modal-metric-val ${{gc}}">${{r.value}}</span>
        </div>`;
      }}).join('');
    if (!rows) return '';
    return `<div class="modal-section">
      <h3>${{sec.label}}</h3>
      ${{rows}}
    </div>`;
  }}).filter(Boolean).join('');

  // Score breakdown bars
  const breakdown = p.breakdown || {{}};
  const weights   = p.weights   || {{}};
  const barsHtml  = Object.entries(breakdown)
    .filter(([k]) => (weights[k] || 0) > 0)
    .sort((a,b) => b[1] - a[1])
    .map(([k, v]) => {{
      const pct = Math.min(100, v);
      const w   = ((weights[k] || 0) * 100).toFixed(0);
      return `<div class="score-bar-row">
        <span class="score-bar-label">${{k}} <span style="color:#b8960c">(${{w}}%)</span></span>
        <div class="score-bar-track"><div class="score-bar-fill" style="width:${{pct}}%"></div></div>
        <span class="score-bar-num">${{v.toFixed(0)}}</span>
      </div>`;
    }}).join('');

  const notesHtml = p.notes
    ? `<div class="modal-notes">${{p.notes}}</div>` : '';

  const rentHtml = rentLines.length
    ? `<div class="modal-section" style="margin-top:1rem"><h3>Rent Detail</h3>
        ${{rentLines.map(l => `<div class="modal-metric-row"><span class="modal-metric-name" style="color:var(--ink)">${{l}}</span></div>`).join('')}}
      </div>` : '';

  const propDetails = `
    <div class="modal-metric-row"><span class="modal-metric-name">MLS #</span><span class="modal-metric-val info">${{p.mls}}</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Type</span><span class="modal-metric-val info">${{p.type}}</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Total Sq Ft</span><span class="modal-metric-val info">${{p.sqft.toLocaleString()}}</span></div>
    ${{ppSqft ? `<div class="modal-metric-row"><span class="modal-metric-name">Price / Sq Ft</span><span class="modal-metric-val info">${{fmt(ppSqft, 0, '$')}}</span></div>` : ''}}
    <div class="modal-metric-row"><span class="modal-metric-name">Asking Price</span><span class="modal-metric-val info">${{fmtMoney(p.asking)}}</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Original Price</span><span class="modal-metric-val info">${{fmtMoney(p.original)}}</span></div>
    ${{p.construction > 0 ? `<div class="modal-metric-row"><span class="modal-metric-name">Construction</span><span class="modal-metric-val info">+${{fmtMoney(p.construction)}}</span></div>` : ''}}
    <div class="modal-metric-row"><span class="modal-metric-name">Property Taxes</span><span class="modal-metric-val info">${{fmtMoney(p.taxes)}}/yr</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Down Payment</span><span class="modal-metric-val info">${{(p.down_pct*100).toFixed(0)}}%</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Interest Rate</span><span class="modal-metric-val info">${{(p.rate*100).toFixed(2)}}%</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Term / Hold</span><span class="modal-metric-val info">${{p.term}} yr / ${{p.hold}} yr</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Expense Ratio</span><span class="modal-metric-val info">${{(p.expense_ratio*100).toFixed(0)}}%</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Lease Type</span><span class="modal-metric-val info">${{p.lease_type}}</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Listed</span><span class="modal-metric-val info">${{p.listed}}</span></div>
    ${{p.dist_km != null ? `<div class="modal-metric-row"><span class="modal-metric-name">Distance</span><span class="modal-metric-val info">${{p.dist_km}}km to ${{p.dist_centre}}</span></div>` : ''}}
  `;

  // ── What would make this score 100? ──
  const targets = p.targets || {{}};
  const hasTargets = Object.keys(targets).length > 0;
  const TARGET_LABELS = {{
    price:    {{ label: "Asking Price",  fmt: v => fmtMoney(v),            note: "negotiate down to" }},
    rent:     {{ label: "Annual Rent",   fmt: v => fmtMoney(v) + "/yr",    note: "needs to reach"    }},
    rate:     {{ label: "Interest Rate", fmt: v => (v*100).toFixed(2)+"%", note: "refinance below"   }},
    down_pct: {{ label: "Down Payment",  fmt: v => (v*100).toFixed(0)+"%", note: "increase to"       }},
  }};
  const targetRows = Object.entries(targets).map(([k, v]) => {{
    const def_ = TARGET_LABELS[k] || {{ label: k, fmt: x => x, note: "target" }};
    return `<div class="modal-metric-row">
      <span class="modal-metric-name">${{def_.label}} <span style="color:var(--muted);font-size:10px">(${{def_.note}})</span></span>
      <span class="modal-metric-val good">${{def_.fmt(v)}}</span>
    </div>`;
  }}).join('');
  const targetsHtml = hasTargets
    ? `<div style="margin-top:1.5rem"><div class="modal-section">
        <h3 style="color:var(--gold)">What would make this a 100/100?</h3>
        <div style="font-size:11px;color:var(--muted);margin-bottom:0.6rem;font-style:italic">
          Each lever shown independently — changing one alone would achieve a perfect score.
        </div>
        ${{targetRows}}
      </div></div>`
    : (p.score !== null && p.score >= 99
        ? `<div style="margin-top:1rem;padding:0.8rem 1rem;background:#d4edda;border-left:3px solid var(--green);font-family:'DM Mono',monospace;font-size:12px;color:var(--green)">
            Already scores 100/100 — this is an exceptional investment.</div>`
        : '');

  document.getElementById('modal-content').innerHTML = `
    <div id="modal-img-wrap">
      <iframe class="modal-map-frame"
              src="${{mapEmbedUrl}}"
              loading="lazy"
              referrerpolicy="no-referrer-when-downgrade"
              allowfullscreen>
      </iframe>
      <div class="modal-map-bar">
        <span>${{p.address}}</span>
        <a href="${{mapsSearchUrl}}" target="_blank" rel="noopener">Open in Google Maps ↗</a>
      </div>
    </div>
    <div class="modal-body">
      <div class="modal-header">
        <div class="modal-address">${{p.address}}</div>
        <div class="modal-sub">
          <span>${{p.city}}${{p.province ? ', ' + p.province : ''}}</span>
          <span>${{p.type}}</span>
          <span style="color:${{p.status==='active'?'#2d6a4f':'#8b1a1a'}}">${{p.status}}</span>
          ${{p.score !== null ? `<span style="color:var(--gold);font-weight:500">Score: ${{p.score.toFixed(0)}}/100 — ${{scoreGradeLabel(p.score)[1]}}</span>` : ''}}
        </div>
      </div>
      ${{notesHtml}}
      <div class="modal-grid">
        <div>
          <div class="modal-section">
            <h3>Property Details</h3>
            ${{propDetails}}
          </div>
          ${{rentHtml}}
        </div>
        <div>
          ${{sectionsHtml}}
        </div>
      </div>
      ${{barsHtml ? `<div style="margin-top:1.5rem"><div class="modal-section"><h3>Score Breakdown</h3>${{barsHtml}}</div></div>` : ''}}
      ${{targetsHtml}}
    </div>
  `;

  document.getElementById('modal-overlay').classList.add('open');
  document.body.style.overflow = 'hidden';
}}

function closeModal() {{
  document.getElementById('modal-overlay').classList.remove('open');
  document.body.style.overflow = '';
}}

function handleOverlayClick(e) {{
  if (e.target === document.getElementById('modal-overlay')) closeModal();
}}

document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeModal(); }});
</script>

</body>
</html>"""

        # Write to temp file and open in browser
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.html', delete=False,
            prefix='property_report_', encoding='utf-8'
        )
        tmp.write(html)
        tmp.close()
        webbrowser.open(f'file://{tmp.name}')
        print(f"\n  Report opened in browser.")
        print(f"  File saved to: {tmp.name}")

    def _import_csv(self):
        """
        Import multiple properties from a CSV file.

        Expected columns (order does not matter, matched by header name):
          address, mls_number, status, original_price, property_type,
          commercial_rent, floors, total_sq_ft,
          bachelor, one_br, two_br, three_br, four_br, unknown,
          residential_rent, property_taxes, down_payment_pct,
          interest_rate, term_years, hold_years, expense_ratio, lease_type

        Percentages (down_payment_pct, interest_rate, expense_ratio) accept
        either 20 or 0.20 format.
        Empty cells use the same defaults as manual entry.
        """
        print(f"\n  CSV IMPORT")
        print(self.THIN_DIVIDER)
        print("  Enter path to CSV file, or 'template' to save a sample CSV:")
        path = input("  > ").strip()

        if path.lower() == "template":
            self._save_csv_template()
            return

        if not path:
            print("  Cancelled.")
            return

        if not os.path.exists(path):
            print(f"  File not found: {path}")
            return

        # Read rows — try common encodings in order.
        # OpenOffice uses utf-8 (no BOM) or system locale (often latin-1/iso-8859-1).
        # Excel uses utf-8-sig (UTF-8 with BOM) or cp1252.
        # latin-1 is a superset that accepts any single byte, so it is the final fallback.
        rows = None
        enc  = None
        tried = []
        for enc in ("utf-8", "utf-8-sig", "cp1252", "iso-8859-1", "latin-1"):
            tried.append(enc)
            try:
                with open(path, newline="", encoding=enc) as f:
                    reader = _csv.DictReader(f)
                    rows = list(reader)
                break
            except UnicodeDecodeError:
                continue
            except Exception as e:
                print(f"  Could not read file: {e}")
                return
        if rows is None:
            print(f"  Could not decode file (tried: {', '.join(tried)}).")
            print("  In OpenOffice: File > Save As > CSV, set encoding to UTF-8.")
            return

        if not rows:
            print("  File is empty.")
            return

        # If the first row looks like data (not headers), inject the expected header.
        # Detection: "address" column header is present → already has headers.
        # The expected column order matches the property creation flow.
        EXPECTED_HEADERS = [
            "address", "mls_number", "status", "original_price", "property_type",
            "commercial_rent", "floors", "total_sq_ft",
            "bachelor", "one_br", "two_br", "three_br", "four_br", "unknown",
            "residential_rent", "property_taxes", "down_payment_pct",
            "interest_rate", "term_years", "hold_years", "expense_ratio", "lease_type",
            "hotel_rooms", "hotel_adr", "hotel_occupancy",
            "ind_warehouse_sqft", "ind_office_sqft", "ind_yard_sqft",
            "ind_dock_doors", "ind_drive_in_doors", "ind_clear_height_ft",
            "ind_office_rate", "ind_yard_rate"
        ]
        first_keys = [k.strip().lower() for k in rows[0].keys()]
        has_header = "address" in first_keys
        if not has_header:
            # Re-read as plain rows and zip with expected headers
            with open(path, newline="", encoding=enc) as f:
                plain_rows = list(_csv.reader(f))
            # Pad or trim each row to match header length
            rows = []
            for r in plain_rows:
                padded = r + [""] * (len(EXPECTED_HEADERS) - len(r))
                rows.append(dict(zip(EXPECTED_HEADERS, padded[:len(EXPECTED_HEADERS)])))
            print(f"  No header row detected — using default column order ({len(rows)} rows).")

        def cell(row, key, default=None):
            val = row.get(key, "").strip()
            return val if val else default

        def to_int(row, key, default=0):
            try:
                return int(float(cell(row, key, default)))
            except (TypeError, ValueError):
                return default

        def to_float(row, key, default=None):
            try:
                v = cell(row, key)
                return float(v) if v else default
            except ValueError:
                return default

        def to_pct(row, key, default_pct):
            v = to_float(row, key)
            if v is None:
                return default_pct / 100
            return v / 100 if v > 1 else v

        PROVINCES = {"AB","BC","MB","NB","NL","NS","NT","NU","ON","PE","QC","SK","YT"}

        def parse_city_province(addr):
            if not addr:
                return None, None
            # Normalise: some addresses use ". City" instead of ", City"
            # Replace the LAST period-space that precedes what looks like a city
            # (i.e. not part of an abbreviation like "St.") with a comma
            normalised = addr
            # Try comma split first
            parts = [p.strip() for p in normalised.split(",")]
            last = parts[-1].strip()
            if last.upper() in PROVINCES:
                # "..., City, ON"
                return (parts[-2].strip() if len(parts) >= 2 else None), last.upper()
            tokens = last.split()
            if tokens and tokens[-1].upper() in PROVINCES:
                # "..., City ON"
                province = tokens[-1].upper()
                city = " ".join(tokens[:-1]).strip() or None
                return city, province
            # No comma-based city found — try splitting on the last ". " sequence
            # e.g. "177 Queen St. Port Perry"
            dot_idx = addr.rfind(". ")
            if dot_idx != -1:
                candidate = addr[dot_idx + 2:].strip()
                if candidate:
                    c_tokens = candidate.split()
                    if c_tokens and c_tokens[-1].upper() in PROVINCES:
                        province = c_tokens[-1].upper()
                        city = " ".join(c_tokens[:-1]).strip() or None
                        return city, province
                    return candidate, None
            # No province found — treat the last comma segment as the city
            city = last if last else None
            return city, None

        COMMERCIAL_TYPES = {"office", "retail", "industrial", "mixed-use", "retail-office"}

        saved = 0
        errors = []

        for row_num, row in enumerate(rows, start=2):  # start=2 because row 1 is header
            try:
                address = cell(row, "address", "")
                if not address:
                    errors.append(f"  Row {row_num}: missing address — skipped")
                    continue

                mls = cell(row, "mls_number", "")
                if not mls:
                    errors.append(f"  Row {row_num} ({address}): missing MLS # — skipped")
                    continue

                status_raw = cell(row, "status", "active").lower()
                status = {"a": "active", "i": "inactive"}.get(status_raw, status_raw)
                if status not in ("active", "inactive"):
                    status = "active"

                original_price = to_float(row, "original_price")
                if original_price is None:
                    errors.append(f"  Row {row_num} ({address}): missing original_price — skipped")
                    continue

                property_type_raw = cell(row, "property_type", "")
                is_commercial = property_type_raw.strip().lower() in COMMERCIAL_TYPES
                prop_type_field = property_type_raw if is_commercial else None

                city, province = parse_city_province(address)
                # Default to ON when province can't be parsed from address
                if province is None:
                    province = "ON"

                commercial_rent = to_float(row, "commercial_rent")
                floors          = to_int(row, "floors", 1)
                total_sq_ft     = to_float(row, "total_sq_ft")
                if not total_sq_ft:   # None or 0
                    errors.append(f"  Row {row_num} ({address}): missing total_sq_ft — skipped")
                    continue

                bachelor = to_int(row, "bachelor", 0)
                one_br   = to_int(row, "one_br",   0)
                two_br   = to_int(row, "two_br",   0)
                three_br = to_int(row, "three_br", 0)
                four_br  = to_int(row, "four_br",  0)
                unknown  = to_int(row, "unknown",  0)
                total_units = bachelor + one_br + two_br + three_br + four_br + unknown

                residential_rent = to_float(row, "residential_rent")
                construction_cost = to_float(row, "construction_cost", 0)
                hotel_rooms     = int(to_float(row, "hotel_rooms", 0) or 0)
                _hotel_adr      = to_float(row, "hotel_adr")
                hotel_adr       = _hotel_adr if _hotel_adr else None
                _occ_csv        = to_float(row, "hotel_occupancy")
                hotel_occupancy = (_occ_csv / 100 if _occ_csv and _occ_csv > 1 else _occ_csv) if _occ_csv else None
                ind_warehouse_sqft  = to_float(row, "ind_warehouse_sqft")  or 0.0
                ind_office_sqft     = to_float(row, "ind_office_sqft")     or 0.0
                ind_yard_sqft       = to_float(row, "ind_yard_sqft")       or 0.0
                ind_dock_doors      = int(to_float(row, "ind_dock_doors")  or 0)
                ind_drive_in_doors  = int(to_float(row, "ind_drive_in_doors") or 0)
                ind_clear_height_ft = to_float(row, "ind_clear_height_ft") or 0.0
                ind_office_rate     = to_float(row, "ind_office_rate")     or None
                ind_yard_rate       = to_float(row, "ind_yard_rate")       or None
                property_taxes   = to_float(row, "property_taxes", 0)
                down_payment_pct = to_pct(row, "down_payment_pct", 20)
                interest_rate    = to_pct(row, "interest_rate",    4.5)
                term_years       = to_int(row, "term_years",  25)
                hold_years       = to_int(row, "hold_years",  30)
                expense_ratio    = to_pct(row, "expense_ratio", 40)
                lease_type_raw   = cell(row, "lease_type", "Normal").lower()
                lease_type = {"no": "Normal", "n": "Normal", "normal": "Normal",
                              "nn": "NNN", "nnn": "NNN"}.get(lease_type_raw, "Normal")

                # Determine rent mode
                annual_rent = None
                unit_mix    = None
                has_units   = total_units > 0

                if commercial_rent and not has_units:
                    annual_rent = commercial_rent
                elif residential_rent and not commercial_rent:
                    annual_rent = residential_rent
                elif commercial_rent and has_units:
                    annual_rent = commercial_rent + (residential_rent or 0)
                elif has_units:
                    # Residential or mixed-use — use city market rates
                    unit_mix = UnitMix(
                        bachelor=bachelor, one_br=one_br, two_br=two_br,
                        three_br=three_br, four_br=four_br, unknown=unknown,
                        floors=floors,
                    )
                    if is_commercial:
                        prop_type_field = property_type_raw
                # If nothing is set (no rent, no units, no property type) the
                # analyzer will still run — it will log missing data and save
                # whatever metrics it can compute.

                prop = PropertyInput(
                    address          = address,
                    mls_number       = mls,
                    status           = status,
                    original_price   = int(original_price),
                    asking_price     = int(original_price),
                    total_sq_ft      = int(total_sq_ft),
                    property_taxes   = property_taxes or 0,
                    down_payment_pct = down_payment_pct,
                    interest_rate    = interest_rate,
                    term_years       = term_years,
                    expense_ratio    = expense_ratio,
                    lease_type       = lease_type,
                    listing_date     = date.today().isoformat(),
                    hold_years       = hold_years,
                    annual_rent      = annual_rent,
                    city             = city,
                    province         = province,
                    property_type    = prop_type_field,
                    unit_mix         = unit_mix,
                    construction_cost = construction_cost,
                    hotel_rooms         = hotel_rooms,
                    hotel_adr           = hotel_adr,
                    hotel_occupancy     = hotel_occupancy,
                    ind_warehouse_sqft  = ind_warehouse_sqft,
                    ind_office_sqft     = ind_office_sqft,
                    ind_yard_sqft       = ind_yard_sqft,
                    ind_dock_doors      = ind_dock_doors,
                    ind_drive_in_doors  = ind_drive_in_doors,
                    ind_clear_height_ft = ind_clear_height_ft,
                    ind_office_rate     = ind_office_rate,
                    ind_yard_rate       = ind_yard_rate,
                )

                try:
                    analyzer = CommercialPropertyAnalyzer(prop, self._resolver)
                    self._store.save_property(analyzer.to_record())
                    if city and province:
                        self._store.ensure_city_in_rates(city, province)
                    saved += 1
                    print(f"  ✓ Imported: {address} [{mls}]")
                except ValueError as e:
                    # Save a full record with all input fields so it can be re-analyzed later
                    now = date.today().isoformat()
                    self._store.save_property({
                        "address":          address,
                        "mls_number":       mls,
                        "status":           status,
                        "listing_date":     now,
                        "created_at":       now,
                        "last_modified":    now,
                        "analyzed_on":      None,
                        "asking_price":     int(original_price),
                        "original_price":   int(original_price),
                        "total_sq_ft":      int(total_sq_ft),
                        "city":             city,
                        "province":         province,
                        "property_type":    prop_type_field,
                        "property_taxes":   property_taxes or 0,
                        "down_payment_pct": down_payment_pct,
                        "interest_rate":    interest_rate,
                        "term_years":       term_years,
                        "hold_years":       hold_years,
                        "expense_ratio":    expense_ratio,
                        "lease_type":       lease_type,
                        "annual_rent":      annual_rent,
                        "unit_mix": {
                            "bachelor": bachelor, "one_br": one_br, "two_br": two_br,
                            "three_br": three_br, "four_br": four_br, "unknown": unknown,
                            "floors": floors,
                        },
                        "floors":           floors,
                        "hotel_rooms":      hotel_rooms,
                        "hotel_adr":        hotel_adr,
                        "hotel_occupancy":  hotel_occupancy,
                        "ind_warehouse_sqft":  ind_warehouse_sqft,
                        "ind_office_sqft":     ind_office_sqft,
                        "ind_yard_sqft":       ind_yard_sqft,
                        "ind_dock_doors":      ind_dock_doors,
                        "ind_drive_in_doors":  ind_drive_in_doors,
                        "ind_clear_height_ft": ind_clear_height_ft,
                        "ind_office_rate":     ind_office_rate,
                        "ind_yard_rate":       ind_yard_rate,
                        "results":          [],
                    })
                    saved += 1
                    print(f"  ✓ Imported (no analysis): {address} [{mls}] — {e}")

            except Exception as e:
                errors.append(f"  Row {row_num} ({row.get('address','?')}): {e}")

        print(f"\n  Done — {saved} imported, {len(errors)} skipped.")
        if errors:
            print("  Issues:")
            for e in errors:
                print(e)

    def _save_csv_template(self):
        """Saves a sample CSV template the user can fill in."""
        path = "property_import_template.csv"
        headers = [
            "address", "mls_number", "status", "original_price", "property_type",
            "commercial_rent", "floors", "total_sq_ft",
            "bachelor", "one_br", "two_br", "three_br", "four_br", "unknown",
            "residential_rent", "property_taxes", "down_payment_pct",
            "interest_rate", "term_years", "hold_years", "expense_ratio", "lease_type",
            "hotel_rooms", "hotel_adr", "hotel_occupancy"
        ]
        placeholder = [
            "123 Example St, City, ON", "MLS-XXX", "active", "500000", "Retail",
            "", "1", "3000",
            "0", "0", "0", "0", "0", "0",
            "", "6000", "20", "4.5", "25", "30", "40", "Normal"
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(headers)
            w.writerow(placeholder)
        print(f"  Template saved to: {path}")

    @staticmethod
    def _record_to_prop(p: dict) -> "PropertyInput":
        """Rebuild a PropertyInput from a saved record dict. Raises ValueError if incomplete."""
        um_data   = p.get("unit_mix") or {}
        has_units = any(um_data.get(k, 0) for k in
                        ("bachelor","one_br","two_br","three_br","four_br","unknown"))
        unit_mix  = UnitMix(
            bachelor  = um_data.get("bachelor",  0),
            one_br    = um_data.get("one_br",    0),
            two_br    = um_data.get("two_br",    0),
            three_br  = um_data.get("three_br",  0),
            four_br   = um_data.get("four_br",   0),
            unknown   = um_data.get("unknown",   0),
            floors    = um_data.get("floors",    p.get("floors", 1)),
        ) if has_units else None
        return PropertyInput(
            address          = p["address"],
            mls_number       = p.get("mls_number", ""),
            status           = p.get("status", "active"),
            original_price   = p.get("original_price", p.get("asking_price", 0)),
            asking_price     = p.get("asking_price", 0),
            total_sq_ft      = p.get("total_sq_ft", 0),
            property_taxes   = p.get("property_taxes", 0),
            down_payment_pct = p.get("down_payment_pct", 0.20),
            interest_rate    = p.get("interest_rate",    0.045),
            term_years       = p.get("term_years",       25),
            hold_years       = p.get("hold_years",       30),
            expense_ratio    = p.get("expense_ratio",    0.40),
            lease_type       = p.get("lease_type",       "Normal"),
            construction_cost = p.get("construction_cost", 0) or 0,
            listing_date     = p.get("listing_date",     date.today().isoformat()),
            # Use manual annual_rent only if no derived values have ever been saved
            annual_rent      = p.get("annual_rent") if (
                p.get("commercial_rent") is None and p.get("residential_rent") is None
            ) else None,
            city             = p.get("city"),
            province         = p.get("province"),
            property_type    = p.get("property_type"),
            unit_mix         = unit_mix,
            hotel_rooms      = p.get("hotel_rooms", 0) or 0,
            hotel_adr        = p.get("hotel_adr"),
            hotel_occupancy  = p.get("hotel_occupancy"),
            ind_warehouse_sqft  = p.get("ind_warehouse_sqft",  0) or 0,
            ind_office_sqft     = p.get("ind_office_sqft",     0) or 0,
            ind_yard_sqft       = p.get("ind_yard_sqft",       0) or 0,
            ind_dock_doors      = p.get("ind_dock_doors",      0) or 0,
            ind_drive_in_doors  = p.get("ind_drive_in_doors",  0) or 0,
            ind_clear_height_ft = p.get("ind_clear_height_ft", 0) or 0,
            ind_office_rate     = p.get("ind_office_rate"),
            ind_yard_rate       = p.get("ind_yard_rate"),
        )

    def _reanalyze_city(self, city: str, province: str):
        """Re-run analysis for all saved properties in the given city and update their records."""
        props   = self._store.load_properties()
        updated = 0
        for i, p in enumerate(props):
            if (p.get("city", "").lower() != city.lower() or
                    p.get("province", "").upper() != province.upper()):
                continue
            try:
                prop     = self._record_to_prop(p)
                analyzer = CommercialPropertyAnalyzer(prop, self._resolver)
                record   = analyzer.to_record(existing=p)
                self._store.update_property(i, record)
                updated += 1
            except Exception:
                pass  # Leave unchanged if still can't analyze
        if updated:
            print(f"  ✓ Re-analyzed {updated} propert{'y' if updated == 1 else 'ies'} in {city}, {province}.")

    def _edit_score_config(self):
        """Display scoring formula and allow editing weights, thresholds, and city distances."""
        cfg        = self._load_score_config()
        weights    = cfg["weights"]
        thresholds = cfg["thresholds"]

        DESCRIPTIONS = {
            "Cap Rate":        "NOI / (asking + construction)  —  higher is better",
            "CoCR":            "Annual cash flow / cash invested  —  higher is better",
            "DSCR":            "NOI / annual mortgage payment  —  higher is better",
            "IRR":             "Internal rate of return over hold period  —  higher is better",
            "Equity Multiple": "Total return / cash invested  —  higher is better",
            "Cash Flow":       "Annual cash flow ($)  —  higher is better",
            "Price Drop":      "% reduction from original list price  —  higher is better",
            "DOM":             "Days on market  —  more days = more seller motivation",
            "Location":        "km to nearest regional centre  —  closer is better",
        }

        while True:
            cfg      = self._load_score_config()
            weights  = cfg["weights"]
            thresholds = cfg["thresholds"]
            total_w  = sum(w for w in weights.values() if w > 0)

            print(f"\n{'SCORING FORMULA':^75}")
            print(self.DIVIDER)
            print(f"  Weights must sum to 1.0.  Currently: {total_w:.2f}")
            print("  Scores normalized automatically — set a weight to 0 to disable a component.")
            print(self.DIVIDER)
            print(f"  {'#':<3} {'COMPONENT':<18} {'WEIGHT':>7}  {'FLOOR':>9}  {'CEILING':>9}  DESCRIPTION")
            print(self.DIVIDER)
            keys = list(weights.keys())
            for i, k in enumerate(keys, 1):
                w      = weights[k]
                lo, hi = thresholds.get(k, [0, 1])
                desc   = DESCRIPTIONS.get(k, "")
                pct    = f"{w*100:.0f}%"
                print(f"  {i:<3} {k:<18} {pct:>7}  {lo:>9}  {hi:>9}  {desc}")
            print(self.DIVIDER)
            print("  d  Edit city distances to regional centres")
            print("  c  Edit city opportunity score weights")
            print("  0  Back")
            print(self.DIVIDER)

            choice = input("  Edit # (or d/c/0): ").strip().lower()
            if choice == "0":
                break

            if choice == "d":
                self._edit_city_distances()
                continue

            if choice == "c":
                self._edit_city_weights()
                continue

            try:
                idx = int(choice) - 1
                if not (0 <= idx < len(keys)):
                    raise ValueError
            except ValueError:
                print("  Invalid choice.")
                continue

            k      = keys[idx]
            lo, hi = thresholds[k]
            w      = weights[k]

            print(f"\n  Editing: {k}")
            print(f"  {DESCRIPTIONS.get(k, '')}")
            print(self.THIN_DIVIDER)

            # Weight
            raw = input(f"  Weight % (currently {w*100:.0f}%, Enter to keep): ").strip()
            if raw:
                try:
                    new_w = float(raw)
                    new_w = new_w / 100 if new_w > 1 else new_w
                    weights[k] = round(new_w, 4)
                except ValueError:
                    print("  Invalid — weight unchanged.")

            # Floor threshold
            raw = input(f"  Floor (currently {lo}, score=0 at this value, Enter to keep): ").strip()
            if raw:
                try:
                    thresholds[k][0] = float(raw)
                except ValueError:
                    print("  Invalid — floor unchanged.")

            # Ceiling threshold
            raw = input(f"  Ceiling (currently {hi}, score=10 at this value, Enter to keep): ").strip()
            if raw:
                try:
                    thresholds[k][1] = float(raw)
                except ValueError:
                    print("  Invalid — ceiling unchanged.")

            cfg["weights"]    = weights
            cfg["thresholds"] = thresholds
            self._save_score_config(cfg)
            print("  Saved.")

    def _edit_city_weights(self):
        """Edit the weights used to compute the city opportunity score."""
        DESCRIPTIONS = {
            "avg_score":  "Avg investment score of all deals in city  (higher = better city)",
            "best_score": "Best single deal score available in city",
            "volume":     "Number of active listings  (more = more deal flow)",
            "cap_rate":   "Avg cap rate of city properties  (higher yield environment)",
            "price_drop": "Avg % price reduction from original list  (seller motivation)",
            "dom":        "Avg days on market  (higher = softer market = more leverage)",
            "coc":        "Avg cash-on-cash return  (immediate income quality)",
        }
        while True:
            cfg  = self._load_score_config()
            cw   = cfg.get("city_weights", {})
            total = sum(cw.values())
            keys  = list(cw.keys())

            print(f"\n{'CITY OPPORTUNITY WEIGHTS':^75}")
            print(self.DIVIDER)
            print(f"  Weights must sum to 1.0.  Currently: {total:.2f}")
            print(self.DIVIDER)
            print(f"  {'#':<3} {'SIGNAL':<14} {'WEIGHT':>7}  DESCRIPTION")
            print(self.DIVIDER)
            for i, k in enumerate(keys, 1):
                pct = f"{cw[k]*100:.0f}%"
                print(f"  {i:<3} {k:<14} {pct:>7}  {DESCRIPTIONS.get(k,'')}")
            print(self.DIVIDER)
            print("  0  Back")
            print(self.DIVIDER)

            choice = input("  Edit # (or 0): ").strip()
            if choice == "0":
                break
            try:
                idx = int(choice) - 1
                if not (0 <= idx < len(keys)):
                    raise ValueError
            except ValueError:
                print("  Invalid choice.")
                continue

            k = keys[idx]
            raw = input(f"  New weight % for '{k}' (currently {cw[k]*100:.0f}%, Enter to keep): ").strip()
            if raw:
                try:
                    v = float(raw)
                    v = v / 100 if v > 1 else v
                    cw[k] = round(v, 4)
                    cfg["city_weights"] = cw
                    self._save_score_config(cfg)
                    print(f"  Saved. New total: {sum(cw.values()):.2f}")
                except ValueError:
                    print("  Invalid number.")

    def _edit_city_distances(self):
        """Add or edit distance-to-regional-centre for each city."""
        path      = "json/city_distances.json"
        distances = {}
        if os.path.exists(path):
            try:
                distances = self._store._read(path)
            except Exception:
                pass

        # Pre-populate with cities from saved properties
        for p in self._store.load_properties():
            city = (p.get("city") or "").strip()
            if city and city not in distances:
                distances[city] = {"distance_km": None, "nearest_centre": ""}

        while True:
            cities = sorted(distances.keys(), key=str.lower)
            print(f"\n{'CITY DISTANCES TO REGIONAL CENTRES':^75}")
            print(self.DIVIDER)
            print(f"  {'#':<3} {'CITY':<22} {'NEAREST CENTRE':<22} {'KM':>6}")
            print(self.DIVIDER)
            for i, city in enumerate(cities, 1):
                d  = distances[city]
                km = d.get("distance_km")
                nc = d.get("nearest_centre") or "—"
                print(f"  {i:<3} {city:<22} {nc:<22} {str(km) if km is not None else '—':>6}")
            print(self.DIVIDER)
            print("  Enter # to edit   a = add city   0 = back")
            print(self.THIN_DIVIDER)

            choice = input("  Select: ").strip().lower()
            if choice == "0":
                break

            if choice == "a":
                city = input("  City name: ").strip().title()
                if not city:
                    continue
                if city not in distances:
                    distances[city] = {"distance_km": None, "nearest_centre": ""}
                cities = sorted(distances.keys(), key=str.lower)

            try:
                idx  = int(choice) - 1
                city = cities[idx]
            except (ValueError, IndexError):
                print("  Invalid.")
                continue

            nc = input(f"  Nearest regional centre (currently '{distances[city].get('nearest_centre') or ''}', Enter to keep): ").strip()
            if nc:
                distances[city]["nearest_centre"] = nc

            km_raw = input(f"  Distance in km (currently {distances[city].get('distance_km')}, Enter to keep): ").strip()
            if km_raw:
                try:
                    distances[city]["distance_km"] = float(km_raw)
                except ValueError:
                    print("  Invalid km — unchanged.")

            os.makedirs("json", exist_ok=True)
            self._store._write(path, distances)
            print(f"  Saved {city}.")

    def _reanalyze_all(self):
        """Re-run analysis for every saved property and update all records."""
        props = self._store.load_properties()
        if not props:
            print("\n  No properties on file.")
            return
        updated = skipped = errors = 0
        for i, p in enumerate(props):
            try:
                prop     = self._record_to_prop(p)
                analyzer = CommercialPropertyAnalyzer(prop, self._resolver)
                record   = analyzer.to_record(existing=p)
                # Preserve notes — to_record doesn't include them
                if p.get("notes"):
                    record["notes"] = p["notes"]
                self._store.update_property(i, record)
                updated += 1
            except ValueError:
                skipped += 1   # missing rent data — leave unchanged
            except Exception:
                errors += 1
        total = len(props)
        print(f"\n  Re-analysis complete — {updated}/{total} updated", end="")
        if skipped: print(f", {skipped} skipped (missing rates)", end="")
        if errors:  print(f", {errors} errors", end="")
        print(".")

    def _edit_commercial_rates(self):
        """Browse and edit commercial rates for any city."""
        raw = self._store._read(self._store._commercial_path)
        cities = sorted(raw["cities"].keys(), key=str.lower)
        if not cities:
            print("\n  No commercial rate data found.")
            return

        COMM_TYPES = ["Office", "Retail", "Industrial", "Mixed-Use"]
        col_n    = 3
        col_city = 20
        col_prov = 4
        col_rate = 12   # each rate column

        header = (
            f"  {'#':<{col_n}} {'CITY':<{col_city}} {'PROV':<{col_prov}}"
            + "".join(f"  {t:>{col_rate}}" for t in COMM_TYPES)
        )
        divider = "-" * len(header)

        print(f"\n{'COMMERCIAL RENT RATES ($/sq ft/yr)':^{len(header)}}")
        print(divider)
        print(header)
        print(divider)
        for i, c in enumerate(cities, 1):
            d = raw["cities"][c]
            row = f"  {i:<{col_n}} {c:<{col_city}} {d['province']:<{col_prov}}"
            for t in COMM_TYPES:
                val = d["types"].get(t)
                cell = f"${val}" if val is not None else "—"
                row += f"  {cell:>{col_rate}}"
            print(row)
        print(divider)
        print(f"  {'N':<{col_n}} {'Add new city':}")
        print()

        choice = input("  Select city to edit, or N to add: ").strip()

        if choice.lower() == "n":
            city     = input("  City name: ").strip()
            province = input("  Province: ").strip().upper()
            self._enter_commercial_rates(city, province)
            return

        try:
            idx = int(choice) - 1
            if not (0 <= idx < len(cities)):
                print("  Invalid.")
                return
        except ValueError:
            print("  Invalid.")
            return

        city_name = cities[idx]
        city_data = raw["cities"][city_name]
        province  = city_data["province"]
        COMM_TYPES = ["Office", "Retail", "Industrial", "Mixed-Use"]

        print(f"\n  Editing: {city_name}, {province}")
        print(self.THIN_DIVIDER)
        current_types = city_data["types"]
        for i, t in enumerate(COMM_TYPES, 1):
            cur = current_types.get(t, "—")
            print(f"  {i}  {t:<14} (current: ${cur}/sq ft)")
        print("  0  Done")

        updated = dict(current_types)
        while True:
            c = input("  Field to edit (0 done): ").strip()
            if c == "0":
                break
            try:
                fi = int(c) - 1
                if not (0 <= fi < len(COMM_TYPES)):
                    print("  Invalid.")
                    continue
            except ValueError:
                print("  Invalid.")
                continue
            t = COMM_TYPES[fi]
            raw_val = input(f"  New rate for {t} ($/sq ft/yr): ").strip()
            if not raw_val:
                continue
            try:
                updated[t] = float(raw_val)
                print(f"  Set {t} = ${updated[t]}/sq ft")
            except ValueError:
                print("  Invalid number.")

        self._store.save_commercial_city(city_name, province, updated)
        print(f"  Saved commercial rates for {city_name}, {province}.")
        self._reanalyze_city(city_name, province)

    def _edit_residential_rates(self):
        """Browse and edit residential rates for any city."""
        raw = self._store._read(self._store._residential_path)
        cities = sorted(raw["cities"].keys(), key=str.lower)
        if not cities:
            print("\n  No residential rate data found.")
            return

        RES_FIELDS = [
            ("bachelor",  "Bachelor"),
            ("one_br",    "1BR"),
            ("two_br",    "2BR"),
            ("three_br",  "3BR"),
            ("four_br",   "4BR"),
            ("unknown",   "Unknown"),
        ]

        RES_LABELS = [("bachelor","Bach"), ("one_br","1BR"), ("two_br","2BR"),
                      ("three_br","3BR"), ("four_br","4BR"), ("unknown","Unk")]
        col_n    = 3
        col_city = 20
        col_prov = 4
        col_rate = 8

        header = (
            f"  {'#':<{col_n}} {'CITY':<{col_city}} {'PROV':<{col_prov}}"
            + "".join(f"  {lbl:>{col_rate}}" for _, lbl in RES_LABELS)
        )
        divider = "-" * len(header)

        print(f"\n{'RESIDENTIAL RENT RATES ($/mo)':^{len(header)}}")
        print(divider)
        print(header)
        print(divider)
        for i, c in enumerate(cities, 1):
            d = raw["cities"][c]
            row = f"  {i:<{col_n}} {c:<{col_city}} {d['province']:<{col_prov}}"
            for key, _ in RES_LABELS:
                val = d["units"].get(key)
                cell = f"${int(val)}" if val is not None else "—"
                row += f"  {cell:>{col_rate}}"
            print(row)
        print(divider)
        print(f"  {'N':<{col_n}} {'Add new city':}")
        print()

        choice = input("  Select city to edit, or N to add: ").strip()

        if choice.lower() == "n":
            city     = input("  City name: ").strip()
            province = input("  Province: ").strip().upper()
            self._enter_residential_rates(city, province)
            return

        try:
            idx = int(choice) - 1
            if not (0 <= idx < len(cities)):
                print("  Invalid.")
                return
        except ValueError:
            print("  Invalid.")
            return

        city_name = cities[idx]
        city_data = raw["cities"][city_name]
        province  = city_data["province"]
        current   = city_data["units"]

        print(f"\n  Editing: {city_name}, {province}")
        print(self.THIN_DIVIDER)
        for i, (key, label) in enumerate(RES_FIELDS, 1):
            cur = current.get(key, "—")
            print(f"  {i}  {label:<12} (current: ${cur}/mo)")
        print("  0  Done")

        updated = dict(current)
        while True:
            c = input("  Field to edit (0 done): ").strip()
            if c == "0":
                break
            try:
                fi = int(c) - 1
                if not (0 <= fi < len(RES_FIELDS)):
                    print("  Invalid.")
                    continue
            except ValueError:
                print("  Invalid.")
                continue
            key, label = RES_FIELDS[fi]
            raw_val = input(f"  New monthly rent for {label}: $").strip()
            if not raw_val:
                continue
            try:
                updated[key] = float(raw_val)
                print(f"  Set {label} = ${updated[key]}/mo")
            except ValueError:
                print("  Invalid number.")

        # Auto-populate unknown as average of bedroom rates
        known_vals = [updated[k] for k in ("bachelor","one_br","two_br","three_br","four_br") if k in updated]
        if known_vals:
            updated["unknown"] = round(sum(known_vals) / len(known_vals), 2)
        self._store.save_residential_city(city_name, province, updated)
        print(f"  Saved residential rates for {city_name}, {province}.")
        print(f"  Unknown rate set to average: ${updated.get('unknown', '—')}/mo")
        self._reanalyze_city(city_name, province)

    def _enter_commercial_rates(self, city: str, province: str):
        """Prompt for all commercial rate fields for a new or missing city."""
        COMM_TYPES = ["Office", "Retail", "Industrial", "Mixed-Use"]
        print(f"\n  Enter commercial rates for {city}, {province} ($/sq ft/yr):")
        rates = {}
        for t in COMM_TYPES:
            while True:
                raw = input(f"    {t:<14}: $").strip()
                if not raw:
                    print(f"    Skipping {t}.")
                    break
                try:
                    rates[t] = float(raw)
                    break
                except ValueError:
                    print("    Invalid number.")
        if rates:
            self._store.save_commercial_city(city, province, rates)
            print(f"  Saved commercial rates for {city}, {province}.")
            self._reanalyze_city(city, province)

    def _enter_residential_rates(self, city: str, province: str):
        """Prompt for all residential rate fields for a new or missing city."""
        RES_FIELDS = [
            ("bachelor",  "Bachelor"),
            ("one_br",    "1BR"),
            ("two_br",    "2BR"),
            ("three_br",  "3BR"),
            ("four_br",   "4BR"),
            ("unknown",   "Unknown"),
        ]
        print(f"\n  Enter residential rates for {city}, {province} ($/mo):")
        units = {}
        for key, label in RES_FIELDS:
            while True:
                raw = input(f"    {label:<12}: $").strip()
                if not raw:
                    print(f"    Skipping {label}.")
                    break
                try:
                    units[key] = float(raw)
                    break
                except ValueError:
                    print("    Invalid number.")
        if units:
            # Auto-populate unknown as average of bedroom rates
            known_vals = [units[k] for k in ("bachelor","one_br","two_br","three_br","four_br") if k in units]
            if known_vals:
                units["unknown"] = round(sum(known_vals) / len(known_vals), 2)
            self._store.save_residential_city(city, province, units)
            print(f"  Saved residential rates for {city}, {province}.")
            print(f"  Unknown rate set to average: ${units.get('unknown', '—')}/mo")
            self._reanalyze_city(city, province)

    def _delete(self):
        props = self._sorted_props()
        if not props:
            print("\n  No properties on file.")
            return
        self._list()
        idx = self._pick_index(props, "Delete property #")
        if idx is None:
            return

        p     = props[idx]
        addr  = _display_address(p.get("address", ""))
        confirm = input(f"  Delete '{addr}'? This cannot be undone. (y/n): ").strip().lower()
        if confirm in ("y", "yes"):
            # Find raw index (storage order may differ from display order)
            raw_props = self._store.load_properties()
            key = (p.get("address",""), p.get("listing_date",""))
            raw_idx = next((i for i,r in enumerate(raw_props)
                            if (r.get("address",""),r.get("listing_date","")) == key), None)
            if raw_idx is not None:
                self._store.delete_property(raw_idx)
                print(f"  Deleted: {addr}")
            else:
                print("  Error: could not locate record.")
        else:
            print("  Cancelled.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sort_key(p):
        city    = p.get("city")
        addr    = p.get("address") or ""
        st_name, st_num = _parse_address_sort(addr)
        if city:
            return (0, city.lower(), st_name, st_num)
        return (1, st_name, st_num, "")

    def _sorted_props(self) -> list:
        """Returns properties sorted the same way list_properties displays them."""
        return sorted(self._store.load_properties(), key=self._sort_key)

    def _pick_index(self, sorted_props: list, prompt: str):
        """Prompts for a 1-based number from the sorted list, returns 0-based index or None."""
        try:
            n = int(input(f"  {prompt} (1-{len(sorted_props)}): ").strip())
            if 1 <= n <= len(sorted_props):
                return n - 1
            print("  Number out of range.")
            return None
        except (ValueError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return None

    def _prompt_property(self) -> PropertyInput:
        """
        Prompts for all property fields in a fixed, logical order.

        Rules:
          - MLS # is required
          - Asking price = original price (editable later)
          - City AND province are parsed from the address string automatically
            Expected format: "... , City Province"  e.g. "24 Main St, Alexandria ON"
            Also handles unit prefix:  "24-26 Main St S, Alexandria, ON"
          - Listing date is set automatically to today
          - Rent mode auto-detected from what is entered

        Rent mode:
          - Commercial income entered, no units         → pure commercial
          - Units entered, no commercial income         → residential (market rate or direct)
          - Both entered                                → mixed-use (rents summed)
          - Neither, commercial type, city in CSV       → city market rate lookup
          - Neither, city NOT in CSV or residential type → error with clear message
        """

        def ask(label, cast=str, default=None, optional=False):
            parts = [f"  {label}"]
            if optional:
                parts.append(" (optional, Enter to skip)")
            if default is not None:
                parts.append(f" [{default}]")
            parts.append(": ")
            raw = input("".join(parts)).strip()
            if not raw:
                if default is not None:
                    return default
                if optional:
                    return None
            return cast(raw) if raw else None

        def ask_pct(label, default_pct):
            """Accepts 20 or 0.20 — always returns decimal."""
            raw = ask(label, float, default_pct)
            return raw / 100 if raw > 1 else raw

        def parse_city_province(addr: str):
            """
            Extracts city and province from an address string.

            Handles formats:
              "123 Main St, Ottawa ON"          → ("Ottawa", "ON")
              "24-26 Main St S, Alexandria, ON" → ("Alexandria", "ON")
              "456 Bank St, Suite 2, Toronto ON" → ("Toronto", "ON")

            Strategy: look at the last 1-2 comma-separated segments.
            The province is the last 2-letter uppercase token found.
            The city is everything in that segment before the province token.
            """
            if not addr or "," not in addr:
                return None, None

            # Check if last segment is just a province code e.g. ", ON"
            parts = [p.strip() for p in addr.split(",")]
            last = parts[-1].strip()

            # Canadian province codes
            PROVINCES = {"AB","BC","MB","NB","NL","NS","NT","NU","ON","PE","QC","SK","YT"}

            if last.upper() in PROVINCES:
                # Format: "..., City, ON"
                province = last.upper()
                city     = parts[-2].strip() if len(parts) >= 2 else None
            else:
                # Format: "..., City ON"  — province is last word of last segment
                tokens   = last.split()
                province = tokens[-1].upper() if tokens and tokens[-1].upper() in PROVINCES else None
                city     = " ".join(tokens[:-1]).strip() if province else None

            return city or None, province or None

        print()

        # ── Core identity ────────────────────────────────────────────────
        while True:
            address = ask("Address")
            city, province = parse_city_province(address)
            if city:
                break
            print("  ⚠  Could not parse city from that address.")
            print("     Expected: '123 Main St, Ottawa ON'  or  '123 Main St, Ottawa, ON'")
            print("     Please re-enter.")

        original_price = ask("Original price", lambda x: int(float(x.replace(',',''))))
        mls_number     = ask("MLS #")
        if not mls_number:
            raise ValueError("MLS # is required.")

        while True:
            status_raw = input("  Status (a=active / i=inactive): ").strip().lower()
            resolved = {"a": "active", "i": "inactive"}.get(status_raw, status_raw)
            if resolved in ("active", "inactive"):
                status = resolved
                break
            print("  Invalid — enter 'a' or 'i'.")

        # ── Property type ─────────────────────────────────────────────────
        PROP_SHORTCUTS = {
            "o": "Office", "r": "Retail", "i": "Industrial",
            "m": "Mixed-Use", "re": "Residential", "mu": "Multi-Family", "h": "Hotel", "ro": "Retail-Office"
        }
        VALID_TYPES = set(PROP_SHORTCUTS.values())
        print("  Property type:  o=Office  r=Retail  i=Industrial  m=Mixed-Use  re=Residential  mu=Multi-Family")
        while True:
            _pt_raw = input("  Property type: ").strip()
            if not _pt_raw:
                print("  Required — enter a type or shorthand.")
                continue
            _resolved = PROP_SHORTCUTS.get(_pt_raw.lower())
            if not _resolved:
                _resolved = next((v for v in VALID_TYPES if v.lower() == _pt_raw.lower()), None)
            if not _resolved:
                print(f"  Invalid — must be one of: {', '.join(sorted(VALID_TYPES))}.")
                continue
            property_type_raw = _resolved
            break

        COMMERCIAL_TYPES   = {"office", "retail", "industrial", "mixed-use", "hotel", "retail-office"}
        is_commercial_type = property_type_raw.strip().lower() in COMMERCIAL_TYPES

        # ── Rent income ───────────────────────────────────────────────────
        commercial_rent = ask("Commercial rent income / year", float, optional=True)

        # ── Building structure ───────────────────────────────────────────
        floors      = ask("Floors", int, 1)
        total_sq_ft = ask("Total sq ft", lambda x: int(float(x.replace(',',''))))

        # ── Residential units ────────────────────────────────────────────
        bachelor = ask("Bachelor units", int, 0)
        one_br   = ask("1BR units",      int, 0)
        two_br   = ask("2BR units",      int, 0)
        three_br = ask("3BR units",      int, 0)
        four_br  = ask("4BR units",      int, 0)
        unknown  = ask("Unknown residential units", int, 0)

        total_units      = bachelor + one_br + two_br + three_br + four_br + unknown
        residential_rent = ask("Residential rent income / year", float, optional=True) if total_units > 0 else None

        # ── Financials ───────────────────────────────────────────────────
        property_taxes    = ask("Annual property taxes", float)
        construction_cost = ask("Construction cost (renos/build-out)", float, optional=True) or 0.0
        down_payment_pct = ask_pct("Down payment %", 20)
        interest_rate    = ask_pct("Interest rate %", 4.5)
        term_years       = ask("Loan term (years)", int, 25)

        # ── Analysis parameters ──────────────────────────────────────────
        hold_years    = ask("Hold years", int, 30)
        expense_ratio = ask_pct("Expense ratio %", 40)
        while True:
            _lt_raw = input("  Lease type (no=Normal / nn=NNN) [Normal]: ").strip().lower()
            if not _lt_raw:
                lease_type = "Normal"
                break
            resolved_lt = {"no": "Normal", "n": "Normal", "normal": "Normal",
                           "nn": "NNN", "nnn": "NNN"}.get(_lt_raw)
            if resolved_lt:
                lease_type = resolved_lt
                break
            print("  Invalid — enter 'no' for Normal or 'nn' for NNN.")

        # Listing date = today, set automatically
        listing_date = date.today().isoformat()

        # ── Hotel-specific fields (only prompted for Hotel type) ─────────────
        hotel_rooms     = 0
        hotel_adr       = None
        hotel_occupancy = None
        if property_type_raw.strip().lower() == "hotel":
            print("  ── Hotel Details ──")
            hotel_rooms = ask("Number of rooms", int)
            _adr_raw = input("  Average Daily Rate / room (ADR $, Enter to skip): ").strip()
            if _adr_raw:
                try:
                    hotel_adr = float(_adr_raw.replace(",", "").replace("$", ""))
                except ValueError:
                    pass
            _occ_raw = input("  Target occupancy % (e.g. 65, Enter to skip): ").strip()
            if _occ_raw:
                try:
                    v = float(_occ_raw.replace("%", ""))
                    hotel_occupancy = v / 100 if v > 1 else v
                except ValueError:
                    pass

        # ── Industrial-specific fields (only prompted for Industrial type) ────
        ind_warehouse_sqft  = 0.0
        ind_office_sqft     = 0.0
        ind_yard_sqft       = 0.0
        ind_dock_doors      = 0
        ind_drive_in_doors  = 0
        ind_clear_height_ft = 0.0
        ind_office_rate     = None
        ind_yard_rate       = None
        if property_type_raw.strip().lower() == "industrial":
            print("  ── Industrial Details (Enter to skip any field) ──")
            _v = ask("Warehouse/storage sq ft", float, optional=True)
            if _v: ind_warehouse_sqft = _v
            _v = ask("Office component sq ft", float, optional=True)
            if _v: ind_office_sqft = _v
            _v = ask("Yard/outdoor storage sq ft", float, optional=True)
            if _v: ind_yard_sqft = _v
            _v = ask("Dock-level doors (count)", int, optional=True)
            if _v: ind_dock_doors = int(_v)
            _v = ask("Drive-in doors (count)", int, optional=True)
            if _v: ind_drive_in_doors = int(_v)
            _v = ask("Clear ceiling height (ft)", float, optional=True)
            if _v: ind_clear_height_ft = _v
            _raw = input("  Office component rate $/sqft/yr (Enter to use 140% of base): ").strip()
            if _raw:
                try: ind_office_rate = float(_raw)
                except ValueError: pass
            _raw = input("  Yard rate $/sqft/yr (Enter to use 15% of base): ").strip()
            if _raw:
                try: ind_yard_rate = float(_raw)
                except ValueError: pass

        # ── Determine rent mode ──────────────────────────────────────────
        has_units     = total_units > 0
        has_comm_rent = commercial_rent is not None
        has_res_rent  = residential_rent is not None

        annual_rent     = None
        unit_mix        = None
        prop_type_field = property_type_raw  # always preserve the entered type

        if has_comm_rent and not has_units:
            # Pure commercial, rent given directly
            annual_rent = commercial_rent

        elif has_res_rent and not has_comm_rent:
            # Pure residential, rent given directly
            annual_rent = residential_rent

        elif has_comm_rent and has_units:
            # Mixed-use, both rents given directly — sum them
            annual_rent = commercial_rent + (residential_rent or 0)

        elif has_units and not has_comm_rent:
            # Residential or mixed-use — use city market rates for missing rent
            unit_mix = UnitMix(
                bachelor=bachelor, one_br=one_br, two_br=two_br,
                three_br=three_br, four_br=four_br, unknown=unknown,
                floors=floors,
            )
            # Keep property_type for mixed-use ground floor commercial lookup
            if is_commercial_type:
                prop_type_field = property_type_raw

        elif property_type_raw.strip().lower() == "hotel":
            # Hotel revenue computed from rooms/ADR/occupancy in RentResolver
            pass

        elif property_type_raw.strip().lower() == "retail-office":
            # Retail-Office: no residential units, but floors matters for the rent split
            # Build a floors-only UnitMix so the resolver can read floors
            if not unit_mix:
                unit_mix = UnitMix(floors=floors)

        else:
            # No rent, no units — need commercial type + city market data
            if not is_commercial_type:
                raise ValueError(
                    f"'{property_type_raw}' is not a known commercial type. "
                    "Enter rent income directly, or use: Office, Retail, Industrial, Mixed-Use."
                )

        return PropertyInput(
            address          = address,
            mls_number       = mls_number,
            status           = status,
            original_price   = original_price,
            asking_price     = original_price,
            total_sq_ft      = total_sq_ft,
            property_taxes   = property_taxes,
            down_payment_pct = down_payment_pct,
            interest_rate    = interest_rate,
            term_years       = term_years,
            expense_ratio    = expense_ratio,
            lease_type       = lease_type,
            listing_date     = listing_date,
            hold_years       = hold_years,
            annual_rent      = annual_rent,
            city             = city,
            province         = province,
            property_type    = prop_type_field,
            unit_mix         = unit_mix,
            construction_cost = construction_cost,
            hotel_rooms       = hotel_rooms,
            hotel_adr         = hotel_adr,
            hotel_occupancy   = hotel_occupancy,
            ind_warehouse_sqft  = ind_warehouse_sqft,
            ind_office_sqft     = ind_office_sqft,
            ind_yard_sqft       = ind_yard_sqft,
            ind_dock_doors      = ind_dock_doors,
            ind_drive_in_doors  = ind_drive_in_doors,
            ind_clear_height_ft = ind_clear_height_ft,
            ind_office_rate     = ind_office_rate,
            ind_yard_rate       = ind_yard_rate,
        )

# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    store = DataStore()
    resolver = RentResolver(
        commercial_loader  = CommercialRentLoader(store),
        residential_loader = ResidentialRentLoader(store),
        data_store         = store,
    )
    PropertyMenu(store, resolver).run()