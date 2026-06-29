"""
simulate.py

Power simulation for a two-arm RCT.
Estimates empirical power across a range of sample sizes given:
  - A between-group mean difference (effect size)
  - A shared standard deviation
  - A dropout rate (MCAR - Missing Completely At Random)

Usage (AWS Batch):
    Submitted via aws batch submit-job with --n_values, --n_iter, --effect_size,
    --sd, --dropout_rate, and --bucket as container overrides.
    n_per_arm is automatically determined by AWS_BATCH_JOB_ARRAY_INDEX
    mapping into the --n_values list.

Usage (local testing):
    python simulate.py --n_values 50,75,100,150,200 --n_iter 10000 --effect_size 4 \
                       --sd 4.5 --dropout_rate 0.20 --bucket trial-sim-results
    Note: requires AWS credentials and an existing S3 bucket.
    For local simulation without AWS, use simulate_local.py instead.
"""

import argparse
import csv
import io
import os
import numpy as np
from scipy import stats
import boto3


# ── 1. ARGUMENT PARSING ───────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="RCT power simulation")

    parser.add_argument("--n_values",     type=str,   required=True,
                        help="Comma-separated list of n_per_arm values to simulate "
                             "e.g. 50,75,100,150,200")
    parser.add_argument("--n_iter",       type=int,   default=10000,
                        help="Number of simulation iterations (default: 10000)")
    parser.add_argument("--effect_size",  type=float, default=4.0,
                        help="Expected mean difference between arms in kg (default: 4.0)")
    parser.add_argument("--sd",           type=float, default=4.5,
                        help="Shared standard deviation in kg (default: 4.5)")
    parser.add_argument("--dropout_rate", type=float, default=0.20,
                        help="Proportion of participants dropping out (default: 0.20)")
    parser.add_argument("--bucket",       type=str,   default="trial-sim-results",
                        help="S3 bucket name (default: trial-sim-results)")

    return parser.parse_args()


# ── 2. RESOLVE n_per_arm FROM ARRAY INDEX AND n_values LIST ──────────────────
def resolve_n(n_values_str):
    """
    Parse the comma-separated n_values string into a list,
    then use AWS_BATCH_JOB_ARRAY_INDEX to pick which value this job runs.

    Example:
        n_values_str = "50,75,100,150,200"
        array_index  = 2
        n_per_arm    = 100

    If running locally with no array index, defaults to index 0.
    """

    # Parse comma-separated string into list of integers
    n_list = [int(n.strip()) for n in n_values_str.split(",")]

    # Get array index from AWS Batch environment variable
    array_index = int(os.environ.get("AWS_BATCH_JOB_ARRAY_INDEX", 0))

    # Validate index is within bounds
    if array_index >= len(n_list):
        raise ValueError(
            f"Array index {array_index} is out of bounds for n_values list of length {len(n_list)}"
        )

    n_per_arm = n_list[array_index]
    seed      = array_index + 1  # unique seed per job

    print(f"  n_values list:     {n_list}")
    print(f"  Array index:       {array_index}")
    print(f"  Selected n_per_arm:{n_per_arm}")

    return n_per_arm, seed


# ── 3. SINGLE TRIAL SIMULATION ────────────────────────────────────────────────
def simulate_trial(n_per_arm, effect_size, sd, dropout_rate, rng):
    """
    Simulate one trial and return True if the null hypothesis is rejected.

    Parameters
    ----------
    n_per_arm    : int   - randomized participants per arm
    effect_size  : float - mean weight change difference (treatment - placebo), kg
    sd           : float - shared SD for both arms, kg
    dropout_rate : float - proportion of participants lost to follow-up (MCAR)
    rng          : numpy Generator - seeded random number generator

    Returns
    -------
    bool - True if p < 0.05 (null rejected), False otherwise
    """

    # Simulate observed weight change at Week 12
    treatment = rng.normal(loc=effect_size, scale=sd, size=n_per_arm)
    placebo   = rng.normal(loc=0.0,         scale=sd, size=n_per_arm)

    # Apply MCAR dropout
    n_dropout = int(np.floor(n_per_arm * dropout_rate))

    dropout_trt = rng.choice(n_per_arm, size=n_dropout, replace=False)
    dropout_pbo = rng.choice(n_per_arm, size=n_dropout, replace=False)

    treatment[dropout_trt] = np.nan
    placebo[dropout_pbo]   = np.nan

    # Remove NaNs before t-test (complete case analysis)
    treatment_obs = treatment[~np.isnan(treatment)]
    placebo_obs   = placebo[~np.isnan(placebo)]

    # Safety check
    if len(treatment_obs) < 2 or len(placebo_obs) < 2:
        return False

    # Two-sample Welch's t-test
    _, p_value = stats.ttest_ind(treatment_obs, placebo_obs, equal_var=False)

    return p_value < 0.05


