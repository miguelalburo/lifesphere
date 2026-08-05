# LifeSphere

An ETL pipeline that harmonises biomedical cancer-study data (clinical + biospecimen + omics) from the GDC into a Neo4j knowledge graph.


## Main Components

1. **Extraction** (`src/extract/`) — fetch from the GDC and write one TSV per entity to `data/raw/<dataset>/`.

2. **Standardisation** (`src/standardise/`) — bind raw TSV columns to the graph schema and emit graph-ready `nodes/*.csv` and `edges/*.csv` to `data/standardised/<dataset>/`.

3. **Graph Load** (`src/load/`) — read those CSVs and MERGE nodes and edges into a Neo4j database.


## Setup & Requirements

**Requirements:** Python 3.12, Neo4j 5+

1. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate        # Mac/Linux
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in your Neo4j credentials.


## How-to-Run

For more specific details, see the guide documents at `docs/guides/`.

Ensure the virtual environment is active (`source .venv/bin/activate`), then run the pipeline stages in order:

```bash
python3 -m src.extract TCGA-CHOL --clinical   # Stage 1: fetch from GDC → data/raw/
python3 -m src.standardise TCGA-CHOL          # Stage 2: bind columns → data/standardised/
python3 -m src.validate TCGA-CHOL             # optional: offline integrity check
python3 -m src.load TCGA-CHOL                 # Stage 3: import into Neo4j
```

On the HPC cluster, submit the extraction jobs via SLURM instead:
```bash
scripts/submit_extract_TCGA.sh      # sbatches the per-layer extraction jobs
scripts/submit_standardise_TCGA.sh  # sbatches the standardise jobs
scripts/submit_load_TCGA.sh         # sbatches the driver load (MERGE over bolt)
scripts/submit_import_TCGA.sh       # offline path: neo4j-admin import → dump → load
```

The standardised CSVs live on the cluster filesystem and are not mounted on the
Neo4j host, so the load runs as a SLURM job and pushes over bolt:
```bash
scripts/submit_load_TCGA.sh --database lifesphere_test TCGA_EXPRESSION
```
Use the driver load for test databases and top-ups into an existing graph; use
the offline `submit_import_TCGA.sh` path for a full-scale rebuild.

## Directory Map

```
lifesphere/
├── data/
│   ├── raw/            # source TSVs from GDC (extraction output)
│   ├── interim/        # reshape pre-pass outputs (omics only, created automatically)
│   └── standardised/   # graph-ready CSVs ready for Neo4j load
│
├── src/
│   ├── extract/        # GDC fetch → per-entity TSVs (clinical emitters + omics)
│   ├── standardise/    # column + value mapping → nodes/*.csv + edges/*.csv
│   ├── reshape/        # omics matrix reshape (called by standardise omics profile)
│   ├── load/           # Neo4j graph import (MERGE strategy + bulk-import adapter)
│   ├── schema.py       # graph definition; load_schema() used by both stages
│   ├── validate.py     # offline referential-integrity check
│   └── visualise.py    # interactive HTML of the live schema
│
├── config/             # YAML field mappings, schema definitions
│
├── tests/              # unit + integration tests mirroring src/ structure
│
├── scripts/                        # operational entrypoints that orchestrate src/
│   ├── submit_extract_TCGA.sh      # sbatches the per-layer extraction jobs
│   ├── submit_standardise_TCGA.sh  # sbatches the standardise jobs
│   └── extract_TCGA/               # HPC (SLURM) job scripts
│
├── logs/               # run logs (gitignored)
├── .venv/              # Python virtual environment (gitignored)
├── docs/
│   ├── schema.md       # authoritative data model
│   └── guides/         # stage-by-stage guide documents
├── requirements.txt    # Python dependencies
├── .env.example        # template for credentials (copy to .env)
├── .gitignore
└── README.md
```
