# ElementeX asset-health method demonstration

Synthetic data, not a real utility. Method demonstration; ElementeX Labs has no utility clients.

Live page: https://elementexlabs.ca/demos/asset-health/ serves the committed `dist/index.html` unchanged (same SHA-256 as listed below).

This demonstration shows data quality, inventory and partial current replacement value (CRV), a visible health index, an age profile, two replacement scenarios and four acceptance checks. It has one snapshot, **2026-03-31**. There are **300 transformers and 700 poles**, with deliberately defective data. Appended duplicates bring the source to **1,015 rows**: **990 accepted in service, 15 held, 10 excluded exact copies**. Held and excluded rows are never added to inventory or CRV.

## Run

Python 3.11 or later; standard library only. Nothing to install. From this repository:

```sh
python3 -m amdemo
```

That command regenerates synthetic CSVs and the test-only defect manifest, runs all 36 automated tests, verifies two fresh-process artifact hashes, writes `dist/results.json` and `dist/index.html`, and opens the HTML with Python's `webbrowser` module. An error exits nonzero before generated files are written. Double-clicking the committed HTML also works, with no server or account.

For headless verification, set `AMDEMO_NO_OPEN=1`. Set `PYTHONDONTWRITEBYTECODE=1` to avoid bytecode caches. These environment variables do not change artifact bytes. Unit tests can also be run with `python3 -m unittest discover -s tests -v`.

Tested build environments: Python 3.11.15 and Python 3.14.6 on macOS 27.0.1, arm64. Fresh local clones on both versions produce the same SHA-256: `dist/results.json` = `2166ebf3bce1272997d9b1071435913225d99df0452025e2e5f8ac41df256d61`; `dist/index.html` = `fb76f974be4d794dc20feb5095b90ab531b59624ab4a7939708d56cd86c50a92`. Browser verification uses an existing headless-shell binary, an isolated throwaway profile and debugging pipes; it installs nothing and attaches to no running browser. The build command itself needs no browser-test dependency.

## The six screens

1. **Data quality:** source-level completeness, usability, missing, estimated and invalid counts; exclusive dispositions and row reasons. Expand any exception count to see source IDs. Download raw rows, quality or dispositions.
2. **Inventory and CRV:** accepted in-service inventory, held and excluded counts, price coverage, unvalued subtypes and the complete invented cost table.
3. **Health index:** three hand-worked fixtures, fixed weights, lives, exact scales, health band frequencies and asset lookup. Details show raw inputs, scores, fixed and renormalized weights, contributions, evidence weight, provenance and exclusions.
4. **Age profile:** 10-year known-age categories, plus separate estimated, unknown and invalid categories. Counts reconcile to accepted in-service inventory.
5. **Plans:** annual whole-asset selections, spending, underspend and present value; separate ordinal risk and health frequency tables. The 1, 2 and 3 point annual deterioration scenarios are shown together. Exclusion reasons are expandable and exported.
6. **Acceptance tests:** build-time actual versus expected results, failing row IDs if applicable, and a visible uncertainty trace across source, inventory, health and plans. The page does not rerun calculations.

Every table has a CSV download (related plan tables have separate downloads). Every CSV includes the synthetic notice, model version and seed; nested row IDs, warning flags and factor detail are JSON strings in quoted CSV cells. Null values export as blank cells, not zero. Tab navigation, asset lookup and downloads are presentation-only JavaScript. All calculations run in Python.

## Data dictionary and generator

`data/synthetic/assets.csv` contains `source_row_id`, `asset_id`, `asset_group` (TX or POLE), `subtype`, `status`, `area`, `customers_served`, `install_date`, `install_date_status`, `inspection_date`, `condition_grade`, `measurement`. Every row represents one unit, in service. TX subtypes are 25, 50 and 100 kVA; poles are standard or heavy. Areas A1 to A6 are fictional labels. Known/recorded dates are supplied synthetic dates, never verified records.

`data/synthetic/unit_costs.csv` contains group, subtype, whole-dollar installed unit cost, basis, effective date, source and estimated flag. Effective date is 2026-01-01. Prices: TX 25=8,000, 50=12,000, 100=20,000 CAD; pole standard=4,000, heavy=6,000 CAD. Basis: installed like-for-like replacement including labour, excluding removal. Every source is **invented demonstration assumption, not a quotation**. All prices are estimated.

