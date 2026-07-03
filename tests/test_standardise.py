"""Unit tests for Stage 1 standardisation (src/standardise).

Uses a tiny synthetic raw extract (no network) to assert the mapping contract:
grain preservation, prefix-stripping renames, linkage-column dropping,
Program/Project dedup, placeholder scrub, and edge referential integrity.
"""

import csv
import json
import shutil
from pathlib import Path

import pytest

from src.standardise.aliases import canonicalise, load_alias_map
from src.standardise.run import run

BASE = "TEST-XX"
_REAL_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "config" / "schemas"


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

    # Program and Project are now dedicated extract files (not derived from subject).
    _write_tsv(raw / f"{BASE}.program.tsv",
        ["program_name"],
        [["TCGA"]])
    _write_tsv(raw / f"{BASE}.project.tsv",
        ["project_id"],
        [["TCGA-BRCA"]])

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
    # demographic_ prefix stripped, project/program columns dropped, output camelCased
    assert "sexAtBirth" in header and "vitalStatus" in header
    assert not any(h.startswith("demographic") for h in header)
    assert "projectId" not in header and "programName" not in header


def test_child_prefix_stripped(std_dir):
    header = list(_node(std_dir, "Diagnosis")[0].keys())
    assert "ajccPathologicStage" in header      # was diagnosis_ajcc_pathologic_stage
    assert "caseId" not in header                 # linkage column dropped
    assert header[0] == "id"


def test_placeholder_scrubbed(std_dir):
    subj = {r["id"]: r for r in _node(std_dir, "Subject")}
    assert subj["c2"]["sexAtBirth"] == ""        # "[Not Available]" -> ""
    diag = {r["id"]: r for r in _node(std_dir, "Diagnosis")}
    assert diag["d2"]["ajccPathologicStage"] == ""  # "[Not Evaluated]" -> ""


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


# --------------------------------------------------------------------------- #
# Column-alias detection                                                       #
# --------------------------------------------------------------------------- #

def test_load_alias_map_missing_file(tmp_path):
    """A schema dir without aliases.json yields an empty (no-op) map."""
    assert load_alias_map(tmp_path) == {}


def test_load_alias_map_normalises_and_inverts(tmp_path):
    (tmp_path / "aliases.json").write_text(
        json.dumps({"case_id": ["BCR_Patient_UUID", " case_uuid "]})
    )
    amap = load_alias_map(tmp_path)
    assert amap == {"bcr_patient_uuid": "case_id", "case_uuid": "case_id"}


def test_canonicalise_renames_known_leaves_unknown():
    amap = {"bcr_patient_uuid": "case_id"}
    assert canonicalise(["BCR_Patient_UUID", "other"], amap) == ["case_id", "other"]


@pytest.fixture(scope="module")
def aliased_schema_dir(tmp_path_factory) -> Path:
    """Real schemas plus a custom aliases.json for an alternately-named source."""
    d = tmp_path_factory.mktemp("schemas")
    for fname in ("entities.json", "edges.json", "placeholders.json"):
        shutil.copy(_REAL_SCHEMA_DIR / fname, d / fname)
    (d / "aliases.json").write_text(
        json.dumps({
            "case_id": ["bcr_patient_uuid"],
            "project_id": ["project.project_id"],
            "program_name": ["program.name"],
        })
    )
    return d


def test_alias_renaming_end_to_end(tmp_path, aliased_schema_dir):
    """A subject file using aliased headers still matches schemas and links up."""
    raw = tmp_path / "raw"
    raw.mkdir()
    out = tmp_path / "std"
    _write_tsv(raw / f"{BASE}.subject.tsv",
        ["bcr_patient_uuid", "submitter_id", "disease_type", "primary_site",
         "project.project_id", "project_name", "program.name",
         "demographic_vital_status"],
        [["c1", "TCGA-01", "Adeno", "Breast", "TCGA-BRCA",
          "Breast Invasive Carcinoma", "TCGA", "Alive"]])

    # Program and Project are now dedicated files; aliased columns still apply.
    _write_tsv(raw / f"{BASE}.program.tsv",
        ["program.name"],
        [["TCGA"]])
    _write_tsv(raw / f"{BASE}.project.tsv",
        ["project.project_id"],
        [["TCGA-BRCA"]])

    run(raw, out, aliased_schema_dir)

    # Subject node keyed by the canonicalised case_id, not the alias.
    subjects = _read(out / "nodes" / "Subject.csv")
    assert [s["id"] for s in subjects] == ["c1"]
    # Program/Project resolved from aliased columns.
    assert [p["id"] for p in _read(out / "nodes" / "Program.csv")] == ["TCGA"]
    assert [p["id"] for p in _read(out / "nodes" / "Project.csv")] == ["TCGA-BRCA"]
    # Edges built off the canonical FK names.
    enrolls = _read(out / "edges" / "ENROLLS.csv")
    assert enrolls == [{"source_id": "TCGA-BRCA", "target_id": "c1"}]


# --------------------------------------------------------------------------- #
# Edge properties                                                             #
# --------------------------------------------------------------------------- #

def test_edge_props_emitted_scrubbed_and_missing_dropped(tmp_path):
    """Declared edge props are emitted (placeholder-scrubbed); absent ones dropped."""
    from src.standardise.run import _make_clean, standardise_edge

    raw = tmp_path / "in.tsv"
    _write_tsv(raw,
        ["sample_id", "cell_set_id", "contributed_cell_count", "fraction_of_sample_cells"],
        [["s1", "cs1", "120", "0.18"],
         ["s2", "cs1", "[Not Available]", "0.07"]])
    (tmp_path / "edges").mkdir()

    schema = {
        "label": "CONTRIBUTES_TO",
        "source_id": "sample_id",
        "target_id": "cell_set_id",
        # 'missing_col' is declared but not in the file -> dropped from output
        "props": ["contributed_cell_count", "fraction_of_sample_cells", "missing_col"],
        "dedup": False,
    }
    clean = _make_clean(frozenset({"[Not Available]"}))
    n = standardise_edge(schema, raw, tmp_path, clean)
    assert n == 2

    rows = _read(tmp_path / "edges" / "CONTRIBUTES_TO.csv")
    assert list(rows[0].keys()) == [
        "source_id", "target_id", "contributedCellCount", "fractionOfSampleCells"
    ]
    assert rows[0]["contributedCellCount"] == "120"
    assert rows[1]["contributedCellCount"] == ""     # placeholder scrubbed to empty


def test_plain_edge_stays_two_column(tmp_path):
    """An edge schema with no props declared emits exactly source_id,target_id."""
    from src.standardise.run import _make_clean, standardise_edge

    raw = tmp_path / "in.tsv"
    _write_tsv(raw, ["case_id", "diagnosis_id", "extra"], [["c1", "d1", "ignored"]])
    (tmp_path / "edges").mkdir()
    schema = {"label": "HAS_DIAGNOSIS", "source_id": "case_id",
              "target_id": "diagnosis_id", "dedup": False}
    standardise_edge(schema, raw, tmp_path, _make_clean(frozenset()))
    rows = _read(tmp_path / "edges" / "HAS_DIAGNOSIS.csv")
    assert list(rows[0].keys()) == ["source_id", "target_id"]
