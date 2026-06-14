from models.report_row import ReportRow
from analysis.industrial_config import load_premiums


class HotelMetrics:
    """Hotel-specific operating metrics: RevPAR, ADR, Occupancy, GOP, NRevPAR."""

    FF_E_RESERVE_RATIO = 0.04

    NREVPAR_DIST_COST_LOW  = 0.10  # direct-heavy / owner-operated
    NREVPAR_DIST_COST_MID  = 0.15  # typical mixed-channel
    NREVPAR_DIST_COST_HIGH = 0.20  # OTA-heavy / branded with fees

    def __init__(self, prop, annual_revenue: float):
        rooms       = prop.hotel_rooms or 0
        adr         = prop.hotel_adr or 0.0
        occupancy   = prop.hotel_occupancy or 0.0
        self.rooms      = rooms
        self.adr        = adr
        self.occupancy  = occupancy * 100

        self.revpar        = adr * occupancy
        self.nrevpar_low   = self.revpar * (1 - self.NREVPAR_DIST_COST_LOW)
        self.nrevpar_mid   = self.revpar * (1 - self.NREVPAR_DIST_COST_MID)
        self.nrevpar_high  = self.revpar * (1 - self.NREVPAR_DIST_COST_HIGH)
        self.rev_per_room = (annual_revenue / rooms) if rooms else 0
        self.gop_amount   = annual_revenue * (1 - prop.expense_ratio)
        self.gop_margin   = (1 - prop.expense_ratio) * 100
        self.ffe_reserve  = annual_revenue * self.FF_E_RESERVE_RATIO
        occupied_nights   = rooms * occupancy * 365 if rooms else 0
        total_expenses    = annual_revenue * prop.expense_ratio
        self.cpor         = (total_expenses / occupied_nights) if occupied_nights else 0

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
            rows.append(ReportRow("RevPAR",              f"${self.revpar:,.2f}",                                                    self._revpar_grade()))
            rows.append(ReportRow("NRevPAR (low dist.)",  f"${self.nrevpar_low:,.2f}",  ""))
            rows.append(ReportRow("NRevPAR (mid dist.)",  f"${self.nrevpar_mid:,.2f}",  ""))
            rows.append(ReportRow("NRevPAR (high dist.)", f"${self.nrevpar_high:,.2f}", ""))
        if self.rooms:
            rows.append(ReportRow("Rev/Room/Yr",     f"${self.rev_per_room:,.0f}",      ""))
        rows.append(    ReportRow("GOP Margin",      f"{self.gop_margin:.1f}%",         self._gop_grade()))
        rows.append(    ReportRow("GOP Amount",      f"${self.gop_amount:,.0f}",        ""))
        if self.cpor:
            rows.append(ReportRow("CPOR",            f"${self.cpor:,.2f}/night",        ""))
        rows.append(    ReportRow("FF&E Reserve",    f"${self.ffe_reserve:,.0f}/yr",    ""))
        return rows


