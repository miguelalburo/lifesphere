# LifeSphere: TCGA DNA Methylation Data Standardisation

## Overview

This workflow converts wide-format TCGA DNA methylation beta-value matrices into schema-aligned, graph-ready staging files for LifeSphere.

The workflow separates:

- stable `CpGSite` reference entities;
- sample-specific `MethylationObservation` records;
- reusable `MethylationStatusRule` records;
- sample-to-observation relationships;
- observation-to-CpG relationships; and
- observation-to-classification-rule relationships.

The current implementation is **schema-aware and partly configuration-driven**:

- `tcga_methylation_mapping.json` controls the mapping and derivation of node properties;
- `lifesphere_schema.json` acts as a runtime schema contract and supplies property names and data types;
- `methylation.py` explicitly defines the required methylation workflow, input filename patterns, required graph patterns, output filenames, and relationship endpoint columns.

The script therefore does not infer an arbitrary graph workflow from any schema. It implements the LifeSphere TCGA methylation workflow and validates that the supplied schema and mapping configuration remain compatible with that workflow.

---

## Recommended Codebase Placement

Within the LifeSphere repository, the workflow can be organised as:

```text
lifesphere/
├── config/
│   ├── standardisation_mapping/
│   │   └── methylation/
│   │       └── tcga_methylation_mapping.json
│   └── schema/
│       └── lifesphere_schema.json
├── standardisation_scripts/
│   ├── methylation.py
│   └── transform_library.py
├── job_scripts/
│   │   └── standardisation/
│   │       └── run_methylation.sh
├── docs/
│   └── standardisation_readme_guides/
│       └── methylation_standardisation_README.md
└── data/
    └── standardised/
        └── <cohort outputs>
```

The current HPC shell script uses absolute BlueBEAR paths. If these files are moved into the GitHub repository, update the path variables in `run_methylation.sh` or make them repository-relative before running it.

Large generated TCGA outputs should normally remain outside Git and be ignored through `.gitignore`. The repository should retain the code, configuration, schema, documentation, and small test fixtures rather than multi-gigabyte cohort outputs.

---

## Workflow Components

### 1. Configuration and schema enforcement

The output structure is not hardcoded directly into the processing logic. Instead, `methylation.py` reads `tcga_methylation_mapping.json` to determine:

- which source files and columns should be used;
- how source values map to LifeSphere node properties;
- which transformations should be applied;
- how primary identifiers should be generated;
- which node and relationship CSV files should be created; and
- how the generated outputs align with `lifesphere_schema.json`.

For example, the script generates a unique `methylationObservationId` for each methylation measurement using the configured identifier recipe:

```text
"obs_" + sampleId + "_" + cpgId


### 2. Processing with `methylation.py`

The Python program performs:

1. command-line argument parsing;
2. mapping-configuration loading;
3. LifeSphere schema loading and validation;
4. optional sample and CpG selection;
5. cohort discovery;
6. CpG annotation standardisation;
7. chunked wide-to-long beta-matrix conversion;
8. beta-value validation and filtering;
9. methylation-status derivation when configured;
10. node and relationship file generation;
11. atomic finalisation of output files; and
12. per-cohort manifest generation.

### 3. Processing with `run_methylation.sh`

The Slurm script:

- requests BlueBEAR compute resources;
- loads the required software environment;
- defines the input, output, configuration, schema, and script paths;
- runs `methylation.py` with an explicit chunk size; and
- writes standard-output and standard-error logs.

### 4. Requisite of `tcga_methylation_mapping.json`

The mapping configuration defines how source and derived values populate:

- `CpGSite`;
- `MethylationObservation`; and
- `MethylationStatusRule`.

It also defines configured transformations and computation recipes, such as:

- direct source-column mapping;
- default values;
- identifier concatenation;
- matrix-header extraction;
- matrix-index extraction;
- matrix-value extraction;
- cohort-name derivation;
- filename derivation; and
- methylation-status derivation.

### 5. Requisite of `lifesphere_schema.json` schema

The schema JSON provides the active node and relationship definitions used by the script as a runtime contract.

The script checks that the required nodes, primary keys, properties, and relationship patterns exist before any cohort is processed.

### 6. Requisite of `transform_library.py` (RAGAD's onboarding logic)

`methylation.py` imports:

```python
from transform_library import TEMPLATES
```

Therefore, `transform_library.py` must be importable from the execution environment. In the current arrangement, it should normally be in the same script directory as `methylation.py`, or otherwise available through `PYTHONPATH`.

---

## Current BlueBEAR Paths

The supplied `run_methylation.sh` uses the following effective paths:

| Purpose | Path |
|---|---|
| Script directory | `/rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/standardisation_script` |
| Input data | `/rds/homes/s/sxm2220/Shalini/THESIS/TCGA_methylation_data` |
| Output directory | `/rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/outputs` |
| Mapping configuration | `/rds/homes/s/sxm2220/Shalini/THESIS/JSON/tcga_methylation_mapping.json` |
| LifeSphere schema | `/rds/projects/r/ranaaaa-ai-hackathon/Lifesphere/Shalini/THESIS/schema/lifesphere_schema.json` |
| Slurm logs | `/rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/slurm_log/` |

These command-line values override the default paths declared inside `methylation.py`.

Before submission, ensure that the output and log directories exist:

```bash
mkdir -p /rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/outputs
mkdir -p /rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/slurm_log
```

Slurm does not create missing parent directories for `#SBATCH --output` or `#SBATCH --error`.

