# LifeSphere Knowledge-Graph Data Model

The target schema for the Neo4j knowledge graph, and the single source of truth for
what `src/standardise/` must emit and what `src/load/` (BioCypher) loads. Encoded
formally in [`config/schema_config.yaml`](../../config/schema_config.yaml).

Upstream grain and PK/FK contract come from the extractor — see
[`gdc_extraction_notes.md`](../other/gdc_extraction_notes.md). The 12 per-entity TSVs
are already at true 1:many grain, so **the extraction grain is the graph grain**:
standardisation renames and cleans, it does not re-pivot.

Backbone: `Program → Project → Subject → {Diagnosis, Sample, …} → Omics`.

---

## Design rules

1. **Custom lightweight ontology.** Node/edge labels are our own terms (Subject,
   Diagnosis, Sample, `HAS_DIAGNOSIS` …), not Biolink. No external ontology commitment.
2. **1:1 → property, 1:many → node.** An entity that is strictly one-per-parent is folded
   into the parent's properties; a one-to-many entity becomes its own node. Hence
   `demographic` (1:1 with case) becomes Subject properties, while `follow_up`,
   `treatment`, etc. (n per parent) are nodes.
3. **Subject = case.** "Subject" is the standardised rename of GDC `case`; `case_id`
   remains the stable key. One Subject per case; no cross-program patient reconciliation.
4. **Stable IDs.** Node IDs are the GDC UUIDs (`case_id`, `diagnosis_id`, `sample_id`, …).
   `Program`/`Project` are keyed by their natural ids (`program_name`, `project_id`) and
   deduplicated (many case rows repeat them).
5. **Property naming.** Standardisation strips the source entity prefix from content
   columns, then camelCases them for the graph: `diagnosis_ajcc_pathologic_stage →
   ajccPathologicStage`, `demographic_sex_at_birth → sexAtBirth`. Node/edge **labels**
   are PascalCase, relationship types UPPER_SNAKE_CASE, and the graph id property
   (`preferred_id`) is the camelCase of the source id column (`sample_id → sampleId`).
   The snake_case names in the tables below are the *source* columns the config
   references; the graph exposes their camelCase form.
6. **Placeholder scrub.** GDC/BCR placeholder tokens (`[Not Available]`, `[Not Evaluated]`,
   `[Unknown]`, `[Not Applicable]`, `--`) are treated as null and dropped.

---

## Nodes

IDs are GDC UUIDs unless noted. Property lists are representative; the full content
column set of each source TSV carries through (prefix-stripped) unless pruned.

| Node label | ID (source column) | Source TSV | Key properties (prefix stripped) |
|---|---|---|---|
| **Program** | `program_name` (dedup) | `subject` | — |
| **Project** | `project_id` (dedup) | `subject` | project_name, disease_type, primary_site, program_name |
| **Subject** | `case_id` | `subject` (the case table, +`demographic_*` folded in) | submitter_id, disease_type, primary_site, sex_at_birth, race, ethnicity, vital_status, age_at_index, days_to_birth, year_of_death, cause_of_death |
| **Diagnosis** | `diagnosis_id` | `diagnosis` | primary_diagnosis, ajcc_pathologic_stage, tumor_grade, morphology, tissue_or_organ_of_origin, age_at_diagnosis, days_to_diagnosis, prior_malignancy |
| **Treatment** | `treatment_id` | `treatment` | treatment_type, therapeutic_agents, treatment_intent_type, treatment_outcome, days_to_treatment_start, days_to_treatment_end |
| **PathologyDetail** | `pathology_detail_id` | `pathology_detail` | percent_tumor_*, lymph-node counts, margin/invasion fields |
| **FollowUp** | `follow_up_id` | `follow_up` | days_to_follow_up, disease_response, progression_or_recurrence, days_to_progression, days_to_recurrence |
| **MolecularTest** | `molecular_test_id` | `molecular_test` | gene_symbol, molecular_analysis_method, test_result, variant_type, laboratory_test (ER/PR/HER2 biomarkers live here) |
| **PhenotypeObservation** | `exposure_id` / `family_history_id` | `exposure`, `family_history` (both append into the same CSV) | exposure fields: tobacco_smoking_status, pack_years_smoked, alcohol_history, bmi; family-history fields: relationship_primary_diagnosis, relative_with_cancer_history |
| **Sample** | `sample_id` (= aliquot) | `sample` (aliquot grain) | type, tissue_type, tumor_descriptor, specimen_type, preservation_method, days_to_collection; provenance: gdc_sample_id, gdc_sample_submitter_id, portion_id, analyte_id, analyte_type |
| **ExperimentalCondition** | `group_id` (dedup) | `sample` (derived from `sample_type`) | group_label (control/treatment arm) |

