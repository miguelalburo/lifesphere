"""Reshape raw concatenated omics matrices into standardiser-ready TSVs.

``omics.py`` downloads and vertically concatenates every open-access file of a type
into one flat matrix (``{base}.{type}.tsv``) keyed by ``case_id`` / ``file_id`` /
``aliquot_id``. That flat matrix is *not* the shape the standardiser consumes: the KG
model reifies each measurement into a per-assay **observation node** wired between a
**Sample** (= aliquot) and a shared **feature node** (Gene / CpGSite / Variant).

This module bridges that gap — a source-format-specific post-process (the same role
``biospecimen.py`` plays for samples) that splits each matrix into:

  * a deduplicated **feature reference** TSV  (``{base}.gene.tsv``, ``.cpg_site.tsv``,
    ``.variant.tsv``) — the shared dimension, and
  * an **observation** TSV (``{base}.gene_expression.tsv``, ``.methylation.tsv``,
    ``.somatic_mutation.tsv``) carrying a deterministic surrogate id, the
    ``sample_id`` (aliquot) it was measured on, the feature FK, and the measurement
    values.

Those file names match the entity names in ``config/schemas/entities.json`` /
``edges.json``, so the generic standardiser then emits the observation node plus both
of its edges (Sample→Observation→Feature) with no engine change. Surrogate ids are
deterministic (``{file_id}:{feature}``) so re-runs are idempotent.

Pure-``csv``; safe to unit-test on hand-built matrices with no network.
"""

import csv
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# One (feature_file, observation_file) pair per omics type; matched to schema names.
_OUTPUTS = {
    "expression":  ("gene",      "gene_expression"),
    "methylation": ("cpg_site",  "methylation"),
    "variation":   ("variant",   "somatic_mutation"),
}


def _reader(path: Path):
    f = open(path, newline="")
    return f, csv.DictReader(f, delimiter="\t")


def _writer(path: Path, columns: list[str]):
    f = open(path, "w", newline="")
    w = csv.DictWriter(f, fieldnames=columns, delimiter="\t", extrasaction="ignore")
    w.writeheader()
    return f, w


def _ensembl(gene_id: str) -> str:
    """Strip the GDC version suffix: ``ENSG00000000003.15`` -> ``ENSG00000000003``."""
    return (gene_id or "").split(".", 1)[0]


# --------------------------------------------------------------------------- #
# Expression                                                                   #
# --------------------------------------------------------------------------- #

_GENE_COLS = ["ensembl", "symbol", "gene_type"]
_EXPR_COLS = ["expression_id", "sample_id", "gene_ensembl",
              "tpm", "fpkm", "fpkm_uq", "unstranded", "file_id"]


def reshape_expression(concat_path: Path, out_dir: Path, base: str) -> tuple[int, int]:
    gene_path = out_dir / f"{base}.gene.tsv"
    obs_path = out_dir / f"{base}.gene_expression.tsv"
    seen_genes: set[str] = set()
    n_genes = n_obs = 0

    rin, reader = _reader(concat_path)
    gf, gene_w = _writer(gene_path, _GENE_COLS)
    of, obs_w = _writer(obs_path, _EXPR_COLS)
    try:
        for row in reader:
            ensembl = _ensembl(row.get("gene_id", ""))
            if not ensembl:
                continue
            if ensembl not in seen_genes:
                seen_genes.add(ensembl)
                gene_w.writerow({"ensembl": ensembl, "symbol": row.get("gene_name", ""),
                                 "gene_type": row.get("gene_type", "")})
                n_genes += 1
            file_id = row.get("file_id", "")
            obs_w.writerow({
                "expression_id": f"{file_id}:{ensembl}",
                "sample_id": row.get("aliquot_id", ""),
                "gene_ensembl": ensembl,
                "tpm": row.get("tpm_unstranded", ""),
                "fpkm": row.get("fpkm_unstranded", ""),
                "fpkm_uq": row.get("fpkm_uq_unstranded", ""),
                "unstranded": row.get("unstranded", ""),
                "file_id": file_id,
            })
            n_obs += 1
    finally:
        rin.close(); gf.close(); of.close()
    return n_genes, n_obs


# --------------------------------------------------------------------------- #
# Methylation                                                                  #
# --------------------------------------------------------------------------- #

_CPG_COLS = ["cpg"]
_METH_COLS = ["methylation_id", "sample_id", "cpg", "beta_value", "file_id"]


