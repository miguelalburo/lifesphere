<!-- title: Remaining 27 TCGA Cohorts: Full Load Summary -->

# Remaining 27 TCGA Cohorts — Full Load Summary

**What this covers:** next-steps item 1 — running every remaining eligible cohort (27 of the 30 standard-shape cohorts; TCGA-CESC, TCGA-BLCA, TCGA-LAML were already done in an earlier round) through the `tcga_bulk` profile for real, completing the goal set out in the [TCGA Bulk-Download Profile Implementation Summary](https://claude.ai/code/artifact/5125e435-c3dd-45ee-b343-d72cc0f77451). All 30 eligible cohorts have now been loaded, all with expression data.

**Update:** the first pass flagged TCGA-BRCA as having zero expression data due to a UUID-vs-barcode mismatch in its source file. You replaced that file with a corrected version (proper TCGA barcode headers); BRCA was re-run against it and now loads completely — see the BRCA section below. Everything in this report reflects the corrected, final state.

## Why output landed on an external volume

Before starting, disk math showed the projected output (~164GB, based on the exact rows/GB ratio measured from the 3 already-completed runs) far exceeded the ~31-39GB free locally (the local disk was already at 93% capacity). Rather than truncate coverage to fit, output was redirected to `/Volumes/BoFang/individual/standardisation_output/data/{standardised,interim}` (1.6TB free at the time). The pipeline itself never wrote anything to `data/raw/` — the local disk's own free space was unchanged (38GB) throughout the run, and the one change `data/raw/TCGA-BRCA/TCGA-BRCA_tpm_unstranded.tsv` did see afterward was your own manual file replacement, not anything this pipeline did.

## Results: 27/27 completed, 0 crashes

| Cohort | Time | Sample | Subject | Diagnosis | Survival | ExpressionObservation |
|---|---|---|---|---|---|---|
| TCGA-CHOL | 24.3 min | 154 | 51 | 48 | 45 | 2,669,040 |
| TCGA-DLBC | 1.5 min | 161 | 58 | 48 | 48 | 2,911,680 |
| TCGA-UCS | 1.4 min | 171 | 57 | 57 | 57 | 3,457,620 |
| TCGA-UVM | 2.5 min | 256 | 80 | 80 | 80 | 4,852,800 |
| TCGA-MESO | 2.7 min | 249 | 87 | 87 | 87 | 5,277,420 |
| TCGA-KICH | 3.5 min | 347 | 113 | 113 | 113 | 5,520,060 |
| TCGA-THYM | 15.4 min | 373 | 124 | 124 | 124 | 7,400,520 |
| TCGA-TGCT | 5.1 min | 803 | 263 | 263 | 134 | 9,462,960 |
| TCGA-READ | 9.6 min | 547 | 172 | 172 | 170 | 10,736,820 |
| TCGA-PAAD | 6.2 min | 566 | 185 | 185 | 185 | 11,100,780 |
| TCGA-PCPG | 9.2 min | 546 | 179 | 179 | 179 | 11,343,420 |
| TCGA-ESCA | 6.8 min | 536 | 185 | 185 | 185 | 12,010,680 |
| TCGA-GBM | 13.5 min | 1,582 | 617 | 600 | 596 | 18,379,980 |
| TCGA-KIRP | 14.0 min | 893 | 291 | 291 | 291 | 19,593,180 |
| TCGA-LIHC | 18.9 min | 1,168 | 377 | 377 | 377 | 25,719,840 |
| TCGA-OV | 20.5 min | 1,329 | 608 | 587 | 587 | 26,326,440 |
| TCGA-STAD | 20.8 min | 1,359 | 443 | 443 | 443 | 27,175,680 |
| TCGA-SKCM | 16.9 min | 1,384 | 470 | 470 | 470 | 28,692,180 |
| TCGA-COAD | 26.4 min | 1,490 | 461 | 461 | 459 | 31,179,240 |
| TCGA-LGG | 33.1 min | 1,553 | 516 | 516 | 515 | 32,392,440 |
| TCGA-LUSC | 37.8 min | 1,562 | 504 | 504 | 504 | 33,484,320 |
| TCGA-HNSC | 25.7 min | 1,578 | 528 | 528 | 528 | 34,333,560 |
| TCGA-THCA | 26.2 min | 1,562 | 507 | 507 | 507 | 34,697,520 |
| TCGA-UCEC | 21.8 min | 1,641 | 560 | 548 | 548 | 35,486,100 |
| TCGA-LUAD | 20.8 min | 1,781 | 585 | 522 | 522 | 35,789,400 |
| TCGA-KIRC | 25.6 min | 1,618 | 537 | 537 | 537 | 37,002,600 |
| TCGA-BRCA | 18.3 min | 3,397 | 1,098 | 1,097 | 1,097 | 41,708,520 |

Total wall time: **~7.1 hours** (24,623s for the 27-cohort batch, +1,100s for the BRCA re-run). Total output: **153GB** in `data/standardised/`, **83GB** in `data/interim/` (regenerable, safe to delete if that space is needed back). Combined with the 3 cohorts from the earlier round, **all 30 eligible cohorts are now loaded, all with expression data.**

## One finding, corrected after re-verification; one confirmed benign

### 1. TCGA-BRCA: initially zero expression data — root-caused to a stale source file, corrected after you swapped in the right one

The first pass of this run found `ExpressionObservation` at exactly 0 for BRCA, finishing suspiciously fast (4.4s) for what should have been the largest expression matrix in the batch. Investigated and reported at the time as: every one of BRCA's 1,231 expression-matrix column headers was a GDC UUID (e.g. `2c3000b7-4db9-4f00-a82a-ca6802806631`), not a TCGA barcode — the only cohort in the corpus where that was true, confirmed with a direct UUID-regex classification (1,231/1,231 UUID-format) and a check that ruled out an easy crosswalk (zero of those UUIDs matched `_biospecimen.csv`'s own UUID column either).

