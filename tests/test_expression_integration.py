"""Integration test: expression reshape → standardise (omics profile) → validate.

Pipeline under test:
  1. Synthetic STAR-Counts TSVs written to tmp raw dir.
  2. reshape() merges them into expression_observation.tsv.
  3. standardise("MINI", "omics") writes node/edge CSVs.
  4. Sample.csv pre-populated to simulate the clinical standardise pass.
  5. validate() run with --strict equivalent → zero dangling references.

Uses the real config/ schema and config/mapping/omics.yaml so that any drift
between the mapping and the schema is caught here.
"""

from __future__ import annotations

import csv
from pathlib import Path
from textwrap import dedent

import pytest

from src.extract.omics.expression import reshape
from src.standardise import standardise
from src.validate import validate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STAR_COUNTS = dedent("""\
    N_unmapped\t0\t0\t0
    N_multimapping\t0\t0\t0
    N_noFeature\t0\t0\t0
    N_ambiguous\t0\t0\t0
    gene_id\tgene_name\tgene_type\tunstranded\tstranded_first\tstranded_second\ttpm_unstranded\tfpkm_unstranded\tfpkm_uq_unstranded
    ENSG00000141510.12\tTP53\tprotein_coding\t1000\t500\t500\t5.25\t2.10\t2.60
    ENSG00000012048.21\tBRCA1\tprotein_coding\t2000\t1000\t1000\t10.50\t4.20\t5.10
""")

DATASET = "OMICS_MINI"
SAMPLE_ID = "al-001"
ASSAY_ID = "Illumina|RNA-Seq|STAR - Counts"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    return path


def _csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# Fixture: tmp raw + standardised directories
# ---------------------------------------------------------------------------

@pytest.fixture
def pipeline_dirs(tmp_path: Path):
    """Build raw dir, run reshape, standardise omics, then pre-write Sample.csv."""
    raw_root = tmp_path / "raw"
    std_root = tmp_path / "standardised"
    dataset_raw = raw_root / DATASET

    # 1. Write two synthetic STAR-Counts files (two aliquots, same two genes)
    f1 = dataset_raw / "expression" / "file-001" / "sample1_STAR.tsv"
    f2 = dataset_raw / "expression" / "file-002" / "sample2_STAR.tsv"
    _write(f1, STAR_COUNTS)
    _write(f2, STAR_COUNTS)

    entries = [
        {"path": f1, "sample_id": SAMPLE_ID, "assay_id": ASSAY_ID,
         "source_file": "file-001", "pipeline_version": "STAR - Counts"},
        {"path": f2, "sample_id": "al-002", "assay_id": ASSAY_ID,
         "source_file": "file-002", "pipeline_version": "STAR - Counts"},
    ]

    # 2. Reshape → expression_observation.tsv in raw dir
    obs_path = dataset_raw / "expression_observation.tsv"
    reshape(entries, obs_path, dataset=DATASET)

    # 3. Standardise with omics profile (real schema + omics.yaml)
    standardise(DATASET, "omics", raw_root=raw_root, out_root=std_root, log=False)

    # 4. Pre-populate Sample.csv (simulates clinical standardise pass).
    #    Validate checks that Sample startIds resolve; these nodes come from
    #    the clinical layer, not the omics profile.
    sample_csv = std_root / DATASET / "nodes" / "Sample.csv"
    _write(sample_csv, f"sampleId\n{SAMPLE_ID}\nal-002\n")

    return {"raw": raw_root, "std": std_root}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOmicsStandardise:
    def test_expression_observation_node_csv_written(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "nodes" / "ExpressionObservation.csv"
        assert path.exists()

    def test_gene_node_csv_written(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "nodes" / "Gene.csv"
        assert path.exists()

    def test_assay_node_csv_written(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "nodes" / "Assay.csv"
        assert path.exists()

    def test_expression_observation_count(self, pipeline_dirs):
        # 2 samples × 2 genes = 4 observation rows
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "ExpressionObservation.csv")
        assert len(rows) == 4

    def test_gene_dedup(self, pipeline_dirs):
        # 2 unique genes across 2 samples
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "Gene.csv")
        assert len(rows) == 2

    def test_assay_dedup(self, pipeline_dirs):
        # 1 unique assay (same platform/strategy/workflow across both files)
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "Assay.csv")
        assert len(rows) == 1

    def test_has_expression_observation_edge(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "edges" / "HAS_EXPRESSION_OBSERVATION.csv"
        assert path.exists()
        rows = _csv_rows(path)
        assert len(rows) == 4

    def test_measures_gene_edge(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "edges" / "MEASURES_GENE.csv"
        assert path.exists()
        rows = _csv_rows(path)
        assert len(rows) == 4

    def test_assayed_by_edge_dedup(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "edges" / "ASSAYED_BY.csv"
        assert path.exists()
        rows = _csv_rows(path)
        # 2 samples × 1 assay = 2 edges (deduped from 4 observation rows)
        assert len(rows) == 2

    def test_expression_value_populated(self, pipeline_dirs):
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "ExpressionObservation.csv")
        values = {r.get("expressionValue") for r in rows}
        assert values == {"5.25", "10.50"}

    def test_expression_unit_populated(self, pipeline_dirs):
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "ExpressionObservation.csv")
        assert all(r.get("expressionUnit") == "TPM" for r in rows)


class TestValidateZeroDangling:
    def test_zero_problems(self, pipeline_dirs):
        result = validate(DATASET, standardised_root=pipeline_dirs["std"])
        assert result["problems"] == [], "\n".join(result["problems"])

    def test_all_node_types_present(self, pipeline_dirs):
        result = validate(DATASET, standardised_root=pipeline_dirs["std"])
        # Sample (pre-written), ExpressionObservation, Gene, Assay
        assert result["node_types"] == 4

    def test_edge_count(self, pipeline_dirs):
        result = validate(DATASET, standardised_root=pipeline_dirs["std"])
        # HAS_EXPRESSION_OBSERVATION(4) + MEASURES_GENE(4) + ASSAYED_BY(2) = 10
        assert result["edges"] == 10
