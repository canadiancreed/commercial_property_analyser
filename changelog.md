# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [2.5.0] — 2026-06-12

### Fixed

- **Stress test was ~10× too lenient** — `DebtMetrics` previously computed the stressed debt
  service as `annual_mortgage × 1.02`, treating the 2% shock as a 2% increase in the *payment
  amount* rather than a 200 bp increase in the *interest rate*. On a 25-year loan at 5%, a genuine
  +200 bp shock raises the payment by ~21%, not 2%. Properties that would have failed a real rate
  shock were incorrectly shown as PASS.
- **`TestStressTestScalesWithLoan` did not catch the bug** — the test only asserted that the shock
  was proportional across loan sizes (which the flat ×1.02 trivially satisfied) and never verified
  that the shock magnitude was realistic.

### Changed

- **`DebtMetrics` now recalculates the stressed payment from first principles** — accepts
  `loan_amount`, `interest_rate`, and `term_years`; applies the standard amortization formula at
  `interest_rate + stress_rate_bump` to derive the true shocked annual debt service.
- **Stress rate bump is configurable** — `DebtMetrics.__init__` accepts a `stress_rate_bump`
  parameter (default `0.02`). The row label (`Stress Test (+2%)`) reflects whatever value is
  passed. `analyzer.py` passes the actual loan parameters so the calculation is always exact.
- **`TestStressTestScalesWithLoan` strengthened** — tests now supply proportional loan amounts and
  include a new `test_stress_shock_magnitude_is_realistic` assertion that the payment increase for
  a +200 bp shock falls between 15% and 30% (the correct range near 5% / 25-year), which the old
  ×1.02 formula would have failed.

---

## [2.2.0] — 2026-06-12

### Fixed

- **Single `rent_manually_entered` flag could not distinguish which component a user entered** —
  the previous boolean flag was property-level, not component-level. A mixed-use property with a
  manually-entered commercial rent and a resolver-derived residential rent could not express that
  state: setting the flag `True` froze both components, setting it `False` re-derived both. Any
  re-analysis after a rate update either left the user's figure intact and silently kept the stale
  residential rent, or wiped the user's figure by re-deriving everything.
- **`_reanalyze_city` was defeated for any property carrying `rent_manually_entered=True`** —
  the method exists specifically to propagate market-rate updates to stored records, but the
  short-circuit in `RentResolver.resolve()` returned the stored values immediately, making the
  method a no-op for any manually-entered property regardless of which component had changed.
  With the two-key design, `_reanalyze_city` now correctly re-derives only the resolver-derived
  component while leaving the frozen one untouched.
- **`rent_manually_entered` was never written to the JSON for any of the 476 existing records** —
  the field was added to `to_record()` after all records had been saved; no re-analysis had been
  run since. All records therefore loaded with the flag defaulting to `False`, meaning any
  previously manually-entered commercial rent would have been silently overwritten on the next
  `_reanalyze_city` run. Replaced by the two-key design and a one-time backfill (see below).

### Added

- **`commercial_rent_user_entered` and `residential_rent_user_entered` on `PropertyInput`** —
  two `bool` fields (both default `False`) replace the single `rent_manually_entered` flag.
  Each controls exactly one rent component. `rent_manually_entered` is retained as a computed
  property (`commercial_rent_user_entered or residential_rent_user_entered`) for backward
  compatibility with any code that reads it.
- **Component-level freeze in `RentResolver.resolve()`** — four tiers now:
  (1) both flags `True` → full short-circuit, no market lookups at all;
  (2) only `commercial_rent_user_entered=True` → stored commercial used directly, residential
  re-derived from current market rates (market lookup skipped for the commercial component);
  (3) only `residential_rent_user_entered=True` → stored residential used directly, commercial
  re-derived (market lookup skipped for the residential component);
  (4) both `False` → full re-derive from market rates (existing behaviour for all legacy records).
  All four tiers are integrated into each resolution path (mixed-use, residential-only,
  retail-office, pure commercial, hotel) so that market lookups are genuinely skipped rather than
  called and then overridden.
- **Backward compat: old single-flag records load correctly** — `_record_to_prop` reads
  `commercial_rent_user_entered` and `residential_rent_user_entered` first; if absent it falls
  back to the legacy `rent_manually_entered` key, applying its value to both component flags.
  Records with neither key present default both to `False`.
- **One-time backfill script (deleted after run)** — compared stored `commercial_rent` and
  `residential_rent` against what the resolver would derive today from current market rates.
  Records where stored ≠ derived (and stored ≠ 0) were flagged as manually entered for that
  component. Result: 19 of 476 records flagged (12 commercial, 7 residential), 457 confirmed
  resolver-derived. The 8 records with no market data for their city were also flagged if they
  carried a stored rent value. Both new keys written to every record; legacy
  `rent_manually_entered` key removed.
- **28-test suite `tests/test_rent_manually_entered_flag.py` rewritten for two-key design** —
  covers: both flags default `False`; `rent_manually_entered` computed property (`False`, `True`
  from comm only, `True` from res only, `True` from both); full short-circuit with no market
  lookups; stale stored rents ignored when both flags `False`; partial freeze — comm frozen /
  res derived; partial freeze — res frozen / comm derived; market lookups confirmed skipped for
  each frozen component; `needs_residential_recalc` overrides res freeze when no stored value
  exists; `to_record()` writes both flags correctly for all three flag states; `_record_to_prop`
  reads two-key flags; missing flags default to `False`; legacy single flag `True` fans out to
  both keys; legacy `False` fans out to both `False`; new keys take precedence over old flag when
  both present; `_reanalyze_city`-shaped resolver calls confirm derived-component updates and
  frozen-component preservation at the resolver level.