**You had a corrected copy of `TCGA-BRCA_tpm_unstranded.tsv` and replaced the raw file with proper TCGA-barcode headers.** Re-verified from scratch, independent of the original check: the new file's mtime (Apr 30) predates the old one (Jul 29), its header is 1,226/1,226 barcode-format (`TCGA-C8-A1HM-01A`, etc.), all 1,226 columns match a real `Sample` id, and a full re-run now produces **41,708,520 ExpressionObservation rows** across 1,097 Diagnosis / 1,097 Survival / all 3,397 Sample records — the clinical layer was correct all along, only the expression matrix needed replacing. Re-verified referential integrity (0 dangling `PROVIDED_SAMPLE` edges) and placeholder scrubbing (none leaked) on the corrected output.

One residual detail worth flagging, not a problem: the corrected file has **33,984 distinct genes**, versus ~60,616 in every other cohort — a smaller/different gene annotation set than the rest of the corpus. Not investigated further this round; worth knowing if BRCA's gene coverage is ever compared directly against another cohort's.

### 2. TCGA-SKCM: `OF_DISEASE` covers only 118/470 (25%) of `Diagnosis` rows — benign, confirmed

Checked directly against the raw source: 352 of SKCM's 470 diagnosis records have the literal string `"NA"` as their `icd_10_code` in `TCGA-SKCM_clinical.csv`. `"NA"` is a configured placeholder (`config/placeholders.yaml`), so it's correctly scrubbed to empty, and `OF_DISEASE` correctly skips edges with no resolvable disease id — exactly the intended, documented behavior for missing data, not a mapping defect. SKCM's source data is just genuinely sparser on ICD-10 coding than other cohorts (plausibly because melanoma staging/coding practices varied more across contributing sites).

## Verification performed

- Zero Python exceptions across all 27 cohorts in the main batch, plus the standalone BRCA re-run (each cohort wrapped individually, so one failure wouldn't have stopped the batch — none needed it).
- Systematic cross-cohort scan for zero-row and disproportionate-ratio anomalies across every node/edge type, not just spot-checks — this is what caught both findings above, including BRCA's originally-zero expression count.
- Referential integrity re-checked directly on 4 cohorts spanning the size range (smallest: CHOL, two of the largest of the batch: KIRC, HNSC, plus the corrected BRCA): 0 dangling `PROVIDED_SAMPLE` edges in all four.
- Placeholder-scrub re-checked on the same 4 cohorts: no leaked bracket tokens.
- `data/raw/` was not modified by anything this pipeline ran — the only change to it was your own manual replacement of `TCGA-BRCA_tpm_unstranded.tsv` with a corrected file, which is exactly what resolved the BRCA finding above.

## Suggested follow-ups

1. **`data/interim/` on the external volume (77GB+) is safe to delete** if that space is needed — it's fully regenerable on any future re-run of these cohorts, same as the local cleanup done in the earlier round.
2. ACC/PRAD/SARC (alternate dot-named files) and the methylation/mutation/proteomics/enrichment data excluded from this profile's scope from the start remain open, independent follow-ups from the original compatibility report — unchanged by this round.
3. BRCA's smaller gene set (33,984 vs ~60,616 in every other cohort) is worth a closer look if BRCA's gene-level coverage is ever compared directly against another cohort — not investigated further this round.
