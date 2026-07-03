#!/usr/bin/env python3
"""Load standardised KG CSVs into Neo4j (Stage 3) — unified, idempotent entry point.

Usage:
  python scripts/load_neo4j.py <input_dir> [options]
  python scripts/load_neo4j.py data/standardised/TCGA_COMBINED
  python scripts/load_neo4j.py data/standardised/TCGA_COMBINED --validate --strict
  python scripts/load_neo4j.py data/standardised/TCGA_COMBINED --fresh --yes
  python scripts/load_neo4j.py data/standardised/OMICS --mode bulk

Modes:
  merge (default)  Idempotent online Bolt load. MERGE never duplicates nodes/edges;
                   a JSON ledger file skips a dataset whose CSVs are unchanged
                   (--force to reload, --fresh to wipe first).
  bulk             Offline BioCypher — generates neo4j-admin import artifacts under
                   biocypher-out/ for a fresh bulk load on the Neo4j server.

Credentials load from .env / NEO4J_URI|USER|PASSWORD|DATABASE; --uri/--user/
--password/--database override. See `--help` for all options.
"""

import sys
from pathlib import Path

# Allow running from the project root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.load.dispatch import main

if __name__ == "__main__":
    raise SystemExit(main())
