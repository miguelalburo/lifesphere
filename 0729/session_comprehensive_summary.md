<!-- title: Session Summary: Schema Migration → Full TCGA Corpus Load -->

# Session Summary: Schema Migration → Full TCGA Corpus Load

Consolidated retrospective covering every file change and real run from Proposal A onward. The earlier schema-diff analysis (`neo4j_updated_schema_draft_3.md` vs code, then `neo4j_updated_schema_new_v2.md` vs code) set the direction for this work but didn't itself touch any files — see [the draft_3 diff](https://claude.ai/code/artifact/8118c879-1c5d-4d30-9ccc-a15a4d73fde0) and [the new_v2 diff](https://claude.ai/code/artifact/bf80d5fd-ed89-485e-aca9-f23ac56f9937) for that background. Everything below is condensed; each linked artifact has the full detail (exact diffs, per-cohort tables, verification transcripts).

## 1. What changed, per file

| File | What changed | From |
|---|---|---|
| `config/schema/nodes.yaml` | Renamed/added properties on `GenomicRegion`, `Variant`, `CpGSite`, `Gene`, `Study`, `Assay`, `LibraryPreparation`, `PhenotypeObservation`, `ExperimentalCondition` (e.g. `start`→`startPosition`, `Study.diseaseType`→`diseaseCategory`, `+coordinateSystem`, `+referenceGenome`). Old names commented out in place, not deleted. **Disease's MONDO-centric rewrite was deliberately discarded** — TCGA is ICD-10-coded. | [Proposal A Implementation Summary](https://claude.ai/code/artifact/8bb3ea16-f086-4f4e-996f-065290147055) |
| `config/schema/edges.yaml` | `MEASURES_GENE` trimmed to `ExpressionObservation→Gene` only, no properties — dropped an undocumented `MethylationObservation` pair and `functionalDomain` property (confirmed unused by any mapping config). | same |
| `tests/test_variation_integration.py` | Assertion updated from the now-renamed `positionStart` column to `startPosition`. | [Follow-Up: Variant Pipeline Wiring](https://claude.ai/code/artifact/762dd131-42d1-42a0-8aea-e1a26eae90d6) |
| `config/mapping/omics.yaml` | Added `position_start`→`startPosition` / `position_end`→`endPosition` aliases (in `omics.yaml`, not `traditional.yaml`, since the GDC path uses `--profile omics` directly and would otherwise have stayed broken). | same |
| `config/mapping/tcga_bulk.yaml` | **New file.** Binds the bulk-downloaded TCGA files (`_biospecimen.csv`, `_clinical.csv`, `_survival.csv`, `_tpm_unstranded.tsv`) to `Sample`/`Subject`/`Diagnosis`/`Disease`/`Survival` + edges, reusing `include: [omics]` for the expression pipeline. Later gained 2 more `Diagnosis` aliases (`figo_stage`, `ann_arbor_clinical_stage` → `pathologicStage`) plus a documentation block recording "no schema home" findings. | [TCGA Bulk-Download Profile Summary](https://claude.ai/code/artifact/5125e435-c3dd-45ee-b343-d72cc0f77451), [Alias-Discovery Refinement](https://claude.ai/code/artifact/6edd9f6e-bf20-4cc9-9aa8-b4f084f5d129) |
| `config/placeholders.yaml` | Added 5 bracket-wrapped placeholder tokens (`[Not Available]`, `[Not Applicable]`, `[Unknown]`, `[Discrepancy]`, `[Not Evaluated]`) — confirmed as the exact set present in the raw clinical/survival files, not guessed. | TCGA Bulk-Download Profile Summary |
| `src/standardise/transform.py` | Added `truncate_barcode()` — keeps only the first N `-`-separated barcode segments, bridging a Sample (aliquot-grain) id down to a Subject (patient-grain) id. | same |
| `src/standardise/mapping.py` | Added `truncate_start_segments`/`truncate_end_segments` fields to `EdgeMapping` (default `None`, no effect on other profiles). | same |
| `src/standardise/run.py` | `_resolve_source()`: substitutes a `{dataset}` placeholder in `file:` entries with the actual dataset folder name, so one profile works across every cohort. `_write_edge()`: wired in `truncate_barcode()`. | same |
| `src/reshape/matrix.py` | Same `{dataset}` substitution for reshape `input:` entries; also fixed `sourceFile` provenance and log messages to use the *resolved* filename (caught during verification — they'd been writing the literal `{dataset}` template into `ExpressionObservation.sourceFile` otherwise). | same |

Two rounds of raw-data edits were yours, not this pipeline's: replacing `TCGA-BRCA_tpm_unstranded.tsv` (fixed a UUID-vs-barcode mismatch) and replacing ACC/PRAD/SARC's clinical/survival/expression files (Xena-flattened format → standard GDC shape). Both are covered in "Real run results" below.

## 2. Real run results (final state, all verification already performed)

**All 33 TCGA cohort folders in `data/raw/` are now loaded** with Sample/Subject/Diagnosis/Disease/Survival/ExpressionObservation data.

| Batch | Cohorts | Output location | Size |
|---|---|---|---|
| Initial 3 | CESC, BLCA, LAML | local `data/standardised/` | 15GB |
| Remaining 27 | CHOL, DLBC, UCS, UVM, MESO, KICH, THYM, TGCT, READ, PAAD, PCPG, ESCA, GBM, KIRP, LIHC, OV, STAD, SKCM, COAD, LGG, LUSC, HNSC, THCA, UCEC, LUAD, KIRC, BRCA | `/Volumes/BoFang/.../data/standardised/` | 153GB |
| ACC/PRAD/SARC | ACC, SARC, PRAD | same external volume | 15.2GB |

**Total: ~183GB across all 33 cohorts.** Every cohort passed the same verification: `PROVIDED_SAMPLE` referential integrity (0 dangling edges), placeholder scrubbing (0 leaked bracket tokens), and `data/raw/` confirmed untouched by the pipeline itself throughout. Full per-cohort tables (sample/subject/diagnosis/survival/expression counts, timing) are in the [27-cohort load summary](https://claude.ai/code/artifact/88b54762-e922-442a-ab3b-a07f7db20e18) and the [ACC/PRAD/SARC summary](https://claude.ai/code/artifact/2c2d5d0b-ec37-40bc-af36-7c08855c5b6c).

**Two anomalies surfaced and resolved:**
- **BRCA** initially loaded with zero expression rows — root-caused to its `_tpm_unstranded.tsv` using GDC UUIDs as column headers instead of TCGA barcodes (confirmed: 1,231/1,231 UUID-format, and ruled out an easy crosswalk via biospecimen's own UUID column). You replaced the file with a corrected version; re-verified independently (file mtime, byte-level header inspection, full match-rate check) and re-ran — now 41.7M `ExpressionObservation` rows, fully clean.
- **SKCM**: only 25% of `Diagnosis` rows resolve to a `Disease` via `OF_DISEASE`. Confirmed benign — 352 of 470 diagnosis records have the literal string `"NA"` as their `icd_10_code` in the raw source file, correctly scrubbed and skipped.

`data/interim/` (regenerable reshape intermediates) was cleaned up both locally (~9GB) and on the external volume (~83GB) after each batch completed, since it's fully reconstructed on any future re-run.

## 3. Known limitations (deliberate scope boundaries, not defects)

- **Disease stays ICD-10-shaped**, not MONDO — an explicit decision, not an oversight, since TCGA data is ICD-10-coded.
- **`Sample.subjectId` is not populated** — only the `PROVIDED_SAMPLE` *edge* bridges Sample (aliquot-grain) to Subject (patient-grain) via barcode truncation; the property mirror was intentionally left out of scope (would need a separate per-property transform hook that doesn't exist).
- **`Survival` only captures OS** (overall survival) — the source file carries DSS/DFI/PFI too, but there's no reshape capability to melt a wide multi-endpoint row into separate records.
- **Expression is TPM-only**, not raw counts — deliberate, to avoid an id collision (`ExpressionObservation`'s id is minted from `(sample_id, gene_id)` only, so both units for the same pair would silently overwrite each other).
- **Methylation, mutation (MAF-style and CNV), proteomics, and BRCA's differential-expression/enrichment bundle are entirely out of scope.** Proteomics/metabolite observation types don't even exist in the reshape/observation code layer today (`src/observation.py` has no `PROTEIN_OBS_COLUMNS`).
- **The two shared pan-cancer files** (`TCGA_CDR_Survival_Master.csv`, `All_PanCancer_Subtypes.csv`) are excluded — the mapping engine has no per-dataset row-filtering mechanism, and these files are duplicated unfiltered across ~31 folders.
- **AJCC T/N/M sub-stage components, staging-edition, and Diagnosis-level laterality** have no schema property to hold them, despite recurring in 27-28 of 29 checked cohorts — documented in `tcga_bulk.yaml`'s own comments, not modeled.
- **`Gene`/`CpGSite` reference annotation and `GenomicRegion`** remain unpopulated by any pipeline — they're "dedup reference dimensions" whose full annotation was always meant to come from a separate source that was never wired.
- Standard TCGA/GDC data gaps (Subject: species, consentStatus, bloodType, etc.; Sample: cellularComposition, purity, etc.) — confirmed absent across all cohorts checked, consistent with `extract.yaml`'s own documented gaps, not a mapping defect.
- **BRCA's corrected expression file has ~34,000 genes vs. ~60,616 in every other cohort** — noted, not investigated further.

## 4. Unsolved / open issues

- **Proposal 3** (proteomics/metabolite code support) and **Proposal 4** (row-filtering in the mapping engine, to safely bind the shared pan-cancer files) from the original compatibility report — neither implemented.
- **`config/mapping/extract.yaml`'s `Intervention` binding** was flagged early on as possibly not populating the `_subtypeLabel` discriminator column needed for `Drug`/`Radiation`/`Surgery`/etc. multi-labelling — never independently verified or fixed in this session.
- **`Study.diseaseCategory`, `Assay.assayChemistry`, `LibraryPreparation.libraryChemistry`** remain aspirational properties with no GDC/bulk source binding — flagged, deliberately deferred, still unresolved.
- No performance work done on the pure-Python matrix melt (no pandas) — the 27-cohort batch took ~6.8 hours; this is fine for a one-time load but would matter if reloading becomes routine.
- ACC/PRAD/SARC's own methylation/mutation files (`_methylation450.tsv`, `_somaticmutation_wxs.tsv`, `_star_fpkm-uq.tsv`, the hg19/hg38 probe manifests) were never revisited after the original compatibility report — still fully unmapped.

## 5. Suggested next steps

1. Decide whether the "no schema home" findings (AJCC T/N/M, staging edition, Diagnosis laterality) are worth formal schema properties, now that real cross-cohort evidence exists for how often they'd be populated.
2. Scope Proposal 3 (proteomics/metabolite ingestion) if BRCA's proteomics/CNV data — or any future cohort's — needs to come into the graph.
3. Scope Proposal 4 (mapping-engine row filtering) if the two shared pan-cancer files' subtype/survival-master data is wanted without a separate pre-split step.
4. Verify (independently of this session) whether GDC-sourced `Intervention` rows are actually getting their subtype labels — flagged but never checked.
5. If BRCA's smaller gene set matters for downstream cross-cohort queries, investigate why (different annotation version, different quantification pipeline) before relying on gene-level comparisons involving BRCA.
6. Methylation/mutation ingestion (across all cohorts that have it: ACC, PRAD, SARC, and BRCA's CNV) remains a fully open, separately-scoped initiative if that data is wanted in the graph.
