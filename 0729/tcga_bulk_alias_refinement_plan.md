<!-- title: Alias-Discovery Refinement Plan -->

# `tcga_bulk.yaml` Alias-Discovery Refinement — Plan

**What this is:** [Suggested next step 2](https://claude.ai/code/artifact/5125e435-c3dd-45ee-b343-d72cc0f77451) from the TCGA Bulk-Download Profile Implementation Summary, done *before* next step 1 (running the remaining ~24 cohorts). `config/mapping/tcga_bulk.yaml`'s Diagnosis/Subject/Sample/Survival aliases were built by inspecting one cohort (TCGA-CESC) and reusing `extract.yaml`'s existing choices where the column names matched. This task widens that check across every eligible cohort before any of them get a real production load, so the alias set doesn't need revisiting cohort-by-cohort later.

## Decisions locked in before this plan

| Question | Decision |
|---|---|
| Which cohorts to check | All ~30 eligible cohorts — every standard-shape folder except ACC/PRAD/SARC (dot-named files, already out of scope). Includes BRCA, whose `_biospecimen.csv`/`_clinical.csv`/`_survival.csv`/`_tpm_unstranded.tsv` are standard-shaped even though its proteomics/CNV/enrichment files stay excluded. |
| Fields with no schema property at all | Document only — no `config/schema/nodes.yaml` changes this round. |
| Verification depth | Schema validation + `--report` coverage checks only. No `data/standardised/` writes this round (running the remaining cohorts for real is the deferred next-steps item 1). |

Carried over from the prior implementation round, still in force: no line removed from any file — a changed alias is the old line commented out in place, immediately followed by the new one; `data/raw/` is read-only throughout.

## Eligible cohorts (30)

```
TCGA-BLCA  TCGA-BRCA  TCGA-CESC  TCGA-CHOL  TCGA-COAD  TCGA-DLBC  TCGA-ESCA
TCGA-GBM   TCGA-HNSC  TCGA-KICH  TCGA-KIRC  TCGA-KIRP  TCGA-LAML  TCGA-LGG
TCGA-LIHC  TCGA-LUAD  TCGA-LUSC  TCGA-MESO  TCGA-OV    TCGA-PAAD  TCGA-PCPG
TCGA-READ  TCGA-SKCM  TCGA-STAD  TCGA-TGCT  TCGA-THCA  TCGA-THYM  TCGA-UCEC
TCGA-UCS   TCGA-UVM
```

Three of these (BLCA, LAML, and possibly others) already have a known missing source file (BLCA has no `_survival.csv`; LAML has no `_clinical.csv` — see the compatibility report). `--report` will just report those entries as skipped for that cohort, same as the real run already confirmed; the discovery pass doesn't need to special-case them.

## Method

1. **Collect.** Run `python -m src.standardise <dataset> --profile tcga_bulk --report --values` for all 30 cohorts programmatically (one Python driver calling `src.standardise.run.report()` in a loop — much faster than 30 CLI invocations, and `report()` never touches the reshape/matrix path, so this is cheap: no melting the large expression matrices, only reading small clinical/biospecimen/survival file headers and a sample of values).
2. **Aggregate per node/edge type** (Sample, Subject, Diagnosis, Disease, Survival, and their edges) across all 30 reports:
   - For every schema property currently listed as **unmatched** in the CESC-only pass, check whether *any* other cohort's report resolves it (a column present there that CESC's file happened to lack, or a naming variant CESC didn't expose).
   - For every **unused** raw column that recurs across many cohorts (not just a one-off), check whether it represents real signal worth aliasing to a currently-unmatched property, or is a duplicate/synonym of an already-matched one under a different name.
3. **Classify each finding** into exactly one of three outcomes:
   - **New alias** — a recurring raw column clearly corresponds to an existing, still-unmatched schema property → add to `config/mapping/tcga_bulk.yaml`.
   - **Already covered, differently** — the raw column is a synonym of something already matched by camel/normalized auto-resolution; no action needed, just noted for completeness.
   - **No schema home** — real, populated, recurring column with no corresponding property anywhere in the current schema (see hypotheses below) → documented in the findings report, not added anywhere.
4. **Apply.** Edit `config/mapping/tcga_bulk.yaml`'s existing `aliases:` blocks (Sample/Subject/Diagnosis/Disease/Survival) — additions only, and any changed line (if a prior alias choice turns out to be wrong for some cohort) follows the comment-out-old / add-new convention.
5. **Verify.**
   - `load_schema()` / `load_mapping('tcga_bulk')` still load and validate cleanly.
   - Re-run the `--report` pass across all 30 cohorts and confirm total matched-property count increased (or stayed equal — never decreased) versus the pre-change baseline, cohort by cohort.
   - `pytest` — full suite still green (this task shouldn't touch any `.py` file at all, only the YAML profile, so this is mostly a sanity check).
6. **Report.** Write the same kind of implementation summary as the prior round: what aliases were added and why (with the specific cohorts that motivated each), the "no schema home" list, and the before/after coverage numbers.

## Hypotheses going in (to be confirmed or refuted by the actual data, not assumed)

Based on how TCGA's clinical/biospecimen/survival files are generally structured across disease areas, these are the most likely places the discovery pass will find something — listed so the findings report can explicitly confirm or refute each, not to pre-decide the outcome:

- **Disease-specific staging fields** are the most likely source of "no schema home" findings: FIGO stage (gynecological cohorts — CESC, OV, UCEC, UCS), Gleason score (prostate — out of scope, PRAD excluded), Breslow depth / Clark level (melanoma — SKCM), circumferential resection margin (colorectal — COAD, READ). The schema's `Diagnosis` node has generic `pathologicStage`/`tumorGrade`/`tumorSubtype` slots but nothing scored specifically for these disease-specific scales — expect several of these to land in "no schema home," not "new alias."
- **Survival columns** are likely already consistent across all 30 cohorts, since `_survival.csv` is generated from the same TCGA CDR source schema regardless of cancer type — expect little to no new aliasing needed here, but worth confirming rather than assuming, since one cohort's export could still differ.
- **Subject demographic fields** (species, consentStatus, bloodType, etc.) are gaps in the *source data itself* (TCGA doesn't collect them, same as `extract.yaml`'s own documented GDC gaps) rather than naming mismatches — expect these to remain unmatched across every cohort, not because of a missing alias.
- **Sample/biospecimen fields** are the most standardized file type in this corpus (same ~32-column shape observed in every cohort inspected so far) — expect the smallest number of new findings here.

## What this plan does not cover

- Actually running `standardise()` (the real load) for any of the 30 cohorts — that's the deferred next-steps item 1.
- Any change to `config/schema/nodes.yaml` — "no schema home" findings are recorded, not acted on.
- ACC/PRAD/SARC's alternate dot-named clinical/survival files, or any of the excluded methylation/mutation/proteomics/enrichment files — unchanged scope from the original profile.
