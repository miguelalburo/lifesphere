#!/bin/bash
# Submit the TCGA omics reshape *resume* jobs (expression + methylation).
# Offline re-run of reshape() from already-downloaded raw files — finishes a
# partial/empty *_observation.tsv without touching the network. Use after a
# full extraction whose download phase completed but reshape did not.
# Run from anywhere — paths come from .env.

SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
source "${SCRIPT_DIR}/../.env"

TS="$(date -d "today" +"%d%m%Y%H%M")"
mkdir -p "${LOG_DIR}/extraction"

sbatch --chdir="${PROJECT_DIR}" --output="${LOG_DIR}/extraction/expression_resume_%j_${TS}.log"  "${SCRIPT_DIR}/extract_TCGA/resume_TCGA_expression.sh"
sbatch --chdir="${PROJECT_DIR}" --output="${LOG_DIR}/extraction/methylation_resume_%j_${TS}.log" "${SCRIPT_DIR}/extract_TCGA/resume_TCGA_methylation.sh"
