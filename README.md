# LifeSphere

An ETL pipeline that harmonises biomedical (clinical) patient data from cancer studies into a knoweldge graph.


## Main Components

1. **Standardisation** which maps columns and their values to a strict schema. 

2. **Graph Import** which takes the standardised outputs and loads them onto a Neo4J knowledge graph.


## Setup & Requirements

**Requirements:** Python 3.10+, Neo4j 5+

1. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate        # Mac/Linux
   .venv\Scripts\activate           # Windows
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Fill your credentials in `.env.example` and rename to `.env`


## How-to-Run

For more specific details, see the guide documents at `docs/guides/`.

Ensure the virtual environment is active (`source .venv/bin/activate`), then run the relevant pipeline stage:

```bash
python3 -m src.standardise.run    # Stage 1: standardise raw data
python3 -m src.load.run           # Stage 2: import into Neo4j
```

On the HPC cluster, submit the extraction jobs via SLURM instead:
```bash
scripts/submit_extract_TCGA.sh   # sbatches the per-layer jobs in scripts/extract_TCGA/
scripts/submit_resume_TCGA.sh    # resumes omics reshape offline (expression + methylation)
```

## Directory Map

```
lifesphere/
├── data/
│   ├── raw/            # original source files (read-only)
│   ├── interim/        # intermediate outputs between pipeline stages
│   └── standardised/   # final standardised CSVs ready for graph load
│
├── src/
│   ├── extract/        # parsers / data ingestion per study format
│   ├── standardise/    # column + value mapping logic (Stage 1)
│   ├── load/           # Neo4j graph import (Stage 2)
│   └── utils/          # shared helpers (logging, I/O, graph client)
│
├── config/             # YAML/JSON field mappings, schema definitions, study configs
│
├── tests/              # unit + integration tests mirroring src/ structure
│
├── scripts/                    # operational entrypoints that orchestrate src/
│   ├── submit_extract_TCGA.sh  # sbatches the per-layer extraction jobs
│   ├── submit_resume_TCGA.sh   # sbatches the omics reshape resume jobs
│   └── extract_TCGA/           # HPC (SLURM) job scripts + resume_omics_reshape.py
│
├── logs/               # run logs (gitignored)
├── .venv/              # Python virtual environment (gitignored)
├── docs/
├── requirements.txt    # Python dependencies
├── .env.example        # template for credentials (copy to .env)
├── .gitignore
└── README.md
```