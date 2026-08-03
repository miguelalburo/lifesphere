"""Canonical observation-grain contract, shared by both ingest paths.

The GDC extractor (``src/extract/omics/``) and the traditional reshaper
(``src/reshape/``) must emit **byte-identical** observation TSVs. To stop the two
paths silently drifting, the contract they share lives here, in one neutral
module both import:

* the observation column set per observation type
  (:data:`EXPRESSION_OBS_COLUMNS`, :data:`METHYLATION_OBS_COLUMNS`,
  :data:`VARIATION_OBS_COLUMNS`);
* the ``{sample}:{feature}`` surrogate-id minting (:func:`obs_id`);
* unversioned-Ensembl stripping (:func:`strip_version`);
* the :data:`DERIVED_KEYS` registry — the single, profile-independent place that
  says how each *created* node id is minted from its source columns, so the
  standardise engine mints them itself rather than trusting whatever id string an
  upstream path happened to write.

Nothing here does I/O — it is pure data + string helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

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


def is_zero(value: str | None) -> bool:
    """Return True if *value* parses as a float equal to exactly 0.

    Empty/missing/non-numeric values return False (they are "absent", not
    "zero", and stay subject to the usual missing-data handling).
    """
    if not value:
        return False
    try:
        return float(value) == 0.0
    except ValueError:
        return False


# A zero reading in these raw (snake_case) source columns is disregarded
# everywhere the row would otherwise contribute — a whole source row is
# dropped, not just the value blanked. Both ingest paths (the GDC extractor's
# own reshape() and the traditional matrix reshape feeding standardise) fan
# out from the same observation TSV into a node and multiple edges, so this
# must be enforced at the row level and applied identically to every node/edge
# reader of that file — dropping the observation node alone while still
# writing its edges would leave dangling references.
#
# expression_value == 0 means "gene not detected in this sample" — with
# ~60k genes x every sample, most rows are this and uninformative at graph
# scale, so they're excluded. beta_value == 0 is a real, meaningful "fully
# unmethylated" reading (methylation beta values are genuinely bimodal at 0/1)
# rather than a missing/uninformative one, so it is deliberately NOT included
# here — see CLAUDE.md / the schema docs for the domain rationale if this ever
# needs revisiting.
ZERO_EXCLUDED_COLUMNS: frozenset[str] = frozenset({"expression_value"})


# ─────────────────────── Derived-key registry ───────────────────────
# Some node ids are *created* (minted by concatenating other columns), not copied
# from a stable natural key. Those are the ones that historically diverged between
# the GDC and traditional paths — each minted them inline, its own way.
#
# The fix is to mint created ids in exactly one place: standardise reads this
# registry and builds the id itself, from the row's *required-present* raw columns,
# via one shared function per label. The id therefore no longer depends on which
# path produced the file, nor on the mapping profile (this lives in code, not YAML).
#
# Invariant: an entry lists the raw columns its id is built from (all must be
# present and non-empty in a row) and the function that maps their values, in
# order, to the id string. Per-label logic may differ; each label is defined once.
#
# Scope note: only the observation surrogate keys are registered for now — their
# ``obs_id`` composition is already agreed and identical on both paths, so routing
# it through here is a pure refactor. The other created keys (``Variant``,
# ``Assay``) still differ in *format* between paths (colon-vs-dash, pipe-vs-
# hardcoded); unifying those is a follow-up once the team fixes the id standard,
# and is a one-line addition here when that scheme is decided.

@dataclass(frozen=True)
class KeyBuilder:
    """How standardise mints one created node id from a source row.

    ``sources`` are the raw (snake_case) columns the id is built from; the engine
    requires every one present and non-empty before minting. ``build`` maps those
    column values, in ``sources`` order, to the id string.
    """
    sources: tuple[str, ...]
    build: Callable[..., str]

    def mint(self, values: list[str]) -> str:
        return self.build(*values)


DERIVED_KEYS: dict[str, KeyBuilder] = {
    "ExpressionObservation": KeyBuilder(("sample_id", "gene_id"), obs_id),
    "MethylationObservation": KeyBuilder(("sample_id", "cpg_id"), obs_id),
    "VariantObservation": KeyBuilder(("sample_id", "variant_id"), obs_id),
}
