"""Unit tests for src.extract.case_selector.

Tests cover:
  - _case_ids_from_files: extract GDC case UUIDs from file hits
  - _preferred_case_id: prefer primary-tumor cases; fall back to any case
  - select_case: integration with mocked GDC API (3-type intersection,
    widening to fallback projects, RuntimeError when nothing qualifies)

The barcode→UUID map builder (aliquot_map) lives in src.extract.omics.variation
and is tested in test_variation_reshape.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.extract.case_selector import (
    CaseSelection,
    _case_ids_from_files,
    _preferred_case_id,
    select_case,
)


# ─────────────────────────────── Fixtures ────────────────────────────────────


def _make_file(file_id: str, case_id: str, barcode: str = "", uuid: str = "",
               sample_type: str = "") -> dict:
    """Build a minimal /files response hit with nested case/aliquot structure."""
    aliquot: dict = {}
    if barcode:
        aliquot["submitter_id"] = barcode
    if uuid:
        aliquot["aliquot_id"] = uuid
    case: dict = {"case_id": case_id}
    if sample_type:
        case["samples"] = [
            {"sample_type": sample_type, "portions": [
                {"analytes": [{"aliquots": [aliquot]}]}
            ]}
        ]
    elif barcode or uuid:
        case["samples"] = [
            {"portions": [{"analytes": [{"aliquots": [aliquot]}]}]}
        ]
    return {"file_id": file_id, "file_name": f"{file_id}.tsv", "cases": [case]}


# ──────────────────────────── _case_ids_from_files ───────────────────────────


class TestCaseIdsFromFiles:
    def test_extracts_case_ids(self):
        files = [
            _make_file("f1", "case-001"),
            _make_file("f2", "case-002"),
        ]
        assert _case_ids_from_files(files) == {"case-001", "case-002"}

    def test_skips_empty_case_id(self):
        files = [{"file_id": "f1", "cases": [{"case_id": ""}]}]
        assert _case_ids_from_files(files) == set()

    def test_multi_case_file(self):
        # A project MAF can be associated with many cases.
        files = [{
            "file_id": "maf",
            "cases": [{"case_id": "c1"}, {"case_id": "c2"}, {"case_id": "c3"}],
        }]
        assert _case_ids_from_files(files) == {"c1", "c2", "c3"}

    def test_empty_input(self):
        assert _case_ids_from_files([]) == set()

    def test_no_cases_key(self):
        assert _case_ids_from_files([{"file_id": "f1"}]) == set()


# ─────────────────────────── _preferred_case_id ──────────────────────────────


class TestPreferredCaseId:
    def test_prefers_primary_tumor(self):
        files = [
            _make_file("f1", "case-blood", sample_type="Blood Derived Normal"),
            _make_file("f2", "case-tumor", sample_type="Primary Tumor"),
        ]
        case_ids = {"case-blood", "case-tumor"}
        assert _preferred_case_id(case_ids, files) == "case-tumor"

    def test_falls_back_to_any_case(self):
        files = [_make_file("f1", "case-x", sample_type="Blood Derived Normal")]
        result = _preferred_case_id({"case-x"}, files)
        assert result == "case-x"

    def test_skips_cases_not_in_set(self):
        files = [
            _make_file("f1", "case-exclude", sample_type="Primary Tumor"),
            _make_file("f2", "case-include", sample_type="Metastatic"),
        ]
        case_ids = {"case-include"}
        assert _preferred_case_id(case_ids, files) == "case-include"

    def test_empty_case_set(self):
        files = [_make_file("f1", "case-x", sample_type="Primary Tumor")]
        assert _preferred_case_id(set(), files) is None


# ──────────────────────────────── select_case ────────────────────────────────


def _make_page(hits: list[dict]) -> dict:
    """Wrap file hits in a GDC-style /files response."""
    return {"data": {"hits": hits, "pagination": {"total": len(hits)}}}


class TestSelectCase:
    """select_case with mocked GDC API calls."""

    def _patch(self, responses: list[dict]):
        """Patch gdc_api.post to return successive responses from ``responses``."""
        mock = MagicMock(side_effect=responses)
        return patch("src.extract.case_selector.gdc_api.post", mock)

    def test_happy_path_one_project(self):
        expr_file = _make_file("e1", "case-chol", "TCGA-ZC-001-01", "uuid-e1", "Primary Tumor")
        meth_file = _make_file("m1", "case-chol", "TCGA-ZC-001-02", "uuid-m1", "Primary Tumor")
        var_file = {**_make_file("v1", "case-chol"), "file_name": "maf.maf.gz"}
        var_case_file = _make_file("v2", "case-chol", "TCGA-ZC-001-03", "uuid-v1")

        # Query order: expression, methylation, variation, per-case expression,
        #              per-case methylation, per-case variation (for aliquot map)
        responses = [
            _make_page([expr_file]),      # expression files
            _make_page([meth_file]),      # methylation files
            _make_page([var_file]),       # variation files
            _make_page([expr_file]),      # per-case expression
            _make_page([meth_file]),      # per-case methylation
            _make_page([var_case_file]),  # per-case variation (aliquot map)
        ]

        with self._patch(responses):
            sel = select_case("TCGA-CHOL", log=False)

        assert sel.case_id == "case-chol"
        assert sel.project_id == "TCGA-CHOL"
        assert len(sel.expression_files) == 1
        assert len(sel.methylation_files) == 1
        assert len(sel.variation_files) == 1

    def test_aliquot_map_populated(self):
        expr_file = _make_file("e1", "case-chol", "TCGA-ZC-001-01", "uuid-e1", "Primary Tumor")
        meth_file = _make_file("m1", "case-chol", "TCGA-ZC-001-02", "uuid-m1", "Primary Tumor")
        var_file = {**_make_file("v1", "case-chol"), "file_name": "maf.maf.gz"}
        var_case_file = _make_file("v2", "case-chol", "TCGA-ZC-001-03", "uuid-v1")

        responses = [
            _make_page([expr_file]),
            _make_page([meth_file]),
            _make_page([var_file]),
            _make_page([expr_file]),
            _make_page([meth_file]),
            _make_page([var_case_file]),
        ]
        with self._patch(responses):
            sel = select_case("TCGA-CHOL", log=False)

        # RNA aliquot from expression file is still present
        assert "TCGA-ZC-001-01" in sel.aliquot_map
        assert sel.aliquot_map["TCGA-ZC-001-01"] == "uuid-e1"
        # DNA aliquot from variation file is also present
        assert "TCGA-ZC-001-03" in sel.aliquot_map
        assert sel.aliquot_map["TCGA-ZC-001-03"] == "uuid-v1"

    def test_widens_to_fallback_when_chol_empty(self):
        expr_file = _make_file("e1", "case-brca", "TCGA-A1-001-01", "uuid-b1", "Primary Tumor")
        meth_file = _make_file("m1", "case-brca", "TCGA-A1-001-02", "uuid-b2", "Primary Tumor")
        var_file = {**_make_file("v1", "case-brca"), "file_name": "maf.maf.gz"}
        var_case_file = _make_file("v2", "case-brca", "TCGA-A1-001-03", "uuid-b3")

        responses = [
            _make_page([]),           # TCGA-CHOL expression (empty)
            _make_page([expr_file]),  # TCGA-BRCA expression
            _make_page([meth_file]),  # TCGA-BRCA methylation
            _make_page([var_file]),   # TCGA-BRCA variation
            _make_page([expr_file]),  # per-case expression
            _make_page([meth_file]),  # per-case methylation
            _make_page([var_case_file]),  # per-case variation (aliquot map)
        ]
        with self._patch(responses):
            sel = select_case("TCGA-CHOL", fallback_projects=["TCGA-BRCA"], log=False)

        assert sel.project_id == "TCGA-BRCA"
        assert sel.case_id == "case-brca"

    def test_raises_when_no_multi_omic_case(self):
        responses = [
            _make_page([]),  # TCGA-CHOL expression (empty)
        ]
        with self._patch(responses):
            with pytest.raises(RuntimeError, match="No multi-omic case found"):
                select_case("TCGA-CHOL", fallback_projects=[], log=False)

    def test_no_intersection_skips_project(self):
        # Expression case ≠ methylation case → no intersection
        expr_file = _make_file("e1", "case-a", sample_type="Primary Tumor")
        meth_file = _make_file("m1", "case-b", sample_type="Primary Tumor")
        var_file = {**_make_file("v1", "case-a"), "file_name": "maf.maf.gz"}

        # TCGA-CHOL has no intersection; TCGA-BRCA is not in fallback → RuntimeError
        responses = [
            _make_page([expr_file]),
            _make_page([meth_file]),
            _make_page([var_file]),
        ]
        with self._patch(responses):
            with pytest.raises(RuntimeError, match="No multi-omic case found"):
                select_case("TCGA-CHOL", fallback_projects=[], log=False)
