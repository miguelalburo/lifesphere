"""Unit tests for expression reshape.

Covers: TPM selection, version-stripped ENSG, deterministic ids, N_* row
skipping, expression_unit literal, provenance columns, multi-file merge.
"""

from __future__ import annotations

import csv
from pathlib import Path
from textwrap import dedent

import pytest

from src.extract.omics.expression import _strip_version, reshape


# ---------------------------------------------------------------------------
# Synthetic STAR-Counts fixture
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


def _write_counts(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _read_obs(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        rows = list(reader)
        return list(reader.fieldnames or []), rows


# ---------------------------------------------------------------------------
# _strip_version
# ---------------------------------------------------------------------------

class TestStripVersion:
    def test_strips_numeric_suffix(self):
        assert _strip_version("ENSG00000141510.12") == "ENSG00000141510"

    def test_strips_single_digit_suffix(self):
        assert _strip_version("ENSG00000012048.5") == "ENSG00000012048"

    def test_no_dot_unchanged(self):
        assert _strip_version("ENSG00000141510") == "ENSG00000141510"

    def test_non_ensg_still_stripped(self):
        assert _strip_version("ENSR00000141510.3") == "ENSR00000141510"


# ---------------------------------------------------------------------------
# reshape
# ---------------------------------------------------------------------------

class TestReshape:
    def test_returns_row_count(self, tmp_path):
        counts_path = _write_counts(tmp_path, "counts.tsv", STAR_COUNTS)
        out = tmp_path / "obs.tsv"
        n = reshape(
            [{"path": counts_path, "sample_id": "s1", "assay_id": "A1"}],
            out,
        )
        assert n == 2  # 2 gene rows

    def test_metadata_rows_excluded(self, tmp_path):
        counts_path = _write_counts(tmp_path, "counts.tsv", STAR_COUNTS)
        out = tmp_path / "obs.tsv"
        reshape([{"path": counts_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        gene_ids = {r["gene_id"] for r in rows}
        assert not any(g.startswith("N_") for g in gene_ids)

    def test_header_row_excluded(self, tmp_path):
        counts_path = _write_counts(tmp_path, "counts.tsv", STAR_COUNTS)
        out = tmp_path / "obs.tsv"
        reshape([{"path": counts_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        assert not any(r["gene_id"] == "gene_id" for r in rows)

    def test_tpm_selected(self, tmp_path):
        counts_path = _write_counts(tmp_path, "counts.tsv", STAR_COUNTS)
        out = tmp_path / "obs.tsv"
        reshape([{"path": counts_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        assert rows[0]["expression_value"] == "5.25"
        assert rows[1]["expression_value"] == "10.50"

    def test_counts_not_in_output(self, tmp_path):
        counts_path = _write_counts(tmp_path, "counts.tsv", STAR_COUNTS)
        out = tmp_path / "obs.tsv"
        reshape([{"path": counts_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        for row in rows:
            assert "unstranded" not in row
            assert "fpkm" not in row

    def test_expression_unit_is_tpm(self, tmp_path):
        counts_path = _write_counts(tmp_path, "counts.tsv", STAR_COUNTS)
        out = tmp_path / "obs.tsv"
        reshape([{"path": counts_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        assert all(r["expression_unit"] == "TPM" for r in rows)

    def test_gene_id_version_stripped(self, tmp_path):
        counts_path = _write_counts(tmp_path, "counts.tsv", STAR_COUNTS)
        out = tmp_path / "obs.tsv"
        reshape([{"path": counts_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        gene_ids = {r["gene_id"] for r in rows}
        assert gene_ids == {"ENSG00000141510", "ENSG00000012048"}
        assert not any("." in g for g in gene_ids)

    def test_deterministic_obs_id(self, tmp_path):
        counts_path = _write_counts(tmp_path, "counts.tsv", STAR_COUNTS)
        out = tmp_path / "obs.tsv"
        reshape([{"path": counts_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        obs_ids = {r["expression_observation_id"] for r in rows}
        assert "s1:ENSG00000141510" in obs_ids
        assert "s1:ENSG00000012048" in obs_ids

    def test_provenance_columns_present(self, tmp_path):
        counts_path = _write_counts(tmp_path, "counts.tsv", STAR_COUNTS)
        out = tmp_path / "obs.tsv"
        reshape(
            [{"path": counts_path, "sample_id": "s1", "assay_id": "A1",
              "source_file": "f-uuid-001", "pipeline_version": "STAR - Counts"}],
            out, dataset="TCGA-CHOL",
        )
        _, rows = _read_obs(out)
        for row in rows:
            assert row["source_dataset"] == "TCGA-CHOL"
            assert row["source_file"] == "f-uuid-001"
            assert row["pipeline_version"] == "STAR - Counts"

    def test_multi_file_merge(self, tmp_path):
        f1 = _write_counts(tmp_path, "f1.tsv", STAR_COUNTS)
        f2 = _write_counts(tmp_path, "f2.tsv", STAR_COUNTS)
        out = tmp_path / "obs.tsv"
        n = reshape(
            [
                {"path": f1, "sample_id": "s1", "assay_id": "A1"},
                {"path": f2, "sample_id": "s2", "assay_id": "A1"},
            ],
            out,
        )
        assert n == 4  # 2 genes × 2 samples
        _, rows = _read_obs(out)
        sample_ids = {r["sample_id"] for r in rows}
        assert sample_ids == {"s1", "s2"}

    def test_empty_entries(self, tmp_path):
        out = tmp_path / "obs.tsv"
        n = reshape([], out)
        assert n == 0
        _, rows = _read_obs(out)
        assert rows == []
