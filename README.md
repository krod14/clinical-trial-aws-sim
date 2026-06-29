# Clinical Trial Simulation in AWS

A scalable, cloud-based pipeline for running clinical trial power simulations
using Amazon Web Services (AWS). Demonstrates how EC2, S3, Batch, ECR, and
SageMaker can replace local computing for large-scale statistical simulation,
eliminating compute as a bottleneck when the number of scenarios or replicates
grows beyond what a local machine can efficiently handle.

Designed around a parallel simulation structure where each replicate is
independent, making AWS Batch array jobs a natural fit for distributing
workloads across many compute nodes on demand.

---

## Pipeline Overview

```
simulate.py → Docker Image (ECR) → AWS Batch (Array Jobs) → S3 (Results) → SageMaker (Visualization)
```

| Step | Tool | Purpose |
|------|------|---------|
| Simulation | Python (numpy, scipy) | Generate trial replicates and estimate empirical power |
| Containerization | Docker + ECR | Package simulation environment for reproducible execution |
| Job Orchestration | AWS Batch | Submit and manage array jobs across sample size scenarios |
| Storage | Amazon S3 | Store result CSVs, accessible by all collaborators |
| Visualization | SageMaker + `power_curve.ipynb` | Load results from S3 and plot empirical power curves |

---

## Repository Structure

```
clinical-trial-aws-sim/
├── simulate_local.py       # Local simulation script (CSV output)
├── simulate.py             # S3-enabled simulation script (for AWS Batch)
├── Dockerfile              # Container definition for AWS Batch jobs
├── environment_local.yml   # Local conda environment (numpy, scipy)
├── environment.yml         # AWS conda environment (numpy, scipy, boto3)
├── notebooks/
│   └── power_curve.ipynb   # SageMaker notebook for power curve visualization
├── docs/
│   └── setup.md            # Step-by-step AWS setup guide
└── README.md
```

---

## Quickstart

### Local Execution

#### Step 1: Clone the repository

```bash
git clone https://github.com/krod14/clinical-trial-aws-sim.git
cd clinical-trial-aws-sim
```

#### Step 2: Set up local environment

```bash
conda env create -f environment_local.yml
conda activate clin-trial-sim
```

#### Step 3: Run a local simulation

`simulate_local.py` runs a single scenario at a time. Adjust the arguments
to match your own trial assumptions:

```bash
python simulate_local.py \
  --n_per_arm 65 \
  --n_iter 10000 \
  --effect_size 4 \
  --sd 4.5 \
  --dropout_rate 0.20 \
  --seed 42 \
  --output results.csv
```

For sweeping across sample sizes, use AWS Batch (see below) — each array
job automatically picks its own `n_per_arm` from the `--n_values` list
based on its array index.

---

### AWS Execution

For large-scale simulation sweeps, AWS Batch eliminates local compute
constraints by running all scenarios in parallel. Full setup instructions
are in the [AWS Setup Guide](docs/setup.md) which include IAM configuration,
S3 bucket creation, Docker image build and push to ECR, and Batch environment
setup. Once that is complete, set up the AWS environment and submit an array job:

```bash
conda env create -f environment.yml
conda activate clin-trial-sim-aws
```

> **Note:** The `--job-queue`, `--job-definition`, and `--bucket` values below
> must match the names you created in the setup guide. If you used different
> names, update them here accordingly before submitting.

```bash
aws batch submit-job \
  --job-name trial-sim-sweep \
  --job-queue trial-sim-queue \
  --job-definition trial-sim-job \
  --array-properties size=30 \
  --container-overrides '{
    "command": [
      "--n_values", "10,20,30,40,50,60,70,80,90,100,110,120,130,140,150,160,170,180,190,200,210,220,230,240,250,260,270,280,290,300",
      "--n_iter", "10000",
      "--effect_size", "4",
      "--sd", "4.5",
      "--dropout_rate", "0.20",
      "--bucket", "trial-sim-results"
    ]
  }'
```

Each array job reads `AWS_BATCH_JOB_ARRAY_INDEX` from its environment to
select its own `n_per_arm` from the `--n_values` list, runs 10,000
iterations, and writes its result to S3 as an individual file
(`results/YYYYMMDD/job-id/n_<value>.csv`).

Monitor job status: **AWS Console → Batch → Jobs → trial-sim-sweep**
(`SUBMITTED → PENDING → RUNNING → SUCCEEDED`)

---

## Simulation Design

This pipeline is demonstrated using a **toy Phase 2 RCT**. This toy RCT 
is a simulated mental-health clinical trial evaluating empirical power 
for detecting a treatment effect on body weight across a range of sample sizes.

**Trial Setting:** Phase 2, randomized, double-blind, placebo-controlled

