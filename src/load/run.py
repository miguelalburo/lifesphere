"""Stage 2 engine — load standardised CSVs into the graph via BioCypher.

    python3 -m src.load.run <standardised_dir> [--schema config/schema_config.yaml]
    python3 -m src.load.run data/standardised/TCGA-DLBC

By default BioCypher writes Neo4j admin-import CSVs (offline). Point it at a live
Neo4j via a biocypher config / .env if online import is wanted.

BioCypher is imported lazily so this module (and the adapter) import fine without it
installed; only ``run()`` requires the dependency.
"""

import argparse
from pathlib import Path

from .adapters import StandardisedCSVAdapter


def run(input_dir: Path, schema_config: Path) -> None:
    from biocypher import BioCypher  # lazy: keeps import-time dependency optional

    bc = BioCypher(schema_config_path=str(schema_config))
    adapter = StandardisedCSVAdapter(input_dir)

    bc.write_nodes(adapter.get_nodes())
    bc.write_edges(adapter.get_edges())
    bc.write_import_call()   # emits the neo4j-admin import shell script
    bc.summary()             # prints ontology/graph structure + any deviations


def main(argv: list[str] = None) -> int:
    p = argparse.ArgumentParser(description="Load standardised KG CSVs into Neo4j via BioCypher.")
    p.add_argument("input_dir", type=Path, help="Standardised dir with nodes/ and edges/")
    p.add_argument("--schema", type=Path, default=Path("config/schema_config.yaml"),
                   help="BioCypher schema config (default: config/schema_config.yaml)")
    args = p.parse_args(argv)
    run(args.input_dir, args.schema)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