- **10-test suite `tests/test_reanalyze_city.py`** — tests `_reanalyze_city` end-to-end through
  the full call chain (store load → `_record_to_prop` → resolver → `to_record` →
  `store.update_property`), covering: resolver-derived commercial rent updates when rate changes;
  records from other cities and provinces skipped; manually-entered commercial rent not
  overwritten; commercial market lookup not called when frozen; manually-entered residential rent
  not overwritten; residential market lookup not called when frozen; mixed-use partial freeze
  (comm frozen → res updates; res frozen → comm updates); both flags written back correctly to
  the saved record after re-analysis.

### Changed

- **`_prompt_property` sets two-key flags on new property entry** — `commercial_rent_user_entered`
  is set to `True` when the user fills in the Commercial rent field; `residential_rent_user_entered`
  is set to `True` when the user fills in the Residential rent field. Properties where those fields
  are left blank receive `False` for the corresponding flag.
- **`to_record()` writes `commercial_rent_user_entered` and `residential_rent_user_entered`**
  instead of the legacy `rent_manually_entered` key.
- **Existing tests updated** — `test_explicit_rent_inputs.py`, `test_reanalysis_stale_residential.py`,
  `test_retail_office_floor_loss.py`, and `test_floor_preservation_all_types.py` updated to pass
  the two-key flags. The `_prop` helper in `test_explicit_rent_inputs.py` auto-sets both flags
  from the presence of `commercial_rent` / `residential_rent`, matching the menu behaviour.

### Fixed (edge cases — same session)

- **`_edit` never set the provenance flags when a rent was changed or cleared** — fields 7
  (Commercial rent / year) and 16 (Residential rent / year) went through the `"optional"` branch
  at `menu.py` which wrote the value but left `commercial_rent_user_entered` /
  `residential_rent_user_entered` unchanged. The post-edit re-analysis immediately re-derived from
  market rates and overwrote whatever the user had just typed. The optional branch now writes the
  flag atomically with the value in the same `update_property` call: entering a value sets the
  flag `True`, clearing (Enter with no input) sets it `False`.
- **Clearing a rent in `_edit` re-froze the resolver-derived replacement** — clearing left a
  stale `user_entered=True` flag; the resolver re-derived (value is `None`), but `to_record()`
  persisted the flag verbatim next to the freshly resolved value, stamping it as user-entered and
  freezing the market-derived figure on every subsequent re-analysis. Fixed by the same change:
  clearing now explicitly writes `False`.
- **CSV import never set the provenance flags** — `csv_handler.py` collapsed explicit CSV rents
  into `annual_rent` on `PropertyInput` and never populated `commercial_rent_user_entered` /
  `residential_rent_user_entered`, so any rent provided in a CSV row was silently overwritten by
  the next `_reanalyze_city` pass. The import path now passes `commercial_rent` and
  `residential_rent` as component fields with the correct flags set, matching the behaviour of the
  interactive add form. The partial-save fallback (no resolver data available) also writes both
  flags.
- **9-test suite `tests/test_edit_rent_flags.py`** — covers all three write paths: `_edit` sets
  `commercial_rent_user_entered=True` when a commercial rent is typed; `_edit` sets
  `residential_rent_user_entered=True` when a residential rent is typed; clearing commercial rent
  sets the flag `False`; clearing residential rent sets the flag `False`; cleared flag allows
  re-analysis to re-derive from market rates; CSV import with explicit commercial rent sets flag
  `True`; CSV import with no explicit rent leaves both flags `False`; CSV import with explicit
  residential rent sets flag `True`; CSV-imported user rent survives subsequent `_reanalyze_city`
  unchanged.

---

## [2.1.0] — 2026-06-12

### Fixed

- **Market-resolved rents frozen permanently after first analysis** — `RentResolver.resolve()`
  opened with a short-circuit that fired whenever `commercial_rent` or `residential_rent` was
  non-`None` on the `PropertyInput`, regardless of how that value got there. Because
  `to_record()` always writes both rent fields to the JSON record and `_record_to_prop` always
  reads them back, any rent resolved from market rates on a first analysis was treated as an
  explicit user entry on every subsequent re-analysis. Updating city rate tables, changing
  market assumptions, or running a batch re-analysis had no effect on already-stored commercial
  properties — the old figure was returned verbatim with no warning. The resolver now only
  short-circuits when `PropertyInput.rent_manually_entered` is `True`, meaning the value came
  directly from a user input field rather than a prior market resolution.

### Added

- **`rent_manually_entered` flag on `PropertyInput`** — new `bool` field (default `False`) that
  distinguishes a user-typed rent figure from a market-resolved one stored in a prior analysis.
  The flag is never shown to or entered by the user; it is set automatically by the code that
  collects rent input.
- **Flag set on new and edited properties** — `_prompt_property` in `ui/menu.py` sets
  `rent_manually_entered=True` when the user fills in the Commercial rent or Residential rent
  field during the Add Property form. Properties where those fields are left blank (delegating
  to market-rate resolution) receive `False`.
