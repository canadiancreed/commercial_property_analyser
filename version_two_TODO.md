# Version 2 TODO — Full Findings & Recommendations

> **Origin:** Produced from a full codebase review on 2026-06-10/11 (all 642 tests passing,
> 99% branch coverage at time of review, 476 records in `properties.json`).
>
> **Audience:** This document is written to be fed to an AI assistant (or developer) one item
> at a time to implement fixes. Each item is self-contained: it explains what the code does
> today, exactly where the problem lives, how it manifests, why it matters, and the
> recommended direction. Items marked **[VERIFIED]** were reproduced by actually executing
> the code during the review — they are not speculative.
>
> **Ground rules for whoever implements these:**
> - **The SQLite migration (Section G) is the #1 priority** (changed 2026-06-11): the
>   single-file rewrite pattern exposes all 476 records to total corruption on any crash
>   mid-write. Bugs 1–3 (data-corrupting at the value level) follow immediately after.
> - Several existing tests assert the *buggy* behaviour (called out explicitly below).
>   Those tests must be updated alongside the fix — a failing test after one of these fixes
>   may be the test being wrong, not the fix.
> - Run `python -m pytest` after every change; coverage is enforced at 90% minimum via
>   `.coveragerc`.

---

## SECTION A — DATA-CORRUPTING BUGS (fix first)

### A1. ✅ DONE (2026-06-11) — [VERIFIED] Retail-Office properties lose their floor count on re-analysis, silently inflating rent and permanently destroying the stored floors value

> **Status: fixed 2026-06-11, verified 2026-06-12.** All four legs patched:
> `_record_to_prop` now always builds a `UnitMix` (floors preserved in the no-units
> branch, `ui/menu.py` ~903); the `getattr(prop, "floors", 1)` hack is removed from the
> resolver (`analysis/rent_resolver.py` ~116); `to_record()` falls back to the *existing*
> record's floors instead of stomping 1 (`analysis/analyzer.py` ~152–154); CSV import
> builds `UnitMix(floors=...)` for unit-less properties (`ui/csv_handler.py` ~204).
> Regression tests: `tests/test_retail_office_floor_loss.py`,
> `tests/test_floor_preservation_all_types.py`. Data repair: see
> `find_affected_floor_loss.py` for auditing records already overwritten to floors=1.
> Full suite green (747 passed, 98.8% coverage).
>
> **Spun off for separate diagnosis:** the related observation that a saved
> `commercial_rent` short-circuits re-resolution (rent_resolver.py ~35), freezing rents
> against market-rate updates — same ratchet family as A3/B3, tracked outside this item.

**Files involved:**
- `ui/menu.py` — `PropertyMenu._record_to_prop()` (~line 888–940)
- `analysis/rent_resolver.py` — the `retail-office` branch (~line 115–140)
- `models/property_input.py` — `PropertyInput` dataclass (has **no** `floors` field)
- `analysis/analyzer.py` — `to_record()` (~line 152–154, where `floors` is re-serialized)

**What happens today, step by step:**

1. When a user adds a Retail-Office property through the interactive menu
   (`_prompt_property`), the floor count is stored inside a `UnitMix` object even when
   there are zero residential units — see `ui/menu.py` ~line 866:
   `elif property_type_raw.strip().lower() == "retail-office": unit_mix = UnitMix(floors=floors)`.
   This is the *only* place a floors-only `UnitMix` is created.

2. The rent resolver's retail-office branch (`analysis/rent_resolver.py` ~line 115) computes
   `floor_sq_ft = prop.total_sq_ft / floors`, prices the **ground floor at the Retail rate**
   and the **upper floors at the Office rate**. The floors value comes from
   `prop.unit_mix.floors if prop.unit_mix else getattr(prop, "floors", 1)`. Note the
   `getattr` fallback: `PropertyInput` has **no** `floors` attribute, so the fallback is
   always 1.

3. `CommercialPropertyAnalyzer.to_record()` saves `floors` into the record both as a
   top-level `"floors"` key and inside the `"unit_mix"` dict. So far so good — the saved
   JSON contains the correct floor count.

4. **The bug:** when any re-analysis path runs — menu option 4 (edit), option 7 (commercial
   rate edit triggers `_reanalyze_city`), option r (re-analyze all) — the saved record is
   converted back to a `PropertyInput` via `PropertyMenu._record_to_prop()`. That method
   contains:
   ```python
   has_units = any(um_data.get(k, 0) for k in ("bachelor","one_br",...))
   unit_mix  = UnitMix(...) if has_units else None
   ```
   A retail-office property has zero residential units, so `has_units` is `False`,
   `unit_mix` becomes `None`, and the floors value stored in the record is **never read**.
   The resolver then falls into the `getattr(prop, "floors", 1)` fallback → floors = 1.

5. With floors = 1, the resolver prices the **entire building at the Retail rate** (the
   ground-floor branch gets all the square footage; the office-floors branch computes 0
   floors). Then `to_record()` runs again and writes `floors: 1` back to disk, **destroying
   the original floor count permanently**. Every subsequent analysis is wrong forever, and
   there is no warning anywhere.

**Verified reproduction (executed during review):** a 3-floor, 9,000 sqft Retail-Office
with Retail @ $25/sqft and Office @ $18/sqft should resolve to
`25×3,000 + 18×6,000 = $183,000/yr`. After one `_record_to_prop` round-trip it resolved to
`$225,000/yr` (all 9,000 sqft at the Retail rate), with the breakdown line
`"Ground floor Retail (9,000 sq ft @ $25.0/sq ft)"`. The returned `prop.unit_mix` was `None`.

**Why this matters:** rent is the root input to nearly every downstream metric (NOI, cap
rate, DSCR, CoCR, IRR, equity multiple, score, city ranking). A ~23% rent overstatement on
this example flows through the entire report and makes a bad deal look good. Because the
corruption writes back to disk, even fixing the code later does not recover the lost floor
counts — affected records must be re-entered or restored from backup.

**Recommended fix direction (choose one, the first is cleaner):**
- **Option 1 (preferred):** add a first-class `floors: int = 1` field to `PropertyInput`,
  populate it everywhere (`_prompt_property`, `_record_to_prop`, CSV import), have the
  resolver read `prop.floors` when `unit_mix` is None, and keep `unit_mix.floors` only for
  genuinely mixed residential buildings. Remove the `getattr(prop, "floors", 1)` hack.
- **Option 2 (smaller diff):** in `_record_to_prop`, construct a `UnitMix(floors=...)` even
  when there are no residential units, whenever the stored `floors`/`unit_mix.floors` value
  is > 1 or the property type is retail-office/mixed-use. This mirrors what
  `_prompt_property` already does.
- Either way, add a **data-repair consideration**: floor counts already overwritten to 1
  cannot be recovered programmatically; at minimum log/flag retail-office records with
  `floors == 1` so the user can review them.

**Tests to add:** a parametrized round-trip idempotency test (see Section D, item D1) would
have caught this; specifically assert that for a retail-office record with `floors: 3`,
`_record_to_prop(record)` preserves the floor count and a second analysis produces the same
rent as the first.

---

### A2. [VERIFIED] Zero-filled rate placeholders permanently disable the missing-rate detection workflow

**Files involved:**
- `data/store.py` — `DataStore.ensure_city_in_rates()` (~line 176–223)
- `ui/menu.py` — `PropertyMenu._scan_existing_cities()` (~line 51–56, called from `__init__`)
- `analysis/rent_resolver.py` — every `if rate is None:` / `if comm_rate is None:` check
  (~lines 94–99, 121–127, 143–151) and `_resolve_residential` (~line 164)
- `data/store.py` — `CommercialRentLoader.get_rent_per_sqft()` (~line 285–292)

**What happens today, step by step:**

1. `ensure_city_in_rates(city, province)` is designed to register cities that lack rent
   data. It inserts **zero-valued placeholder entries** into both rate files:
   `{"Office": 0, "Retail": 0, "Industrial": 0, "Mixed-Use": 0}` into
   `commercial_rents.json` and an all-zero unit dict into `residential_rents.json`, and
   records the city in `missing_rent_data.json`.

2. `PropertyMenu.__init__` calls `_scan_existing_cities()`, which runs
   `ensure_city_in_rates` for the city of **every saved property**. So after the menu has
   been opened once, every city that any property references has zero-filled entries in
   both rate files.

3. The rent resolver's missing-data detection is `None`-based:
   `rate = self._commercial.get_rent_per_sqft(...); if rate is None: ...`. The loader
   returns `index[city_key][type_key]`, which for a placeholder city is `0` — **not
   `None`**. Therefore:
   - The "missing rate" branches never execute.
   - `_log_missing` is never called, so `missing_cities.json` is never updated.
   - The `ValueError("No commercial rate for {city}... Use menu option 7 to add rates.")`
     that drives the user-guidance workflow is never raised.
   - Rent silently resolves to **$0/yr**, the analyzer takes the no-rent path, and the
     property is saved with partial results and no actionable message.

**Verified reproduction (executed during review):** with a mocked loader returning `0`
(simulating a placeholder entry), `resolver.resolve()` returned rent `0.0`, the breakdown
read `"Office @ $0/sq ft × 5,000 sq ft"`, and `store.log_missing_city` was never called.

**Why this matters:** the README describes a core workflow — add a property, get told which
rates are missing, add them via menu options 7/8, automatic re-analysis. That workflow
functions only on the very first encounter with a city (before `ensure_city_in_rates`
runs). Afterwards the system's primary feedback loop is dead: users see `$0/sq ft`
breakdowns or silent partial analyses with no pointer to the cause. There are also now
**two parallel "missing data" registries** (`missing_cities.json` written by
`_log_missing`, and `missing_rent_data.json` written by `ensure_city_in_rates`) that can
disagree — see structural item F4.

