"""
Integration test for scripts/download_gdc_clinical.py.

Requires internet access to the GDC API (~10-30 s).
Uses TCGA-DLBC (~48 cases) to keep runtime short.
"""

import csv
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "download_gdc_clinical.py"
TEST_PROJECT = "TCGA-DLBC"


def _expected_columns() -> set[str]:
    from src.extract.cases import flatten
    return set(flatten({}).keys())


def _run_script(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True, text=True,
    )


def test_download_project_creates_tsv(tmp_path):
    result = _run_script(["--project", TEST_PROJECT, str(tmp_path)])
    assert result.returncode == 0, f"Script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    tsv_path = tmp_path / f"{TEST_PROJECT}.metadata.tsv"
    assert tsv_path.exists(), f"Expected output TSV not found: {tsv_path}"


def test_download_project_has_rows(tmp_path):
    _run_script(["--project", TEST_PROJECT, str(tmp_path)])

    tsv_path = tmp_path / f"{TEST_PROJECT}.metadata.tsv"
    with open(tsv_path) as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    assert len(rows) > 0, "Output TSV has no data rows"


def test_download_project_columns_match_data_dict(tmp_path):
    """All columns derived from gdc_data_dict.json must be present in the output TSV."""
    _run_script(["--project", TEST_PROJECT, str(tmp_path)])

    tsv_path = tmp_path / f"{TEST_PROJECT}.metadata.tsv"
    with open(tsv_path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        actual_cols = set(reader.fieldnames)

    missing = _expected_columns() - actual_cols
    assert not missing, (
        f"{len(missing)} expected column(s) missing from TSV:\n"
        + "\n".join(f"  - {c}" for c in sorted(missing))
    )


def test_download_project_no_extra_columns(tmp_path):
    """TSV must not contain columns outside the defined schema."""
    _run_script(["--project", TEST_PROJECT, str(tmp_path)])

    tsv_path = tmp_path / f"{TEST_PROJECT}.metadata.tsv"
    with open(tsv_path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        actual_cols = set(reader.fieldnames)

    extra = actual_cols - _expected_columns()
    assert not extra, (
        f"{len(extra)} unexpected column(s) in TSV:\n"
        + "\n".join(f"  + {c}" for c in sorted(extra))
    )


def test_mutual_exclusion_project_and_cases(tmp_path):
    result = _run_script(["--project", TEST_PROJECT, "--cases", "some-uuid", str(tmp_path)])
    assert result.returncode != 0, "Script should fail when both --project and --cases are given"


def test_requires_project_or_cases(tmp_path):
    result = _run_script([str(tmp_path)])
    assert result.returncode != 0, "Script should fail when neither --project nor --cases is given"
