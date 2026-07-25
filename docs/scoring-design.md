# Scoring design decisions

Record of the structural scoring changes made in July 2026 in response to a
read-only diagnostic. For each change: **what** changed, **why**, the
**alternative** that was rejected, and what it **means for score interpretation**.
A final section collects the judgment calls that are *deliberate, non-standard
choices* so they are not mistaken for conventions.

Measurements are on the live data set: **639 properties across 109 cities**,
re-analysed through the real pipeline (not synthetic fixtures). "Before" figures
are the pre-fix `main` behaviour; "after" figures are quoted per fix and again in
[Validation](#validation).

## How scoring works (context)

Two scores are produced from the same per-property analysis records:

* **Property score (0–100).** A weighted blend of normalised factors
  (`scoring/scorer.py`). Each factor `component(key, x)` maps a raw metric `x`
  onto `0..10` via a linear ramp `[lo, hi]` with a hard clamp:
  `clamp((x-lo)/(hi-lo), 0, 1)`. Weights and ramps live in
  `json/score_weights.json`. Factors with weight 0 (Price Drop, DOM) are computed
  and displayed but not scored.
* **City opportunity (0–100).** `scoring/city_ranker.py` aggregates property
  metrics per city into a **quality** sub-score (weighted blend of normalised
  market factors) and a **depth** sub-score (log of active inventory), then takes
  their weighted geometric mean. Quality factors use their own ramps in
  `city_score_thresholds`.

The clamp is the crux of several problems below: it is a **non-linear** function,
so *the order of "average" and "normalise" matters* (Fix 1), and everything below
`lo` collapses to an indistinguishable `0` (Fix 2).

---

## Fix 1 — Per-listing normalisation before averaging (city factors)

**What changed.** In `city_ranker.py`, city metric factors (active cap rate,
CoCR, IRR, DSCR, cash flow, price drop, days-listed, and inactive cap rate) are
now normalised **per listing first, then averaged**. Previously the raw metric
was averaged across active listings and the single city mean was normalised
against `[lo, hi]`. The displayed city averages (e.g. "Cap Rate (Active) 6.2%")
are unchanged — only the *factor score* feeding opportunity changed.

**Why.** `normalise()` is non-linear (a clamped ramp), so by Jensen's inequality
`mean(f(x)) ≠ f(mean(x))`. Averaging first destroys within-market variation and,
worse, silently zeroes real signal: Kingston has an active listing at **8.19%
IRR** against a city IRR floor of 8.0, but because the *market mean* IRR is 5.8%
(below the floor) the whole factor scored exactly **0.0** — the one genuinely
strong listing was erased. Normalising each listing first preserves it: values
above the floor contribute their real strength even when the mean sits below it.

**Alternative rejected.** Keep average-then-normalise but lower the floors so the
mean clears them. Rejected: it treats a symptom (floors "too high") rather than
the cause (clamping a mean), would need constant re-tuning per metric, and still
compresses a city of uniformly-mediocre listings and a city with one star listing
into the same number.

**Interpretation.** City factor scores now reflect *how many listings clear the
bar and by how much*, not *whether the town's average does*. This is strictly
more information. Cities that previously scored a hard 0 on a factor despite
having qualifying listings now score proportionally.
Effect (Fix 1 in isolation): cities scoring exactly 0.0 on the four collinear
factors dropped from **CoCR 71 / IRR 66 / DSCR 68 / Cash-Flow 69 (of 109)** to
**CoCR 57 / IRR 57 / DSCR 57 / Cash-Flow 57** — i.e. **14 / 9 / 11 / 12** cities
moved 0.0 → non-zero. Kingston's IRR factor is the cited case: **0.0 → 0.11**, its
8.07 / 8.19 / 9.63% listings now counted instead of erased by a 5.8%-mean floor.
The remaining 57 are cities whose active listings are *all* below the floor
(genuinely no qualifying listing) — Fixes 2 (negative floors) and 3 (IRR
recalibration) reduce these further. Overall property scores are unchanged (Fix 1
touches only city opportunity); opportunity compresses slightly at the top
(max 59.3 → 58.9) as within-market variation is restored.

---

## Fix 2 — Scoring floors extended into negative territory

**What changed.**
* **CoCR** ramp `[0, 12]` → **`[-10, 15]`** (`json/score_weights.json`
  thresholds *and* the city `act_coc` threshold).
* **Cash Flow** is no longer scored on **absolute dollars** `[0, 50000]`. It is
  converted to a **size-relative** measure — annual cash flow as a **percent of
  asking price** — and scored on **`[-6, 8]`** (property scorer and city
  `act_cf`). Displayed dollar cash flow is unchanged.

**Why.** With a `[0, …]` floor every negative value clamps to an identical 0: a
property at **−0.77% CoCR** scored the same as one at **−50%**. 291 of 635 scored
properties had negative CoCR, all pinned at 0 — no rank order among the deals that
are *closest to break-even*. Extending the floor below zero restores that order.
The absolute-dollar Cash-Flow ramp also carried a **deal-size bias**: a \$20M
industrial trivially clears a \$50k threshold that a \$5M mixed-use cannot, so the
factor rewarded size rather than performance. Percent-of-price removes that; the
observed distribution (min −5.74%, p5 −3.14%, median 0.28%, p90 6.10%) makes
`[-6, 8]` capture the **entire** negative tail with no clamping (full rank
preservation on the downside) while only the strongest ~7% of deals clamp at the
top.

**Alternative rejected.** A larger negative floor (e.g. CoCR `[-100, 15]`) to
give every catastrophic deal its own slot. Rejected: below roughly −10% CoCR the
deals are all simply "uninvestable", and stretching the ramp there would compress
resolution in the −10..0 band that actually matters for ranking near-miss deals.
`-10` is where "bad" becomes "catastrophic"; both still score ~0.

**Measured effect.** Properties scoring exactly 0 on the CoCR factor fell
**291 → 75** (the 75 are CoCR < −10, the deliberate catastrophic band); on the
Cash-Flow factor **291 → 0** (the observed min −5.74% sits inside the −6 floor, so
every deal is now ranked). At city level, `act_coc` zeros fell **57 → 36** and
`act_cf` **57 → 27**. The property-score median rose 34.0 → 43.5 as near-break-even
deals stopped collapsing onto 0; the concentrated low band [10,30) thinned
272 → 204.

**Interpretation — read this carefully.** A negative CoCR is **still a failing
deal.** These floors do **not** make negative cash-on-cash acceptable; they only
sort the *least-bad* below-threshold deals above the catastrophic ones so the
ranking is monotonic through zero. A property scoring, say, 8/100 on the CoCR
factor at −4% CoCR is *not* "8% good" — it is "the top of the failing pile."
The floor values are a **ranking-resolution choice, not an industry convention**
(see [deliberate choices](#deliberate-non-standard-choices)).

---

## Fix 3 — Modelled hold shortened 30 → 10 years

**What changed.** `config/financing.json` `defaults.hold_years` **30 → 10**. The
IRR scoring ramp was recalibrated to the resulting distribution
(`[4, 20]` → **`[0, 18]`**).

**Why.** Equity Multiple over a 30-year hold with 2% NOI growth is ~8.5× at the
median — far past the `[1, 3]` ramp ceiling — so **EM scored ~100/100 for almost
every property** (median 100, σ 5.1). A factor carrying 10% of the weight was
acting as a near-constant, contributing nothing to discrimination. A 10-year hold
is also **standard institutional practice** (ARGUS and major-brokerage
underwriting default to a 10-year hold), so this both restores EM's discriminating
power and aligns the model with convention. Shortening the hold changes IRR and EM
for every property, so the IRR ramp was re-fit to the new spread rather than left
at values tuned for 30-year cash flows.

**Alternative rejected.** Keep 30 years and simply re-scale the EM ramp (e.g.
`[3, 12]`). Rejected: it would rescue EM's spread but leave the model quoting
30-year IRRs and multiples that no institutional buyer underwrites, and it
compounds the NOI-growth assumption over an implausibly long horizon.

**Recalibration & measured spread.** EM median fell **8.45× → 1.96×**; the EM
*factor score* went from median 100 / σ 5.1 (a constant) to **median 48 / σ 36.9**
(a real discriminator) — the `[1, 3]` ramp needed no change. IRR shifted down and
widened: 30-yr p25/median/p75 were 5.2 / 8.8 / 15.1; 10-yr are **0.8 / 7.4 / 15.8**
(p10 −6.6, p90 28.6, 148 of 630 now negative). The IRR ramp was recalibrated
**`[4, 20]` → `[0, 18]`** (property *and* city `act_irr`, which had been `[8, 20]`
— a floor sitting *above* the new median, the cause of its high zero count). Floor
0: a negative 10-yr IRR is a failing deal and piles at 0 like CoCR < −10; ceiling
18 ≈ the new p80 (strong value-add). City `act_irr` zeros fell 62 → **44**.

**Interpretation.** IRR and EM now describe a **10-year hold**. Scores fell overall
(median 43.5 → 39.6) because the 30-year horizon had been inflating weak deals via
NOI-growth compounding; the 10-year hold exposes them. The bottom band [0,10) grew
to 112 properties — but these are spread across **55 distinct score values** (no
identical pile), i.e. genuine discrimination among weak deals, not a new zero
cluster. Any saved or exported returns from before this change are on a different
horizon and are not comparable.

---

## Fix 4 — Per-asset-type financing defaults (verification + audit)

**What changed.** The per-type financing layer (`config/financing.json` +
`analysis/financing_config.py`) already resolves down-payment / rate /
amortisation **by asset class** (introduced earlier). This fix **verified** it
against source, **audited** the data it depends on, and added a per-type
**covenant DSCR** parameter used by Fix 6.

* **CMHC MLI Select parameters verified** against current CMHC documentation
  (2025–26): 95% LTV at the top (100-point) tier, up to 50-year amortisation,
  1.10 minimum DCR across tiers — matching the config. No change required.
* **Unit-count audit.** The 5-unit CMHC threshold routes on
  `unit_mix.total_units`. Of 187 Multi-Family records, **only 4 have a missing /
  zero unit count** (92 are 1–4 units, 91 are 5+). The field is well-populated;
  the "silent fallback to conventional" risk is real but confined to those 4
  records, which are flagged. (Across *all* 639 records, 133 have no unit count,
  but unit count is irrelevant to non-multifamily types, which do not route on
  it.)
* **Covenant DSCR per type** added (`covenant_dscr`), equal to each type's
  lending `dscr_floor` for consistency, with a residential 1–4 fallback of 1.10
  (that class qualifies on borrower GDS/TDS, not a project DSCR).

**Why.** The diagnostic asked to confirm the model scores each class on terms it
can *actually obtain* rather than a single global best case, and to prove the
5-unit threshold is not silently mis-routing. Both are now evidenced, not assumed.
The covenant parameter must be per-type because 1.20 (conventional commercial)
does not apply to CMHC-insured multifamily (1.10) — hard-coding one value would
mis-score the robustness margins in Fix 6.

**Alternative rejected.** Re-underwrite 5+ MF onto conventional terms for scoring
and show MLI Select only as upside. Rejected: MLI Select *is* the realistic
obtainable program for eligible 5+ multifamily in Canada, and the diagnostic's own
framing ("falling back to conventional … **understating** those deals") treats the
MLI terms as the correct basis for that class. "Do not default to best-case"
governs *across* classes (office stays conservative, mixed-use gets no CMHC) — not
a demotion of multifamily below its real financing.

**Interpretation.** Multifamily 5+ (loan ≥ \$1M) is scored on MLI Select; below
\$1M on conventional (small-balance CMHC rarely pencils); 1–4 on residential;
office most conservative; mixed-use/retail/industrial conventional commercial. A
deal's score reflects **its** financing regime, so cross-class score comparisons
already embed different leverage.

---

## Fix 5 — Break-even financing diagnostic

**What changed.** A displayed diagnostic (`analysis/metrics/financing_robustness.py`)
states the financing terms a deal needs to reach **positive cash flow and DSCR ≥
its covenant**, e.g. *"positive at 5.50% / 30yr; negative at 6.50% / 25yr."*
Deals that fail under **all** realistic terms (best-case of the type's rate/amort
band) are flagged as a **distinct category** ("fails under all realistic terms")
rather than lumped with deals that merely miss current assumptions.

**Why.** A single pass/fail at the current rate hides *how close* a deal is and
*what would fix it*. Separating "fails now but works at obtainable terms" from
"fails at every obtainable term" is the difference between a negotiation target
and a structural non-starter.

**Interpretation.** This is a **diagnostic, not a score input** — it is
threshold-independent and comparable across asset classes (see Fix 6). "Positive
at X" is a fact about the deal, not a grade. On this book the verdict splits
**237 pass at current terms · 38 conditional · 355 fail under all realistic
terms** (of 630 debt-financed deals) — a blunt reminder that most of the screened
inventory is thin-margin market estimates, not that the diagnostic is harsh.

---

## Fix 6 — Financing robustness as a scored factor

**What changed.** A new scored factor, **Financing Robustness**, computed in
`analysis/metrics/financing_robustness.py` and weighted in `score_weights.json`.
Its weight is taken **from the collinear group**: CoCR / DSCR / Cash Flow are three
views of the same NOI-minus-debt-service relationship, so the model now **scores
CoCR** (the returns view) and **displays DSCR and Cash Flow** (weight 0), freeing
their weight for robustness.

Weights: CoCR 0.20 (kept), DSCR **0.15 → 0**, Cash Flow **0.05 → 0**, Financing
Robustness **0 → 0.20** (total unchanged).

**Two separate readings, not one blend.** Rate risk and amortisation risk are
reported separately because they are different kinds of exposure:
* **Rate risk is scheduled and certain** — the term matures on a known date and
  renews at the market rate. Weighted **more** (0.7 of the factor).
* **Amortisation risk is conditional** — it only bites on a *forced* refinance
  into a shorter schedule. Weighted **less** (0.3).

For each, two break-even points are computed and reported:
1. **Covenant breach** — the rate rise (or amortisation cut) at which DSCR falls
   below the per-type covenant.
2. **Cash-flow zero** — the point at which annual cash flow hits zero (DSCR 1.00).

Both margins **and the spread between them** are surfaced, because their ordering
is itself the signal: covenant breach usually arrives first, while cash flow is
still positive — *the lender acts before the owner feels pain*. The reverse
ordering means the owner can fund the shortfall out of pocket while still in good
standing. Glanceable output, e.g. *"covenant breach +40bps · cash flow zero +85bps
· amortisation tolerance −4yr."*

The scored sub-score uses the **covenant-breach** margins (the binding constraint):
`robustness = 100 · (0.7 · clamp(rate_margin_bps / 250, 0, 1) + 0.3 ·
clamp(amort_margin_yr / 10, 0, 1))`. The reference denominators (250 bps, 10 yr) and
the 0.7 / 0.3 split live in `config/underwriting.json`; 250 bps because a deal that
absorbs +250 bps to *covenant* is genuinely robust (only ~10% of passing deals do),
10 yr likewise for amortisation headroom. A covenant-breached deal (negative margin)
scores 0 on robustness — it has no robustness — and the ordering *among* breached
deals is preserved by the displayed margins and by the other negative-floor factors
(CoCR, Cash Flow, IRR), not by this factor.

**Why.** A deal profitable only at low rates and stretched amortisation is more
fragile than one profitable at higher rates and shorter amortisation, but the old
score could rank the fragile one higher. Financing fragility is a **property of the
deal**, so it belongs in the score, not a footnote. And unlike the scoring ramps,
this measure is **threshold-independent**: "breaks at +180 bps" is an absolute fact
about the deal, comparable across asset classes, price bands and financing regimes,
and valid regardless of whether the other ramps are perfectly calibrated. That
absoluteness is exactly why it is a good anchor for the collinear weight.

**Alternative rejected.** Blend rate and amortisation risk into one "financing
stress" number. Rejected: it conflates a *certain, scheduled* exposure with a
*conditional* one and hides the covenant-vs-cash-flow ordering that tells you
whether the lender or the owner moves first.

**Covenant DSCR is per-type, not hard-coded.** 1.20 is common for conventional
commercial but CMHC-insured multifamily runs 1.10; the covenant is the per-type
`covenant_dscr` from Fix 4 so the two configurations stay consistent.

**Pending vs measured (stale records).** A record analysed before this factor
existed has no stored `financing_robustness`. That absence is treated as *not yet
measured*, **not** a real 0: the scorer **drops the factor and renormalises the
remaining factors to their original relative weights**, and the score breakdown
renders "Pending re-analysis" instead of a 0.0 bar. Substituting 0 would silently
dock such a deal ~20% and be indistinguishable from a genuinely fragile one. A
stored 0.0 *is* a genuine "maximally fragile" measurement and is kept. Full
accuracy still needs a re-analysis (a stale record's other metrics are also on the
old horizon), but the score is never invisibly penalised for the missing factor.

**Interpretation.** A high robustness score means the deal survives a large rate
shock before the lender intervenes; a low score means thin margin. Because DSCR and
Cash Flow are now display-only, the card still shows them — they are not gone, just
not double-counted against the robustness factor that already captures the same
NOI-vs-debt-service relationship under stress.

**Measured effect.** Of 630 debt-financed deals, **393 (62%) already sit below their
covenant** at current terms (median rate margin −147 bps) — so robustness is 0 for
the majority, honestly reflecting a book of thin-margin market estimates. Robustness
score σ is 42.6 (a strong discriminator among the deals that *do* have margin). At
the whole-score level this **widened** the spread (σ 27.1 baseline → 31.6) and left
433 distinct score values across 635 properties (largest tie 11), i.e. it added
signal without re-piling the bottom.

---

## Fix 7 — Card labels reconciled to scoring ramps

**What changed.** The property-card metric colours (`reporting/property_report.py`,
`metricClass`) and the city-card thresholds/sub-labels
(`reporting/city_report.py`, `gc()` and the "≥7% strong" captions) were realigned
to the **actual scoring ramps**. A metric is coloured green at/above the ramp
**ceiling** (`hi`, "strong"), red below the ramp **floor** (`lo`), amber on the
ramp between them; sub-labels quote the real ramp instead of invented thresholds.

**Why.** The cards previously advertised "≥7% cap strong," "≥10% CoCR strong,"
"≥15% IRR strong," "≥1.5 DSCR strong" while the engine scored on entirely different
boundaries — a card could show a green "DSCR 1.50" that the engine scored 58/100.
Displayed thresholds that contradict the scoring boundaries are actively
misleading.

**Interpretation.** Card colour now means the same thing as the score: green =
at/above the ramp ceiling the engine rewards, red = below the floor it treats as
failing. The colour and the number finally agree.

---

## Covenant score cap (post-hoc gate)

**What changed.** After the weighted score is computed *and* after the confidence
haircut and every other adjustment, a final **cap** is applied
(`scoring/scorer.py`): if a property's current (unstressed) DSCR is below its
per-asset-type covenant, the final score is clamped to at most
`covenant_score_cap` (config `json/score_weights.json`, currently **60**). The cap
resolves the covenant from config (the same per-type `covenant_dscr` as Fix 4/6 —
never hardcoded), floors nothing (it only lowers), and is skipped entirely when
DSCR is unavailable (`"N/A (no debt)"` or a stale record with no DSCR row) so a
missing value can never trigger a false cap.

**Why a cap, not restored DSCR weight.** Covenant compliance is a **gate**, not a
factor that strong projected returns can average away: a deal that cannot cover
debt service at today's rates should not present as mid-tier-or-better on the
strength of IRR/EM. Re-adding DSCR as a weighted factor would (a) reintroduce the
collinearity Fix 6 deliberately removed (CoCR/DSCR/Cash-Flow are one relationship)
and (b) still be *outweighable* — a high enough IRR could buy back the DSCR
penalty. A post-hoc ceiling cannot be outweighed. DSCR stays display-only
(weight 0); the collinearity fix is intact. The **60 ceiling is a design choice**
— it says "a below-covenant deal may still rank as *Fair*, but never *Good* or
better." It is a config value, trivially tunable.

**Measured effect — currently non-binding.** Across 638 scored properties, 398 are
below covenant, but **the cap binds on 0 of them at ceiling 60**, because the
highest-scoring below-covenant deal is only **54.7** — the robustness factor
(0.20 weight, and 0 for every below-covenant deal) already pulls them all below 55.
So at 60 the cap is a **standing safety gate**: it changes nothing on today's data
but guarantees the ceiling holds if the weighting ever lets a below-covenant deal
climb past 60. Lowering the ceiling makes it bite — it would bind on 2 deals at 54,
10 at 50, 24 at 45 — but that is a separate calibration decision from installing
the gate. Invariants verified: no above-covenant deal is ever affected, nothing
already below the ceiling moves, and every capped deal is both below covenant and
left at exactly the ceiling.

---

## Deliberate, non-standard choices

These are judgment calls, **not** industry conventions. They are chosen for
*ranking resolution within this data set* and should be re-examined if the model is
used differently.

1. **Negative CoCR / Cash-Flow ramps (`[-10,15]`, `[-6,8]%`).** No convention says
   score negative cash-on-cash. These floors exist solely to keep rank order
   monotonic through zero. **Negative CoCR remains a failing deal;** a non-zero
   factor score below break-even is "least-bad," not "acceptable."
2. **Cash Flow as % of asking price.** A pragmatic size-normaliser, not a standard
   metric (per-door is standard for multifamily but undefined for the rest of the
   book). Chosen so one relative ramp applies across every asset class.
3. **Robustness reference denominators (rate 250 bps, amort 10 yr) and the
   0.7 / 0.3 rate-vs-amort split.** Calibrated to this data set's margin
   distribution and to the judgment that scheduled rate risk dominates conditional
   amortisation risk. Not a market standard.
4. **Scoring one of three collinear factors (CoCR) and displaying the others
   (DSCR, Cash Flow).** A deliberate de-collinearisation to avoid triple-counting
   NOI-minus-debt-service; the freed weight funds the robustness factor. The
   displayed DSCR/Cash-Flow are unchanged in meaning, just unweighted.
5. **Per-listing-then-average city factors (Fix 1).** Mathematically the correct
   order for a non-linear normaliser, but note it makes a city's factor sensitive
   to its *best* listings, not just its average — intended, but a change in what
   "city quality" measures.

6. **5+ multifamily (loan ≥ \$1M) scored on MLI Select top-tier terms
   (95% LTV / 50-yr / 1.10 DCR).** This is the one place a *best-case within the
   asset class* is assumed: the 95% LTV tier requires the full 100-point commitment
   (deep affordability + energy + accessibility). It is retained because the
   diagnostic explicitly frames MLI as the correct basis for that class ("falling
   back to conventional … understating those deals"), and because MLI Select is the
   dominant real program for eligible 5+ multifamily — but it is flagged here as a
   point to revisit if a more conservative MLI tier is preferred. Below \$1M, 5+ MF
   is scored conventional (small-balance CMHC rarely pencils). 49 deals are on the
   MLI Select basis, 42 on conventional.

7. **Covenant score cap ceiling of 60.** A judgment call: below-covenant deals may
   still rank *Fair* but never *Good* or better. It is deliberately a *ceiling*, not
   a target — it does not pull a below-covenant deal down to 60, it only prevents it
   from exceeding 60. On current data it binds on nothing (the highest below-covenant
   score is 54.7), so it functions as a standing gate rather than an active
   correction. The value lives in config and can be lowered if the intent is to
   actively demote below-covenant deals out of the mid-pack.

Standard / conventional choices retained: 10-year institutional hold (Fix 3),
CMHC MLI Select terms for eligible 5+ multifamily (Fix 4, verified), per-asset-class
financing and covenant DSCR (Fix 4).

---

## Validation

Distribution across 639 properties (635 scored) and 109 cities, before all fixes
vs after. Re-analysed through the real pipeline on the live data.

| Measure | Before | After |
|---|---|---|
| Property score: median / mean / σ | 34.0 / 43.3 / **27.1** | 34.9 / 42.0 / **31.6** |
| Property score: min / max | 2.2 / 95.7 | 0.0 / 100.0 |
| Distinct property-score values | 402 | **433** |
| Properties in the piled [10,30) band | **272** | **140** |
| Cities scoring 0.0 — CoCR factor | 71 | **36** |
| Cities scoring 0.0 — IRR factor | 66 | **44** |
| Cities scoring 0.0 — DSCR factor | 68 | **57** |
| Cities scoring 0.0 — Cash-Flow factor | 69 | **27** |
| EM factor score: median / σ | 100 / 5.1 | **48 / 36.9** |
| City opportunity: median / max | 24.5 / 59.3 | 27.2 / 64.5 |
| Low-cap band (cap < 5%, n=235): distinct scores / σ | 123 / 5.9 | **134 / 8.5** |

**Fewer zeros, wider spread, more discrimination** — all three confirmed. City
factor zeros fell on every collinear axis; the spread widened (σ 27.1 → 31.6); the
count of distinct scores rose (402 → 433); and within the low-cap band the σ rose
5.9 → 8.5. The CoCR ordering the diagnostic cited is restored: −0.01% → factor 40,
−6.43% → 14.3, −51.70% → 0 (the last still floored, as designed, below −10).

**Movers are all in the expected direction.** Largest drops are low-cap
(3.6–4.4%) negative-leverage multifamily in Ottawa/Kingston (e.g. 393 Nelson St
25 → 8) that the 30-year hold had been flattering; largest rises are higher-cap
(6.8–7.6%) positive-leverage multifamily in Saint John / St. John's / Cornwall
(e.g. 3 Exmount St 80 → 91). No deal moved in a direction inconsistent with its
fundamentals.

**One movement to flag as surprising-but-correct.** The [0,10) band grew 4 → 133
and the mean dipped 43.3 → 42.0. This is Fix 3 (10-year hold) plus Fix 6
(robustness) correctly exposing the weak, thin-coverage majority that the 30-year
horizon had inflated — *not* a new zero cluster: those 133 span 59 distinct values,
exactly **one** property scores 0.0 (cap 2.79 / CoCR −11.69 / IRR −10.83 / EM 0.86:
every weighted factor genuinely at its floor), and the drops land on precisely the
negative-leverage deals that should fall. The DSCR city factor is the least-improved
(68 → 57) because Fix 2's negative floor was applied to CoCR and Cash Flow per the
spec, not DSCR; DSCR is display-only at the property level after Fix 6, so this does
not affect property scores.
