# GDC Data Overview

## What is GDC?

The **Genomic Data Commons (GDC)** is an NCI data repository and harmonisation platform that stores, standardises, and distributes cancer genomics data. Raw data from multiple programmes (TCGA, TARGET, CPTAC, CGCI, etc.) is processed through uniform bioinformatics pipelines and made available via a portal and API.

API base: `https://api.gdc.cancer.gov/`

---

## TCGA vs. the Pan-Cancer Atlas

| | TCGA | Pan-Cancer Atlas |
|---|---|---|
| **What it is** | A data collection programme (2006–2018) | A coordinated analysis project |
| **Output** | Raw + processed omics data for 33 cancer types across ~11,000 patients | 27 Cell papers (2018) analysing all 33 cohorts jointly |
| **Lives on GDC?** | Yes — the 33 TCGA projects are the source data | Same data; the distinction is analytical scope |
| **Use case** | Single-cohort or multi-cohort omics analysis | Cross-cancer comparisons following the Atlas methodology |

The underlying GDC data is identical — "pan-cancer analysis" simply means pooling all 33 TCGA cohorts together rather than analysing one at a time.

---

## Projects with Open-Access Omics Data

The following 43 GDC projects have **open-access** data for all three of:
- Gene expression (Transcriptome Profiling)
- DNA methylation (DNA Methylation)
- Genomic variants (Simple Nucleotide Variation)

| Project | Program | Primary Site | Name |
|---|---|---|---|
| CCG-CUPP | CCG | Unknown | Cancers of Unknown Primary |
| CGCI-HTMCP-CC | CGCI | Cervix uteri | HIV+ Tumor Molecular Characterization – Cervical Cancer |
| CPTAC-3 | CPTAC | Multiple | Brain, Head/Neck, Kidney, Lung, Pancreas, Uterus |
| HCMI-CMDC | HCMI | Multiple | NCI Cancer Model Development |
| RC-PTCL | RC | Liver / bile duct | Refractory Cancers – Peripheral T-Cell Lymphoma |
| TARGET-ALL-P3 | TARGET | Haematopoietic | Acute Lymphoblastic Leukaemia – Phase III |
| TARGET-AML | TARGET | Haematopoietic | Acute Myeloid Leukaemia |
| TARGET-NBL | TARGET | Mediastinum | Neuroblastoma |
| TARGET-OS | TARGET | Bone | Osteosarcoma |
| TARGET-WT | TARGET | Kidney | High-Risk Wilms Tumour |
| TCGA-ACC | TCGA | Adrenal gland | Adrenocortical Carcinoma |
| TCGA-BLCA | TCGA | Bladder | Bladder Urothelial Carcinoma |
| TCGA-BRCA | TCGA | Breast | Breast Invasive Carcinoma |
| TCGA-CESC | TCGA | Cervix / Ovary | Cervical Squamous Cell Carcinoma |
| TCGA-CHOL | TCGA | Liver / bile duct | Cholangiocarcinoma |
| TCGA-COAD | TCGA | Colon | Colon Adenocarcinoma |
| TCGA-DLBC | TCGA | Colon | Diffuse Large B-cell Lymphoma |
| TCGA-ESCA | TCGA | Oesophagus | Oesophageal Carcinoma |
| TCGA-GBM | TCGA | Brain | Glioblastoma Multiforme |
| TCGA-HNSC | TCGA | Head and neck | Head and Neck Squamous Cell Carcinoma |
| TCGA-KICH | TCGA | Kidney | Kidney Chromophobe |
| TCGA-KIRC | TCGA | Kidney | Kidney Renal Clear Cell Carcinoma |
| TCGA-KIRP | TCGA | Kidney | Kidney Renal Papillary Cell Carcinoma |
| TCGA-LAML | TCGA | Haematopoietic | Acute Myeloid Leukaemia |
| TCGA-LGG | TCGA | Brain | Brain Lower Grade Glioma |
| TCGA-LIHC | TCGA | Liver | Liver Hepatocellular Carcinoma |
| TCGA-LUAD | TCGA | Lung | Lung Adenocarcinoma |
| TCGA-LUSC | TCGA | Lung | Lung Squamous Cell Carcinoma |
| TCGA-MESO | TCGA | Lung / pleura | Mesothelioma |
| TCGA-OV | TCGA | Peritoneum | Ovarian Serous Cystadenocarcinoma |
| TCGA-PAAD | TCGA | Pancreas | Pancreatic Adenocarcinoma |
| TCGA-PCPG | TCGA | Adrenal gland | Pheochromocytoma and Paraganglioma |
| TCGA-PRAD | TCGA | Prostate | Prostate Adenocarcinoma |
| TCGA-READ | TCGA | Rectum | Rectum Adenocarcinoma |
| TCGA-SARC | TCGA | Retroperitoneum | Sarcoma |
| TCGA-SKCM | TCGA | Skin | Skin Cutaneous Melanoma |
| TCGA-STAD | TCGA | Stomach | Stomach Adenocarcinoma |
| TCGA-TGCT | TCGA | Testis | Testicular Germ Cell Tumours |
| TCGA-THCA | TCGA | Thyroid | Thyroid Carcinoma |
| TCGA-THYM | TCGA | Thymus | Thymoma |
| TCGA-UCEC | TCGA | Uterus | Uterine Corpus Endometrial Carcinoma |
| TCGA-UCS | TCGA | Uterus | Uterine Carcinosarcoma |
| TCGA-UVM | TCGA | Eye | Uveal Melanoma |

