# Thesis Research Proposal

**Working title:** *Biologically-Informed Heterogeneous Graph Neural Networks for
Multi-Omics Cancer Survival Prediction and Biomarker Discovery*

**Candidate:** Miguel Alburo
**Date:** 2026-07-04
**Platform:** LifeSphere — a config-driven ETL pipeline harmonising GDC clinical,
biospecimen, and multi-omics cancer data into a Neo4j knowledge graph.

---

## 1. Background

Prognostic modelling in oncology increasingly draws on *multi-omics* data —
transcriptomic, epigenomic, genomic, and proteomic measurements of the same tumour.
The dominant modelling pattern concatenates these modalities into a single flat
feature vector fed to a regularised Cox model or a feed-forward network. This
discards the relational structure that biology actually has: a gene participates in
pathways, a variant affects a gene, a gene encodes a protein. Two measurements that
are mechanistically linked are, to a flat model, just two more columns.

Knowledge graphs restore that structure. LifeSphere already encodes it: omics
measurements are **reified** as observation nodes wired
`Sample → Observation → Feature`, features (`Gene`, `CpGSite`, `Variant`, `Protein`,
`Pathway`) are **shared, deduplicated dimensions**, and curated biological priors
(`AFFECTS_GENE`, `PARTICIPATES_IN_PATHWAY`, `ENCODES`) connect them. Survival
endpoints (`OverallSurvival`, `ProgressionFreeInterval`, `DiseaseFreeInterval`) are
derived per-subject with an `event` flag and `time_days`. The graph is therefore a
ready substrate for a **heterogeneous graph neural network (GNN)** whose message
passing follows real biology rather than a flattened matrix.

## 2. Research gap

> Multi-omics cancer-survival models predominantly operate on flattened feature
> vectors or on a single molecular network (typically protein–protein interaction),
> and treat interpretability as a post-hoc feature-importance ranking. Few methods
> learn directly over a **harmonised, reified, multi-omics knowledge graph** in which
> curated biological edges serve as the inductive bias, and fewer still exploit that
> same graph structure to produce **mechanistically meaningful, subgraph-level
> explanations** of a prognosis.

This gap has two halves that this project is unusually well-positioned to close,
because LifeSphere supplies the harmonised graph and the derived survival labels that
such a study would otherwise have to build from scratch.

## 3. Research questions

1. **Predictive.** Does a biologically-informed heterogeneous GNN over the LifeSphere
   KG improve survival discrimination (OS / PFI / DFI) over strong flat-feature
   baselines (regularised Cox, gradient-boosted trees, MLP on concatenated omics)?
2. **Structural.** How much of any gain is attributable to the *biological prior
   edges* specifically — i.e. does ablating `PARTICIPATES_IN_PATHWAY` / `AFFECTS_GENE`
   / `ENCODES` degrade performance?
3. **Explanatory.** Do the model's explanation subgraphs (attention weights /
   GNNExplainer) recover known cancer-relevant genes and pathways, and do they yield
   testable biomarker hypotheses beyond the flat-model feature ranking?

## 4. Approach

**Data & pipeline (contribution 0).** Extend and run the LifeSphere pipeline to load a
real pan-cancer TCGA cohort end-to-end. The clinical backbone and survival layer are
already load-tested; the omics bridge is currently verified on synthetic fixtures
only. Running `src/extract/omics_reshape.py` on a live `gdc-client` download and
ingesting Omnipath static-biology edges is therefore treated as **part of the thesis
contribution**, not a given — it hardens the reified multi-omics layer into a real,
reproducible graph.

**Model (contribution 1).** A heterogeneous GNN — heterogeneous GraphSAGE, R-GCN, or a
Heterogeneous Graph Transformer (HGT) — that produces a `Subject`-level embedding by
message passing through the `Subject → Sample → Observation → Feature` structure and
across the biological prior edges. A survival head (DeepSurv-style Cox partial
likelihood, or a discrete-time hazard head) maps the embedding to a risk score.
Trained separately per endpoint (OS / PFI / DFI) and, if time allows, in a shared
multi-task setting.

**Explainability (contribution 2).** For a held-out cohort, extract per-prediction
explanation subgraphs via GNNExplainer / attention over the heterogeneous edges. Because
the edges are explicit biology, a highlighted `Gene → Pathway` path *is* a mechanistic
hypothesis. Validate recovered genes/pathways against curated cancer references
(e.g. COSMIC Cancer Gene Census, MSigDB Hallmark) and compare the biological coherence
of GNN explanations against flat-model feature-importance rankings.

## 5. Evaluation

- **Discrimination:** Harrell's C-index and time-dependent AUC, with confidence
  intervals from patient-level bootstrap; stratified cross-validation by cancer type.
- **Baselines:** regularised Cox (elastic net), gradient-boosted survival trees, and an
  MLP on the same features concatenated flat — isolating the value of graph structure.
- **Ablations:** remove biological prior edges; remove individual omics modalities;
  swap the heterogeneous GNN for a homogeneous one — answering RQ2.
- **Explanation quality:** enrichment of explanation genes/pathways in curated cancer
  reference sets; overlap and biological-coherence comparison against flat baselines.

## 6. Scope, risks, and mitigations

| Risk | Mitigation |
|---|---|
| Live omics ingestion not yet run on real GDC data | Core study stands on the load-tested clinical + survival layers; omics loading is scoped as an explicit thesis deliverable with the synthetic fixture as a fallback for pipeline validation. |
| Missing modalities per sample (data sparsity) | GNN naturally tolerates variable neighbourhoods; report per-modality-availability strata. |
| Small effective sample size per cancer type | Pan-cancer training with cancer-type as covariate; transfer/fine-tune per type. |
| Explanations not biologically meaningful | Pre-register curated reference sets; treat a null result (GNN no more coherent than flat) as a reportable finding. |

**Out of scope (future work):** the single-cell / spatial layer (`Cell` + `ADJACENT_TO`)
is an inert scaffold with no reshaper emitting data; a spatial-GNN extension is noted as
a natural follow-on but not attempted here.

## 7. Expected contributions

1. A hardened, reproducible pipeline that materialises a real pan-cancer multi-omics
   survival knowledge graph from the GDC.
2. A biologically-informed heterogeneous GNN for cancer survival, benchmarked against
   flat-feature baselines with structure-isolating ablations.
3. An analysis of whether graph-structured explanations yield more biologically
   coherent biomarker hypotheses than conventional feature-importance methods.

## 8. Indicative timeline

| Phase | Months | Output |
|---|---|---|
| Pipeline hardening + live omics load | 1–2 | Reproducible pan-cancer KG in Neo4j |
| Baselines + data splits | 2–3 | Flat-model benchmark, evaluation harness |
| Heterogeneous GNN + survival head | 3–6 | Trained models, C-index results (RQ1–2) |
| Explainability + biological validation | 6–8 | Explanation study (RQ3) |
| Writing | 8–10 | Thesis |

---

*Grounded in the LifeSphere data model
([`docs/dev_guides/kg_data_model.md`](dev_guides/kg_data_model.md)) and BioCypher
schema ([`config/schema_config.yaml`](../config/schema_config.yaml)).*