---

## Input Directory Contract

The input root must contain one or more directories whose names begin with `TCGA-`:

```text
TCGA_methylation_data/
├── TCGA-ACC/
├── TCGA-BLCA/
├── TCGA-BRCA/
└── ...
```

When `--cohort` is not supplied, `methylation.py` discovers and processes all immediate subdirectories matching:

```text
TCGA-*
```

For each cohort, the script requires exactly one beta matrix and exactly one CpG annotation file.

### Required cohort files

```text
TCGA-BRCA/
├── <prefix>_beta_matrix.csv
└── <prefix>_rowData_cpg_annotation.csv
```

The exact glob patterns are:

```text
*_beta_matrix.csv
*_rowData_cpg_annotation.csv
```

Processing fails for a cohort when either pattern matches:

- no file; or
- more than one file.

### Beta-matrix requirements

The beta matrix must satisfy all of the following:

1. The first column contains CpG or methylation-feature identifiers.
2. At least one sample column follows the identifier column.
3. Every column after the first must be a TCGA sample column whose name begins with `TCGA-`.
4. No additional annotation or metadata columns may occur after the first column.
5. Sample column names must be unique.
6. CpG identifiers must not repeat within a chunk or across chunks.
7. Every matrix CpG retained for processing must exist in the generated `CpGSite` annotation output.

Conceptual input:

```text
cpg_id,TCGA-XX-0001-01A,TCGA-XX-0002-01A
cg00000029,0.812,0.231
cg00000108,0.544,0.731
```

### CpG annotation requirements

The annotation file must contain the source columns required by the `CpGSite` mappings in `tcga_methylation_mapping.json`.

Optional mapped source columns may be absent. In that case, the script writes blank values and reports a message.

Required mapped source columns cause the cohort to fail when absent.

---

## Schema Contract Validation

Before reading cohort data, the script verifies the supplied LifeSphere schema.

### Required nodes and primary keys

| Node | Required primary key |
|---|---|
| `CpGSite` | `cpgId` |
| `MethylationObservation` | `methylationObservationId` |
| `MethylationStatusRule` | `methylationStatusRuleId` |
| `Sample` | `sampleId` |
| `Assay` | `assayId` |

The primary key must be declared as the node's `primaryKey` and must also occur in its property catalogue.

### Required relationship patterns

```cypher
(:Sample)-[:HAS_METHYLATION_OBSERVATION]->(:MethylationObservation)

(:MethylationObservation)-[:MEASURES_CPG]->(:CpGSite)

(:MethylationObservation)-[:CLASSIFIED_USING]->(:MethylationStatusRule)
```

### Required `MethylationObservation` schema properties

The schema must define:

```text
methylationObservationId
observationType
sampleId
assayId
cpgId
betaValue
methylationStatus
methylationStatusMethod
numCpGSites
modificationType
qualityScore
normalizationMethod
sourceDataset
sourceFile
pipelineVersion
configKey
```

