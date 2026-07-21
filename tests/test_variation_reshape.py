"""Unit tests for variation reshape.

Covers: variantId construction (chrom:pos:ref:alt), version-stripped ENSG
sharing with expression layer, deterministic obs id, VAF computation, MAF
comment-line skipping, somatic_status literal, provenance columns, multi-file
merge.
"""

from __future__ import annotations

import csv
import gzip
from pathlib import Path
from textwrap import dedent

import pytest

from src.extract.omics.variation import (
    _compute_vaf,
    _strip_version,
    _variant_id,
    aliquot_map,
    reshape,
)


# ---------------------------------------------------------------------------
# Synthetic MAF fixture (GDC Masked Somatic Mutation format)
# ---------------------------------------------------------------------------

MAF_FILE = dedent("""\
    # GDC MAF file - comment header
    Hugo_Symbol\tChromosome\tStart_Position\tEnd_Position\tVariant_Classification\tVariant_Type\tReference_Allele\tTumor_Seq_Allele2\tTumor_Sample_Barcode\tGene\tIMPACT\tt_depth\tt_alt_count\tn_depth\tn_alt_count\tFILTER
    TP53\t17\t7674220\t7674220\tMissense_Mutation\tSNP\tC\tT\tTCGA-XX-0001-01A-11D-0001-08\tENSG00000141510.11\tMODERATE\t100\t25\t80\t0\tPASS
    BRCA1\t17\t43092912\t43092912\tFrameshift_Del\tDEL\tAGTC\t-\tTCGA-XX-0001-01A-11D-0001-08\tENSG00000012048.22\tHIGH\t80\t40\t70\t0\tPASS
""")


