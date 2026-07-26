#!/usr/bin/env python3
"""
Fetch + rebuild json/vacancy_rates.json from the CMHC Rental Market Survey (RMS).

The second of the two scripted fetches behind the regional vacancy pipeline
(analysis/vacancy_resolver.py). It pulls apartment (residential) vacancy by centre,
maps each surveyed centre to its StatCan CMA/CA code (via json/geographic_crosswalk.json,
so the resolver's join is code-to-code), and aggregates provincial + national averages
as the fallback tiers.

Refresh = re-run. Vacancy is published annually (October survey), so this runs more
often than the crosswalk fetch.

SOURCE — why StatCan, not cmhc-schl.gc.ca directly:
    CMHC publishes the RMS on its HMIP portal (www03.cmhc-schl.gc.ca), which blocks
    unauthenticated/programmatic access from many networks (HTTP 403), and there is no
    installable `cmhc` API wrapper on PyPI. The IDENTICAL CMHC series — same figures,
    source attributed to "Canada Mortgage and Housing Corporation" — is republished by
    Statistics Canada's Web Data Service (fully reachable) as tables:
        34-10-0127  vacancy rate, apartment 6+ units — major CMAs
        34-10-0128  vacancy rate, apartment 6+ units — mid-size centres
        34-10-0129  vacancy rate, apartment 6+ units — smaller centres/CAs
    Each row carries a DGUID whose trailing digits are the StatCan CMA/CA code, giving a
    code-to-code join to the crosswalk. This is the reachable channel for the real data.

    NOTE: StatCan's republication does NOT carry CMHC's per-figure a/b/c/d reliability
    letters (those live only on the HMIP portal). It carries StatCan's own quality flag
    (STATUS: 'E' use-with-caution, 'F' too-unreliable-so-suppressed). We record whatever
    quality flag is present; 'F'/suppressed rows have no value and are skipped.

Usage:
    python scripts/fetch_vacancy_rates.py                     # pull the latest survey
    python scripts/fetch_vacancy_rates.py --table rms.csv     # parse a manual RMS CSV export

Prerequisite: run scripts/fetch_geographic_crosswalk.py FIRST — the centre->CMA/CA code
mapping and province/name labels come from the crosswalk.

This script never fabricates figures and never clobbers the existing file on failure.
"""
import argparse
import csv
import io
import json
import os
import sys
import urllib.request
import zipfile
from datetime import date

CROSSWALK_PATH = os.path.join("json", "geographic_crosswalk.json")
OUT_PATH = os.path.join("json", "vacancy_rates.json")

# StatCan WDS product IDs carrying the CMHC RMS apartment (6+ units) vacancy series,
# CMA/CA level. Together they cover the surveyed centres across Canada.
WDS_PIDS = ("34100127", "34100128", "34100129")
WDS_CSV_META = "https://www150.statcan.gc.ca/t1/wds/rest/getFullTableDownloadCSV/{pid}/en"

SOURCE_NAME = ("Canada Mortgage and Housing Corporation, Rental Market Survey "
               "(republished via Statistics Canada WDS tables 34-10-0127/128/129)")
SOURCE_URL = "https://www150.statcan.gc.ca/t1/tbl/en/tv.action?pid=3410012701"

# StatCan data-quality symbol -> our reliability slot (lowercased). CMHC's own a/b/c/d
# letters are not present in this channel; only these StatCan flags are.
_STATUS_TO_RELIABILITY = {"E": "e"}   # 'F' rows are suppressed (no value) and never reach here

RELIABILITY_CODES = {
    "e": "StatCan 'use with caution' (higher sampling variability) - demoted to the parent tier",
    None: "no quality flag on the figure (StatCan channel does not carry CMHC's a/b/c/d letters)",
}

_USER_AGENT = "commercial-property-analyser/3.7 (vacancy fetch)"


