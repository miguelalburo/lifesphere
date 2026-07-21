"""Canonical observation-grain contract, shared by both ingest paths.

The GDC extractor (``src/extract/omics/``) and the traditional reshaper
(``src/reshape/``) must emit **byte-identical** observation TSVs. To stop the two
paths silently drifting, the contract they share lives here, in one neutral
module both import:

* the observation column set per observation type
  (:data:`EXPRESSION_OBS_COLUMNS`, :data:`METHYLATION_OBS_COLUMNS`,
  :data:`VARIATION_OBS_COLUMNS`);
* the ``{sample}:{feature}`` surrogate-id minting (:func:`obs_id`);
* unversioned-Ensembl stripping (:func:`strip_version`).

Nothing here does I/O — it is pure data + string helpers.
"""

from __future__ import annotations

# ─────────────────────── Observation column sets ───────────────────────
# Order is significant: it is the TSV column order both paths must reproduce.

EXPRESSION_OBS_COLUMNS: list[str] = [
    "expression_observation_id",
    "sample_id",
    "gene_id",
    "expression_value",
    "expression_unit",
    "assay_id",
    "source_dataset",
    "source_file",
    "pipeline_version",
]

METHYLATION_OBS_COLUMNS: list[str] = [
    "methylation_observation_id",
    "sample_id",
    "cpg_id",
    "beta_value",
    "num_cpg_sites",
    "modification_type",
    "methylation_status",
    "chromosome",
    "start_position",
    "gene_symbol",
    "assay_id",
    "source_dataset",
    "source_file",
    "pipeline_version",
]

VARIATION_OBS_COLUMNS: list[str] = [
    "variant_observation_id",
    "sample_id",
    "variant_id",
    "gene_id",
    "chromosome",
    "position_start",
    "position_end",
    "reference_allele",
    "alternate_allele",
    "variant_class",
    "impact",
    "variant_allele_frequency",
    "tumor_read_count",
    "tumor_variant_count",
    "normal_read_count",
    "normal_variant_count",
    "filter_status",
    "somatic_status",
    "assay_id",
    "source_dataset",
    "source_file",
    "pipeline_version",
]


# ─────────────────────── Surrogate-key minting ───────────────────────

def strip_version(feature_id: str) -> str:
    """Strip an Ensembl version suffix: ``ENSG00000141510.12`` -> ``ENSG00000141510``.

    A key without a dot is returned unchanged. This keeps ``Gene`` a shared
    dimension across the GDC and traditional paths (both drop the version).
    """
    return feature_id.split(".")[0]


def obs_id(sample_id: str, feature_id: str) -> str:
    """Return ``{sample_id}:{feature_id}`` as the observation surrogate key."""
    return f"{sample_id}:{feature_id}"