`config/model.json` contains version `demo-1`, seed **20261010**, generator version **1**, lives, weights, scales, evidence rules, plausibility limits, ordinal band thresholds, plan budget and discount rate. All are **invented demonstration values**, not utility, geographic, standard or benchmark inputs. Edit weights there and rerun; weights must be nonnegative, finite and sum to one. The page never edits them live. Each view shares a footer with version, seed and the exact SHA-256 of `results.json`.

Only a locally seeded `random.Random(20261010).random()` is called. No clock, global random state, sampling helpers or normal-distribution helpers are used. Inverse transforms and Box-Muller are explicit. Draw order:

1. Six fictional area customer values, uniformly 20 to 800.
2. Assets sorted by ID; for each, subtype (TX uniform among three; poles 80% standard), installation-decade draw, year, month, day, two condition-normal draws, measurement draw(s), area draw, TX customer draw if applicable, inspection-age draw.
3. One draw per base row to sort a seeded permutation; its disjoint consecutive sets receive the planted defects below.

Installation-decade weights for 1960s through 2020s are 0.08, 0.17, 0.20, 0.15, 0.15, 0.15, 0.10. Years are uniform within the decade, but the current decade ends at the snapshot; days are uniform 1 to 28. Condition grade is round-half-up of `1 + 3*min(age/life,1.3) + N(0,0.8)`, bounded between 1 and 5. Lives are TX 45 and POLE 60 years. TX loading is triangular (20,65,150); pole strength is `100 - 30*age/life + N(0,8)`, bounded between 30 and 100. Measurements are stored to four decimals. TX customers are uniform 1 to 30; poles use their fictional area's value. Inspection age is uniform 0 to 12 years in elapsed days.

**The health index follows age because the generator was built that way.** Random defects are coverage fixtures, not a representative missingness mechanism or evidence of real fleet realism.

Planted defects are exact counts, on disjoint base source IDs: 80 missing installation dates; 80 estimated dates set to July 1; 10 recorded placeholders `1900-01-01`; 5 future dates; 60 missing inspections; 10 impossible measurements; 10 unmatched subtypes; 5 blank identities; 10 exact duplicate copies appended; 5 conflicting copies appended. Estimated current-year dates move to the preceding July so they remain valid estimates. Each copy gets a new source ID. The committed `data/synthetic/defects.json` gives every planted source ID and appended ID; only generator-fixture tests consult it. Quality and calculation logic do not import or read it. It is not displayed as detection evidence.

## Formulas and output contract

