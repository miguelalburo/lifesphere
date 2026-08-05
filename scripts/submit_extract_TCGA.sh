#!/bin/bash
# Submit TCGA extraction jobs. Run from anywhere — paths come from .env.
#
# Usage:
#   scripts/submit_extract_TCGA.sh [--clinical] [--expression] [--methylation] [--variation] [--survival]
#
# No flags = submit everything (previous default behaviour). One or more
# flags = submit only the named categories.
#
# --survival needs subject.tsv (written by the clinical job) for its
# barcode->case_id crosswalk. If --clinical is submitted in the same
# invocation, --survival is made to depend on it (afterok); otherwise it is
# submitted immediately, relying on a subject.tsv already on disk from a
# previous clinical run.
set -euo pipefail

SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
source "${SCRIPT_DIR}/../.env"

CLINICAL=0
EXPRESSION=0
METHYLATION=0
VARIATION=0
SURVIVAL=0

if [[ $# -eq 0 ]]; then
    CLINICAL=1
    EXPRESSION=1
    METHYLATION=1
    VARIATION=1
    SURVIVAL=1
else
    for arg in "$@"; do
        case "${arg}" in
            --clinical)    CLINICAL=1 ;;
            --expression)  EXPRESSION=1 ;;
            --methylation) METHYLATION=1 ;;
            --variation)   VARIATION=1 ;;
            --survival)    SURVIVAL=1 ;;
            *)
                echo "usage: $(basename "${BASH_SOURCE[0]}") [--clinical] [--expression] [--methylation] [--variation] [--survival]" >&2
                exit 2 ;;
        esac
    done
fi

TS="$(date -d "today" +"%d%m%Y%H%M")"
mkdir -p "${LOG_DIR}/extraction"

CLINICAL_JOBID=""
if [[ "${CLINICAL}" -eq 1 ]]; then
    CLINICAL_JOBID=$(sbatch --parsable --chdir="${PROJECT_DIR}" --output="${LOG_DIR}/extraction/clinical_extraction_%j_${TS}.log" "${SCRIPT_DIR}/extract_TCGA/extract_TCGA_clinical.sh")
fi

if [[ "${EXPRESSION}" -eq 1 ]]; then
    sbatch --chdir="${PROJECT_DIR}" --output="${LOG_DIR}/extraction/expression_extraction_%j_${TS}.log" "${SCRIPT_DIR}/extract_TCGA/extract_TCGA_expression.sh"
fi

if [[ "${METHYLATION}" -eq 1 ]]; then
    sbatch --chdir="${PROJECT_DIR}" --output="${LOG_DIR}/extraction/methylation_extraction_%j_${TS}.log" "${SCRIPT_DIR}/extract_TCGA/extract_TCGA_methylation.sh"
fi

if [[ "${VARIATION}" -eq 1 ]]; then
    sbatch --chdir="${PROJECT_DIR}" --output="${LOG_DIR}/extraction/variation_extraction_%j_${TS}.log" "${SCRIPT_DIR}/extract_TCGA/extract_TCGA_variation.sh"
fi

if [[ "${SURVIVAL}" -eq 1 ]]; then
    if [[ -n "${CLINICAL_JOBID}" ]]; then
        sbatch --dependency="afterok:${CLINICAL_JOBID}" --chdir="${PROJECT_DIR}" --output="${LOG_DIR}/extraction/survival_extraction_%j_${TS}.log" "${SCRIPT_DIR}/extract_TCGA/extract_TCGA_survival.sh"
    else
        sbatch --chdir="${PROJECT_DIR}" --output="${LOG_DIR}/extraction/survival_extraction_%j_${TS}.log" "${SCRIPT_DIR}/extract_TCGA/extract_TCGA_survival.sh"
    fi
fi
