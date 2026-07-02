"""Load standardised CSVs into a running Neo4j instance via the Bolt driver.

Usage:
    python3 -m src.load.neo4j_loader data/standardised/TCGA_COMBINED \\
        [--uri neo4j://localhost:7687] \\
        [--user neo4j] \\
        [--password password] \\
        [--database neo4j] \\
        [--batch-size 500]

Credentials can also be set via NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD /
NEO4J_DATABASE env vars.
"""

import argparse
import csv
import json
import logging
import os
from pathlib import Path
from typing import Iterator

from neo4j import GraphDatabase
from neo4j.exceptions import ClientError

log = logging.getLogger(__name__)

BATCH_SIZE = 500
_DEFAULT_SCHEMA_DIR = Path(__file__).parent.parent.parent / "config" / "schemas"


def load_schema(
    schema_dir: Path,
) -> tuple[list[str], dict[str, tuple[str | None, str | None]]]:
    """Derive node labels and edge endpoint labels from the JSON schema configs.

    Returns:
        node_labels: ordered unique list of node labels (from entities.json).
        edge_schema: maps each edge label → (source_node_label, target_node_label).
            A None label means the endpoint is polymorphic — Cypher will match on id
            alone, without a label constraint (GDC UUIDs are globally unique).
    """
    with open(schema_dir / "entities.json") as f:
        entities: list[dict] = json.load(f)
    with open(schema_dir / "edges.json") as f:
        edges: list[dict] = json.load(f)

    # id_col → node label; used to resolve edge source/target labels.
    id_to_label: dict[str, str] = {e["id_col"]: e["label"] for e in entities}

    node_labels = list(dict.fromkeys(e["label"] for e in entities))
    edge_schema: dict[str, tuple[str | None, str | None]] = {
        e["label"]: (id_to_label.get(e["source_id"]), id_to_label.get(e["target_id"]))
        for e in edges
    }
    return node_labels, edge_schema


def _iter_batches(path: Path, size: int) -> Iterator[list[dict]]:
    with open(path, newline="", encoding="utf-8") as f:
        batch: list[dict] = []
        for row in csv.DictReader(f):
            batch.append(row)
            if len(batch) >= size:
                yield batch
                batch = []
        if batch:
            yield batch


class Neo4jLoader:
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str,
        batch_size: int = BATCH_SIZE,
        schema_dir: Path = _DEFAULT_SCHEMA_DIR,
    ):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database
        self.batch_size = batch_size
        self.node_labels, self.edge_schema = load_schema(schema_dir)

    def close(self) -> None:
        self.driver.close()

    def _session(self):
        return self.driver.session(database=self.database)

    def create_constraints(self) -> None:
        with self._session() as session:
            for label in self.node_labels:
                try:
                    # Neo4j 5+ syntax
                    session.run(
                        f"CREATE CONSTRAINT IF NOT EXISTS "
                        f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
                    )
                except ClientError:
                    # Neo4j 4.x syntax
                    session.run(
                        f"CREATE CONSTRAINT IF NOT EXISTS "
                        f"ON (n:{label}) ASSERT n.id IS UNIQUE"
                    )
                log.info("  constraint: %s.id", label)

    def load_nodes(self, nodes_dir: Path) -> None:
        for path in sorted(nodes_dir.glob("*.csv")):
            label = path.stem
            total = 0
            with self._session() as session:
                for batch in _iter_batches(path, self.batch_size):
                    rows = []
                    for r in batch:
                        node_id = r.pop("id", "")
                        if node_id:
                            rows.append({"id": node_id, "props": r})
                    if rows:
                        session.run(
                            f"UNWIND $rows AS row "
                            f"MERGE (n:{label} {{id: row.id}}) "
                            f"SET n += row.props",
                            rows=rows,
                        )
                        total += len(rows)
            log.info("  %s: %d nodes", label, total)

    def load_edges(self, edges_dir: Path) -> None:
        for path in sorted(edges_dir.glob("*.csv")):
            rel_type = path.stem
            src_label, tgt_label = self.edge_schema.get(rel_type, (None, None))

            src_pat = f"(a:{src_label} {{id: row.src}})" if src_label else "(a {id: row.src})"
            tgt_pat = f"(b:{tgt_label} {{id: row.tgt}})" if tgt_label else "(b {id: row.tgt})"
            cypher = (
                f"UNWIND $rows AS row "
                f"MATCH {src_pat}, {tgt_pat} "
                f"MERGE (a)-[r:{rel_type}]->(b) "
                f"SET r += row.props"
            )

            total = 0
            with self._session() as session:
                for batch in _iter_batches(path, self.batch_size):
                    rows = []
                    for r in batch:
                        src = r.pop("source_id", "")
                        tgt = r.pop("target_id", "")
                        if src and tgt:
                            props = {k: v for k, v in r.items() if v}
                            rows.append({"src": src, "tgt": tgt, "props": props})
                    if rows:
                        session.run(cypher, rows=rows)
                        total += len(rows)
            log.info("  %s: %d edges", rel_type, total)


