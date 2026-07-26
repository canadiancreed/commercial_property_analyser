#!/usr/bin/env python3
"""
Fetch + rebuild json/geographic_crosswalk.json from the StatCan Geographic
Attribute File (2021 Census, Catalogue 92-151-X).

This is one of the two scripted fetches behind the regional vacancy pipeline
(analysis/vacancy_resolver.py). It downloads the versioned StatCan file, extracts
every Census Subdivision (CSD = municipality), and records for each: its name, its
parent Census Metropolitan Area / Census Agglomeration (CMA/CA) code + name, and
its province. It also builds a normalized name index so the deal-data city+province
can be resolved to a CSD code (the one unavoidable name-based hop; everything after
is code-to-code).

Refresh = re-run. No hand-editing. The crosswalk is versioned by census, so this
only changes when StatCan publishes a new census vintage.

    python scripts/fetch_geographic_crosswalk.py

Network: reachable from a normal machine (the file is public open data, ~10 MB zip).
Stdlib only — no third-party dependencies.
"""
import csv
import io
import json
import os
import sys
import urllib.request
import zipfile
from datetime import date

# StatCan 2021 Census Geographic Attribute File (92-151-X), English CSV in a zip.
SOURCE_URL = ("https://www12.statcan.gc.ca/census-recensement/2021/geo/aip-pia/"
              "attribute-attribs/files-fichiers/2021_92-151_X.zip")
SOURCE_NAME = "Statistics Canada, 2021 Census - Geographic Attribute File (Catalogue 92-151-X)"
SOURCE_PAGE = ("https://www12.statcan.gc.ca/census-recensement/2021/geo/aip-pia/"
               "attribute-attribs/index-eng.cfm")
CENSUS_YEAR = 2021

OUT_PATH = os.path.join("json", "geographic_crosswalk.json")

# Standard Geographical Classification province/territory codes (PRUID) -> 2-letter.
# Factual, stable codes; the 2-letter form is what the deal data + resolver use.
PROVINCE_CODES = {
    "10": "NL", "11": "PE", "12": "NS", "13": "NB", "24": "QC", "35": "ON",
    "46": "MB", "47": "SK", "48": "AB", "59": "BC", "60": "YT", "61": "NT", "62": "NU",
}

# CMHC RMS surveys apartment vacancy at the CMA/CA level, so the crosswalk only needs
# CSD -> CMA/CA containment. CMAUID 996/997/998/999 are NOT real CMA/CAs — they are the
# "metropolitan influenced zone" categories (strong/moderate/weak/none) shared across
# provinces for CSDs that sit outside every CMA/CA. A CSD carrying one of these has no
# parent CMA/CA (it resolves to the provincial tier), and the codes must never be stored
# as regions (their names are province-specific text on a shared code).
NON_CMA_CODES = {"996", "997", "998", "999"}


def _clean_cma_name(name: str) -> str:
    """Trim StatCan's part-qualifier parentheticals so split CMAs read cleanly, e.g.
    'Ottawa - Gatineau (Ontario part / partie de l'Ontario)' -> 'Ottawa - Gatineau'."""
    n = (name or "").strip()
    return n.split(" (", 1)[0].strip() if " (" in n else n

_USER_AGENT = "commercial-property-analyser/3.7 (crosswalk fetch)"


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    print(f"  Downloading {url} ...")
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    print(f"  Got {len(data):,} bytes.")
    return data


def _open_csv(zip_bytes: bytes):
    """Yield decoded text lines from the (single) CSV inside the StatCan zip."""
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    if not csv_names:
        raise SystemExit(f"No CSV found in the StatCan zip (members: {zf.namelist()})")
    # The attribute file is the largest CSV member.
    name = max(csv_names, key=lambda n: zf.getinfo(n).file_size)
    print(f"  Reading {name} ...")
    raw = zf.read(name)
    # StatCan files are usually latin-1/cp1252; fall back if utf-8 fails.
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _find_col(header: list, *prefixes: str):
    """Locate a column by case-insensitive prefix. StatCan headers carry bilingual
    suffixes (e.g. CSDNAME_CSDNOM), so prefix-matching is the robust approach."""
    low = [h.strip().lower() for h in header]
    for pfx in prefixes:
        p = pfx.lower()
        for i, h in enumerate(low):
            if h == p or h.startswith(p):
                return i
    return None


