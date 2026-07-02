"""
Fetch harmonized cases from the GDC /cases endpoint and write one TSV per entity.

A single ``expand`` fetch pulls each case with all nested sub-objects, then every
registered emitter (see ``entities/``) writes its own ``{base}.{entity}.tsv`` at
that entity's true grain. This preserves 1:many entities (follow_ups, treatments,
diagnoses, aliquots, ...) that the previous single-row-per-case flatten collapsed.
"""

import csv
from pathlib import Path

from . import gdc_api
from .biospecimen import merge_sample_aliquot
from .entities import EMITTERS, EXPAND


def _fetch(filters: dict) -> list[dict]:
    hits, from_pos, total = [], 0, None
    while total is None or from_pos < total:
        payload = {
            "filters": filters,
            "expand": ",".join(EXPAND),
            "size": 500,
            "from": from_pos,
        }
        d = gdc_api.post(gdc_api.CASES_URL, payload)["data"]
        if total is None:
            total = d["pagination"]["total"]
            print(f"  Total cases: {total}")
        hits.extend(d["hits"])
        from_pos += len(d["hits"])
        print(f"  Fetched {from_pos}/{total}...", flush=True)
    return hits


def fetch_all(project_id: str) -> list[dict]:
    return _fetch({"op": "=", "content": {"field": "project.project_id", "value": project_id}})


def fetch_by_program(program: str) -> list[dict]:
    return _fetch({"op": "=", "content": {"field": "project.program.name", "value": program}})


def fetch_by_ids(case_ids: list[str]) -> list[dict]:
    return _fetch({"op": "in", "content": {"field": "case_id", "value": case_ids}})


def _derive_program_project(hits: list[dict], out_dir: Path, base_name: str) -> None:
    """Write {base_name}.project.tsv and {base_name}.program.tsv from case hits."""
    from collections import defaultdict

    project_cases: dict[str, dict] = {}  # project_id -> {project_name, program_name, n_cases}
    for case in hits:
        proj = case.get("project") or {}
        pid = proj.get("project_id", "")
        if pid not in project_cases:
            project_cases[pid] = {
                "project_id":   pid,
                "project_name": proj.get("name", ""),
                "program_name": (proj.get("program") or {}).get("name", ""),
                "n_cases":      0,
            }
        project_cases[pid]["n_cases"] += 1

    project_path = out_dir / f"{base_name}.project.tsv"
    project_cols = ["project_id", "project_name", "program_name", "n_cases"]
    rows = sorted(project_cases.values(), key=lambda r: r["project_id"])
    with open(project_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=project_cols, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {project_path.name:42s} {len(rows):7d} rows × {len(project_cols)} cols")

    program_cases: dict[str, dict] = defaultdict(lambda: {"n_projects": 0, "n_cases": 0})
    for r in rows:
        pg = r["program_name"]
        program_cases[pg]["program_name"] = pg
        program_cases[pg]["n_projects"] += 1
        program_cases[pg]["n_cases"] += r["n_cases"]

    program_path = out_dir / f"{base_name}.program.tsv"
    program_cols = ["program_name", "n_projects", "n_cases"]
    pg_rows = sorted(program_cases.values(), key=lambda r: r["program_name"])
    with open(program_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=program_cols, delimiter="\t")
        writer.writeheader()
        writer.writerows(pg_rows)
    print(f"  {program_path.name:42s} {len(pg_rows):7d} rows × {len(program_cols)} cols")


def write_entities(hits: list[dict], out_dir: Path, base_name: str) -> None:
    """Write one {base_name}.{entity}.tsv per registered emitter."""
    for emitter in EMITTERS:
        out_path = out_dir / f"{base_name}.{emitter.NAME}.tsv"
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=emitter.COLUMNS, delimiter="\t", extrasaction="ignore"
            )
            writer.writeheader()
            n = 0
            for case in hits:
                for row in emitter.iter_rows(case):
                    writer.writerow(row)
                    n += 1
        print(f"  {out_path.name:42s} {n:7d} rows × {len(emitter.COLUMNS)} cols")

    # Post-processing: collapse biospecimen to aliquot grain (sample <- aliquot).
    merge_sample_aliquot(out_dir, base_name)
    # Post-processing: aggregate project and program summary tables.
    _derive_program_project(hits, out_dir, base_name)


def download_cases_tsv(project_id: str, out_dir: Path) -> None:
    print("\n[2/2] Fetching harmonized cases from GDC /cases endpoint...")
    hits = fetch_all(project_id)
    if not hits:
        print("  No cases found.")
        return
    write_entities(hits, out_dir, project_id)


def download_cases_tsv_by_program(program: str, out_dir: Path) -> None:
    print("\n[1/1] Fetching harmonized cases from GDC /cases endpoint...")
    hits = fetch_by_program(program)
    if not hits:
        print("  No cases found.")
        return
    write_entities(hits, out_dir, program)


def download_cases_tsv_by_ids(case_ids: list[str], out_dir: Path) -> None:
    print("\n[1/1] Fetching harmonized cases from GDC /cases endpoint...")
    hits = fetch_by_ids(case_ids)
    if not hits:
        print("  No cases found.")
        return
    write_entities(hits, out_dir, "cases")
