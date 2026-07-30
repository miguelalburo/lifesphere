<!-- title: data/raw Compatibility Analysis & Ingestion Proposals -->

# `data/raw` Compatibility Analysis

**Question:** are the 33 TCGA cancer-type datasets sitting in `data/raw/` compatible with the current schema (`config/schema/*.yaml`) and ingestion code (`src/extract`, `src/reshape`, `src/standardise`, `config/mapping/*.yaml`)? **Short answer: no — 0 of 33 are pipeline-ready as-is.** None of the raw files match either of the two file-naming contracts the code understands (`extract.yaml`'s GDC-API names, or `traditional.yaml`'s hardcoded matrix/VCF names). Getting any of them into `data/standardised/` requires new work, not just running an existing command. This report inventories what's actually there, itemizes every compatibility gap found (config-only vs. real code gaps), and proposes four ways forward.

## 1. What's in `data/raw`

33 folders (`TCGA-ACC` … `TCGA-UVM`), ~250 files total, downloaded from what looks like a mix of sources (UCSC Xena Pan-Cancer Atlas hub, GDC bulk clinical/biospecimen exports, and TCGA Pan-Cancer publication supplementary tables) — not this repo's own `src/extract` GDC-API puller, and not hand-authored "traditional" inputs either.

| Pattern found in every / most folders | Count | Shape |
|---|---|---|
| `All_PanCancer_Subtypes.csv` | 31/33 folders (missing: ACC, BRCA) | Shared pan-cancer molecular-subtype table, **byte-identical across all 31 folders that have it** (verified by checksum) |
| `TCGA_CDR_Survival_Master.csv` | 31/33 folders (missing: ACC, BRCA) | Shared pan-cancer clinical/survival master table (11,161 rows spanning every TCGA project), **byte-identical across all 31 folders** — same file copied into each, not pre-filtered |
| `*_biospecimen.csv` | 33/33 | GDC biospecimen bulk-export shape, wide, ~50+ columns, quoted CSV |
| `*_clinical.csv` / `*.clinical.tsv` | 32/33 (missing: LAML) | Two **different** schemas coexist across the corpus (see §3.2) |
| `*_survival.csv` / `*.survival.tsv` | 32/33 (missing: BLCA — relies on the shared CDR master instead) | Per-project slice of TCGA's Clinical Data Resource (CDR) survival schema |
| `*_tpm_unstranded.tsv` / `*_unstranded_counts.tsv` | 33/33 | Wide, genes × samples, Ensembl gene ids (versioned, e.g. `ENSG00000000003.15`) |

Outliers, in order of increasing richness:

