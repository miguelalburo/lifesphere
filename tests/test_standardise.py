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


def test_report_values_flag_surfaces_samples(mini_config, mini_raw):
    from src.standardise.run import report
    rep = report("MINI", "test", raw_root=mini_raw, config_dir=mini_config, values=True)
    # Sample node: method column is unused (it's the edge's column, not Sample's property)
    sample = rep["nodes"]["Sample"]
    assert len(sample["unused"]) > 0
    entry = sample["unused"][0]
    assert isinstance(entry, dict)
    assert entry["column"] == "method"
    assert any(v in entry["samples"] for v in ("Resection", "Biopsy"))


def test_report_no_values_flag_returns_strings(mini_config, mini_raw):
    from src.standardise.run import report
    rep = report("MINI", "test", raw_root=mini_raw, config_dir=mini_config, values=False)
    sample = rep["nodes"]["Sample"]
    assert len(sample["unused"]) > 0
    assert isinstance(sample["unused"][0], str)


def test_format_report_renders_samples(mini_config, mini_raw):
    from src.standardise.run import format_report, report
    rep = report("MINI", "test", raw_root=mini_raw, config_dir=mini_config, values=True)
    text = format_report(rep)
    assert "method" in text
    assert "Resection" in text or "Biopsy" in text


def test_format_report_no_values_unchanged(mini_config, mini_raw):
    from src.standardise.run import format_report, report
    rep = report("MINI", "test", raw_root=mini_raw, config_dir=mini_config, values=False)
    text = format_report(rep)
    assert "method" in text
    # no sample values should appear (bracket notation is only added with --values)
    assert "[Resection" not in text and "[Biopsy" not in text


def test_interim_overrides_raw_for_same_filename(mini_config, mini_raw, tmp_path):
    """A filename present in interim wins over the same name in raw."""
    from tests.conftest import write

    interim_root = tmp_path / "interim"
    # Interim subject.tsv carries a different subject set than raw's c1/c2.
    write(interim_root / "MINI" / "subject.tsv", """
        case_id\tsex\tsubject_type
        c9\tmale\tpatient
    """)

    out_root = tmp_path / "std"
    standardise(
        "MINI", "test",
        raw_root=mini_raw, out_root=out_root, interim_root=interim_root,
        config_dir=mini_config, log=False,
    )
    header, rows = _read(out_root / "MINI" / "nodes" / "Subject.csv")
    # Subject came from interim (c9), not raw (c1/c2).
    assert rows == [["c9", "male", "patient"]]

    # sample.tsv exists only in raw -> still resolves unchanged.
    header, rows = _read(out_root / "MINI" / "nodes" / "Sample.csv")
    assert [r[0] for r in rows] == ["s1", "s2"]


def test_standardise_skips_missing_and_unbound(mini_config, mini_raw, tmp_path):
    summary = standardise(
        "MINI", "test",
        raw_root=mini_raw, out_root=tmp_path / "std", config_dir=mini_config, log=False,
    )
    # Ghost maps to an absent file -> skipped, never raises
    assert "Ghost" in summary["skipped"]
    assert not (tmp_path / "std" / "MINI" / "nodes" / "Ghost.csv").exists()