Not every property is required to contain a value in every output row. However, each property must exist in the schema because the workflow expects a stable observation-property contract.

---

## Configuration Behaviour

### Node properties

For node outputs, the mapping file can use the following modes.

#### `map`

Copies a configured source column, optionally applying a named transform.

#### `default`

Writes a configured constant value.

#### `compute`

Uses a supported computation recipe.

The current `MethylationObservation` recipes are:

| Recipe | Purpose |
|---|---|
| `concat` | Builds an identifier or other concatenated value |
| `from_matrix_headers` | Uses the sample ID from a matrix column |
| `from_matrix_index` | Uses the CpG ID from the matrix's first column |
| `from_matrix_values` | Uses the beta value |
| `derive_methylation_status` | Classifies the beta value using the configured rule |
| `cohort_name` | Writes the current cohort name |
| `filename` | Writes the source beta-matrix filename |
| `status_rule_type` | Writes the active rule type |
| `status_rule_config_key` | Writes the active rule's configuration key |

### Observation identifier requirement

The mapping for `methylationObservationId` must use:

```json
{
  "mode": "compute",
  "recipe": "concat"
}
```

Its inputs must include both:

```text
sampleId
cpgId
```

This guarantees one observation identity per sample–CpG measurement.

When no literal separator is supplied in the configured inputs, the script inserts `|` as the default delimiter. For example:

```text
obs|TCGA-XX-0001-01A|cg00000029
```

The exact identifier depends on the configured input sequence and literals.

### Schema-driven output columns

For the three node files, the script reindexes each DataFrame against the complete property list in `lifesphere_schema.json`.

Consequently:

- every schema property for the relevant node appears as an output column;
- mapped or derived properties contain values;
- unmapped optional properties are written as blank columns; and
- supported scalar types are coerced according to the schema.

Supported coercions include:

- `Integer`;
- `Float`;
- `Boolean`; and
- `String`.

Invalid non-blank values that cannot be converted to the required schema type cause processing to fail rather than being silently accepted.

---

## Methylation-Status Rule

Status classification is activated only when a `MethylationObservation` mapping uses:

```json
{
  "mode": "compute",
  "recipe": "derive_methylation_status"
}
```

When classification is requested, `mappings.MethylationStatusRule` must exist.

The current script supports only:

```json
"mode": "default"
```

for individual rule properties.

### Required rule fields

```text
methylationStatusRuleId
ruleName
ruleType
ruleDescription
betaValueScale
hypoThreshold
hyperThreshold
intermediateLowerBound
intermediateUpperBound
```

### Rule validation

Thresholds must satisfy:

```text
0.0 <= hypoThreshold < hyperThreshold <= 1.0
```

For the current three-state absolute-threshold implementation:

```text
intermediateLowerBound == hypoThreshold
intermediateUpperBound == hyperThreshold
```

The execution logic treats the outer thresholds as inclusive:

```text
betaValue <= hypoThreshold  → Hypomethylated
hypoThreshold < betaValue < hyperThreshold → Intermediate
betaValue >= hyperThreshold → Hypermethylated
```

The inclusive-boundary behaviour is currently implemented by the workflow because the active schema does not define separate boundary-operator properties.

If classification is not requested:

- the status rule is not used;
- `methylation_status_rules.csv` is created with headers but no data row; and
- `methylation_observation_classified_using.csv` is created with headers but no relationship rows.

---

## CpG and Measurement Validation

### Accepted methylation-feature identifiers

The script accepts identifiers matching:

```text
cg<digits>
ch.<value>
rs<digits>
```

Examples:

```text
cg00000029
ch.1.123456
rs123456
```

Unrecognised identifiers are dropped with warnings during annotation processing, matrix-chunk processing, or post-melt cleaning.

### CpG annotation duplicates

If duplicate `cpgId` rows contain identical annotation values, duplicates are removed.

If duplicate `cpgId` rows contain conflicting annotations, the cohort fails.

### Beta-value cleaning

After melting, beta values are converted to numeric values.

The script separately counts and excludes:

- missing values;
- non-numeric values; and
- values outside the inclusive range `0.0–1.0`.

