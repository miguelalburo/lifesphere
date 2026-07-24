#!/usr/bin/env python3
"""Assemble a single combined ``neo4j-admin database import full`` for many datasets.

The offline bulk builder (:func:`src.load.bulk.build_import`) rewrites *one*
standardised dataset into admin-import CSVs. For the combined LifeSphere graph we
want *every* dataset (clinical + each omics layer, across every project) to land
in **one** store, so this helper runs the builder per dataset and stitches the
per-file ``--nodes``/``--relationships`` arguments into one arg list.

Key detail — why one arg per file rather than ``--nodes=Label=f1,f2``: each
per-dataset CSV carries its *own* header row, so they cannot share a single
header the way admin-import's comma-joined form assumes. Passing them as separate
``--nodes=Label=<file>`` / ``--relationships=TYPE=<file>`` args instead makes
admin-import merge same-label / same-type groups across files. Because every
node's id-space group is named after its label (see ``bulk.py``), edges resolve
into the right nodes regardless of which dataset file they came from — that is
what lets omics edges point at clinical ``Sample`` nodes in the combined store.

Nothing here talks to Neo4j. It writes two files under ``--out`` and prints their
paths:

* ``import.args``       — the argv *after* ``neo4j-admin database import full``,
                          one token per line (options, then every ``--nodes`` /
                          ``--relationships``, then the database name last), ready
                          for ``mapfile`` in the build job.
* ``constraints.cypher`` — de-duplicated uniqueness constraints to apply on the
                          Enterprise host once the loaded database is online.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# scripts/ orchestrate src/ (never the reverse); make the repo root importable.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.load.bulk import ARRAY_DELIMITER, build_import  # noqa: E402


def _rel_type(path: Path) -> str:
    """``TYPE`` from a split edge file named ``TYPE__startLabel__endLabel.csv``."""
    return path.name.split("__", 1)[0]


def assemble(datasets: list[str], out: Path, database: str,
             id_type: str = "string") -> dict:
    """Build every dataset under ``out/<dataset>`` and merge into one arg list."""
    out.mkdir(parents=True, exist_ok=True)

    node_args: list[str] = []
    rel_args: list[str] = []
    constraints: list[str] = []       # de-duplicated, order-preserving
    seen_constraints: set[str] = set()
    n_node_files = n_edge_files = 0

    for dataset in datasets:
        plan = build_import(dataset, out_dir=out / dataset, database=database,
                            id_type=id_type)
        for path in plan["node_files"]:
            node_args.append(f"--nodes={path.stem}={path}")
            n_node_files += 1
        for path in plan["edge_files"]:
            rel_args.append(f"--relationships={_rel_type(path)}={path}")
            n_edge_files += 1
        for stmt in plan["constraints"]:
            if stmt not in seen_constraints:
                seen_constraints.add(stmt)
                constraints.append(stmt)

    # Options mirror bulk.build_import; --overwrite-destination lets the job
    # re-run against a fresh node-local scratch store without a manual wipe.
    options = [
        "--overwrite-destination=true",
        f"--id-type={id_type}",
        f"--array-delimiter={ARRAY_DELIMITER}",
        "--ignore-empty-strings=true",
    ]
    # database name is positional and goes LAST (matches bulk.build_import).
    argv = [*options, *node_args, *rel_args, database]

    args_file = out / "import.args"
    args_file.write_text("\n".join(argv) + "\n", encoding="utf-8")

    constraints_file = out / "constraints.cypher"
    constraints_file.write_text(
        "".join(f"{stmt};\n" for stmt in constraints), encoding="utf-8")

    return {
        "args_file": args_file,
        "constraints_file": constraints_file,
        "n_datasets": len(datasets),
        "n_node_files": n_node_files,
        "n_edge_files": n_edge_files,
        "n_constraints": len(constraints),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="assemble_import.py",
        description="Assemble one combined neo4j-admin import for many datasets.",
    )
    parser.add_argument("datasets", nargs="+",
                        help="dataset folder names under data/standardised/")
    parser.add_argument("--out", required=True, type=Path,
                        help="output dir for rewritten CSVs + import.args (node-local scratch)")
    parser.add_argument("--database", required=True,
                        help="target combined database name")
    parser.add_argument("--id-type", default="string")
    args = parser.parse_args(argv)

    result = assemble(args.datasets, args.out, args.database, id_type=args.id_type)
    print(
        f"# assembled {result['n_datasets']} datasets -> "
        f"{result['n_node_files']} node + {result['n_edge_files']} relationship files, "
        f"{result['n_constraints']} constraints",
        file=sys.stderr,
    )
    print(result["args_file"])
    print(result["constraints_file"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
