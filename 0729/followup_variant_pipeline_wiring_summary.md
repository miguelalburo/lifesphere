<!-- title: Proposal A Follow-Up: Variant Pipeline Wiring -->

# Proposal A Follow-Up: Variant Pipeline Wiring

**What this covers:** the three deferred follow-up items from the [Proposal A Implementation Summary](https://claude.ai/code/artifact/8bb3ea16-f086-4f4e-996f-065290147055) — restoring `Variant.startPosition`/`endPosition` population after the earlier schema rename, and closing out the `diseaseCategory`/`assayChemistry`/`libraryChemistry` question.

## Decision locked in before implementation

A pre-implementation check surfaced a scope problem with the original request ("add the alias to `config/mapping/traditional.yaml`"): the currently-failing test, and the real TCGA production pipeline, both run GDC variation data through `--profile omics` directly (`scripts/submit_standardise_TCGA.sh`), not through `traditional.yaml`. `src/extract/omics/variation.py` (GDC) and `src/reshape/vcf.py` (traditional VCF) both write the same shared `position_start`/`position_end` columns (`src/observation.py`'s `VARIATION_OBS_COLUMNS`, which its own docstring requires to be byte-identical across both paths), and both bind `Variant` through the same `config/mapping/omics.yaml` entry — `traditional.yaml` only adds `include: [omics]` on top, it has no `Variant` binding of its own.

**Decision:** put the alias in `config/mapping/omics.yaml` (the shared profile), not `traditional.yaml`. This fixes both the GDC and traditional/VCF paths at once, and is what the failing test actually needed to pass.

## Changes made

### 1. `tests/test_variation_integration.py`

Line 187's assertion on the now-renamed `positionStart` column commented out, replaced with an assertion on `startPosition`:

```python
        assert tp53_row["chromosome"] == "17"
        # assert tp53_row["positionStart"] == "7674220"  # renamed -> startPosition
        # (schema migration follow-up: config/schema/nodes.yaml Variant rename,
        # neo4j_updated_schema_new_v2.md §7.4)
        assert tp53_row["startPosition"] == "7674220"
        assert tp53_row["referenceAllele"] == "C"
```

### 2. `config/mapping/omics.yaml`

Added an `aliases:` block (this file had none before) mapping the shared raw column names to the renamed schema properties:

```yaml
profile: omics

aliases:
  position_start: startPosition
  position_end: endPosition

nodes:
  ...
```

`config/mapping/traditional.yaml` was **not** touched — it inherits this fix automatically via `include: [omics]`, and its own `aliases:` block (`sex: sexAtBirth`) merges cleanly with no conflict.

### 3. `Study.diseaseCategory` / `Assay.assayChemistry` / `LibraryPreparation.libraryChemistry`

**No change made — confirmed as intentional.** Per your instruction, these remain aspirational columns with no GDC source binding, the same status they had before the rename (neither `diseaseType`/`chemistry` was wired to a GDC column before either — `config/mapping/extract.yaml` already documents `diseaseType`/`primarySite` as a known gap with no source column). Revisit only if/when a source for these fields is added.

## Verification

- **Full test suite: 324/324 passed** (was 323/324 before this round — the one prior failure is fixed, no new failures introduced).
- **Resolver-level proof, not just test-green:** loaded both mapping profiles directly and confirmed the alias actually resolves, not just that the assertion string matches —

  ```
  omics profile aliases: {'position_start': 'startPosition', 'position_end': 'endPosition'}
  startPosition -> Resolution(raw='position_start', strategy='alias')
  endPosition   -> Resolution(raw='position_end', strategy='alias')

  traditional profile aliases (merged via include): {'position_start': 'startPosition',
    'position_end': 'endPosition', 'sex': 'sexAtBirth'}
  startPosition (traditional) -> Resolution(raw='position_start', strategy='alias')
  ```

  Both the GDC (`omics`) and traditional (`traditional`, via `include`) profiles resolve `startPosition`/`endPosition` to the correct raw columns through the `alias` strategy — the fix reaches both ingestion paths from one place, as intended.
- `src/schema.py::load_schema()` was unaffected by this round (only mapping config and a test changed, not `config/schema/*.yaml`) — still 42 nodes, 52 edges, zero validation errors.

## Files changed this round

| File | Change |
|---|---|
| `config/mapping/omics.yaml` | +14 lines: new `aliases:` block (`position_start`→`startPosition`, `position_end`→`endPosition`), with an explanatory comment on why it's needed and shared by both ingestion paths. |
| `tests/test_variation_integration.py` | Old assertion commented out in place, new assertion added on the next line. |
| `config/mapping/traditional.yaml` | Untouched — inherits the fix via `include: [omics]`. |

No remaining follow-up items from this round. The two other Proposal A follow-ups not addressed here — wiring `Gene`/`CpGSite` reference-annotation ingestion, and the deliberately-deferred `Disease` MONDO question — are unchanged and still open for a future pass.
