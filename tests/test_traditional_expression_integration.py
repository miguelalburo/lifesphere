"""Integration test: fused `standardise(dataset, "traditional")` for expression.

A user drops a sample-metadata table + a genes_x_samples expression matrix under
data/raw/<dataset>/ and runs one fused command. The reshape pre-pass melts the
matrix into data/interim/, the binder resolves it interim-first and reuses the
omics mapping, and the metadata table binds Sample/Subject. validate() then sees
zero dangling references against the real config.
"""

from __future__ import annotations

import csv
from pathlib import Path
from textwrap import dedent

import pytest

from src.standardise import standardise
from src.validate import validate

DATASET = "TRAD_EXPR"

METADATA = """
    sample_id\tsubject_id\tsex\tsample_type
    sampleA\tsubj1\tfemale\tPrimary Tumor
    sampleB\tsubj2\tmale\tPrimary Tumor
"""

# genes_x_samples TPM matrix; versioned Ensembl ids.
EXPR_MATRIX = """
    gene_id\tsampleA\tsampleB
    ENSG00000141510.12\t5.25\t3.10
    ENSG00000012048.21\t10.50\t8.20
"""

# Same shape, but BRCA1 reads 0 in both samples — undetected genes are
# excluded from standardisation (see observation.ZERO_EXCLUDED_COLUMNS), and
# this is the path (traditional matrix reshape) that never goes through
# src.extract.omics.expression.reshape()'s own extraction-side filter, so it's
# the one that actually exercises the standardise-level defense-in-depth.
EXPR_MATRIX_WITH_ZERO = """
    gene_id\tsampleA\tsampleB
    ENSG00000141510.12\t5.25\t3.10
    ENSG00000012048.21\t0\t0
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    return path


def _csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture
def dirs(tmp_path: Path):
    raw_root = tmp_path / "raw"
    interim_root = tmp_path / "interim"
    std_root = tmp_path / "standardised"
    _write(raw_root / DATASET / "sample_metadata.tsv", METADATA)
    _write(raw_root / DATASET / "expression_matrix.tsv", EXPR_MATRIX)

    standardise(DATASET, "traditional", raw_root=raw_root, out_root=std_root,
                interim_root=interim_root, log=False)
    return {"raw": raw_root, "interim": interim_root, "std": std_root}


class TestFusedExpression:
    def test_interim_observation_tsv_written(self, dirs):
        # reshape pre-pass wrote the canonical TSV to interim, not raw.
        assert (dirs["interim"] / DATASET / "expression_observation.tsv").exists()
        assert not (dirs["raw"] / DATASET / "expression_observation.tsv").exists()

    def test_expression_observation_count(self, dirs):
        rows = _csv_rows(dirs["std"] / DATASET / "nodes" / "ExpressionObservation.csv")
        assert len(rows) == 4  # 2 genes × 2 samples

    def test_gene_ids_version_stripped_and_deduped(self, dirs):
        rows = _csv_rows(dirs["std"] / DATASET / "nodes" / "Gene.csv")
        ids = {r["geneId"] for r in rows}
        assert ids == {"ENSG00000141510", "ENSG00000012048"}

    def test_sample_and_subject_from_metadata(self, dirs):
        samples = _csv_rows(dirs["std"] / DATASET / "nodes" / "Sample.csv")
        subjects = _csv_rows(dirs["std"] / DATASET / "nodes" / "Subject.csv")
        assert {r["sampleId"] for r in samples} == {"sampleA", "sampleB"}
        assert {r["subjectId"] for r in subjects} == {"subj1", "subj2"}

    def test_assay_dedup_and_provenance(self, dirs):
        rows = _csv_rows(dirs["std"] / DATASET / "nodes" / "Assay.csv")
        assert len(rows) == 1
        assay = rows[0]
        assert assay["assayId"] == "traditional-rnaseq-grch38"
        assert assay["platform"] == "Illumina NovaSeq"
        # libraryStrategy moved to LibraryPreparation-only (Assay no longer
        # declares it); Assay.csv has no such column.
        assert "libraryStrategy" not in assay
        assert assay["referenceGenome"] == "GRCh38"
        assert assay["geneAnnotationVersion"] == "GENCODE v36"

    def test_assayed_by_dedup(self, dirs):
        rows = _csv_rows(dirs["std"] / DATASET / "edges" / "ASSAYED_BY.csv")
        assert len(rows) == 2  # one per sample

    def test_expression_edges(self, dirs):
        has_obs = _csv_rows(dirs["std"] / DATASET / "edges" / "HAS_EXPRESSION_OBSERVATION.csv")
        measures = _csv_rows(dirs["std"] / DATASET / "edges" / "MEASURES_GENE.csv")
        assert len(has_obs) == 4
        assert len(measures) == 4

    def test_provided_sample_edge(self, dirs):
        rows = _csv_rows(dirs["std"] / DATASET / "edges" / "PROVIDED_SAMPLE.csv")
        assert len(rows) == 2


class TestValidateZeroDangling:
    def test_zero_problems(self, dirs):
        result = validate(DATASET, standardised_root=dirs["std"])
        assert result["problems"] == [], "\n".join(result["problems"])


ZERO_DATASET = "TRAD_EXPR_ZERO"


@pytest.fixture
def zero_dirs(tmp_path: Path):
    raw_root = tmp_path / "raw"
    interim_root = tmp_path / "interim"
    std_root = tmp_path / "standardised"
    _write(raw_root / ZERO_DATASET / "sample_metadata.tsv", METADATA)
    _write(raw_root / ZERO_DATASET / "expression_matrix.tsv", EXPR_MATRIX_WITH_ZERO)

    standardise(ZERO_DATASET, "traditional", raw_root=raw_root, out_root=std_root,
                interim_root=interim_root, log=False)
    return {"raw": raw_root, "interim": interim_root, "std": std_root}


class TestFusedExpressionExcludesZero:
    def test_zero_gene_excluded_from_node(self, zero_dirs):
        rows = _csv_rows(zero_dirs["std"] / ZERO_DATASET / "nodes" / "ExpressionObservation.csv")
        assert len(rows) == 2  # 1 gene × 2 samples (BRCA1's all-zero rows dropped)

    def test_zero_gene_excluded_from_gene_node(self, zero_dirs):
        rows = _csv_rows(zero_dirs["std"] / ZERO_DATASET / "nodes" / "Gene.csv")
        ids = {r["geneId"] for r in rows}
        assert ids == {"ENSG00000141510"}

    def test_zero_gene_excluded_from_edges(self, zero_dirs):
        has_obs = _csv_rows(zero_dirs["std"] / ZERO_DATASET / "edges" / "HAS_EXPRESSION_OBSERVATION.csv")
        measures = _csv_rows(zero_dirs["std"] / ZERO_DATASET / "edges" / "MEASURES_GENE.csv")
        assert len(has_obs) == 2
        assert len(measures) == 2

    def test_no_dangling_references(self, zero_dirs):
        result = validate(ZERO_DATASET, standardised_root=zero_dirs["std"])
        assert result["problems"] == [], "\n".join(result["problems"])