- **ACC** — Xena-exported dot-named files (`TCGA-ACC.clinical.tsv`, `.survival.tsv`, `.star_tpm.tsv`) instead of the shared-file pattern, **plus** `.methylation450.tsv` (450K array beta values) and `.somaticmutation_wxs.tsv` (MAF-style long-form mutation calls), **plus** an hg38 CpG probe manifest (`HM450.hg38.manifest.gencode.v36.tsv`).
- **PRAD** — the standard pattern **plus** its own dot-named methylation450/star_tpm files (both naming conventions coexist here).
- **SARC** — the standard pattern **plus** dot-named mutation/FPKM-UQ expression files, **plus** a differently-named methylation matrix (`TCGA_SARC_HumanMethylation450.tsv`) and an **hg19** probe map (`probeMap_illuminaMethyl450_hg19_GPL16304_TCGAlegacy.tsv` — note the build mismatch against ACC's hg38 manifest).
- **BRCA** — richest by far, and the only folder with **no** shared pan-cancer files at all. Has its own clinical/survival/biospecimen, plus `_methylation_matrix.tsv`, `_proteomics_matrix.tsv` (RPPA antibody panel), `_variation_cnv.tsv` (copy-number calls, not SNVs), `_clinical_marker.csv` (PAM50/ER/PR/HER2 status), `_design_matrix.csv` (subtype/risk grouping), and **18 downstream statistical-analysis files** — a full differential-expression table, 9 GO over-representation result files, 3 KEGG enrichment result files, and 3 DESeq2 (`res_*_Ord.csv`) output tables.

`data/standardised/` and `data/interim/` are currently empty (just `.gitkeep`) — nothing has been run against this data yet.

## 2. How the pipeline actually expects data to look

Two contracts exist today, neither of which matches what's on disk:

- **`config/mapping/extract.yaml`** (the "extract" profile) expects `program.tsv`, `study.tsv`, `subject.tsv`, `sample.tsv`, `diagnosis.tsv`, `pathology_detail.tsv`, `survival.tsv`, `exposure.tsv`, `treatment.tsv` — lowercase, no dataset prefix, GDC-API column names. These are produced by `src/extract/entities/*.py` querying the live GDC API (`src/extract/gdc_api.py`), not by downloading bulk files.
- **`config/mapping/traditional.yaml`** (the "traditional" profile, reused via `include: [omics]`) is a **template**: its header comment says "rename in this profile to match your dataset," and it hardcodes placeholder filenames (`sample_metadata.tsv`, `expression_matrix.tsv`, `methylation_matrix.tsv`, `variants.vcf`) that a new profile is meant to override per dataset. None of the 33 folders' actual filenames match these placeholders, and no per-dataset profile overriding them has been written yet.

Neither contract is "broken" — they just haven't been pointed at this particular data source yet.

## 3. Gap analysis

### 3.1 File-naming / pipeline-path mismatch — universal, blocks all 33 datasets

Every file in `data/raw` uses either a `TCGA-<CODE>_snake_case.ext` or `TCGA-<CODE>.dot.case.ext` convention foreign to both `extract.yaml` and `traditional.yaml`. This alone means `python -m src.standardise <dataset> --profile extract` or `--profile traditional` fails immediately (missing source files) for every one of the 33 folders today.

### 3.2 Identity-space mismatch: what is `Sample.sampleId`?

- In the `extract` (GDC-API) path, `Sample.sampleId` is minted from the **GDC aliquot UUID** (`src/extract/entities/sample.py`: `row["sample_id"] = aliquot.get("aliquot_id", "")`). The human-readable TCGA barcode is a *secondary* property, `externalSampleId`.
- Every downloaded matrix, clinical, survival, and mutation file in `data/raw` uses the **TCGA barcode** (`TCGA-OR-A5LF-01A`) as its only identifier — there is no GDC UUID anywhere in these files.
- A profile binding this data must therefore follow `traditional.yaml`'s pattern (barcode-as-primary-key), not `extract.yaml`'s. Mixing the two is not possible without an explicit UUID↔barcode crosswalk, which doesn't exist.
- One of the two clinical schemas (the dot-named Xena export, e.g. `TCGA-ACC.clinical.tsv`) makes this worse by mixing **both** spaces in one row: `case_id`/`id` columns hold GDC UUIDs, while `submitter_id` (patient barcode) and `sample` (full sample barcode) hold TCGA barcodes — a profile author needs to pick the barcode columns deliberately, not the first UUID-looking column.

### 3.3 No row-filtering in the mapping engine — the two shared pan-cancer files

`TCGA_CDR_Survival_Master.csv` and `All_PanCancer_Subtypes.csv` are the **same pan-cancer table** copied verbatim into 31 folders (confirmed by checksum — identical MD5 in every folder that has them). Loading, say, TCGA-CESC's copy of the CDR master naively would pull in survival records for all ~33 TCGA projects, not just CESC — `src/standardise/mapping.py`'s `NodeMapping`/`EdgeMapping` dataclasses have **no `filter:` field at all**; every node/edge binding consumes 100% of its bound file's rows (minus dedup). This is a genuine code gap, not just a missing config entry: there is currently no way to say "only rows where `type == 'CESC'`" declaratively. Confirmed empirically: CESC's dedicated `_survival.csv` has 307 data rows, matching almost exactly the 307 CESC-tagged rows inside the 11,161-row shared master — so the data to slice out is there, the mechanism to slice it isn't.

### 3.4 Proteomics/metabolomics ingestion is missing at the **code** level, not just unmapped

`config/schema/nodes.yaml`/`edges.yaml` fully define `ProteinObservation`, `MetaboliteObservation`, and their edges. But the reshape/observation contract layer does not:

- `src/observation.py` defines `EXPRESSION_OBS_COLUMNS`, `METHYLATION_OBS_COLUMNS`, `VARIATION_OBS_COLUMNS` — **no `PROTEIN_OBS_COLUMNS` or `METABOLITE_OBS_COLUMNS`**, and `DERIVED_KEYS` has entries for `ExpressionObservation`/`MethylationObservation`/`VariantObservation` only.
- `src/reshape/matrix.py`'s `_OBS_PROFILES` dict has exactly two keys, `"expression"` and `"methylation"`. Calling the melt with `observation: protein` raises `ValueError: unknown observation type 'protein'` — there is no code path that can turn a wide protein/metabolite matrix into observation rows today.

BRCA's `_proteomics_matrix.tsv` (a 488-row RPPA antibody panel) therefore **cannot be ingested through any existing code path** — this needs new code, not a new config file.

There's a second, independent limitation compounding this: `melt_matrix` supports exactly **one** `feature_id_column`. The proteomics matrix has five metadata columns per row (`Protein_ID, Gene_Symbol, Ensembl_ID, Modification_Type, Modification_Site`); today, only one can be the feature id and the rest must be listed in `ignore_columns` — where they are silently dropped, not carried into the observation. Even after adding a `"protein"` observation profile, PTM/modification-site information would still be lost unless the melt function itself is extended to carry extra per-feature columns. There is also no natural UniProt id here at all (`Protein_ID` values look like `AGID00100`, an antibody-array id) — `Protein.proteinId`'s documented UniProt-based identity has no clean source value in this dataset.

### 3.5 Variant format gap: MAF-style TSV isn't VCF; CNV isn't SNV

- `*.somaticmutation_wxs.tsv` (ACC, SARC) is a long-form, MAF-like table (`sample, gene, chrom, start, end, ref, alt, ..., callers, dna_vaf`) — **not** VCF format. `src/reshape/vcf.py`'s dedicated reader expects a `#CHROM` header line and per-sample genotype columns and cannot parse this. Since the file is already tidy/long (one row per variant call, not a wide matrix), it doesn't need `reshape:` at all — it could in principle be bound directly via `nodes:`/`edges:` like `sample.tsv` is, with new aliases (`sample`→ not `sample_id`, `gene`→not `gene_id`, etc.). That binding hasn't been written.
- `_variation_cnv.tsv` (BRCA) is copy-number data, not point mutations: its `Reference_Allele`/`Alternate_Allele` columns hold **ploidy values** (`"2"`, `"1"`) rather than nucleotide bases. Loading this under `Variant.referenceAllele`/`alternateAllele` — the same properties the VCF path fills with `"C"`/`"T"` — would conflate two different meanings under one property name unless `variantClass = "CNV"` rows are handled with distinct semantics somewhere downstream.

### 3.6 Methylation reference/build inconsistency

ACC ships an **hg38** CpG probe manifest (`HM450.hg38.manifest.gencode.v36.tsv`); SARC ships an **hg19** probe map (`probeMap_illuminaMethyl450_hg19_GPL16304_TCGAlegacy.tsv` — note "TCGAlegacy" in the filename). Same array, two different genome builds, in a corpus where `CpGSite`'s reference annotation is currently unpopulated project-wide (per the earlier schema-migration work) and where `CpGSite.referenceGenome`/`genomeBuild` would need to be tracked per source file, not assumed constant across the corpus. Also worth checking before load: SARC's methylation sample barcodes appear shorter (no trailing vial letter, e.g. `TCGA-DX-A1KX-01`) than ACC/BRCA's methylation barcodes (`TCGA-OR-A5K2-01A`) — a potential join-key granularity mismatch within SARC specifically that needs verifying against that dataset's own expression/clinical barcodes before trusting a join.

### 3.7 Multiple expression units per sample+gene — a `DERIVED_KEYS` collision risk

Most folders carry both `_tpm_unstranded.tsv` and `_unstranded_counts.tsv` for the same samples/genes (ACC/SARC add a third: STAR TPM or FPKM-UQ). `ExpressionObservation`'s derived id is minted from `(sample_id, gene_id)` only (`src/observation.py::DERIVED_KEYS`) — loading two unit variants for the same sample/gene pair through two reshape passes into the same output would collide on the same `expressionObservationId` (last-write-wins on MERGE), not produce two distinct observations. Only one unit can be loaded per sample/gene pair without either picking one and dropping the rest, or extending the key/id scheme to fold in the unit.

### 3.8 Scope boundary, not a defect: BRCA's differential-expression / enrichment bundle

`BRCA_Differential_Gene_Expression_Table.txt`, all 9 `ORA_GO_*` files, 3 `ORA_KEGG_*` files, and 3 `res_*_Ord.csv` (DESeq2 output) files are downstream statistical-analysis products (differential expression, GO/KEGG over-representation analysis). The schema's own design document is explicit that the KG "does not currently perform statistical testing, differential analysis, marker discovery, enrichment, deconvolution, trajectory inference, pseudotime analysis, or downstream modelling" (§1.2) — there is intentionally no `DifferentialExpressionResult` or `PathwayEnrichmentResult` node type. This isn't a pipeline bug to fix; it's 18 files that fall outside the graph's stated purpose by design, and any proposal to ingest them is really a proposal to expand that scope.

### 3.9 Smaller items worth knowing about before loading

- **Placeholder tokens**: `config/placeholders.yaml` scrubs `"NA"`, `"Not Reported"`, etc., but **not** the bracket-wrapped tokens (`"[Not Available]"`, `"[Not Applicable]"`) used throughout the CDR-style clinical/survival files — these would land as literal garbage strings in node properties without an addition to that list.
- **Embedded R-serialized values**: some `*_biospecimen.csv` columns contain R vector syntax inside CSV cells (e.g. an `analyte_id` cell containing `c("uuid1", "uuid2")`-style text) — these need cleaning before they're usable as scalar properties; a naive bind would inject R syntax into the graph.
- **LAML has no dedicated clinical file** and **BLCA has no dedicated survival file** — genuine per-cohort data gaps in the source, not pipeline defects; a profile needs to fall back to the shared CDR master for BLCA's survival data specifically, and accept sparser `Diagnosis` coverage for LAML.
- **One clean compatibility point**: Ensembl gene ids across every expression/methylation-adjacent file already carry version suffixes (`ENSG00000000003.15`) exactly as `src/observation.py::strip_version()` expects — gene-dimension joining across all 33 datasets and the existing `Gene` reference dimension should work cleanly once a profile exists.

## 4. Compatibility summary

| Raw file pattern | Target node(s) | Compatible via existing code? | Blocking gap |
|---|---|---|---|
| `*_biospecimen.csv` | `Sample` | Partially — needs a new profile + R-syntax cleanup | Config gap + data cleaning |
| `*_clinical.csv` / `.clinical.tsv` | `Subject`, `Diagnosis`, `Sample` | Partially — two different schemas need two different bindings | Config gap (no code blocker) |
| `*_survival.csv` / `.survival.tsv` / CDR master | `Survival` | Partially — CDR master needs row-filtering support | Config gap **+ code gap** (§3.3) |
| `All_PanCancer_Subtypes.csv` | *(no matching node — subtype calls per omics layer)* | No — needs row-filtering, and no schema home for multi-omics subtype calls | Code gap (§3.3) + schema gap |
| `*_tpm_unstranded.tsv` / `*_unstranded_counts.tsv` / `.star_tpm.tsv` | `ExpressionObservation` | Yes, structurally — but only one unit per sample/gene without a key-scheme change | Config gap; DERIVED_KEYS limit if both units wanted (§3.7) |
| `.methylation450.tsv` / `*_methylation_matrix.tsv` | `MethylationObservation`, `CpGSite` | Yes, structurally | Config gap + genome-build tracking (§3.6) |
| `*.somaticmutation_wxs.tsv` (MAF-style) | `VariantObservation`, `Variant` | No — not VCF-shaped, needs direct table binding | Config gap, no reshape needed |
| `*_variation_cnv.tsv` | `VariantObservation`, `Variant` | Questionable — allele fields hold ploidy, not bases | Schema semantics gap (§3.5) |
| `*_proteomics_matrix.tsv` | `ProteinObservation`, `Protein` | **No** | **Code gap** — no protein observation contract exists at all (§3.4) |
| `*_clinical_marker.csv`, `*_design_matrix.csv` | *(no matching node)* | No | Schema gap — no biomarker-status / cohort-grouping node exists |
| Differential-expression / ORA-GO / ORA-KEGG / `res_*_Ord.csv` | *(no matching node, deliberately)* | No, by design | Out of stated scope (§3.8) |

## 5. Proposals

### Proposal 1 — New "TCGA bulk-download" mapping profile (config-only, fastest path)

Write a new `config/mapping/tcga_bulk.yaml` profile (parallel to `traditional.yaml`, reusing `include: [omics]` for the expression/methylation reshape machinery) that binds directly to the actual filenames present: `*_biospecimen.csv` → `Sample`, `*_clinical.csv`/`.clinical.tsv` → `Subject`/`Diagnosis` (two variants, may need two sub-profiles or a per-dataset override), `*_survival.csv` → `Survival`, `*_tpm_unstranded.tsv` → `ExpressionObservation` via the existing `matrix` reshaper.

- **Covers:** all 27 "standard" cohorts' clinical/survival/expression data — the bulk of the corpus.
- **Explicitly excludes:** the two shared pan-cancer files (until Proposal 4 or a pre-split lands), proteomics, CNV, and the BRCA analysis bundle.
- **Effort:** low — no code changes, just new YAML plus the aliasing work already demonstrated in `extract.yaml`/`traditional.yaml`.
- **Risk:** without also doing something about §3.3, this profile must simply not bind the two shared files, or it will silently produce cross-cancer-type contamination.

### Proposal 2 — Pre-processing "landing zone" stage ahead of the existing pipeline

Add a small, separate script/stage (not touching `src/standardise` at all) that runs **before** ingestion and normalizes `data/raw/<dataset>/` into the shapes the existing profiles already expect: renames files to match a chosen profile's filenames, splits/filters the two shared pan-cancer files down to one cancer type each (writing a per-project `survival.csv`/`subtypes.csv`), and converts the MAF-style mutation TSV into a minimal synthetic VCF (or simply routes it to direct table binding instead, avoiding the VCF reader entirely).

- **Covers:** everything Proposal 1 covers, plus resolves the shared-file contamination risk without touching `src/standardise/mapping.py`.
- **Effort:** medium — one new script, but it keeps the "config is the source of truth" architecture unchanged; the existing profiles stay the single binding contract.
- **Risk:** introduces a second stage to keep in sync if the source data's shape changes; the split/rename logic itself needs its own tests.

### Proposal 3 — Extend the schema/code for the richer omics types (proteomics, CNV)

Accept that proteomics and CNV genuinely need new code, not just config, and do it explicitly: add `PROTEIN_OBS_COLUMNS`/`METABOLITE_OBS_COLUMNS` to `src/observation.py`, add matching `DERIVED_KEYS` entries, add `"protein"`/`"metabolite"` profiles to `src/reshape/matrix.py::_OBS_PROFILES`, and either accept `melt_matrix`'s single-feature-id-column limit (dropping PTM/modification-site data) or extend it to carry extra per-feature metadata columns if that data matters. Separately, decide explicitly whether CNV-type variants get their own node/relationship shape (since `referenceAllele`/`alternateAllele` don't fit) or stay out of `Variant` entirely.