- Completeness = 100 × nonblank applicable source values / applicable source rows. Usability = 100 × valid nonmissing applicable values / applicable source rows. Duplicates remain in these denominators. Estimated dates count as present and have a separate flag. Empty denominators are unavailable, never zero.
- Disposition order: exclude exact copies after the lowest source ID; hold blank identities and all remaining rows of conflicting IDs; accept the rest with field warnings. Missing condition, invalid dates, high loading and unmatched costs do not erase an identifiable asset.
- Installation dates on/before the planted placeholder `1900-01-01`, malformed dates and future dates are invalid. `1970-01-01` has no sentinel meaning. Dates are parsed exactly. Age = elapsed days / 365.2425.
- CRV(asset) = matched installed unit cost, chosen on or before the snapshot. CRV(group) sums only valued accepted in-service assets, and is labelled **Partial CRV** if any are unvalued. Missing matches are null, never zero. Integer dollars are exact; no adjustment or second price year is used.
- `clamp(x) = min(100,max(0,x))`. Age deterioration = clamp(100×age/life); condition = 25×(grade−1), where **1 is best and 5 worst**; TX loading = clamp(2×(loading−80)); pole strength = clamp(100×(100−strength)/40). The 60% scale point is an invented illustration, not a standard limit or replacement trigger.
- TX weights: age .3, condition .5, measurement .2. Pole weights: age .2, condition .3, measurement .5. `HI = 100 − Σ(w×available score)/Σ(available w)`. Need a valid condition grade supported by a valid inspection date and available weight ≥.7. Invalid/missing factors are unavailable. Inspections older than 10 years are flagged and retained, as the approved illustration specifies. Loading >130% is a warning; outside 0% to 200% is unusable. Strength outside 0% to 100% is unusable. All limits are invented demonstration rules.
- Estimated age can contribute and is flagged **uses estimated age** when scored. Unknown/invalid dates contribute no age score; an otherwise sufficiently evidenced TX can still score. Its reduced evidence coverage and missing/invalid flags remain visible. No mean is inserted, and no cross-group or mixed-evidence group mean is reported.
- HI bands: ≥80 very good, [60,80) good, [40,60) fair, [20,40) poor, <20 very poor; null = insufficient evidence. Band decisions use the full score, before display rounding. The three default hand figures are 100.000, 60.000 and 52.857. They are outside all fleet counts.
- Risk likelihood is the ordinal health-band rank 1 to 5. Consequence is rank 1 to 5 from invented customers-served cut points 10, 50, 150, 400 (upper bound inclusive). `R = L×C`, ordinal and uncalibrated. Display frequency counts for R 1 to 4, 5 to 9, 10 to 14 and 15 to 25, and IDs with R≥15. **Never sum or average R. Risk is not a probability or dollars.**
- Plans share the scored, valued, recorded-valid-age cohort. Plan A orders by descending projected R; B by descending known age; ties use ID. Both have CAD 300,000 a year, for five years. Buy whole assets until the next does not fit; stop instead of skipping it. Show underspend; do not carry it forward or buy an asset twice.
- Observe at the beginning of year t, after any intervention: unreplaced `HI(t)=max(0,HI0−rate×(t−1))`; replaced `HI=95` thereafter, explicitly a **scenario reset, not a test result**. R is derived from the resulting band. For rates 1, 2 and 3, rebuild both plans independently from the same cohort.
- Spend at the start of the replacement year; `PV=Σ spend(t)/(1.03)^(t−1)`. Constant 2026 dollars, no escalation. Decimal arithmetic rounds once half-up to cents. This replacement-spending comparison excludes maintenance, disposal, residual value and failure losses.

**Plan A wins on its own measure by design.** Sorting by its assessment measure establishes its framing; no scenario difference is a measured reliability benefit or a general guarantee that one ordering dominates every metric.

## Acceptance and verification

These are **Demo thresholds, not utility acceptance**:

1. Every source ID has exactly one disposition; 1,015 = 990 + 15 + 10; every hold/exclusion has a reason. Zero unexplained rows.
2. Independently read cost CSV and recompute every asset and group valuation, null and partial label. Zero dollar difference.
3. Compare row-level date provenance and visible traces across quality, inventory, health, age and plans. Check estimate flags, unavailable factors, exclusions and age reconciliation. Zero lost flags within this stated output contract.
4. Generate complete candidate artifacts in two fresh Python processes and compare SHA-256 of both `results.json` and `index.html`. Compare them to the publishing process too. Canonical object keys and row order; no timestamp is hashed. A stable verification slot avoids recursive self-hashing; a PASS is written only after actual process verification succeeds.

All 36 automated tests include hand-worked health/PV, band and date boundaries, inspection evidence, exact defect detection counts, disposition precedence, cost lookup and missing costs, evidence threshold, weight validation/configuration, shared cohorts, budget stopping, intervention timing, static HTML and fresh-process repeatability. Float totals use `math.fsum`, including model validation, health evidence and weighted scores, generator accumulation and hand-check expectations, so the Python 3.12 change to built-in float `sum` does not change the outputs. The regression test rejects any built-in `sum` with float inputs during a complete candidate build. Integer counts and dollars retain exact integer sums; present value retains Decimal arithmetic. Four deliberate corruptions remove a hold reason, alter CRV by one dollar, hide an estimated-age flag and alter a canonical result. Each corresponding acceptance check must report FAIL for the unit test to pass.

`tools/headless_check.py` is a verification utility, separate from the portable build. It uses the installed headless shell directly and only the Python standard library. It takes `--binary`, `--page`, `--shots` and `--profile` paths. It verifies the actual local file, traverses all six tabs, tests lookup and CSV downloads, captures six PNGs and rejects external requests. It uses process debugging pipes, not a browser attachment or network server. Do not install anything to run it.

