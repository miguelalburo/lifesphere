<!-- title: TCGA Bulk-Download Mapping Profile: Implementation Summary -->

# TCGA Bulk-Download Mapping Profile — Implementation Summary

**What this covers:** Proposal 1 from the [data/raw Compatibility Analysis](https://claude.ai/code/artifact/c4cf94fe-59b6-4c55-91be-9173bf181b99) — a new config/mapping profile that binds the actual bulk-downloaded TCGA files in `data/raw/` to the schema, targeting `data/standardised/` as the output. **No file under `data/raw/` was read-modified, renamed, or deleted at any point** — every raw file used in verification was a copy made in a separate scratch directory outside the repo.

## Decisions locked in before implementation

Two rounds of clarifying questions surfaced real architectural gaps the original proposal hadn't accounted for. Resolved as follows:

| Question | Decision |
|---|---|
| Raw filenames embed the dataset code (`TCGA-ACC_biospecimen.csv`); the loader has no per-dataset templating | Add a small `{dataset}` placeholder substitution to `src/standardise`/`src/reshape` — one shared profile works for every cohort instead of ~27 near-duplicate YAML files |
| Corpus variance (ACC/PRAD/SARC use a different file-naming convention) | Standard-shape files only this round: `*_biospecimen.csv`, `*_clinical.csv`, `*_survival.csv`, `*_tpm_unstranded.tsv`. ACC/PRAD/SARC's dot-named files, methylation, mutation, and BRCA's proteomics/CNV/enrichment bundle stay out of scope |
| Both `*_tpm_unstranded.tsv` and `*_unstranded_counts.tsv` exist for the same sample/gene pairs; `ExpressionObservation`'s id is minted from `(sample_id, gene_id)` only | TPM only — avoids the id collision entirely |
| Bracket-wrapped placeholders (`"[Not Available]"`, etc.) aren't in `config/placeholders.yaml`'s scrub list | Add them now (pure addition) |
| Sample (`*_biospecimen.csv`, aliquot grain) and Subject (`*_clinical.csv`, patient grain) share no raw column | Add a small barcode-truncation helper so `PROVIDED_SAMPLE` and the graph connect correctly |

## Files changed

Every change is additive: no existing line was deleted from any file below. Renames/behavior changes are old code commented out in place, immediately followed by the new code, per your instruction.

| File | Change |
|---|---|
| `config/mapping/tcga_bulk.yaml` | **New file.** The profile itself — see §2 below. |
| `config/placeholders.yaml` | Added 5 bracket-wrapped tokens (`[Not Available]`, `[Not Applicable]`, `[Unknown]`, `[Discrepancy]`, `[Not Evaluated]`) — verified these are the exact 5 distinct tokens actually present in the raw clinical/survival files, not a guessed list. |
| `src/standardise/transform.py` | Added `truncate_barcode(value, segments)` — keeps only the first N `-`-separated parts of a barcode. Mirrors the existing `strip_prefix` pattern; `segments=None` (the default for every other profile) is a no-op. |
| `src/standardise/mapping.py` | Added `truncate_start_segments`/`truncate_end_segments` fields to `EdgeMapping` (default `None`, no behavior change for `extract`/`omics`/`traditional`), parsed in `load_mapping()`. |
| `src/standardise/run.py` | `_resolve_source()`: substitutes a `{dataset}` placeholder in a `file:` entry with the dataset's own directory name before resolving. `_write_edge()`: old start/end-id lines commented out, replaced with lines that additionally apply `truncate_barcode()` when `cfg.truncate_start_segments`/`truncate_end_segments` is set. |
| `src/reshape/matrix.py` | `melt_matrix()`: substitutes `{dataset}` in `spec.input` before resolving the source path; the resolved name is also now used for the "skip" log messages and the `sourceFile` provenance stamp (the original unsubstituted template string would otherwise have been written into every `ExpressionObservation.sourceFile` — caught during verification, see below). |

## The profile itself

`config/mapping/tcga_bulk.yaml` reuses `include: [omics]` (same pattern as `traditional.yaml`) for the expression-observation machinery, and defines new bindings for the clinical layer:

- **Nodes:** `Sample` (← `*_biospecimen.csv`, keyed on the aliquot barcode), `Subject`/`Diagnosis`/`Disease` (← `*_clinical.csv`, keyed on patient barcode / `diagnosis_id` / `icd_10_code`), `Survival` (← `*_survival.csv`, keyed on `bcr_patient_barcode`).
- **Edges:** `PROVIDED_SAMPLE` (Subject→Sample, using `truncate_start_segments: 3` to bridge the barcode-grain mismatch), `HAS_DIAGNOSIS`, `OF_DISEASE`, `HAS_SURVIVAL_RECORD`.
- **Reshape:** one `matrix` spec melting `{dataset}_tpm_unstranded.tsv` into `expression_observation.tsv`, feeding the inherited `ExpressionObservation`/`Gene`/`Assay` bindings from `omics.yaml`.
- Diagnosis/Disease aliases largely mirror `config/mapping/extract.yaml`'s existing choices, since this bulk export uses many of the same GDC-native column names — plus one addition `extract.yaml` doesn't have (`age_at_onset` → `ageOfOnsetDays`).

## Known limitations (by design, documented in the profile's own comments)

1. **`Sample.subjectId` stays empty.** The barcode-truncation fix was scoped to the `PROVIDED_SAMPLE` *edge* only (graph connectivity), not to node *properties* — populating the mirror property too would need a second, more invasive mechanism (a per-property transform hook, which doesn't exist anywhere in the pipeline today). The edge is what actually connects Subject and Sample in the graph; the property is a convenience mirror. Confirmed in verification: 0 of 888 `PROVIDED_SAMPLE` edges pointed at a non-existent Subject id.
2. **Only OS (overall survival) is loaded from `*_survival.csv`.** The file carries four survival endpoints (OS, DSS, DFI, PFI) as parallel columns on one wide row per patient; there's no reshape capability to melt a wide multi-endpoint row into separate `Survival` records, so `survivalType` is left unpopulated rather than hardcoded to a wrong/misleading value.
3. **A dataset missing one of the four source files degrades independently per node/edge**, not as an all-or-nothing failure (confirmed for BLCA, which has no `_survival.csv`, and LAML, which has no `_clinical.csv` — see verification below). One side effect: LAML's `PROVIDED_SAMPLE` edges still get written even though no `Subject` node is (since Sample's own file has everything the edge needs) — this produces edges pointing at Subject ids with no corresponding node/properties, which Neo4j's `MERGE` would create as bare stub nodes on load. This matches the existing pipeline's general philosophy elsewhere (e.g. `extract.yaml`'s documented "TCGA-CHOL has no exposure records" case) rather than being a new problem introduced here.
4. **`data/standardised/` now holds real, complete output for three cohorts** (CESC, BLCA, LAML) — see "Real production run" below. The remaining ~24 standard-shape cohorts were not run this round; each takes several minutes given the pure-Python matrix melt (no pandas) over ~60,661-gene matrices.

## Verification performed

1. **`load_schema()` / `load_mapping('tcga_bulk')`**: both load and validate cleanly (42 nodes, 52 edges, zero schema errors; new profile parses with the expected node/edge set, correctly inheriting `omics`'s bindings).
2. **`python -m src.standardise <dataset> --profile tcga_bulk --report`** against the real `TCGA-CESC` raw files: confirmed real-file column coverage (which properties matched, by which strategy, and which raw columns are still unused) without writing anything.
3. **Full end-to-end `standardise()` run**, using small copies of the real `_biospecimen.csv`/`_clinical.csv`/`_survival.csv` files (unmodified, just copied to a scratch directory outside the repo) plus a tiny synthetic 2-gene/3-sample expression matrix (to exercise the reshape path without waiting on the full-scale melt) — this is a faster but equally real exercise of every code path touched this round:
   - Schema/mapping loading, `{dataset}` substitution (both in `run.py` and `matrix.py`), barcode truncation, placeholder scrubbing, and the inherited omics observation bindings all ran together, unmodified from how a real dataset run would behave.
   - **Referential integrity check**: wrote a script to confirm every one of 888 `PROVIDED_SAMPLE` edges' truncated `startId` matched a real `Subject` node id — 0 mismatches.
   - **Placeholder check**: grepped every output CSV for the 5 newly-added bracket tokens — none found (correctly scrubbed).
   - **Provenance check**: `ExpressionObservation.sourceFile` correctly reads `TCGA-CESC_tpm_unstranded.tsv` (the resolved filename), not the unsubstituted `{dataset}_tpm_unstranded.tsv` template — this caught a real bug in my first pass (the `melt_matrix` log/provenance lines still referenced `spec.input` after I'd only fixed the path-resolution line), fixed before finishing.
   - **Graceful-degradation check**: re-ran against copies of BLCA's (`_biospecimen.csv` + `_clinical.csv`, no survival file) and LAML's (`_biospecimen.csv` + `_survival.csv`, no clinical file) real files — both produced exactly the expected partial output (BLCA: Sample/Subject/Diagnosis/Disease but no Survival; LAML: Sample/Survival but no Subject/Diagnosis/Disease), with no errors or crashes.
4. **Full regression suite**: `pytest` — **324/324 passed**, confirming none of the additive changes to `run.py`/`mapping.py`/`matrix.py`/`transform.py` affected the `extract`, `omics`, or `traditional` profiles' existing behavior.

## Real production run

After the initial verification (above), the real, complete pipeline was run against the actual `data/raw/` files, writing real output into `data/standardised/` — not a synthetic smoke test. `data/raw/` was not modified in any way; this only reads from it.

| Dataset | Wall time | ExpressionObservation rows | Sample / Subject / Diagnosis / Disease / Survival | Notes |
|---|---|---|---|---|
| TCGA-CESC | 400s (~6.7 min) | 18,743,940 | 888 / 307 / 307 / 4 / 307 | Full coverage, all node/edge types populated |
| TCGA-BLCA | 567s (~9.5 min) | 25,962,480 | 1,240 / 412 / 412 / 8 / — | No Survival, as expected (no `_survival.csv` for this cohort) |
| TCGA-LAML | 203s (~3.4 min) | 9,159,660 | 697 / — / — / — / 200 | No Subject/Diagnosis/Disease, as expected (no `_clinical.csv` for this cohort) |

Total: **~19.5 minutes**, **15 GB** written to `data/standardised/` (5.3 GB CESC, 7.3 GB BLCA, 2.6 GB LAML — the size mostly comes from `ExpressionObservation.csv` and its mirror `HAS_EXPRESSION_OBSERVATION`/`MEASURES_GENE` edge files, each storing the full gene × sample matrix as long-form rows).

Re-verified against the **real** output (not the earlier synthetic one) directly, at full scale:
- **Referential integrity**: 0 of 888 (CESC), 0 of 1,240 (BLCA), 0 of 697 (LAML) `PROVIDED_SAMPLE` edges point at a `Sample` id missing from that dataset's own `Sample.csv`.
- **Placeholder scrubbing**: grepped every output file (tens of millions of rows) for the 5 newly-added bracket tokens across all three datasets — none found in any of them.
- **Provenance**: `ExpressionObservation.sourceFile` correctly reads the resolved filename (e.g. `TCGA-BLCA_tpm_unstranded.tsv`) in every dataset, not the unsubstituted `{dataset}_tpm_unstranded.tsv` template.

One operational note from this run: an earlier attempt at this same 3-dataset run was interrupted partway through (killed after ~6 minutes, having reached `MEASURES_GENE` for CESC but before its remaining edge types), which left a 4.4 GB **partial** `data/standardised/TCGA-CESC/` on disk — missing 5 of 7 edge types. Since `standardise()` always regenerates every output file it's asked to write (documented behavior, not a special case), simply re-running it to completion overwrote that partial state cleanly with no manual cleanup needed.

## Suggested next steps

1. Run the remaining ~24 standard-shape cohorts the same way — each takes several minutes given the pure-Python matrix melt; consider whether a faster (e.g. batched/vectorized) melt path is worth it if all ~27 standard cohorts are to be loaded routinely, given the ~15 GB / 3-dataset footprint observed here.
2. Extend `config/mapping/extract.yaml`'s alias-discovery pattern (`--report --values`) across a few more cohorts to refine the Diagnosis/Subject alias list — the current set mirrors `extract.yaml`'s existing choices plus one addition, but wasn't exhaustively tuned against every cohort's column variations.
3. Decide whether to invest in Proposal 4 (row-filtering in the mapping engine) to also bring in the two shared pan-cancer files, or Proposal 3 (proteomics/CNV code support) for BRCA's richer data — both remain open, independent follow-ups from the original compatibility report.
