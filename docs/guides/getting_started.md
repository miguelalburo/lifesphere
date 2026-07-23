# Getting started

## What is LifeSphere

LifeSphere is an ETL (Extract, Transform, Load) pipeline that pulls cancer study data from the GDC (Genomic Data Commons) — a public database of cancer genomics data — and organises it into a knowledge graph stored in Neo4j (a graph database). The result is a connected graph of patients, samples, diagnoses, treatments, and molecular measurements that researchers can query to explore relationships across the data.

The pipeline has three stages:

1. **Extract** — fetch raw data from the GDC and write it to TSV files on disk
2. **Standardise** — bind those raw columns to a defined schema and produce graph-ready CSV files
3. **Load** — import those CSVs into a Neo4j database

## Prerequisites

Before you begin, make sure you have the following:

| Prerequisite | Why you need it |
|---|---|
| **Python 3.12** | The pipeline is written in Python; version 3.12 is required |
| **Neo4j 5+** | The graph database that stores the final knowledge graph |
| **Internet access** | The extract stage downloads data from the GDC public API |
| **A terminal** | All pipeline stages are run from the command line |

## Step 1 — Check your Python version

Open a terminal and run:

```bash
python3 --version
```

You should see `Python 3.12.x`. If Python 3.12 is not installed, download it from [python.org/downloads](https://www.python.org/downloads/) and follow the instructions for your operating system.

## Step 2 — Get the code

Clone the repository using git:

```bash
git clone https://github.com/miguelalburo/lifesphere.git
cd lifesphere
```

If you do not have git installed, you can download a ZIP from the repository page and unzip it instead. Then open a terminal in the resulting folder.

## Step 3 — Create the virtual environment

A virtual environment is an isolated Python installation for this project. It keeps LifeSphere's dependencies separate from any other Python projects on your machine.

```bash
python3 -m venv .venv
source .venv/bin/activate   # Mac/Linux
```

Your terminal prompt will change to show `(.venv)` when the environment is active. You will need to run `source .venv/bin/activate` each time you open a new terminal session before running any pipeline commands.

## Step 4 — Install dependencies

With the virtual environment active, install the required packages:

```bash
pip install -r requirements.txt
```

## Step 5 — Configure .env

The pipeline reads connection credentials from a file called `.env` in the project root. Copy the provided template:

```bash
cp .env.example .env
```

Open `.env` in a text editor and fill in the values:

| Variable | Required | Description |
|---|---|---|
| `NEO4J_URI` | Yes | Connection URI for your Neo4j database, e.g. `bolt://localhost:7687` |
| `NEO4J_USER` | Yes | Neo4j username (default: `neo4j`) |
| `NEO4J_PASSWORD` | Yes | Neo4j password you set when creating the database |
| `NEO4J_DATABASE` | No | Named database to use (defaults to `neo4j` if omitted) |
| `RAW_DIR` | No | Custom path for raw TSVs (defaults to `data/raw/` inside the repo) |
| `STD_DIR` | No | Custom path for standardised CSVs (defaults to `data/standardised/`) |
| `LOG_DIR` | No | Custom path for log files (defaults to `logs/`) |

The three optional `*_DIR` variables are useful if you want to store large data files outside the repository directory. If you leave them unset, the pipeline creates `data/raw/`, `data/standardised/`, and `logs/` inside the project folder automatically.

Do not commit `.env` to git — it contains credentials and is listed in `.gitignore`.

## Data directories

After running the pipeline you will see these directories under the project root (or at the custom paths you set in `.env`):

| Directory | Contents |
|---|---|
| `data/raw/` | Source TSVs downloaded from the GDC — one file per entity type |
| `data/interim/` | Reshape outputs for omics layers — created automatically, only populated for omics runs |
| `data/standardised/` | Graph-ready CSVs — `nodes/*.csv` and `edges/*.csv` ready for Neo4j |

You do not need to create these directories manually; the pipeline creates them on first run.

## Quick start

The following four commands run the full pipeline for `TCGA-CHOL` (cholangiocarcinoma), clinical data only. Run them in order with your virtual environment active:

```bash
# 1. Download clinical data from the GDC
python -m src.extract TCGA-CHOL --clinical

# 2. Bind raw columns to the schema and produce CSVs
python -m src.standardise TCGA-CHOL

# 3. Check referential integrity offline (no Neo4j needed)
python -m src.validate TCGA-CHOL

# 4. Import the CSVs into Neo4j
python -m src.load TCGA-CHOL
```

`TCGA-CHOL` is a small TCGA project (~45 cases) and is a good choice for a first run. The extract and standardise steps take under a minute; load time depends on your Neo4j setup.

## Where to go next

- [extraction.md](extraction.md) — full documentation for the extract stage, including all layer flags and the SLURM fan-out for large runs
- [standardisation.md](standardisation.md) — how the column-binding engine works, how to diagnose coverage gaps, and the three-directory data flow
- [loading.md](loading.md) — both loading strategies (MERGE and bulk import), the `--dry-run` flag, and idempotency guarantees
- [docs/schema.md](../schema.md) — the authoritative data model: node labels, relationship types, and property definitions