Not yet checked by hand: Firefox, Edge and Chrome, or any operating system other than macOS. A manual check would open the page, move through the six tabs with pointer and arrow keys, check the six notices, the actual and expected acceptance values, an asset lookup including an estimated and an unvalued row, and the downloads, then resize to a narrow window. No broad browser compatibility claim is made.

## Open by design

Code, page templates and tests are Apache-2.0, in `LICENSE`. Synthetic fixtures, costs, defect manifest and numerical results are CC0-1.0, in `DATA-LICENCE`. The generated HTML combines Apache-2.0 presentation code with CC0-1.0 synthetic data. No proprietary assets, dependencies, telemetry, accounts, remote fonts, imports or network services. All inputs, rules and outputs are readable and locally reproducible. The code licence covers this demo; it does not describe a future utility contract or imply support commitments. One maintainer: Amirhossein (Amir) Daneshpajouh.

## Limits

- The data is synthetic, and the health index's link to age is built into the generator.
- Weights, lives, costs and thresholds are invented. They aren't engineer-approved or calibrated.
- CRV is a planning estimate, not book value.
- Risk scores are ordinal and are not probabilities or dollars.
- The plans show the mechanics, not a measured benefit, and there is no optimization.
- There are no failure curves, GIS, ERP integration or security hardening.
- Passing tests verifies the code against this data, not the method on real extracts.
- There is one maintainer, and the licence covers the demo only: Apache 2.0 for the code and CC0 for the data.

ElementeX Labs Inc. has no utility clients. A passing test is not a utility reference, engineering approval, operational prioritization, a safety classification or evidence that one person can deliver a utility programme. There are no real places, buyers, utility names, standard limits or published benchmarks behind any number. Historical snapshots, retirement tracking and full lifecycle costing are not demonstrated.

## Design notes

The build follows these rules:

1. **Source count:** 1,000 is the base population. Ten exact and five conflicting copies append 15 rows. Reconciliation states 1,015 source / 990 accepted / 15 held / 10 excluded, instead of calling appended rows part of a 1,000-row source.
2. **Valid fixture dates:** the current installation decade ends at the snapshot; estimated July dates cannot land in the future. This prevents unintended baseline defects from contaminating exact planted counts. Invalid dates are unavailable, never unknown or mean-filled.
3. **Elapsed age:** age uses a 365.2425-day year. Ten-year bins are half-open; estimates remain separate.
4. **Inspection evidence:** condition needs a valid inspection date as well as a valid grade; missing/future/malformed inspection evidence cannot score. A 10-year stale-inspection flag is kept, with no shorter expiry. This keeps the evidence visible without claiming an engineering inspection cycle.
5. **Comparable plans:** both plans exclude unvalued, unscored and non-recorded ages. A plan ordered by known age cannot rank unknown or estimated dates honestly. The same fixed cohort is used in both plans and all three scenarios, with per-row exclusion reasons. Copies sharing an eligible asset ID still remain excluded source rows.
6. **Timing:** observations are at the beginning of each year, after any intervention. Year 1 starts at HI0 for unreplaced assets. Start-of-year replacement spending is discounted by t−1; replacement HI stays at its declared scenario value of 95. No probabilistic deterioration claim is implied.
7. **Ordinal risk:** use individual ordinal products only to order/count categories. No sum, mean, percentage reduction or currency column appears in the risk table. Explicit invented band cut points and inclusive consequence edges make the output testable.
8. **Visible uncertainty:** source, inventory, scored and plan populations have separate numerators, denominators and source-ID lists. A bounded row-level contract is used, because a claim to trace every uncertainty through every output could not be tested. The test-only planting log is not displayed as detection validation.
9. **Verification scope:** 36 automated tests cover the boundaries listed above. Six isolated headless-shell screenshots and smoke assertions check the page; no test framework or dependency is added. Manual browser checks are listed above as not yet done.
10. **Local operation and hosting:** a normal build opens the page in the default browser; automated checks suppress this with an environment variable so they never touch a running desktop browser. The hosted page is the committed `dist/index.html`, served as a static file with no server-side code.