def _get(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": _USER_AGENT}), timeout=90)


# ── Crosswalk (CMA/CA code -> province, name, level) ────────────────────────

def _load_crosswalk():
    if not os.path.exists(CROSSWALK_PATH):
        raise SystemExit(
            f"Crosswalk not found at {CROSSWALK_PATH}. Run "
            f"scripts/fetch_geographic_crosswalk.py first."
        )
    with open(CROSSWALK_PATH, encoding="utf-8") as f:
        return json.load(f).get("cma_ca", {})


def _dguid_code(dguid: str):
    """The CMA/CA SGC code is the digit tail of the DGUID, e.g.
    '2011S0503521' -> '521' (Kingston CMA), '2011S0504512' -> '512' (Brockville CA)."""
    tail = (dguid or "").strip()[9:]   # strip the 'YYYYS050X' vintage+schema prefix
    return tail if tail.isdigit() else None


def _province_from_geo(geo: str):
    """Fallback province parse from a 'Centre, Province' GEO label."""
    from_names = {
        "newfoundland and labrador": "NL", "prince edward island": "PE", "nova scotia": "NS",
        "new brunswick": "NB", "quebec": "QC", "ontario": "ON", "manitoba": "MB",
        "saskatchewan": "SK", "alberta": "AB", "british columbia": "BC", "yukon": "YT",
        "northwest territories": "NT", "nunavut": "NU",
    }
    tail = (geo or "").split(",")[-1].strip().lower()
    tail = tail.split("/")[0].strip().replace(" part", "")   # "Ontario/Quebec" / "Ontario part"
    return from_names.get(tail)


# ── Source: StatCan WDS (the real, reachable CMHC series) ────────────────────

def _load_wds_table(pid: str):
    meta = json.loads(_get(WDS_CSV_META.format(pid=pid)).read())
    zip_url = meta["object"]
    zf = zipfile.ZipFile(io.BytesIO(_get(zip_url).read()))
    name = max((n for n in zf.namelist() if n.lower().endswith(".csv") and "MetaData" not in n),
               key=lambda n: zf.getinfo(n).file_size)
    text = zf.read(name).decode("utf-8-sig", errors="replace")
    return list(csv.reader(io.StringIO(text)))


def fetch_via_wds(cma_ca: dict):
    """Return (records, reference_year). Each record:
    {code, name, province, geo_level, vacancy_rate, reliability, ref_date}."""
    best = {}   # code -> record (latest ref_date wins)
    max_year = None
    for pid in WDS_PIDS:
        print(f"  Pulling StatCan/CMHC table {pid} ...")
        rows = _load_wds_table(pid)
        h = rows[0]
        gi, ri, di = h.index("GEO"), h.index("REF_DATE"), h.index("DGUID")
        vi, si = h.index("VALUE"), (h.index("STATUS") if "STATUS" in h else None)
        for r in rows[1:]:
            if len(r) <= max(gi, ri, di, vi):
                continue
            code = _dguid_code(r[di])
            if not code:                      # aggregate rows ("Census metropolitan areas") have no DGUID
                continue
            # Keep only real CMA/CA codes present in the crosswalk. This drops the
            # province-part cuts of bi-provincial CMAs (e.g. Ottawa-Gatineau's ON/QC
            # parts carry 5-digit DGUID tails like 35505/24505) that can never join a
            # CSD and would otherwise pollute the provincial aggregation.
            if cma_ca and code not in cma_ca:
                continue
            val = r[vi].strip()
            if val in ("", ".."):             # suppressed / not available
                continue
            try:
                rate = round(float(val) / 100.0, 4)
            except ValueError:
                continue
            year = r[ri].strip()
            prev = best.get(code)
            if prev and prev["ref_date"] >= year:
                continue
            status = (r[si].strip() if si is not None and len(r) > si else "")
            blk = cma_ca.get(code, {})
            best[code] = {
                "code": code,
                "name": blk.get("name") or r[gi].split(",")[0].strip(),
                "province": blk.get("province") or _province_from_geo(r[gi]),
                "geo_level": blk.get("type") or "CMA",
                "vacancy_rate": rate,
                "reliability": _STATUS_TO_RELIABILITY.get(status),
                "ref_date": year,
            }
            if max_year is None or year > max_year:
                max_year = year
    return list(best.values()), max_year


# ── Source: a manually-downloaded RMS CSV (kept as a fallback) ───────────────

def fetch_via_table(path: str, cma_ca: dict):
    print(f"  Reading RMS data table {path} ...")
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    delim = ";" if text[:4096].count(";") > text[:4096].count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    name_to_code = {(_norm(b.get("name")), b.get("province")): c for c, b in cma_ca.items()}
    out = []
    for row in reader:
        low = {(k or "").strip().lower(): v for k, v in row.items()}
        centre = _first(low, "geography", "centre", "center", "geo", "name")
        prov = _prov_code(_first(low, "province", "prov"))
        rate = _to_fraction(_first(low, "total", "vacancy rate", "vacancy", "value"))
        rel = _rel_letter(_first(low, "reliability", "quality"))
        if not centre or rate is None:
            continue
        code = name_to_code.get((_norm(centre), prov))
        blk = cma_ca.get(code, {})
        out.append({"code": code, "name": centre, "province": prov or blk.get("province"),
                    "geo_level": blk.get("type") or "CMA", "vacancy_rate": rate,
                    "reliability": rel, "ref_date": ""})
    if not out:
        raise SystemExit("No usable rows parsed from the table.")
    return out, ""


def _norm(s):
    s = (s or "").strip().lower()
    return " ".join("".join(c for c in s if c.isalnum() or c.isspace()).split())


def _first(d, *keys):
    for k in keys:
        for kk, v in d.items():
            if (kk == k or kk.startswith(k)) and v not in (None, "", "..", "n/a"):
                return v
    return None


def _to_fraction(v):
    if v is None:
        return None
    try:
        x = float(str(v).replace("%", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None
    return round(x / 100.0 if x > 1.0 else x, 4)


def _prov_code(v):
    return _province_from_geo(f", {v}") if v else None


def _rel_letter(v):
    if not v:
        return None
    s = str(v).strip().lower()[:1]
    return s if s in ("a", "b", "c", "d", "e") else None


# ── Build ────────────────────────────────────────────────────────────────────

def build_vacancy(records, reference: str) -> dict:
    regions, prov_bucket = {}, {}
    for rec in records:
        if rec.get("code"):
            regions[rec["code"]] = {
                "vacancy_rate": rec["vacancy_rate"],
                "reliability": rec.get("reliability"),
                "geo_level": rec.get("geo_level", "CMA"),
                "name": rec.get("name"),
                "province": rec.get("province"),
                "ref_date": rec.get("ref_date"),
            }
        if rec.get("province"):
            prov_bucket.setdefault(rec["province"], []).append(rec["vacancy_rate"])

    # Provincial + national are AGGREGATES of the real surveyed centres (StatCan does not
    # publish a provincial CMHC-RMS cut). They are the UNWEIGHTED mean of the province's
    # surveyed centres: the RMS rental universe (unit count per centre) that a
    # population/stock-weighted mean would need is NOT published on the reachable StatCan
    # WDS channel (it lives only on CMHC's HMIP portal, which blocks access). So the mean
    # is unweighted and labeled as such, never mistaken for an official provincial figure.
    # Reported raw (tier 3 does not floor).
    provincial = {
        p: {"vacancy_rate": round(sum(v) / len(v), 4), "reliability": None,
            "note": f"unweighted mean of {len(v)} surveyed CMHC centre(s), {reference}"}
        for p, v in prov_bucket.items() if v
    }
    all_rates = [r["vacancy_rate"] for r in regions.values()]
    national = ({"vacancy_rate": round(sum(all_rates) / len(all_rates), 4),
                 "note": f"unweighted mean of {len(all_rates)} surveyed CMHC centres, {reference}"}
                if all_rates else {})

    ref_label = f"October {reference}" if reference and reference.isdigit() else (reference or "latest RMS")
    print(f"  Built {len(regions)} regions across {len(provincial)} provinces "
          f"(reference {ref_label}).")
    return {
        "_meta": {
            "description": "CMHC Rental Market Survey apartment (residential) vacancy by geography.",
            "source": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "reference_date": ref_label,
            "attribution": f"Adapted from Canada Mortgage and Housing Corporation, "
                           f"Rental Market Survey, {ref_label}.",
            "unit": "fraction (0.031 == 3.1%)",
            "reliability_codes": RELIABILITY_CODES,
            "last_updated": date.today().isoformat(),
            "status": "fetched",
            "reliability_note": "Regional figures come from StatCan's republication of the CMHC "
                                "series, which carries StatCan quality flags (E=use with caution, "
                                "F=suppressed) rather than CMHC's a/b/c/d letters.",
            "aggregate_note": "provincial/national are UNWEIGHTED means of surveyed centres, not "
                              "official CMHC provincial figures. Universe/unit-count weights are "
                              "not published on the reachable StatCan WDS channel, so a "
                              "stock-weighted provincial mean is not possible from this source.",
            "license_note": "CMHC data carries an attribution requirement: value-added products must "
                            "display the 'attribution' string wherever the figures surface.",
        },
        "regions": regions,
        "provincial": provincial,
        "national": national,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Rebuild json/vacancy_rates.json from the CMHC RMS.")
    ap.add_argument("--table", help="Path to a manually-downloaded RMS data-table CSV (bypasses WDS).")
    args = ap.parse_args()

    cma_ca = _load_crosswalk()
    if not cma_ca:
        print("  WARNING: crosswalk has no CMA/CA entries — run "
              "scripts/fetch_geographic_crosswalk.py first.", file=sys.stderr)

    try:
        if args.table:
            records, reference = fetch_via_table(args.table, cma_ca)
        else:
            records, reference = fetch_via_wds(cma_ca)
    except SystemExit:
        raise
    except Exception as e:
        print(f"  ERROR fetching CMHC RMS vacancy: {e}", file=sys.stderr)
        print("  The existing json/vacancy_rates.json was left untouched.", file=sys.stderr)
        return 1

    matched = sum(1 for r in records if r.get("code"))
    if not matched:
        print("  ERROR: no surveyed centre matched a crosswalk CMA/CA code — nothing written.",
              file=sys.stderr)
        return 1

    data = build_vacancy(records, reference)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT_PATH)
    print(f"  Wrote {OUT_PATH} ({len(data['regions'])} regions). Re-analyze to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
