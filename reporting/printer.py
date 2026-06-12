from core.address import _display_address, _parse_address_sort
from analysis.metrics.income import INCOME_METRIC_NAMES


class ReportPrinter:

    DIVIDER = "-" * 75

    @classmethod
    def print_report(cls, analyzer, show: bool = True):
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
    def list_properties(cls, store):
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
            addr     = _display_address(p.get("address") or "")[:col_addr] or "—"
            mls      = (p.get("mls_number") or "—")[:col_mls]
            status   = (p.get("status") or "—")[:col_status]
            price    = f"${p.get('asking_price', 0):,.0f}"
            sqft     = f"{p.get('total_sq_ft', 0):,.0f}"
            ptype    = (p.get("property_type") or "Residential")[:col_type]
            listed   = p.get("listing_date", "—")
            analyzed = p.get("analyzed_on") or "—"
            has_analysis = any(r.get("metric") in INCOME_METRIC_NAMES for r in (p.get("results") or []))
            ana_flag = "✓" if has_analysis else "—"
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
