"""
Integration test for scripts/download_gdc_clinical.py.

Requires internet access to the GDC API (~10-30 s).
Uses TCGA-DLBC (~48 cases) to keep runtime short. TCGA-DLBC cases have multiple
follow_ups, treatments and aliquots, so it exercises 1:many preservation.
"""

import csv
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "download_gdc_clinical.py"
TEST_PROJECT = "TCGA-DLBC"


def _run_script(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True, text=True,
    )


def _read(path: Path) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f, delimiter="\t"))


@pytest.fixture(scope="module")
def download_dir(tmp_path_factory) -> Path:
    """Download TCGA-DLBC once for the whole module."""
    out = tmp_path_factory.mktemp("dlbc")
    result = _run_script(["--project", TEST_PROJECT, str(out)])
    assert result.returncode == 0, f"Script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    return out


def _path(out: Path, entity: str) -> Path:
    return out / f"{TEST_PROJECT}.{entity}.tsv"


def test_all_entity_tsvs_created(download_dir):
    from src.extract.entities import EMITTERS
    for emitter in EMITTERS:
        p = _path(download_dir, emitter.NAME)
        assert p.exists(), f"Expected output TSV not found: {p.name}"


def test_case_tsv_has_rows(download_dir):
    rows = _read(_path(download_dir, "case"))
    assert len(rows) > 0, "case TSV has no data rows"


def test_case_id_is_unique(download_dir):
    rows = _read(_path(download_dir, "case"))
    ids = [r["case_id"] for r in rows]
    assert len(ids) == len(set(ids)), "case_id is not unique in case TSV"


@pytest.mark.parametrize("entity", [
    "case", "diagnosis", "treatment", "pathology_detail", "follow_up",
    "molecular_test", "exposure", "family_history", "other_clinical_attribute",
    "sample", "aliquot", "file",
])
def test_columns_match_emitter(download_dir, entity):
    """Each TSV's header must exactly match its emitter's declared COLUMNS."""
    from src.extract.entities import EMITTERS
    emitter = next(e for e in EMITTERS if e.NAME == entity)
    with open(_path(download_dir, entity)) as f:
        header = next(csv.reader(f, delimiter="\t"))
    assert header == emitter.COLUMNS, (
        f"{entity}: header does not match declared COLUMNS\n"
        f"  header : {header}\n  columns: {emitter.COLUMNS}"
    )


def test_child_rows_link_back_to_case(download_dir):
    """Every child-table case_id must exist in the case table."""
    case_ids = {r["case_id"] for r in _read(_path(download_dir, "case"))}
    for entity in ("diagnosis", "treatment", "follow_up", "sample", "aliquot", "file"):
        rows = _read(_path(download_dir, entity))
        orphans = {r["case_id"] for r in rows} - case_ids
        assert not orphans, f"{entity}: {len(orphans)} case_id(s) not present in case TSV"


def test_multiplicity_preserved(download_dir):
    """The whole point of the refactor: 1:many entities must not be collapsed."""
    n_cases = len(_read(_path(download_dir, "case")))
    n_follow_ups = len(_read(_path(download_dir, "follow_up")))
    n_treatments = len(_read(_path(download_dir, "treatment")))
    n_samples = len(_read(_path(download_dir, "sample")))
    n_aliquots = len(_read(_path(download_dir, "aliquot")))

    # TCGA-DLBC cases have many follow_ups and treatments each.
    assert n_follow_ups > n_cases, (
        f"follow_up rows ({n_follow_ups}) not > cases ({n_cases}) — multiplicity lost"
    )
    assert n_treatments > n_cases, (
        f"treatment rows ({n_treatments}) not > cases ({n_cases}) — multiplicity lost"
    )
    assert n_aliquots > n_samples > 0, (
        f"expected aliquots ({n_aliquots}) > samples ({n_samples}) > 0"
    )


def test_treatments_link_to_diagnoses(download_dir):
    """treatment.diagnosis_id must reference a diagnosis in the diagnosis TSV."""
    diag_ids = {r["diagnosis_id"] for r in _read(_path(download_dir, "diagnosis"))}
    tx = _read(_path(download_dir, "treatment"))
    assert tx, "treatment TSV is empty"
    orphans = {r["diagnosis_id"] for r in tx} - diag_ids
    assert not orphans, f"{len(orphans)} treatment diagnosis_id(s) not present in diagnosis TSV"


def test_mutual_exclusion_project_and_cases(tmp_path):
    result = _run_script(["--project", TEST_PROJECT, "--cases", "some-uuid", str(tmp_path)])
    assert result.returncode != 0, "Script should fail when both --project and --cases are given"


def test_requires_project_or_cases(tmp_path):
    result = _run_script([str(tmp_path)])
    assert result.returncode != 0, "Script should fail when neither --project nor --cases is given"
