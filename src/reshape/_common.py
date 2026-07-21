"""Small helpers shared by the matrix melt and the VCF reader.

Both reshapers live behind the one door and emit the same canonical observation
shape, so the mechanical bits — stderr logging, the assay-augmented field list,
a provenance-stamped blank record, and the loud sample-reconciliation tail — are
defined once here rather than copied into each.
"""

from __future__ import annotations

import sys


def log(msg: str, enabled: bool) -> None:
    if enabled:
        print(msg, file=sys.stderr, flush=True)


def observation_fieldnames(base_columns: list[str], assay: dict[str, str]) -> list[str]:
    """Base contract columns plus any assay provenance keys not already among them.

    ``assay_id`` already lives in the contract; ``platform``/``library_strategy``/…
    become extra constant columns the Assay node binding picks up.
    """
    extra = [k for k in assay if k not in base_columns]
    return [*base_columns, *extra]


def stamp_row(fieldnames: list[str], assay: dict[str, str], *, dataset: str,
              source_file: str) -> dict[str, str]:
    """A blank observation record with assay + source provenance already stamped."""
    rec = {c: "" for c in fieldnames}
    for k, v in assay.items():
        rec[k] = v
    rec["source_dataset"] = dataset
    rec["source_file"] = source_file
    return rec


def log_skipped_samples(skipped: set[str], source: str, enabled: bool) -> None:
    """Loudly report matrix/VCF sample ids absent from the metadata Sample set."""
    for s in sorted(skipped):
        log(f"! skip sample {s!r}: not in metadata Sample set ({source})", enabled)
