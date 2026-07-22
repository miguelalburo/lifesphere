"""Offline admin-import adapter: header rewriting, edge splitting, command build."""

from __future__ import annotations

from pathlib import Path

from conftest import write

from src.load.bulk import build_import


def _config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config"
    write(cfg / "schema" / "nodes.yaml", """
        Sample:
          id: sampleId
          properties: [subjectId, {purity: float}]
        Gene:
          id: geneId
        Obs:
          id: obsId
          properties: [{value: float}]
        Widget:
          id: widgetId
          subtypeLabels: [Big, Small]
          subtypeFrom: _subtypeLabel
          properties: [color]
    """)
    write(cfg / "schema" / "edges.yaml", """
        LINK:
          pairs: [[Sample, Gene], [Obs, Gene]]
          properties: [{confidence: double}]
    """)
    return cfg


def _dataset(tmp_path: Path) -> Path:
    ds = tmp_path / "std" / "MINI"
    write(ds / "nodes" / "Sample.csv", "sampleId,subjectId,purity\nS1,SUB1,0.9\n")
    write(ds / "nodes" / "Gene.csv", "geneId\nG1\n")
    write(ds / "nodes" / "Obs.csv", "obsId,value\nO1,3.14\n")
    write(ds / "nodes" / "Widget.csv",
          "widgetId,color,_subtypeLabel\nW1,red,Big\nW2,blue,\n")
    write(ds / "edges" / "LINK.csv",
          "startId,endId,startLabel,endLabel,confidence\n"
          "S1,G1,Sample,Gene,0.7\nO1,G1,Obs,Gene,0.4\n")
    return tmp_path / "std"


def _header(path: Path) -> str:
    return path.read_text(encoding="utf-8").splitlines()[0]


def _run(tmp_path):
    out = tmp_path / "import" / "MINI"
    plan = build_import(
        "MINI",
        standardised_root=_dataset(tmp_path),
        out_dir=out,
        database="lifesphere",
        config_dir=_config(tmp_path),
    )
    return plan, out


def test_node_headers_and_types(tmp_path):
    _plan, out = _run(tmp_path)
    assert _header(out / "Sample.csv") == "sampleId:ID(Sample),subjectId,purity:float"
    assert _header(out / "Obs.csv") == "obsId:ID(Obs),value:float"
    assert _header(out / "Gene.csv") == "geneId:ID(Gene)"


def test_multilabel_column(tmp_path):
    _plan, out = _run(tmp_path)
    lines = (out / "Widget.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "widgetId:ID(Widget),color,:LABEL"
    assert lines[1] == "W1,red,Big"     # subtype maps to the extra label
    assert lines[2] == "W2,blue,"       # blank subtype -> no extra label


def test_edges_split_per_pair(tmp_path):
    _plan, out = _run(tmp_path)
    sg = out / "LINK__Sample__Gene.csv"
    og = out / "LINK__Obs__Gene.csv"
    assert _header(sg) == ":START_ID(Sample),:END_ID(Gene),confidence:double"
    assert _header(og) == ":START_ID(Obs),:END_ID(Gene),confidence:double"
    assert sg.read_text(encoding="utf-8").splitlines()[1] == "S1,G1,0.7"
    assert og.read_text(encoding="utf-8").splitlines()[1] == "O1,G1,0.4"


def test_command_and_constraints(tmp_path):
    plan, out = _run(tmp_path)
    cmd = plan["command"]
    assert cmd[:4] == ["neo4j-admin", "database", "import", "full"]
    assert "--id-type=string" in cmd
    # blank typed cells (sparse rows) must be treated as null, not parse errors
    assert "--ignore-empty-strings=true" in cmd
    assert cmd[-1] == "lifesphere"                      # database is the last arg
    assert f"--nodes=Sample={out / 'Sample.csv'}" in cmd
    assert f"--relationships=LINK={out / 'LINK__Sample__Gene.csv'}" in cmd
    assert f"--relationships=LINK={out / 'LINK__Obs__Gene.csv'}" in cmd
    # one uniqueness constraint per loaded node label
    assert len(plan["constraints"]) == 4
    assert any("Sample" in c and "sampleId" in c for c in plan["constraints"])


def test_subtype_column_not_double_emitted(tmp_path):
    """A subtypeFrom column listed in properties still becomes only :LABEL."""
    cfg = tmp_path / "config"
    write(cfg / "schema" / "nodes.yaml", """
        Thing:
          id: thingId
          subtypeLabels: [A, B]
          subtypeFrom: kind
          properties: [kind, color]
    """)
    write(cfg / "schema" / "edges.yaml", "{}")
    ds = tmp_path / "std" / "MINI"
    write(ds / "nodes" / "Thing.csv", "thingId,kind,color\nT1,A,red\n")

    out = tmp_path / "import" / "MINI"
    build_import("MINI", standardised_root=tmp_path / "std", out_dir=out,
                 config_dir=cfg)
    lines = (out / "Thing.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "thingId:ID(Thing),color,:LABEL"   # kind only as :LABEL
    assert lines[1] == "T1,red,A"


def test_cli_bulk_emits_command(tmp_path, monkeypatch, capsys):
    """--bulk writes files and prints the command without touching a database."""
    from src.load import __main__ as cli
    from src.load import bulk

    std_root = tmp_path / "std"
    write(std_root / "MINI" / "nodes" / "Sample.csv", "sampleId,subjectId\nS1,SUB1\n")
    monkeypatch.setattr(bulk, "DATA_STANDARDISED", std_root)
    monkeypatch.setattr(bulk, "DATA_IMPORT", tmp_path / "import")

    rc = cli.main(["MINI", "--bulk", "--database", "kg"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "neo4j-admin database import full" in out
    assert "--nodes=Sample=" in out
    assert "CREATE CONSTRAINT" in out          # follow-up constraints printed
    assert (tmp_path / "import" / "MINI" / "Sample.csv").exists()
