# LifeSphere — Roadmap (2026-07-02)

Prioritized implementation plan from an end-to-end codebase review (extract →
standardise → load). Foundation is solid: cleanly separated stages, config-driven
standardiser (JSON schemas + alias + placeholder layers), grain preserved from
extraction to graph, clinical backbone verified on the full 11,428-case TCGA
extract. Gaps are about **completeness (omics), resilience, and productionization**,
not core design.

Priority key: **P0** = blocks the graph's largest layer / silent data loss ·
**P1** = resilience & correctness · **P2** = productionization.

---

## P0 — Omics extract → standardise bridge

**Problem.** The omics layer is modelled (schemas, both load paths, synthetic smoke
test in `tests/fixtures/omics_smoke`) but nothing connects real downloaded omics to
the standardiser:

- `src/extract/omics.py` writes a flat `{base}.{type}.tsv` = `[case_id,
  case_submitter_id, file_id, <raw GDC header>]`. The standardiser expects a
  `gene_expression` entity keyed by `expression_id`, a **separate deduped**
  `gene.tsv` reference, `gene_ensembl` (not GDC `gene_id`), and a **`sample_id`**
  to anchor `HAS_EXPRESSION`.
- `omics.py` never captures the file→aliquot association (`_file_meta` keeps only
  `cases[0]`), so the `(Sample)-[:HAS_*]->(Observation)` linkage the whole model is
  built on **cannot currently be produced**. It also silently drops multi-case
  files by taking `cases[0]`.

**Deliverable.** (a) Extend extraction to record the **file→aliquot (sample) id**;
(b) add a reshape post-process turning each concatenated matrix into
standardiser-ready TSVs: a deduped feature reference file + an observation file with
a deterministic surrogate id, `sample_id`, and the canonical feature FK. Keeps the
standardiser generic (mirrors the biospecimen-merge post-process pattern).

Per type:
- expression → `{base}.gene.tsv` (`ensembl`, symbol, type) + `{base}.gene_expression.tsv`
  (`expression_id`, `sample_id`, `gene_ensembl`, tpm, fpkm, file_id)
- methylation → `{base}.cpg_site.tsv` (`cpg`) + `{base}.methylation.tsv`
  (`methylation_id`, `sample_id`, `cpg`, beta_value, file_id)
- variation (MAF) → `{base}.variant.tsv` (`variant_id`, `gene_ensembl`, chrom/pos/ref/alt)
  + `{base}.somatic_mutation.tsv` (`variant_call_id`, `sample_id`, `variant_id`,
  consequence, impact, vaf, file_id); sample comes from the MAF row's tumor aliquot.

## P0 — Load-time referential-integrity reporting

**Problem.** `neo4j_loader.load_edges` does `MATCH ... MERGE`; if an endpoint node is
missing, the edge is **silently dropped** — no warning, no count. Nothing validates
node/edge referential integrity before ingest.

**Deliverable.** A lightweight, offline pre-load validator (`src/load/validate.py`)
that builds node-id sets from `nodes/*.csv` and reports, per edge file, dangling
source/target counts (using the schema's endpoint labels; falls back to the global
id set for polymorphic endpoints). Wire it into the loader CLI (`validate`
subcommand + `--validate`/`--strict` before `load`). Unit-testable without a DB.

---

## P1 — Extraction resilience

`gdc_api.post` has no retry/backoff and `sys.exit`s on the first transient error —
one blip aborts a multi-hour pull. Add exponential backoff on 5xx/timeouts + 429
handling; return errors instead of exiting so callers decide. Add resumability
(skip already-downloaded files, checkpoint pagination) for the large omics pulls.

## P1 — Value-based column profiling

Extends the name-based alias system (`src/standardise/aliases.py`). Per todo
`020726.md`: when a header is unrecognized, infer canonical identity from **values**
(UUID pattern → id column; controlled-vocabulary overlap → known categorical).

## P1 — Run manifest + unified logging

Standardize on `logging` across all three stages (extract/standardise currently
`print`). Emit a per-run JSON manifest: GDC data release, data-dictionary version,
selector, per-stage row counts, timestamps. Foundation for reproducibility and the
validation stage.

---

## P2 — Packaging + CI

Add `pyproject.toml` (drop the `sys.path` hacks in `scripts/`), pin dependencies,
add a GitHub Actions workflow running the suite. Backfill tests for `load/run.py`,
`load/subset.py`, and `extract/omics.py` reshape (all unit-testable without network).

## P2 — Omics load scaling + canonical path

Two load paths currently diverge (BioCypher offline-CSV keeps empty props for column
consistency; direct-Bolt now drops them per-node). Document which is canonical. For
omics volume, route bulk observations through the offline `neo4j-admin import`
(BioCypher) path; reserve the Bolt loader for incremental clinical updates.

---

## Status

- [x] P0 — Omics extract → standardise bridge *(2026-07-02: `src/extract/omics_reshape.py`
      + file→aliquot capture in `omics.py`; tested reshape→standardise→validate. Not yet
      run on a real network download / gdc-client pull.)*
- [x] P0 — Load-time referential-integrity reporting *(2026-07-02: `src/load/validate.py`,
      `validate` subcommand + `--validate/--strict`, per-edge created-vs-attempted warning in
      `load_edges`. Verified 0 dangling on the full TCGA graph.)*
- [ ] P1 — Extraction resilience
- [ ] P1 — Value-based column profiling
- [ ] P1 — Run manifest + unified logging
- [ ] P2 — Packaging + CI
- [ ] P2 — Omics load scaling + canonical path
</content>
