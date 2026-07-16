"""Pure Cypher-statement builders. No driver, no I/O — trivially unit-testable.

Row shapes the queries expect (passed as ``$rows``):
    node:  {"id": <value>, "props": {<prop>: <value>, ...}}
    edge:  {"startId": <value>, "endId": <value>, "props": {...}}
"""

from __future__ import annotations

from ..schema import Node


def _bt(identifier: str) -> str:
    """Backtick-quote a label or property name for safe interpolation."""
    return "`" + identifier.replace("`", "``") + "`"


def constraint_name(label: str, id_prop: str) -> str:
    return f"{label.lower()}_{id_prop.lower()}_unique"


def constraint_statement(node: Node) -> str:
    """Uniqueness constraint for a node's primary key (§9.1)."""
    return (
        f"CREATE CONSTRAINT {constraint_name(node.label, node.id)} IF NOT EXISTS "
        f"FOR (n:{_bt(node.label)}) REQUIRE n.{_bt(node.id)} IS UNIQUE"
    )


def node_merge_query(label: str, id_prop: str,
                     extra_labels: tuple[str, ...] = ()) -> str:
    """Batched MERGE for one node label (plus optional multi-labels)."""
    labels = ":".join(_bt(lbl) for lbl in (label, *extra_labels))
    return (
        "UNWIND $rows AS r "
        f"MERGE (n:{labels} {{{_bt(id_prop)}: r.id}}) "
        "SET n += r.props"
    )


def edge_merge_query(edge_type: str, start_label: str, start_id_prop: str,
                     end_label: str, end_id_prop: str) -> str:
    """Batched MATCH-endpoints + MERGE for one relationship type/pair."""
    return (
        "UNWIND $rows AS r "
        f"MATCH (a:{_bt(start_label)} {{{_bt(start_id_prop)}: r.startId}}) "
        f"MATCH (b:{_bt(end_label)} {{{_bt(end_id_prop)}: r.endId}}) "
        f"MERGE (a)-[e:{_bt(edge_type)}]->(b) "
        "SET e += r.props"
    )
