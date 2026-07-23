#!/bin/bash
#SBATCH --job-name=tcga_methylation
#SBATCH --account=ranaaaa-ai-hackathon
#SBATCH --qos=bbpriority3
#SBATCH --time=24:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --output=/rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/slurm_log/methylation_%j.out
#SBATCH --error=/rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/slurm_log/methylation_%j.err

set -e

# Load necessary modules (adjust these according to Bear HPC environment)
module purge
module load bluebear
module load bear-apps/2024a
module load SciPy-bundle/2024.05-gfbf-2024a

# Set paths
SCRIPT_DIR="/rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/standardisation_script"
DATA_DIR="/rds/homes/s/sxm2220/Shalini/THESIS/TCGA_methylation_data"
OUT_DIR="/rds/homes/s/sxm2220/Shalini/THESIS/data_standardisation/outputs"
CONFIG_FILE="/rds/homes/s/sxm2220/Shalini/THESIS/JSON/tcga_methylation_mapping.json"
SCHEMA_FILE="/rds/projects/r/ranaaaa-ai-hackathon/Lifesphere/Shalini/THESIS/schema/lifesphere_schema.json"

echo "=========================================================="
echo "Starting TCGA Methylation Standardisation Pipeline"
echo "Date: $(date)"
echo "Host: $(hostname)"
echo "Job ID: $SLURM_JOB_ID"
echo "=========================================================="

cd "${SCRIPT_DIR}"

python methylation.py \
    --data-dir "${DATA_DIR}" \
    --out-dir "${OUT_DIR}" \
    --config "${CONFIG_FILE}" \
    --schema "${SCHEMA_FILE}" \
    --chunk-size 5000

echo "=========================================================="
echo "Pipeline execution completed at $(date)."
echo "=========================================================="