Only valid numeric values in `[0, 1]` become `MethylationObservation` records.

The counts are written to the cohort manifest.

---

## Chunked Wide-to-Long Processing

The beta matrix is read by CpG rows in Pandas chunks.

The supplied Slurm script runs:

```bash
--chunk-size 5000
```

This means that up to 5,000 CpG rows are read before melting them across all selected sample columns.

The Python CLI default is:

```text
500
```

but the shell script overrides it with `5000`.

Conceptual conversion:

```text
Wide matrix
cpgId       Sample_A    Sample_B
cg000001    0.81        0.22

Long observations
cpgId       sampleId    betaValue
cg000001    Sample_A    0.81
cg000001    Sample_B    0.22
```

The approximate number of observation rows before filtering is:

```text
number of retained CpGs × number of selected samples
```

Therefore, memory use and output volume depend on both dimensions, not only on the number of CpG rows in each read chunk.

---

## Optional Materialisation Filters

The script can restrict output to selected samples, selected CpGs, or both.

### `--sample-list`

Accepts a one-column TXT, CSV, TSV, semicolon-delimited, or pipe-delimited file of sample identifiers.

Recognised optional headers include:

```text
id
sampleId
sample_id
```

Requested sample IDs absent from a cohort are reported and ignored. At least one selected sample must remain in the cohort.

### `--cpg-list`

Accepts a one-column identifier file using the same delimiter detection.

Recognised optional headers include:

```text
id
cpgId
cpg_id
```

Only selected CpGs are retained in both the annotation and matrix outputs.

### Complete external staging mode

When neither filter is supplied, the script emits a warning and materialises all valid sample–CpG measurements into the long-format staging CSV.

This can create extremely large files. The LifeSphere graph-design policy recommends keeping dense matrices external and loading only selected, query-relevant observations into Neo4j.

---

## Cohort Processing Behaviour

### All cohorts

Without `--cohort`, all `TCGA-*` subdirectories are processed sequentially.

A failure in one cohort is recorded, a traceback is printed, and the script continues with the remaining cohorts.

At the end, the script reports:

```text
<successful count> successful, <failed count> failed
```

If any cohort failed, the overall process exits with status `1`.

Because `run_methylation.sh` uses:

```bash
set -e
```

the Slurm job is also reported as failed when the Python process exits non-zero.

### One cohort

Use:

```bash
python methylation.py \
  --data-dir /path/to/TCGA_methylation_data \
  --out-dir /path/to/outputs \
  --config /path/to/tcga_methylation_mapping.json \
  --schema /path/to/lifesphere_schema.json \
  --cohort TCGA-BRCA \
  --chunk-size 5000
```

When a specific cohort fails, the command terminates immediately with an error.

---

## Output Directory Structure

The current Python implementation writes a **flat per-cohort directory**. It does not create separate physical `nodes/` and `edges/` subdirectories.

```text
outputs/
├── TCGA-ACC/
│   ├── cpg_sites.csv
│   ├── methylation_observations.csv
│   ├── methylation_status_rules.csv
│   ├── sample_has_methylation_observation.csv
│   ├── methylation_observation_measures_cpg.csv
│   ├── methylation_observation_classified_using.csv
│   └── methylation_standardisation_manifest.json
├── TCGA-BLCA/
│   └── ...
└── TCGA-BRCA/
    └── ...
```

The node/relationship grouping described below is semantic. If the repository requires:

```text
nodes/
edges/
```

subdirectories, `methylation.py` or a post-processing packaging step must be changed accordingly.

Each successfully processed cohort produces **seven final files**:

- three node CSVs;
- three relationship CSVs; and
- one JSON manifest.

---

## Node Outputs

### `cpg_sites.csv`

Represents:

```cypher
(:CpGSite)
```

#### Row meaning

One row represents one unique, valid, selected CpG or accepted methylation feature from the cohort annotation file.

#### Columns

The file contains all properties defined for `CpGSite` in `lifesphere_schema.json`.

At minimum, the workflow requires:

```text
cpgId
```

Other columns depend on the schema and mapping configuration and may include:

