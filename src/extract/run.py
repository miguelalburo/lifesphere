"""Fetch GDC cases and write one {NAME}.tsv per entity emitter.

Sample is already at aliquot grain, Treatment already fanned out, Program/Study
already aggregated, Survival already derived — all via iter_rows().
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from . import gdc_api
from ._base import emit
from .entities import EMITTERS, EXPAND


def _fetch(filters: dict) -> list[dict]:
    hits: list[dict] = []
    from_pos, total = 0, None
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
            print(f"  Total cases: {total}", flush=True)
        hits.extend(d["hits"])
        from_pos += len(d["hits"])
        print(f"  Fetched {from_pos}/{total}...", flush=True)
    return hits


def fetch_project(project_id: str) -> list[dict]:
    return _fetch({"op": "=", "content": {"field": "project.project_id", "value": project_id}})


def fetch_program(program_name: str) -> list[dict]:
    return _fetch({"op": "=", "content": {"field": "project.program.name", "value": program_name}})


def write_entities(hits: list[dict], out_dir: Path) -> None:
    """Write {NAME}.tsv for every registered emitter (columns discovered dynamically)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for emitter in EMITTERS:
        columns, rows = emit(hits, emitter.iter_rows)
        out_path = out_dir / f"{emitter.NAME}.tsv"
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, delimiter="\t", extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        print(f"  {out_path.name:42s} {len(rows):7d} rows × {len(columns)} cols", flush=True)


def extract(project_id: str, out_dir: Path) -> None:
    print(f"Fetching {project_id} from GDC /cases...", file=sys.stderr, flush=True)
    hits = fetch_project(project_id)
    if not hits:
        print("  No cases found.", file=sys.stderr)
        return
    print(f"Writing TSVs to {out_dir}...", file=sys.stderr, flush=True)
    write_entities(hits, out_dir)
    print(f"Done — {len(EMITTERS)} entity files written.", file=sys.stderr, flush=True)


def extract_program(program_name: str, out_dir: Path) -> None:
    print(f"Fetching all cases in program {program_name} from GDC /cases...", file=sys.stderr, flush=True)
    hits = fetch_program(program_name)
    if not hits:
        print("  No cases found.", file=sys.stderr)
        return
    print(f"Writing TSVs to {out_dir}...", file=sys.stderr, flush=True)
    write_entities(hits, out_dir)
    print(f"Done — {len(EMITTERS)} entity files written.", file=sys.stderr, flush=True)