- **Covers:** BRCA's proteomics matrix and CNV calls — the two pieces of data no other proposal can touch.
- **Effort:** highest — genuine code changes to the shared observation/reshape contract, needs new tests (mirroring the existing `test_reshape_matrix.py`/`test_expression_reshape.py` pattern).
- **Risk:** touches code every dataset's ingestion depends on (`src/observation.py` is explicitly the "one neutral module both ingest paths import") — needs care not to regress expression/methylation.
- **Explicitly out of scope even after this proposal:** the 18-file differential-expression/enrichment bundle (§3.8) — that's a scope decision, not an engineering gap this proposal should try to close.

### Proposal 4 — Add row-filtering to the mapping engine itself (small, generalizable code change)

Add an optional filter (e.g. `filter: {column: type, equals: "${dataset_code}"}` or similar) to `NodeMapping`/`EdgeMapping` in `src/standardise/mapping.py`, so a profile can bind directly to a shared/unfiltered file and declare which rows belong to the current dataset. This turns §3.3 from "don't bind these files" into "bind them safely."

- **Covers:** unblocks binding `TCGA_CDR_Survival_Master.csv` and `All_PanCancer_Subtypes.csv` directly, no separate pre-split step needed, and generalizes to any future shared-reference-file scenario (not just this corpus).
- **Effort:** low-to-medium — one new dataclass field, one new filtering step in the row-resolution loop, tests mirroring `tests/test_load.py`/`tests/test_standardise.py`.
- **Risk:** lowest of the four — additive, opt-in, doesn't change behavior for any binding that doesn't declare a filter.

### Recommendation shape (not a decision — for discussion)

Proposals 1 and 4 are small, additive, and together unblock the 27 standard cohorts' clinical/survival/expression data cleanly, without a separate pre-processing stage. Proposal 3 is a separate, larger initiative worth scoping on its own once the standard cohorts are flowing, since it touches the shared observation contract every dataset depends on. Proposal 2 is a reasonable alternative to Proposal 4 if adding a `filter:` concept to the mapping engine is considered too broad a change to the core contract — it trades a slightly larger one-off script for a smaller, safer change to shared code.