```text
chromosome
startPosition
endPosition
strand
geneSymbol
ensemblGeneId
annotationSource
annotationVersion
```

Unmapped optional schema properties remain blank.

### `methylation_observations.csv`

Represents:

```cypher
(:MethylationObservation)
```

#### Row meaning

One row represents one valid sample–CpG beta-value measurement.

#### Required populated fields

The workflow requires meaningful values for:

```text
methylationObservationId
observationType
sampleId
cpgId
betaValue
sourceDataset
```

`assayId` is present as a schema column and is normalised as an identifier. The script currently warns rather than fails when some `assayId` values are blank.

The file contains every `MethylationObservation` property declared in the schema, including optional columns that may remain blank.

### `methylation_status_rules.csv`

Represents:

```cypher
(:MethylationStatusRule)
```

#### Row meaning

When classification is active, the file normally contains one reusable rule row.

The same rule is repeated in each cohort directory so that every cohort output is self-contained.

Downstream ingestion must use:

```cypher
MERGE (r:MethylationStatusRule {
  methylationStatusRuleId: row.methylationStatusRuleId
})
```

rather than creating a duplicate rule node for every cohort.

When classification is inactive, this file contains only its header.

---

## Relationship Outputs

### Important current limitation

The current implementation does **not** dynamically export arbitrary relationship properties from the mapping configuration.

`build_relationship_chunks()` explicitly generates only the source and target identifiers shown below.

Therefore, optional relationship properties such as `mappingConfidence` will not appear merely because they are added to `tcga_methylation_mapping.json`. Supporting such a property would require a corresponding change to the Python relationship-output logic.

### `sample_has_methylation_observation.csv`

Creates:

```cypher
(:Sample)-[:HAS_METHYLATION_OBSERVATION]->(:MethylationObservation)
```

Columns:

```text
sampleId
methylationObservationId
```

Expected row count:

```text
one row per materialised MethylationObservation
```

### `methylation_observation_measures_cpg.csv`

Creates:

```cypher
(:MethylationObservation)-[:MEASURES_CPG]->(:CpGSite)
```

Columns:

```text
methylationObservationId
cpgId
```

Expected row count:

```text
one row per materialised MethylationObservation
```

This is a direct identifier-based relationship. The observation is generated from the beta value associated with the same `cpgId` used to identify the target `CpGSite`.

### `methylation_observation_classified_using.csv`

Creates:

```cypher
(:MethylationObservation)-[:CLASSIFIED_USING]->(:MethylationStatusRule)
```

Columns:

```text
methylationObservationId
methylationStatusRuleId
```

Expected row count when classification is active:

```text
one row per materialised MethylationObservation
```

When classification is inactive, the file contains only its header.

---

## Manifest Output

### `methylation_standardisation_manifest.json`

The manifest records the cohort-level execution summary.

Example structure:

```json
{
  "cohort": "TCGA-BRCA",
  "createdAtUtc": "2026-07-23T20:00:00+00:00",
  "schemaName": "LifeSphere Neo4j Knowledge Graph Schema",
  "sourceBetaFile": "TCGA-BRCA_beta_matrix.csv",
  "sourceAnnotationFile": "TCGA-BRCA_rowData_cpg_annotation.csv",
  "selectedSampleCount": 780,
  "selectedCpGCount": 485577,
  "materialisedObservationCount": 350000000,
  "methylationStatusRuleId": "absolute_beta_threshold_rule",
  "filteredValues": {
    "missing": 1200,
    "nonNumeric": 0,
    "outsideZeroToOne": 0
  },
  "outputs": {
    "CpGSite": "cpg_sites.csv",
    "MethylationObservation": "methylation_observations.csv",
    "MethylationStatusRule": "methylation_status_rules.csv",
    "HAS_METHYLATION_OBSERVATION": "sample_has_methylation_observation.csv",
    "MEASURES_CPG": "methylation_observation_measures_cpg.csv",
    "CLASSIFIED_USING": "methylation_observation_classified_using.csv"
  }
}
```

The numeric values above are illustrative. Actual values are calculated from the processed cohort.

The manifest records:

- source filenames;
- selected sample count;
- processed CpG count;
- materialised observation count;
- active rule identifier;
- filtered-value counts; and
- generated output filenames.

