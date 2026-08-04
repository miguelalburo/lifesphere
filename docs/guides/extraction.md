# Extraction

## What this stage does

The extraction stage fetches data from the GDC (Genomic Data Commons) public API and writes one TSV file per entity into `data/raw/<dataset>/`. For clinical data it calls the `/cases` endpoint and emits a file for each entity type (subjects, samples, diagnoses, etc.). For omics data it downloads raw genomic files from GDC object storage and reshapes them into per-observation TSVs.

This stage requires an internet connection to reach the GDC. No Neo4j instance or credentials are needed.

## CLI synopsis

```bash
python -m src.extract <project_id | --program NAME> <layer flags> [--out PATH]
```

You must supply either a `project_id` (e.g. `TCGA-CHOL`) or `--program NAME` (e.g. `TCGA`), and at least one layer flag.

## Scope options

| Argument | What it targets |
|---|---|
| `project_id` | A single GDC project, e.g. `TCGA-CHOL` |
| `--program NAME` | All projects within a program, e.g. `TCGA` |

Using `--program` can involve thousands of files; see [When to use SLURM](#when-to-use-slurm) below.

## Layer flags

| Flag | What it fetches |
|---|---|
| `--clinical` | GDC `/cases` endpoint — subjects, samples, aliquots, diagnoses, treatments, exposures, family history |
| `--expression` | RNA-seq STAR-Counts files — per-gene TPM and raw counts |
| `--methylation` | DNA-methylation Beta Value files — per-CpG site beta values |
| `--variation` | Masked Somatic Mutation MAF files — somatic variant calls |
| `--omics` | Shorthand for `--expression --methylation --variation` combined |
| `--survival` | TCGA-CDR survival calls (OS/DSS/DFI/PFI) from the cBioPortal PanCanAtlas mirror |

`--survival` ignores `project_id`/`--program` and always pulls the full TCGA pan-cancer study list, writing `survival.tsv` to `--out` (or its default). It requires `subject.tsv` to already exist there, so run `--clinical` first.

Flags can be combined freely. For example, to fetch clinical data and expression only:

```bash
python -m src.extract TCGA-CHOL --clinical --expression
```

## Optional flags

| Flag | Effect |
|---|---|
| `--out PATH` | Write raw TSVs to a custom directory instead of the default `data/raw/<dataset>/` |
| `--workers N` | Concurrent file downloads for `--expression`/`--methylation` (default: 8). Downloads are the bottleneck for these layers — each file is fetched and integrity-checked independently, so raising this shortens wall-clock time roughly linearly up to what the GDC API and your network can sustain. `--variation` is unaffected (not yet parallelised). |

## Zero-value expression rows are dropped

A gene with `expression_value == 0` (TPM) means "not detected in this sample" — with ~60k genes scored per sample, most rows are this, and at program scale they dominate the graph with uninformative observation nodes. These rows are excluded both where they're produced (`extract_expression`'s reshape step) and again in `standardise` (so the traditional matrix-reshape ingest path, which never runs the GDC extractor, is covered too — see `src/observation.py::ZERO_EXCLUDED_COLUMNS`). Methylation beta values are **not** filtered this way: `beta_value == 0` is a real, meaningful "fully unmethylated" reading, not noise.

## Output

After a successful run, `data/raw/<dataset>/` contains:

- **Clinical layer**: one `.tsv` file per entity type (e.g. `subject.tsv`, `sample.tsv`, `diagnosis.tsv`).
- **Omics layers**: one `*_observation.tsv` file per molecular assay (e.g. `expression_observation.tsv`, `methylation_observation.tsv`, `variation_observation.tsv`), plus a shared `gene.tsv` reference file for expression.

The `<dataset>` folder name is derived from the `project_id` (e.g. `TCGA-CHOL`) or, for `--program` runs, from the program name.

## Example commands

```bash
# Extract clinical data for one project
python -m src.extract TCGA-CHOL --clinical

# Extract clinical + all omics for one project
python -m src.extract TCGA-CHOL --clinical --omics

# Extract clinical for every TCGA project (see SLURM note below)
python -m src.extract --program TCGA --clinical
```

## When to use SLURM

Running `--program TCGA` with omics layers on a login node will take many hours and consume significant memory. For full-program runs on an HPC cluster, use the SLURM fan-out scripts instead:

```bash
scripts/submit_extract_TCGA.sh
```

This submits one SLURM array job per extraction layer, targeting all TCGA projects in parallel.

---

**Next step:** once you have TSVs in `data/raw/<dataset>/`, proceed to [standardisation.md](standardisation.md) to bind those columns to the graph schema and produce graph-ready CSVs.
