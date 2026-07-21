#!/usr/bin/env python3
"""Offline resume of omics reshape from already-downloaded raw files.

The expression/methylation extractors (``src.extract.omics.*``) run in two
phases: download every GDC file, then reshape them to an observation-grain TSV.
Downloads are resume-safe and the file→sample/assay mapping is written up front,
so a run that downloaded everything but produced an empty/partial
``*_observation.tsv`` (e.g. the pre-fix STAR ``#``-comment / headerless-sesame
parser bug) can be finished without touching the network.

This script re-runs only ``reshape()`` — with the *current* parsers — using the
local files, so it is safe on an offline HPC compute node (no GDC query, no
re-download).

For each raw output dir it looks for ``expression/`` and/or ``methylation/``
subdirs containing ``file_metadata.tsv`` (columns: file_id, file_name,
sample_id, assay_id, pipeline_version) and rewrites
``<raw_dir>/<layer>_observation.tsv`` — exactly where a successful extract would.

Usage
-----
    # HPC layout (one out dir per layer, as scripts/extract_TCGA/extract_TCGA_*.sh use):
    python scripts/extract_TCGA/resume_omics_reshape.py \
        "$RAW_DIR/TCGA_EXPRESSION" "$RAW_DIR/TCGA_METHYLATION"

    # a single dataset dir holding both layer subdirs:
    python scripts/extract_TCGA/resume_omics_reshape.py data/raw/TCGA

    # override the source_dataset label written into the observations:
    python scripts/extract_TCGA/resume_omics_reshape.py --dataset TCGA "$RAW_DIR/TCGA_EXPRESSION"

The source_dataset label defaults to the raw dir name with a trailing
``_EXPRESSION`` / ``_METHYLATION`` / ``_VARIATION`` stripped (so
``TCGA_EXPRESSION`` → ``TCGA``, matching ``--program TCGA``). Use ``--dataset``
if that heuristic is wrong for your naming.

Note: variation is not handled here — it reshapes a project-level MAF via a
different code path and was unaffected by the parser bugs.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

# Ensure the project root is importable when run as a plain script.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.extract.omics import expression as expr_mod
from src.extract.omics import methylation as meth_mod

_LAYERS = {"expression": expr_mod, "methylation": meth_mod}
_SUFFIX_RE = re.compile(r"_(EXPRESSION|METHYLATION|VARIATION)$", re.IGNORECASE)


def _infer_dataset(raw_dir: Path) -> str:
    """Best-effort source_dataset label: strip a trailing layer suffix."""
    return _SUFFIX_RE.sub("", raw_dir.name)


def _read_metadata(meta_path: Path) -> list[dict]:
    with meta_path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def resume_layer(raw_dir: Path, layer: str, dataset: str) -> int | None:
    """Rebuild ``<raw_dir>/<layer>_observation.tsv`` from local files. Returns count."""
    module = _LAYERS[layer]
    layer_dir = raw_dir / layer
    meta_path = layer_dir / "file_metadata.tsv"
    if not meta_path.exists():
        print(f"  [{layer}] no {meta_path} — skipping", file=sys.stderr)
        return None

    rows = _read_metadata(meta_path)
    entries: list[dict] = []
    missing = 0
    for r in rows:
        file_id = (r.get("file_id") or "").strip()
        file_name = (r.get("file_name") or "").strip()
        path = layer_dir / file_id / file_name
        if not path.exists():
            missing += 1
            continue
        entries.append({
            "path": path,
            "sample_id": r.get("sample_id", ""),
            "assay_id": r.get("assay_id", ""),
            "source_file": file_id,
            "pipeline_version": r.get("pipeline_version", ""),
        })

    if not entries:
        print(
            f"  [{layer}] {len(rows)} metadata rows but no downloaded files found "
            f"under {layer_dir} — nothing to reshape",
            file=sys.stderr,
        )
        return None

    out_path = raw_dir / f"{layer}_observation.tsv"
    count = module.reshape(entries, out_path, dataset=dataset)
    status = f"{len(entries)}/{len(rows)} files"
    if missing:
        status += f", {missing} not yet downloaded"
    print(
        f"  [{layer}] {count:,} observations from {status} "
        f"(source_dataset={dataset!r}) → {out_path}",
        file=sys.stderr,
    )
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts/extract_TCGA/resume_omics_reshape.py",
        description="Re-run omics reshape offline from already-downloaded raw files.",
    )
    parser.add_argument(
        "raw_dirs", type=Path, nargs="+",
        help="raw output dir(s) each containing expression/ and/or methylation/ subdirs",
    )
    parser.add_argument(
        "--layers", nargs="+", choices=sorted(_LAYERS), default=sorted(_LAYERS),
        help="which layers to reshape (default: expression methylation)",
    )
    parser.add_argument(
        "--dataset", default=None,
        help="source_dataset label to write (default: raw dir name minus layer suffix)",
    )
    args = parser.parse_args(argv)

    total = 0
    did_any = False
    for raw_dir in args.raw_dirs:
        if not raw_dir.exists():
            parser.error(f"raw dir not found: {raw_dir}")
        dataset = args.dataset or _infer_dataset(raw_dir)
        print(f"{raw_dir} (source_dataset={dataset!r}):", file=sys.stderr)
        for layer in args.layers:
            if not (raw_dir / layer).exists():
                continue
            did_any = True
            n = resume_layer(raw_dir, layer, dataset)
            if n:
                total += n

    if not did_any:
        parser.error(
            "no expression/ or methylation/ subdirs found in the given raw dir(s)"
        )
    print(f"Done — {total:,} observations rewritten.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
