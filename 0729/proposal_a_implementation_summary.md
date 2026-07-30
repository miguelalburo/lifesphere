<!-- title: Proposal A Implementation Summary -->

# Proposal A Implementation Summary

**What this covers:** the schema-config changes landed against `config/schema/nodes.yaml` and `config/schema/edges.yaml`, following [Proposal A](https://claude.ai/code/artifact/bf80d5fd-ed89-485e-aca9-f23ac56f9937) from the v2 diff report — with the MONDO-centric `Disease` rewrite explicitly discarded (TCGA source data is ICD-10, not MONDO), and scoped to schema declarations only, not the ingestion pipeline.

## Decisions locked in before implementation

| Question | Decision |
|---|---|
| Scope | Schema-config only — `config/schema/nodes.yaml`/`edges.yaml` only. `config/mapping/*.yaml`, `src/standardise`, `src/extract` were **not** touched. |
| Rename mechanics | Comment out the old property/pair with an explanation, add the new one as a new line. No line was deleted from either file. |
| `MEASURES_GENE` undocumented pair/property | Dropped from code (aligned to doc) — commented out, not deleted. |
| Properties in code but not in new v2 (`CpGSite.geneSymbol`/`ensemblGeneId`/`genomeBuild`, `Assay.libraryStrategy`) | Kept as intentional LifeSphere extensions, untouched. |
| `Disease` MONDO rewrite | **Discarded per your instruction** — TCGA is ICD-10-coded, not MONDO. `Disease.diseaseId/diseaseType/diseaseName/ontologyId/sourceVocabulary/sourceDataset` is untouched. This is the one Proposal A item deliberately not implemented. |

## Changes made

### `config/schema/nodes.yaml`

| Node | Change |
|---|---|
| `Study` | `diseaseType` → `diseaseCategory` (renamed) |
| `Assay` | `chemistry` → `assayChemistry` (renamed); `libraryStrategy` kept as-is |
| `LibraryPreparation` | `chemistry` → `libraryChemistry` (renamed) |
| `ExperimentalCondition` | `+ sourceDataset` (added) |
| `PhenotypeObservation` | `+ interventionId` (added — mirror for the `RESULTED_IN` edge) |
| `Gene` | `+ referenceGenome`, `+ coordinateSystem` (added) |
| `GenomicRegion` | `start`→`startPosition`, `end`→`endPosition`, `name`→`regionName`, `description`→`regionDescription` (renamed); `+ coordinateSystem` (added) |
| `Variant` | `positionStart`→`startPosition`, `positionEnd`→`endPosition` (renamed, now aligned with `GenomicRegion`/`CpGSite`/`Gene`); `+ coordinateSystem` (added) |
| `CpGSite` | `+ sourceCpgId`, `+ platformCode`, `+ coordinateSystem`, `+ referenceGenome` (added); existing `geneSymbol`/`ensemblGeneId`/`genomeBuild` kept |

Every rename is implemented as: old line commented out in place, immediately followed by the new line — e.g.

```yaml
GenomicRegion:
  id: regionId
  properties:
    - referenceGenome
    - chromosome
    # - start  # renamed -> startPosition, aligned with CpGSite/Gene naming (schema migration: neo4j_updated_schema_new_v2.md §7.4)
    - startPosition
    ...
```

Nodes that only got additions (`Gene`, `CpGSite`, `PhenotypeObservation`, `ExperimentalCondition`) kept every existing property line untouched; new properties were appended with an inline comment marking them as additions.

### `config/schema/edges.yaml`

`MEASURES_GENE`: the undocumented `[MethylationObservation, Gene]` pair and the undocumented `functionalDomain` property are commented out (not deleted), leaving `ExpressionObservation → Gene` with no properties, matching new v2 §5.4/§8.4 exactly.

```yaml
MEASURES_GENE:
  pairs:
    - [ExpressionObservation, Gene]
    # - [MethylationObservation, Gene]  # removed: undocumented pair, not in new_v2 §5.4/§8.4 ...
  properties: []
  # properties: [functionalDomain]  # removed: undocumented property ...
```

**Not changed:** the discarded `Disease` item, and every other node/edge not listed above.

## Verification

- `src/schema.py::load_schema()` loads both files cleanly: **42 nodes, 52 edges, zero validation errors** (was 41/52 before the `CpGSite`/`Gene`/etc. additions — the node count didn't change, only property lists did; 42 was already the count including `Evidence` etc. from the prior reconciliation).
- Confirmed via direct load that every renamed/added property parses to exactly the intended name (spot-checked `GenomicRegion`, `Variant`, `CpGSite`, `Gene`, `Study`, `Assay`, `LibraryPreparation`, `PhenotypeObservation`, `ExperimentalCondition`, and `MEASURES_GENE`).
- Full test suite: **323 passed, 1 failed.**
  - The one failure — `tests/test_variation_integration.py::TestVariationOmicsStandardise::test_variant_properties_populated` — asserts on a CSV column literally named `positionStart`, which no longer exists (it's now `startPosition`). This is the direct, expected consequence of the "schema-config only" scope decision, not a regression introduced by mistake.

## Impact analysis (why "schema-config only" has real consequences, not just cosmetic ones)

Before implementing, I checked what actually populates each changed field, to be upfront about what does and doesn't work today:

- **`GenomicRegion`**: not populated by any current mapping config — this node isn't emitted by any pipeline yet. The renames/additions have **zero functional impact** right now.
- **`Gene` / `CpGSite`**: documented in `config/mapping/omics.yaml` as "dedup reference dimensions — only the id column is populated here; full annotation comes from reference sources" (i.e., these are known-incomplete already). The additions have **zero functional impact** until that reference-annotation ingestion exists.
- **`Variant.startPosition`/`endPosition`**: this is the one with a real, immediate effect. `src/reshape/vcf.py` emits raw columns named `position_start`/`position_end`; the standardise engine's automatic snake_case→camelCase alias pass turns that into `positionStart`, which matched the old schema name exactly. It does **not** produce `startPosition`. So as of this change, **`Variant.startPosition` will be emitted as an empty column** by the TCGA VCF pipeline until an explicit alias (`positionStart: startPosition` or equivalent) is added to `config/mapping/traditional.yaml` — this is exactly the kind of follow-up the "schema-config only" scope deferred.
- **`Study.diseaseCategory`, `Assay.assayChemistry`, `LibraryPreparation.libraryChemistry`**: `config/mapping/extract.yaml` already documents `diseaseType`/`primarySite` as a known GDC gap ("no GDC source column"); no current mapping sets `chemistry` either. These renames land on fields that weren't being actively populated from TCGA/GDC, so there's no working alias to break — but they also won't populate under the new names without mapping work either.
- **`PhenotypeObservation.interventionId`, `ExperimentalCondition.sourceDataset`**: pure additions on nodes with partial or no existing mapping coverage for these specific fields — safe, no working alias broken.
- **`MEASURES_GENE`**: confirmed via `config/mapping/omics.yaml` that the `MethylationObservation→Gene` pair and `functionalDomain` property were never emitted by any mapping config in the first place — this was genuinely dead schema, zero pipeline impact from removing it.

## Follow-up work (deferred by the "schema-config only" scope choice)

1. Fix `tests/test_variation_integration.py:187` to assert on `startPosition` instead of `positionStart`.
2. Add a `positionStart → startPosition` (and `positionEnd → endPosition`) alias to `config/mapping/traditional.yaml` so the VCF pipeline actually populates the renamed `Variant` columns again — without this, `Variant.startPosition`/`endPosition` will silently come out empty on the next pipeline run.
3. Decide whether `Study.diseaseCategory` and `Assay.assayChemistry`/`LibraryPreparation.libraryChemistry` need new GDC source bindings in `config/mapping/extract.yaml`/`omics.yaml`, or remain aspirational columns until a source exists (same status as before the rename, since neither was wired before).
4. When `Gene`/`CpGSite` reference-annotation ingestion is eventually built, include `referenceGenome`, `coordinateSystem`, `sourceCpgId`, and `platformCode` in that work.
5. The MONDO-centric `Disease` rewrite remains an open item from the original migration plan — revisit only if/when a non-TCGA, MONDO-coded dataset is added; for an ICD-10 source, the current `Disease` shape is the right one and shouldn't change.
