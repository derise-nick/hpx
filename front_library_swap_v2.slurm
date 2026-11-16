#!/bin/bash
#SBATCH --job-name=hpx-front-swap-v2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --exclusive
#SBATCH --time=00:30:00
#SBATCH --output=front-swap-v2-%j.out
#SBATCH --error=front-swap-v2-%j.err
# Copy any required partition/account/QoS directives from your existing job.
set -euo pipefail
cd /home/nderis2/sw/hpx
export PATH="$HOME/micromamba/envs/gcc-env/bin:$PATH"
RUNS="${RUNS:-50}"
OUTPUT="$PWD/results/front-swap-v2-${SLURM_JOB_ID:-manual}"

python3 ./run_front_library_swap_v2.py \
  --repo "$PWD" \
  --runs "$RUNS" \
  --iterations 1000000 \
  --test-count 20 \
  --partition-size 16 \
  --warmup-iterations 10000 \
  --output "$OUTPUT"
