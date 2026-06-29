"""
simulate_local.py

Power simulation for a two-arm RCT.
Estimates empirical power across a range of sample sizes given:
  - A between-group mean difference (effect size)
  - A shared standard deviation
  - A dropout rate (MCAR - Missing Completely At Random)

Usage:
    python simulate_local.py --n_per_arm 65 --n_iter 10000 --effect_size 4 \
                             --sd 4.5 --dropout_rate 0.20 --seed 42 --output results.csv
"""

import argparse
import csv
import os
import numpy as np
from scipy import stats


# ── 1. ARGUMENT PARSING ───────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="RCT power simulation (local)")

    parser.add_argument("--n_per_arm",    type=int,   required=True,
                        help="Number of participants randomized per arm")
    parser.add_argument("--n_iter",       type=int,   default=10000,
                        help="Number of simulation iterations (default: 10000)")
    parser.add_argument("--effect_size",  type=float, default=4.0,
                        help="Expected mean difference between arms in kg (default: 4.0)")
    parser.add_argument("--sd",           type=float, default=4.5,
                        help="Shared standard deviation in kg (default: 4.5)")
    parser.add_argument("--dropout_rate", type=float, default=0.20,
                        help="Proportion of participants dropping out (default: 0.20)")
    parser.add_argument("--seed",         type=int,   default=42,
                        help="Random seed for reproducibility (default: 42)")
    parser.add_argument("--output",       type=str,   default="results.csv",
                        help="Output CSV filename (default: results.csv)")

    return parser.parse_args()


# ── 2. SINGLE TRIAL SIMULATION ────────────────────────────────────────────────
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


# ── 3. POWER ESTIMATION ACROSS ITERATIONS ────────────────────────────────────
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


# ── 4. WRITE RESULTS TO LOCAL CSV ─────────────────────────────────────────────
def write_results(output_path, n_per_arm, power, n_iter, effect_size, sd, dropout_rate, seed):
    """
    Append a single result row to a local CSV file.
    Creates the file with a header if it does not already exist.
    """

    file_exists = os.path.isfile(output_path)

    with open(output_path, mode="a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "n_per_arm", "power", "n_iter", "effect_size", "sd", "dropout_rate", "seed"
        ])

        if not file_exists:
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

    print(f"  -> Written to {output_path}")


# ── 5. MAIN ──────────────────────────────────────────────────────────────────
def main():
    args = parse_args()

    print(f"\nRunning power simulation:")
    print(f"  n_per_arm    = {args.n_per_arm}")
    print(f"  n_iter       = {args.n_iter}")
    print(f"  effect_size  = {args.effect_size} kg")
    print(f"  sd           = {args.sd} kg")
    print(f"  dropout_rate = {args.dropout_rate * 100:.0f}%")
    print(f"  seed         = {args.seed}")

    power = estimate_power(
        n_per_arm    = args.n_per_arm,
        n_iter       = args.n_iter,
        effect_size  = args.effect_size,
        sd           = args.sd,
        dropout_rate = args.dropout_rate,
        seed         = args.seed
    )

    print(f"\n  Empirical power: {power:.4f} ({power*100:.1f}%)")

    write_results(
        output_path  = args.output,
        n_per_arm    = args.n_per_arm,
        power        = power,
        n_iter       = args.n_iter,
        effect_size  = args.effect_size,
        sd           = args.sd,
        dropout_rate = args.dropout_rate,
        seed         = args.seed
    )


if __name__ == "__main__":
    main()