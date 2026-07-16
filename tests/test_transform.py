"""Unit tests for the pure standardise transforms."""

from __future__ import annotations

from src.standardise.transform import camel, scrub, strip_prefix

PLACEHOLDERS = frozenset({"na", "--", "unknown"})


def test_camel_snake_and_spaces():
    assert camel("sample_id") == "sampleId"
    assert camel("days to collection") == "daysToCollection"
    assert camel("ajcc_pathologic_stage") == "ajccPathologicStage"


def test_camel_passthrough_for_camel_tokens():
    assert camel("gdcSampleId") == "gdcSampleId"
    assert camel("symbol") == "symbol"
    assert camel("") == ""


def test_scrub_trims_and_blanks_placeholders():
    assert scrub("  female ", PLACEHOLDERS) == "female"
    assert scrub("NA", PLACEHOLDERS) == ""
    assert scrub("--", PLACEHOLDERS) == ""
    assert scrub("Unknown", PLACEHOLDERS) == ""  # case-insensitive
    assert scrub(None, PLACEHOLDERS) == ""


def test_strip_prefix():
    assert strip_prefix("TCGA-BH-A0B3", "TCGA-") == "BH-A0B3"
    assert strip_prefix("BH-A0B3", "TCGA-") == "BH-A0B3"
    assert strip_prefix("x", None) == "x"
