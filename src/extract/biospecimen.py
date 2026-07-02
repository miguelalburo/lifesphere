"""Post-processing: collapse the biospecimen hierarchy to aliquot grain.

The emitters write two biospecimen tables:
  - ``{base}.sample.tsv``  — one row per GDC sample (sample-level descriptors);
  - ``{base}.aliquot.tsv`` — one row per aliquot, carrying its ``sample_id``.

Downstream the KG treats the **aliquot** as the analysed unit (the "Sample" node
that omics files map to), so this step merges the sample-level descriptors onto
every aliquot row and rewrites ``{base}.sample.tsv`` at aliquot grain, renaming
the ids so the aliquot becomes the primary Sample identity:

    sample_id           -> gdc_sample_id            (originating GDC sample)
    sample_submitter_id -> gdc_sample_submitter_id
    aliquot_id          -> sample_id                (new Sample primary key)

The now-redundant ``{base}.aliquot.tsv`` (fully absorbed) is removed.

Pure ``csv``; run automatically at the end of ``cases.write_entities`` and
invocable standalone to reprocess an existing extract in place.
"""

import csv
from pathlib import Path

# GDC-sample identifiers get a gdc_ prefix; the aliquot id becomes sample_id.
_RENAME = {
    "sample_id": "gdc_sample_id",
    "sample_submitter_id": "gdc_sample_submitter_id",
    "aliquot_id": "sample_id",
}

# Sample columns not grafted onto aliquot rows: case identity + the join key,
# and sample_type (already carried on every aliquot row).
_SKIP_SAMPLE_COLS = {"case_id", "case_submitter_id", "sample_id", "sample_sample_type"}


def _read(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def merge_sample_aliquot(out_dir, base: str) -> None:
    """Merge ``{base}.sample.tsv`` onto ``{base}.aliquot.tsv`` (in place)."""
    out_dir = Path(out_dir)
    sample_path = out_dir / f"{base}.sample.tsv"
    aliquot_path = out_dir / f"{base}.aliquot.tsv"
    if not (sample_path.exists() and aliquot_path.exists()):
        print("  merge_sample_aliquot: sample/aliquot TSV missing — skipped.")
        return

    sample_cols, samples = _read(sample_path)
    aliquot_cols, aliquots = _read(aliquot_path)

    # Sample descriptors keyed by the originating GDC sample_id.
    graft_cols = [c for c in sample_cols if c not in _SKIP_SAMPLE_COLS]
    sample_by_id = {
        r["sample_id"]: {_RENAME.get(c, c): r.get(c, "") for c in graft_cols}
        for r in samples
    }

    out_cols = ([_RENAME.get(c, c) for c in aliquot_cols]
                + [_RENAME.get(c, c) for c in graft_cols])

    with open(sample_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=out_cols, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        for a in aliquots:
            row = {_RENAME.get(k, k): v for k, v in a.items()}
            row.update(sample_by_id.get(a.get("sample_id", ""), {}))
            writer.writerow(row)

    aliquot_path.unlink()
    print(f"  merged sample+aliquot -> {sample_path.name} "
          f"({len(aliquots)} rows × {len(out_cols)} cols); removed {aliquot_path.name}")
