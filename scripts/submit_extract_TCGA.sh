#!/bin/bash
# Submit all TCGA extraction jobs. Run from anywhere — paths come from .env.

SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
source "${SCRIPT_DIR}/../.env"

TS="$(date -d "today" +"%d%m%Y%H%M")"
mkdir -p "${LOG_DIR}/extraction"

sbatch --chdir="${PROJECT_DIR}" --output="${LOG_DIR}/extraction/clinical_extraction_%j_${TS}.log"   "${SCRIPT_DIR}/extract_TCGA/extract_TCGA_clinical.sh"
sbatch --chdir="${PROJECT_DIR}" --output="${LOG_DIR}/extraction/expression_extraction_%j_${TS}.log"  "${SCRIPT_DIR}/extract_TCGA/extract_TCGA_expression.sh"
sbatch --chdir="${PROJECT_DIR}" --output="${LOG_DIR}/extraction/methylation_extraction_%j_${TS}.log" "${SCRIPT_DIR}/extract_TCGA/extract_TCGA_methylation.sh"
sbatch --chdir="${PROJECT_DIR}" --output="${LOG_DIR}/extraction/variation_extraction_%j_${TS}.log"   "${SCRIPT_DIR}/extract_TCGA/extract_TCGA_variation.sh"