> Note: "Variants" here refers to Simple Nucleotide Variation (SNVs/indels from MAF/VCF files). Copy Number Variation is a separate `data_category` and would further narrow this list.

---

## Downloading Clinical & Biospecimen Data

### Available Formats

TCGA clinical/biospecimen data on GDC is **not** stored as CSV or TSV. The available formats are:

| Format | Count (TCGA-BRCA) | Description |
|---|---|---|
| BCR XML | ~3,400 | Legacy TCGA XML supplements |
| BCR BioTab | 19 | Tab-delimited clinical/biospecimen tables |
| PDF | ~1,100 | Pathology reports |
| SVS | ~3,100 | Whole slide images (very large) |

For tabular work, the two practical sources are:

**1. BCR BioTab files** — tab-delimited flat files produced by the TCGA Biospecimen Core Resource, downloaded via `gdc-client`. For TCGA-BRCA these cover:

| File | Content |
|---|---|
| `clinical_patient_brca.txt` | Core demographics, vital status, dates |
| `clinical_drug_brca.txt` | Drug/treatment records |
| `clinical_radiation_brca.txt` | Radiation treatment records |
| `clinical_follow_up_v*.txt` | Longitudinal follow-up visits (multiple versions) |
| `clinical_nte_brca.txt` | New tumour events |
| `clinical_omf_v4.0_brca.txt` | Other malignancy forms |
| `biospecimen_sample_brca.txt` | Sample-level metadata |
| `biospecimen_aliquot_brca.txt` | Aliquot-level metadata |
| `biospecimen_analyte_brca.txt` | Analyte QC metrics |
| `biospecimen_portion_brca.txt` | Portion metadata |
| `biospecimen_slide_brca.txt` | Slide metadata |
| `biospecimen_protocol_brca.txt` | Sample processing protocols |
| `biospecimen_shipment_portion_brca.txt` | Shipment records |
| `biospecimen_diagnostic_slides_brca.txt` | Diagnostic slide info |
| `ssf_tumor_samples_brca.txt` | SSF tumour sample metadata |
| `ssf_normal_controls_brca.txt` | SSF normal control metadata |

**2. GDC `/cases` API endpoint** — harmonised, GDC-standardised clinical data returned as JSON (flattened to TSV in the download script). One row per case, covering demographics, diagnosis, staging, treatments, exposures, and sample types.

### Download Script

`scripts/download_gdc_clinical.py` takes a project ID and output directory and downloads both sources:

```bash
python3 scripts/download_gdc_clinical.py TCGA-PRAD ~/Downloads/tcga-prad-clinical
```

Output structure:
```
<output_dir>/
  biotab/
    manifest.txt
    <uuid>/<filename>.txt   # one subdirectory per file
  gdc_clinical_<PROJECT>.tsv
```

---

## GDC Data Dictionary: Subject & Sample Entities

All temporal fields in GDC use **days-from-index** (e.g. `days_to_death`) rather than calendar dates. The anchor is set by `case.index_date` (e.g. Diagnosis, First Treatment).

### Entity Hierarchy