def _write_maf(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _read_obs(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        rows = list(reader)
        return list(reader.fieldnames or []), rows


# ---------------------------------------------------------------------------
# _strip_version (shared rule with expression layer)
# ---------------------------------------------------------------------------

class TestStripVersion:
    def test_strips_version_suffix(self):
        assert _strip_version("ENSG00000141510.11") == "ENSG00000141510"

    def test_no_dot_unchanged(self):
        assert _strip_version("ENSG00000141510") == "ENSG00000141510"

    def test_matches_expression_rule(self):
        # same gene, different MAF vs expression version numbers → same stripped id
        from src.extract.omics.expression import _strip_version as expr_strip
        assert _strip_version("ENSG00000141510.11") == expr_strip("ENSG00000141510.12")


# ---------------------------------------------------------------------------
# _variant_id
# ---------------------------------------------------------------------------

class TestVariantId:
    def test_chrom_pos_ref_alt_format(self):
        assert _variant_id("17", "7674220", "C", "T") == "17:7674220:C:T"

    def test_deletion_alt(self):
        assert _variant_id("17", "43092912", "AGTC", "-") == "17:43092912:AGTC:-"


# ---------------------------------------------------------------------------
# _compute_vaf
# ---------------------------------------------------------------------------

class TestComputeVaf:
    def test_basic_division(self):
        assert _compute_vaf("100", "25") == "0.2500"

    def test_zero_depth_returns_empty(self):
        assert _compute_vaf("0", "5") == ""

    def test_non_numeric_returns_empty(self):
        assert _compute_vaf(".", ".") == ""

    def test_empty_returns_empty(self):
        assert _compute_vaf("", "") == ""

    def test_full_vaf(self):
        assert _compute_vaf("80", "80") == "1.0000"


# ---------------------------------------------------------------------------
# reshape
# ---------------------------------------------------------------------------

class TestReshape:
    def test_returns_row_count(self, tmp_path):
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        n = reshape([{"path": maf_path, "assay_id": "A1"}], out)
        assert n == 2

    def test_comment_lines_excluded(self, tmp_path):
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": maf_path, "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        # no row should have sample_id starting with "#"
        assert not any(r["sample_id"].startswith("#") for r in rows)

    def test_header_row_excluded(self, tmp_path):
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": maf_path, "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        assert not any(r["sample_id"] == "Tumor_Sample_Barcode" for r in rows)

    def test_variant_id_format(self, tmp_path):
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": maf_path, "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        var_ids = {r["variant_id"] for r in rows}
        assert "17:7674220:C:T" in var_ids
        assert "17:43092912:AGTC:-" in var_ids

    def test_gene_id_version_stripped(self, tmp_path):
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": maf_path, "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        gene_ids = {r["gene_id"] for r in rows}
        assert gene_ids == {"ENSG00000141510", "ENSG00000012048"}
        assert not any("." in g for g in gene_ids)

    def test_gene_id_converges_with_expression(self, tmp_path):
        """version-stripped gene_id from MAF matches expression layer's gene_id."""
        from src.extract.omics.expression import _strip_version as expr_strip
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": maf_path, "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        variation_gene_ids = {r["gene_id"] for r in rows}
        # expression would strip ENSG00000141510.12 → ENSG00000141510
        assert "ENSG00000141510" in variation_gene_ids
        assert expr_strip("ENSG00000141510.12") in variation_gene_ids

    def test_deterministic_obs_id(self, tmp_path):
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": maf_path, "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        obs_ids = {r["variant_observation_id"] for r in rows}
        assert "TCGA-XX-0001-01A-11D-0001-08:17:7674220:C:T" in obs_ids

    def test_vaf_computed(self, tmp_path):
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": maf_path, "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        row = next(r for r in rows if r["variant_id"] == "17:7674220:C:T")
        assert row["variant_allele_frequency"] == "0.2500"

    def test_somatic_status_literal(self, tmp_path):
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": maf_path, "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        assert all(r["somatic_status"] == "Somatic" for r in rows)

    def test_filter_status_populated(self, tmp_path):
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": maf_path, "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        assert all(r["filter_status"] == "PASS" for r in rows)

    def test_reference_columns_populated(self, tmp_path):
        """Variant reference columns are populated for Variant node dedup."""
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        reshape([{"path": maf_path, "assay_id": "A1"}], out)
        _, rows = _read_obs(out)
        row = next(r for r in rows if r["variant_id"] == "17:7674220:C:T")
        assert row["chromosome"] == "17"
        assert row["position_start"] == "7674220"
        assert row["reference_allele"] == "C"
        assert row["alternate_allele"] == "T"
        assert row["variant_class"] == "Missense_Mutation"

    def test_provenance_columns_present(self, tmp_path):
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        reshape(
            [{"path": maf_path, "assay_id": "A1",
              "source_file": "file-uuid-var", "pipeline_version": "Varscan2"}],
            out, dataset="TCGA-CHOL",
        )
        _, rows = _read_obs(out)
        for row in rows:
            assert row["source_dataset"] == "TCGA-CHOL"
            assert row["source_file"] == "file-uuid-var"
            assert row["pipeline_version"] == "Varscan2"

    def test_multi_file_merge(self, tmp_path):
        f1 = _write_maf(tmp_path, "f1.tsv", MAF_FILE)
        f2 = _write_maf(tmp_path, "f2.tsv", MAF_FILE.replace(
            "TCGA-XX-0001-01A-11D-0001-08", "TCGA-YY-0002-01A-11D-0002-08"
        ))
        out = tmp_path / "obs.tsv"
        n = reshape(
            [
                {"path": f1, "assay_id": "A1"},
                {"path": f2, "assay_id": "A1"},
            ],
            out,
        )
        assert n == 4  # 2 mutations × 2 samples
        _, rows = _read_obs(out)
        sample_ids = {r["sample_id"] for r in rows}
        assert "TCGA-XX-0001-01A-11D-0001-08" in sample_ids
        assert "TCGA-YY-0002-01A-11D-0002-08" in sample_ids

    def test_empty_entries(self, tmp_path):
        out = tmp_path / "obs.tsv"
        n = reshape([], out)
        assert n == 0
        _, rows = _read_obs(out)
        assert rows == []

    def test_gzipped_maf_parsed(self, tmp_path):
        gz_path = tmp_path / "maf.maf.gz"
        gz_path.write_bytes(gzip.compress(MAF_FILE.encode("utf-8")))
        out = tmp_path / "obs.tsv"
        n = reshape([{"path": gz_path, "assay_id": "A1"}], out)
        assert n == 2

    def test_sample_id_map_remaps_barcode_to_uuid(self, tmp_path):
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        barcode = "TCGA-XX-0001-01A-11D-0001-08"
        uuid = "aliquot-uuid-0001"
        reshape(
            [{"path": maf_path, "assay_id": "A1"}],
            out,
            sample_id_map={barcode: uuid},
        )
        _, rows = _read_obs(out)
        sample_ids = {r["sample_id"] for r in rows}
        assert sample_ids == {uuid}, f"Expected {{uuid}}, got {sample_ids}"
        assert barcode not in sample_ids

    def test_sample_id_map_fallback_to_barcode_when_unmapped(self, tmp_path):
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        # Map does NOT include the barcode in the file → barcode is kept as-is
        reshape(
            [{"path": maf_path, "assay_id": "A1"}],
            out,
            sample_id_map={"OTHER-BARCODE": "other-uuid"},
        )
        _, rows = _read_obs(out)
        sample_ids = {r["sample_id"] for r in rows}
        assert "TCGA-XX-0001-01A-11D-0001-08" in sample_ids

    def test_keep_barcodes_filters_rows(self, tmp_path):
        # Two samples in MAF; keep only one
        other_barcode = "TCGA-YY-0002-01A-11D-0002-08"
        maf_two = MAF_FILE + (
            f"TP53\t17\t7674220\t7674220\tMissense_Mutation\tSNP\tC\tT"
            f"\t{other_barcode}\tENSG00000141510.11\tMODERATE\t100\t25\t80\t0\tPASS\n"
        )
        maf_path = _write_maf(tmp_path, "maf.tsv", maf_two)
        out = tmp_path / "obs.tsv"
        keep = {"TCGA-XX-0001-01A-11D-0001-08"}
        n = reshape([{"path": maf_path, "assay_id": "A1"}], out, keep_barcodes=keep)
        _, rows = _read_obs(out)
        sample_ids = {r["sample_id"] for r in rows}
        assert other_barcode not in sample_ids
        assert "TCGA-XX-0001-01A-11D-0001-08" in sample_ids

    def test_keep_barcodes_and_sample_id_map_compose(self, tmp_path):
        # Filter to one barcode AND remap it to a UUID
        barcode = "TCGA-XX-0001-01A-11D-0001-08"
        uuid = "aliquot-uuid-0001"
        maf_path = _write_maf(tmp_path, "maf.tsv", MAF_FILE)
        out = tmp_path / "obs.tsv"
        reshape(
            [{"path": maf_path, "assay_id": "A1"}],
            out,
            sample_id_map={barcode: uuid},
            keep_barcodes={barcode},
        )
        _, rows = _read_obs(out)
        sample_ids = {r["sample_id"] for r in rows}
        assert sample_ids == {uuid}


# ---------------------------------------------------------------------------
# aliquot_map: build {aliquot barcode → aliquot UUID} from /files hits
# ---------------------------------------------------------------------------


def _file_with_aliquots(*aliquots: tuple[str, str]) -> dict:
    """A /files hit with one case whose sole sample carries the given aliquots.

    Each aliquot is a (submitter_id, aliquot_id) pair; empty strings are kept so
    incomplete-aliquot handling can be exercised.
    """
    entries = [{"submitter_id": bc, "aliquot_id": uid} for bc, uid in aliquots]
    return {"cases": [
        {"case_id": "c1", "samples": [
            {"portions": [{"analytes": [{"aliquots": entries}]}]}
        ]}
    ]}


class TestAliquotMap:
    def test_builds_barcode_to_uuid(self):
        files = [_file_with_aliquots(("TCGA-AB-0001-01A-11D-0001-08", "uuid-001"))]
        assert aliquot_map(files) == {"TCGA-AB-0001-01A-11D-0001-08": "uuid-001"}

    def test_unions_across_files_and_aliquots(self):
        files = [
            _file_with_aliquots(("TCGA-AB-0001-01A-11D-0001-08", "uuid-001")),
            _file_with_aliquots(
                ("TCGA-AB-0002-01A-11D-0002-08", "uuid-002"),
                ("TCGA-AB-0003-10A-11D-0003-08", "uuid-003"),
            ),
        ]
        assert aliquot_map(files) == {
            "TCGA-AB-0001-01A-11D-0001-08": "uuid-001",
            "TCGA-AB-0002-01A-11D-0002-08": "uuid-002",
            "TCGA-AB-0003-10A-11D-0003-08": "uuid-003",
        }

    def test_skips_incomplete_aliquots(self):
        # barcode without uuid (and vice versa) → not added
        files = [_file_with_aliquots(("TCGA-X", ""), ("", "uuid-orphan"))]
        assert aliquot_map(files) == {}

    def test_tolerates_missing_nesting(self):
        # hits without the cases/samples/... expand must not raise
        assert aliquot_map([{"file_id": "f1"}, {"cases": [{"case_id": "c1"}]}]) == {}

    def test_empty_input(self):
        assert aliquot_map([]) == {}
