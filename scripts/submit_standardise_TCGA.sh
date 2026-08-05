#!/bin/bash
# Submit one standardise job per dataset under RAW_DIR. Run from anywhere —
# paths come from .env. Profile is chosen from the dataset name: the clinical
# extract uses the `extract` profile, the omics extracts use `omics`.
#
# Idempotent by default: a dataset whose STD_DIR/<dataset>/nodes already holds
# CSVs is skipped (standardise output is not auto-cleaned, so re-runs would just
# overwrite). Pass --force / -f to re-standardise everything anyway.
#
# Usage:
#   scripts/submit_standardise_TCGA.sh [-f|--force] [--clinical] [--expression] [--methylation] [--variation]
#
# No category flags = standardise every dataset under RAW_DIR (previous default
# behaviour). One or more category flags = standardise only matching datasets.

SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
source "${SCRIPT_DIR}/../.env"

FORCE=0
CLINICAL=0
EXPRESSION=0
METHYLATION=0
VARIATION=0
ANY_CATEGORY=0

for arg in "$@"; do
    case "${arg}" in
        -f|--force)    FORCE=1 ;;
        --clinical)    CLINICAL=1;    ANY_CATEGORY=1 ;;
        --expression)  EXPRESSION=1;  ANY_CATEGORY=1 ;;
        --methylation) METHYLATION=1; ANY_CATEGORY=1 ;;
        --variation)   VARIATION=1;   ANY_CATEGORY=1 ;;
        *)
            echo "usage: $(basename "${BASH_SOURCE[0]}") [-f|--force] [--clinical] [--expression] [--methylation] [--variation]" >&2
            exit 2 ;;
    esac
done

# no category flags -> standardise everything
if [[ "${ANY_CATEGORY}" -eq 0 ]]; then
    CLINICAL=1
    EXPRESSION=1
    METHYLATION=1
    VARIATION=1
fi

TS="$(date -d "today" +"%d%m%Y%H%M")"
mkdir -p "${LOG_DIR}/standardisation"

for dataset_dir in "${RAW_DIR}"/*/; do
    [[ -d "${dataset_dir}" ]] || continue          # no-match glob guard
    dataset="$(basename "${dataset_dir}")"

    case "${dataset}" in
        *CLINICAL*)
            profile="extract"
            [[ "${CLINICAL}" -eq 1 ]] || { echo "- skip ${dataset}: --clinical not selected"; continue; } ;;
        *EXPRESSION*)
            profile="omics"
            [[ "${EXPRESSION}" -eq 1 ]] || { echo "- skip ${dataset}: --expression not selected"; continue; } ;;
        *METHYLATION*)
            profile="omics"
            [[ "${METHYLATION}" -eq 1 ]] || { echo "- skip ${dataset}: --methylation not selected"; continue; } ;;
        *VARIATION*)
            profile="omics"
            [[ "${VARIATION}" -eq 1 ]] || { echo "- skip ${dataset}: --variation not selected"; continue; } ;;
        *)
            echo "! skip ${dataset}: no profile rule (add a case in $(basename "${BASH_SOURCE[0]}"))"
            continue ;;
    esac

    # already-standardised guard: skip unless --force
    if [[ "${FORCE}" -eq 0 ]] && compgen -G "${STD_DIR}/${dataset}/nodes/*.csv" > /dev/null; then
        echo "= skip ${dataset}: already standardised (${STD_DIR}/${dataset}/nodes) — use --force to redo"
        continue
    fi

    echo "submitting ${dataset} (profile: ${profile})"
    sbatch \
        --job-name="std_${dataset}" \
        --chdir="${PROJECT_DIR}" \
        --output="${LOG_DIR}/standardisation/${dataset}_%j_${TS}.log" \
        "${SCRIPT_DIR}/standardise_TCGA/standardise_TCGA.sh" "${dataset}" "${profile}"
done
