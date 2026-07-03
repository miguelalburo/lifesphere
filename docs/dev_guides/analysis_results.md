# Ingesting Analysis Results (DE / DMP / GWAS)

This guide explains how to feed **analysis results** — differential expression,
differential methylation, and GWAS associations — into the LifeSphere KG. It is written
for whoever prepares the input tables; no code changes are needed to add a new study.

---

## What "analysis results" are, and how they differ from measurements

A raw measurement is an observation of **one sample** (`tpm` of a gene in a sample). An
analysis result is a **statistic computed over a cohort comparison** — a log2 fold change
between tumour and normal, a Δβ between two groups, a variant–trait association across a
cohort. It has no single sample; it belongs to a *contrast*.

So the KG reifies a result the same way it reifies a measurement, but anchored to a
**`Contrast`** instead of a **`Sample`**, and it reuses the *same* shared feature nodes
(`Gene`, `CpGSite`, `Variant`) that the omics layer already populates:

```
(Analysis)-[:PRODUCED]->(Contrast)-[:HAS_DIFFERENTIAL_EXPRESSION] ->(DifferentialExpression) -[:FOR_GENE]   ->(Gene)
                                   -[:HAS_DIFFERENTIAL_METHYLATION]->(DifferentialMethylation)-[:FOR_CPG]    ->(CpGSite)
                                   -[:HAS_ASSOCIATION]             ->(Association)             -[:FOR_VARIANT]->(Variant)
                                                                                               -[:FOR_TRAIT]  ->(Trait)
```

- **`Analysis`** — provenance: the method, tool version, genome build.
- **`Contrast`** — what was compared: the two groups, their sizes, the clinical variable
  stratified on.
- **`Trait`** — GWAS phenotype (ontology-mapped), a shared dimension like `Gene`.

The reshaper runs in **Stage 2 (standardise)**, not extract, because results are a
derived, study-specific layer computed downstream of the harmonised data. Everything is
driven by a manifest — no code, no schema edits.

---

## The two things you provide

Drop both into the dataset directory (the same folder Stage 2 reads, alongside the raw
`{base}.*.tsv` files):

1. **A manifest** — `{base}.analyses.tsv` — one row per (analysis × contrast × result
   table). It carries provenance, the contrast/trait definition, and **the column names
   to read from each result table**.
2. **The result tables themselves** — the raw tool output (DESeq2, limma, REGENIE, …),
   referenced by the manifest's `table` column. These are used as-is; you tell the
   manifest which columns mean what, so you never have to rename tool output.

If no `{base}.analyses.tsv` is present, this whole step is silently skipped.

> **Note on `{base}`** — use the same base prefix as the rest of the dataset (e.g.
> `TCGA.analyses.tsv`). Result-table filenames are free-form but must not collide with a
> real entity name (`gene`, `sample`, …) after the first dot.

---

## The manifest: `{base}.analyses.tsv`

Tab-separated. Columns common to every row:

| Column | Required | Meaning |
|---|---|---|
| `analysis_id` | ✅ | Stable id for the analysis run → `Analysis` node (deduplicated) |
| `contrast_id` | ✅ | Stable id for the comparison → `Contrast` node (deduplicated) |
| `result_type` | ✅ | `differential_expression` \| `differential_methylation` \| `association` |
| `table` | ✅ | Filename of the result table, relative to the dataset dir |
| `method` | | Tool name (DESeq2, limma, REGENIE) → `Analysis.method` |
| `software_version` | | → `Analysis.software_version` |
| `genome_build` | | e.g. `GRCh38` → `Analysis.genome_build` (matters for GWAS coords) |
| `group_a`, `group_b` | | Group labels → `Contrast` |
| `group_a_n`, `group_b_n` | | Group sizes → `Contrast` |
| `stratify_on` | | Clinical variable the contrast is defined over (e.g. `sample_type`) |

Rows sharing an `analysis_id` / `contrast_id` collapse into one node, so you can list
several result tables under the same contrast.

The remaining columns depend on `result_type` and are **column-name mappings** into your
result table — see each section below. Any mapping you omit falls back to a sensible
default (shown in parentheses).

---

## `differential_expression`

One `DifferentialExpression` node per gene, linked to the shared `Gene` node via
`FOR_GENE`.

**Manifest mapping columns** (defaults in parentheses):

| Column | Points at | Default |
|---|---|---|
| `feature_col` | gene id (Ensembl) | `gene_id` |
| `effect_col` | log2 fold change | `log2FoldChange` |
| `pvalue_col` | raw p-value | `pvalue` |
| `padj_col` | adjusted p-value | `padj` |
| `base_mean_col` | mean expression | `baseMean` |
| `lfc_threshold` | \|log2FC\| for direction call | `1.0` |
| `padj_threshold` | significance cut-off | `0.05` |

**Result table** — a standard DESeq2/edgeR/limma table, e.g.:

```
gene_id             baseMean   log2FoldChange   pvalue    padj
ENSG00000141510.17  880.5      2.31             1e-9      3e-8
ENSG00000012048.23  45.2       -3.4             1e-5      2e-4
```

**Derived properties:** `direction` = `up` / `down` / `ns` (from `log2fc` vs
±`lfc_threshold`); `significant` = `true`/`false` (from `padj` vs `padj_threshold`).
Ensembl version suffixes (`.17`) are stripped to match the `Gene` node id space.

---

## `differential_methylation`