`other_clinical_attribute` is empty for TCGA and has no node type. The `file` table
(908k rows, provenance) is **not** a backbone node; it feeds omics-edge provenance later.

---

## Relationships

Custom predicates, direction parent → child. Each edge is derived from FK columns
already present in a single source TSV (no joins needed).

| Edge | From → To | Source TSV | source_id → target_id |
|---|---|---|---|
| `HAS_PROJECT` | Program → Project | `case` (dedup) | program_name → project_id |
| `ENROLLS` | Project → Subject | `case` | project_id → case_id |
| `HAS_DIAGNOSIS` | Subject → Diagnosis | `diagnosis` | case_id → diagnosis_id |
| `HAS_TREATMENT` | Diagnosis → Treatment | `treatment` | diagnosis_id → treatment_id |
| `HAS_PATHOLOGY` | Diagnosis → PathologyDetail | `pathology_detail` | diagnosis_id → pathology_detail_id |
| `HAS_FOLLOWUP` | Subject → FollowUp | `follow_up` | case_id → follow_up_id |
| `HAS_MOLECULAR_TEST` | Diagnosis **or** FollowUp → MolecularTest | `molecular_test` | parent_id → molecular_test_id (parent chosen by `parent_entity`) |
| `HAS_PHENOTYPE_OBSERVATION` | Subject → PhenotypeObservation | `exposure`, `family_history` (both append into `HAS_PHENOTYPE_OBSERVATION.csv`) | case_id → exposure_id / family_history_id |
| `PROVIDED_SAMPLE` | Subject → Sample | `sample` | case_id → sample_id |
| `HAS_CONDITION` | Sample → ExperimentalCondition | `sample` | sample_id → group_id |

**Backbone shape.** GDC has no FK from Sample to Diagnosis; both are children of the case.
So Diagnosis and Sample are **parallel branches off Subject**, not a chain. (A tumour↔sample
link can be inferred later from `sample_type` if a use case needs it.)

**Molecular-test routing.** `molecular_test.parent_entity ∈ {diagnosis, follow_up}` selects
whether the edge originates from a Diagnosis or a FollowUp; `parent_id` is the source node id.

---

## Omics layer

The omics ontology is modelled and wired through the standardise + load pipelines. **This pass
plumbs the model with a synthetic fixture** (`tests/fixtures/omics_smoke`); real GDC omics-file
parsing and real Omnipath ingestion are still deferred (see *Deferred* below).

**Measurements are reified into per-assay observation nodes** — *not* stored as edge
properties. Each measurement is one node carrying its value(s) + provenance, wired between the
Sample and the shared feature it measures:

```
(Sample)-[:HAS_EXPRESSION_OBSERVATION]->(ExpressionObservation {tpm, fpkm, aliquot_id, file_id})-[:MEASURES_GENE]->(Gene)
(Sample)-[:HAS_METHYLATION_OBSERVATION]->(MethylationObservation {beta_value, ...})-[:MEASURES_CPG]->(CpGSite)
(Sample)-[:HAS_VARIANT_OBSERVATION]->(VariantObservation {vaf, consequence, impact, ...})-[:OBSERVED_VARIANT]->(Variant)
(Sample)-[:HAS_PROTEIN_OBSERVATION]->(ProteinObservation {value, ...})-[:MEASURES_PROTEIN]->(Protein)
```