---

## Atomic Output and Failure Handling

### Node files

`cpg_sites.csv`, `methylation_status_rules.csv`, and the manifest are written to temporary files and atomically renamed to their final filenames.

### Chunked files

The observation and relationship outputs are appended to files with a `.tmp` suffix during processing:

```text
methylation_observations.csv.tmp
sample_has_methylation_observation.csv.tmp
methylation_observation_measures_cpg.csv.tmp
methylation_observation_classified_using.csv.tmp
```

Only after the cohort completes successfully are these files renamed to their final `.csv` names.

If cohort processing fails:

- the partially written files retain the `.tmp` suffix;
- final filenames are not created from those partial files; and
- `.tmp` files must not be ingested.

At the start of a new run, stale temporary files for the cohort are removed before writing begins.

---

## Slurm Execution

The supplied `run_methylation.sh` requests:

```bash
#SBATCH --job-name=tcga_methylation
#SBATCH --account=ranaaaa-ai-hackathon
#SBATCH --qos=bbpriority3
#SBATCH --time=24:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
```

Logs are written to:

```text
/rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/slurm_log/methylation_<job-id>.out
/rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/slurm_log/methylation_<job-id>.err
```

### Loaded modules

The script runs:

```bash
module purge
module load bluebear
module load bear-apps/2024a
module load SciPy-bundle/2024.05-gfbf-2024a
```

`SciPy-bundle/2024.05-gfbf-2024a` provides the scientific Python environment used by the workflow, including Pandas in the current BlueBEAR setup.

### Effective Python command

The shell script executes:

```bash
python methylation.py \
    --data-dir "/rds/homes/s/sxm2220/Shalini/THESIS/TCGA_methylation_data" \
    --out-dir "/rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/outputs" \
    --config "/rds/homes/s/sxm2220/Shalini/THESIS/JSON/tcga_methylation_mapping.json" \
    --schema "/rds/projects/r/ranaaaa-ai-hackathon/Lifesphere/Shalini/THESIS/schema/lifesphere_schema.json" \
    --chunk-size 5000
```

Because no `--cohort`, `--sample-list`, or `--cpg-list` is supplied, the current job:

- processes all discovered `TCGA-*` cohorts sequentially;
- uses all TCGA sample columns in each cohort;
- uses all valid annotated CpGs; and
- creates complete long-format external staging files.

---

## Running the Workflow

### 1. Prepare directories

```bash
mkdir -p /rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/outputs
mkdir -p /rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/slurm_log
```

### 2. Confirm required files

```bash
ls -l /rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/standardisation_script/methylation.py
ls -l /rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/standardisation_script/transform_library.py
ls -l /rds/homes/s/sxm2220/Shalini/THESIS/JSON/tcga_methylation_mapping.json
ls -l /rds/projects/r/ranaaaa-ai-hackathon/Lifesphere/Shalini/THESIS/schema/lifesphere_schema.json
```

### 3. Submit the job

```bash
cd /rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/standardisation_script
sbatch run_methylation.sh
```

### 4. Record the submitted job ID

Slurm returns a message similar to:

```text
Submitted batch job 12345678
```

---

## Monitoring

### View active jobs

```bash
squeue -u "$USER"
```

### Inspect the output log

```bash
tail -f /rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/slurm_log/methylation_<job-id>.out
```

### Inspect the error log

```bash
tail -f /rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/slurm_log/methylation_<job-id>.err
```

### Cancel the job

```bash
scancel <job-id>
```

### Check final Slurm status

```bash
sacct -j <job-id> --format=JobID,JobName,State,ExitCode,Elapsed,MaxRSS
```

---

## Direct CLI Examples

### Process all cohorts

```bash
python methylation.py \
  --data-dir /path/to/TCGA_methylation_data \
  --out-dir /path/to/outputs \
  --config /path/to/tcga_methylation_mapping.json \
  --schema /path/to/lifesphere_schema.json \
  --chunk-size 5000
```

### Process one cohort

```bash
python methylation.py \
  --data-dir /path/to/TCGA_methylation_data \
  --out-dir /path/to/outputs \
  --config /path/to/tcga_methylation_mapping.json \
  --schema /path/to/lifesphere_schema.json \
  --cohort TCGA-BRCA \
  --chunk-size 5000
```

