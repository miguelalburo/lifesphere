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
