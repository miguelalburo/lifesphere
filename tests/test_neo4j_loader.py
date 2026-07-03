"""Unit test for Stage 3 Neo4j Bolt loading (src/load/neo4j_loader).

No live database: the Bolt session is faked so we can assert the rows the loader
would send. Focus: empty attributes are dropped per node, so a node carries only
the properties it actually has even when siblings of the same label define more.
"""

import csv
from contextlib import contextmanager
from pathlib import Path

from src.load.neo4j_loader import Neo4jLoader


class _FakeSession:
    def __init__(self, sink: list):
        self.sink = sink

    def run(self, cypher, **params):
        self.sink.append((cypher, params))


def _loader(monkeypatch, sink):
    """Neo4jLoader whose driver/session are stubbed out (no connection made)."""
    monkeypatch.setattr(
        "src.load.neo4j_loader.GraphDatabase.driver",
        lambda *a, **k: object(),
    )
    loader = Neo4jLoader("bolt://x", "u", "p", "neo4j")

    @contextmanager
    def fake_session():
        yield _FakeSession(sink)

    monkeypatch.setattr(loader, "_session", fake_session)
    return loader


class _Counters:
    relationships_created = 0


class _Summary:
    counters = _Counters()


class _EdgeResult:
    def consume(self):
        return _Summary()


class _EdgeSession:
    """Like _FakeSession but returns a result with .consume() for edge loading."""

    def __init__(self, sink: list):
        self.sink = sink

    def run(self, cypher, **params):
        self.sink.append((cypher, params))
        return _EdgeResult()


def test_polymorphic_endpoint_matches_all_labels_via_index(tmp_path, monkeypatch):
    """A None (polymorphic) endpoint expands to a label disjunction so the per-label
    id index is used, instead of a label-less match that forces an AllNodesScan."""
    edges = tmp_path / "edges"
    edges.mkdir()
    with open(edges / "HAS_MOLECULAR_TEST.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_id", "target_id"])
        w.writerow(["s1", "t1"])

    sink: list = []
    loader = _loader(monkeypatch, sink)
    loader.node_labels = ["Diagnosis", "FollowUp", "MolecularTest"]
    loader.edge_schema = {"HAS_MOLECULAR_TEST": (None, "MolecularTest")}

    @contextmanager
    def edge_session():
        yield _EdgeSession(sink)

    monkeypatch.setattr(loader, "_session", edge_session)
    loader.load_edges(edges)

    cypher, _ = sink[-1]
    # Polymorphic source → disjunction over all node labels; no bare label-less match.
    assert "(a:Diagnosis|FollowUp|MolecularTest {id: row.src})" in cypher
    assert "(a {id:" not in cypher
    # Resolved target keeps its single label.
    assert "(b:MolecularTest {id: row.tgt})" in cypher


def test_empty_attributes_dropped_per_node(tmp_path, monkeypatch):
    nodes = tmp_path / "nodes"
    nodes.mkdir()
    # Two Subjects sharing a label: c1 has vital_status but blank race;
    # c2 has race but blank vital_status.
    with open(nodes / "Subject.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "vital_status", "race"])
        w.writerow(["c1", "Alive", ""])
        w.writerow(["c2", "", "white"])

    sink: list = []
    loader = _loader(monkeypatch, sink)
    loader.load_nodes(nodes)

    # One UNWIND call; inspect the per-row props.
    _, params = sink[-1]
    props = {row["id"]: row["props"] for row in params["rows"]}
    assert props["c1"] == {"vital_status": "Alive"}   # blank race omitted
    assert props["c2"] == {"race": "white"}           # blank vital_status omitted
