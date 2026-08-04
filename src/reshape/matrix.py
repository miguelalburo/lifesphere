"""Generic wide-matrix melt into canonical observation-grain TSVs.

One melt drives both expression (now) and methylation (later): the observation
type only selects which canonical column set and which id/feature/value/unit
columns are populated. Reuses the shared observation contract
(:mod:`src.observation`) so a traditional matrix cannot drift from the GDC path.

Orientation is declared, never auto-detected:

* ``genes_x_samples`` (default) — features on rows, samples on columns. The
  ``feature_id_column`` holds the feature id; every other header (minus
  ``ignore_columns``) is a sample.
* ``samples_x_genes`` — samples on rows, features on columns. The
  ``feature_id_column`` here labels the *sample* column (row identifiers); every
  other header (minus ``ignore_columns``) is a feature id.

Sample ids are reconciled against the metadata ``Sample`` set: an id absent from
that set is reported as a loud ``! skip`` and dropped, never silently emitted
into a dangling edge. Passing ``sample_ids=None`` disables reconciliation.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ..observation import (
    EXPRESSION_OBS_COLUMNS,
    METHYLATION_OBS_COLUMNS,
    mint_id,
    obs_id,
    strip_version,
)
from ._common import log as _log, log_skipped_samples, observation_fieldnames, stamp_row
from .spec import ReshapeSpec


@dataclass(frozen=True)
class _ObsProfile:
    """Which canonical columns carry the id / feature / value / unit for a type."""
    columns: list[str]
    id_column: str
    feature_column: str
    value_column: str
    unit_column: str | None


_OBS_PROFILES: dict[str, _ObsProfile] = {
    "expression": _ObsProfile(
        EXPRESSION_OBS_COLUMNS, "expression_observation_id",
        "gene_id", "expression_value", "expression_unit",
    ),
    "methylation": _ObsProfile(
        METHYLATION_OBS_COLUMNS, "methylation_observation_id",
        "cpg_id", "beta_value", None,
    ),
}


def _feature_id(raw: str, feature_id_type: str, warned: set[str], log: bool) -> str:
    """Normalise a feature id per the declared type.

    ``ensembl`` strips the version suffix via the shared contract; a key that
    does not look like an Ensembl accession raises a loud (once-per-key) warning
    so symbol/Entrez matrices are caught. Any other type is used as-is (CpG
    probe ids are already the shared ``CpGSite`` dimension).
    """
    raw = raw.strip()
    if feature_id_type == "ensembl":
        if not raw.upper().startswith("ENS") and raw not in warned:
            warned.add(raw)
            _log(f"! warning: feature id {raw!r} does not look like an Ensembl id "
                 f"(feature_id_type: ensembl) — symbol/Entrez matrices need upstream remapping", log)
        return strip_version(raw)
    return raw


def melt_matrix(spec: ReshapeSpec, raw_dir: Path, interim_dir: Path, *, dataset: str,
                sample_ids: set[str] | None = None, log: bool = True) -> Path:
    """Melt one wide matrix to its canonical observation TSV; return the output path."""
    profile = _OBS_PROFILES.get(spec.observation)
    if profile is None:
        raise ValueError(f"unknown observation type {spec.observation!r} "
                         f"(expected one of {sorted(_OBS_PROFILES)})")

    src = raw_dir / spec.input
    out_path = interim_dir / (spec.output or f"{spec.observation}_observation.tsv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        # A traditional dataset may not carry every declared matrix. Skip loudly
        # and clear any stale interim output so a re-load never reads it.
        _log(f"! skip matrix {spec.input}: source not found in raw", log)
        if out_path.exists():
            out_path.unlink()
        return out_path

    fieldnames = observation_fieldnames(profile.columns, spec.assay)
    ignore = set(spec.ignore_columns)
    warned: set[str] = set()
    skipped_samples: set[str] = set()

    with src.open(newline="", encoding="utf-8") as fh, \
            out_path.open("w", newline="", encoding="utf-8") as out_fh:
        reader = csv.reader(fh, delimiter="\t")
        writer = csv.DictWriter(out_fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()

        header = next(reader, None) or []
        if spec.feature_id_column not in header:
            _log(f"! skip matrix {spec.input}: label column "
                 f"{spec.feature_id_column!r} not in header", log)
            return out_path
        label_idx = header.index(spec.feature_id_column)

        def emit(sample: str, feature: str, value: str) -> None:
            if not value.strip():
                return
            rec = stamp_row(fieldnames, spec.assay, dataset=dataset, source_file=spec.input)
            rec["sample_id"] = sample
            if spec.observation == "methylation":
                # CpGSite.cpgId is namespace-qualified by platform (see
                # docs/unique_ids.md §4) so probe ids from different array
                # platforms never collide into one CpGSite node. A dataset
                # without a declared assay.platform_code falls back to
                # "unknown", matching the GDC path's own missing-platform
                # fallback (src/extract/omics/methylation.py).
                plat_code = spec.assay.get("platform_code", "unknown")
                rec["source_cpg_id"] = feature
                rec[profile.feature_column] = mint_id(plat_code, feature)
            else:
                rec[profile.feature_column] = feature
            rec[profile.id_column] = obs_id(sample, rec[profile.feature_column])
            rec[profile.value_column] = value
            if profile.unit_column:
                rec[profile.unit_column] = spec.unit
            writer.writerow(rec)

        if spec.orientation == "samples_x_genes":
            # rows = samples; feature ids are the column headers.
            feature_cols = [(i, h) for i, h in enumerate(header)
                            if i != label_idx and h not in ignore]
            for row in reader:
                if not row:
                    continue
                sample = row[label_idx].strip()
                if not sample:
                    continue
                if sample_ids is not None and sample not in sample_ids:
                    skipped_samples.add(sample)
                    continue
                for ci, feat_raw in feature_cols:
                    if ci >= len(row):
                        continue
                    feature = _feature_id(feat_raw, spec.feature_id_type, warned, log)
                    emit(sample, feature, row[ci])
        else:
            # genes_x_samples (default): rows = features; samples are the headers.
            sample_cols = [(i, h) for i, h in enumerate(header)
                           if i != label_idx and h not in ignore]
            kept = []
            for ci, sname in sample_cols:
                s = sname.strip()
                if sample_ids is not None and s not in sample_ids:
                    skipped_samples.add(s)
                    continue
                kept.append((ci, s))
            for row in reader:
                if not row:
                    continue
                feature = _feature_id(row[label_idx], spec.feature_id_type, warned, log)
                if not feature:
                    continue
                for ci, sample in kept:
                    if ci >= len(row):
                        continue
                    emit(sample, feature, row[ci])

    log_skipped_samples(skipped_samples, spec.input, log)
    return out_path
