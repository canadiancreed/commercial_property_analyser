# Regional Vacancy Pipeline (3.7)

Replaces the flat, type-keyed vacancy constant with a **region-keyed lookup** resolved
by an always-terminating 4-tier fallback chain. Sourced entirely from two scripted,
versioned downloads — no hand-entry, refresh = re-run.

## Why

Vacancy nets out of EGI, and expenses are a ratio of EGI, so a single national constant
(e.g. 3% for every residential deal) silently mis-states NOI, cap rate, cash flow, DSCR
and the score. Underwriting Kingston (tight market) and a high-vacancy small town at the
same 3% is wrong in opposite directions. This keys vacancy to the property's actual
region.

## Sources

| File | Source | Rebuilt by | Cadence |
|---|---|---|---|
| `json/vacancy_rates.json` | CMHC Rental Market Survey (apartment/residential vacancy), keyed by StatCan CMA/CA code, + provincial/national aggregates | `scripts/fetch_vacancy_rates.py` | annual (October survey) |
| `json/geographic_crosswalk.json` | StatCan Geographic Attribute File (Catalogue 92-151-X): CSD → CMA/CA → province, numeric codes + a normalized name index | `scripts/fetch_geographic_crosswalk.py` | per census |

**Why the vacancy fetch pulls from StatCan, not cmhc-schl.gc.ca:** CMHC's HMIP portal
(`www03.cmhc-schl.gc.ca`) blocks programmatic access (HTTP 403), and there is no
installable `cmhc` API wrapper on PyPI. The **identical CMHC RMS series** — attributed to
"Canada Mortgage and Housing Corporation" — is republished by Statistics Canada's Web Data
Service (fully reachable) as tables **34-10-0127 / 128 / 129** (apartment 6+ units, by
CMA/CA), each row carrying a `DGUID` whose trailing digits are the CMA/CA code. That is the
reachable channel for the real figures. Two consequences, both handled honestly:
- **Reliability:** the StatCan channel carries StatCan's quality flag (`E` use-with-caution,
  `F` suppressed) — **not** CMHC's a/b/c/d letters, which live only on the 403'ing portal.
  The resolver demotes on `e`/`d`; suppressed (`F`) rows have no value and are skipped.
- **Provincial/national:** StatCan publishes no provincial CMHC-RMS cut, so those tiers are
  the **unweighted mean of the surveyed centres** in each province (labeled as such in
  `_meta` and inline on the report row), reported raw at tier 3. A stock-weighted mean
  would be preferable (it would stop small towns from padding a province held mostly by one
  tight metro), but the **RMS rental universe (unit count per centre) is not published on
  the reachable WDS channel** — it lives only on the 403'ing HMIP portal — so weighting is
  not possible from this source. This is a known limitation, not an oversight.

## The join

```
deal city + province  →  CSD code  →  (CMA/CA code, province)  →  vacancy
                      ↑ name_index (crosswalk)     ↑ csd[code].cma_ca_code   ↑ regions[code]
```

Only the first hop is name-based (deal data carries no codes); the crosswalk's
`name_index` maps a normalized `city|PROV` key to a CSD code. Everything after is
code-to-code.

## Fallback chain (first hit wins)

| Tier | Condition | Value | Stamp | Normal? |
|---|---|---|---|---|
| 1 | CSD maps to a directly-surveyed CMHC region | that region's vacancy | `region` | yes |
| 2 | CSD sits in a surveyed CMA/CA (not surveyed alone) | parent CMA/CA vacancy | `parent_cma` | yes |
| 3 | outside any surveyed region | provincial average (raw) | `provincial_avg` | yes |
| 4 | nothing resolved (province unknown) | `max(type constant, national)` | `constant_floor` | **no — alarm** |

- **Conservative floor** — **only tier 4** (the genuine no-real-data / pipeline-break
  case) floors at `max(type constant, national)`. Tiers 1-3 report their real CMHC
  figure raw, including a provincial average below the 3% constant — that is real data,
  not a gap. Flooring tier 3 would overwrite genuine sub-constant provinces (national
  purpose-built vacancy ran 1.5–2.2% in 2023–24; BC ~1.9%) with the stale default,
  re-creating the blanket constant this pipeline exists to remove.