def build_crosswalk(csv_text: str) -> dict:
    # Detect delimiter (StatCan uses ',' or ';').
    sample = csv_text[:4096]
    delim = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(csv_text), delimiter=delim)
    header = next(reader)

    idx = {
        "csduid":  _find_col(header, "CSDUID", "CSDIDU"),
        "csdname": _find_col(header, "CSDNAME", "CSDNOM"),
        "cmauid":  _find_col(header, "CMAUID", "CMAIDU"),
        "cmaname": _find_col(header, "CMANAME", "CMANOM"),
        "cmatype": _find_col(header, "CMATYPE"),
        "pruid":   _find_col(header, "PRUID", "PRIDU"),
    }
    missing = [k for k, v in idx.items() if v is None and k in ("csduid", "csdname", "pruid")]
    if missing:
        raise SystemExit(
            f"Could not locate required column(s) {missing} in the attribute file.\n"
            f"Header was: {header}"
        )

    csd, cma_ca, name_index = {}, {}, {}
    seen_csd = set()
    rows = 0
    for row in reader:
        rows += 1
        if not row or idx["csduid"] >= len(row):
            continue
        csduid = (row[idx["csduid"]] or "").strip()
        if not csduid or csduid in seen_csd:
            continue
        seen_csd.add(csduid)

        csdname = (row[idx["csdname"]] or "").strip()
        pruid = (row[idx["pruid"]] or "").strip()
        prov = PROVINCE_CODES.get(pruid, pruid)

        cmauid = (row[idx["cmauid"]] or "").strip() if idx["cmauid"] is not None else ""
        cmaname = (row[idx["cmaname"]] or "").strip() if idx["cmaname"] is not None else ""
        cmatype = (row[idx["cmatype"]] or "").strip().upper() if idx["cmatype"] is not None else ""
        parent = None
        if cmauid and cmauid not in NON_CMA_CODES:
            parent = cmauid
            if cmauid not in cma_ca:
                cma_ca[cmauid] = {
                    "name": _clean_cma_name(cmaname) or cmauid,
                    "type": "CMA" if cmatype == "B" else "CA",
                    "province": prov,
                }

        csd[csduid] = {"name": csdname, "cma_ca_code": parent, "province": prov}

        key = f"{_normalize_name(csdname)}|{prov}"
        # First writer wins; a name collision within a province is rare and the
        # resolver's downstream tiers still terminate safely.
        name_index.setdefault(key, csduid)

    print(f"  Parsed {rows:,} rows -> {len(csd):,} CSDs, {len(cma_ca):,} CMA/CAs.")
    return {
        "_meta": {
            "description": "CSD (municipality) -> CMA/CA -> province crosswalk. Powers tiers "
                           "2-3 of the regional vacancy fallback chain (analysis/vacancy_resolver.py).",
            "source": SOURCE_NAME,
            "source_url": SOURCE_PAGE,
            "download_url": SOURCE_URL,
            "census_year": CENSUS_YEAR,
            "last_updated": date.today().isoformat(),
            "status": "fetched",
            "join": "deal city+province -> name_index -> csd_code -> csd[csd_code].cma_ca_code "
                    "-> vacancy_rates.regions[cma_ca_code]. Only the first hop is name-based.",
        },
        "province_codes": PROVINCE_CODES,
        "cma_ca": cma_ca,
        "csd": csd,
        "name_index": name_index,
    }


def _normalize_name(city: str) -> str:
    """Must match analysis/vacancy_resolver._normalize_name: lowercase, punctuation
    dropped, whitespace collapsed."""
    s = (city or "").strip().lower()
    keep = [ch for ch in s if ch.isalnum() or ch.isspace()]
    return " ".join("".join(keep).split())


def main() -> int:
    try:
        zip_bytes = _download(SOURCE_URL)
    except Exception as e:  # network/URL issues — surface clearly, don't clobber the seed.
        print(f"  ERROR downloading the StatCan attribute file: {e}", file=sys.stderr)
        print("  The existing json/geographic_crosswalk.json was left untouched.", file=sys.stderr)
        return 1
    data = build_crosswalk(_open_csv(zip_bytes))
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT_PATH)
    print(f"  Wrote {OUT_PATH} ({len(data['csd']):,} CSDs).")
    print("  Next: run scripts/fetch_vacancy_rates.py to populate the vacancy figures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
