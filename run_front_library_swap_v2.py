#!/usr/bin/env python3
"""Compare two HPX component libraries using one identical benchmark executable.

Both modes run build/perftest-enforce/bin/partitioned_vector_front_report_test.
LD_PRELOAD selects only the partitioned_vector component from the relevant
build, while libhpx and libhpx_core remain from the enforce build. Alternates
launch order and preserves all raw measurements for reproducibility.
"""
import argparse
import csv
import hashlib
import datetime as dt
import json
import math
import os
from pathlib import Path
import random
import re
import statistics as stats
import subprocess
import sys
import time

MODES = ("ignore", "enforce")

def command_output(argv, cwd=None, env=None):
    proc = subprocess.run(argv, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False)
    return proc.returncode, proc.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--runs", type=int, default=50,
                        help="independent launches per mode (default 50)")
    parser.add_argument("--iterations", type=int, default=1_000_000)
    parser.add_argument("--test-count", type=int, default=20)
    parser.add_argument("--partition-size", type=int, default=16)
    parser.add_argument("--warmup-iterations", type=int, default=10_000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    modes = MODES
    if os.environ.get("LD_PRELOAD"):
        parser.error("Unset LD_PRELOAD before running; this runner sets it per mode")
    if min(args.runs, args.iterations, args.test_count, args.partition_size) <= 0:
        parser.error("runs, iterations, test-count, partition-size must be positive")
    if args.warmup_iterations < 0:
        parser.error("warmup-iterations must be nonnegative")

    repo = args.repo.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    exe = repo / "build/perftest-enforce/bin/partitioned_vector_front_report_test"
    if not exe.is_file():
        raise SystemExit(f"Missing executable: {exe}")
    libs = {
        mode: repo / "build" / f"perftest-{mode}" / "lib" /
              "libhpx_partitioned_vector.so.2.0.0"
        for mode in modes
    }
    for mode, lib in libs.items():
        if not lib.is_file():
            raise SystemExit(f"Missing {mode} component library: {lib}")

    # Verify the loader truly swaps only the intended component.
    for mode in modes:
        env = os.environ.copy()
        env["LD_PRELOAD"] = str(libs[mode])
        rc, linked = command_output(["ldd", "-r", str(exe)], cwd=repo, env=env)
        (output / f"ldd-{mode}.txt").write_text(linked)
        core = str(repo / "build/perftest-enforce/lib")
        if (rc or "undefined symbol:" in linked or str(libs[mode]) not in linked or
                linked.count("libhpx_partitioned_vector") != 1 or
                f"libhpx.so.2 => {core}/libhpx.so.2" not in linked or
                f"libhpx_core.so => {core}/libhpx_core.so" not in linked):
            raise SystemExit(f"Unexpected {mode} library resolution; inspect "
                             f"{output / f'ldd-{mode}.txt'}")

    def sha256(path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    _, commit = command_output(["git", "rev-parse", "HEAD"], cwd=repo)
    _, status = command_output(["git", "status", "--short"], cwd=repo)
    (output / "metadata.json").write_text(json.dumps({
        "utc_start": dt.datetime.now(dt.timezone.utc).isoformat(),
        "hostname": os.uname().nodename, "slurm_job_id": os.getenv("SLURM_JOB_ID"),
        "commit": commit.strip(), "source_status": status.strip(),
        "comparison": "same_enforce_executable_component_library_swap",
        "component_library_by_mode": {mode: str(libs[mode]) for mode in modes},
        "component_library_sha256": {mode: sha256(libs[mode]) for mode in modes},
        "executable_sha256": sha256(exe),
        "arguments": {"runs_per_mode": args.runs, "iterations": args.iterations,
                      "test_count": args.test_count, "partition_size": args.partition_size,
                      "warmup_iterations": args.warmup_iterations},
        "executable": str(exe),
    }, indent=2) + "\n")

    launch_rows = []
    sample_rows = []
    checksums = set()
    for pair in range(1, args.runs + 1):
        # AB, BA, AB, BA ...; each adjacent pair contains one of each mode.
        order = modes if pair % 2 else tuple(reversed(modes))
        for mode in order:
            command = [str(exe), "--hpx:threads=1",
                       f"--partition_size={args.partition_size}",
                       f"--iterations={args.iterations}",
                       f"--warmup_iterations={args.warmup_iterations}",
                       f"--test_count={args.test_count}", "--detailed_bench"]
            tag = f"{pair:03d}-{mode}"
            started = time.perf_counter()
            env = os.environ.copy()
            env["LD_PRELOAD"] = str(libs[mode])
            proc = subprocess.run(command, cwd=repo, env=env, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  check=False)
            wall_s = time.perf_counter() - started
            (output / f"{tag}.json").write_text(proc.stdout)
            (output / f"{tag}.stderr.txt").write_text(proc.stderr)
            if proc.returncode != 0:
                raise SystemExit(f"Failed {tag}, exit {proc.returncode}. "
                                 f"See {output / f'{tag}.stderr.txt'}")
            try:
                result = json.loads(proc.stdout)["outputs"]
                assert len(result) == 1
                assert result[0]["name"] == "partitioned_vector_front"
                assert result[0]["executor"] == "server_direct"
                samples = list(map(float, result[0]["series"]))
                assert len(samples) == args.test_count
                assert all(math.isfinite(x) and x > 0 for x in samples)
            except (ValueError, KeyError, TypeError, AssertionError) as exc:
                raise SystemExit(f"Unexpected report in {output / f'{tag}.json'}: {exc}") from exc
            match = re.search(r"\bchecksum=(\d+)\b", proc.stderr)
            if not match:
                raise SystemExit(f"Checksum missing in {output / f'{tag}.stderr.txt'}")
            checksum = int(match.group(1))
            checksums.add(checksum)
            launch_rows.append({
                "pair": pair, "mode": mode, "sample_median_s": stats.median(samples),
                "sample_mean_s": stats.mean(samples),
                "ns_per_call": stats.median(samples) * 1e9 / args.iterations,
                "process_wall_s": wall_s, "checksum": checksum, "json_file": f"{tag}.json"
            })
            sample_rows.extend({
                "pair": pair, "mode": mode, "sample": i,
                "sample_s": x, "ns_per_call": x * 1e9 / args.iterations
            } for i, x in enumerate(samples, 1))
            print(f"pair {pair:02d}/{args.runs} {mode:7s}  "
                  f"median={stats.median(samples)*1e9/args.iterations:.3f} ns/call",
                  flush=True)
    if len(checksums) != 1:
        raise SystemExit(f"Checksums varied between configurations: {checksums}")

    for filename, rows in (("launches.csv", launch_rows), ("samples.csv", sample_rows)):
        with (output / filename).open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    by_mode = {mode: [r["ns_per_call"] for r in launch_rows if r["mode"] == mode]
               for mode in modes}
    by_pair = {(r["pair"], r["mode"]): r["ns_per_call"] for r in launch_rows}
    first, second = modes
    log_ratios = [math.log(by_pair[(i, second)] / by_pair[(i, first)])
                  for i in range(1, args.runs + 1)]
    paired_geo_pct = (math.exp(stats.mean(log_ratios)) - 1) * 100
    rng = random.Random(20261112)
    bootstrap = sorted((math.exp(stats.mean(rng.choices(log_ratios, k=len(log_ratios)))) - 1) * 100
                       for _ in range(10_000))
    ci = (bootstrap[249], bootstrap[9749])
    median_overhead_pct = (stats.median(by_mode[second]) /
                           stats.median(by_mode[first]) - 1) * 100
    first_label, second_label = ("Ignore component", "Enforce component")
    lines = [
        "Experiment: component-library swap (single enforce-built executable)",
        f"Host: {os.uname().nodename}",
        f"Executable: {exe}",
        "Other HPX libraries: enforce build in both modes",
        f"Commit: {commit.strip()}",
        f"Launches: {args.runs} per mode, {args.test_count} samples per launch, "
        f"{args.iterations:,} front() calls per sample",
        f"Checksum (identical): {next(iter(checksums))}",
        f"{first_label} median of launch medians:  {stats.median(by_mode[first]):.4f} ns/call",
        f"{second_label} median of launch medians: {stats.median(by_mode[second]):.4f} ns/call",
        f"Ratio of those medians: {median_overhead_pct:+.2f}%",
        f"Geometric mean of paired ratios: {paired_geo_pct:+.2f}%",
        f"Pair-bootstrap 95% interval: {ci[0]:+.2f}% to {ci[1]:+.2f}%",
        "Note: Results from one node/job do not capture between-job variability."
    ]
    summary = "\n".join(lines) + "\n"
    (output / "summary.txt").write_text(summary)
    print("\n" + summary + f"Raw outputs and CSVs: {output}")

if __name__ == "__main__":
    main()