**Recommended fix direction (pick one consistently):**
- **Option 1 (preferred, smallest blast radius):** treat zero as missing at the resolver
  boundary. Change every `if rate is None:` to `if not rate:` (and equivalently in
  `_resolve_residential`, skip unit rates that are falsy and exclude zeros from the
  `city_avg_rate` computation — note `known_rates` currently includes `0` values, dragging
  the average down). This makes placeholders behave identically to absent entries.
- **Option 2:** stop writing zero placeholders entirely — `ensure_city_in_rates` records
  the city in the missing registry but does not touch the rate files. This is cleaner
  long-term but changes the rate-editor UX (cities won't pre-appear in the option 7/8
  listings), so the editors would need to also list cities from the missing registry.
- In both options: audit existing rate files for placeholder zeros and ensure the rate
  editors don't interpret a deliberate `0` rate as "skip" vs "free" — decide and document
  whether a true $0 rate is ever legitimate (recommendation: it is not; use absence).

**Tests to add:** cross-layer test — call `ensure_city_in_rates` on a real temp
`DataStore`, then resolve a property in that city through a real
`CommercialRentLoader`/`ResidentialRentLoader`, and assert the missing-rate `ValueError`
fires and `missing_cities.json` is updated (this is Section D, item D3).

---

### A3. [VERIFIED] Resolved NOI growth rate is persisted into the override field, freezing it as a fake "manual override" after one analysis round-trip

**Files involved:**
- `analysis/analyzer.py` — `_resolve_noi_growth()` (~line 17–43) and `to_record()`
  (~line 167: `"noi_growth_rate": self._noi_growth_rate if self._has_rent else p.noi_growth_rate`)
- `ui/menu.py` — `_record_to_prop()` (~line 939: `noi_growth_rate = p.get("noi_growth_rate")`)
- `tests/test_analysis_analyzer.py` — `test_to_record_saves_resolved_growth_when_prop_has_none`
  (~line 134) **asserts the buggy behaviour and must be rewritten with the fix**
- `tests/test_reanalysis_stale_residential.py` — `test_reanalysis_is_idempotent` passes today
  partly *because* of this freezing; re-check after fix.

**What happens today, step by step:**

1. `PropertyInput.noi_growth_rate` is documented as `None = resolve from city demographics`.
   `_resolve_noi_growth` implements a priority chain:
   explicit value on the prop → `"manual override"`;
   else city entry in `json/city_demographics.json` → `"{City} demographics ({date})"`
   (with a `"DATA MAY BE STALE"` suffix when the file's `_meta.last_updated` is older than
   `refresh_years`); else 2% default → `"default (no locale data)"`.

2. `to_record()` saves the **resolved** rate into the record's `noi_growth_rate` key —
   the same key that means "user override" on input.

3. On any re-analysis, `_record_to_prop` reads that key and sets it on the new
   `PropertyInput`. Because it is now non-None, `_resolve_noi_growth` short-circuits at the
   first priority: the value is treated as a **manual override**.

**Verified reproduction (executed during review):** an Ottawa property analyzed once showed
source label `"Ottawa demographics (2026-06-07)"` and saved `noi_growth_rate = 0.0172`.
After a single `_record_to_prop` round-trip, the source label became `"manual override"`.

**Consequences (all confirmed by code reading):**
1. **Demographics updates never propagate.** Updating `city_demographics.json` (menu
   option s → m) and running "Re-analyze all" changes nothing for the 476 already-analyzed
   properties — each one carries its frozen rate forward forever.
2. **The report lies.** The "NOI Growth Assumption" row displays
   `({source})` — after one round-trip every property claims "manual override" even though
   the user never set anything.
3. **The staleness-warning feature is dead code in practice.** The
   `"DATA MAY BE STALE — refresh demographics"` warning (built in `_resolve_noi_growth` and
   surfaced in `ReturnMetrics.rows()`) can only ever fire on a property's *first* analysis,
   because every subsequent analysis sees a "manual override" and never consults the
   demographics file or its `_meta` freshness data.
