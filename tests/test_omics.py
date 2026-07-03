"""Unit tests for the omics layer of Stage 1 standardisation (src/standardise).

Runs the standardiser over the checked-in synthetic fixture
(tests/fixtures/omics_smoke) and asserts the reified omics contract:
per-assay observation nodes carry their measurement props, shared feature nodes
are deduplicated, all edges keep referential integrity, and the
Sample -> Observation -> Feature chain resolves.
"""

import csv
from pathlib import Path

import pytest

from src.standardise.run import run

FIXTURE = Path(__file__).parent / "fixtures" / "omics_smoke"


@pytest.fixture(scope="module")
def std_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("omics_std")
    run(FIXTURE, out)
    return out


def _read(path: Path) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


def _node(std: Path, label: str) -> list[dict]:
    return _read(std / "nodes" / f"{label}.csv")


def _edge(std: Path, label: str) -> list[dict]:
    return _read(std / "edges" / f"{label}.csv")


def _ids(std: Path, label: str) -> set:
    return {r["id"] for r in _node(std, label)}


def test_feature_nodes_deduped(std_dir):
    # Each feature appears once despite being measured in multiple samples.
    assert len(_node(std_dir, "Gene")) == 2
    assert len(_node(std_dir, "CpGSite")) == 2
    assert len(_node(std_dir, "Variant")) == 2
    assert len(_node(std_dir, "Protein")) == 2
    assert len(_node(std_dir, "Pathway")) == 2


def test_observation_grain_preserved(std_dir):
    # One observation node per measurement (no collapsing): 4 bulk sample x gene
    # rows + 2 pseudobulk sample x cell_type x gene rows, all ExpressionObservation nodes.
    assert len(_node(std_dir, "ExpressionObservation")) == 6
    assert len(_node(std_dir, "MethylationObservation")) == 3
    assert len(_node(std_dir, "VariantObservation")) == 2
    assert len(_node(std_dir, "ProteinObservation")) == 2


def test_observation_nodes_carry_measurement_props(std_dir):
    expr = {r["id"]: r for r in _node(std_dir, "ExpressionObservation")}
    row = expr["EXP-S1-ENSG001"]
    assert row["tpm"] == "12.5" and row["fpkm"] == "10.1"
    assert row["aliquotId"] == "S1" and row["fileId"] == "F1"
    # FK columns are dropped from the node (they live on the edges instead).
    assert "sampleId" not in row and "geneEnsembl" not in row and "caseId" not in row

    vc = {r["id"]: r for r in _node(std_dir, "VariantObservation")}["VC-S1-V1"]
    assert vc["vaf"] == "0.35"
    assert vc["consequence"] == "missense_variant" and vc["impact"] == "MODERATE"


def test_variant_node_keeps_gene_annotation(std_dir):
    v = {r["id"]: r for r in _node(std_dir, "Variant")}["V1"]
    assert v["geneEnsembl"] == "ENSG001"
    assert v["hgvsp"] == "p.R175H"


def test_omics_edge_referential_integrity(std_dir):
    """Every edge endpoint resolves to a node of the expected label."""
    checks = [
        ("HAS_EXPRESSION_OBSERVATION", "Sample", "ExpressionObservation"),
        ("MEASURES_GENE", "ExpressionObservation", "Gene"),
        ("OF_CELL_TYPE", "ExpressionObservation", "CellType"),
        ("HAS_METHYLATION_OBSERVATION", "Sample", "MethylationObservation"),
        ("MEASURES_CPG", "MethylationObservation", "CpGSite"),
        ("HAS_VARIANT_OBSERVATION", "Sample", "VariantObservation"),
        ("OBSERVED_VARIANT", "VariantObservation", "Variant"),
        ("HAS_PROTEIN_OBSERVATION", "Sample", "ProteinObservation"),
        ("MEASURES_PROTEIN", "ProteinObservation", "Protein"),
        ("AFFECTS_GENE", "Variant", "Gene"),
        ("PARTICIPATES_IN_PATHWAY", "Gene", "Pathway"),
        ("ENCODES", "Gene", "Protein"),
    ]
    for edge_label, src_label, tgt_label in checks:
        edges = _edge(std_dir, edge_label)
        assert edges, f"{edge_label} has no rows"
        src_ids, tgt_ids = _ids(std_dir, src_label), _ids(std_dir, tgt_label)
        assert {r["source_id"] for r in edges} <= src_ids, f"{edge_label} bad source"
        assert {r["target_id"] for r in edges} <= tgt_ids, f"{edge_label} bad target"


def test_sample_observation_feature_chain_resolves(std_dir):
    """S1 -HAS_EXPRESSION_OBSERVATION-> ExpressionObservation -MEASURES_GENE-> ENSG001 is a connected path."""
    has_expr = {(r["source_id"], r["target_id"]) for r in _edge(std_dir, "HAS_EXPRESSION_OBSERVATION")}
    of_gene = {(r["source_id"], r["target_id"]) for r in _edge(std_dir, "MEASURES_GENE")}
    assert ("S1", "EXP-S1-ENSG001") in has_expr
    assert ("EXP-S1-ENSG001", "ENSG001") in of_gene


def test_pseudobulk_folds_into_expression(std_dir):
    """Pseudobulk is an ExpressionObservation node with assay_type=pseudobulk + an
    OF_CELL_TYPE edge; bulk rows share the node label but carry no cell-type edge."""
    expr = {r["id"]: r for r in _node(std_dir, "ExpressionObservation")}
    bulk, pseudo = expr["EXP-S1-ENSG001"], expr["PB-S1-CT1-ENSG001"]

    assert bulk["assayType"] == "bulk"
    assert pseudo["assayType"] == "pseudobulk"
    # Pseudobulk-only stats ride through as node props; the cell_type FK does not.
    assert pseudo["meanExpr"] == "9.9" and pseudo["pctExpressing"] == "0.62"
    assert "cellTypeId" not in pseudo

    # OF_CELL_TYPE materialises for pseudobulk rows only (bulk rows leave the FK blank).
    of_cell_type = {(r["source_id"], r["target_id"]) for r in _edge(std_dir, "OF_CELL_TYPE")}
    assert of_cell_type == {("PB-S1-CT1-ENSG001", "CL:0000236"),
                            ("PB-S1-CT1-ENSG002", "CL:0000236")}
    assert not any(src.startswith("EXP-") for src, _ in of_cell_type)
