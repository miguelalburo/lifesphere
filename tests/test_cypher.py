"""Pure-string tests for the Cypher builders (no database)."""

from __future__ import annotations

from src.load import cypher
from src.schema import Node


def test_constraint_statement():
    node = Node(label="Sample", id="sampleId")
    stmt = cypher.constraint_statement(node)
    assert "CREATE CONSTRAINT sample_sampleid_unique IF NOT EXISTS" in stmt
    assert "FOR (n:`Sample`) REQUIRE n.`sampleId` IS UNIQUE" in stmt


def test_node_merge_query_plain():
    q = cypher.node_merge_query("Subject", "subjectId")
    assert q == (
        "UNWIND $rows AS r MERGE (n:`Subject` {`subjectId`: r.id}) SET n += r.props"
    )


def test_node_merge_query_with_subtype_labels():
    q = cypher.node_merge_query("Intervention", "interventionId", ("Drug", "Immunotherapy"))
    assert "MERGE (n:`Intervention`:`Drug`:`Immunotherapy` {`interventionId`: r.id})" in q


def test_edge_merge_query():
    q = cypher.edge_merge_query("PROVIDED_SAMPLE", "Subject", "subjectId", "Sample", "sampleId")
    assert "MATCH (a:`Subject` {`subjectId`: r.startId})" in q
    assert "MATCH (b:`Sample` {`sampleId`: r.endId})" in q
    assert "MERGE (a)-[e:`PROVIDED_SAMPLE`]->(b) SET e += r.props" in q
