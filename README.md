# LifeSphere

An ETL pipeline that harmonises biomedical (clinical) patient data from cancer studies into a knoweldge graph.


## Main Components

1. **Standardisation** which maps columns and their values to a strict schema. 

2. **Graph Import** which takes the standardised outputs and loads them onto a Neo4J knowledge graph.


## Setup & Requirements

...

## How-to-Run

...

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
├── scripts/
│   └── slurm/          # HPC job submission scripts
│
├── logs/               # run logs (gitignored)
├── docs/
├── .gitignore
└── README.md
```