def reshape_methylation(concat_path: Path, out_dir: Path, base: str) -> tuple[int, int]:
    cpg_path = out_dir / f"{base}.cpg_site.tsv"
    obs_path = out_dir / f"{base}.methylation.tsv"
    seen_cpg: set[str] = set()
    n_cpg = n_obs = 0

    rin, reader = _reader(concat_path)
    cf, cpg_w = _writer(cpg_path, _CPG_COLS)
    of, obs_w = _writer(obs_path, _METH_COLS)
    try:
        for row in reader:
            cpg = row.get("cpg", "")
            if not cpg:
                continue
            if cpg not in seen_cpg:
                seen_cpg.add(cpg)
                cpg_w.writerow({"cpg": cpg})
                n_cpg += 1
            file_id = row.get("file_id", "")
            obs_w.writerow({
                "methylation_id": f"{file_id}:{cpg}",
                "sample_id": row.get("aliquot_id", ""),
                "cpg": cpg,
                "beta_value": row.get("beta_value", ""),
                "file_id": file_id,
            })
            n_obs += 1
    finally:
        rin.close(); cf.close(); of.close()
    return n_cpg, n_obs


# --------------------------------------------------------------------------- #
# Variation (MAF)                                                              #
# --------------------------------------------------------------------------- #

_VARIANT_COLS = ["variant_id", "gene_ensembl", "chromosome", "start_position",
                 "reference_allele", "tumor_allele", "variant_type"]
_CALL_COLS = ["variant_call_id", "sample_id", "variant_id", "hugo_symbol",
              "consequence", "impact", "variant_classification",
              "vaf", "t_depth", "t_alt_count", "file_id"]


def _vaf(t_alt: str, t_depth: str) -> str:
    try:
        depth = int(t_depth)
        return f"{int(t_alt) / depth:.4f}" if depth else ""
    except (TypeError, ValueError):
        return ""


def reshape_variation(concat_path: Path, out_dir: Path, base: str) -> tuple[int, int]:
    variant_path = out_dir / f"{base}.variant.tsv"
    obs_path = out_dir / f"{base}.somatic_mutation.tsv"
    seen_variants: set[str] = set()
    n_var = n_obs = 0

    rin, reader = _reader(concat_path)
    vf, var_w = _writer(variant_path, _VARIANT_COLS)
    of, obs_w = _writer(obs_path, _CALL_COLS)
    try:
        for i, row in enumerate(reader):
            chrom = row.get("Chromosome", "")
            pos = row.get("Start_Position", "")
            ref = row.get("Reference_Allele", "")
            alt = row.get("Tumor_Seq_Allele2", "")
            if not (chrom and pos):
                continue
            variant_id = f"{chrom}:{pos}:{ref}>{alt}"
            gene_ensembl = _ensembl(row.get("Gene", ""))
            if variant_id not in seen_variants:
                seen_variants.add(variant_id)
                var_w.writerow({
                    "variant_id": variant_id,
                    "gene_ensembl": gene_ensembl,
                    "chromosome": chrom,
                    "start_position": pos,
                    "reference_allele": ref,
                    "tumor_allele": alt,
                    "variant_type": row.get("Variant_Type", ""),
                })
                n_var += 1
            file_id = row.get("file_id", "")
            # Per-row tumour aliquot is the sample linkage for MAF; fall back to the
            # file-level aliquot captured at download time.
            sample_id = row.get("Tumor_Sample_UUID", "") or row.get("aliquot_id", "")
            obs_w.writerow({
                "variant_call_id": f"{file_id}:{i}",
                "sample_id": sample_id,
                "variant_id": variant_id,
                "hugo_symbol": row.get("Hugo_Symbol", ""),
                "consequence": row.get("Consequence", ""),
                "impact": row.get("IMPACT", ""),
                "variant_classification": row.get("Variant_Classification", ""),
                "vaf": _vaf(row.get("t_alt_count", ""), row.get("t_depth", "")),
                "t_depth": row.get("t_depth", ""),
                "t_alt_count": row.get("t_alt_count", ""),
                "file_id": file_id,
            })
            n_obs += 1
    finally:
        rin.close(); vf.close(); of.close()
    return n_var, n_obs


_RESHAPERS = {
    "expression": reshape_expression,
    "methylation": reshape_methylation,
    "variation": reshape_variation,
}


def reshape_omics_type(omics_type: str, concat_path: Path, out_dir: Path, base: str) -> None:
    """Reshape one concatenated matrix into its feature + observation TSVs."""
    if omics_type not in _RESHAPERS:
        raise ValueError(f"no reshaper for omics type {omics_type!r}")
    if not concat_path.exists():
        log.warning("reshape %s: %s not found — skipping", omics_type, concat_path.name)
        return
    feat_name, obs_name = _OUTPUTS[omics_type]
    n_feat, n_obs = _RESHAPERS[omics_type](concat_path, out_dir, base)
    log.info("  reshaped %s -> %s (%d) + %s (%d)",
             concat_path.name, f"{base}.{feat_name}.tsv", n_feat,
             f"{base}.{obs_name}.tsv", n_obs)


def reshape_omics(out_dir: Path, base: str, omics_types: list[str]) -> None:
    """Reshape every requested type's concatenated matrix found in ``out_dir``."""
    for omics_type in omics_types:
        reshape_omics_type(omics_type, out_dir / f"{base}.{omics_type}.matrix.tsv", out_dir, base)
