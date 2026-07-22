# Standardisation

## What this stage does

The standardisation stage reads the raw TSVs in `data/raw/<dataset>/`, binds each source column to a property in the graph schema, and emits graph-ready CSV files into `data/standardised/<dataset>/nodes/` and `data/standardised/<dataset>/edges/`. It is a pure column-mapping and value-cleaning pass — no Neo4j connection is needed.

## CLI synopsis

```bash
python -m src.standardise <dataset> [--profile extract|omics] [--report] [--values] [--quiet]
```

`<dataset>` is the folder name under `data/raw/` (e.g. `TCGA-CHOL`).

## Flags

| Flag | Effect |
|---|---|
| `--profile extract` | Use the clinical mapping profile (`config/mapping/extract.yaml`) — default |
| `--profile omics` | Use the omics mapping profile (`config/mapping/omics.yaml`) |
| `--report` | Print column-binding coverage to stdout without writing any output files |
| `--values` | Like `--report` but also prints per-column value samples |
| `--quiet` | Suppress per-file progress logging |

## Choosing a profile

A **profile** is a mapping config that tells the engine which raw source column feeds which schema property. Choose based on which extraction layer produced your `data/raw/<dataset>/` files:

- `--profile extract` (default) — for datasets produced by `python -m src.extract ... --clinical`
- `--profile omics` — for datasets produced by `python -m src.extract ... --expression`, `--methylation`, or `--variation`

If you ran both `--clinical` and `--omics` in the same extraction, run standardise twice — once per profile — targeting the same `<dataset>`.

## Diagnosing coverage gaps with --report

Before committing to a full run, use `--report` to audit column binding without writing any files:

```bash
python -m src.standardise TCGA-CHOL --report
```

This prints a table showing which raw column feeds which schema property and by which resolution rule (explicit config, shared alias, camelCase match, etc.). When `LOG_DIR` is set in `.env`, the report is also written to `logs/standardisation/<dataset>.txt`.

`--values` adds a sample of distinct values seen in each column — useful for understanding the raw data before writing alias rules.

## Three-directory data flow

```
data/raw/<dataset>/          ← source TSVs from GDC (extraction output)
       ↓
data/interim/<dataset>/      ← reshape pre-pass output (omics only, created automatically)
       ↓
data/standardised/<dataset>/ ← graph-ready CSVs (standardisation output)
```

`data/interim/` is created automatically and is only populated when running the `omics` profile. It holds reshaped observation files before they are standardised. You do not need to create or manage it manually.

## Understanding `! skip` log lines

The standardise engine never fails hard on missing data. A `! skip` log line means one of:

- A source file listed in the profile was not found in `data/raw/<dataset>/` — expected when a dataset does not include that entity type.
- A mapping entry has no `key` column configured — the entry is intentionally unpopulated for this source.
- An id or foreign-key column was absent or blank for a row — that row is dropped.

A `! skip` is a **bug** only when the column should be present but is not. If you expect a node type to appear in the output but it is being skipped, check the profile entry and confirm the source TSV contains the expected column name.

## Output

After a successful run:

```
data/standardised/<dataset>/
├── nodes/
│   ├── Subject.csv
│   ├── Sample.csv
│   ├── Diagnosis.csv
│   └── ...
└── edges/
    ├── SUBJECT_HAS_SAMPLE.csv
    ├── SUBJECT_HAS_DIAGNOSIS.csv
    └── ...
```

Each CSV has a header row matching the property names declared in the schema (camelCase). Node CSVs have an `id` column; edge CSVs have `startId` and `endId` columns.

## Example commands

```bash
# Standardise a clinical dataset (default profile)
python -m src.standardise TCGA-CHOL

# Standardise an omics dataset
python -m src.standardise TCGA-CHOL --profile omics

# Audit coverage without writing output
python -m src.standardise TCGA-CHOL --report
python -m src.standardise TCGA-CHOL --values
```

---

**Next step:** before loading, run the offline integrity check:

```bash
python -m src.validate TCGA-CHOL
```

Then proceed to [loading.md](loading.md) to import the CSVs into Neo4j.
