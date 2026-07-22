#!/bin/bash
# Submit one standardise job per dataset under RAW_DIR. Run from anywhere —
# paths come from .env. Profile is chosen from the dataset name: the clinical
# extract uses the `extract` profile, the omics extracts use `omics`.

SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
source "${SCRIPT_DIR}/../.env"

TS="$(date -d "today" +"%d%m%Y%H%M")"
mkdir -p "${LOG_DIR}/standardisation"

for dataset_dir in "${RAW_DIR}"/*/; do
    [[ -d "${dataset_dir}" ]] || continue          # no-match glob guard
    dataset="$(basename "${dataset_dir}")"

    case "${dataset}" in
        *CLINICAL*)
            profile="extract" ;;
        *EXPRESSION*|*METHYLATION*|*VARIATION*)
            profile="omics" ;;
        *)
            echo "! skip ${dataset}: no profile rule (add a case in $(basename "${BASH_SOURCE[0]}"))"
            continue ;;
    esac

    echo "submitting ${dataset} (profile: ${profile})"
    sbatch \
        --job-name="std_${dataset}" \
        --chdir="${PROJECT_DIR}" \
        --output="${LOG_DIR}/standardisation/${dataset}_%j_${TS}.log" \
        "${SCRIPT_DIR}/standardise_TCGA/standardise_TCGA.sh" "${dataset}" "${profile}"
done