One `DifferentialMethylation` node per CpG probe, linked to the shared `CpGSite` node via
`FOR_CPG`.

**Manifest mapping columns:**

| Column | Points at | Default |
|---|---|---|
| `feature_col` | CpG probe id | `cpg` |
| `delta_beta_col` | mean β difference | *(unset)* |
| `effect_col` | limma logFC on M-values | `logFC` |
| `pvalue_col` | raw p-value | `P.Value` |
| `padj_col` | adjusted p-value | `adj.P.Val` |
| `delta_threshold` | magnitude for hyper/hypo call | `0.0` |
| `padj_threshold` | significance cut-off | `0.05` |

**Result table** — a limma/minfi DMP table, e.g.:

```
probe        logFC   delta_beta   P.Value   adj.P.Val
cg00000029   -1.2    -0.28        1e-6      4e-5
cg09999999   0.9     0.19         2e-3      8e-3
```

**Derived properties:** `status` = `hyper` / `hypo` / `ns`. The sign is taken from
`delta_beta_col` when you provide it (preferred — it's the interpretable β difference),
otherwise from `effect_col`. `significant` from `padj` vs `padj_threshold`.

---

## `association` (GWAS)

One `Association` node per variant, linked to the shared `Variant` node via `FOR_VARIANT`
and to a `Trait` node via `FOR_TRAIT`.

**Trait columns** (define the phenotype once per row; deduplicated into `Trait` nodes):

| Column | Meaning |
|---|---|
| `trait_id` | Stable id — EFO/MONDO id or a label (→ `Trait` id) |
| `trait_name` | Human-readable name |
| `trait_source` | Ontology source (e.g. `EFO`) |

**Variant identity** — either give a ready id column, or let the reshaper build the
omics-style coordinate id:

| Column | Points at | Default |
|---|---|---|
| `variant_id_col` | an existing id (rsID or canonical) | *(unset)* |
| `chrom_col` / `pos_col` / `ref_col` / `alt_col` | build `{chrom}:{pos}:{ref}>{alt}` | `chromosome` / `position` / `reference_allele` / `effect_allele` |

**Statistics mapping:**

| Column | Points at | Default |
|---|---|---|
| `effect_col` | beta or odds ratio | `beta` |
| `effect_type` | `beta` or `or` (sets the direction null: 0 or 1) | `beta` |
| `se_col` | standard error | `se` |
| `pvalue_col` | p-value | `pvalue` |
| `effect_allele_col` | effect allele | `effect_allele` |
| `other_allele_col` | other allele | `other_allele` |
| `eaf_col` | effect-allele frequency | `eaf` |
| `n_col` | sample size | `n` |
| `pvalue_threshold` | significance cut-off | `5e-8` |
| `import_max_pvalue` | **import filter** — drop rows above this p-value | *(unset = keep all)* |

**Result table** — REGENIE/PLINK-style summary stats, e.g.:

```
rsid        A1   A2   beta    se     eaf   n       pvalue
rs2981582   A    G    0.21    0.02   0.4   50000   2e-30
rs889312    C    A    -0.09   0.03   0.3   50000   3e-3
```

**Derived properties:** `direction` = `pos` / `neg` / `ns` relative to the null
(`effect_type`); `significant` from `pvalue` vs `pvalue_threshold`.

> **Scale — use `import_max_pvalue`.** Genome-wide summary stats are millions of rows.
> Set `import_max_pvalue` (e.g. `1e-5`) so only hits worth a node enter the graph; keep
> the full file as a `ProcessedDataOutput` pointer. This is the same "big data stays
> external" discipline the single-cell matrix layer uses.

---

## The shared feature dimension (why edges never dangle)

Every result links to a feature node. To keep results **loadable on their own** — analysis
tables are often shared without the raw matrices, and germline GWAS variants never appear
in the somatic set — the reshaper **merges** each referenced feature id into the shared
reference file (`{base}.gene.tsv` / `.cpg_site.tsv` / `.variant.tsv`):

- Existing rows (and columns like gene symbol or variant coordinates) from the omics
  layer are **kept**.
- Feature ids not already present are appended (id only).
- The merge is additive and deduplicated, so re-runs are idempotent.

> **Caveat — variant id space.** GWAS rsIDs and somatic `{chrom}:{pos}:{ref}>{alt}` ids do
> not auto-reconcile: a variant referenced under both keys becomes two `Variant` nodes.
> Normalise upstream (pick rsID *or* coordinates consistently), or map them before ingest.

---

## Running it

Nothing special — the reshaper runs automatically at the start of Stage 2:

```bash
python3 -m src.standardise.run data/raw/<dataset> --out data/standardised/<dataset>
python3 -m src.load.validate   data/standardised/<dataset> --strict   # 0 dangling expected
```

You'll see a line like:

```
analysis reshape: analysis(3) contrast(3) trait(1) differential_expression(2, +1 gene) ...
```

confirming the nodes emitted and how many new feature refs were merged.

---

## Extending to a new result type

The three modalities are registered in `_DISPATCH` in
`src/standardise/analysis_reshape.py`. A new type needs: a small reshaper function, its
result-node entry in `entities.json` + `schema_config.yaml` (as an `is_a: analysis
result` subclass with a **distinct `id_col`**), and its `HAS_*` / `FOR_*` edges in
`edges.json` + `schema_config.yaml` (distinct labels — Stage 1 writes one
`edges/{LABEL}.csv` per entry). See `docs/dev_guides/change_schema.md` for the sync rules.