- **Flag persisted and round-tripped through JSON** — `analyzer.to_record()` writes
  `rent_manually_entered` to the property record. `_record_to_prop` reads it back on load
  (`p.get("rent_manually_entered", False)`). Legacy records that pre-date this field receive
  `False` on load, causing their rents to be re-resolved from current market rates on next
  analysis rather than remaining frozen at a stale stored value.
- **15-test regression suite** — `tests/test_rent_manually_entered_flag.py` covers: flag
  default (`False`) and explicit `True`; manual-entry short-circuit for commercial-only,
  residential-only, and both-rents combined (verifying no market lookup occurs); stale stored
  commercial rent with `flag=False` re-resolves from market rates; stale stored residential
  rent with `flag=False` re-resolves from unit mix; stale mixed-use rents both re-resolve;
  breakdown message accuracy (manual says "directly", market does not); `to_record()` persists
  `True` and `False` correctly; `_record_to_prop` restores `True`, restores `False`, and
  defaults missing key to `False` for legacy records.

### Changed

- **Existing tests updated to reflect manual-entry semantics** — tests across
  `test_explicit_rent_inputs.py`, `test_reanalysis_stale_residential.py`,
  `test_retail_office_floor_loss.py`, and `test_floor_preservation_all_types.py` that relied
  on the old unconditional short-circuit now pass `rent_manually_entered=True` (or have their
  stored record fixtures updated) where the test intent is "user explicitly provided this
  rent." The `_prop` helper in `test_explicit_rent_inputs.py` auto-sets the flag when
  `commercial_rent` or `residential_rent` is supplied, matching the menu behaviour.

---

## [2.1.0-b] — 2026-06-12

### Fixed

- **Zero-filled rate stubs silently produced $0 rent for all property types** —
  `ensure_city_in_rates` in `data/store.py` wrote `{"Office": 0, "Retail": 0, …}` (commercial)
  and `{"bachelor": 0, "one_br": 0, …}` (residential) as sentinels for "rate not yet fetched."
  Every guard in `RentResolver` that should have caught a missing rate checked
  `if rate is None`, so `0` passed through as a valid rate. The result was `$0/sq ft × sqft =
  $0` annual rent: no `ValueError`, no `log_missing` call, and no user-visible warning. The
  analyzer received `annual_rent = 0`, treated it as "no rent available" (`_has_rent = False`),
  and produced a partial analysis record silently. Properties stored in any city whose data had
  never been filled — across Office, Retail, Industrial, Mixed-Use, Retail-Office, Residential,
  and Multi-Family types — were permanently affected. Hotel was immune (its revenue path never
  calls the rate loaders).
- **`_reanalyze_all` silently updated stub-city properties instead of skipping them** — because
  the zero rate never raised `ValueError`, the bulk re-analysis path incremented `updated`
  rather than `skipped` and wrote partial records with `$0` income back to disk on every run,
  making the corruption self-perpetuating.
- **`load_residential_rates` raised `TypeError` on `None`-valued stubs** — the comprehension
  `{k: float(v) for k, v in …}` called `float(None)` after the sentinel migration. Updated to
  `float(v) if v is not None else None`.
- **`_resolve_residential` used `None` per-unit values as `$0/month`** — the per-key lookup
  `elif unit_key in market` fired even when `market[unit_key]` was `None` or `0`, multiplying
  `None × count × 12` (crash) or `0 × count × 12` (silent zero). The guard is now
  `market[unit_key] is not None and market[unit_key] > 0`.
- **City average rate included `None` and `0` stubs** — `known_rates` was built with
  `isinstance(v, (int, float))`, which excluded `None` but passed `0`. A stub city with one
  real rate (e.g., `one_br = 1_200`) and five zeros averaged to `200/month` rather than
  `1_200/month`. Filter updated to `isinstance(v, (int, float)) and v > 0`.

### Added

- **`ensure_city_in_rates` migrates legacy on-disk zero stubs to `None`** — on every call the
  method now iterates all cities in both `commercial_rents.json` and `residential_rents.json`
  and replaces any `0`-valued type/unit entry with `null`. The migration is idempotent (a second
  pass touching only `None` values does nothing) and writes back only when a change was made, so
  the extra I/O on unchanged files is a single read with no write. Existing real rates (non-zero)
  are never touched.
- **`ResidentialRentLoader.get_rates` returns `None` for all-`None` stub cities** — after
  migration a stub city's residential dict contains only `null` values; the loader now returns
  `None` in that case so the existing `if market is None:` guard in `_resolve_residential` fires
  correctly, triggering `log_missing` and the "no rate" breakdown lines.
- **36-test regression suite** — `tests/test_zero_rate_stub_bug.py` covers five layers:
  (1) *Sentinel / migration* — new stubs write `None`; existing zeros are migrated; real rates
  are untouched; migration is idempotent; stub city keys appear in both indexes with `None`
  values; (2) *Loaders* — `CommercialRentLoader` returns `None` for each stub type; residential
  loader returns `None` for an all-`None` city and returns the dict for a partially-populated
  city; `load_residential_rates` does not raise on `None` values; (3) *Resolver — all property
  types* — Office, Retail, Industrial, and Retail-Office all raise `ValueError`; Mixed-Use skips
  the commercial component and logs missing; both-stubs-`None` Mixed-Use returns zero rent;
  residential-only stub logs missing; `log_missing` is called (not bypassed); a pre-fix `0`
  mock is included as a documented regression anchor showing `_has_rent = False`; (4)
  *`_resolve_residential` partial stubs* — `None` per-unit value falls through to city avg;
  `None` values excluded from avg; all-`None` market falls through to missing path; override
  wins over `None` in market; explicit `0` values excluded from avg computation; (5)
  *`_reanalyze_all` end-to-end* — stub-city property is counted as `skipped`, not `updated`;
  `0/1 updated` is confirmed in output; populated-city property is counted as `updated`; stub
  city does not produce income metrics (NOI, Cap Rate, Gross Rent Multiplier); a mixed batch of
  one stub + one real city produces `1/2 updated, 1 skipped`; parametrised over Office, Retail,
  Industrial, and Retail-Office stub types.

