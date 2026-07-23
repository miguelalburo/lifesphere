"""Created ids are minted inside standardise, not copied from the source file.

The observation surrogate keys are *created* ids: they must come out identical no
matter which ingest path (GDC extract vs traditional reshape) wrote the file, and
no matter what the file's own id column happens to hold. These tests pin that
guarantee at both seams — the shared registry (unit) and the engine (behaviour).
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.observation import DERIVED_KEYS, EXPRESSION_OBS_COLUMNS, obs_id
from src.standardise import standardise

DATASET = "MINI_DERIVED"


# ── unit: the registry mints from its declared source columns ──────────────

def test_expression_observation_builder_matches_obs_id():
    builder = DERIVED_KEYS["ExpressionObservation"]
    assert builder.sources == ("sample_id", "gene_id")
    assert builder.mint(["al-001", "ENSG0001"]) == obs_id("al-001", "ENSG0001")


def test_every_registered_builder_is_deterministic():
    for builder in DERIVED_KEYS.values():
        args = [f"v{i}" for i in range(len(builder.sources))]
        assert builder.mint(args) == builder.mint(args)


# ── behaviour: standardise ignores the file's id column and mints it ───────

def _write_obs(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXPRESSION_OBS_COLUMNS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_standardise_mints_created_id_ignoring_source_column(tmp_path):
    """A deliberately wrong id column is overridden by the minted `sample:gene`."""
    raw_root = tmp_path / "raw"
    std_root = tmp_path / "standardised"
    obs = raw_root / DATASET / "expression_observation.tsv"
    # expression_observation_id holds GARBAGE — as if a divergent path wrote it.
    _write_obs(obs, [
        {"expression_observation_id": "WRONG-DASH-FORM", "sample_id": "al-001",
         "gene_id": "ENSG0001", "expression_value": "5.0", "expression_unit": "tpm",
         "assay_id": "a1", "source_dataset": DATASET, "source_file": "f1",
         "pipeline_version": "STAR"},
    ])

    standardise(DATASET, "omics", raw_root=raw_root, out_root=std_root, log=False)

    node_rows = _rows(std_root / DATASET / "nodes" / "ExpressionObservation.csv")
    assert [r["expressionObservationId"] for r in node_rows] == ["al-001:ENSG0001"]

    # the edge endpoint onto that node mints the same id, so it still attaches
    edge_rows = _rows(std_root / DATASET / "edges" / "HAS_EXPRESSION_OBSERVATION.csv")
    assert [r["endId"] for r in edge_rows] == ["al-001:ENSG0001"]


def test_created_id_skipped_when_a_source_column_is_empty(tmp_path):
    """No id can be minted from a missing component — the row is dropped, not blank."""
    raw_root = tmp_path / "raw"
    std_root = tmp_path / "standardised"
    obs = raw_root / DATASET / "expression_observation.tsv"
    _write_obs(obs, [
        {"expression_observation_id": "x", "sample_id": "al-001", "gene_id": "",
         "expression_value": "5.0", "expression_unit": "tpm", "assay_id": "a1",
         "source_dataset": DATASET, "source_file": "f1", "pipeline_version": "STAR"},
    ])

    standardise(DATASET, "omics", raw_root=raw_root, out_root=std_root, log=False)

    node_rows = _rows(std_root / DATASET / "nodes" / "ExpressionObservation.csv")
    assert node_rows == []