- **Shared feature nodes** — a deduplicated reference dimension reused across all samples:
  `Gene` (Ensembl id), `CpGSite` (cg#), `Variant` (`variant_id`, keeps `gene_ensembl`),
  `Protein` (UniProt), `Pathway`. `CpGSite`/`Variant` carry chromosome-specific position props.
- **Observation nodes** — per-assay, one per sample×feature: `ExpressionObservation`,
  `MethylationObservation`, `VariantObservation`, `ProteinObservation`. Every observation
  carries `aliquot_id` / `file_id` for provenance to the assay file.
- **Static biology** (Omnipath): `Variant ─AFFECTS_GENE→ Gene`, `Gene ─PARTICIPATES_IN_PATHWAY→ Pathway`,
  `Gene ─ENCODES→ Protein`. All edges are plain (no properties).

**Why reify instead of valued edges.** The measurement count is identical either way (one
element per sample×feature); reification adds a node + a hop but buys robust node-property
indexing in Neo4j, room to link an observation out to further provenance (File/assay/platform),
and it means **no engine change** — measurement values live on nodes (which already pass
properties through), so every edge stays a plain `source_id,target_id` pair.

**Reference files vs measurement files.** Feature nodes come from dedicated reference TSVs
(`{base}.gene.tsv`, `.cpg_site.tsv`, `.variant.tsv`, `.protein.tsv`, `.pathway.tsv`) — one
source file per node label (feature nodes are deduplicated reference dimensions). Each measurement TSV (`{base}.gene_expression.tsv`,
`.methylation.tsv`, `.somatic_mutation.tsv`, `.protein_expression.tsv`) yields its observation
node **and** both of its edges (the same one-file→node+edges pattern as `subject.tsv`). Static
biology comes from `{base}.gene_pathway.tsv` and `{base}.gene_protein.tsv` (edge-only).

**Sample = aliquot.** The Sample node is the **aliquot** (the analysed unit omics files map
to), produced by a post-processing merge in the extractor (`src/extract/biospecimen.py`):
sample-level descriptors are grafted onto every aliquot row, `aliquot_id` becomes the Sample
`sample_id`, and the originating GDC sample is retained as `gdc_sample_id`. `portion_id` /
`analyte_*` ride along as provenance. See `docs/other/gdc_extraction_notes.md`.

**Omics bridge (2026-07-02).** `src/extract/omics_reshape.py` now turns each raw concatenated
matrix (`{base}.{type}.matrix.tsv`) into the standardiser-ready feature + observation TSVs, and
`omics.py` captures the file→aliquot mapping so observations carry the Sample (`sample_id`).
Covers expression (`gene` + `gene_expression`), methylation (`cpg_site` + `methylation`), and
variation/MAF (`variant` + `somatic_mutation`, per-row tumour aliquot as `sample_id`). Verified
reshape→standardise→validate on synthetic matrices; **not yet run on a live gdc-client download**.

**Deferred.** (1) Run the omics bridge on a real GDC download (needs network + gdc-client);
protein/RPPA (`protein_expression`) is modelled but has no extractor yet. (2) Real Omnipath
ingestion for the static-biology edges. (3) Biospecimen QC (percent tumour cells, RIN, 260/280)
wanted on the observations / Sample is **not yet extracted** — the merged `sample.tsv` carries
descriptors + ids but no slide/analyte QC; surfacing it needs the extractor emitters extended
first (add slide and analyte QC), tracked separately from this model.

---

## Single-cell, spatial & provenance layer (draft-3 adoptions)

Concepts adopted from `docs/other/neo4j_updated_schema_draft_3.md` (2026-07-02):

- **Pseudobulk folds into `ExpressionObservation`, not a separate node.** A pseudobulk value is a
  cell-type-stratified gene-expression observation, so it is the same reified `ExpressionObservation`
  node as bulk RNA-seq, distinguished by `assay_type` (`bulk` | `pseudobulk`) and an extra
  `(ExpressionObservation)-[:OF_CELL_TYPE]->(CellType)` edge. Bulk grain is `sample × gene`; pseudobulk
  grain is `sample × cell_type × gene` (`expression_id = {sample_id}:{cell_type_id}:{gene_ensembl}`),
  carrying `mean_expr` / `pct_expressing` alongside `tpm`. Because `standardise_edge` skips
  blank FKs, `OF_CELL_TYPE` materialises only for pseudobulk rows (bulk rows leave
  `cell_type_id` empty). Query bulk-only with `WHERE e.assay_type = 'bulk'`.
- **CellSet, not per-cell nodes, for dissociated scRNA.** A `CellSet` is a reproducible
  cell group (cluster / cell-type population); sample participation is
  `(Sample)-[:CONTRIBUTES_TO {contributed_cell_count, fraction_of_sample_cells}]->(CellSet)`,
  and annotation is `(CellSet)-[:ANNOTATED_AS_CELL_TYPE {source_value,
  ontology_mapping_status}]->(CellType)`. This replaces the earlier `Cluster` +
  `CellTypeProportion` nodes. Per-unit `Cell` nodes (x,y, `ADJACENT_TO`) are kept **only
  for spatial**, where topology is the point.
- **CellState** is its own node (`(CellSet)-[:HAS_CELL_STATE]->(CellState)`), never a
  `CellType` property (avoids global-overwrite / combinatorial-explosion).
- **Disease** as a stable ontology-backed node (`(Diagnosis)-[:OF_DISEASE]->(Disease)`),
  splitting the disease concept from the GDC diagnosis record for cross-dataset queries.
- **ProcessedDataOutput** as a first-class external-file pointer (checksum/format/path),
  linked `(Assay)-[:GENERATED_OUTPUT]->` and `(Observation)-[:FROM_OUTPUT]->`, unifying
  bulk `file_id` and single-cell matrix provenance.

**Edge properties are now supported** by the standardiser: an `edges.json` entry may
declare `"props": [...]`, which `standardise_edge` emits after `source_id,target_id`
(placeholder-scrubbed; absent columns dropped). This enables the `CONTRIBUTES_TO` /
`ANNOTATED_AS_CELL_TYPE` qualifiers above. Deferred: `MARKER_GENE` score and
`ADJACENT_TO` distance (reify or add typed edge-prop declarations if needed). The whole
layer is inert until the single-cell reshaper emits its TSVs (see
`docs/todo/020726_singlecell_scaffold.md`).

## Survival-outcome layer

GDC ships **no** precomputed survival endpoint (there is no `OS`/`OS.time` column). The
three standard endpoints are **derived per-subject** by `src/extract/survival_reshape.py`
(a post-extract reshape, same role as `omics_reshape.py`) and modelled as **subclasses of a
common `SurvivalOutcome`** — they share one property schema (`outcome_type`, `event`,
`time_days`) via `is_a: survival outcome` in `schema_config.yaml`.

| Node (`is_a: survival outcome`) | Source TSV | Edge | event = 1 when | time_days |
|---|---|---|---|---|
| `OverallSurvival` (`os_id`) | `overall_survival` | `HAS_OVERALL_SURVIVAL` | subject died | `days_to_death`, else last contact (censored) |
| `ProgressionFreeInterval` (`pfi_id`) | `progression_free_interval` | `HAS_PROGRESSION_FREE_INTERVAL` | progression, recurrence, or death | earliest of those, else last contact |
| `DiseaseFreeInterval` (`dfi_id`) | `disease_free_interval` | `HAS_DISEASE_FREE_INTERVAL` | recurrence | `days_to_recurrence`, else last contact |

All three edges run `Subject → outcome` on `case_id → {os,pfi,dfi}_id`. `last contact` =
`max(diagnosis.days_to_last_follow_up, follow_up.days_to_follow_up)`. Surrogate ids are
deterministic (`{case_id}:OS|PFI|DFI`); a subject with no usable time for an outcome is
skipped (not emitted with a null time). **Each subclass keeps a distinct `id_col`** because
the loader (`neo4j_loader.load_schema`) keys node labels by `id_col` — a shared id column
would collapse the three labels.

Rules follow the TCGA Clinical Data Resource (Liu et al., Cell 2018) adapted to GDC
harmonized fields. Caveats: OS requires `demographic.days_to_death` (added to
`gdc_data_dict.json`; a dead subject missing it censors rather than dropping); TCGA-CDR
restricts DFI to subjects tumor-free after therapy, but GDC carries no clean initial
tumor-free flag, so DFI here is a recurrence-based approximation over all subjects. Tested
via `tests/test_survival_reshape.py`.

## BioCypher encoding

`config/schema_config.yaml` declares every node/edge above with a custom `input_label`,
`represented_as: node|relationship`, and a `properties` block. `src/load/adapters.py` reads
the standardised CSVs and yields BioCypher node/edge tuples; `src/load/run.py` runs BioCypher
to write the Neo4j import files. See [`../user_guides/standardisation.md`](../user_guides/standardisation.md)
for the run flow.
