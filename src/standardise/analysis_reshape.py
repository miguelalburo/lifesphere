"""Reshape external differential/association result tables into standardiser-ready TSVs.

This is the analysis-result analogue of extract's ``omics_reshape.py`` /
``survival_reshape.py`` — but it runs **inside Stage 2 (standardise)**, not extract,
because analysis results are a *derived, study-specific* layer computed downstream of
the harmonised measurements (a DE table from DESeq2/limma, a DMP table from limma/minfi,
GWAS summary stats from PLINK/REGENIE). GDC ships none of it; it is produced per-study
and dropped into the dataset dir, so the standardiser is the right place to fold it in.

The KG models an analysis result the same way it models a raw measurement — by
**reification** — but anchored to a **Contrast** (a cohort comparison) instead of a
**Sample**, while reusing the *same shared feature dimension* the omics layer populates::

    (Analysis)-[:PRODUCED]->(Contrast)-[:HAS_DIFFERENTIAL_EXPRESSION] ->(DifferentialExpression) -[:FOR_GENE]   ->(Gene)
                                       -[:HAS_DIFFERENTIAL_METHYLATION]->(DifferentialMethylation)-[:FOR_CPG]    ->(CpGSite)
                                       -[:HAS_ASSOCIATION]             ->(Association)             -[:FOR_VARIANT]->(Variant)
                                                                                                   -[:FOR_TRAIT]  ->(Trait)

Each Contrast→result edge has its own label (Stage 1 writes one ``edges/{LABEL}.csv``
per edge schema, so a shared label would collide) — the same pattern the SurvivalOutcome
subclasses use. The ``FOR_*`` feature edges are distinct from the measurement edges
(``OF_GENE``/``AT_CPG``/``OF_VARIANT``) but target the *same* deduplicated feature nodes:
the shared dimension is the node, not the edge name.

To stay loadable standalone (analysis tables are often shared without the raw matrices,
and germline GWAS variants never appear in the somatic set), each referenced feature id
is **merged** into the shared feature-reference TSV (``{base}.gene.tsv`` / ``.cpg_site.tsv``
/ ``.variant.tsv``) — additive and deduplicated, so any omics-populated rows are kept.

Input contract (files placed in the dataset dir):

  * ``{base}.analyses.tsv`` — the **manifest**: one row per (analysis × contrast ×
    result table). Carries provenance + contrast/trait definition + the column names to
    read from the result table. Absent manifest -> no-op (skip), like every reshaper.
  * each ``table`` it references — the raw tool output, one row per feature.

Emitted (into the dataset dir, consumed by the generic engine via entities/edges JSON):

  * ``{base}.analysis.tsv``                 -> Analysis  (dedup analysis_id)
  * ``{base}.contrast.tsv``                 -> Contrast  (dedup contrast_id) + PRODUCED FK
  * ``{base}.trait.tsv``                    -> Trait     (dedup trait_id, GWAS only)
  * ``{base}.differential_expression.tsv``  -> DifferentialExpression  obs nodes + edge FKs
  * ``{base}.differential_methylation.tsv`` -> DifferentialMethylation obs nodes + edge FKs
  * ``{base}.association.tsv``              -> Association            obs nodes + edge FKs

Surrogate ids are deterministic (``de_id = {contrast_id}:{gene}`` etc.) so re-runs are
idempotent. Pure-``csv``; unit-testable on hand-built tables with no network.
"""

import csv
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_MANIFEST_ENTITY = "analyses"

# --- provenance / anchor node columns ---
_ANALYSIS_COLS = ["analysis_id", "method", "software_version", "genome_build"]
_CONTRAST_COLS = ["contrast_id", "analysis_id", "group_a", "group_b",
                  "group_a_n", "group_b_n", "stratify_on"]
_TRAIT_COLS = ["trait_id", "trait_name", "trait_source"]

# --- result observation node columns (id + FKs + stats). entities.json drops the FK
# columns from node properties; edges.json reads them to build the edges. ---
_DE_COLS = ["de_id", "contrast_id", "gene_ensembl", "log2fc", "base_mean",
            "pvalue", "padj", "direction", "significant"]
_DM_COLS = ["dmp_id", "contrast_id", "cpg", "delta_beta", "log2fc",
            "pvalue", "padj", "status", "significant"]
_ASSOC_COLS = ["assoc_id", "contrast_id", "variant_id", "trait_id", "effect",
               "effect_type", "se", "effect_allele", "other_allele", "eaf", "n",
               "pvalue", "direction", "significant"]