def clear(uri: str, user: str, password: str, database: str, batch_size: int,
          schema_dir: Path = _DEFAULT_SCHEMA_DIR) -> None:
    """Delete all data then drop all constraints and indexes for a full schema reset."""
    loader = Neo4jLoader(uri, user, password, database, batch_size, schema_dir)
    try:
        with loader._session() as session:
            log.info("Deleting relationships...")
            total = 0
            while True:
                result = session.run(f"MATCH ()-[r]-() WITH r LIMIT {batch_size} DELETE r")
                deleted = result.consume().counters.relationships_deleted
                total += deleted
                if deleted == 0:
                    break
                log.info("  %d relationships deleted so far...", total)
            log.info("  relationships deleted: %d", total)

            log.info("Deleting nodes...")
            total = 0
            while True:
                result = session.run(f"MATCH (n) WITH n LIMIT {batch_size} DELETE n")
                deleted = result.consume().counters.nodes_deleted
                total += deleted
                if deleted == 0:
                    break
                log.info("  %d nodes deleted so far...", total)
            log.info("  nodes deleted: %d", total)

            log.info("Dropping constraints...")
            constraints = session.run("SHOW CONSTRAINTS YIELD name").data()
            for c in constraints:
                session.run(f"DROP CONSTRAINT {c['name']}")
                log.info("  dropped constraint: %s", c['name'])
            log.info("  constraints dropped: %d", len(constraints))

            log.info("Dropping indexes...")
            indexes = session.run(
                "SHOW INDEXES YIELD name, type WHERE type <> 'LOOKUP'"
            ).data()
            for idx in indexes:
                session.run(f"DROP INDEX {idx['name']}")
                log.info("  dropped index: %s", idx['name'])
            log.info("  indexes dropped: %d", len(indexes))
    finally:
        loader.close()


def run(
    input_dir: Path,
    uri: str,
    user: str,
    password: str,
    database: str,
    batch_size: int,
    schema_dir: Path = _DEFAULT_SCHEMA_DIR,
) -> None:
    loader = Neo4jLoader(uri, user, password, database, batch_size, schema_dir)
    try:
        log.info("Creating uniqueness constraints...")
        loader.create_constraints()

        log.info("Loading nodes...")
        loader.load_nodes(input_dir / "nodes")

        log.info("Loading edges...")
        loader.load_edges(input_dir / "edges")

        log.info("Load complete.")
    finally:
        loader.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    p = argparse.ArgumentParser(
        description="Load standardised KG CSVs into a live Neo4j instance."
    )
    sub = p.add_subparsers(dest="command")

    # --- clear subcommand ---
    pc = sub.add_parser("clear", help="Delete all nodes and relationships from the database.")
    pc.add_argument("--uri",        default=os.getenv("NEO4J_URI",      "bolt://localhost:7687"))
    pc.add_argument("--user",       default=os.getenv("NEO4J_USER",     "neo4j"))
    pc.add_argument("--password",   default=os.getenv("NEO4J_PASSWORD", "password"))
    pc.add_argument("--database",   default=os.getenv("NEO4J_DATABASE", "neo4j"))
    pc.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    pc.add_argument("--schemas",    type=Path, default=_DEFAULT_SCHEMA_DIR,
                    help="Directory containing entities.json and edges.json")

    # --- load subcommand (default behaviour) ---
    pl = sub.add_parser("load", help="Load standardised CSVs into Neo4j.")
    pl.add_argument("input_dir", type=Path, help="Dir with nodes/ and edges/ subdirs")
    pl.add_argument("--uri",        default=os.getenv("NEO4J_URI",      "bolt://localhost:7687"))
    pl.add_argument("--user",       default=os.getenv("NEO4J_USER",     "neo4j"))
    pl.add_argument("--password",   default=os.getenv("NEO4J_PASSWORD", "password"))
    pl.add_argument("--database",   default=os.getenv("NEO4J_DATABASE", "neo4j"))
    pl.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                    help="Rows per Cypher transaction (default: 500)")
    pl.add_argument("--schemas",    type=Path, default=_DEFAULT_SCHEMA_DIR,
                    help="Directory containing entities.json and edges.json")

    args = p.parse_args(argv)

    if args.command == "clear":
        clear(args.uri, args.user, args.password, args.database, args.batch_size, args.schemas)
    elif args.command == "load":
        run(args.input_dir, args.uri, args.user, args.password, args.database, args.batch_size,
            args.schemas)
    else:
        p.print_help()
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
