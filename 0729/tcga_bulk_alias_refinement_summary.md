<!-- title: Alias-Discovery Refinement: Findings & Implementation Summary -->

# Alias-Discovery Refinement — Findings & Implementation Summary

**What this covers:** execution of the [Alias-Discovery Refinement Plan](https://claude.ai/code/artifact/dc588331-39b5-4876-8535-960c21c21330) — running `--report --values` across all 30 eligible cohorts to widen `config/mapping/tcga_bulk.yaml`'s alias coverage beyond the single cohort (TCGA-CESC) it was originally built against, before running the remaining cohorts for real (deferred, per your instruction, to a later task).

## Method actually used

Rather than 30 individual CLI calls, a Python driver called `src.standardise.run.report(dataset, profile='tcga_bulk', values=True)` in a loop across all 30 eligible cohorts (all standard-shape folders except ACC/PRAD/SARC), collecting structured results into JSON for aggregation. `report()` doesn't run the reshape/matrix-melt step, so this only reads clinical/biospecimen/survival file headers and a small value sample — all 30 cohorts collected with zero errors.

## Findings

### 1. New aliases added (2)

Cross-referencing which schema properties were unmatched in *some* cohorts but matched in others pointed straight at disease-specific staging systems using a different column than `ajcc_pathologic_stage`:

| Cohort(s) affected | Missing column | Found instead | Fix |
|---|---|---|---|
| TCGA-DLBC (lymphoma) | `ajcc_pathologic_stage` | `ann_arbor_clinical_stage` | Added `ann_arbor_clinical_stage: pathologicStage` |
| TCGA-OV (ovarian) | `ajcc_pathologic_stage` | `figo_stage` | Added `figo_stage: pathologicStage` |

Both added to `config/mapping/tcga_bulk.yaml`'s `Diagnosis` aliases block as pure additions — nothing removed or reordered. Both resolve only when `ajcc_pathologic_stage` is absent from a given cohort's file (the resolver's alias lookup is first-present-wins, and `ajcc_pathologic_stage` is listed first), so cohorts that already had AJCC staging matched are unaffected.

**Effect, verified by re-running `--report` across all 30 cohorts after the change:** `Diagnosis.pathologicStage` now matches in DLBC and OV (both previously unmatched); every other cohort's coverage is unchanged. Total matched-property count across all 30 cohorts: 691 → 693 (net +2, zero regressions).

One cohort — **TCGA-LGG** (low-grade glioma) — still has no matching column for `pathologicStage` after this fix, and none was found in its unused-column list either. This is expected, not a gap: gliomas aren't staged with an anatomic TNM/FIGO/Ann-Arbor system in the first place; `tumorGrade` (WHO grade) is the relevant field for CNS tumors, and that property already resolves correctly for LGG via the existing `tumor_grade` auto-camel match.

### 2. "No schema home" findings (documented, not acted on — per the locked-in decision)

Four columns recur across the large majority of cohorts (27–28 of 29) with real, non-placeholder data, but have no corresponding property anywhere in `config/schema/nodes.yaml`:

| Column | Cohorts | What it is | Why it has no home |
|---|---|---|---|
| `ajcc_pathologic_t` | 27/29 | Tumor (T) sub-stage | `Diagnosis` has `pathologicStage` (the combined stage) but no T/N/M sub-components |
| `ajcc_pathologic_n` | 28/29 | Node (N) sub-stage | same |
| `ajcc_pathologic_m` | 28/29 | Metastasis (M) sub-stage | same |
| `ajcc_staging_system_edition` | 28/29 | AJCC edition/version used | No staging-metadata property on `Diagnosis` |
| `laterality` | 28/29 | Tumor sidedness at diagnosis | A same-named property exists on `Intervention`'s `:Surgery` subtype (surgical laterality — a different context), but `Diagnosis` itself has none |

These are recorded as a comment block directly in `config/mapping/tcga_bulk.yaml` (not just this report) so a future schema-extension pass has a ready-made, evidence-backed list rather than needing to rediscover it. No `config/schema/nodes.yaml` change was made, per the locked-in scope decision.

### 3. Confirmed non-issues — real data absence, not aliasing bugs

Two properties showed partial coverage (matched in roughly half of cohorts) that looked at first like they might need a second alias, but turned out to be genuine source-data variance once checked directly against the raw files:

- **`Sample.collectionMethod` / `Sample.passageNumber`** — unmatched in the same 14 cohorts, all missing the `method_of_sample_procurement`/`passage_count` columns entirely. Compared `TCGA-CESC`'s `_biospecimen.csv` header (32 columns) against `TCGA-CHOL`'s (23 columns) directly — CHOL's export is a genuinely smaller shape, not a renamed column. No alternate source exists to alias instead.
- **`Diagnosis.diagnosisMethod`** — unmatched in the same 14 cohorts (same pattern), `method_of_diagnosis` simply absent from their `_clinical.csv`.
- **`Diagnosis.ageOfOnsetDays`** — matched in only 5/29 cohorts, but confirmed this is because `age_at_onset` genuinely only appears in 5 cohorts' source files (a real GDC field for hereditary/familial-onset tracking, not routinely collected for most cancer types) — the alias itself is correct, the data just isn't there for most cohorts.
- Every **Subject demographic property** (`species`, `consentStatus`, `bloodType`, `geneticAncestry`, etc.) and **Sample** property (`cellularComposition`, `purity`, `suspensionType`, etc.) that was unmatched for CESC alone remains unmatched in *every one* of the 30 cohorts — confirming these are genuine gaps in what TCGA bulk exports collect (consistent with `config/mapping/extract.yaml`'s own documented GDC-wide gaps), not a CESC-specific naming quirk.

## Verification

- `load_schema()` / `load_mapping('tcga_bulk')`: load and validate cleanly (42 nodes, 52 edges, zero errors) with the new aliases present.
- Re-ran `--report` (no `--values`, faster) across all 30 cohorts post-change and diffed against the pre-change baseline: **+2 net matched properties** (DLBC and OV each gained `pathologicStage`), zero cohorts lost coverage anywhere.
- Full `pytest` suite: **324/324 passed** — this round only touched the YAML profile, no `.py` files, so this is confirmation nothing else moved.
- No `data/standardised/` writes this round, per the locked-in scope decision — `--report` never touches the reshape/matrix path, so none of this required melting the large expression matrices. Running the remaining ~24 cohorts for real remains the deferred next-steps item 1.
- `data/raw/` was read-only throughout — confirmed via `git status` showing zero changes there.

## What changed

| File | Change |
|---|---|
| `config/mapping/tcga_bulk.yaml` | Added 2 new `Diagnosis` aliases (`figo_stage`, `ann_arbor_clinical_stage` → `pathologicStage`) and a documentation comment block recording the "no schema home" and "confirmed non-issue" findings above, for future reference. |

## Suggested next step

With this refinement done, the original next-steps item 1 — running the remaining ~24 standard-shape cohorts through `standardise()` for real, writing into `data/standardised/` — is now unblocked and doesn't need revisiting for alias coverage afterward.
