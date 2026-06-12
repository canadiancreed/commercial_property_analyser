import re as _re


def _display_address(address: str) -> str:
    """Strip trailing province code from address for display (e.g. ', ON' or ' ON')."""
    return _re.sub(r",?\s+[A-Z]{2}\s*$", "", (address or "").strip())


def _parse_address_sort(address: str):
    """Returns (street_name, street_number) for sorting. Handles '123 Main St' and '123-45 Main St'."""
    addr = (address or "").strip()
    addr = addr.split(",")[0].strip()
    STREET_NORM = [
        (r"\bst\.?$",   "street"),
        (r"\bave?\.?$", "avenue"),
        (r"\bdr\.?$",   "drive"),
        (r"\brd\.?$",   "road"),
        (r"\bblvd\.?$", "boulevard"),
        (r"\bln\.?$",   "lane"),
        (r"\bcr?t\.?$", "court"),
        (r"\bpl\.?$",   "place"),
        (r"\bpkwy\.?$", "parkway"),
        (r"\bhwy\.?$",  "highway"),
    ]
    m = _re.match(r"^([\d\-]+)\s+(.*)", addr)
    if m:
        num_str = _re.sub(r"[^0-9]", "", m.group(1).split("-")[0])
        num     = int(num_str) if num_str else 0
        name    = m.group(2).lower().strip()
    else:
        num  = 0
        name = addr.lower().strip()
    for pattern, replacement in STREET_NORM:
        name = _re.sub(pattern, replacement, name, flags=_re.IGNORECASE)
    return name, num