---

## [2.0.1] — 2026-06-11

### Fixed

- **Floor count destroyed on re-analysis for unit-less properties** — `_record_to_prop` in
  `ui/menu.py` only built a `UnitMix` when residential units existed, so any unit-less record
  loaded for re-analysis had `unit_mix = None` on the `PropertyInput`. `RentResolver` then fell
  back to `getattr(prop, "floors", 1)` — dead code, since `PropertyInput` has no `floors`
  field — and `to_record()` wrote `floors = 1` back, permanently destroying the stored value.
  Confirmed via data audit: 9 unit-less Retail-Office and 12 unit-less Mixed-Use records all
  showed `floors = 1` with a matching 2026-06-09 batch timestamp. `_record_to_prop` now builds
  a floors-only `UnitMix` (`total_units = 0`) for every unit-less property regardless of type,
  carrying the floor count through the pipeline. This object is behaviourally inert in the
  resolver and analyzer — it exists purely to preserve the value.
- **Retail-Office rent computed as single-floor when no saved rent exists** — with floors
  collapsed to 1 and no stored `commercial_rent`/`annual_rent` (e.g. a CSV row imported without
  rent, or a rent field cleared in the editor), the resolver priced the entire building at the
  ground-floor Retail rate across all square footage instead of splitting it into ground-floor
  Retail plus upper-floor Office. Records with a saved `commercial_rent` were shielded by the
  resolver's short-circuit (rent frozen, not inflated). Fixed by the floor preservation above.
- **`to_record()` no longer stomps floors to 1 when no unit mix is present** — both the
  top-level `floors` key and `unit_mix.floors` now fall back to the existing record's stored
  value (`(existing or {}).get("floors", 1)`) instead of a hardcoded `1`, so any future code
  path that builds a `PropertyInput` without a `UnitMix` preserves rather than destroys the
  stored floor count. The dead `hasattr(p, "floors")` fallback was removed.
- **CSV import dropped floors for unit-less rows** — `csv_handler.py` only built a `UnitMix`
  when residential unit counts were present, so any unit-less row lost its `floors` column on
  first import. A floors-only `UnitMix` is now built for all unit-less rows regardless of
  property type, including when rent is provided.
- **Dead `getattr(prop, "floors", 1)` fallback removed from `RentResolver`** — the attribute
  never existed on `PropertyInput`, so the expression silently always yielded 1 and masked the
  floor-loss bug. The resolver now reads floors from `unit_mix` or defaults to 1 explicitly.
- **First-time entry also lost floors for unit-less non-Retail-Office properties** — on a brand
  new record there is no existing saved record for the `to_record()` fallback to draw from, so
  a new 3-floor Office or unit-less Mixed-Use entered via the add form or CSV silently saved
  `floors = 1` from day one. The interactive add form now also builds a floors-only `UnitMix`
  for all unit-less properties, closing the gap across all three write paths: add form,
  re-analysis, and CSV import.
