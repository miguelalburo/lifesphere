# Loading

## What this stage does

The loading stage reads the graph-ready CSVs from `data/standardised/<dataset>/nodes/` and `data/standardised/<dataset>/edges/`, creates uniqueness constraints in Neo4j, and MERGEs nodes and edges into the database in batches. It requires a running Neo4j instance and connection credentials in `.env`.

## CLI synopsis

```bash
python -m src.load <dataset> [--dry-run] [--bulk] [--database NAME] [--batch-size N] [--no-constraints]
```

`<dataset>` is the folder name under `data/standardised/` (e.g. `TCGA-CHOL`).

## Flags

| Flag | Effect |
|---|---|
| `--dry-run` | Build and print the full query plan without connecting to a database |
| `--bulk` | Emit `neo4j-admin database import full` compatible CSVs and print the import command |
| `--database NAME` | Target a specific named Neo4j database (overrides `NEO4J_DATABASE` env var, then falls back to `neo4j`) |
| `--batch-size N` | Number of rows per MERGE batch (default: 1000) |
| `--no-constraints` | Skip creating uniqueness constraints before loading |

## Run validate first

Before connecting to Neo4j, check referential integrity offline:

```bash
python -m src.validate TCGA-CHOL [--strict]
```

This verifies that all node IDs are non-blank, there are no duplicate IDs within a label, and all edge endpoints refer to nodes that exist in the standardised output — without requiring a database connection. Fix any reported issues before loading.

For omics datasets whose edges reference clinical node IDs, use `--reference` to resolve them:

```bash
python -m src.validate TCGA-CHOL --profile omics --reference TCGA-CHOL
```

## Verifying a load plan offline with --dry-run

`--dry-run` builds and prints the complete query plan — constraint statements, MERGE queries, and row counts — without opening a database connection:

```bash
python -m src.load TCGA-CHOL --dry-run
```

This is the safe way to inspect what the loader will do before you run it against a live database.

## Two loading strategies

### MERGE (default)

The default strategy uses `MERGE` on the node's primary key. It is safe to run against a database that already contains data:

- **Idempotent**: running the same load twice produces the same graph. Nodes and edges that already exist are matched, not duplicated.
- **Restartable**: if a load is interrupted, you can restart it from the beginning — MERGE skips already-imported rows safely.

```bash
python -m src.load TCGA-CHOL
```

### Bulk import with --bulk

`--bulk` emits `neo4j-admin database import full` compatible header and data CSVs and prints the command to run:

```bash
python -m src.load TCGA-CHOL --bulk
```

This is significantly faster than MERGE for initial loads of large datasets, but it **requires a completely empty database**. Do not use `--bulk` against a database that already has data — the `neo4j-admin` import tool will reject or corrupt it.

Use `--bulk` when:
- You are doing a fresh initial load of a large TCGA dataset
- You have an empty Neo4j database ready to receive the import

Use MERGE (default) when:
- You are adding data to an existing graph
- You need to re-run a load after a partial failure

## Multi-label nodes (subtypeFrom)

Some node types in the schema declare a `subtypeFrom` column. At load time, the value of that column becomes an additional Neo4j label on the node. For example, a `Sample` node with `sampleType = "Primary Tumor"` receives both the `:Sample` label and the subtype label derived from that value. This is handled automatically by the loader.

## Example commands

```bash
# Dry-run to verify the plan without a database
python -m src.load TCGA-CHOL --dry-run

# Load into the default database
python -m src.load TCGA-CHOL

# Load into a named database
python -m src.load TCGA-CHOL --database tcga

# Initial bulk import into an empty database
python -m src.load TCGA-CHOL --bulk
```
