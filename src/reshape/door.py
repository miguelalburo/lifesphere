"""The single public reshape entry: ``reshape_dataset(dataset, specs) -> paths``.

The reshape package is one deep door. Matrix-melt and the VCF reader are internal
implementations reachable only through here, dispatched by each spec's ``type``.
There is no standalone reshape CLI and no per-format script — the standardise
flow calls this once, and nothing else touches the internals.

Reshaped observation TSVs are written to ``data/interim/<dataset>/`` and
regenerated (overwritten) each run, so a stale interim file never misleads a
re-load. The single-homed metadata table stays in ``data/raw/``.
"""

from __future__ import annotations

from pathlib import Path

from .. import DATA_INTERIM, DATA_RAW
from .matrix import melt_matrix
from .spec import ReshapeSpec


def reshape_dataset(dataset: str, specs, *, raw_root: Path | None = None,
                    interim_root: Path | None = None,
                    sample_ids: set[str] | None = None, log: bool = True) -> list[Path]:
    """Run every reshape spec for ``dataset``; return the interim TSV paths written.

    ``sample_ids`` is the metadata ``Sample`` set used to reconcile matrix sample
    axes (``None`` disables reconciliation). Dispatch is by ``spec.type``.
    """
    raw_dir = (raw_root or DATA_RAW) / dataset
    interim_dir = (interim_root or DATA_INTERIM) / dataset
    interim_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for spec in specs:
        if not isinstance(spec, ReshapeSpec):
            raise TypeError(f"expected ReshapeSpec, got {type(spec).__name__}")
        if spec.type == "matrix":
            paths.append(melt_matrix(
                spec, raw_dir, interim_dir,
                dataset=dataset, sample_ids=sample_ids, log=log,
            ))
        elif spec.type == "vcf":
            from .vcf import read_vcf
            paths.extend(read_vcf(
                spec, raw_dir, interim_dir,
                dataset=dataset, sample_ids=sample_ids, log=log,
            ))
        else:
            raise ValueError(f"unknown reshape type {spec.type!r} (expected 'matrix' or 'vcf')")
    return paths