```
program
└── project
    └── case
        ├── demographic
        ├── diagnosis
        │   ├── treatment
        │   ├── pathology_detail
        │   └── molecular_test
        ├── exposure
        ├── follow_up
        │   ├── molecular_test
        │   └── other_clinical_attribute
        ├── family_history
        └── sample
            └── portion
                ├── slide
                └── analyte
                    └── aliquot
                        └── read_group
```

---

### Subject / Patient / Case Entities

#### `case` *(administrative)*
Root entity linking a patient to a project.

| Field | Type | Description |
|---|---|---|
| `primary_site` | enum (72) | Anatomic site of disease |
| `disease_type` | enum (59) | WHO ICD-O disease category |
| `index_date` | enum | Anchor for all day-offset fields |
| `lost_to_followup` | enum | Whether patient was lost to follow-up |
| `days_to_lost_to_followup` | integer | Days from index to loss |
| `consent_type` | enum | Type of consent obtained |

#### `demographic` *(links to: case)*
Core patient identity and survival fields.

| Field | Type | Description |
|---|---|---|
| `sex_at_birth` | enum | female / male / unknown |
| `gender` | enum | Patient gender identity |
| `race` | enum | Self-reported race |
| `ethnicity` | enum | Hispanic/Latino status |
| `vital_status` | enum | Alive / Dead / Unknown |
| `days_to_birth` | integer | Negative days from index to birth |
| `days_to_death` | integer | Days from index to death |
| `year_of_birth` / `year_of_death` | integer | Calendar year |
| `cause_of_death` | enum | Cancer-related, cardiovascular, etc. |
| `cause_of_death_source` | enum | Death certificate, autopsy, etc. |
| `age_at_index` | number | Age in years at index date |
| `country_of_birth` | enum (230) | Country of birth |
| `education_level` | enum | Highest education attained |
| `marital_status` | enum | Current conjugal status |

#### `diagnosis` *(links to: case)*
Primary disease characterisation — the most field-rich entity.

| Category | Key Fields |
|---|---|
| **Histology** | `primary_diagnosis` (2,600+ ICD-O terms), `morphology` (1,150+ codes), `tissue_or_organ_of_origin`, `site_of_resection_or_biopsy` |
| **AJCC staging** | `ajcc_pathologic_stage`, `ajcc_pathologic_t/n/m`, `ajcc_clinical_stage`, `ajcc_clinical_t/n/m`, `ajcc_staging_system_edition` |
| **Other staging** | FIGO, Ann Arbor, ENSAT, ISS, COG, INSS, INRG, IRS, IGCCCG, Masaoka, Enneking (MSTS) |
| **Disease-specific** | Gleason score/grade (prostate), WHO CNS grade, WHO NTE grade, Weiss score (adrenal), Clark level (melanoma), Child-Pugh (liver), CALGB risk group (AML), ELN classification (AML) |
| **Outcomes** | `days_to_last_follow_up`, `last_known_disease_status`, `progression_or_recurrence`, `days_to_recurrence`, `residual_disease` |
| **Other** | `age_at_diagnosis`, `days_to_diagnosis`, `year_of_diagnosis`, `prior_malignancy`, `prior_treatment`, `laterality`, `tumor_grade`, `tumor_focality`, `method_of_diagnosis` |

#### `treatment` *(links to: diagnosis)*

| Field | Type | Description |
|---|---|---|
| `treatment_type` | enum (70) | Surgery, chemotherapy, radiation, ablation, etc. |
| `therapeutic_agents` | enum (4,400+) | Named drug or agent |
| `treatment_intent_type` | enum | Adjuvant, curative, palliative, etc. |
| `days_to_treatment_start/end` | integer | Timing relative to index |
| `number_of_cycles` | integer | Chemotherapy cycles |
| `treatment_outcome` | enum | Complete response, progression, etc. |
| `route_of_administration` | array | IV, oral, topical, etc. |
| `prescribed_dose` / `prescribed_dose_units` | number / enum | Dosing information |
| `initial_disease_status` | enum | Disease state when treatment began |
| `reason_treatment_ended` | enum | Completion, adverse event, death, etc. |

#### `exposure` *(links to: case)*

| Category | Key Fields |
|---|---|
| **Tobacco** | `tobacco_smoking_status`, `pack_years_smoked`, `cigarettes_per_day`, `type_of_tobacco_used`, `tobacco_smoking_onset_year`, `tobacco_smoking_quit_year` |
| **Alcohol** | `alcohol_history`, `alcohol_intensity`, `alcohol_drinks_per_day`, `alcohol_days_per_week` |
| **Environment** | `exposure_type`, `asbestos_exposure_type`, `type_of_smoke_exposure`, `environmental_tobacco_smoke_exposure` |
| **Physical** | `bmi`, `height`, `weight`, `occupation_type`, `occupation_duration_years` |

