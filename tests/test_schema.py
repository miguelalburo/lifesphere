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
    assert edge.has_pair("Evidence", "Condition")
    assert not edge.has_pair("Gene", "Evidence")


def test_inconsistent_schema_is_detected():
    from src.schema import Edge

    # an edge referencing undefined nodes must produce validation errors
    bad = Schema(nodes={}, edges={"E": Edge("E", (("X", "Y"),))})
    assert bad.validate()  # non-empty errors


# ─────────────────────── typed properties (admin-import) ───────────────────────

from conftest import write  # noqa: E402


def _load(tmp_path, nodes_yaml, edges_yaml="{}"):
    cfg = tmp_path / "config"
    write(cfg / "schema" / "nodes.yaml", nodes_yaml)
    write(cfg / "schema" / "edges.yaml", edges_yaml)
    return load_schema(cfg)


def test_property_types_parse(tmp_path):
    schema = _load(
        tmp_path,
        """
        Obs:
          id: obsId
          properties: [sampleId, {value: float}, {count: long}]
        """,
    )
    node = schema.node("Obs")
    # names keep declared order; untyped and typed alike appear in .properties
    assert node.properties == ("sampleId", "value", "count")
    assert node.columns == ("obsId", "sampleId", "value", "count")
    # only the annotated ones carry a type; everything else defaults to string
    assert node.property_type("value") == "float"
    assert node.property_type("count") == "long"
    assert node.property_type("sampleId") == "string"
    assert node.property_type("obsId") == "string"


def test_edge_property_types_parse(tmp_path):
    schema = _load(
        tmp_path,
        """
        Obs:
          id: obsId
          properties: []
        Gene:
          id: geneId
        """,
        """
        MEASURES:
          pairs: [[Obs, Gene]]
          properties: [{confidence: double}, note]
        """,
    )
    edge = schema.edge("MEASURES")
    assert edge.properties == ("confidence", "note")
    assert edge.property_type("confidence") == "double"
    assert edge.property_type("note") == "string"


def test_unknown_property_type_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown property type"):
        _load(
            tmp_path,
            """
            Obs:
              id: obsId
              properties: [{value: flaot}]
            """,
        )
