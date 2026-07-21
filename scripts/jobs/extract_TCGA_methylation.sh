#!/bin/bash
#SBATCH --job-name=extract_tcga_methylation
#SBATCH --qos=bbdefault
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=08:00:00
set -e

# ---------------------------------------------------------------------------
# PATHS  (all vars must be set in .env — no defaults)
# ---------------------------------------------------------------------------

source .env

TS="$(date -d "today" +"%d%m%Y%H%M")"
exec > "${LOG_DIR}/methylation_extraction_${TS}.log" 2>&1

# ---------------------------------------------------------------------------
# MODULES
# ---------------------------------------------------------------------------
echo "=== LOADING BEAR MODULES $(date -Is) ==="

module purge
module load bluebear
module load bear-apps/2024a
module load Python/3.12.3-GCCcore-13.3.0
module load gdc-client/1.6.0-GCCcore-13.3.0

# ---------------------------------------------------------------------------
# VIRTUAL ENVIRONMENT
# ---------------------------------------------------------------------------
echo "=== SETTING UP VIRTUAL ENVIRONMENT $(date -Is) ==="
mkdir -p ${VENV_DIR}
if [[ ! -d ${VENV_DIR} ]] || [[ ! -f ${VENV_DIR}/bin/activate ]]; then
    rm -rf ${VENV_DIR}
    python3 -m venv --system-site-packages ${VENV_DIR}
    if [[ $? -ne 0 ]]; then
        echo "ERROR: venv creation failed" >&2
        exit 1
    fi
fi
source ${VENV_DIR}/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# ---------------------------------------------------------------------------
# RUN EXTRACTION
# ---------------------------------------------------------------------------
echo "=== RUNNING EXTRACTION $(date -Is) ==="

python -m src.extract --program TCGA --methylation --out "${RAW_DIR}/TCGA_METHYLATION"

echo "=== COMPLETED SUCCESSFULLY? $(date -Is) ==="

mv "slurm-${SLURM_JOB_ID}.out.stats" "${LOG_DIR}/methylation_extraction_${TS}.stats"
