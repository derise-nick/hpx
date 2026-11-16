#!/usr/bin/env python3
"""Compare HPX partitioned_vector::get_value(0) in ignore/enforce or A/A mode.

Uses only the Python standard library. Each pair has two independent process
launches, with the order alternating to limit drift. With --aa (or AA=1), both
positions run exactly the same ignore executable as a negative control.
"""
import argparse
import csv
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

def command_output(argv, cwd=None):
    proc = subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE,
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
    parser.add_argument("--aa", action="store_true",
                        help="A/A control: run the ignore executable in both positions; "
                             "also enabled with environment variable AA=1")
    args = parser.parse_args()
    aa = args.aa or os.getenv("AA", "").strip().lower() in ("1", "true", "yes", "on")
    modes = ("ignore_a", "ignore_b") if aa else MODES
    build_mode = {mode: "ignore" if aa else mode for mode in modes}
    if min(args.runs, args.iterations, args.test_count, args.partition_size) <= 0:
        parser.error("runs, iterations, test-count, partition-size must be positive")
    if args.warmup_iterations < 0:
        parser.error("warmup-iterations must be nonnegative")

    repo = args.repo.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    exes = {
        mode: repo / "build" / f"perftest-{build_mode[mode]}" / "bin" /
              "partitioned_vector_get_value_report_test"
        for mode in modes
    }
    for mode, exe in exes.items():
        if not exe.is_file():
            raise SystemExit(f"Missing {mode} executable: {exe}")
        rc, linked = command_output(["ldd", str(exe)])
        (output / f"ldd-{mode}.txt").write_text(linked)
        expected = str(repo / "build" / f"perftest-{build_mode[mode]}" / "lib" /
                       "libhpx_partitioned_vector.so")
        if rc or expected not in linked:
            raise SystemExit(f"Unexpected {mode} component library; inspect "
                             f"{output / f'ldd-{mode}.txt'}")

    _, commit = command_output(["git", "rev-parse", "HEAD"], cwd=repo)
    _, status = command_output(["git", "status", "--short"], cwd=repo)
    (output / "metadata.json").write_text(json.dumps({
        "utc_start": dt.datetime.now(dt.timezone.utc).isoformat(),
        "hostname": os.uname().nodename, "slurm_job_id": os.getenv("SLURM_JOB_ID"),
        "commit": commit.strip(), "source_status": status.strip(),
        "comparison": "AA_ignore_vs_ignore" if aa else "AB_ignore_vs_enforce",
        "mode_to_build": build_mode,
        "arguments": {"runs_per_mode": args.runs, "iterations": args.iterations,
                      "test_count": args.test_count, "partition_size": args.partition_size,
                      "warmup_iterations": args.warmup_iterations},
        "executables": {mode: str(exe) for mode, exe in exes.items()},
    }, indent=2) + "\n")

    launch_rows = []
    sample_rows = []
    checksums = set()
    for pair in range(1, args.runs + 1):
        # AB, BA, AB, BA ...; each adjacent pair contains one of each mode.
        order = modes if pair % 2 else tuple(reversed(modes))
        for mode in order:
            command = [str(exes[mode]), "--hpx:threads=1",
                       f"--partition_size={args.partition_size}",
                       f"--iterations={args.iterations}",
                       f"--warmup_iterations={args.warmup_iterations}",
                       f"--test_count={args.test_count}", "--detailed_bench"]
            tag = f"{pair:03d}-{mode}"
            started = time.perf_counter()
            proc = subprocess.run(command, cwd=repo, text=True,
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
                assert result[0]["name"] == "partitioned_vector_get_value"
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
    first_label, second_label = ("Ignore A", "Ignore B") if aa else ("Ignore", "Enforce")
    lines = [
        f"Experiment: {'A/A control (ignore vs same ignore executable)' if aa else 'A/B (ignore vs enforce)'}",
        f"Host: {os.uname().nodename}",
        f"Commit: {commit.strip()}",
        f"Launches: {args.runs} per mode, {args.test_count} samples per launch, "
        f"{args.iterations:,} get_value(0) calls per sample",
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
