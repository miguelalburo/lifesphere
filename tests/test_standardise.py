"""Unit tests for Stage 1 standardisation (src/standardise).

Uses a tiny synthetic raw extract (no network) to assert the mapping contract:
grain preservation, prefix-stripping renames, linkage-column dropping,
Program/Project dedup, placeholder scrub, and edge referential integrity.
"""

import csv
from pathlib import Path

import pytest

from src.standardise.run import run

BASE = "TEST-XX"


def _write_tsv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(header)
        w.writerows(rows)


@pytest.fixture(scope="module")
def std_dir(tmp_path_factory) -> Path:
    """Build a minimal raw extract, standardise it, return the output dir."""
    raw = tmp_path_factory.mktemp("raw")
    out = tmp_path_factory.mktemp("std")

    # 2 cases in the SAME project/program (exercises dedup).
    _write_tsv(raw / f"{BASE}.subject.tsv",
        ["case_id", "submitter_id", "disease_type", "primary_site",
         "index_date", "index_date_type", "project_id", "project_name",
         "program_name", "demographic_sex_at_birth", "demographic_vital_status"],
        [["c1", "TCGA-01", "Adeno", "Breast", "Diagnosis", "", "TCGA-BRCA",
          "Breast Invasive Carcinoma", "TCGA", "Female", "Alive"],
         ["c2", "TCGA-02", "Adeno", "Breast", "Diagnosis", "", "TCGA-BRCA",
          "Breast Invasive Carcinoma", "TCGA", "[Not Available]", "Dead"]])

    # case c1 has TWO diagnoses (multiplicity); c2 has one.
    _write_tsv(raw / f"{BASE}.diagnosis.tsv",
        ["case_id", "case_submitter_id", "diagnosis_id", "diagnosis_submitter_id",
         "diagnosis_primary_diagnosis", "diagnosis_ajcc_pathologic_stage"],
        [["c1", "TCGA-01", "d1", "TCGA-01_d", "Carcinoma", "Stage II"],
         ["c1", "TCGA-01", "d2", "TCGA-01_d2", "Carcinoma", "[Not Evaluated]"],
         ["c2", "TCGA-02", "d3", "TCGA-02_d", "Carcinoma", "Stage III"]])

    _write_tsv(raw / f"{BASE}.treatment.tsv",
        ["case_id", "case_submitter_id", "diagnosis_id", "treatment_id",
         "treatment_submitter_id", "treatment_treatment_type"],
        [["c1", "TCGA-01", "d1", "t1", "TCGA-01_t", "Pharmaceutical"],
         ["c1", "TCGA-01", "d1", "t2", "TCGA-01_t2", "Radiation"]])

    # molecular_test nesting: one under a diagnosis, one under a follow_up.
    _write_tsv(raw / f"{BASE}.follow_up.tsv",
        ["case_id", "case_submitter_id", "follow_up_id", "follow_up_submitter_id",
         "follow_up_days_to_follow_up"],
        [["c1", "TCGA-01", "f1", "TCGA-01_f", "100"]])
    _write_tsv(raw / f"{BASE}.molecular_test.tsv",
        ["case_id", "case_submitter_id", "parent_entity", "parent_id",
         "molecular_test_id", "molecular_test_submitter_id", "molecular_test_gene_symbol"],
        [["c1", "TCGA-01", "diagnosis", "d1", "m1", "TCGA-01_m", "ERBB2"],
         ["c1", "TCGA-01", "follow_up", "f1", "m2", "TCGA-01_m2", "ESR1"]])

    _write_tsv(raw / f"{BASE}.sample.tsv",
        ["case_id", "case_submitter_id", "sample_id", "sample_submitter_id",
         "sample_sample_type", "sample_tissue_type"],
        [["c1", "TCGA-01", "s1", "TCGA-01_s", "Primary Tumor", "Tumor"],
         ["c2", "TCGA-02", "s2", "TCGA-02_s", "Primary Tumor", "Tumor"]])

    run(raw, out)
    return out


def _read(path: Path) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


def _node(std: Path, label: str) -> list[dict]:
    return _read(std / "nodes" / f"{label}.csv")


def _edge(std: Path, label: str) -> list[dict]:
    return _read(std / "edges" / f"{label}.csv")


def test_grain_preserved(std_dir):
    assert len(_node(std_dir, "Subject")) == 2
    assert len(_node(std_dir, "Diagnosis")) == 3        # multiplicity kept
    assert len(_node(std_dir, "Treatment")) == 2


def test_program_project_dedup(std_dir):
    assert len(_node(std_dir, "Program")) == 1
    assert len(_node(std_dir, "Project")) == 1
    assert len(_edge(std_dir, "HAS_PROJECT")) == 1


def test_demographic_folded_and_renamed(std_dir):
    header = list(_node(std_dir, "Subject")[0].keys())
    # demographic_ prefix stripped, project/program columns dropped
    assert "sex_at_birth" in header and "vital_status" in header
    assert not any(h.startswith("demographic_") for h in header)
    assert "project_id" not in header and "program_name" not in header


def test_child_prefix_stripped(std_dir):
    header = list(_node(std_dir, "Diagnosis")[0].keys())
    assert "ajcc_pathologic_stage" in header      # was diagnosis_ajcc_pathologic_stage
    assert "case_id" not in header                 # linkage column dropped
    assert header[0] == "id"


def test_placeholder_scrubbed(std_dir):
    subj = {r["id"]: r for r in _node(std_dir, "Subject")}
    assert subj["c2"]["sex_at_birth"] == ""        # "[Not Available]" -> ""
    diag = {r["id"]: r for r in _node(std_dir, "Diagnosis")}
    assert diag["d2"]["ajcc_pathologic_stage"] == ""  # "[Not Evaluated]" -> ""


def test_edge_referential_integrity(std_dir):
    subj_ids = {r["id"] for r in _node(std_dir, "Subject")}
    diag_ids = {r["id"] for r in _node(std_dir, "Diagnosis")}
    hd = _edge(std_dir, "HAS_DIAGNOSIS")
    assert {r["source_id"] for r in hd} <= subj_ids
    assert {r["target_id"] for r in hd} == diag_ids


def test_molecular_test_routing(std_dir):
    """parent_id resolves to the diagnosis OR follow_up it nested under."""
    diag_ids = {r["id"] for r in _node(std_dir, "Diagnosis")}
    fu_ids = {r["id"] for r in _node(std_dir, "FollowUp")}
    parents = {r["source_id"] for r in _edge(std_dir, "HAS_MOLECULAR_TEST")}
    assert parents == {"d1", "f1"}
    assert parents <= (diag_ids | fu_ids)