# --- shared feature-reference file columns (must match omics_reshape output) ---
_GENE_REF_COLS = ["ensembl", "symbol", "gene_type"]
_CPG_REF_COLS = ["cpg"]
_VARIANT_REF_COLS = ["variant_id", "gene_ensembl", "chromosome", "start_position",
                     "reference_allele", "tumor_allele", "variant_type"]


def _reader(path: Path):
    f = open(path, newline="")
    delim = "," if path.suffix.lower() == ".csv" else "\t"
    return f, csv.DictReader(f, delimiter=delim)


def _writer(path: Path, columns: list[str]):
    f = open(path, "w", newline="")
    w = csv.DictWriter(f, fieldnames=columns, delimiter="\t", extrasaction="ignore")
    w.writeheader()
    return f, w


def _ensembl(gene_id: str) -> str:
    """Strip the version suffix so the FK matches the shared Gene node id space.

    ``ENSG00000000003.15`` -> ``ENSG00000000003`` (same rule omics_reshape applies).
    """
    return (gene_id or "").split(".", 1)[0]


def _float(value: str, default: float | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bucket(value: str, threshold: float, up: str, down: str, mid: str, null: float = 0.0) -> str:
    """Label an effect: >= null+threshold -> up, <= null-threshold -> down, else mid.

    Blank when the value is unparseable. ``null`` recentres for odds ratios (null=1).
    """
    v = _float(value, None)
    if v is None:
        return ""
    if v >= null + threshold:
        return up
    if v <= null - threshold:
        return down
    return mid


def _significant(pvalue: str, threshold: float) -> str:
    v = _float(pvalue, None)
    if v is None:
        return ""
    return "true" if v <= threshold else "false"


def _out_path(in_dir: Path, base: str, entity: str) -> Path:
    return in_dir / (f"{base}.{entity}.tsv" if base else f"{entity}.tsv")


def _find_manifest(in_dir: Path) -> tuple[Path | None, str]:
    """Locate ``{base}.analyses.tsv`` (or ``analyses.tsv``); return (path, base)."""
    for p in sorted(in_dir.glob("*.tsv")) + sorted(in_dir.glob("*.csv")):
        stem = p.stem
        entity = stem.split(".", 1)[1] if "." in stem else stem
        if entity == _MANIFEST_ENTITY:
            base = stem.rsplit(".", 1)[0] if "." in stem else ""
            return p, base
    return None, ""


# --------------------------------------------------------------------------- #
# Per-modality result-table reshapers                                          #
# --------------------------------------------------------------------------- #

def _reshape_de(table_path: Path, m: dict) -> list[dict]:
    """One DifferentialExpression row per gene in a DE result table."""
    lfc_thr = _float(m.get("lfc_threshold"), 1.0)
    padj_thr = _float(m.get("padj_threshold"), 0.05)
    feat_col = m.get("feature_col") or "gene_id"
    eff_col = m.get("effect_col") or "log2FoldChange"
    p_col = m.get("pvalue_col") or "pvalue"
    q_col = m.get("padj_col") or "padj"
    base_col = m.get("base_mean_col") or "baseMean"
    contrast_id = m["contrast_id"]

    rows: list[dict] = []
    f, reader = _reader(table_path)
    try:
        for r in reader:
            ensembl = _ensembl(r.get(feat_col, ""))
            if not ensembl:
                continue
            lfc = r.get(eff_col, "")
            padj = r.get(q_col, "")
            rows.append({
                "de_id": f"{contrast_id}:{ensembl}",
                "contrast_id": contrast_id,
                "gene_ensembl": ensembl,
                "log2fc": lfc,
                "base_mean": r.get(base_col, ""),
                "pvalue": r.get(p_col, ""),
                "padj": padj,
                "direction": _bucket(lfc, lfc_thr, "up", "down", "ns"),
                "significant": _significant(padj, padj_thr),
            })
    finally:
        f.close()
    return rows


def _reshape_dm(table_path: Path, m: dict) -> list[dict]:
    """One DifferentialMethylation row per CpG probe in a DMP result table.

    ``status`` is hyper/hypo/ns from the sign of the methylation change: the effect is
    read from ``delta_beta_col`` when present (mean β difference), else ``effect_col``
    (a limma logFC on M-values).
    """
    delta_thr = _float(m.get("delta_threshold"), 0.0)
    padj_thr = _float(m.get("padj_threshold"), 0.05)
    feat_col = m.get("feature_col") or "cpg"
    delta_col = m.get("delta_beta_col") or ""
    eff_col = m.get("effect_col") or "logFC"
    p_col = m.get("pvalue_col") or "P.Value"
    q_col = m.get("padj_col") or "adj.P.Val"
    contrast_id = m["contrast_id"]

    rows: list[dict] = []
    f, reader = _reader(table_path)
    try:
        for r in reader:
            cpg = (r.get(feat_col, "") or "").strip()
            if not cpg:
                continue
            delta = r.get(delta_col, "") if delta_col else ""
            effect = r.get(eff_col, "")
            padj = r.get(q_col, "")
            signal = delta if delta_col else effect
            rows.append({
                "dmp_id": f"{contrast_id}:{cpg}",
                "contrast_id": contrast_id,
                "cpg": cpg,
                "delta_beta": delta,
                "log2fc": effect,
                "pvalue": r.get(p_col, ""),
                "padj": padj,
                "status": _bucket(signal, delta_thr, "hyper", "hypo", "ns"),
                "significant": _significant(padj, padj_thr),
            })
    finally:
        f.close()
    return rows


def _variant_id(r: dict, m: dict) -> str:
    """Resolve a variant id in the shared Variant space.

    Prefer ``variant_id_col`` (rsID or an already-canonical id); otherwise build the
    omics-style ``{chrom}:{pos}:{ref}>{alt}`` from the coordinate columns. Reconciling
    germline rsIDs with somatic coordinate ids is the caller's responsibility — mismatched
    keys simply create separate Variant reference nodes.
    """
    vid_col = m.get("variant_id_col")
    if vid_col and (r.get(vid_col, "") or "").strip():
        return r[vid_col].strip()
    chrom = r.get(m.get("chrom_col") or "chromosome", "")
    pos = r.get(m.get("pos_col") or "position", "")
    ref = r.get(m.get("ref_col") or "reference_allele", "")
    alt = r.get(m.get("alt_col") or "effect_allele", "")
    return f"{chrom}:{pos}:{ref}>{alt}" if (chrom and pos) else ""


def _reshape_assoc(table_path: Path, m: dict) -> list[dict]:
    """One Association row per variant in a GWAS summary-stats table.

    ``import_max_pvalue`` (optional) filters at import to keep the graph tractable —
    genome-wide summary stats are millions of rows; store only hits worth a node and keep
    the full file as a ProcessedDataOutput. ``effect_type`` (beta|or) recentres the
    direction null (0 for beta, 1 for odds ratios).
    """
    sig_thr = _float(m.get("pvalue_threshold"), 5e-8)
    import_max = _float(m.get("import_max_pvalue"), None)
    effect_type = (m.get("effect_type") or "beta").strip().lower()
    null = 1.0 if effect_type == "or" else 0.0
    eff_col = m.get("effect_col") or "beta"
    se_col = m.get("se_col") or "se"
    p_col = m.get("pvalue_col") or "pvalue"
    ea_col = m.get("effect_allele_col") or "effect_allele"
    oa_col = m.get("other_allele_col") or "other_allele"
    eaf_col = m.get("eaf_col") or "eaf"
    n_col = m.get("n_col") or "n"
    contrast_id = m["contrast_id"]
    trait_id = m.get("trait_id", "")

    rows: list[dict] = []
    f, reader = _reader(table_path)
    try:
        for r in reader:
            variant_id = _variant_id(r, m)
            if not variant_id:
                continue
            pvalue = r.get(p_col, "")
            pv = _float(pvalue, None)
            if import_max is not None and (pv is None or pv > import_max):
                continue
            effect = r.get(eff_col, "")
            rows.append({
                "assoc_id": f"{contrast_id}:{variant_id}",
                "contrast_id": contrast_id,
                "variant_id": variant_id,
                "trait_id": trait_id,
                "effect": effect,
                "effect_type": effect_type,
                "se": r.get(se_col, ""),
                "effect_allele": r.get(ea_col, ""),
                "other_allele": r.get(oa_col, ""),
                "eaf": r.get(eaf_col, ""),
                "n": r.get(n_col, ""),
                "pvalue": pvalue,
                "direction": _bucket(effect, 0.0, "pos", "neg", "ns", null=null),
                "significant": _significant(pvalue, sig_thr),
            })
    finally:
        f.close()
    return rows


# result_type -> (reshaper, output entity name, output columns, id-key for the shared
# feature ref, feature-ref file entity, feature-ref columns)
_DISPATCH = {
    "differential_expression":
        (_reshape_de, "differential_expression", _DE_COLS, "gene_ensembl", "gene", _GENE_REF_COLS, "ensembl"),
    "differential_methylation":
        (_reshape_dm, "differential_methylation", _DM_COLS, "cpg", "cpg_site", _CPG_REF_COLS, "cpg"),
    "association":
        (_reshape_assoc, "association", _ASSOC_COLS, "variant_id", "variant", _VARIANT_REF_COLS, "variant_id"),
}


def _emit(path: Path, columns: list[str], rows) -> None:
    f, w = _writer(path, columns)
    try:
        w.writerows(rows)
    finally:
        f.close()


def _merge_feature_refs(path: Path, id_col: str, ids: set[str], default_cols: list[str]) -> int:
    """Additively merge ``ids`` into a shared feature-reference TSV, deduplicated.

    Preserves any existing rows/columns (e.g. omics-populated symbol/coords); new ids are
    appended id-only. No new ids and an existing file -> left untouched. Returns rows added.
    """
    ids = {i for i in ids if i}
    if not ids:
        return 0
    existing: list[dict] = []
    seen: set[str] = set()
    cols = list(default_cols)
    if path.exists():
        f, reader = _reader(path)
        try:
            cols = reader.fieldnames or list(default_cols)
            for row in reader:
                existing.append(row)
                seen.add(row.get(id_col, ""))
        finally:
            f.close()
    if id_col not in cols:
        cols = [id_col] + cols
    new = [{id_col: i} for i in sorted(ids) if i not in seen]
    if not new and path.exists():
        return 0
    f, w = _writer(path, cols)
    try:
        w.writerows(existing)
        w.writerows(new)
    finally:
        f.close()
    return len(new)


def reshape_analysis(in_dir: Path, base: str | None = None) -> None:
    """Read the analysis manifest in ``in_dir`` and emit the derived entity TSVs.

    Idempotent and skip-tolerant: no manifest -> log skip and return; an unknown
    ``result_type`` or a missing result table is warned and skipped, never fatal.
    """
    in_dir = Path(in_dir)
    manifest, detected_base = _find_manifest(in_dir)
    if manifest is None:
        log.info("! skip analysis reshape: no %s.tsv in %s", _MANIFEST_ENTITY, in_dir)
        return
    base = detected_base if base is None else base

    mf, mreader = _reader(manifest)
    try:
        manifest_rows = list(mreader)
    finally:
        mf.close()

    analyses: dict[str, dict] = {}
    contrasts: dict[str, dict] = {}
    traits: dict[str, dict] = {}
    # result_type -> accumulated result rows
    results: dict[str, list[dict]] = {rt: [] for rt in _DISPATCH}

    for m in manifest_rows:
        result_type = (m.get("result_type") or "").strip()
        if result_type not in _DISPATCH:
            log.warning("  ! analysis reshape: unknown result_type %r — skipping row", result_type)
            continue
        table_path = in_dir / (m.get("table") or "")
        if not m.get("table") or not table_path.exists():
            log.warning("  ! analysis reshape: table %r not found — skipping row", m.get("table"))
            continue

        analyses.setdefault(m["analysis_id"], {
            "analysis_id": m["analysis_id"],
            "method": m.get("method", ""),
            "software_version": m.get("software_version", ""),
            "genome_build": m.get("genome_build", ""),
        })
        contrasts.setdefault(m["contrast_id"], {
            "contrast_id": m["contrast_id"],
            "analysis_id": m["analysis_id"],
            "group_a": m.get("group_a", ""),
            "group_b": m.get("group_b", ""),
            "group_a_n": m.get("group_a_n", ""),
            "group_b_n": m.get("group_b_n", ""),
            "stratify_on": m.get("stratify_on", ""),
        })
        trait_id = (m.get("trait_id") or "").strip()
        if trait_id:
            traits.setdefault(trait_id, {
                "trait_id": trait_id,
                "trait_name": m.get("trait_name", ""),
                "trait_source": m.get("trait_source", ""),
            })

        reshaper = _DISPATCH[result_type][0]
        results[result_type].extend(reshaper(table_path, m))

    _emit(_out_path(in_dir, base, "analysis"), _ANALYSIS_COLS, analyses.values())
    _emit(_out_path(in_dir, base, "contrast"), _CONTRAST_COLS, contrasts.values())
    if traits:
        _emit(_out_path(in_dir, base, "trait"), _TRAIT_COLS, traits.values())

    summary = [f"analysis({len(analyses)})", f"contrast({len(contrasts)})"]
    if traits:
        summary.append(f"trait({len(traits)})")
    for result_type, (_fn, entity, cols, fk_col, feat_entity, feat_cols, feat_id) in _DISPATCH.items():
        rows = results[result_type]
        if not rows:
            continue
        _emit(_out_path(in_dir, base, entity), cols, rows)
        n_feat = _merge_feature_refs(
            _out_path(in_dir, base, feat_entity), feat_id,
            {r[fk_col] for r in rows}, feat_cols,
        )
        summary.append(f"{entity}({len(rows)}, +{n_feat} {feat_entity})")

    log.info("  reshaped analyses -> %s", " ".join(summary))
    print(f"  analysis reshape: {' '.join(summary)}")