- **Stored `annual_rent = 0` froze rent at $0 permanently** — `_record_to_prop` coerces falsy
  `commercial_rent` and `residential_rent` to `None` ("not recorded — recompute from market
  rates") but passed a literal `annual_rent: 0` through unchanged. The resolver's short-circuit
  checks `prop.annual_rent is not None`, so `0` was returned as "rent provided directly", every
  income metric (NOI, cap rate, DSCR, IRR) was skipped, and `to_record()` wrote the `0` straight
  back — a self-perpetuating $0 record no re-analysis could heal, even after city rate data
  became available. `annual_rent` now receives the same `or None` coercion as the other two
  rent fields. A data scan confirmed no stored records currently carry a literal zero, so no
  migration was needed.

### Added

- **12-test regression suite for Retail-Office floor loss** — `tests/test_retail_office_floor_loss.py`
  covers four layers: (1) `_record_to_prop` — floors survive record → `PropertyInput` conversion,
  including fallback to the top-level `floors` key for older records, and all unit-less types
  now produce a floors-only `UnitMix`; (2) `RentResolver` — a 3-floor building prices as
  ground-floor Retail plus two upper Office floors, and a missing `UnitMix` defaults to one
  floor; (3) end-to-end — re-analysis preserves floors in both record keys, is idempotent, keeps
  the saved-rent short-circuit intact, recomputes cleared rent across all floors, and
  `to_record()` falls back to the existing record's floors when `unit_mix` is absent; (4) CSV
  import — a unit-less Retail-Office row persists its floors with and without a provided rent.
- **10-test regression suite for zero annual rent** — `tests/test_reanalysis_zero_annual_rent.py`
  covers three layers: (1) `_record_to_prop` — `annual_rent = 0` becomes `None`, `null` stays
  `None`, a positive value survives, and component rents still suppress `annual_rent`;
  (2) `RentResolver` — `None` falls through to the market-rate lookup while a provided non-zero
  rent short-circuits with no lookup; (3) end-to-end — a frozen $0 record recomputes from market
  rates, its income metrics (NOI, Cap Rate) reappear, recovery is idempotent, and a genuine
  provided rent is preserved verbatim.
- **83-test floor-preservation suite covering every property type** —
  `tests/test_floor_preservation_all_types.py` parametrises the full re-analysis round-trip
  (record → `_record_to_prop` → analyzer → `to_record()`) over all eight property types plus
  untyped records across four scenarios: unit-less and with-units re-analysis (single and
  double pass, matching the 2026-06-09 batch-run shape), legacy records missing the `unit_mix`
  dict, genuine `floors = 1` not being inflated, first-save of a brand-new property
  (`to_record(existing=None)`), `_record_to_prop` independently confirmed to carry floors for
  all unit-less types, and CSV import of unit-less rows for all eight named types. The exact
  `_record_to_prop(p)` → `to_record(existing=p)` call chain used by `_reanalyze_all` and
  `_reanalyze_city` was verified clean across all 18 type × unit-count combinations.
- **`find_affected_floor_loss.py`** — read-only diagnostic that scans `properties.json` and
  classifies every unit-less Retail-Office record by exposure: floors still intact (at risk),
  floors already at 1 (possibly destroyed), rent-corruption exposed (no saved rent), or rent
  already computed single-floor.

### Data repair

- **Nine Retail-Office records had their floor counts restored manually** — all nine unit-less
  Retail-Office records in `properties.json` were found at `floors = 1` (all last modified
  2026-06-09, consistent with a single batch re-analysis pass having stomped them). The original
  values were not recoverable from the data file, so the floor counts were re-checked against
  their MLS listings and re-entered by hand (six 2-floor, two 3-floor, one 4-floor). Their
  stored rents were unaffected throughout (all carry an explicit `commercial_rent` that predates
  any single-floor recomputation), and the floor-preservation fixes above now keep the
  re-entered values stable across future re-analyses.

---

## [1.6.1] — 2026-06-11

### Changed

- **Address helpers moved from root `utils.py` to `core/address.py`** — `_display_address` and
  `_parse_address_sort` were the only functions in a catch-all `utils.py` at the project root.
  Both are address-specific and are now co-located in `core/address.py`. Imports updated in
  `ui/menu.py`, `reporting/printer.py`, and `tests/test_utils.py`. `utils.py` deleted.

---

## [1.6.0] — 2026-06-10

### Fixed

- **City report Score mini-stat color now matches the opportunity score** — the Score value shown
  in each city row's mini-stats was colored via `gc('score', act_score)`, which applied green when
  the individual deal score averaged ≥ 70. The city-level opportunity number uses `oppColor`, which
  applies amber for scores between 35 and 65. A city could therefore display a green "Score 72"
  alongside an amber "50 / 100", creating a visually contradictory signal. The mini-stat span now
  uses `style="color:${barColor}"` (the same `oppColor` derivation as the opportunity number), so
  the two always share the same color.

### Tests

- **`TestIncomeMetrics` — 3 new tests for construction cost in cap rate** (`test_metrics_income.py`):
  verifies that `cap_rate` and `entry_cap` use `asking_price + construction_cost` as the cost basis,
  and that a non-zero construction cost produces a lower cap rate than the same property without one.
- **`TestConstructionCostPropagation` — 7-test class added to `test_analysis_analyzer.py`**: covers
  the full propagation of `construction_cost` through the analyzer — cost basis in pricing, cash
  invested in cash flow, cap rate reduction, IRR reduction, "Construction Cost" / "Total Cash In"
  mortgage rows appearing when cost > 0 and absent when 0, and persistence via `to_record()`.
- **`TestCityReportGenerator` — 2 new tests for Score mini-stat color** (`test_reporting_generators.py`):
  asserts the rendered HTML contains `style="color:${barColor}"` for the Score span, and that the
  old class-based `Score <span class="${gc(` pattern is absent.

---

## [1.5.0] — 2026-06-10

### Fixed

- **City opportunity score weights rebalanced to sum to 1.00** — addition of `absorption_rate`
  and `price_trend` as scoring factors had pushed the total weight to 1.05, allowing raw
  opportunity scores to exceed 100. Weights across all 15 city score factors have been
  redistributed in `json/score_weights.json` so they sum exactly to 1.00.
- **`act_irr`, `act_dscr`, and `act_cf` now contribute to city opportunity score** — these three
  metrics were averaged per city and included in the report output but were absent from the `raw`
  formula in `CityRanker.rank()`. They are now scored factors with weights and thresholds
  configurable via `json/score_weights.json`.
- **`best_score` now contributes to city opportunity score** — the highest individual property
  score within a city is now a scored factor, reflecting the peak deal quality available in that
  market.
- **`inact_cap` threshold ceiling raised from 9% to 10%** — brought into line with the `act_cap`
  ceiling; having different ceilings for the same metric on active vs. inactive listings was
  skewing `cap_trend` interpretation.
- **`act_cap` threshold ceiling raised from 9% to 10%** — cap rates above 9% are achievable in
  secondary markets; the previous ceiling was penalising high-yield cities unnecessarily.
- **`act_coc` threshold ceiling raised from 12% to 15%** — widens the scoring range for
  cash-on-cash return, giving stronger deals room to differentiate.
- **`act_dom` threshold floor raised from 0 to 30 days** — listings under 30 days on market
  receive no DOM score contribution; very fresh listings do not indicate seller motivation.
- **`_avg` helper no longer silently drops zero values** — the previous implementation excluded
  any entry where the metric value was `0`, treating it the same as `None`. Zero is a valid
  value for DOM (listed today) and price drop (no reduction); the helper now only excludes
  `None`. Zero-sentinel handling is now done via `or None` at the point of data collection.

---

## [1.4.0] — 2026-06-09

### Fixed

- **Residential rent silently zeroed on re-analysis for properties created before city data existed** —
  `RentResolver.resolve()` opened with an early-exit that fired whenever either `commercial_rent`
  or `residential_rent` was not `None` on the `PropertyInput`. Mixed-Use properties stored before
  residential rent data was available for their city had `residential_rent = 0.0` written to disk;
  on every subsequent re-analysis `_record_to_prop` converted that `0.0` to `None` (via `or None`),
  which still satisfied the `commercial_rent is not None` branch, causing the early-exit to return
  the commercial-only total and write `residential_rent = 0.0` back — permanently. The resolver
  now checks whether the property has residential units (`unit_mix.total_units > 0`) with no
  recorded residential income (`residential_rent` is `None` or `0.0`); when that condition holds
  the early-exit is bypassed and the full mixed-use calculation runs, correctly picking up the
  now-available city residential rates.
- **Six Midland Mixed-Use properties updated on disk** — as a one-time migration the stale records
  were re-analysed and saved with the correct residential rent components: 262 King St (+$37,200/yr),
  276 King St (+$24,600/yr), 290 King St (+$172,200/yr), 261 King St (+$37,200/yr),
  289 King St (+$49,200/yr), 253 King St (+$49,200/yr). 270 King St (Retail-Office, no residential
  units) was unaffected.

### Added

- **17-test regression suite for stale residential rent** — `tests/test_reanalysis_stale_residential.py`
  covers three layers: (1) `_record_to_prop` — verifies `residential_rent = 0.0` becomes `None`,
  `commercial_rent` is preserved, `unit_mix` is rebuilt, and `annual_rent` is suppressed when
  explicit rent fields are present; (2) `RentResolver` — verifies `None` and `0.0` both trigger
  recalculation while a positive `residential_rent` still short-circuits; (3) end-to-end pipeline —
  verifies `to_record()` writes the correct `residential_rent`, that re-analysis is idempotent
  (running twice produces identical output), that NOI improves after recalculation, and that a
  no-unit property is unchanged.

---

## [1.3.0] — 2026-06-08

### Fixed

- **Explicit commercial and residential rent now honoured on property add** — `commercial_rent`
  and `residential_rent` are now separate named fields on `PropertyInput` (previously the menu
  collapsed them into a single `annual_rent`, causing the resolver to treat residential rent as
  commercial rent and always write `residential_rent = 0` to the record). `RentResolver.resolve()`
  now checks these fields first (Mode 0) and returns immediately without touching city-data
  lookups; the existing annual_rent / city-data fallback chain is unchanged.
- **Unit mix (bachelor/1BR/2BR/…) now preserved when explicit rent is provided** — `_prompt_property`
  in `ui/menu.py` previously only built a `UnitMix` object when no explicit rent was given;
  entering unit counts alongside a rent figure silently discarded the counts. A `UnitMix` is now
  always constructed when `total_units > 0`, regardless of whether `commercial_rent` or
  `residential_rent` was also provided.
- **`_record_to_prop` passes explicit rent fields on re-analysis** — saved records that contain
  non-zero `commercial_rent` or `residential_rent` are now loaded back into `PropertyInput` via
  those fields instead of being collapsed into `annual_rent`, preserving the correct split on
  every re-analysis.
- **Expense ratio prompt removed from Add Property form** — `ask_pct("Expense ratio %", 40)` has
  been removed from `_prompt_property` in `ui/menu.py`; `expense_ratio=None` is now passed to
  `PropertyInput`, which resolves the correct type-specific default via `__post_init__` using
  `EXPENSE_RATIO_DEFAULTS` in `models/constants.py` (e.g. hotel → 0.63, NNN → 0.08). The
  previous prompt always defaulted to 40% regardless of property type.
- **`_record_to_prop` expense ratio fallback corrected** — the hardcoded `0.40` fallback when
  loading a saved record without a stored ratio has been replaced with `None`, so old records
  now receive the correct type-specific default on next load rather than a flat 40%.
- **Expense ratio reset when lease type or property type is edited** — editing either field in
  the edit form now writes `expense_ratio = None` to the store so it recomputes from the
  updated type on the next load, preventing a stale ratio from persisting after a type change.
- **CSV ingestion no longer defaults expense ratio to 40%** — `csv_handler.py` now passes `None`
  when the expense ratio column is blank, deferring to the type-specific default rather than
  hardcoding 40%.
- **Add Property form fields now loop until valid input** — four fields that previously returned
  `None` silently on blank input (dropping the user back to the main menu mid-entry) have been
  replaced with `while True` loops: Original price (required), MLS # (required), Annual property
  taxes (required), and Total sq ft (defaults to 5,000, shown in prompt). Hotel rooms now
  defaults to 0 instead of requiring explicit entry.

### Added

- **36-test suite for explicit rent inputs** — `tests/test_explicit_rent_inputs.py` covers all
  eight property types (Office, Retail, Industrial, Mixed-Use, Hotel, Retail-Office, Residential,
  Multi-Family) across: explicit rent bypasses city-data lookup, correct `_comm_rent`/`_res_rent`
  split, unit mix preservation, city-data fallback when no explicit rent is given, and breakdown
  message labelling.

---

## [1.2.0] — 2026-06-08

### Fixed

- **HTML modal Market Staleness row now renders** — `property_report.py` imports
  `METRIC_MARKET_STALENESS` from `analysis/metrics/returns.py` and interpolates it via a
  local `staleness_key` variable into the JS `SECTIONS` array. The previous template contained
  the literal string `"{METRIC_MARKET_STALENESS}"` which never matched any result key, making
  the Market Staleness row permanently invisible in the modal.
- **HTML modal Price/Sq Ft row now renders** — Pricing section key changed from the exact
  string `"Price/Sq Ft"` to the wildcard `"Price/Sq Ft (*"`, matching the dynamic
  `f"Price/Sq Ft ({property_type})"` label emitted by `PricingMetrics`. The row was never
  visible for any property type.
- **HTML modal Income section keys corrected** — four stale or missing keys fixed:
  `"Annual Rent"` → `"Gross Potential Rent"` (matching `IncomeMetrics` output);
  `"Entry Cap Rate"` removed (metric is no longer emitted); `"Effective Gross Income"` and
  `"Vacancy Rate"` added (both emitted but previously absent from the key list).
- **HTML modal Hotel NRevPAR rows now render** — the single key `"NRevPAR"` replaced with
  three explicit keys `"NRevPAR (low dist.)"`, `"NRevPAR (mid dist.)"`, and
  `"NRevPAR (high dist.)"`, matching the labels emitted by `HotelMetrics`. All three rows
  were previously invisible.
- **City ranker `n_active` weight corrected** — `city_score_weights.n_active` reduced from
  `0.20` to `0.15` in `json/score_weights.json`; weights now sum to exactly `1.00`. The
  previous total of `1.05` allowed the raw opportunity score to exceed 100.
- **Price/Sq Ft suppressed for non-sqft asset classes** — `PricingMetrics` now sets
  `_show_sqft = ptype not in {"hotel", "residential", "multi-family"}` and skips the
  Price/Sq Ft row for those types. Hotel, residential, and multi-family properties do not
  trade on a price-per-sqft basis and the metric was misleading.
- **Mixed-use Price/Sq Ft uses commercial floor area** — `PricingMetrics` accepts a new
  `comm_sq_ft` parameter; `CommercialPropertyAnalyzer` passes
  `getattr(rent_resolver, "_comm_sq_ft", None)`. For mixed-use properties the denominator
  is now the commercial floor area rather than total building sqft, which previously inflated
  the metric by including residential floors.
- **Mixed-use `city_rent_per_sqft` now populated** — `RentResolver.resolve()` sets
  `self._city_rent_per_sqft = comm_rate` and `self._comm_sq_ft = floor_sq_ft` inside the
  `is_mixed` branch when a commercial rate is found. Previously the attribute was only set
  in the pure-commercial branch, leaving mixed-use properties with static sqft thresholds.
- **DOM scorer uses shared constant** — `PropertyScorer.score_property()` now looks up the
  DOM metric via `METRIC_MARKET_STALENESS` (imported from `analysis/metrics/returns.py`).
  Any future rename of the label only requires updating the one constant.
- **Listing date prompted on first add** — `_prompt_property()` in `ui/menu.py` now prompts
  for the listing date (defaulting to today) so that properties with a historical listing
  date correctly compute Days on Market from the first save.

### Changed

- **Unknown-city Location score is intentionally zero** — `PropertyScorer` returns
  `Location = 0.0` when a city has no entry in `json/city_distances.json`. This is now
  documented as deliberate: an unknown location is treated as worst-case rather than neutral,
  to incentivise keeping the distances file current. The corresponding xfail tests were
  replaced with passing assertions that verify the zero value.

---

## [1.1.0] — 2026-06-08

### Added

- `INCOME_METRIC_NAMES` — canonical `frozenset` exported from `analysis/metrics/income.py`
  and imported by `scoring/scorer.py`, `ui/menu.py`, and `reporting/printer.py`; replaces three
  independent inline sets that contained stale metric names.
- `ExitMetrics` and `ReturnMetrics` now accept an explicit `noi_growth_rate` keyword argument,
  making the growth rate an injected dependency rather than a side-effect read from `prop`.
- `ReturnMetrics.__init__` now accepts `noi_growth_rate: Optional[float]` directly from the
  analyzer, removing the implicit coupling to `prop.noi_growth_rate`.
- `CommercialPropertyAnalyzer` stores the resolved NOI growth rate as `self._noi_growth_rate`
  and surfaces it via `to_record()`, replacing the previous mutation pattern.
- `to_record()` now persists `vacancy_rate` and `noi_growth_rate` to the saved JSON record so
  that re-analysis reproduces the same figures without re-querying demographics data.
- `_parse_listing_date()` helper in `ui/menu.py`; `_prompt_property` now prompts for the
  listing date with a default of today, allowing historical dates to be entered on first add.
- `city_score_weights` and `city_score_thresholds` sections added to `DEFAULT_SCORE_CONFIG` in
  `scoring/scorer.py`, making all city opportunity score weights and thresholds user-configurable
  via the scoring menu.
- `val_prefix()` inner helper in `PropertyScorer.score_property()` for prefix-based metric
  lookups.

### Changed

- **Exit price now uses terminal NOI** — `ExitMetrics` computes
  `terminal_noi = est_noi × (1 + g) ^ hold_years` before dividing by the exit cap rate.
  Previously used year-1 NOI, understating exit value by ~22% on a 10-year hold at 2% growth.
- **IRR cash flows now hold the mortgage constant** — `ReturnMetrics` builds yearly flows as
  `year1_noi × (1 + g) ^ (yr − 1) − annual_mortgage`, accepting `year1_noi` as a dedicated
  parameter. The previous implementation escalated the full `(NOI − mortgage)` bundle, inflating
  late-year cash flows.
- **IRR row label is now dynamic** — `ReturnMetrics.rows()` emits `f"IRR ({hold_years}-Yr)"`
  instead of the hardcoded `"IRR (5-Yr)"`.
- **Scorer IRR lookup is now prefix-based** — `val_prefix("IRR (")` replaces
  `val("IRR (5-Yr)")`, preventing the IRR contribution from silently zeroing out for any
  hold period other than five years.
- **Break-even occupancy formula corrected** — `DebtMetrics` second parameter changed from
  `est_expenses: float` to `expense_ratio: float`; BEO is now computed as
  `annual_mortgage / (annual_rent × (1 − expense_ratio))`, the standard variable-expense
  formulation. The previous formula mixed an EGI-adjusted numerator against a gross-rent
  denominator, producing an inconsistently scaled result.
- **`CommercialPropertyAnalyzer` no longer mutates `PropertyInput`** — NOI growth rate is
  resolved into `self._noi_growth_rate` and passed explicitly to `ExitMetrics` and
  `ReturnMetrics`. `prop.noi_growth_rate` is left unchanged by the analyzer.
- **`_view` partial-results advisory** now uses `COMMERCIAL_TYPES_LOWER` (imported from
  `models.constants`) instead of a hardcoded tuple that excluded `hotel` and `retail-office`,
  which caused those types to display the wrong advisory message and point to the wrong menu
  option.
- **City ranker weights refactored** — hardcoded float literals replaced with lookups against
  `cfg["city_score_weights"]`, making all nine city-score factors configurable at runtime.

### Fixed

- `IncomeMetrics.rows()` no longer emits an `"Entry Cap Rate"` row; the value was identical to
  `"Cap Rate"` (same formula, same result), producing a duplicate row in every analysis report.
- `IncomeMetrics.rows()` suppresses the `"Vacancy Rate"` row for hotel properties. Hotel revenue
  is modelled via `rooms × ADR × occupancy × 365`, so a `0.0%` vacancy figure was misleading
  alongside the `"Occupancy Rate"` row already shown by `HotelMetrics`.

### Removed

- `"Entry Cap Rate"` row from `IncomeMetrics.rows()` (see Fixed above).

---

## [1.0.0] — 2026-05-01

### Added

- Full object-oriented refactor of the analysis pipeline.
- `ui/menu.py` split into four modules using the mixin pattern:
  `PropertyMenu`, `RateEditorMixin`, `ConfigEditorMixin`, `CsvHandlerMixin`.
- `models/constants.py` — sourced benchmark defaults:
  `VACANCY_RATE_DEFAULTS`, `EXPENSE_RATIO_DEFAULTS`, `EXPENSE_RATIO_RANGES`,
  `PROP_SHORTCUTS`, `PROPERTY_TYPES`, `COMMERCIAL_TYPES`, `COMMERCIAL_TYPES_LOWER`.
- `PropertyInput.__post_init__` auto-resolves `expense_ratio` and `vacancy_rate` from
  `models/constants.py` when `None` is supplied.
- `IncomeMetrics` — models vacancy: `EGI = annual_rent × (1 − vacancy_rate)`;
  expenses and NOI derived from EGI.
- `ExitCapEstimator` — exit cap built from entry cap plus an aging spread
  (10 bps/yr, capped at 10 years) and a market drift spread (25 bps).
- `ReturnMetrics` — Newton-Raphson IRR; equity multiple accounts for principal
  paydown via `exit_equity = exit_price − loan_balance`.
- `MarketMetrics` — seller bleed scaled by `vacancy_rate`.
- `HotelMetrics` — three NRevPAR scenarios: low / mid / high distribution cost.
- `IndustrialMetrics` — per-component income breakdown with clear-height premium.
- `PricingMetrics` — per-type GRM thresholds; price/sqft thresholds derived from
  `GRM × city_rent_per_sqft` when a market rate is available.
- Per-type expense ratio range validation with contextual warning messages.
- NOI growth rate resolved from `json/city_demographics.json` with staleness detection;
  defaults to 2 % when no locale data is present.
- `METRIC_MARKET_STALENESS` constant shared between `returns.py` and `scorer.py`.
- `README.md` v1.0 — purpose of every file, directory, JSON schema, menu reference,
  metrics glossary, and quick-start guide.
- `pytest` suite with branch coverage; `fail_under = 90` enforced via `.coveragerc`.

### Fixed

- `FileNotFoundError` on `json/commercial_rents.json` when selecting menu option 7
  before any properties have been saved; replaced with a user-friendly message and
  graceful return to the main menu.

### Removed

- `htmlcov/` directory and `--cov-report=html` flag from `pytest.ini`; VS Code
  Coverage Gutters reads `coverage.xml` directly.
