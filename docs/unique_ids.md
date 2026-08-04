# Unique ID standard

_Last updated: 2026-08-04_

How every node's primary key (`id`, `sampleId`, `expressionObservationId`, ...)
gets its value. See [GitHub issue #69](https://github.com/miguelalburo/lifesphere/issues/69)
for the motivating problem: most ids are copied verbatim from a source column,
but a handful have to be **minted** — created from scratch, because no single
source column is a stable, unique key for that grain — and different parts of
the pipeline used to mint them differently. This document is the one standard;
`src/observation.py` is where it lives in code.

## 1. Two kinds of id

| Kind | Definition | Example |
|------|------------|---------|
| **Natural** | Copied as-is from one source column that is already a stable, unique key for the node's grain. | `Sample.sampleId` <- GDC aliquot UUID; `Gene.geneId` <- Ensembl id |
| **Minted** | Built by the pipeline because no single source column is unique/stable enough on its own. | `ExpressionObservation.expressionObservationId` (no such column exists in a GDC STAR-Counts file — the grain is one row *per gene per sample*, so the id has to say which) |

Most nodes are natural keys and need no minting logic at all. This document
covers the minted ones only.

## 2. The minting standard

**A minted id is a plain concatenation of its required-present source values,
in a fixed order, joined by a separator — never a hash, never a generated
UUID.** Concatenation keeps ids human-readable and traceable back to their
inputs, which matters for debugging a knowledge graph; a hash or uuid would
hide that provenance and buys nothing here (uniqueness only has to hold across
the fields already chosen for the grain, not across arbitrary strings).

The default separator is **`:`** (colon). Everything that mints an id goes
through one function:

```python
# src/observation.py
def mint_id(*parts: str, sep: str = ID_SEPARATOR) -> str:
    return sep.join(parts)
```

`obs_id(sample_id, feature_id)` — the observation surrogate key — is just
`mint_id` with two required arguments; it exists because it is by far the most
common composition (every omics observation type keys off `sample:feature`).

There is exactly **one** documented exception to the `:` default — see §4.

### Presence rule

A minted id may only be built from values that are **required** for that
row/entry — never treated as optional. What happens when a required value is
actually missing differs by minting site, though, because the two sites are
minting different grains:

* **Standardise-time** (`DERIVED_KEYS`, §3a): if any source column is
  missing/empty on a row, `_mint()` cannot build the id, and the **whole row
  is dropped** — not written with a blank id — because a blank id can't dedupe
  or link. One observation row missing its gene id is one dropped observation;
  dropping the rest of the file over it would be wrong.
* **Extract-time** (`assay_id()` functions, §3b): these mint one id per
  *source file*, not per observation row, from GDC file-metadata fields that
  are normally always present. A single missing field there (e.g. an
  unexpected blank `platform`) falls back to the literal `"unknown"` for that
  segment rather than dropping every observation in the file — losing an
  entire file's worth of measurements over one metadata gap would be a much
  larger loss than losing one row. This predates the standard and is
  unchanged by it; it's noted here so the rule above isn't read as uniform
  across both sites.

## 3. Where minting happens: registry vs extract-time

There are two places a minted id can be built, and which one applies is
decided by one question: **are all of the id's source columns already present
on the row being standardised?**

### 3a. Standardise-time — `observation.DERIVED_KEYS` (preferred)

If yes, the id is minted by the `standardise` engine itself, from
`DERIVED_KEYS` — a profile-independent registry in `src/observation.py` mapping
a node label to the source columns and the function that combines them:

```python
DERIVED_KEYS: dict[str, KeyBuilder] = {
    "ExpressionObservation": KeyBuilder(("sample_id", "gene_id"), obs_id),
    "MethylationObservation": KeyBuilder(("sample_id", "cpg_id"), obs_id),
    "VariantObservation": KeyBuilder(("sample_id", "variant_id"), obs_id),
    "Survival": KeyBuilder(("case_id", "survival_type"), mint_id),
}
```

When a node label is in `DERIVED_KEYS`, `standardise` (`src/standardise/run.py`
`_write_node`/`_write_edge`) **ignores whatever id string the raw file
holds** and re-mints the id itself from the row's own columns — for both the
node and any edge endpoint pointing at it. This is the strongest guarantee:
the id is byte-identical no matter which extractor/reshaper produced the file,
and no matter what (possibly stale or wrong) value sits in the file's own id
column. The mapping profile's `key:`/`start_key:`/`end_key:` entries for these
labels are kept only as documentation of which raw column the id happens to
populate — changing them does not change how the id is minted.

This is preferred whenever it's possible. Prefer it for any new minted id
whose source columns are already carried on the row.

### 3b. Extract-time (fallback)

If a required source value is **not** carried on the observation row — it only
exists further upstream, e.g. in GDC file-metadata — the id has to be minted
where that value is still available: in the extractor/reshaper, before the row
is ever written. `standardise` then trusts that column verbatim (same as any
natural key).

This is the case for `Assay.assayId`: it's built from `platform`,
`experimental_strategy`, and `analysis.workflow_type`, none of which are
columns on `expression_observation.tsv` / `methylation_observation.tsv` /
`variation_observation.tsv` (only the finished `assay_id` is). Adding those
three columns to the observation contract just to move this one id into
`DERIVED_KEYS` isn't worth the churn — the extract-time functions all still go
through `mint_id`, so the id's *format* follows the standard even though its
*minting site* doesn't move.

## 4. Full inventory of minted ids

| Node / edge endpoint | Fields (in order) | Separator | Built by | Site |
|---|---|---|---|---|
| `ExpressionObservation.expressionObservationId` | `sample_id`, `gene_id` | `:` | `obs_id` via `DERIVED_KEYS` | standardise |
| `MethylationObservation.methylationObservationId` | `sample_id`, `cpg_id` | `:` | `obs_id` via `DERIVED_KEYS` | standardise |
| `VariantObservation.variantObservationId` | `sample_id`, `variant_id` | `:` | `obs_id` via `DERIVED_KEYS` | standardise |
| `Survival.survivalId` | `case_id`, `survival_type` | `:` | `mint_id` via `DERIVED_KEYS` | standardise |
| `Assay.assayId` (expression/variation) | `platform`, `experimental_strategy`, `analysis.workflow_type` | `:` | shared `observation.gdc_assay_id` (`mint_id` under the hood), called from `extract/omics/expression.py` and `variation.py` | extract |
| `Assay.assayId` (methylation) | `platform`, `experimental_strategy`, literal `"Methylation Beta Value"` | `:` | `mint_id` in `extract/omics/methylation.py` | extract |
| `Variant.variantId` (GDC path) | `chromosome`, `position`, `reference_allele`, `alternate_allele` | `:` | `mint_id` in `extract/omics/variation.py` | extract |
| `Variant.variantId` (traditional VCF path) | `chromosome`, `position`, `reference_allele`, `alternate_allele` | **`-`** (exception, see below) | `mint_id(..., sep="-")` in `src/reshape/vcf.py` | reshape |
| `Assay.assayId` (traditional path) | n/a — a fixed literal (`traditional-rnaseq-grch38`, `traditional-wgs-grch38`), not a concatenation | n/a | `config/mapping/traditional.yaml` `stamp_row` | reshape config |

### The one deliberate exception: two Variant id-spaces

GDC-path variants (`chrom:pos:ref:alt`) and traditional-VCF-path variants
(`chrom-pos-ref-alt`) use different separators **on purpose**, and this
document preserves that choice rather than quietly aligning it away. It
predates this standard: `src/reshape/vcf.py`'s module docstring already called
the dash form "an accepted, documented consequence" before this document
existed, on the reasoning that the two paths call variants with different
pipelines/callers, and a traditional-path variant shouldn't silently
`MERGE`-collide into a GDC-path `Variant` node just because it happens to
describe the same chromosome/position/alleles. Keeping the separator different
keeps the two id-spaces structurally disjoint by construction, with zero
runtime cost.

This is a real, standing domain decision, not a settled-forever one — it's
recorded here so it's visible and can be revisited deliberately (e.g. if
cross-cohort analysis ever needs the two paths to share `Variant` identity),
rather than being "fixed" as an accidental side effect of some later id-format
cleanup. If it's ever revisited and the two paths should merge, `Variant`
becomes eligible for `DERIVED_KEYS` (§3a) at that point, since its source
columns (`chromosome`, `position_start`, `reference_allele`,
`alternate_allele`) are already present on every variation observation row
from both paths.

## 5. Adding a new minted id

1. Can the id be built from columns already present on the row it lives on
   (or, for an edge, on the row of the endpoint node)? If yes, add an entry to
   `DERIVED_KEYS` (§3a) — that's the strongest guarantee and the default
   choice.
2. If not, mint it at extract/reshape time via `mint_id(...)`, and add a row to
   the table in §4.
3. Use the default `:` separator unless there is a specific, documented reason
   two id-spaces must never collide (§4's exception) — don't introduce a new
   separator for aesthetic reasons alone.
4. Never use a hash or a generated UUID for a minted id — see §2.
