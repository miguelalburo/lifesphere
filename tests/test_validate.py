"""Unit tests for the offline referential-integrity validator (src/load/validate)."""

import csv
from pathlib import Path

from src.load.validate import validate


def _write(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _std_dir(tmp_path: Path) -> Path:
    # Nodes: Subject c1,c2 ; Diagnosis d1,d2
    _write(tmp_path / "nodes" / "Subject.csv", ["id", "vital_status"],
           [["c1", "Alive"], ["c2", "Dead"]])
    _write(tmp_path / "nodes" / "Diagnosis.csv", ["id", "stage"],
           [["d1", "II"], ["d2", "III"]])
    return tmp_path


def test_clean_graph_has_no_dangling(tmp_path):
    std = _std_dir(tmp_path)
    _write(std / "edges" / "HAS_DIAGNOSIS.csv", ["source_id", "target_id"],
           [["c1", "d1"], ["c2", "d2"]])

    reports = {r.label: r for r in validate(std)}
    rep = reports["HAS_DIAGNOSIS"]
    assert rep.ok
    assert rep.total == 2
    assert rep.dangling_source == 0 and rep.dangling_target == 0


def test_dangling_endpoints_detected_and_typed(tmp_path):
    std = _std_dir(tmp_path)
    # c9 (bad source) and d9 (bad target) reference nonexistent nodes.
    _write(std / "edges" / "HAS_DIAGNOSIS.csv", ["source_id", "target_id"],
           [["c1", "d1"], ["c9", "d2"], ["c2", "d9"]])

    rep = {r.label: r for r in validate(std)}["HAS_DIAGNOSIS"]
    assert not rep.ok
    assert rep.total == 3
    assert rep.dangling_source == 1 and "c9" in rep.src_examples
    assert rep.dangling_target == 1 and "d9" in rep.tgt_examples


def test_typed_endpoint_rejects_right_id_wrong_label(tmp_path):
    """A Subject id used where a Diagnosis is expected counts as dangling."""
    std = _std_dir(tmp_path)
    # target 'c1' exists as a Subject but HAS_DIAGNOSIS.target must be a Diagnosis.
    _write(std / "edges" / "HAS_DIAGNOSIS.csv", ["source_id", "target_id"],
           [["c1", "c1"]])

    rep = {r.label: r for r in validate(std)}["HAS_DIAGNOSIS"]
    assert rep.dangling_target == 1
