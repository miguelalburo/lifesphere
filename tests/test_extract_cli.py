"""CLI layer-flag framework — tests for __main__.py.

Covers: --clinical runs extraction; no-layer-flag exits non-zero;
--clinical composes with --program; omics stubs fail with 'not yet wired'.
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
# Omics stubs — accepted, fail with "not yet wired"
# ---------------------------------------------------------------------------

class TestOmicsStubs:
    @pytest.mark.parametrize("flag", ["--expression", "--methylation", "--variation"])
    def test_omics_layer_exits_nonzero(self, flag, tmp_path):
        rc = main(["TCGA-CHOL", flag, "--out", str(tmp_path)])
        assert rc != 0

    @pytest.mark.parametrize("flag", ["--expression", "--methylation", "--variation"])
    def test_omics_layer_prints_not_yet_wired(self, flag, tmp_path, capsys):
        main(["TCGA-CHOL", flag, "--out", str(tmp_path)])
        captured = capsys.readouterr()
        assert "not yet wired" in captured.err.lower()

    def test_omics_flag_exits_nonzero(self, tmp_path):
        rc = main(["TCGA-CHOL", "--omics", "--out", str(tmp_path)])
        assert rc != 0

    def test_omics_flag_prints_not_yet_wired(self, tmp_path, capsys):
        main(["TCGA-CHOL", "--omics", "--out", str(tmp_path)])
        captured = capsys.readouterr()
        assert "not yet wired" in captured.err.lower()

    def test_omics_composes_with_program(self, tmp_path, capsys):
        rc = main(["--program", "TCGA", "--omics", "--out", str(tmp_path)])
        assert rc != 0
        assert "not yet wired" in capsys.readouterr().err.lower()

    def test_omics_reports_all_three_layers(self, tmp_path, capsys):
        main(["TCGA-CHOL", "--omics", "--out", str(tmp_path)])
        err = capsys.readouterr().err
        for layer in ("expression", "methylation", "variation"):
            assert layer in err

    def test_clinical_plus_omics_does_not_run_clinical(self, tmp_path):
        with patch("src.extract.__main__.extract") as m:
            rc = main(["TCGA-CHOL", "--clinical", "--expression", "--out", str(tmp_path)])
        assert rc != 0
        m.assert_not_called()