4. **True manual overrides are indistinguishable from frozen resolved values** in the
   stored data, so a migration/repair cannot tell them apart reliably (best heuristic:
   values equal to a city's historical resolved rate were probably frozen, not manual).

**Recommended fix direction:**
- Persist the resolved value under a **separate key**, e.g.
  `"noi_growth_rate_resolved"` (for display/reproducibility) plus
  `"noi_growth_source"` (the label), and reserve `"noi_growth_rate"` strictly for genuine
  user overrides (`None` when the user never set one). `_record_to_prop` must pass through
  only the override key.
- Update the report row to use the freshly-resolved source each analysis.
- Rewrite `test_to_record_saves_resolved_growth_when_prop_has_none` to assert the new
  contract (resolved value saved under the new key; override key stays `None`).
- Add a regression test: analyze → `to_record` → `_record_to_prop` → re-analyze with a
  *changed* demographics file → assert the new growth rate is picked up and the source
  label still names demographics, not "manual override".
- **Same pattern applies to `vacancy_rate`** — see A6; fix them together with one design.

---

## SECTION B — FUNCTIONAL BUGS

### B1. CSV import silently discards the Hotel property type (and hotel analysis can never run from CSV)

**File:** `ui/csv_handler.py` (~line 95):
```python
COMMERCIAL_TYPES = {"office", "retail", "industrial", "mixed-use", "retail-office"}
```
This is a **local** set that shadows the intent of `models/constants.py`'s
`COMMERCIAL_TYPES`, which **includes `"Hotel"`**. The import flow does:
```python
is_commercial   = property_type_raw.strip().lower() in COMMERCIAL_TYPES
prop_type_field = property_type_raw if is_commercial else None
```

**Effect for a CSV row with `property_type = Hotel`:**
1. `is_commercial` is `False`, so `prop_type_field` becomes `None` — **the type is erased**.
2. The `PropertyInput` is built with `property_type=None`, so the resolver's hotel branch
   (`if ptype == "hotel":`) never fires, even when the CSV's `hotel_rooms`, `hotel_adr`,
   and `hotel_occupancy` columns are fully populated (the template includes these columns,
   so the feature is clearly intended).
3. With no type, no units, and (typically) no `commercial_rent`, the resolver raises
   `ValueError("Provide annual_rent, property_type, unit_mix...")`, the import's fallback
   path saves the record **without analysis and with `property_type: None`**.
4. Crucially, adding rates later cannot fix it — the type is gone from the record. The user
   must notice, manually edit the property, and re-set the type.

Note the same local set also excludes `residential` and `multi-family`; for those the
exclusion is arguably intentional (they resolve via unit mix), but Hotel resolves via its
own dedicated branch keyed on `property_type`, so erasing it is unambiguously wrong.

**Recommended fix direction:** import `COMMERCIAL_TYPES_LOWER` from `models.constants`
instead of redefining a divergent local set, OR keep a local set but include `"hotel"`.
Then decide explicitly how `residential`/`multi-family` types should flow through CSV
(probably: preserve the type string always, and let the resolver decide the mode — there is
no good reason to null out a user-provided type). Add CSV import tests covering a hotel row
with full ADR/occupancy data asserting hotel metrics appear in `results` (Section D, D2).

---

### B2. The "+2% stress test" is not a rate stress — it understates risk by roughly an order of magnitude

**File:** `analysis/metrics/cash_flow.py`, `DebtMetrics` (~lines 32–45):
```python
STRESS_RATE = 0.02
stressed_debt = annual_mortgage * (1 + self.STRESS_RATE)
self.stressed_dscr = est_noi / stressed_debt
```
The report row is labelled `"Stress Test (+2%)"` with `PASS` at stressed DSCR ≥ 1.20.

**The problem:** multiplying the **payment** by 1.02 simulates a 2% increase in the
payment, not a 2-percentage-point increase in the **interest rate**. A real +200bp shock on
a 25-year amortizing loan at 5% raises the annual payment by roughly 20–25%, not 2%. So the
metric labelled as a rate stress applies ~1/10th of the intended shock, and the PASS/FAIL
verdict is far too lenient. For a tool whose purpose is underwriting discipline, this is a
dangerous metric: it produces confident green checkmarks on deals that would genuinely fail
a rate-shock test.

**Why it's structured this way:** `DebtMetrics` receives only `est_noi`, `expense_ratio`,
`annual_mortgage`, `annual_rent` — it has no access to the loan amount, rate, or term, so
it *cannot* compute a true re-priced payment. This is a design limitation, not a typo.

**Existing test that must change:** `tests/test_metrics_cash_flow.py` —
`TestStressTestScalesWithLoan` asserts only that the stress is *proportional* to loan size
(a guard against an even older flat-$9k bug). The current broken implementation passes it
trivially. The test's docstring talks about "a 2% rate shock" but the assertions never
check the shock magnitude. Replace it with a test that computes the true payment at
`rate + 0.02` via `MortgageCalculator` and asserts `stressed_dscr` matches
`est_noi / stressed_payment` within tolerance.

**Recommended fix direction:** compute the stressed payment properly. Two options:
- **Option 1 (preferred):** in `CommercialPropertyAnalyzer.__init__`, construct a second
  `MortgageCalculator` at `prop.interest_rate + 0.02` and pass its `annual_mortgage` into
  `DebtMetrics` as `stressed_annual_mortgage`. Keeps `DebtMetrics` dumb and testable.
- **Option 2:** pass loan parameters (loan amount, rate, term) into `DebtMetrics` and let
  it compute the re-priced payment itself. More self-contained but duplicates mortgage math.
- Keep the row label honest either way; if the +2% is configurable later, derive the label
  from the constant.

---

### B3. Editing a property's type does not reset the vacancy rate — stale type-specific defaults persist forever

**Files:**
- `ui/menu.py` — `_edit`, the `proptype` branch (~line 374):
  `update_property(raw_idx, {key: resolved, "expense_ratio": None, ...})` — note
  `expense_ratio` is reset to `None` so the new type's default applies, but
  **`vacancy_rate` is not reset**.
- `models/property_input.py` — `__post_init__` resolves `vacancy_rate=None` from
  `VACANCY_RATE_DEFAULTS` by property type (Office 14%, Industrial 5%, Multi-family 3%, …).
- `analysis/analyzer.py` — `to_record()` persists the resolved `p.vacancy_rate`.
- `ui/menu.py` — `_record_to_prop` passes the persisted value back as `vacancy_rate`,
  which `__post_init__` treats as explicit (skips re-resolution).

**Effect:** this is the same "resolved value becomes a frozen override" ratchet as A3, plus
a concrete editing bug: convert an Office (default vacancy 14%) to Industrial and the
record keeps 14% vacancy forever — more than double the Industrial default of 5% — skewing
EGI, NOI, cap rate, and everything downstream. The user gets no indication that the vacancy
assumption belongs to the *old* type. Conversely, if the constants in
`models/constants.py` are ever updated (they cite dated market reports: "CBRE Canada Q4
2025" etc.), no existing record ever picks up the new defaults.

**Recommended fix direction:**
- Immediate: in the `proptype` edit branch, also set `"vacancy_rate": None` (mirroring
  `expense_ratio`) so re-analysis re-resolves it for the new type. Consider whether
  `expense_ratio`'s reset should be conditional on it having been a default rather than a
  user-entered value — which leads to:
- Proper: adopt the same two-key design as A3 — store user-set vacancy separately from
  resolved vacancy (`vacancy_rate` = override or `None`; `vacancy_rate_resolved` = what was
  used, for display). Fix A3 and B3 with one shared convention.
- Test: edit-type round-trip asserting the new type's default vacancy is applied unless the
  user explicitly set one.

---

### B4. Invalid input in any "optional" edit field crashes the whole application

**File:** `ui/menu.py` — `_edit`, the `optional` branch (~line 324–330):
```python
if special == "optional":
    raw = input(f"  New {label} (Enter to clear): ").strip()
    val = cast(raw) if raw else None      # ← no try/except
    self._store.update_property(raw_idx, {key: val})
```
Fields using this branch: Commercial rent / year, Residential rent / year, Construction
cost, all six Industrial sqft/rate fields.

**Effect:** typing anything non-numeric (e.g. `abc`, `12,000` — note **commas are not
stripped here** unlike the `nodec`/`hotel` branches, so even `1,500` crashes) raises
`ValueError` from `float(raw)`. Nothing catches it: it propagates out of `_edit()`, through
the `run()` loop (which has no try/except), and the process dies with a traceback. Every
*other* branch in this edit loop (`pct`, `unit`, `nodec`, `hotel`, `hotel_pct`, `date`, and
the standard-field fallthrough) wraps the cast in try/except — this branch is the one
omission. Note the user also loses any in-flight context (though previously confirmed field
edits were already persisted one-by-one, so data loss is limited to surprise, not state).

**Recommended fix direction:** wrap the cast in try/except ValueError, print
`"Invalid number."`, and `continue` — exactly matching the sibling branches. Strip commas
(`raw.replace(",", "")`) for consistency with `nodec`. As defense in depth, consider a
broad try/except around the body of `run()`'s dispatch so no single action can ever kill
the menu loop (print the error, return to menu). Add a scripted-stdin test (Section D, D4).

---

### B5. `DebtMetrics.be_ratio` defaults to 1 when NOI is zero, displaying a GOOD grade on a property with no income

**File:** `analysis/metrics/cash_flow.py` (~line 37):
```python
self.be_ratio = (annual_mortgage / est_noi) * 100 if est_noi else 1
```
**Effect:** when `est_noi == 0` (which can occur via the A2 zero-rate path, a 100% expense
ratio, or 100% vacancy), `be_ratio` becomes `1` — interpreted as **1%**, i.e. "debt service
is 1% of NOI". The grader (`Grader.grade(self.be_ratio, 75, 85, higher_is_better=False)`)
rates anything ≤ 75 as GOOD, so the report shows "Break-Even NOI % 1.00% — GOOD" on a
property that cannot service a single dollar of debt. The sentinel is semantically inverted:
zero NOI is the *worst* case and should grade POOR.

Also note the adjacent oddity: the row labelled `"Break-Even NOI"` (~line 50) displays
`self._annual_mortgage` (the dollar amount of debt service) — the value is *correct* in the
sense that break-even NOI equals the debt service, but a reader may not understand that
identity; consider a clearer label like "Break-Even NOI (= Annual Debt Svc)".

**Recommended fix direction:** use a worst-case sentinel, e.g.
`float("inf")` or a large number like `999.0`, when `est_noi` is zero or negative, so the
grade lands on POOR; or special-case the grade to `"POOR/NO INCOME"`. Add unit tests for
`est_noi == 0` and `est_noi < 0` asserting the grade is POOR.

---

### B6. `DataStore._write` is not crash-safe — a crash mid-write can destroy the entire properties database

**File:** `data/store.py` (~line 35–38):
```python
@staticmethod
def _write(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
```

**The problem:** `open(path, "w")` **truncates the file to zero bytes immediately**, then
streams the JSON. If the process is killed, the machine loses power, or `json.dump` raises
partway (e.g. a non-serializable value sneaks into a record), the file is left empty or
truncated mid-document — and with 476 properties in a single `properties.json`, that is the
entire dataset. The risk window is not theoretical: "Re-analyze all" (menu option r) calls
`update_property` once per property, and each call **rewrites the whole file** — 476
consecutive full-file rewrites per run. There are no backups taken anywhere in the
codebase.

**Recommended fix direction:**
- Minimum: atomic write — dump to a temp file in the same directory
  (`tempfile.NamedTemporaryFile(dir=os.path.dirname(path), delete=False)` or
  `path + ".tmp"`), `f.flush()` + `os.fsync(f.fileno())`, then `os.replace(tmp, path)`
  (atomic on Windows and POSIX). This guarantees the file is always either the old or the
  new complete version.
- Recommended additionally: keep one rolling backup (`os.replace(path, path + ".bak")`
  before the swap, or copy) so even a logically-corrupted write (valid JSON, wrong content)
  is recoverable.
- Note: if the SQLite migration (Section G) proceeds, transactions solve this for property
  data, but `_write` still serves the config/rate JSON files and should be made atomic
  regardless.
- Test: simulate failure by making `json.dump` raise mid-write (e.g. an object that raises
  in `__repr__`/default serializer) and assert the original file content survives intact.

---

### B7. Collection of smaller defects (each small, all real)

**B7a. Expense Ratio row renders raw float artifacts.**
`analysis/metrics/income.py` (~line 57): `f"{p.expense_ratio * 100}%"` has no format spec.
`0.07 * 100 == 7.000000000000001` in IEEE-754, so the report can show
`7.000000000000001%`. Fix: `f"{p.expense_ratio * 100:.1f}%"` (or `:.2f`). Check the scorer's
value-parsing is unaffected (it is — it strips non-numeric chars — but keep it in mind).

**B7b. `MortgageCalculator` divides by zero when `term_years == 0`.**
`analysis/mortgage.py`: `n_payments = term_years * 12` → with rate 0 the payment is
`loan/0` (ZeroDivisionError); with rate > 0 the denominator `(1+r)^0 - 1 == 0` also
divides by zero. The add-property prompt (`ask("Loan term (years)", int, 25)`) accepts 0,
as does CSV import and the edit flow. Fix: validate `term_years >= 1` at input boundaries
and raise a clear `ValueError` in the calculator. Same audit for negative interest rates
and `down_payment_pct > 1`.

**B7c. `PricingMetrics` divides by zero when `original_price == 0` (and `asking_price == 0`).**
`analysis/metrics/pricing.py` (~line 45–47): `price_drop_pct` divides by
`prop.original_price`; `tax_load` and `ltv_ratio` divide by `prop.asking_price`. CSV import
requires `original_price` present but accepts `0`. Fix: guard the divisions (0 → 0.0 or a
"n/a" sentinel) and/or reject 0 prices at input boundaries.

**B7d. Canadian mortgage compounding convention not honoured.**
`analysis/mortgage.py` uses `monthly_rate = interest_rate / 12` (US-style monthly
compounding). Canadian fixed-rate mortgages compound **semi-annually**: the effective
monthly rate is `(1 + rate/2)^(2/12) - 1`, which yields a slightly *lower* payment than
monthly compounding at the same nominal rate. For a README that says "Canadian commercial
real estate", payments are systematically overstated by a small but real margin
(~1–2% of the payment at typical rates). Fix: implement semi-annual compounding, ideally
behind a constant or per-property flag (`compounding: "semi-annual" | "monthly"`,
defaulting to semi-annual for Canada). Update mortgage tests with known-good Canadian
amortization figures.

**B7e. `_parse_listing_date` silently converts typos to "today", corrupting DOM-derived metrics.**
`ui/menu.py` (~line 20–30): an unparseable date in the *add* flow falls back to today's
date with no warning. Days-on-market then computes as 0, which feeds the Market Staleness
grade, Seller Bleed, the DOM scoring component, and city rankings (`act_dom`). A typo like
`2025-13-01` silently makes a 9-month-old listing look brand new. The *edit* flow already
does this right (re-prompts on invalid). Fix: in the add flow, loop until valid or
explicitly accept Enter-for-today; never silently substitute. The test file
`tests/test_menu_listing_date.py` currently asserts the silent fallback — rewrite it to
assert the re-prompt contract instead.

**B7f. Rate lookups ignore province — same-named cities in different provinces collide.**
`data/store.py`: `CommercialRentLoader.get_rent_per_sqft(city, province, type)` and
`ResidentialRentLoader.get_rates(city, province)` accept `province` and never use it; the
underlying indexes key by lowercased city name only. Springfield ON and Springfield NS
would share one rate entry; whichever city was saved last wins
(`load_commercial_rates` collapses case-variant duplicates nondeterministically too, since
`dict` insertion order decides). Fix: key the indexes by `(city_lower, province_upper)`
tuples (or `"city|province"` strings), thread province through both loaders, and migrate
existing files (each city entry already stores its province, so migration is mechanical).
This becomes a natural UNIQUE constraint under the SQLite migration (Section G).

**B7g. `_edit_city_demographics` treats the `_meta` key as a city.**
`ui/config_editor.py` (~line 233): `cities_sorted = sorted(data.keys())` includes the
`"_meta"` entry that `json/city_demographics.json` carries for freshness tracking — it gets
listed as city "`_Meta`" with population "—", is editable, and deletable (deleting it would
break the staleness-warning logic in `analysis/analyzer.py`). Fix: skip keys starting with
`_` in the listing/editing/deletion paths. Note `PropertyScorer.load_city_demographics`
also returns `_meta` lowercased in its dict — harmless today (no city named "_meta") but
filter it there too for hygiene.

**B7h. Demographics growth calculation hardcodes a 5-year census window.**
`ui/config_editor.py` (~line 278): `growth = ((pop / pop16) ** (1/5) - 1) * 100` — the
labels say "Population 2021" / "Population 2016", and the exponent assumes exactly 5 years.
When 2026 census data arrives, users will enter 2026/2021 figures into fields labelled
2021/2016 and the math will still divide by 5 only by luck. Fix: store explicit
`population_year` / `population_prev_year` fields and compute the exponent from their
difference; derive the field labels from stored years.

**B7i. CSV template/headers inconsistencies.**
`ui/csv_handler.py`: (1) the importer reads a `construction_cost` column (~line 163) but it
is **absent from both** `EXPECTED_HEADERS` and the exported template — header-based imports
can supply it only if the user guesses the column name, and headerless imports can never
supply it; (2) the template omits all eight `ind_*` industrial columns that
`EXPECTED_HEADERS` includes, so the documented template cannot express an industrial
property fully; (3) for headerless files, `row_num` starts at 2 even though there is no
header row, so error messages point one row too far down. Fix: make
`EXPECTED_HEADERS`, the template headers, and the documented column order identical
(single source of truth — one module-level list used by both methods), add the missing
columns, and base `row_num` on actual file line numbers.

**B7j. Stray file `json/missing_rent_data copy.json`.**
A manual copy sitting in the data directory. Delete it (verify content is redundant with
`missing_rent_data.json` first). It will confuse any future file-discovery logic and any AI
or human reading the data directory.

**B7k. `DaysOnMarketCalculator` crashes on empty/invalid listing_date and allows negative DOM.**
`analysis/mortgage.py` (~line 57): `date.fromisoformat(listing_date)` raises on `""`
(the `PropertyInput` default). All current call paths happen to set a date, but the default
makes the failure mode latent — any future caller constructing a bare `PropertyInput`
gets an opaque ValueError from deep inside the analyzer. A future-dated listing produces
negative DOM, which then feeds the scorer. Fix: default empty → today (DOM 0) or raise a
clear message; clamp negative DOM to 0 (or warn).

**B7l. `_edit_city_distances` "add city" flow falls through to an error and loses unsaved additions.**
`ui/config_editor.py` (~line 190–201): after choosing `a` and entering a city name, the code
falls through to `int(choice)` with `choice == "a"`, prints "Invalid.", and continues. The
new city exists only in the in-memory dict; the file is saved only at the end of a
*successful edit* of some city, so adding a city and then pressing `0` discards it.
Fix: after the add, `continue` the loop (the city then appears in the list), and/or prompt
immediately for its centre/distance and save.

---

## SECTION C — TEST-SUITE ISSUES (tests that don't test what they should)

### C1. The biggest structural gap: `ui/` is excluded from coverage but contains substantial business logic

`.coveragerc` omits `ui/*` entirely, and the README frames this as "all logic that can be
unit-tested lives in the layers below". That framing is no longer true. Logic currently
living in `ui/` that is pure business logic with no I/O coupling:

- **`PropertyMenu._record_to_prop`** — the record→PropertyInput deserializer. This is the
  inverse of `analyzer.to_record()` and the source of bugs A1 and A3. It is a pure
  function (static method, dict in → dataclass out) with zero UI dependency.
- **The entire CSV importer** (`ui/csv_handler.py`) — header detection, encoding fallback
  chain, per-column type coercion, percent normalization, city/province parsing (a
  *second, divergent* implementation of address parsing — see F3), the rent-mode decision
  tree, and the partial-save fallback record shape. Source of bug B1.
- **`rate_editor.py`'s "unknown = average of known unit rates" rule** (~line 154–156 and
  199–201) — a pricing policy decision, untested.
- **`_parse_listing_date`** and **`parse_city_province`** — input normalization rules.

Some tests *do* import these ad hoc (`test_reanalysis_stale_residential.py` imports
`PropertyMenu._record_to_prop`; `test_menu_listing_date.py` imports `_parse_listing_date`),
which proves they're testable — but they're invisible to the coverage gate, so regressions
in untouched paths (e.g. the whole CSV importer) are undetectable by the 90% floor.

**Recommendation:** move the logic down a layer (see Section F for target locations), then
remove those modules from the coverage omit list. What should remain in `ui/` is genuinely
untestable-without-stdin code: prompt loops, print formatting, menu dispatch.

### C2. Tests that assert buggy behaviour (must change with their fixes)

- `tests/test_analysis_analyzer.py::test_to_record_saves_resolved_growth_when_prop_has_none`
  — explicitly asserts the A3 freezing design ("so re-analysis reproduces the same
  figure"). Rewrite per A3.
- `tests/test_metrics_cash_flow.py::TestStressTestScalesWithLoan` — guards proportionality
  only; passes with the B2-broken implementation. Replace with a magnitude-correct
  assertion per B2.
- `tests/test_menu_listing_date.py` — locks in the silent typo→today fallback (B7e).
- `tests/test_reanalysis_stale_residential.py::test_reanalysis_is_idempotent` — currently
  passes partly *because* A3 freezes the growth rate; after fixing A3, idempotency must be
  re-established by the resolved-value re-derivation being deterministic, and this test
  should be strengthened to also assert the source label survives the round-trip.

### C3. Test isolation: multiple tests silently read the repository's live data files

- `analysis/analyzer._resolve_noi_growth` opens the hardcoded relative path
  `json/city_demographics.json`; tests run from the repo root, so any test analyzing a
  property in "Ottawa", "Midland", etc. (e.g. most of `test_analysis_analyzer.py`,
  `test_reanalysis_stale_residential.py`) reads the **real** demographics file. Editing
  your live demographics data can change test outcomes. One test
  (`test_to_record_saves_resolved_growth_when_prop_has_none`) already had to defend itself
  by inventing "UnknownCityXYZ".
- `PropertyScorer` hardcodes `SCORE_CONFIG_PATH`, `CITY_DISTANCES_PATH`,
  `CITY_DEMOGRAPHICS_PATH` as module constants resolved against the CWD — the injected
  `DataStore`'s configurable paths are bypassed (`load_config` calls
  `self._store._read(SCORE_CONFIG_PATH)`, i.e. uses the store only as a file-reading
  utility). Tests work around this with `unittest.mock.patch` on the module constant
  (`test_scoring_scorer_branches.py` ~lines 385–460).
- Several `test_scoring_city_ranker.py` tests (`~lines 332, 592, 629`) `open("json/score_weights.json")`
  directly and assert specific live config values (e.g. `inact_cap` ceiling must be 10.0,
  certain weights non-zero). These are config-validation tests masquerading as unit tests —
  if the user legitimately tunes weights via menu option `s`, the suite breaks.

**Recommendation:** thread all these paths through `DataStore` (constructor parameters with
the current values as defaults), have `_resolve_noi_growth` take the demographics dict (or
a loader) as a parameter instead of opening files, and convert the live-config assertions
into a separate, clearly-named config-sanity test module that is *expected* to track the
shipped defaults (or drop them).

### C4. Weak assertions that verify execution, not behaviour

Examples (not exhaustive): `test_irr_negative_cash_flow_returns_minus100` asserts only
`isinstance(m.irr, float)` despite its name promising a -100 check;
`test_calc_irr_dnpv_zero` and `test_calc_irr_loop_continues_multiple_iterations` assert
only "is a float" / "did not crash" (these exist to hit coverage branches);
`test_em_grade_poor` accepts either of two grades (`in ("POOR (Underperforming)", "FAIR")`),
i.e. it cannot fail meaningfully. Tighten each to assert the actual expected value, and
rename tests whose names overpromise. Coverage-driven tests that genuinely only need
"doesn't crash" should say so in their name (`..._does_not_crash`).

---

## SECTION D — MISSING INTEGRATION TESTS (ordered by value)

### D1. Save → reload → re-analyze idempotency, parametrized over every property type
The single highest-value addition; it would have caught A1, A3, and B3 directly.
Shape: for each property type (Office, Retail, Industrial, Mixed-Use, Retail-Office
with floors>1, Residential, Multi-Family, Hotel), build a `PropertyInput`, analyze with a
real `RentResolver` over a temp `DataStore` seeded with rates, `to_record()`, then
`_record_to_prop()` → re-analyze → `to_record()` again, and assert: identical resolved
rent, identical metric values in `results`, identical `floors`/`unit_mix`, identical
NOI-growth *source label*, identical vacancy rate. Run the loop twice to catch
second-order ratchets.

### D2. CSV import end-to-end
Write temp CSV files and run `_import_csv` (or its extracted core, per F2) against a temp
`DataStore`: (a) header-based file with all property types **including Hotel with
rooms/ADR/occupancy** — assert type preserved and hotel metrics in results (catches B1);
(b) headerless file using the documented column order; (c) encoding fallback (write
cp1252 bytes with a non-ASCII address); (d) rows with missing required fields — assert
skip messages reference correct row numbers (B7i); (e) the partial-save fallback when
rates are missing — assert the record shape matches what `_record_to_prop` can round-trip.

### D3. `ensure_city_in_rates` ↔ `RentResolver` interplay
On a temp `DataStore`: call `ensure_city_in_rates("Oshawa", "ON")`, then resolve an Office
property in Oshawa through real loaders. Assert (post-A2-fix) that the missing-rate
`ValueError` is raised and `missing_cities.json` gains the entry. This is the regression
test for A2 and pins the contract between the placeholder mechanism and the resolver.

### D4. Menu flows under scripted stdin
Using `monkeypatch.setattr("builtins.input", ...)` with scripted sequences: (a) the B4
crash path — edit a property, choose field 7 (Commercial rent / year), type `abc`, assert
the menu survives and prints an error; (b) the edit-then-reanalyze flow for a
retail-office property asserting floors survive (A1); (c) delete flow — assert the sorted
display index deletes the correct underlying record when the file order differs from the
sorted order (the raw-index remapping in `_delete` is correct today but completely
untested and easy to break).

### D5. `solve_targets` round-trip sanity
For a mid-scoring property on a temp store: take the suggested `targets["price"]`, apply
it to the record, re-analyze via the real pipeline, and assert the resulting score ≥ 99.5
(within the rounding granularity the solver itself applies). Also assert the solver
returns `{}` for an already-perfect property and never suggests a price *above* asking or
rent *below* current.

### D6. Multi-property store-index integrity for bulk re-analysis
`_reanalyze_all` and `_reanalyze_city` capture `props` once and call
`update_property(i, ...)` per index while the file is rewritten each iteration. This is
correct today because updates are positional and in-place, but nothing tests it; a future
change that sorts, filters, or deletes during the loop would silently corrupt the mapping.
Test with ≥3 properties across 2 cities asserting each record receives *its own* updated
analysis.

---

## SECTION E — PERFORMANCE

### E1. Report generation does redundant full re-analyses and file reads at painful scale

**Observed scale:** 476 properties in `properties.json`.

**Hot path 1 — `PropertyMenu._open_report`:** for every property it calls
`scorer.solve_targets(...)`, which runs **up to 4 levers × 60 bisection iterations**, each
iteration performing `copy.deepcopy(record)` + `_record_to_prop` + a full
`CommercialPropertyAnalyzer` construction + `to_record()` + `score_property`. Worst case
~240 full analyses per property → ~114,000 analyses per report.

**Hot path 2 — per-call file I/O:** every single `score_property` call re-reads
`score_weights.json` (`load_config`) **and** `city_distances.json` from disk; every
analyzer construction re-reads `city_demographics.json` inside `_resolve_noi_growth`;
every resolver call re-reads both rent files via the loaders
(`load_commercial_rates`/`load_residential_rates` parse the full file per lookup). Multiply
by the analysis counts above: hundreds of thousands of file opens + JSON parses per report.

**Recommended fix direction (independent of, and complementary to, the SQLite migration):**
1. **Cache per operation, not globally:** load config, distances, demographics, and both
   rate indexes **once** at the top of `_open_report` / `rank()` / `_reanalyze_all` and
   pass them down (or give `DataStore` an mtime-validated cache so unchanged files are
   parsed once per process). The class docstring in `scorer.py` says "no in-memory caching"
   as a deliberate freshness choice — an mtime check preserves that property while
   eliminating ~99% of parses.
2. **Cut bisection cost:** 60 iterations gives ~2^-60 precision on values that are then
   rounded to the nearest $1,000 (price), $100 (rent), or basis point (rate). ~20
   iterations exceeds the displayed precision; also add an early-exit when the bracket is
   already narrower than the rounding quantum.
3. **Skip levers cheaply:** `solve_targets` already pre-checks feasibility with one probe
   per lever — keep that, but short-circuit `score_with` for records whose score is `None`
   (no income metrics) before deep-copying.
4. Optional UX: print progress as `n/total` (currently dots) and consider only solving
   targets for active listings, or making targets an on-demand per-property action.

---

## SECTION F — STRUCTURAL / ARCHITECTURE CHANGES RECOMMENDED

### F1. Move `_record_to_prop` out of the UI layer into the analysis/model layer

It is the deserialization half of the `to_record()` contract, used by scoring
(`solve_targets` receives it as a callback!), bulk re-analysis, and tests. Its current home
forces `scoring/scorer.py` to accept `record_to_prop_fn` as a parameter — a layering
inversion where the scoring layer depends on a UI-provided function to do core domain
conversion. Target: `models/property_input.py` as `PropertyInput.from_record(record)` (a
classmethod next to the dataclass it builds), or a `analysis/serialization.py` module
owning both directions (`to_record` logic + `from_record`) so the round-trip contract
lives in ONE file and can be tested as a pair. After the move, `solve_targets` can import
it directly and drop the callback parameter.

### F2. Extract the CSV importer's parsing core from `ui/csv_handler.py` into `data/csv_import.py`

Split into: (1) a pure function `parse_csv_rows(rows: list[dict]) -> list[ParsedRow |
RowError]` containing header detection, coercion, and the rent-mode decision tree;
(2) a thin UI wrapper that handles `input()`, file paths, and printing. This makes D2
testable under the coverage gate, removes the duplicated `PROVINCES` set and
city/province parser (see F3), and gives the importer a contract the AI/dev can fix B1
and B7i against.

### F3. Single source of truth for address/city/province parsing and the provinces list

There are currently **three** implementations: `utils._parse_address_sort` /
`_display_address` (display/sorting), `PropertyMenu._prompt_property.parse_city_province`
(~line 688), and `csv_handler.parse_city_province` (~line 97, with an extra `". "`
heuristic the menu version lacks). The `PROVINCES` set is defined twice. Behavioural
drift between them already exists. Consolidate into `utils.py` (or a new
`models/address.py`): one `PROVINCES` constant, one `parse_city_province(addr)` used by
both the menu and CSV import, with the union of both heuristics, fully unit-tested.

### F4. Unify the two missing-data registries

`missing_cities.json` (written by `RentResolver._log_missing` →
`DataStore.log_missing_city`, read by `load_missing_cities` with its case-dedupe logic) and
`missing_rent_data.json` (written by `ensure_city_in_rates`) track overlapping facts with
different schemas and no synchronization. After fixing A2, decide on **one** registry
(recommendation: keep `missing_cities.json`'s richer schema — it tracks *which* rate types
are missing — and delete the `missing_rent_data.json` mechanism), and make the rate-editor
save paths (`save_commercial_city`/`save_residential_city`) the single place entries are
cleared. Under the SQLite migration this becomes a `missing_rates` table or simply a view
over rates (a city/type is "missing" iff no row exists — which makes the registry
*derivable* and eliminates the sync problem entirely; strongly prefer that).

### F5. Inject all config-file paths through `DataStore`; eliminate CWD-relative module constants

Offenders: `scoring/scorer.py` (`SCORE_CONFIG_PATH`, `CITY_DISTANCES_PATH`,
`CITY_DEMOGRAPHICS_PATH`), `analysis/analyzer.py` (`_DEMOGRAPHICS_PATH`),
`reporting/city_report.py` (`_SCORE_WEIGHTS_PATH`, which at least anchors to `__file__`),
`ui/config_editor.py` (hardcoded `"json/city_distances.json"`, `DEMO_PATH`). Every one of
these bypasses the dependency-injection design the rest of the codebase follows and is why
`main.py` must `os.chdir` to the project root before anything works. Give `DataStore`
constructor parameters (with current defaults) for each, expose
`load_score_config()/save_score_config()`, `load_city_distances()`,
`load_city_demographics()` on it, and make scorer/analyzer/report consume those. This
fixes test isolation (C3) as a side effect and removes the `scorer._store._read(...)`
private-method reach-through.

### F6. `_resolve_noi_growth` should be a method/dependency, not a file-reading free function

Currently a module-level function in `analyzer.py` that opens a JSON file on every analyzer
construction. After F5, pass the demographics mapping (or a loader callable) into
`CommercialPropertyAnalyzer` (alongside the resolver), making the analyzer fully I/O-free
and the demographics readable once per bulk operation (helps E1). The analyzer also reaches
into the resolver's private attributes (`getattr(rent_resolver, "_comm_rent", None)` etc.)
— formalize that by having `RentResolver.resolve()` return a small result object
(`ResolvedRent(total, breakdown, comm, res, city_rate, comm_sq_ft)`) instead of stashing
state on `self` and having callers `getattr` privates. This also removes the latent bug
where a resolver reused across analyses carries stale `_city_rent_per_sqft` from a prior
property (it is reset at the top of `resolve()` today, but only some of the attributes are).

### F7. `solve_targets`'s `bisect_lever` readability

`scoring/scorer.py` (~line 168–176) uses walrus-in-tuple expressions
(`lo = mid if invert else (lo, hi := mid)[0]`) that are extremely hard to verify and were a
review hazard. Rewrite as a plain if/else block updating `lo`/`hi` explicitly. Behaviour
is believed correct today; this is purely maintainability, but do it before anyone edits
that function for E1.

### F8. Delete or implement `json/missing_cities.json` stray sibling and tidy the data directory

Covered partially by B7j and F4; the `json/` directory should end up containing exactly the
documented files. Also note `properties.json` lives at the **repo root** while everything
else lives in `json/` (`DataStore.PROPERTIES_PATH = "properties.json"`) — README's
directory listing implies it lives in `json/`. Pick one location (suggest `json/` or the
SQLite file) and migrate.

---

## SECTION G — STORAGE MIGRATION: JSON → SQLITE (recommended, scoped)

**Verdict from review:** worth doing now; the driver is **correctness, not scale**.
476 records is trivial for JSON, but the access patterns have outgrown it.

**What hurts today (recap of the analysis):**
1. **No atomicity** — every `update_property` rewrites the whole file (B6); re-analyze-all
   = 476 sequential full-file rewrites with a corruption window each time.
2. **No stable identity** — records addressed by list index or the
   `(address, listing_date)` composite key; the menu performs a fragile
   sorted-index → raw-index remapping in `_edit`/`_delete`; editing an address or listing
   date changes the dedupe key in `save_property` (duplicate risk).
3. **Hand-written database operations** — `CityRanker.rank()` is a GROUP BY;
   `load_missing_cities`'s case-normalization dedupe and the city/province collision (B7f)
   are jobs for a UNIQUE constraint; two registries (F4) are a sync problem SQL makes
   structurally impossible.
4. **Roadmap pull** — price-history tracking (H2) is an append-only child table, awkward in
   a single JSON document.

**Why the cost is unusually low here:** `sqlite3` is in the standard library (preserves the
project's zero-runtime-dependency property), and **all** I/O already flows through
`DataStore`, so the migration is a swap behind one class. Tests inject paths into
`DataStore` today; they would inject `:memory:` (or a tmp db file) tomorrow and get faster.

**Recommended scope — do NOT migrate everything:**
- **Migrate:** `properties` (one table; real columns for queried/aggregated fields:
  id INTEGER PRIMARY KEY, address, mls_number, status, city, province, property_type,
  asking_price, original_price, listing_date, created_at, last_modified, analyzed_on,
  total_sq_ft, financing fields…; plus a single `results_json` TEXT column for the
  display-oriented `results` array and `unit_mix_json` for the mix — do not
  over-normalize write-once display data), a future `price_history` table
  (property_id, date, price), and the missing-data registry (preferably as a **view/query**
  over the rates tables per F4, not a table).
- **Consider migrating:** commercial/residential rates (two small tables keyed
  UNIQUE(city, province, type/unit)) — solves B7f structurally. Acceptable to defer.
- **Keep as JSON:** `score_weights.json`, `city_demographics.json`, `city_distances.json` —
  small, human-edited (README explicitly advertises hand-editability), naturally
  document-shaped. Moving them buys nothing.

**Pros:** transactions (kills B6 for property data), stable primary keys (kills the index
remapping and dedupe-key fragility), UNIQUE constraints (kills B7f and registry drift),
real queries for `CityRanker` and future reporting, concurrent-access safety, `:memory:`
test speed.

**Cons / mitigations:** loss of hand-editability for property records (mitigate: keep a
`export-json` debug command or accept it — users hand-edit configs, rarely 476-record
data); schema migrations become a thing (mitigate: a tiny `user_version`-pragma-based
migration runner — do not add a dependency); the `results` blob stays JSON-in-a-column
(fine: nothing queries inside it except the scorer's value parser, which keeps working);
one-time migration risk (mitigate: importer reads `properties.json`, writes the db,
**keeps the JSON file untouched as the automatic backup**, and verifies round-trip count +
spot-check field equality before declaring success).

**Sequencing note (updated 2026-06-11 — G is now priority #1, ahead of the A-fixes):**
since the migration now lands *before* A1/A3/B3, the schema must be designed around the
**corrected** contract up front (separate `noi_growth_override` vs `noi_growth_resolved`
columns, a real `floors` column, `vacancy_override`/`vacancy_resolved`), and the migrator
must flag suspect frozen values (A3) and floors==1 retail-office rows (A1) during import
so they can be repaired once those fixes land.

---

## SECTION H — FEATURE IDEAS (in rough priority order)

### H1. Sensitivity matrix in the HTML report
A DSCR / annual-cash-flow grid across interest rate (current ±2% in 0.5% steps) ×
vacancy (current ±5% in 1–2% steps) per property. All machinery exists
(`MortgageCalculator`, `IncomeMetrics`, `CashFlowMetrics` are cheap pure constructions);
render as a small heat-mapped table in the property detail panel. This is the single most
useful underwriting addition: it converts point estimates into a risk picture and would
also surface the B2 stress-test fix visually. Keep it out of the terminal report (too
wide); HTML only.

### H2. Price-history tracking
Today `update_property` overwrites `asking_price` in place; the only memory of a price
change is `original_price`. Append `{date, asking_price}` events (JSON list per record now,
or the `price_history` table under G). Unlocks: honest Price Drop % (current vs *peak* vs
original), "price cut velocity" as a scoring signal (recent cuts = motivated seller),
city-level price-trend lines in the city report that don't depend on the active/inactive
average comparison currently used (`price_trend` in `city_ranker.py` is a weak proxy).

### H3. Surface the offer-price solver in the terminal
`solve_targets` already computes the asking price / rent / rate / down payment that would
push a deal to ~99.5/100, but it is only visible in the HTML report. Add it to menu
option 2 (view analysis) as a "TARGETS" footer block. Zero new computation — pure display.
(Gate it behind the E1 performance fixes so a single-property view stays instant.)

### H4. Break-even rent metric
Rent required for DSCR ≥ 1.20 (or configurable) at current financing:
`required_NOI = 1.20 × annual_mortgage`, then invert through expense ratio and vacancy:
`required_rent = required_NOI / ((1 - expense_ratio) × (1 - vacancy_rate))`. Compare to
resolved market rent and report the gap in $ and % — directly actionable in negotiation
("this works at $19/sqft; market is $22 — margin of safety 14%"). Add to `DebtMetrics` or
a new row group; grade by gap size.

### H5. Portfolio summary view
New menu option aggregating across saved properties (filterable to status=active):
total/avg annual cash flow, total equity deployed (cash invested), weighted-average cap
rate and DSCR (weight by cost basis), count by type/city, total NOI. `CityRanker` already
demonstrates the aggregation pattern; this is a simpler flat rollup plus a print table.

### H6. Canadian semi-annual compounding toggle
Covered as bug B7d — listed here too because it is user-visible: expose
`compounding` as a property-level field with a sane default and show it in the mortgage
row group so users know which convention produced the payment.

### H7. Atomic backups / undo for the property store
Covered as B6/G; user-visible angle: a "restore from backup" menu entry that lists the
rolling backups (or, under SQLite, simple file copies of the db) with timestamps.

---

## SECTION I — APPLICATION STRUCTURE & CODE SMELLS (deep dive)

> Section F listed specific mechanical moves. This section is the broader architectural
> review: recurring design smells, why they exist, what they cost, and a proposed target
> organization. Several items here are the *root causes* of bugs in Sections A/B — fixing
> the smell prevents the bug class, not just the instance.

### I1. THE deepest issue: the persistence format is the presentation format

**What:** `CommercialPropertyAnalyzer.to_record()` saves `results` as a list of
`{metric, value, grade}` rows where `value` is a **pre-formatted display string**
(`"$1,234.56"`, `"6.20%"`, `"2.13x"`, `"123 Days"`) and `metric` is a display label that
sometimes embeds data (`"IRR (10-Yr)"` embeds the hold period in the key).

**Where it bites, concretely:**
- `scoring/scorer.py::score_property.val()` must **reverse-parse** the display strings back
  into floats by stripping every character that isn't a digit, `.`, or `-`. This is a
  serialize-then-parse round trip through a lossy human-readable format.
- Because `"IRR (10-Yr)"` embeds hold years in the metric *name*, the scorer needs a
  special `val_prefix("IRR (")` prefix-scan to find it at all.
- `INCOME_METRIC_NAMES` (a frozenset of display labels) is exported from
  `analysis/metrics/income.py` and imported by `reporting/printer.py`, `ui/menu.py`, and
  `scoring/scorer.py` purely so other layers can string-match "does this record have a real
  analysis?". Renaming a report label is a cross-layer breaking change.
- The HTML reports color-code by substring-matching grade strings ("GOOD", "POOR", …).
- Any future feature needing a raw number (sensitivity matrix H1, portfolio rollup H5,
  SQLite queries G) must either re-run the analysis or parse display strings.

**Why it matters:** display formatting should be the *last* step, derived on demand. The
moment formatted strings became the stored truth, every consumer inherited a parsing
obligation and every label became load-bearing API.

**Recommended target:** `to_record()` should persist a **raw metrics dict** alongside (or
instead of) the display rows — e.g.
`"metrics": {"cap_rate": 6.2, "noi": 31200.0, "dscr": 1.41, "irr": 11.3, "hold_years": 10, ...}`
with stable snake_case keys, plus `"grades": {"cap_rate": "good", ...}` if grades need
persisting at all (they're derivable). `ReportRow` lists become a pure rendering concern
generated from the metrics dict by the printer/HTML layer. The scorer reads
`metrics["cap_rate"]` directly — `val()`, `val_prefix()`, and the character-stripping
disappear. Keep writing the old `results` array during a transition for backward
compatibility, then drop it (or keep it solely for the saved-analysis display in menu
option 2). (Originally recommended before the SQLite migration so the schema stores
numbers, not strings; with G now priority #1, the schema keeps `results` as a JSON text
column and adds raw-metrics storage when this item lands.)

### I2. Stringly-typed domain concepts (property types, grades, lease types, status, rent modes)

**Symptoms found throughout:**
- Property type compared via `(prop.property_type or "").strip().lower() == "hotel"`-style
  checks in **at least 15 places** across analyzer, resolver, pricing, menu, CSV handler.
  Three different "commercial types" sets exist: `models/constants.py::COMMERCIAL_TYPES`
  (includes Hotel), `ui/csv_handler.py`'s local set (excludes Hotel — caused bug B1), and
  the rate editors' / `ensure_city_in_rates`' hardcoded
  `["Office", "Retail", "Industrial", "Mixed-Use"]` (excludes Retail-Office and Hotel, a
  third inconsistent universe).
- Grades are free-form strings carrying both severity and message:
  `"GOOD"`, `"FAIR (Thin Margin)"`, `"POOR/BLEEDING"`, `"POOR/UNBANKABLE"`,
  `"FAIL: High Rate Risk"`, `"WARNING: High for Office (typical 32–50%)"`,
  `"FAST CELOC"`, `"WARN — refresh demographics data"`, `"INFO"`, `""`. Consumers
  (HTML color-coding, the `results` filter `grade != ""`) must substring-match. There is
  no way to ask "is this row bad?" without knowing every spelling.
- `lease_type` normalization dict `{"no":"Normal","n":"Normal",...}` is duplicated
  **three times** (menu add flow, menu edit flow, CSV import).
- `status` is `"active"`/`"inactive"` raw strings compared with `.lower()` in some places
  and not others.

**Recommended target:** introduce small enums in `models/` —
`PropertyType` (with a `parse()` classmethod owning all shortcut/case logic, used by menu,
CSV, and edit flows), `Severity` (GOOD/FAIR/POOR/INFO/WARN/NONE) carried on `ReportRow` as
a separate field from the human label, `LeaseType`, `Status`, and a `RentMode` enum (see
I5). Normalize **once at the input boundary**; everything downstream compares enum
identity. This single change eliminates the B1 bug class permanently and makes the
"which types are commercial" question have exactly one answer.

### I3. `DataStore` is a god object, and everyone reaches through its privates

**Symptoms:**
- One class owns: property CRUD, commercial rates, residential rates, two missing-data
  registries, plus generic `_read`/`_write` file helpers.
- **Privacy violations everywhere:** `ui/rate_editor.py` calls
  `self._store._read(self._store._commercial_path)` — reaching through two private
  members to bypass the store's own `load_commercial_rates()` (because that method
  lowercases keys and the editor needs original casing — a sign the API doesn't serve its
  callers). `scoring/scorer.py` calls `self._store._read(SCORE_CONFIG_PATH)` — using the
  store as a bare file utility with a path the store doesn't own. Tests patch
  module-private constants to redirect paths.
- The same data is loaded in different shapes by different callers (raw dict with original
  casing vs lowercased index), so "what does a rate entry look like" has two answers.

**Recommended target:** split along aggregate boundaries —
`PropertyRepository`, `RateRepository` (commercial + residential + missing-rate registry,
since F4 derives the registry from rates), `ConfigRepository` (score weights, distances,
demographics). Each exposes complete public methods for every real use case (including
"list cities with original casing for editing"), so no caller ever needs `_read`. A thin
`DataStore` façade can keep the current constructor signature during transition. Under the
SQLite migration these become natural table gateways.

### I4. Mixins as a file-splitting device, and the 941-line menu

**Symptoms:**
- `PropertyMenu(RateEditorMixin, ConfigEditorMixin, CsvHandlerMixin)` — the README is
  candid that the mixins exist "so each file stays under 1,000 lines". The mixins are not
  reusable units: they silently depend on `self._store`, `self._resolver`,
  `self._reanalyze_city`, `self.THIN_DIVIDER` being provided by the host class — an
  implicit, unchecked contract (a mixin instantiated alone crashes). This is inheritance
  used where composition is meant.
- `ui/menu.py` is 941 lines; `_edit()` alone is ~325 lines — a 37-entry field table plus a
  ladder of ten `if special == "...":` blocks (the "type code + switch" smell). Bug B4
  lives in exactly one rung of that ladder being subtly different from its siblings —
  which is what this smell does: near-duplicate branches drift.
- `_prompt_property()` is ~220 lines mixing prompting, validation, parsing, and
  construction.

**Recommended target:**
- Replace mixins with **composition**: `RateEditor(rate_repo, reanalyzer)`,
  `CsvImporter(property_repo, resolver)` (after F2 extracts its pure core),
  `ConfigEditor(config_repo)` — constructed by and held on `PropertyMenu`, which becomes a
  thin dispatcher. Dependencies become explicit constructor parameters instead of
  implied host attributes.
- Replace the `_edit` special-case ladder with **field descriptor objects**: a small
  `EditableField(label, key, parse, format, apply)` dataclass per field, where `parse`
  raises a uniform `ValidationError` that one loop catches. The 10 branches collapse to
  one loop; B4-style omissions become impossible because there is only one error path.
- Extract a shared `prompt_*` helper module (prompt-with-default, prompt-percent,
  prompt-choice) — the percent-normalization rule `v/100 if v > 1 else v` is currently
  copy-pasted in **six places** (menu `ask_pct`, `pct` branch, `hotel_pct` branch, CSV
  `to_pct`, both config editors), and the `>1` heuristic's edge cases (entering `1` means
  100%? entering `0.5` means 0.5% or 50%?) should be decided once.

### I5. `RentResolver` communicates through side-channel state and a flag soup

**Symptoms:**
- `resolve()` returns `(annual_rent, breakdown)` but its *real* outputs also include
  `self._comm_rent`, `self._res_rent`, `self._city_rent_per_sqft`, `self._comm_sq_ft` —
  instance attributes that the analyzer retrieves via
  `getattr(rent_resolver, "_comm_rent", None)`. This is temporal coupling: the attributes
  are only meaningful immediately after a `resolve()` call, the resolver is not reentrant
  (one shared resolver instance serves all analyses in bulk loops), and only *some*
  attributes are reset at the top of `resolve()` — a stale-state bug waiting to happen.
- Mode selection is a flag soup: `has_units`, `residential_income_recorded`,
  `needs_residential_recalc`, `has_commercial`, `has_residential`, `is_mixed` interact
  across ~30 lines to pick one of six paths (direct-split, direct-annual, hotel, mixed,
  residential, retail-office, commercial). The stale-residential-rent bug class (already
  fixed, per `test_reanalysis_stale_residential.py`) came from exactly this ambiguity.

**Recommended target:** `resolve()` returns a frozen
`ResolvedRent(total, commercial, residential, breakdown, city_rate_per_sqft, comm_sq_ft, mode)`
dataclass; the resolver keeps **zero** post-call state. Mode selection becomes a pure
function `determine_rent_mode(prop) -> RentMode` (an enum: DIRECT, HOTEL, MIXED,
RESIDENTIAL, RETAIL_OFFICE, COMMERCIAL) that is unit-testable in isolation, followed by a
per-mode method dispatch. The analyzer's `getattr` reaching (and `to_record`'s
`self._comm_rent if self._comm_rent else 0.0`) disappears.

### I6. `CommercialPropertyAnalyzer.__init__` does everything, and partial analysis is a None-soup

**Symptoms:**
- The constructor performs the entire pipeline: rent resolution, **file I/O**
  (`_resolve_noi_growth` opens the demographics JSON), construction of ~10 metric objects,
  and can raise `ValueError` mid-construction. Heavy constructors are hard to test, hard
  to make async/cacheable, and surprising to callers (constructing an object should not
  read disk).
- The no-rent path sets
  `self.income = self.exit = self.cashflow = self.debt = self.returns = self.market = None`
  and downstream code branches on Noneness (`report()` filters, `to_record()` has
  `if self.income else` fallbacks per field, the scorer detects partial records by probing
  for income metric names — see I1). "Is this a full or partial analysis?" is answered
  differently in four places.

**Recommended target:** a classmethod factory
`CommercialPropertyAnalyzer.analyze(prop, resolver, demographics) -> AnalysisResult`
returning an explicit result object with a `complete: bool` (or
`FullAnalysis | PartialAnalysis` union) and the raw metrics dict from I1. Metric group
construction stays cheap-in-constructor (those are fine — pure math), but the
*orchestrator* stops being a constructor and stops doing I/O (demographics passed in,
per F6).

### I7. Two parallel grading/threshold systems that can contradict each other

**What:** report grades use **hardcoded** thresholds inline at every `rows()` call site
(`Grader.grade(self.cap_rate, 7.5, 5.5)`, `Grader.grade(self.dscr, 1.5, 1.25)`, hotel
RevPAR bands, etc.), while the *scoring* system uses **user-configurable** floor/ceiling
thresholds from `score_weights.json` for the same quantities (Cap Rate, CoCR, DSCR, IRR,
EM, Cash Flow, Price Drop, DOM). A user who tunes the score thresholds via menu option `s`
will see a property graded "GOOD — Cap Rate" in the report while scoring 3/10 on the same
component, with no indication the two systems are independent.

**Recommended target:** decide the relationship explicitly. Either (a) report grades
derive from the same configurable thresholds (one source of truth — preferred; the
configurable `[floor, ceiling]` pair maps naturally onto FAIR/GOOD bands), or (b) document
them as deliberately separate ("grades = market-convention benchmarks; score = your
strategy") and put the convention thresholds in `models/constants.py` next to their
citations like `EXPENSE_RATIO_RANGES` already does, instead of scattering literals through
`rows()` methods. Today's literals-at-call-sites is the worst of both: unconfigurable AND
undocumented.

### I8. Silent exception swallowing

**Instances:** `analysis/analyzer.py::_resolve_noi_growth` (`except Exception: pass` —
a malformed demographics file silently degrades every analysis to the 2% default),
`data/store.py::ensure_city_in_rates` (`except Exception: missing = {}` — quietly resets
the registry), `scoring/scorer.py::load_city_distances`/`load_city_demographics`
(`except Exception: pass` → Location component silently scores 0 for everyone),
`ui/menu.py::_reanalyze_all`/`_reanalyze_city` (`except Exception` counts or `pass` —
a systemic failure affecting all 476 properties prints as "476 errors" with zero detail,
or nothing at all in the city variant).

**Why it matters:** combined with A2 (missing-rate signal dead) the app has multiple
layers that convert failures into silence. Every one of these should at minimum
distinguish expected conditions (file absent → fine, use default) from unexpected ones
(file present but corrupt → tell the user *which* file and *what* error). The re-analysis
loops should collect `(address, error)` pairs and print them — the information is already
in hand and discarded.

### I9. Duplicated code inventory (beyond F3's address parsing)

For the implementer — each of these exists in 2+ copies that have already drifted or will:
1. `_sort_key(p)` — **verbatim duplicate** in `reporting/printer.py::list_properties` and
   `ui/menu.py::PropertyMenu._sort_key`. The menu's `_pick_index` correctness depends on
   both sorts being identical (the displayed numbers come from the printer's sort, the
   selection indexes the menu's sort) — a drift here mis-targets edits/deletes. Move to
   `utils.py` (or the future `models/address.py`) as the single canonical sort key.
2. Percent normalization `v/100 if v > 1 else v` — six sites (see I4).
3. Lease-type resolution dict — three sites (see I2).
4. `PROVINCES` set — two sites; `parse_city_province` — two divergent implementations (F3).
5. Commercial type lists — three inconsistent universes (see I2, caused B1).
6. CSV `EXPECTED_HEADERS` vs template headers — two lists that must match and don't (B7i).
7. The `{"a":"active","i":"inactive"}` status resolver — menu add flow, menu edit flow,
   CSV import.

### I10. Miscellaneous smaller smells

- **`utils.py` is a root-level grab-bag** whose two functions have underscore-private
  names (`_display_address`, `_parse_address_sort`) yet are imported across three
  packages. Private-by-convention names that are de-facto public API confuse every reader
  and linter. Rename without underscores and house them properly (F3's address module).
- **HTML reports are giant f-strings** (`reporting/property_report.py`,
  `city_report.py` — the templates with `{{`-escaped CSS braces). Brace-escaping in
  f-strings is fragile (every CSS rule needs doubling), diffs are unreadable, and editors
  can't syntax-highlight the HTML. Move templates to
  `reporting/templates/*.html` files using `string.Template` (`$placeholder` — no brace
  escaping, stdlib-only) and `json.dumps` injection for data. No dependency needed.
- **Inconsistent/imprecise type hints** — bare `-> list`, `-> tuple`, `-> dict` returns
  throughout (e.g. `resolve(prop) -> tuple`, every `rows() -> list`). Modern syntax
  (`list[ReportRow]`, `tuple[float, list[str]]`) is free documentation and enables a
  mypy/pyright gate; adopt it during the refactors rather than as a separate pass.
- **`main.py`'s `os.chdir`** is the keystone holding the relative-path system together —
  any entry point that forgets it (a future CLI flag, a test runner, an import from
  elsewhere) breaks all file access. Falls away with F5.
- **`models/constants.py` mixes concerns** — UI shortcut maps (`PROP_SHORTCUTS`), domain
  taxonomies (`PROPERTY_TYPES`, `COMMERCIAL_TYPES`), and market benchmark data with
  citations (`EXPENSE_RATIO_DEFAULTS`, `VACANCY_RATE_DEFAULTS`). After I2's enums land,
  split: enums + taxonomy in `models/enums.py`, benchmark tables (which are *data*, with
  sources and refresh cycles, like the demographics file) arguably belong in a JSON file
  with a `_meta.last_updated`, consistent with how demographics are handled.
- **`PricingMetrics`'s class-body `assert`** (validating `_GRM_THRESHOLDS` keys against
  `PROPERTY_TYPES` at import time) is a nice invariant but `assert` vanishes under
  `python -O`; make it a module-level `if` + `raise` or a unit test.

### I11. Proposed target layout (after F + I items land)

```
commercial_property_analyser/
├── main.py                      # entry point only; no chdir (F5)
├── models/
│   ├── enums.py                 # PropertyType, Severity, LeaseType, Status, RentMode (I2, I5)
│   ├── property_input.py        # PropertyInput, UnitMix, from_record()/to_record() pair (F1)
│   ├── address.py               # PROVINCES, parse_city_province, display/sort helpers (F3, I9)
│   ├── analysis_result.py       # AnalysisResult / ResolvedRent dataclasses (I1, I5, I6)
│   └── constants.py             # benchmark tables (or moved to a versioned JSON data file)
├── data/
│   ├── property_repo.py         # property CRUD (→ SQLite under G)
│   ├── rate_repo.py             # commercial+residential rates, missing-rate derivation (F4)
│   ├── config_repo.py           # score weights, distances, demographics (F5)
│   └── csv_import.py            # pure CSV parsing core (F2)
├── analysis/
│   ├── analyzer.py              # I/O-free orchestrator, factory method (I6)
│   ├── mortgage.py
│   ├── rent_resolver.py         # stateless, returns ResolvedRent (I5)
│   └── metrics/                 # unchanged shape; thresholds sourced per I7
├── scoring/
│   ├── scorer.py                # reads raw metrics dict, no display parsing (I1)
│   └── city_ranker.py
├── reporting/
│   ├── templates/               # *.html string.Template files (I10)
│   ├── printer.py               # renders ReportRows FROM AnalysisResult (I1)
│   ├── property_report.py
│   └── city_report.py
├── ui/                          # thin: prompts, dispatch, formatting ONLY
│   ├── menu.py                  # dispatcher + composition of editors (I4)
│   ├── prompts.py               # shared ask/ask_pct/choice helpers (I4)
│   ├── field_editor.py          # EditableField descriptors for _edit (I4)
│   ├── rate_editor.py           # class, not mixin (I4)
│   ├── config_editor.py         # class, not mixin
│   └── csv_handler.py           # thin wrapper over data/csv_import.py
└── json/                        # all data files, including properties (F8) — or app.db under G
```

Coverage config then shrinks its omit list to genuinely interactive modules
(`ui/menu.py`, `ui/prompts.py`), and everything else faces the 90% gate (C1).

**Sequencing note:** I1 (raw metrics persistence) and I2 (enums) are the two
highest-leverage items — they remove the root causes behind B1, the scorer's parsing
fragility, and the INCOME_METRIC_NAMES coupling. (Original guidance had them precede the
SQLite schema design; with G now priority #1, the schema keeps `results` as a JSON text
column and gains raw-metrics storage when I1 lands — see the implementation order.)
I4/I5/I6 are internal refactors that can proceed independently behind the
existing tests. Everything in this section is behaviour-preserving except where it
intersects a Section A/B bug — land those bug fixes first or together.

---

## Suggested implementation order

> **Priority change (2026-06-11):** the SQLite migration (Section G) is now the **#1
> priority**, ahead of the Section A bug fixes. Rationale: `properties.json` is exposed to
> total corruption *today* — every `update_property` truncates and rewrites the whole
> 476-record file in place (B6), and "Re-analyze all" does this 476 times per run. SQLite
> transactions close that corruption window structurally. The original ordering deferred G
> until after the record-shape fixes; that dependency is handled by the migration caveats
> below (schema designed around the *corrected* contract, suspect data flagged on import)
> rather than by sequencing.

1. **G** (SQLite migration of `properties.json`) — closes the data-corruption exposure
   window. Migration caveats (from Section G's sequencing note, now folded in here):
   - Design the schema around the **corrected** record contract even though the A-fixes
     land later: separate `noi_growth_override` vs `noi_growth_resolved` columns (A3),
     a real `floors` column (A1), and a `vacancy_override`/`vacancy_resolved` pair (B3).
   - The migrator must **flag suspect data** during import: retail-office rows with
     `floors == 1` (possible A1 corruption) and `noi_growth_rate` values matching a city's
     historical resolved rate (probable A3 freezing, not a true manual override).
   - Keep `properties.json` untouched as the automatic backup; verify round-trip count and
     spot-check field equality before declaring success.
   - The `results` array stays a JSON text column for now; revisit after I1 lands.
2. **~~A1~~ (done 2026-06-11), A2, A3** (+ their tests, + C2 test rewrites) — data
   corruption *logic* stops here (G stops corruption of the *file*; these stop corruption
   of the *values*).
3. **B6** (atomic writes) — still needed for the config/rate JSON files that remain
   file-based after G.
4. **B1, B2, B3, B4, B5** — functional correctness.
5. **I2** (enums at input boundaries) — eliminates the B1 bug class and de-risks all
   later refactors; then **I1** (raw metrics persistence) — unblocks the scorer cleanup;
   when it lands, add the raw-metrics columns/blob to the schema from step 1.
6. **F1–F6 + I3–I6** (structure) — do before D-section tests so tests target the final
   shape; I9's duplication sweep folds naturally into these.
7. **D1–D6** (integration tests) + **C3/C4** cleanups + coverage-omit shrink (C1/I11).
8. **E1** (performance) — easier after F5/F6/I3 centralize loading.
9. **B7a–B7l** sweep + **I7/I8/I10** smaller smells.
10. **H** features, each behind its own small test set.
