"""
Merge BCR BioTab clinical_patient files into a cases metadata TSV.

BioTab clinical_patient files are the only BioTab type that is 1:1 with
patients/cases. Other types (drug, radiation, follow_up, biospecimen_*)
are 1:many and require separate handling.

Join key: bcr_patient_uuid (BioTab, case-insensitive) == case_id (metadata TSV).
BioTab columns are added with a "bcr_" prefix to distinguish them from the
harmonized GDC fields already present in the metadata TSV.
"""

import csv
from pathlib import Path

_JOIN_COLS = {"bcr_patient_uuid", "bcr_patient_barcode"}


def _read_patient_files(biotab_dir: Path) -> dict[str, dict]:
    """
    Read all clinical_patient_*.txt files under biotab_dir.
    Returns {uuid_lower: {col: val, ...}}.

    BioTab format:
      row 0  — display column names  (used as headers)
      row 1  — CDE field names       (skipped)
      row 2  — CDE IDs               (skipped)
      row 3+ — data
    """
    lookup: dict[str, dict] = {}
    for path in sorted(biotab_dir.rglob("*clinical_patient_*.txt")):
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        if len(lines) < 4:
            continue
        headers = lines[0].split("\t")
        for line in lines[3:]:
            if not line.strip():
                continue
            vals = line.split("\t")
            row = dict(zip(headers, vals))
            uuid = row.get("bcr_patient_uuid", "").lower()
            if uuid:
                lookup[uuid] = row
    return lookup


def merge_biotab_into_metadata(biotab_dir: Path, metadata_path: Path) -> None:
    """Left-join clinical_patient BioTab columns into metadata_path (in-place)."""
    lookup = _read_patient_files(biotab_dir)
    if not lookup:
        print("  No clinical_patient BioTab files found; skipping merge.")
        return

    # Collect ordered union of BioTab columns, excluding the join/ID keys
    seen_cols: set[str] = set()
    bcr_cols: list[str] = []
    for row in lookup.values():
        for col in row:
            if col not in _JOIN_COLS and col not in seen_cols:
                bcr_cols.append(f"bcr_{col}")
                seen_cols.add(col)

    with open(metadata_path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        meta_rows = list(reader)
        meta_fieldnames = list(reader.fieldnames)

    hits = 0
    merged: list[dict] = []
    for row in meta_rows:
        bt = lookup.get(row["case_id"].lower(), {})
        if bt:
            hits += 1
        new_row = dict(row)
        for col in bcr_cols:
            new_row[col] = bt.get(col[4:], "")  # strip "bcr_" to look up original name
        merged.append(new_row)

    with open(metadata_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=meta_fieldnames + bcr_cols, delimiter="\t")
        writer.writeheader()
        writer.writerows(merged)

    print(f"  Merged BioTab clinical_patient: {hits}/{len(meta_rows)} cases matched, "
          f"{len(bcr_cols)} columns added → {metadata_path.name}")
