#!/bin/bash
# Submit all TCGA extraction jobs. Run from anywhere — paths come from .env.

SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
source "${SCRIPT_DIR}/../.env"

sbatch --chdir="${PROJECT_DIR}" "${SCRIPT_DIR}/extract_TCGA_clinical.sh"
sbatch --chdir="${PROJECT_DIR}" "${SCRIPT_DIR}/extract_TCGA_expression.sh"
sbatch --chdir="${PROJECT_DIR}" "${SCRIPT_DIR}/extract_TCGA_methylation.sh"
sbatch --chdir="${PROJECT_DIR}" "${SCRIPT_DIR}/extract_TCGA_variation.sh"