**Research Question:**
> Among adults with schizophrenia or bipolar disorder who experience
> antipsychotic-associated weight gain, what sample size is needed to
> detect a treatment effect on body weight at Week 12 with sufficient
> power, accounting for dropout and realistic outcome variability?

**Data-Generating Mechanism:**

| Parameter | Value |
|-----------|-------|
| Treatment arm | N(mean = 4 kg, SD = 4.5 kg) |
| Placebo arm | N(mean = 0 kg, SD = 4.5 kg) |
| Dropout | 20% per arm, MCAR |
| Sample sizes | n = 10, 20, …, 300 per arm |
| Iterations per scenario | 10,000 |

**Analysis:** Complete-case two-sample Welch t-test (α = 0.05)

**Key Output:** Empirical power curve — minimum n per arm achieving ≥ 80% power

A realistic sensitivity analysis for a question like this spans combinations of:

| Parameter | Values |
|-----------|--------|
| Sample size per arm | 75–200 |
| True treatment effect | 0, 2, 3, 4 kg |
| Outcome SD | 4.0, 4.5, 5.5, 6.5 kg |
| Dropout rate | 10%, 20%, 30%, 40% |
| Missingness mechanism | MCAR, MAR, MNAR |
| Adherence pattern | Perfect, high, moderate, poor |
| Analysis method | Complete-case ANCOVA, MMRM, MI-based, sensitivity |

At 10,000 replicates per combination, this easily exceeds **millions of
simulated trials** which is well beyond the practical limits of local computing.

---

## Visualization

Once simulation results are stored in S3, `notebooks/power_curve.ipynb` can
be run in a SageMaker JupyterLab instance to visualize and interpret the
output. See [AWS Setup Guide](docs/setup.md) for instructions on launching
the notebook.

The notebook produces:

- **Power curve** — empirical power plotted against sample size, with an 80%
  power threshold line and a vertical marker at the minimum n achieving that threshold
- **Summary statistics** — minimum n per arm, empirical power at that n,
  enrollment after dropout inflation, and total enrollment across both arms

The plot is also saved locally as `power_curve.png` for export.

---

## Results

### Local vs. AWS Batch Runtime

| Scenario | Local | AWS Batch |
|----------|-------|-----------|
| Single run (n = 65, 10k iter) | ~14 sec | — |
| 3-scenario sweep | ~40 sec | — |
| 30-scenario sweep (n = 10–300) | ~7 min | **15 sec** (compute) |

AWS Batch provisioning added ~1 min 44 sec (EC2 spin-up + Docker pull),
for a total wall time of ~1 min 59 sec — a **~5× speedup** over local
sequential execution. Speedup increases as the simulation study scales.

---

## Advantages & Limitations

### Advantages

- **Parallelism** — hundreds of simulation conditions run concurrently
- **Reproducibility** — Docker containers on AWS Batch ensure consistent environments
- **Collaboration** — team-wide access to shared results on S3
- **Elastic scaling** — add or remove compute instantly, no hardware procurement
- **Speed** — removes compute as a bottleneck for large-scale studies

### Limitations

- **Setup overhead** — IAM roles, job definitions, ECR, and Batch configuration take time to configure correctly
- **Cold start latency** — EC2 provisioning and Docker image pulls add overhead; less advantageous for very short single jobs

---

## Cost Estimates

| Resource | Estimate |
|----------|----------|
| AWS Batch compute (30-scenario sweep, 10k iter) | < $1–2 total |
| S3 storage (CSV outputs at this scale) | < $0.01/month |
| SageMaker ml.t3.medium notebook | ~$0.05/hr |

> ⚠️ **Stop your SageMaker notebook instance when not in use** to avoid unnecessary charges.

---

## Requirements

- conda or mamba
- Docker (for containerized execution)
- AWS account with `AmazonEC2ContainerRegistryFullAccess`, `AmazonS3FullAccess`, `AWSBatchFullAccess`
- AWS CLI configured (`aws configure`)

Python dependencies are managed via conda environment files:
- `environment_local.yml` — local execution (`numpy`, `scipy`)
- `environment.yml` — AWS execution (`numpy`, `scipy`, `boto3`)

---

## References

- [AWS Batch Documentation](https://docs.aws.amazon.com/batch/)
- [Amazon S3 Documentation](https://docs.aws.amazon.com/s3/)
- [Amazon SageMaker Documentation](https://docs.aws.amazon.com/sagemaker/)

---

## Author

**Kyle Rodrigues**
M.S. Bioinformatics, Georgetown University
[LinkedIn](https://www.linkedin.com/in/rodrigueskyle) | kyle.r.rodrigues@gmail.com