# ── 4. POWER ESTIMATION ACROSS ITERATIONS ────────────────────────────────────
def estimate_power(n_per_arm, n_iter, effect_size, sd, dropout_rate, seed):
    """
    Run n_iter simulated trials and compute empirical power.
    """

    rng = np.random.default_rng(seed)

    rejections = sum(
        simulate_trial(n_per_arm, effect_size, sd, dropout_rate, rng)
        for _ in range(n_iter)
    )

    return rejections / n_iter


# ── 5. WRITE RESULTS TO S3 ───────────────────────────────────────────────────
def write_results_s3(bucket, n_per_arm, power, n_iter, effect_size, sd, dropout_rate, seed):
    """
    Write a single result row as a CSV directly to S3.
    Results are organized by date and Job ID  for traceability:
    s3://bucket/results/YYYYMMDD/Job ID/n_<value>.csv
    Each n_per_arm gets its own file to avoid write collisions
    when jobs run in parallel on AWS Batch.
    """

    from datetime import datetime

    # Build CSV content in memory
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=[
        "n_per_arm", "power", "n_iter", "effect_size", "sd", "dropout_rate", "seed"
    ])
    writer.writeheader()
    writer.writerow({
        "n_per_arm":    n_per_arm,
        "power":        round(power, 4),
        "n_iter":       n_iter,
        "effect_size":  effect_size,
        "sd":           sd,
        "dropout_rate": dropout_rate,
        "seed":         seed
    })

    date_prefix = datetime.now().strftime("%Y%m%d")
    job_id      = os.environ.get("AWS_BATCH_JOB_ID", "local").split(":")[0]

    s3 = boto3.client("s3")
    s3.put_object(
        Bucket = bucket,
        Key    = f"results/{date_prefix}/{job_id}/n_{n_per_arm}.csv",
        Body   = buffer.getvalue()
    )

    print(f"  -> Written to s3://{bucket}/results/{date_prefix}/{job_id}/n_{n_per_arm}.csv")


# ── 6. MAIN ──────────────────────────────────────────────────────────────────
def main():
    args = parse_args()

    # Resolve n_per_arm and seed from array index and n_values list
    n_per_arm, seed = resolve_n(args.n_values)

    print(f"\nRunning power simulation:")
    print(f"  n_per_arm    = {n_per_arm}")
    print(f"  n_iter       = {args.n_iter}")
    print(f"  effect_size  = {args.effect_size} kg")
    print(f"  sd           = {args.sd} kg")
    print(f"  dropout_rate = {args.dropout_rate * 100:.0f}%")
    print(f"  seed         = {seed}")
    print(f"  bucket       = {args.bucket}")

    power = estimate_power(
        n_per_arm    = n_per_arm,
        n_iter       = args.n_iter,
        effect_size  = args.effect_size,
        sd           = args.sd,
        dropout_rate = args.dropout_rate,
        seed         = seed
    )

    print(f"\n  Empirical power: {power:.4f} ({power*100:.1f}%)")

    write_results_s3(
        bucket       = args.bucket,
        n_per_arm    = n_per_arm,
        power        = power,
        n_iter       = args.n_iter,
        effect_size  = args.effect_size,
        sd           = args.sd,
        dropout_rate = args.dropout_rate,
        seed         = seed
    )


if __name__ == "__main__":
    main()