### Process selected samples

```bash
python methylation.py \
  --data-dir /path/to/TCGA_methylation_data \
  --out-dir /path/to/outputs \
  --config /path/to/tcga_methylation_mapping.json \
  --schema /path/to/lifesphere_schema.json \
  --cohort TCGA-BRCA \
  --sample-list selected_samples.txt \
  --chunk-size 5000
```

### Process selected CpGs

```bash
python methylation.py \
  --data-dir /path/to/TCGA_methylation_data \
  --out-dir /path/to/outputs \
  --config /path/to/tcga_methylation_mapping.json \
  --schema /path/to/lifesphere_schema.json \
  --cohort TCGA-BRCA \
  --cpg-list selected_cpgs.txt \
  --chunk-size 5000
```

### Process selected samples and CpGs

```bash
python methylation.py \
  --data-dir /path/to/TCGA_methylation_data \
  --out-dir /path/to/outputs \
  --config /path/to/tcga_methylation_mapping.json \
  --schema /path/to/lifesphere_schema.json \
  --cohort TCGA-BRCA \
  --sample-list selected_samples.txt \
  --cpg-list selected_cpgs.txt \
  --chunk-size 5000
```

---

## Validation After Completion

For each cohort, confirm that all seven final files exist:

```bash
find /path/to/outputs/TCGA-BRCA -maxdepth 1 -type f -printf '%f\n' | sort
```

Expected:

```text
cpg_sites.csv
methylation_observation_classified_using.csv
methylation_observation_measures_cpg.csv
methylation_observations.csv
methylation_standardisation_manifest.json
methylation_status_rules.csv
sample_has_methylation_observation.csv
```

Check for failed partial files:

```bash
find /path/to/outputs -name '*.tmp' -print
```

Any `.tmp` output indicates an incomplete or failed cohort and must not be ingested.

Inspect the manifest:

```bash
python -m json.tool \
  /path/to/outputs/TCGA-BRCA/methylation_standardisation_manifest.json
```

Compare observation and relationship row counts:

```bash
wc -l \
  /path/to/outputs/TCGA-BRCA/methylation_observations.csv \
  /path/to/outputs/TCGA-BRCA/sample_has_methylation_observation.csv \
  /path/to/outputs/TCGA-BRCA/methylation_observation_measures_cpg.csv \
  /path/to/outputs/TCGA-BRCA/methylation_observation_classified_using.csv
```

When classification is active, these four files should normally have the same number of data rows. Each CSV also has one header row.

---

## Graph Model

```text
(:Sample)
   │
   └──[:HAS_METHYLATION_OBSERVATION]
          ↓
(:MethylationObservation)
   │
   ├──[:MEASURES_CPG]──────────────→(:CpGSite)
   │
   └──[:CLASSIFIED_USING]──────────→(:MethylationStatusRule)
```

This design separates:

- sample identity;
- sample-specific methylation measurements;
- stable CpG reference entities; and
- the reusable classification rule applied to each observation.

---

## Important Implementation Notes

1. **The node mappings are configuration-driven, but the workflow is not completely generic.** Required graph components, file patterns, filenames, relationship endpoints, and several validation rules are explicitly implemented in `methylation.py`.

2. **Relationship properties are not currently exported.** The three edge files contain identifiers only.

3. **The current output structure is flat within each cohort.** A `nodes/` and `edges/` directory layout would require a code or packaging change.

4. **Full materialisation is very large.** With no sample or CpG filter, the workflow writes every valid sample–CpG measurement to external staging CSVs.

5. **Graph loading should remain selective.** Complete long-format files may be retained in external staging, while only query-relevant observations should be loaded into Neo4j.

6. **Rule nodes must be merged by primary key.** The same `MethylationStatusRule` is intentionally repeated in every cohort output.

7. **Do not ingest `.tmp` files.** They indicate incomplete processing.

8. **Runtime and storage are environment-dependent.** The Python and shell scripts do not guarantee a fixed runtime or output size. These depend on cohort dimensions, filesystem throughput, cluster load, filtering, and chunk size.
