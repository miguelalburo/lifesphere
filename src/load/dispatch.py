"""Unified Stage-3 load entry point — dispatch to the merge or bulk loader.

One CLI over LifeSphere's two deliberately-separate load paths:

* ``--mode merge`` (default) — online Bolt/``MERGE`` via :mod:`src.load.neo4j_loader`.
  Idempotent and incremental: safe to re-run against a live database. A JSON
  ledger file (see :mod:`src.load.ledger`) skips a dataset whose CSVs are
  unchanged since the last load, so re-runs do no wasted work. ``--force`` reloads
  anyway; ``--fresh`` wipes the DB first.
* ``--mode bulk`` — offline BioCypher via :mod:`src.load.run`. Generates a
  ``neo4j-admin import`` call + CSVs under ``biocypher-out/`` for a *fresh* bulk
  load (high-volume omics). It does **not** stream to a live DB: the generated
  script must be run on the Neo4j server against a stopped database.

Connection defaults come from ``.env`` / ``NEO4J_*`` env vars; any ``--uri`` /
``--user`` / ``--password`` / ``--database`` flag overrides them.
"""

import argparse
import logging
import os
from pathlib import Path

from . import ledger
from . import neo4j_loader
from .neo4j_loader import BATCH_SIZE, _DEFAULT_SCHEMA_DIR

log = logging.getLogger(__name__)

_DEFAULT_BIOCYPHER_SCHEMA = Path("config/schema_config.yaml")


def _merge(args) -> int:
    from .validate import format_report, validate

    input_dir: Path = args.input_dir
    dataset: str = args.dataset or input_dir.name
    use_ledger = not args.no_ledger
    ledger_file: Path = args.ledger_file

    sha = ledger.content_hash(input_dir)
    node_count, edge_count = ledger.csv_counts(input_dir)
    log.info("Dataset '%s': %d node rows, %d edge rows (hash %s)",
             dataset, node_count, edge_count, sha[:12])

    if args.fresh:
        if not _confirm_fresh(args):
            log.info("Aborted.")
            return 1
        log.info("--fresh: clearing database before load...")
        neo4j_loader.clear(args.uri, args.user, args.password, args.database,
                           args.batch_size, args.schemas)
    elif use_ledger:
        prior = ledger.get(ledger_file, args.uri, args.database, dataset)
        if prior and prior.get("sha256") == sha and not args.force:
            log.info("'%s' already loaded (unchanged, loaded at %s) — skipping. "
                     "Use --force to reload.", dataset, prior.get("loaded_at"))
            return 0

    if args.validate:
        reports = validate(input_dir, args.schemas)
        log.info("Referential-integrity check:\n%s", format_report(reports))
        if args.strict and any(not r.ok for r in reports):
            log.error("Dangling endpoints found — aborting load (--strict).")
            return 1

    neo4j_loader.run(input_dir, args.uri, args.user, args.password,
                     args.database, args.batch_size, args.schemas)

    if use_ledger:
        ledger.record(ledger_file, args.uri, args.database, dataset,
                      sha, node_count, edge_count)
        log.info("Ledger updated for '%s' in %s.", dataset, ledger_file)
    return 0


def _bulk(args) -> int:
    from . import run as biocypher_run

    log.info("Bulk mode: generating BioCypher offline import artifacts...")
    biocypher_run.run(args.input_dir, args.schema)
    log.info(
        "Import artifacts written (see biocypher-out/). Run the generated "
        "neo4j-admin import script on the Neo4j server against a stopped database; "
        "bulk mode does not load a live DB over Bolt."
    )
    return 0


def _confirm_fresh(args) -> bool:
    if args.yes:
        return True
    reply = input(
        f"--fresh will DELETE ALL data in database '{args.database}' at {args.uri}. "
        f"Type 'yes' to continue: "
    )
    return reply.strip().lower() == "yes"


def _add_conn_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--uri",      default=os.getenv("NEO4J_URI",      "bolt://localhost:7687"))
    p.add_argument("--user",     default=os.getenv("NEO4J_USER",     "neo4j"))
    p.add_argument("--password", default=os.getenv("NEO4J_PASSWORD", "password"))
    p.add_argument("--database", default=os.getenv("NEO4J_DATABASE", "neo4j"))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet the driver's per-notification logging: benign server notices
    # (property-key-not-yet-present on the first ledger read, "constraint already
    # exists", cartesian-product on the loader's disconnected MATCH patterns) would
    # otherwise bury our own progress logs on every run.
    logging.getLogger("neo4j").setLevel(logging.ERROR)

    # Load .env before reading env-var defaults so credentials there take effect.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ModuleNotFoundError:
        log.warning("python-dotenv not installed — reading credentials from the shell "
                    "environment only. `pip install python-dotenv` to auto-load .env.")

    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input_dir", type=Path, help="Standardised dir with nodes/ and edges/")
    p.add_argument("--mode", choices=("merge", "bulk"), default="merge",
                   help="merge = idempotent online Bolt load (default); "
                        "bulk = offline BioCypher neo4j-admin import artifacts")
    _add_conn_args(p)
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                   help="merge mode: rows per Cypher transaction (default: 500)")
    p.add_argument("--schemas", type=Path, default=_DEFAULT_SCHEMA_DIR,
                   help="merge mode: dir with entities.json and edges.json")
    p.add_argument("--schema", type=Path, default=_DEFAULT_BIOCYPHER_SCHEMA,
                   help="bulk mode: BioCypher schema config (schema_config.yaml)")
    p.add_argument("--dataset", default=None,
                   help="ledger key for this dataset (default: input_dir name)")
    p.add_argument("--ledger-file", type=Path, default=ledger.DEFAULT_LEDGER_FILE,
                   help="merge mode: JSON file tracking loaded datasets "
                        f"(default: {ledger.DEFAULT_LEDGER_FILE})")
    p.add_argument("--validate", action="store_true",
                   help="merge mode: referential-integrity check before loading")
    p.add_argument("--strict", action="store_true",
                   help="with --validate, abort if any edge has a dangling endpoint")
    p.add_argument("--fresh", action="store_true",
                   help="merge mode: wipe the database before loading (asks to confirm)")
    p.add_argument("--force", action="store_true",
                   help="merge mode: reload even if the ledger hash is unchanged")
    p.add_argument("--yes", action="store_true",
                   help="skip the --fresh confirmation prompt")
    p.add_argument("--no-ledger", action="store_true",
                   help="merge mode: disable the JSON load ledger (no skip, no record)")

    args = p.parse_args(argv)

    if args.mode == "bulk":
        return _bulk(args)
    return _merge(args)


if __name__ == "__main__":
    raise SystemExit(main())
