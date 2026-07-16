"""End-to-end standardise on a tiny self-contained fixture."""

from __future__ import annotations

import csv
from pathlib import Path

from src.standardise import standardise


def _read(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    return rows[0], rows[1:]


def test_standardise_nodes_edges(mini_config, mini_raw, tmp_path):
    out_root = tmp_path / "std"
    summary = standardise(
        "MINI", "test",
        raw_root=mini_raw, out_root=out_root, config_dir=mini_config, log=False,
    )
    out = out_root / "MINI"

    # dedup + placeholder scrub + explicit and auto camel mapping
    header, rows = _read(out / "nodes" / "Subject.csv")
    assert header == ["subjectId", "sexAtBirth", "subjectType"]
    assert rows == [["c1", "female", "patient"], ["c2", "", "patient"]]

    header, rows = _read(out / "nodes" / "Sample.csv")
    assert header == ["sampleId", "subjectId", "sampleClass"]
    assert rows == [["s1", "c1", "Primary Tumor"], ["s2", "c2", ""]]

    # subtype column emitted for the multi-labelled node
    header, rows = _read(out / "nodes" / "Widget.csv")
    assert header == ["widgetId", "color", "_subtypeLabel"]
    assert rows == [["w1", "red", "Big"], ["w2", "blue", "Huge"]]

    # edge with resolved endpoints + startLabel/endLabel
    header, rows = _read(out / "edges" / "PROVIDED_SAMPLE.csv")
    assert header == ["startId", "endId", "startLabel", "endLabel", "derivationMethod"]
    assert rows == [
        ["c1", "s1", "Subject", "Sample", "Resection"],
        ["c2", "s2", "Subject", "Sample", "Biopsy"],
    ]

    assert summary["nodes"] == {"Subject": 2, "Sample": 2, "Widget": 2}
    assert summary["edges"] == {"PROVIDED_SAMPLE": 2}


def test_standardise_skips_missing_and_unbound(mini_config, mini_raw, tmp_path):
    summary = standardise(
        "MINI", "test",
        raw_root=mini_raw, out_root=tmp_path / "std", config_dir=mini_config, log=False,
    )
    # Ghost maps to an absent file -> skipped, never raises
    assert "Ghost" in summary["skipped"]
    assert not (tmp_path / "std" / "MINI" / "nodes" / "Ghost.csv").exists()
