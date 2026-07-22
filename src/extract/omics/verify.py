"""Audit downloaded omics files against their GDC ``manifest.tsv``.

Each omics extractor writes a ``manifest.tsv`` (columns: ``id, filename, md5,
size, state``) alongside the per-file downloads in ``{dir}/{id}/{filename}``.
This command re-checks what's on disk against that manifest so a job that was
killed mid-write (leaving a truncated file the ``exists()`` resume check would
wrongly accept) can be found and re-fetched.

By default it checks only file **size** (a cheap ``stat`` — enough to catch
truncation); pass ``--md5`` for a full checksum over 12k+ files. ``--delete``
removes any bad/partial file so the next extraction re-downloads it, and stray
``.part`` sidecars (from an interrupted atomic write) are always cleaned when
deleting.

    python -m src.extract.omics.verify data/raw/TCGA_METHYLATION/methylation
    python -m src.extract.omics.verify data/raw/TCGA_*/  --md5 --delete
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .download import verify_file


def _find_manifest(target: Path) -> Path | None:
    """Return the manifest for *target*, whether it's the omics dir or its parent."""
    direct = target / "manifest.tsv"
    if direct.is_file():
        return direct
    # e.g. data/raw/TCGA_METHYLATION → data/raw/TCGA_METHYLATION/methylation
    for child in sorted(target.glob("*/manifest.tsv")):
        return child
    return None


def verify_dir(target: Path, *, check_md5: bool, delete: bool) -> dict[str, int]:
    """Verify every manifest entry under *target*. Returns a status tally."""
    manifest = _find_manifest(target)
    if manifest is None:
        print(f"! no manifest.tsv under {target}", file=sys.stderr)
        return {"no_manifest": 1}

    base = manifest.parent
    tally = {"ok": 0, "missing": 0, "bad": 0, "part_removed": 0}
    print(f"Verifying {base} against {manifest.name} (md5={check_md5})...", file=sys.stderr, flush=True)

    with manifest.open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            file_id, name = row["id"], row["filename"]
            size = int(row["size"]) if row.get("size") else None
            md5 = row["md5"] if check_md5 else None
            path = base / file_id / name

            reason = verify_file(path, md5=md5, size=size)
            if reason is None:
                tally["ok"] += 1
                continue

            key = "missing" if reason == "missing" else "bad"
            tally[key] += 1
            print(f"  {key.upper():7} {file_id}/{name}: {reason}", flush=True)
            if delete and reason != "missing":
                path.unlink(missing_ok=True)

            # A leftover .part sidecar means an interrupted atomic write.
            part = base / file_id / (name + ".part")
            if part.exists() and delete:
                part.unlink(missing_ok=True)
                tally["part_removed"] += 1

    print(
        f"  {base.name}: {tally['ok']} ok, {tally['missing']} missing, "
        f"{tally['bad']} bad" + (f", {tally['part_removed']} .part removed" if delete else ""),
        file=sys.stderr, flush=True,
    )
    return tally


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.extract.omics.verify",
        description="Verify downloaded omics files against manifest.tsv.",
    )
    parser.add_argument("dirs", nargs="+", type=Path, help="omics dir(s) (or their parent) holding manifest.tsv")
    parser.add_argument("--md5", action="store_true", help="full md5 check (default: size only)")
    parser.add_argument("--delete", action="store_true", help="delete bad/partial files so a re-run re-fetches them")
    args = parser.parse_args(argv)

    total_bad = total_missing = 0
    for d in args.dirs:
        tally = verify_dir(d, check_md5=args.md5, delete=args.delete)
        total_bad += tally.get("bad", 0)
        total_missing += tally.get("missing", 0)

    # Non-zero exit if any file failed, so a resubmission script can gate on it.
    return 1 if (total_bad or total_missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
