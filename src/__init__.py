"""LifeSphere KG ETL pipeline (schema-driven standardise -> load).

Two stages, both driven by the v2 schema config under ``config/``:

* ``src.standardise`` — dataset dir -> ``nodes/{Label}.csv`` + ``edges/{TYPE}.csv``
* ``src.load``        — those CSVs -> Neo4j (official driver, batched MERGE)

``src.validate`` checks referential integrity of standardised CSVs offline.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

DATA_RAW = Path(os.environ["RAW_DIR"]) if "RAW_DIR" in os.environ else PROJECT_ROOT / "data" / "raw"
DATA_STANDARDISED = Path(os.environ["STD_DIR"]) if "STD_DIR" in os.environ else PROJECT_ROOT / "data" / "standardised"

LOG_DIR = Path(os.environ["LOG_DIR"]) if "LOG_DIR" in os.environ else PROJECT_ROOT / "logs"

__all__ = ["PROJECT_ROOT", "CONFIG_DIR", "DATA_RAW", "DATA_STANDARDISED", "LOG_DIR"]
