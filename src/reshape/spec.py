"""Structured reshape specs parsed from a profile's ``reshape:`` block.

The ``reshape:`` block holds only **structural** melt directives — orientation,
feature-id column, feature-id type, unit, ignore-list, assay sub-block, reshaper
``type``. It is deliberately separate from the alias/binding chain: config
describes *shape*, aliases describe *naming*. Parsing lives here so the mapping
loader stays decoupled from the reshaper internals — it carries the raw block,
the reshape door parses it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReshapeSpec:
    """One reshape directive, dispatched by :attr:`type` at the reshape door.

    ``matrix`` fields drive the generic wide-to-long melt; ``vcf`` fields drive
    the dedicated VCF reader. A spec uses only the fields for its ``type``.
    """

    type: str                       # "matrix" | "vcf"
    input: str                      # source filename under data/raw/<dataset>/
    output: str                     # observation-TSV filename under data/interim/<dataset>/

    # ── matrix melt ──
    observation: str = ""           # "expression" | "methylation" (picks the obs contract)
    orientation: str = "genes_x_samples"   # or "samples_x_genes" (never auto-detected)
    feature_id_column: str = ""     # header of the label column (see melt docstring)
    feature_id_type: str = ""       # "ensembl" -> strip version + check; else used as-is
    unit: str = ""                  # stamped onto the unit column when the contract has one
    ignore_columns: tuple[str, ...] = ()    # non-sample/non-feature annotation columns
    assay: dict[str, str] = field(default_factory=dict)   # constant provenance columns

    # ── vcf reader (see src/reshape/vcf.py) ──
    gene_edge_output: str = ""      # IS_WITHIN_GENE edge TSV filename


def _as_tuple(value) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def parse_specs(raw) -> tuple[ReshapeSpec, ...]:
    """Parse a profile's raw ``reshape:`` list into structured :class:`ReshapeSpec`s."""
    specs: list[ReshapeSpec] = []
    for entry in raw or ():
        specs.append(ReshapeSpec(
            type=entry["type"],
            input=entry["input"],
            output=entry.get("output", ""),
            observation=entry.get("observation", ""),
            orientation=entry.get("orientation", "genes_x_samples"),
            feature_id_column=entry.get("feature_id_column", ""),
            feature_id_type=entry.get("feature_id_type", ""),
            unit=entry.get("unit", ""),
            ignore_columns=_as_tuple(entry.get("ignore_columns")),
            assay=dict(entry.get("assay") or {}),
            gene_edge_output=entry.get("gene_edge_output", ""),
        ))
    return tuple(specs)
