#!/bin/bash
#SBATCH --job-name=extract_tcga_methylation
#SBATCH --qos=bbdefault
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=24:00:00
set -e

# ---------------------------------------------------------------------------
# PATHS  (all vars must be set in .env — no defaults)
# ---------------------------------------------------------------------------

source .env
TS="$(date -d "today" +"%d%m%Y%H%M")"

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
if [[ ! -f ${VENV_DIR}/bin/activate ]]; then
    python3 -m venv --system-site-packages ${VENV_DIR}
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

mv "slurm-${SLURM_JOB_ID}.out.stats" "${LOG_DIR}/extraction/methylation_extraction_${SLURM_JOB_ID}_${TS}.stats"
