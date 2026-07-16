"""Column lookup / alias matching and the report coverage view."""

from __future__ import annotations

from src.standardise.aliases import ColumnResolver
from src.standardise.run import report

FIELDS = [
    "sample_id", "sample_type", "days_to_collection",
    "AJCC_Pathologic_Stage", "diagnoses.tumor_grade", "submitter_id",
]


def test_resolution_strategies():
    r = ColumnResolver(FIELDS, props={"sampleClass": "sample_type"})
    assert r.resolve("sampleClass") == ("sample_type", "override")
    assert r.resolve("daysToCollection") == ("days_to_collection", "camel")
    # camelCase of AJCC_Pathologic_Stage != ajccPathologicStage, but normalized does
    assert r.resolve("ajccPathologicStage") == ("AJCC_Pathologic_Stage", "normalized")
    # dotted GDC name resolved by last-segment
    assert r.resolve("tumorGrade") == ("diagnoses.tumor_grade", "suffix")
    assert r.resolve("purity").strategy == "unmatched"


def test_alias_tables_and_precedence():
    # global alias binds when no node alias exists
    r1 = ColumnResolver(["submitter_id"], global_aliases={"submitter_id": "subjectId"})
    assert r1.resolve("subjectId") == ("submitter_id", "alias")

    # a node alias overrides the global mapping for that raw column
    r2 = ColumnResolver(
        ["submitter_id"],
        node_aliases={"submitter_id": "donorId"},
        global_aliases={"submitter_id": "subjectId"},
    )
    assert r2.resolve("donorId") == ("submitter_id", "alias")
    assert r2.resolve("subjectId").strategy == "unmatched"


def test_alias_ignored_when_column_absent():
    r = ColumnResolver(["x"], global_aliases={"submitter_id": "subjectId"})
    assert r.resolve("subjectId").strategy == "unmatched"


def test_strip_header_prefix():
    fields = ["diagnosis_id", "diagnosis_morphology", "diagnosis_tumor_grade", "morphology"]
    r = ColumnResolver(fields, strip_prefixes=("diagnosis_",))
    # a prefixed header matches its stripped canonical form...
    assert r.resolve("tumorGrade") == ("diagnosis_tumor_grade", "camel")
    # ...but an exact full header still wins over a stripped collision
    assert r.resolve("morphology") == ("morphology", "camel")
    # value is still read from the real (prefixed) column name
    assert r.resolve("tumorGrade").raw == "diagnosis_tumor_grade"


def test_collision_recorded():
    r = ColumnResolver(["tumor_grade", "tumorGrade"])
    assert "tumorGrade" in r.collisions
    assert r.collisions["tumorGrade"] == ["tumor_grade", "tumorGrade"]


def test_report_matched_unmatched_unused():
    r = ColumnResolver(FIELDS, props={"sampleClass": "sample_type"})
    rep = r.report(["sampleClass", "daysToCollection", "purity"], reserved=("sample_id",))

    assert ("sampleClass", "sample_type", "override") in rep["matched"]
    assert rep["unmatched"] == ["purity"]
    # sample_id reserved (key) and matched columns are not reported as unused
    assert "sample_id" not in rep["unused"]
    assert "sample_type" not in rep["unused"]
    assert "submitter_id" in rep["unused"]


def test_shared_alias_resolves_below_profile_aliases():
    r = ColumnResolver(["raw_col"], shared_aliases={"raw_col": "canonProp"})
    assert r.resolve("canonProp") == ("raw_col", "shared_alias")


def test_profile_alias_overrides_shared_alias():
    r = ColumnResolver(
        ["raw_col"],
        global_aliases={"raw_col": "profileProp"},
        shared_aliases={"raw_col": "sharedProp"},
    )
    assert r.resolve("profileProp") == ("raw_col", "alias")
    assert r.resolve("sharedProp").strategy == "unmatched"


def test_camel_beats_shared_alias():
    # auto-camel should win; shared alias for a different canonical is separate
    r = ColumnResolver(["my_prop"], shared_aliases={"my_prop": "otherProp"})
    assert r.resolve("myProp").strategy == "camel"
    assert r.resolve("otherProp") == ("my_prop", "shared_alias")


def test_shared_alias_ignored_when_column_absent():
    r = ColumnResolver(["x"], shared_aliases={"missing_col": "someProp"})
    assert r.resolve("someProp").strategy == "unmatched"


def test_load_mapping_loads_shared_aliases(tmp_path):
    from src.standardise.mapping import load_mapping
    cfg = tmp_path / "config"
    (cfg / "mapping").mkdir(parents=True)
    (cfg / "mapping" / "test.yaml").write_text("profile: test\n")
    (cfg / "aliases.yaml").write_text("raw_col: canonProp\n")
    m = load_mapping("test", config_dir=cfg)
    assert m.shared_aliases == {"raw_col": "canonProp"}


def test_load_mapping_shared_aliases_absent(tmp_path):
    from src.standardise.mapping import load_mapping
    cfg = tmp_path / "config"
    (cfg / "mapping").mkdir(parents=True)
    (cfg / "mapping" / "test.yaml").write_text("profile: test\n")
    m = load_mapping("test", config_dir=cfg)
    assert m.shared_aliases == {}


def test_report_over_dataset(mini_config, mini_raw):
    rep = report("MINI", "test", raw_root=mini_raw, config_dir=mini_config)

    subject = rep["nodes"]["Subject"]
    assert subject["key_present"] is True
    matched = {p: (raw, strat) for p, raw, strat in subject["matched"]}
    assert matched["sexAtBirth"] == ("sex", "override")
    assert matched["subjectType"] == ("subject_type", "camel")

    # Ghost's file is absent -> reported as skipped, never raised
    assert any(name == "Ghost" for name, _ in rep["skipped"])