- **Reliability** — a quality flag is carried through to the record and report; a poor
  flag is demoted to the next tier (`demote_unreliable`, default on), and the demotion is
  **recorded, not silent**: the skipped figure and its grade are kept in `demoted_from`
  (e.g. `Kingston CMA (rel. d)`), persisted to the record (`vacancy_demoted_from`),
  appended to the Vacancy Rate row, and broken out as their own line in the batch
  source-mix — so a demoted deal is never mistaken for a genuine no-regional-data one.

  **Which alphabet, and whether it has fired:** CMHC's own a/b/c/d letters live only on
  the HMIP portal (which 403s). The reachable StatCan WDS republication carries StatCan's
  quality flags instead — `E` (use with caution) and `F` (too unreliable → value
  suppressed). The resolver demotes on `d`/`e`; `F` rows have no value and are skipped
  upstream. **In the current live October-2025 data, no surveyed region carries a
  flagged-with-value code, so demotion has not fired in production** — the feature is
  fully unit-tested (synthetic `d`/`e` fixtures) but is, so far, a latent safeguard on
  live data.

  > **Reliability** here means the published statistical-quality grade on a single Rental
  > Market Survey vacancy figure (CMHC's a/b/c/d on HMIP, StatCan's E/F on the WDS channel
  > this pipeline uses); it applies to CMHC RMS regional vacancy numbers only — a
  > caution-grade figure is skipped for the next fallback tier and the skip is recorded —
  > and it does not touch listing data, prices, rents, the income estimate, or any
  > user/source-entered field. It is confidence in a measured government statistic, not a
  > judgment about data we entered.
- **Tier-4 tripwire** — every property has a province, so tier 3 always resolves in
  healthy operation. A tier-4 hit (`normal=False`) means the fetch/join broke that run;
  the batch re-analysis counts and surfaces it. Not a path — an alarm.

## Type awareness

CMHC RMS measures **residential** vacancy only. So:

- **Residential** asset classes (multi-family, residential, and the residential
  component of mixed-use) walk tiers 1-4 against the survey.
- **Commercial** classes (office/retail/industrial/hotel/…) have no regional survey
  wired in this version. They resolve to their per-type `VACANCY_RATE_DEFAULTS` constant
  (office 14%, retail 5%, …) through the *same* resolver under a distinct `type_default`
  stamp — an expected baseline, `normal=True`, never an alarm. Commercial numbers do not
  regress. A future commercial regional feed slots into tiers 1-3 for these types with
  no resolver change.

## Refresh workflow

```bash
python scripts/fetch_geographic_crosswalk.py   # StatCan crosswalk (run first)
python scripts/fetch_vacancy_rates.py          # CMHC RMS vacancy (needs the crosswalk)
```

Then re-analyze (menu `r`) to persist the new rates + source stamps into stored records.
The committed files hold a real fetch (October 2025: 5,161 CSDs / 153 CMA-CAs in the
crosswalk; 140 surveyed regions across 11 provinces in the vacancy file). If a fetch ever
can't reach a source it leaves the existing file untouched rather than writing a partial —
so the resolver always has a complete file to read.

## License

CMHC data carries an attribution requirement. Wherever RMS vacancy figures surface (the
property report footer, the vacancy-sensitivity report), the products display:

> Adapted from Canada Mortgage and Housing Corporation, Rental Market Survey, &lt;reference date&gt;.

## Key code

- `analysis/vacancy_resolver.py` — `resolve_vacancy(city, province, property_type) → VacancyResolution`
- `analysis/analyzer.py` — `_resolve_vacancy_rate()` (returns the resolution); record fields `vacancy_source`, `vacancy_reliability`, `vacancy_region`, `vacancy_tier`, `vacancy_normal`
- `ui/menu.py` — `_report_vacancy_sources()` (source mix + tier-4 alarm count)
- `analysis/metrics/income.py` — the Vacancy Rate row embeds the provenance
