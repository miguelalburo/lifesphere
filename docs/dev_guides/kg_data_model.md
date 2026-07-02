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
   columns: `diagnosis_ajcc_pathologic_stage → ajcc_pathologic_stage`,
   `demographic_sex_at_birth → sex_at_birth`.
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
| **Exposure** | `exposure_id` | `exposure` | tobacco_smoking_status, pack_years_smoked, alcohol_history, bmi |
| **FamilyHistory** | `family_history_id` | `family_history` | relationship_primary_diagnosis, relative_with_cancer_history |
| **Sample** | `sample_id` (= aliquot) | `sample` (aliquot grain) | type, tissue_type, tumor_descriptor, specimen_type, preservation_method, days_to_collection; provenance: gdc_sample_id, gdc_sample_submitter_id, portion_id, analyte_id, analyte_type |

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
| `HAS_EXPOSURE` | Subject → Exposure | `exposure` | case_id → exposure_id |
| `HAS_FAMILY_HISTORY` | Subject → FamilyHistory | `family_history` | case_id → family_history_id |
| `HAS_SAMPLE` | Subject → Sample | `sample` | case_id → sample_id |

**Backbone shape.** GDC has no FK from Sample to Diagnosis; both are children of the case.
So Diagnosis and Sample are **parallel branches off Subject**, not a chain. (A tumour↔sample
link can be inferred later from `sample_type` if a use case needs it.)

**Molecular-test routing.** `molecular_test.parent_entity ∈ {diagnosis, follow_up}` selects
whether the edge originates from a Diagnosis or a FollowUp; `parent_id` is the source node id.

---

## Omics layer (stub — not yet built)

No omics extractor exists yet, so no omics nodes/edges are emitted in this pass. The agreed
pattern, to implement when omics parsing lands:

- **Shared feature nodes**, reused across all samples: `Gene` (Ensembl id), `CpGSite` (cg#),
  `Variant` (HGVS/dbSNP), `Protein` (UniProt), `Pathway`.
- **Measurements on valued edges** from Sample — never one node per gene×sample:
  - `Sample ─EXPRESSES {tpm, fpkm}→ Gene`
  - `Sample ─METHYLATED_AT {beta_value}→ CpGSite`
  - `Sample ─HAS_VARIANT {vaf, consequence, impact}→ Gene` (or Variant)
  - `Sample ─HAS_PROTEIN_EXPRESSION {value}→ Protein` (RPPA)
  - each edge carries `aliquot_id` / `file_id` for provenance to the assay.
- **Static biology** (Omnipath): `Gene ─IN_PATHWAY→ Pathway`, `Gene ─ENCODES→ Protein`.
  `CpGSite` nodes carry chromosome-specific position properties.

**Sample = aliquot.** The Sample node is the **aliquot** (the analysed unit omics files map
to), produced by a post-processing merge in the extractor (`src/extract/biospecimen.py`):
sample-level descriptors are grafted onto every aliquot row, `aliquot_id` becomes the Sample
`sample_id`, and the originating GDC sample is retained as `gdc_sample_id`. `portion_id` /
`analyte_*` ride along as provenance. See `docs/other/gdc_extraction_notes.md`.

**Dependency — biospecimen QC.** QC (percent tumour cells, RIN, 260/280) wanted on the omics
edges / Sample is **not yet extracted** — the merged `sample.tsv` carries descriptors + ids but
no slide/analyte QC. Surfacing it needs the extractor emitters extended first (add slide and
analyte QC), tracked separately from this model.

---

## BioCypher encoding

`config/schema_config.yaml` declares every node/edge above with a custom `input_label`,
`represented_as: node|relationship`, and a `properties` block. `src/load/adapters.py` reads
the standardised CSVs and yields BioCypher node/edge tuples; `src/load/run.py` runs BioCypher
to write the Neo4j import files. See [`../user_guides/standardisation.md`](../user_guides/standardisation.md)
for the run flow.