#### `follow_up` *(links to: case, diagnosis)*
Longitudinal visit records.

| Field | Type | Description |
|---|---|---|
| `days_to_follow_up` | number | Days from index to visit |
| `disease_response` | enum (29) | CR, PR, PD, SD, etc. |
| `progression_or_recurrence` | enum | Yes / No / Unknown |
| `progression_or_recurrence_type` | enum | Local, distant, biochemical, etc. |
| `ecog_performance_status` | enum | 0–4 ECOG scale |
| `karnofsky_performance_status` | enum | 0–100 Karnofsky scale |
| `adverse_event` | enum (800+) | CTCAE adverse event term |
| `adverse_event_grade` | enum | Grade 1–5 |
| `imaging_type` | enum | CT, MRI, PET, bone scan, etc. |
| `imaging_result` | enum | Positive / Negative / Indeterminate |
| `days_to_progression` / `days_to_recurrence` | integer | Survival endpoints |

#### `family_history` *(links to: case)*
| Field | Description |
|---|---|
| `relationship_type` | 110+ relationship categories |
| `relationship_primary_diagnosis` | Cancer type in the relative |
| `relationship_age_at_diagnosis` | Age of relative at diagnosis |
| `relative_with_cancer_history` | Yes / No / Unknown |
| `relative_smoker` | Whether the relative was a smoker |

#### `molecular_test` *(links to: diagnosis, follow_up, slide)*
Clinical lab and biomarker results.

| Field | Description |
|---|---|
| `gene_symbol` | 743 cancer-relevant genes |
| `molecular_analysis_method` | FISH, IHC, PCR, NGS, flow cytometry, etc. |
| `test_result` | Amplified, deleted, mutated, elevated, etc. |
| `variant_type` | Deletion, amplification, fusion, SNP, etc. |
| `variant_origin` | Germline / Somatic |
| `laboratory_test` | 65+ named clinical lab tests |
| `hpv_strain` | HPV16, HPV18, and 12 others |
| `ploidy` | Diploid, aneuploid, hyperdiploid, etc. |

#### `other_clinical_attribute` *(links to: case, follow_up)*
Comorbidities and lifestyle factors not covered elsewhere.

| Category | Key Fields |
|---|---|
| **Body metrics** | `bmi`, `height`, `weight`, `body_surface_area` |
| **Comorbidities** | `comorbidities` (array), `risk_factors` (array), `diabetes_treatment_type` |
| **HIV** | `cd4_count`, `nadir_cd4_count`, `hiv_viral_load`, `haart_treatment_indicator`, `cdc_hiv_risk_factors` |
| **Reproductive** | `menopause_status`, `number_of_pregnancies`, `pregnant_at_diagnosis`, `hormonal_contraceptive_use`, `hysterectomy_type` |
| **Pulmonary** | `fev1_fvc_pre/post_bronch_percent`, `fev1_ref_pre/post_bronch_percent`, `dlco_ref_predictive_percent` |

#### `pathology_detail` *(links to: diagnosis)*
Detailed histopathology beyond what is in `diagnosis`.

| Category | Key Fields |
|---|---|
| **Invasion** | `vascular_invasion_present/type`, `lymphatic_invasion_present`, `perineural_invasion_present`, `extranodal_extension` |
| **Lymph nodes** | `lymph_nodes_positive`, `lymph_nodes_tested`, `lymph_node_involved_site`, `lymph_node_dissection_method` |
| **Tumour morphology** | `necrosis_present/percent`, `breslow_thickness` (melanoma), `greatest_tumor_dimension`, `tumor_largest_dimension_diameter` |
| **Margins** | `margin_status`, `circumferential_resection_margin`, `residual_tumor/measurement` |
| **Cell composition** | `percent_tumor_cells/nuclei`, `number_proliferating_cells`, `anaplasia_present` |
| **Prostate-specific** | `prostatic_chips_positive/total_count`, `prostatic_involvement_percent`, `zone_of_origin_prostate` |

---

### Sample / Biospecimen / Aliquot Entities

#### `sample` *(links to: case)*
Physical tissue collected from a patient.

