"""Load planning (dry-run) and subtype grouping against the real schema."""

from __future__ import annotations

from pathlib import Path

from conftest import write

from src.load import load
from src.load.run import _read_node_groups


def _standardised(root: Path) -> Path:
    ds = root / "STD" / "MINI"
    write(ds / "nodes" / "Subject.csv", "subjectId,sexAtBirth\nTCGA-1,female\n")
    write(ds / "nodes" / "Sample.csv", "sampleId,subjectId\nS1,TCGA-1\n")
    write(
        ds / "nodes" / "Intervention.csv",
        "interventionId,interventionType,_subtypeLabel\n"
        "I1,drug,Drug\nI2,radiation,Radiation\nI3,other,\n",
    )
    write(
        ds / "edges" / "PROVIDED_SAMPLE.csv",
        "startId,endId,startLabel,endLabel,derivationMethod\n"
        "TCGA-1,S1,Subject,Sample,Resection\n",
    )
    write(
        ds / "edges" / "UNDERWENT_INTERVENTION.csv",
        "startId,endId,startLabel,endLabel\nS1,I1,Sample,Intervention\n",
    )
    return root / "STD"


def test_dry_run_plan(tmp_path):
    std_root = _standardised(tmp_path)
    plan = load("MINI", standardised_root=std_root, dry_run=True, log=False)

    assert len(plan["constraints"]) == 3  # Subject, Sample, Intervention
    assert plan["nodes"] == {"Subject": 1, "Sample": 1, "Intervention": 3}
    assert plan["edges"] == {"PROVIDED_SAMPLE": 1, "UNDERWENT_INTERVENTION": 1}


def test_subtype_grouping(tmp_path):
    std_root = _standardised(tmp_path)
    path = std_root / "MINI" / "nodes" / "Intervention.csv"
    groups = _read_node_groups(path, "interventionId", "_subtypeLabel", ("Drug", "Radiation"))

    assert set(groups) == {("Drug",), ("Radiation",), ()}
    # the base-label group (I3) carries no extra labels and drops the subtype col
    (base_row,) = groups[()]
    assert base_row == {"id": "I3", "props": {"interventionType": "other"}}
