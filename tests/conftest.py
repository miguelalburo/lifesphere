"""Shared test helpers: writing tiny fixture files and a self-contained config."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    return path


@pytest.fixture
def mini_config(tmp_path: Path) -> Path:
    """A minimal, self-contained schema+mapping+placeholders config directory."""
    cfg = tmp_path / "config"
    write(cfg / "schema" / "nodes.yaml", """
        Subject:
          id: subjectId
          properties: [sexAtBirth, subjectType]
        Sample:
          id: sampleId
          properties: [subjectId, sampleClass]
        Widget:
          id: widgetId
          subtypeLabels: [Big, Small]
          subtypeFrom: _subtypeLabel
          properties: [color]
    """)
    write(cfg / "schema" / "edges.yaml", """
        PROVIDED_SAMPLE:
          pairs: [[Subject, Sample]]
          properties: [derivationMethod]
    """)
    write(cfg / "mapping" / "test.yaml", """
        profile: test
        nodes:
          Subject:
            file: subject.tsv
            key: case_id
            dedup: true
            props: {sexAtBirth: sex}
          Sample:
            file: sample.tsv
            key: sample_id
            dedup: true
            props: {subjectId: case_id, sampleClass: sample_type}
          Widget:
            file: widget.tsv
            key: widget_id
            dedup: true
            props: {_subtypeLabel: size, color: color}
          Ghost:
            file: absent.tsv
            key: ghost_id
        edges:
          PROVIDED_SAMPLE:
            file: sample.tsv
            start_key: case_id
            end_key: sample_id
            props: {derivationMethod: method}
    """)
    write(cfg / "placeholders.yaml", """
        placeholders: ["NA", "--", "unknown"]
    """)
    return cfg


@pytest.fixture
def mini_raw(tmp_path: Path) -> Path:
    """A raw dataset directory matching ``mini_config`` files."""
    raw = tmp_path / "raw" / "MINI"
    write(raw / "subject.tsv", """
        case_id\tsex\tsubject_type
        c1\tfemale\tpatient
        c1\tfemale\tpatient
        c2\tNA\tpatient
    """)
    write(raw / "sample.tsv", """
        sample_id\tcase_id\tsample_type\tmethod
        s1\tc1\tPrimary Tumor\tResection
        s1\tc1\tPrimary Tumor\tResection
        s2\tc2\t--\tBiopsy
    """)
    write(raw / "widget.tsv", """
        widget_id\tsize\tcolor
        w1\tBig\tred
        w2\tHuge\tblue
    """)
    return raw.parent  # raw_root (contains dataset dir MINI)
