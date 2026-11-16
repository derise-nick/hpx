#!/bin/bash
#SBATCH --job-name=hpx-front-contracts
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --exclusive
#SBATCH --time=00:30:00
#SBATCH --output=front-contracts-%j.out
#SBATCH --error=front-contracts-%j.err
# If required at LSU, copy the --partition/--account/--qos lines
# from .jenkins/lsu-perftests/entry.sh. To target the usual LSU node,
# add: #SBATCH --nodelist=medusa08
set -euo pipefail
cd /home/nderis2/sw/hpx
export PATH="$HOME/micromamba/envs/gcc-env/bin:$PATH"

# Set RUNS=5 for a pilot or RUNS=50 for the main initial comparison.
RUNS="${RUNS:-50}"
OUTPUT="$PWD/results/front-contracts-${SLURM_JOB_ID:-manual}"

python3 ./run_get_value_bench.py \
  --repo "$PWD" \
  --runs "$RUNS" \
  --iterations 1000000 \
  --test-count 20 \
  --partition-size 16 \
  --warmup-iterations 10000 \
  --output "$OUTPUT"
