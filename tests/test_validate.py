"""Offline referential-integrity validation against the real schema."""

from __future__ import annotations

from pathlib import Path

from conftest import write

from src.validate import validate


def _clean(root: Path) -> Path:
    ds = root / "STD" / "MINI"
    write(ds / "nodes" / "Subject.csv", "subjectId,sexAtBirth\nTCGA-1,female\n")
    write(ds / "nodes" / "Sample.csv", "sampleId,subjectId\nS1,TCGA-1\n")
    write(
        ds / "edges" / "PROVIDED_SAMPLE.csv",
        "startId,endId,startLabel,endLabel,derivationMethod\n"
        "TCGA-1,S1,Subject,Sample,Resection\n",
    )
    return root / "STD"


def test_clean_dataset_has_no_problems(tmp_path):
    report = validate("MINI", standardised_root=_clean(tmp_path))
    assert report["problems"] == []
    assert report["node_ids"] == 2
    assert report["edges"] == 1


def test_dangling_edge_is_flagged(tmp_path):
    std_root = _clean(tmp_path)
    # add an edge pointing at a non-existent Sample
    write(
        std_root / "MINI" / "edges" / "PROVIDED_SAMPLE.csv",
        "startId,endId,startLabel,endLabel,derivationMethod\n"
        "TCGA-1,S1,Subject,Sample,Resection\n"
        "TCGA-1,GHOST,Subject,Sample,Resection\n",
    )
    report = validate("MINI", standardised_root=std_root)
    assert any("dangling endId 'GHOST'" in p for p in report["problems"])


def test_duplicate_id_is_flagged(tmp_path):
    std_root = _clean(tmp_path)
    write(
        std_root / "MINI" / "nodes" / "Subject.csv",
        "subjectId,sexAtBirth\nTCGA-1,female\nTCGA-1,male\n",
    )
    report = validate("MINI", standardised_root=std_root)
    assert any("duplicate id" in p for p in report["problems"])
