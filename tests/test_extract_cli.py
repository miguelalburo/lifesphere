"""CLI layer-flag framework — tests for __main__.py.

Covers: --clinical runs extraction; no-layer-flag exits non-zero;
--clinical composes with --program; --expression, --methylation, and
--variation all wired; --omics composes all three layers.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, call
from pathlib import Path

from src.extract.__main__ import main


# ---------------------------------------------------------------------------
# --clinical with project_id
# ---------------------------------------------------------------------------

class TestClinicalProject:
    def test_clinical_returns_zero(self, tmp_path):
        with patch("src.extract.__main__.extract") as m:
            rc = main(["TCGA-CHOL", "--clinical", "--out", str(tmp_path)])
        assert rc == 0

    def test_clinical_calls_extract(self, tmp_path):
        with patch("src.extract.__main__.extract") as m:
            main(["TCGA-CHOL", "--clinical", "--out", str(tmp_path)])
        m.assert_called_once_with("TCGA-CHOL", tmp_path)

    def test_clinical_default_out_is_data_raw(self):
        with patch("src.extract.__main__.extract") as m, \
             patch("src.extract.__main__.DATA_RAW", Path("/fake/raw")):
            main(["TCGA-CHOL", "--clinical"])
        m.assert_called_once_with("TCGA-CHOL", Path("/fake/raw/TCGA-CHOL"))


# ---------------------------------------------------------------------------
# --clinical with --program
# ---------------------------------------------------------------------------

class TestClinicalProgram:
    def test_clinical_program_returns_zero(self, tmp_path):
        with patch("src.extract.__main__.extract_program") as m:
            rc = main(["--program", "TCGA", "--clinical", "--out", str(tmp_path)])
        assert rc == 0

    def test_clinical_program_calls_extract_program(self, tmp_path):
        with patch("src.extract.__main__.extract_program") as m:
            main(["--program", "TCGA", "--clinical", "--out", str(tmp_path)])
        m.assert_called_once_with("TCGA", tmp_path)


# ---------------------------------------------------------------------------
# No layer flag → non-zero exit with usage message
# ---------------------------------------------------------------------------

class TestNoLayerFlag:
    def test_no_layer_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc:
            main(["TCGA-CHOL"])
        assert exc.value.code != 0

    def test_no_layer_program_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc:
            main(["--program", "TCGA"])
        assert exc.value.code != 0

    def test_error_message_mentions_layer_flag(self, capsys):
        with pytest.raises(SystemExit):
            main(["TCGA-CHOL"])
        captured = capsys.readouterr()
        assert "--clinical" in captured.err or "layer" in captured.err.lower()


# ---------------------------------------------------------------------------
# --variation wired
# ---------------------------------------------------------------------------

class TestVariationWired:
    def test_variation_returns_zero(self, tmp_path):
        with patch("src.extract.omics.variation.extract_variation"):
            rc = main(["TCGA-CHOL", "--variation", "--out", str(tmp_path)])
        assert rc == 0

    def test_variation_calls_extract_variation(self, tmp_path):
        with patch("src.extract.omics.variation.extract_variation") as m:
            main(["TCGA-CHOL", "--variation", "--out", str(tmp_path)])
        m.assert_called_once_with("TCGA-CHOL", tmp_path)

    def test_variation_with_program(self, tmp_path):
        with patch("src.extract.omics.variation.extract_variation") as m:
            rc = main(["--program", "TCGA", "--variation", "--out", str(tmp_path)])
        assert rc == 0
        m.assert_called_once_with("TCGA", tmp_path)

    def test_omics_flag_calls_all_three_layers(self, tmp_path):
        with (
            patch("src.extract.omics.expression.extract_expression") as me,
            patch("src.extract.omics.methylation.extract_methylation") as mm,
            patch("src.extract.omics.variation.extract_variation") as mv,
        ):
            rc = main(["TCGA-CHOL", "--omics", "--out", str(tmp_path)])
        assert rc == 0
        me.assert_called_once_with("TCGA-CHOL", tmp_path)
        mm.assert_called_once_with("TCGA-CHOL", tmp_path)
        mv.assert_called_once_with("TCGA-CHOL", tmp_path)

    def test_omics_composes_with_program(self, tmp_path):
        with (
            patch("src.extract.omics.expression.extract_expression") as me,
            patch("src.extract.omics.methylation.extract_methylation") as mm,
            patch("src.extract.omics.variation.extract_variation") as mv,
        ):
            rc = main(["--program", "TCGA", "--omics", "--out", str(tmp_path)])
        assert rc == 0
        me.assert_called_once_with("TCGA", tmp_path)
        mm.assert_called_once_with("TCGA", tmp_path)
        mv.assert_called_once_with("TCGA", tmp_path)


class TestMethylationWired:
    def test_methylation_returns_zero(self, tmp_path):
        with patch("src.extract.omics.methylation.extract_methylation"):
            rc = main(["TCGA-CHOL", "--methylation", "--out", str(tmp_path)])
        assert rc == 0

    def test_methylation_calls_extract_methylation(self, tmp_path):
        with patch("src.extract.omics.methylation.extract_methylation") as m:
            main(["TCGA-CHOL", "--methylation", "--out", str(tmp_path)])
        m.assert_called_once_with("TCGA-CHOL", tmp_path)

    def test_methylation_with_program(self, tmp_path):
        with patch("src.extract.omics.methylation.extract_methylation") as m:
            rc = main(["--program", "TCGA", "--methylation", "--out", str(tmp_path)])
        assert rc == 0
        m.assert_called_once_with("TCGA", tmp_path)

    def test_clinical_plus_methylation_both_run(self, tmp_path):
        with (
            patch("src.extract.__main__.extract") as mc,
            patch("src.extract.omics.methylation.extract_methylation") as mm,
        ):
            rc = main(["TCGA-CHOL", "--clinical", "--methylation", "--out", str(tmp_path)])
        assert rc == 0
        mc.assert_called_once()
        mm.assert_called_once()


class TestExpressionWired:
    def test_expression_returns_zero(self, tmp_path):
        with patch("src.extract.omics.expression.extract_expression"):
            rc = main(["TCGA-CHOL", "--expression", "--out", str(tmp_path)])
        assert rc == 0

    def test_expression_calls_extract_expression(self, tmp_path):
        with patch("src.extract.omics.expression.extract_expression") as m:
            main(["TCGA-CHOL", "--expression", "--out", str(tmp_path)])
        m.assert_called_once_with("TCGA-CHOL", tmp_path)

    def test_expression_with_program(self, tmp_path):
        with patch("src.extract.omics.expression.extract_expression") as m:
            rc = main(["--program", "TCGA", "--expression", "--out", str(tmp_path)])
        assert rc == 0
        m.assert_called_once_with("TCGA", tmp_path)

    def test_clinical_plus_expression_both_run(self, tmp_path):
        with (
            patch("src.extract.__main__.extract") as mc,
            patch("src.extract.omics.expression.extract_expression") as me,
        ):
            rc = main(["TCGA-CHOL", "--clinical", "--expression", "--out", str(tmp_path)])
        assert rc == 0
        mc.assert_called_once()
        me.assert_called_once()
