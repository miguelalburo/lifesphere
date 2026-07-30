<!-- title: ACC/PRAD/SARC: Now Loaded, Zero Config Changes Needed -->

# TCGA-ACC / TCGA-PRAD / TCGA-SARC — Now Loaded

**What changed:** you replaced the raw clinical/survival/expression files for these three cohorts with versions matching the standard GDC-shaped schema (same filenames *and* same columns as the other 29 cohorts). Verified this directly rather than assuming — checked exact filenames, full column headers, and ran the actual `tcga_bulk` profile's `--report` coverage check before touching anything.

## Verification before running

- **Filenames**: `_clinical.csv`, `_survival.csv`, `_tpm_unstranded.tsv` now exist for all three, exactly matching what `config/mapping/tcga_bulk.yaml` already expects — no profile change needed.
- **Schema**: spot-checked headers directly — `_clinical.csv` matches the standard GDC diagnosis-shaped columns (`project, submitter_id, ajcc_pathologic_stage, primary_diagnosis, ...`, not the Xena-flattened `field.namespace` shape from before); `_survival.csv` is byte-for-byte the same CDR-style schema as every other cohort (`bcr_patient_barcode, ..., OS, OS.time, DSS, ...`); `_tpm_unstranded.tsv` uses real TCGA barcode column headers.
- **`--report` dry run** (no writes) confirmed full property coverage matching the other 29 cohorts before running for real — e.g. ACC: 6/6 Sample properties, 5/5 Subject, 7/7 Diagnosis, 2/2 Disease, 4/4 Survival all resolving via the existing aliases, zero new config needed.

## Real run results

| Cohort | Time | Sample | Subject | Diagnosis | Disease | Survival | ExpressionObservation | Output size |
|---|---|---|---|---|---|---|---|---|
| TCGA-ACC | 2.1 min | 243 | 92 | 92 | 1 | 92 | 4,792,140 | 1.3GB |
| TCGA-SARC | 7.9 min | 795 | 261 | 261 | 27 | 261 | 16,074,900 | 4.5GB |
| TCGA-PRAD | 16.1 min | 1,470 | 500 | 500 | 2 | 500 | 33,605,640 | 9.4GB |

All three: `HAS_DIAGNOSIS`/`Subject` and `OF_DISEASE`/`Diagnosis` ratios are 100% — no anomalies like the earlier BRCA/SKCM findings this round. Referential integrity re-checked directly: 0 dangling `PROVIDED_SAMPLE` edges across all three (243/795/1,470 edges checked). Placeholder-scrub re-checked: no leaked bracket tokens in any of the three.

## Where this leaves the corpus

**All 33 TCGA cohort folders in `data/raw/` are now loaded** with full clinical, survival, and expression data through the single `tcga_bulk` profile — no per-cohort profile variants needed after all, since the file replacements brought ACC/PRAD/SARC into line with the same schema as the other 30. Methylation, mutation, proteomics, CNV, and the BRCA differential-expression/enrichment bundle remain out of scope, unchanged from the original compatibility report — that boundary was never about ACC/PRAD/SARC specifically.

Combined running total across all rounds: 33/33 cohorts loaded, ~168GB in `data/standardised/` on `/Volumes/BoFang/individual/standardisation_output/`, zero changes to the pipeline code or `tcga_bulk.yaml` needed for this round — the fix lived entirely in the source data.
