# Standardisation

Stage 1 of the pipeline: turn the extractor's raw per-entity TSVs into graph-ready
node/edge CSVs that the loader (Stage 2, BioCypher) imports into Neo4j.

The target graph schema is defined in
[`../dev_guides/kg_data_model.md`](../dev_guides/kg_data_model.md); the column-level
mapping lives in [`src/standardise/mapping.py`](../../src/standardise/mapping.py).

## What it does

For a dataset extracted as `{base}.{entity}.tsv` (e.g. `TCGA-DLBC.subject.tsv`):

- one node CSV per label — `nodes/Subject.csv`, `nodes/Diagnosis.csv`, … — with an
  `id` column plus cleaned, prefix-stripped properties;
- one edge CSV per relationship — `edges/HAS_DIAGNOSIS.csv`, … — with `source_id`,
  `target_id`.

The extraction grain already equals the graph grain, so no aggregation happens:
standardisation only **selects columns, strips entity prefixes, drops linkage columns,
and scrubs placeholder tokens** (`[Not Available]`, `[Not Evaluated]`, …). Program and
Project are de-duplicated (they repeat on every case row).

## Run

```bash
# Stage 1: standardise
python3 -m src.standardise.run <in_dir> <base> [--out <dir>]
python3 -m src.standardise.run data/raw/dlbc TCGA-DLBC
# -> data/standardised/TCGA-DLBC/{nodes,edges}/*.csv

# Stage 2: load into Neo4j via BioCypher
python3 -m src.load.run data/standardised/TCGA-DLBC
```

## Extending

- **New source column / rename**: edit the relevant `NodeSpec` in `mapping.py`
  (`strip_prefix`, `drop`, `keep`). Nothing else changes — `run.py` is generic.
- **New node/edge type**: add a `NodeSpec`/`EdgeSpec` and a matching entry in
  `config/schema_config.yaml` (`input_label` must equal the CSV label / `.stem`).
- **Omics**: not yet wired — see the stub section in the data-model doc.
