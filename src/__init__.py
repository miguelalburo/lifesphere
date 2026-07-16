"""LifeSphere KG ETL pipeline (schema-driven standardise -> load).

Two stages, both driven by the v2 schema config under ``config/``:

* ``src.standardise`` — dataset dir -> ``nodes/{Label}.csv`` + ``edges/{TYPE}.csv``
* ``src.load``        — those CSVs -> Neo4j (official driver, batched MERGE)

``src.validate`` checks referential integrity of standardised CSVs offline.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_STANDARDISED = PROJECT_ROOT / "data" / "standardised"

__all__ = ["PROJECT_ROOT", "CONFIG_DIR", "DATA_RAW", "DATA_STANDARDISED"]