| Field | Type | Description |
|---|---|---|
| `sample_type` | enum (50) | Primary tumour, blood-derived, solid tissue normal, metastatic, etc. |
| `tissue_type` | enum | Tumour / Normal / Peritumoral |
| `tumor_descriptor` | enum | Primary, metastatic, recurrence, premalignant, etc. |
| `biospecimen_anatomic_site` | enum (290+) | Named anatomic origin |
| `preservation_method` | enum | FFPE, frozen, fresh, cryopreserved, EDTA |
| `method_of_sample_procurement` | enum (100+) | Biopsy, resection, aspirate, autopsy, etc. |
| `initial_weight` / `current_weight` | number | Milligrams |
| `shortest/intermediate/longest_dimension` | number | Millimetres |
| `days_to_collection` | integer | Days from index to BCR receipt |
| `days_to_sample_procurement` | integer | Days from index to procurement procedure |
| `time_between_excision_and_freezing` | number | Minutes — cold ischaemia time |
| `diagnosis_pathologically_confirmed` | enum | Whether diagnosis was confirmed on this sample |

#### `portion` *(links to: sample)*
A sub-division of a sample sent for processing.

| Field | Description |
|---|---|
| `is_ffpe` | Whether fixed in formalin and paraffin-embedded |
| `weight` | Portion weight in milligrams |
| `portion_number` | Sequential identifier |

#### `slide` *(links to: portion, sample)*
Histological slide review data.

| Field | Description |
|---|---|
| `percent_tumor_cells` | % tumour cell content |
| `percent_tumor_nuclei` | % tumour nuclei |
| `percent_normal_cells` | % normal cell content |
| `percent_necrosis` | % necrotic cells |
| `percent_stromal_cells` | % reactive stromal cells |
| `percent_lymphocyte_infiltration` | % lymphocyte infiltration |
| `percent_granulocyte_infiltration` | % granulocyte infiltration |
| `number_proliferating_cells` | Count of proliferating cells |
| `section_location` | Tissue source of the slide |
| `tissue_microarray_coordinates` | TMA position if applicable |

#### `analyte` *(links to: portion, sample)*
Extracted nucleic acid quality metrics.

| Field | Description |
|---|---|
| `analyte_type` | DNA, RNA, FFPE DNA, FFPE RNA, cfDNA, etc. |
| `concentration` | mg/mL |
| `amount` | Total quantity (g or mL) |
| `analyte_quantity` | µg shipped for sequencing |
| `a260_a280_ratio` | DNA purity (spectrophotometry) |
| `rna_integrity_number` | RIN score (RNA quality) |
| `dna_integrity_number` | DIN score (DNA quality) |
| `ribosomal_rna_28s_18s_ratio` | RNA quality metric |
| `experimental_protocol_type` | Extraction method used |

#### `aliquot` *(links to: analyte, sample)*
The unit dispatched for a specific assay.

| Field | Description |
|---|---|
| `analyte_type` | DNA / RNA / etc. |
| `concentration` | mg/mL |
| `aliquot_quantity` / `aliquot_volume` | µg / µL |
| `no_matched_normal_wgs/wxs/low_pass_wgs/targeted_sequencing` | Flags indicating no matched normal exists |
| `selected_normal_wgs/wxs/...` | Which normal aliquot is preferred for variant calling |
| `source_center` | Centre that provided the aliquot |

#### `read_group` *(links to: aliquot)*
Sequencing library and run metadata — the lowest level of the hierarchy.

| Category | Key Fields |
|---|---|
| **Platform** | `platform` (Illumina, Ion Torrent, Complete Genomics, etc.), `instrument_model` (20 options) |
| **Library** | `library_strategy` (WGS, WXS, RNA-Seq, Bisulfite-Seq, ATAC-Seq, ChIP-Seq, etc.), `library_selection`, `library_strand`, `is_paired_end` |
| **Sequencing** | `read_length`, `sequencing_center`, `days_to_sequencing`, `flow_cell_barcode`, `lane_number` |
| **Target enrichment** | `target_capture_kit` (50+ panels), `target_capture_kit_vendor/version` |
| **Single-cell** | `single_cell_library` (Chromium 3′ v1–v4, Multiome, etc.), `number_expect_cells` |
| **Fragment info** | `fragment_mean/min/max_length`, `fragment_standard_deviation_length` |
| **Kit info** | `library_preparation_kit_name/vendor/version/catalog_number` |
