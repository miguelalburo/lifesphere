"""The real config/schema loads, is self-consistent, and matches the doc."""

from __future__ import annotations

import pytest

from src.schema import Schema, load_schema


def test_real_schema_loads_and_is_consistent():
    schema = load_schema()
    assert schema.validate() == []
    # full v2 catalogue is wired up front
    assert len(schema.nodes) >= 40
    assert len(schema.edges) >= 40


def test_key_identifiers_match_doc():
    schema = load_schema()
    assert schema.node("Sample").id == "sampleId"
    assert schema.node("Subject").id == "subjectId"
    assert schema.node("Organism").id == "taxonId"
    assert schema.node("RegulatoryElement").id == "elementId"


def test_intervention_multilabelling():
    node = load_schema().node("Intervention")
    assert node.subtype_from == "_subtypeLabel"
    assert "Drug" in node.subtype_labels and "Radiation" in node.subtype_labels


def test_polymorphic_edge_pairs():
    edge = load_schema().edge("SUPPORTS_ASSOCIATION_WITH")
    assert edge.has_pair("Evidence", "Gene")
    assert edge.has_pair("Evidence", "Disease")
    assert not edge.has_pair("Gene", "Evidence")


def test_inconsistent_schema_is_detected():
    from src.schema import Edge

    # an edge referencing undefined nodes must produce validation errors
    bad = Schema(nodes={}, edges={"E": Edge("E", (("X", "Y"),))})
    assert bad.validate()  # non-empty errors