class IndustrialMetrics:
    """Industrial property income breakdown by component.

    Coefficients are loaded from json/industrial_premiums.json (heuristics with
    no published $ basis); the class constants below are fallbacks that mirror
    the shipped file. When building details are provided, ``total_income`` is the
    figure the analyser feeds into NOI/score — not a flat $/sq ft estimate.
    """

    # Fallback defaults (mirror json/industrial_premiums.json).
    CLEAR_HEIGHT_BASE_FT         = 18
    CLEAR_HEIGHT_PREMIUM_PER_FT  = 0.02
    CLEAR_HEIGHT_PREMIUM_CAP     = 0.20
    OFFICE_PREMIUM_RATIO         = 1.40
    YARD_RATE_RATIO              = 0.15
    DOCK_DOOR_ANNUAL             = 1200
    DRIVE_IN_DOOR_ANNUAL         = 600

    def __init__(self, prop, base_industrial_rate: float):
        self.base_rate = base_industrial_rate

        prem            = load_premiums()
        ch              = prem["clear_height_premium_per_ft"]
        base_ft         = ch.get("base_ft", self.CLEAR_HEIGHT_BASE_FT)
        per_ft          = ch.get("value",   self.CLEAR_HEIGHT_PREMIUM_PER_FT)
        cap_pct         = ch.get("cap_pct", self.CLEAR_HEIGHT_PREMIUM_CAP)
        office_ratio    = prem["office_premium_ratio"]["value"]
        yard_ratio      = prem["yard_rate_ratio"]["value"]
        dock_annual     = prem["dock_door_annual"]["value"]
        drive_in_annual = prem["drive_in_door_annual"]["value"]

        height = prop.ind_clear_height_ft or 0
        if height > base_ft:
            # Capped so a high-bay building does not double-reward against the
            # big-box size tier (which already prices modern high-spec product).
            premium = min((height - base_ft) * per_ft, cap_pct)
            self.warehouse_rate = base_industrial_rate * (1 + premium)
        else:
            self.warehouse_rate = base_industrial_rate

        self.office_rate = prop.ind_office_rate if prop.ind_office_rate else (
            self.warehouse_rate * office_ratio)
        self.yard_rate   = prop.ind_yard_rate if prop.ind_yard_rate else (
            self.warehouse_rate * yard_ratio)

        total        = prop.total_sq_ft or 0
        office_sqft  = prop.ind_office_sqft  or 0
        yard_sqft    = prop.ind_yard_sqft    or 0
        wh_sqft      = prop.ind_warehouse_sqft or max(0, total - office_sqft)

        self.warehouse_sqft = wh_sqft
        self.office_sqft    = office_sqft
        self.yard_sqft      = yard_sqft
        self.dock_doors     = prop.ind_dock_doors or 0
        self.drive_in_doors = prop.ind_drive_in_doors or 0
        self.clear_height   = height

        # Any building-specific input means we can underwrite from details
        # rather than a flat market rate.
        self.is_detailed = bool(
            height or office_sqft or yard_sqft
            or self.dock_doors or self.drive_in_doors
            or (prop.ind_warehouse_sqft or 0)
        )

        self.warehouse_income = wh_sqft    * self.warehouse_rate
        self.office_income    = office_sqft * self.office_rate
        self.yard_income      = yard_sqft   * self.yard_rate
        self.door_income      = self.dock_doors * dock_annual + self.drive_in_doors * drive_in_annual
        self.total_income     = (self.warehouse_income + self.office_income
                                 + self.yard_income + self.door_income)

        covered_sqft      = wh_sqft + office_sqft
        self.blended_rate = (self.warehouse_income + self.office_income) / covered_sqft if covered_sqft else 0

    @property
    def income_breakdown(self) -> list:
        """Human-readable component lines for the rent breakdown."""
        lines = [
            f"Warehouse {self.warehouse_sqft:,.0f} sq ft @ ${self.warehouse_rate:.2f}/sq ft: ${self.warehouse_income:,.0f}/yr"
        ]
        if self.office_sqft:
            lines.append(
                f"Office {self.office_sqft:,.0f} sq ft @ ${self.office_rate:.2f}/sq ft: ${self.office_income:,.0f}/yr")
        if self.yard_sqft:
            lines.append(
                f"Yard {self.yard_sqft:,.0f} sq ft @ ${self.yard_rate:.2f}/sq ft: ${self.yard_income:,.0f}/yr")
        if self.door_income:
            lines.append(
                f"Doors ({self.dock_doors} dock + {self.drive_in_doors} drive-in): ${self.door_income:,.0f}/yr")
        lines.append(f"Total industrial income (from building details): ${self.total_income:,.0f}/yr")
        return lines

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
                                  f"{self.clear_height:.0f} ft", self._height_grade()))
        if self.dock_doors:
            rows.append(ReportRow("Dock Doors",
                                  f"{self.dock_doors}",
                                  "GOOD" if self.dock_doors >= 2 else "FAIR"))
        if self.drive_in_doors:
            rows.append(ReportRow("Drive-In Doors", f"{self.drive_in_doors}", ""))
        rows.append(ReportRow("Warehouse Sqft",
                               f"{self.warehouse_sqft:,.0f} sq ft @ ${self.warehouse_rate:.2f}/sq ft", ""))
        rows.append(ReportRow("Warehouse Income", f"${self.warehouse_income:,.0f}/yr", ""))
        if self.office_sqft:
            rows.append(ReportRow("Office Component",
                                  f"{self.office_sqft:,.0f} sq ft @ ${self.office_rate:.2f}/sq ft", ""))
            rows.append(ReportRow("Office Income", f"${self.office_income:,.0f}/yr", ""))
        if self.yard_sqft:
            rows.append(ReportRow("Yard/Storage",
                                  f"{self.yard_sqft:,.0f} sq ft @ ${self.yard_rate:.2f}/sq ft", ""))
            rows.append(ReportRow("Yard Income", f"${self.yard_income:,.0f}/yr", ""))
        if self.door_income:
            rows.append(ReportRow("Door Income",
                                  f"${self.door_income:,.0f}/yr "
                                  f"({self.dock_doors} dock + {self.drive_in_doors} drive-in)", ""))
        rows.append(ReportRow("Total Industrial Rev",
                               f"${self.total_income:,.0f}/yr",
                               "GOOD" if self.total_income > 0 else "POOR"))
        if self.blended_rate:
            rows.append(ReportRow("Blended Rate", f"${self.blended_rate:.2f}/sq ft/yr", ""))
        return rows
