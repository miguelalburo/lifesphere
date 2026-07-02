# Changing the Knowledge Graph Schema

This guide covers how to add, remove, or modify nodes and edges in the LifeSphere KG. It is written for both human developers and coding agents.

---

## Overview: what controls the schema

The schema is defined entirely in config files. No code changes are required for standard schema modifications.

| File | Controls |
|------|----------|
| `config/schemas/entities.json` | Which node types exist, what raw file feeds each, which column is the ID, how columns are renamed/dropped |
| `config/schemas/edges.json` | Which edge types exist, which file and FK columns produce them |
| `config/schemas/placeholders.json` | Raw data values treated as null during cleaning |
| `config/schema_config.yaml` | BioCypher ontology mapping — required for the **load stage** (Stage 2) to ingest nodes/edges into Neo4j |

The standardisation engine (`src/standardise/`) reads the first three files at runtime. The load engine (`src/load/`) reads the last one. **Both must stay in sync with each other.**

---

## How the pipeline auto-detects available data

The standardise module never fails hard on a missing entity — it skips gracefully. Before writing any output, `detect.py` verifies:

1. A file matching `{base}.{entity_name}.*` (`.tsv` or `.csv`) exists in the dataset directory
2. The required ID column (node) or FK columns (edge) are present in that file's header

A schema entry that cannot be satisfied is logged as `! skip` and excluded from the run. This means **schema definitions can safely describe entities that don't exist in every dataset**.

---

## Entity schema fields (`entities.json`)

Each object in `entities.json` defines one node type:

```json
{
  "name": "diagnosis",          // matches the entity name in the filename: {base}.diagnosis.tsv
  "label": "Diagnosis",         // graph node label; also the output CSV filename: nodes/Diagnosis.csv
  "id_col": "diagnosis_id",     // column used as the node's primary ID
  "strip_prefix": "diagnosis_", // stripped from property column names (diagnosis_stage -> stage)
  "drop": ["case_id", "case_submitter_id"], // columns excluded from properties (FK / linkage cols)
  "keep": [],                   // if non-empty, ONLY these columns become properties (whitelist mode)
  "dedup": false                // true = collapse rows with duplicate id_col (e.g. Program, Project)
}
```

`keep` and `drop` are mutually exclusive — use `keep` (whitelist) when the source table is wide and you only want a handful of columns; use `drop` (blacklist) when you want everything except linkage columns.

Multiple schemas can reference the same `"name"` (same source file). For example, the `subject` file feeds three node types: `Program`, `Project`, and `Subject`.

---

## Edge schema fields (`edges.json`)

Each object defines one edge type:

```json
{
  "label": "HAS_DIAGNOSIS",         // edge label; output CSV: edges/HAS_DIAGNOSIS.csv
  "source_entity": "diagnosis",     // entity name of the file to read (same as entities.json "name")
  "source_id": "case_id",           // column holding the parent node's ID
  "target_id": "diagnosis_id",      // column holding the child node's ID
  "dedup": false                    // true = emit each (source_id, target_id) pair at most once
}
```

Both FK columns must exist in the source file's header or the edge is skipped at runtime.

---

## Recipes

### Add a new node type

**1. Ensure the extractor emits a file for the new entity** (e.g. `{base}.biomarker.tsv`).

**2. Add an entry to `config/schemas/entities.json`:**

```json
{
  "name": "biomarker",
  "label": "Biomarker",
  "id_col": "biomarker_id",
  "strip_prefix": "biomarker_",
  "drop": ["case_id", "case_submitter_id"],
  "keep": [],
  "dedup": false
}
```

**3. Add any edges to `config/schemas/edges.json`:**

```json
{
  "label": "HAS_BIOMARKER",
  "source_entity": "biomarker",
  "source_id": "case_id",
  "target_id": "biomarker_id",
  "dedup": false
}
```

**4. Add matching entries to `config/schema_config.yaml`** (required for Stage 2 load):

```yaml
biomarker:
  represented_as: node
  is_a: entity
  preferred_id: biomarker_id
  input_label: Biomarker

subject to biomarker:
  represented_as: edge
  is_a: association
  input_label: HAS_BIOMARKER
  source: subject
  target: biomarker
```

**5. Verify:**

```bash
pytest tests/test_standardise.py -v
python3 -m src.standardise.run data/raw/<dataset> --out data/standardised/<dataset>
# check that nodes/Biomarker.csv and edges/HAS_BIOMARKER.csv appear in the output
```

---

### Remove a node type

**1. Delete its entry from `config/schemas/entities.json`.**

**2. Delete any edges that reference it from `config/schemas/edges.json`.**

**3. Delete the corresponding entries from `config/schema_config.yaml`.**

The standardise engine will no longer emit the node or edge CSVs. Existing output directories are not cleaned automatically — delete stale CSV files manually if a re-run will be loaded into Neo4j.

---

### Rename a node label or edge label

A label change only affects the output CSV filename and the BioCypher input_label mapping.

**In `entities.json` or `edges.json`:** change `"label"`.

**In `schema_config.yaml`:** update `input_label` on the corresponding entry.

The source file name (`"name"` in entities, `"source_entity"` in edges) does **not** change — it still refers to the raw extract file.

---

### Change which columns become properties

**Add a property:** remove the column name from `"drop"` (or add it to `"keep"` if in whitelist mode). The column will automatically appear in the output CSV on the next run.

**Remove a property:** add the column name to `"drop"` (or remove it from `"keep"`).

**Rename a property:** the `"strip_prefix"` field handles prefix stripping automatically (e.g. `"strip_prefix": "diagnosis_"` renames `diagnosis_stage` → `stage`). For non-prefix renames, the source column name must be changed upstream in the extractor — standardise does not support arbitrary column aliasing.

---

### Change the ID column

Update `"id_col"` in `entities.json`. Also update `preferred_id` in `schema_config.yaml` for the corresponding node. Check that any edge schemas referencing this node's ID column (`"source_id"` or `"target_id"`) are updated to match.

---

### Add or remove a placeholder token

Edit `config/schemas/placeholders.json`. Values in this list are scrubbed to empty string during standardisation. No code changes required.

---

## What requires a code change

The JSON config covers all structural schema changes. Code changes are only needed when:

- **A new entity has non-standard extraction logic** (e.g. dual-parent routing like `molecular_test`, post-processing like the sample→aliquot collapse). These are handled in `src/extract/entities/`, not in standardise.
- **A new file format is introduced** that is not `.tsv` or `.csv`. Update `detect.scan_files()` to glob for the new extension and `detect._delimiter()` to return the correct separator.
- **A new cleaning rule** beyond placeholder scrubbing is needed. Add a transform step inside `standardise_node()` in `src/standardise/run.py`.

---

## Config → pipeline flow

```
config/schemas/
  entities.json  ──► src/standardise/detect.match_node_plans()
  edges.json     ──► src/standardise/detect.match_edge_plans()
  placeholders.json ► src/standardise/run.load_placeholders() ► _make_clean()
                                   │
                                   ▼
                     src/standardise/run.standardise_node/edge()
                                   │
                                   ▼
                     data/standardised/<dataset>/
                       nodes/{Label}.csv
                       edges/{LABEL}.csv
                                   │
                                   ▼
config/schema_config.yaml ────► src/load/run.py (BioCypher → Neo4j)
```

The load adapter (`src/load/adapters.py`) discovers output CSVs by scanning `nodes/` and `edges/` directories — it never has hardcoded label names. Adding or removing nodes/edges in the JSON config and re-running standardise is sufficient; the load stage picks up the new files automatically.
