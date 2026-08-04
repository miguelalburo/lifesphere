"""Unit tests for methylation reshape.

Covers: beta_value selection, deterministic obs id, CpG annotation inline
(chromosome/start_position/gene_symbol), num_cpg_sites literal, modification_type
literal, methylation_status blank, provenance columns, multi-file merge.
"""

from __future__ import annotations

import csv
from pathlib import Path
from textwrap import dedent

import pytest

from src.extract.omics.methylation import reshape


# ---------------------------------------------------------------------------
# Synthetic methylation beta-value fixture (GDC format)
# ---------------------------------------------------------------------------

BETA_FILE = dedent("""\
    Composite Element REF\tBeta_value\tChromosome\tStart\tEnd\tGene_Symbol\tGene_Type\tTranscript_ID\tPosition_to_TSS\tCGI_Coordinate\tFeature_Type
    cg00000001\t0.1234\tchr1\t10000\t10038\tTP53\tprotein_coding\tENST00000269305\t-100\tchr1:9800-10100\tS_Shore
    cg00000002\t0.5678\tchr17\t50000\t50038\tBRCA1\tprotein_coding\tENST00000357654\t200\t.\tIsland
""")


def _write_beta(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _read_obs(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        rows = list(reader)
        return list(reader.fieldnames or []), rows


# ---------------------------------------------------------------------------
# reshape
# ---------------------------------------------------------------------------

class TestReshape:
    def test_returns_row_count(self, tmp_path):
        beta_path = _write_beta(tmp_path, "beta.tsv", BETA_FILE)
        out = tmp_path / "obs.tsv"
        n = reshape(
            [{"path": beta_path, "sample_id": "s1", "assay_id": "A1"}],
            out,
        )
        assert n == 2

    def test_beta_value_selected(self, tmp_path):
        beta_path = _write_beta(tmp_path, "beta.tsv", BETA_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": beta_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        assert rows[0]["beta_value"] == "0.1234"
        assert rows[1]["beta_value"] == "0.5678"

    def test_deterministic_obs_id(self, tmp_path):
        # No platform_code given -> falls back to "unknown", per the same
        # missing-platform convention as assay_id().
        beta_path = _write_beta(tmp_path, "beta.tsv", BETA_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": beta_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        obs_ids = {r["methylation_observation_id"] for r in rows}
        assert "s1:unknown:cg00000001" in obs_ids
        assert "s1:unknown:cg00000002" in obs_ids

    def test_cpg_id_is_platform_qualified(self, tmp_path):
        beta_path = _write_beta(tmp_path, "beta.tsv", BETA_FILE)
        out = tmp_path / "obs.tsv"
        reshape(
            [{"path": beta_path, "sample_id": "s1", "assay_id": "A1", "platform_code": "450k"}],
            out,
        )
        _, rows = _read_obs(out)
        cpg_ids = {r["cpg_id"] for r in rows}
        source_cpg_ids = {r["source_cpg_id"] for r in rows}
        assert cpg_ids == {"450k:cg00000001", "450k:cg00000002"}
        assert source_cpg_ids == {"cg00000001", "cg00000002"}

    def test_cpg_id_defaults_to_unknown_platform(self, tmp_path):
        beta_path = _write_beta(tmp_path, "beta.tsv", BETA_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": beta_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        cpg_ids = {r["cpg_id"] for r in rows}
        assert cpg_ids == {"unknown:cg00000001", "unknown:cg00000002"}

    def test_cpg_annotation_inline(self, tmp_path):
        beta_path = _write_beta(tmp_path, "beta.tsv", BETA_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": beta_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        row = next(r for r in rows if r["source_cpg_id"] == "cg00000001")
        assert row["chromosome"] == "chr1"
        assert row["start_position"] == "10000"
        assert row["gene_symbol"] == "TP53"

    def test_num_cpg_sites_is_one(self, tmp_path):
        beta_path = _write_beta(tmp_path, "beta.tsv", BETA_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": beta_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        assert all(r["num_cpg_sites"] == "1" for r in rows)

    def test_modification_type_is_5mc(self, tmp_path):
        beta_path = _write_beta(tmp_path, "beta.tsv", BETA_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": beta_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        assert all(r["modification_type"] == "5mC" for r in rows)

    def test_methylation_status_blank(self, tmp_path):
        beta_path = _write_beta(tmp_path, "beta.tsv", BETA_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": beta_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        assert all(r["methylation_status"] == "" for r in rows)

    def test_provenance_columns_present(self, tmp_path):
        beta_path = _write_beta(tmp_path, "beta.tsv", BETA_FILE)
        out = tmp_path / "obs.tsv"
        reshape(
            [{"path": beta_path, "sample_id": "s1", "assay_id": "A1",
              "source_file": "file-uuid-001", "pipeline_version": "SeSAMe"}],
            out, dataset="TCGA-BRCA",
        )
        _, rows = _read_obs(out)
        for row in rows:
            assert row["source_dataset"] == "TCGA-BRCA"
            assert row["source_file"] == "file-uuid-001"
            assert row["pipeline_version"] == "SeSAMe"

    def test_multi_file_merge(self, tmp_path):
        f1 = _write_beta(tmp_path, "f1.tsv", BETA_FILE)
        f2 = _write_beta(tmp_path, "f2.tsv", BETA_FILE)
        out = tmp_path / "obs.tsv"
        n = reshape(
            [
                {"path": f1, "sample_id": "s1", "assay_id": "A1"},
                {"path": f2, "sample_id": "s2", "assay_id": "A1"},
            ],
            out,
        )
        assert n == 4  # 2 CpGs × 2 samples
        _, rows = _read_obs(out)
        sample_ids = {r["sample_id"] for r in rows}
        assert sample_ids == {"s1", "s2"}

    def test_empty_entries(self, tmp_path):
        out = tmp_path / "obs.tsv"
        n = reshape([], out)
        assert n == 0
        _, rows = _read_obs(out)
        assert rows == []

    def test_header_row_not_in_output(self, tmp_path):
        beta_path = _write_beta(tmp_path, "beta.tsv", BETA_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": beta_path, "sample_id": "s1", "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        cpg_ids = {r["cpg_id"] for r in rows}
        assert "Composite Element REF" not in cpg_ids
