# GDC Cases Extraction Notes

How `scripts/download_gdc.py` pulls harmonised clinical/biospecimen data
from the GDC `/cases` endpoint, and the shape of what it writes.

API base: `https://api.gdc.cancer.gov/` — see also [`gdc_formats.md`](gdc_formats.md).

---

## Design: one fetch, N emitters

A single `/cases` request per run uses the GDC `expand` parameter to pull every
case with all of its nested sub-objects (demographic, diagnoses, treatments,
follow-ups, molecular tests, samples/portions/analytes/aliquots, files). Each
case is fetched once; the payload is then handed to a set of **per-entity
emitters** in `src/extract/entities/`, one module per entity.

Every emitter declares `NAME`, `COLUMNS`, and `iter_rows(case)`, and writes one
output file `{base}.{NAME}.tsv` at that entity's **true grain**. `{base}` is the
project id (`TCGA-BRCA`), the program (`TCGA`), or `cases` for an ad-hoc UUID list.

```
fetch_all(project) -> hits          # 1 paginated query, expand=<all sub-objects>
for emitter in EMITTERS:
    for case in hits:
        for row in emitter.iter_rows(case):
            write(row)               # -> {base}.{emitter.NAME}.tsv
```

Orchestration lives in `src/extract/cases.py` (`_fetch` / `write_entities`); the
emitter registry and `expand` list live in `src/extract/entities/__init__.py`.

---

## Why per-entity, not one flat row per case

The previous extractor flattened each case to a **single row**. Its `_resolve()`
walked each entity's path taking `list[0]` at every array step, so for any
one-to-many entity it kept only the first element and silently discarded the
rest — before the file was ever written.

Measured against the live GDC API, the loss affected essentially every case:

| Entity | Cases with >1 (TCGA-BRCA / OV / GBM) | Max per case |
|---|---|---|
| `follow_up` | 100% / 96% / 96% | 24 |
| `treatment`  | 94% / 93% / 92% | 40 |
| `diagnosis`  | 18% / 62% / 63% | 9 |

Treatments were doubly truncated (`diagnoses[0].treatments[0]`), and all
`diagnosis_*` staging/grade/morphology came from `diagnoses[0]` only. None of it
was recoverable downstream. The per-entity design preserves all of it.

By contrast `samples`/`aliquots`/`files` and `molecular_tests` were already being
collected in full (as `;`-joined lists); those are now first-class tables too.

---

## Output tables

`{base}.subject.tsv` is one row per case. Every other table is a child at its own
grain and carries `case_id` (+ `case_submitter_id`) to join back; deeper tables
also carry their parent id.

| File | Grain | Key columns | Notes |
|---|---|---|---|
| `{base}.subject.tsv` | 1 / case | `case_id` (PK), `submitter_id` | The case table (KG naming). Base fields + 1:1 `demographic_*` |
| `{base}.diagnosis.tsv` | n / case | `case_id`, `diagnosis_id` | `diagnosis_*` (staging, grade, morphology) |
| `{base}.treatment.tsv` | n / diagnosis | `case_id`, `diagnosis_id`, `treatment_id` | Links to its parent diagnosis |
| `{base}.pathology_detail.tsv` | n / diagnosis | `case_id`, `diagnosis_id`, `pathology_detail_id` | |
| `{base}.follow_up.tsv` | n / case | `case_id`, `follow_up_id` | Longitudinal timepoints |
| `{base}.molecular_test.tsv` | n / case | `case_id`, `parent_entity`, `parent_id`, `molecular_test_id` | Nests under diagnosis **or** follow_up; `parent_entity` records which. ER/PR/HER2 lives here |
| `{base}.exposure.tsv` | n / case | `case_id`, `exposure_id` | Smoking/alcohol etc. |
| `{base}.family_history.tsv` | n / case | `case_id`, `family_history_id` | |
| `{base}.other_clinical_attribute.tsv` | n / case | `case_id`, `other_clinical_attribute_id` | Empty for TCGA |
| `{base}.sample.tsv` | n / case (**aliquot grain**) | `case_id`, `sample_id` (= aliquot), `gdc_sample_id` | Post-processed: sample descriptors merged onto each aliquot. `sample_id`←`aliquot_id`; `gdc_sample_id`←the GDC sample; carries `portion_id`, `analyte_*` provenance |
| `{base}.file.tsv` | n / case | `case_id`, `file_id` | Every file × case; largest table |

A post-processing step (`src/extract/biospecimen.py`, run automatically after the
emitters) collapses the biospecimen hierarchy to aliquot grain: it merges the
sample-level descriptors onto every aliquot row, writes the result as
`{base}.sample.tsv`, and removes the now-redundant `{base}.aliquot.tsv`. The
aliquot is the analysed unit that omics files map to, so it becomes the Sample
node downstream; the originating GDC sample is retained as `gdc_sample_id`.

Content-field columns are prefixed with the entity name (e.g.
`treatment_therapeutic_agents`, `diagnosis_ajcc_pathologic_stage`) so joined
tables don't collide. Column sets derive from `src/extract/gdc_data_dict.json`
(clinical entities) or an explicit `FIELDS` list in the emitter (biospecimen +
molecular_test).

---

## Latest full-program extract (`--program TCGA`, 2026-07-01)

11,428 cases → `data/raw/TCGA_COMBINED/TCGA.*.tsv` (gitignored). Row counts:

| Table | Rows | Cols |
|---|---:|---:|
| subject | 11,428 | 27 |
| diagnosis | 18,843 | 129 |
| treatment | 55,832 | 47 |
| pathology_detail | 14,366 | 81 |
| follow_up | 72,453 | 43 |
| molecular_test | 20,754 | 54 |
| exposure | 4,500 | 34 |
| family_history | 3,037 | 12 |
| other_clinical_attribute | 0 | 59 |
| sample | 165,261 | 16 |
| file | 908,005 | 12 |

`sample` is post-processed to aliquot grain (165,261 rows = the 165,261 aliquots,
sample descriptors merged in); the separate `aliquot` table (33,939 GDC samples
fanned out) is consumed and removed. For comparison, the old flattened file held
~11,428 treatment rows (one/case); there are now **55,832**, and **72,453**
follow-ups (~6.3/case) — all previously discarded. Integrity verified: `case_id`
unique in `subject.tsv`; zero orphan `case_id`s in the child tables; every
`treatment.diagnosis_id` resolves to a diagnosis; all 20,754 molecular tests
attributed to their `follow_up` parent.

---

## Caveats & usage

- **`file.tsv` is large** (~253 MB / 908k rows for TCGA): every file × case. Skip
  loading it unless you need the file inventory.
- **`other_clinical_attribute` is empty for TCGA** — the table is still written
  (header only) for schema consistency.
- **BCR BioTab (`bcr_*`) is separate.** `--biotab` downloads legacy BioTab files
  per project (requires `gdc-client`) and merges `clinical_patient` into
  `{base}.subject.tsv` on `case_id`. It is project-scoped, so it is a no-op with
  `--program`; run per project if the `bcr_*` fields are needed.
- **`molecular_test` parent is program-dependent.** In TCGA these nest under
  `follow_ups`; other programs may attach them to `diagnoses`. Filter on
  `parent_entity` if the distinction matters.
