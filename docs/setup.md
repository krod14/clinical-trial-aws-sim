# AWS Setup Guide

This document describes how to deploy and run the clinical trial simulation
pipeline on AWS using Batch for compute, ECR for container storage, and S3
for results. This is the recommended approach for large-scale simulation
sweeps, as AWS Batch eliminates local compute constraints by distributing
jobs across many nodes on demand.

---

## Architecture

- **ECR** — container registry for the simulation Docker image
- **AWS Batch** — job orchestration and compute scaling
- **S3** — persistent storage for simulation results
- **SageMaker** — JupyterLab notebook for result visualization
- **IAM** — access management across all services

---

## Prerequisites

- An AWS account
- AWS CLI installed locally
- Docker installed locally
- conda or mamba
- Basic familiarity with the AWS console

---

## Step 1: Clone the Repository

```bash
git clone https://github.com/krod14/clinical-trial-aws-sim.git
cd clinical-trial-aws-sim
```

This gives you the `Dockerfile`, `simulate.py`, `environment.yml`, and
`notebooks/power_curve.ipynb` needed for the steps below.

**Set up the AWS conda environment:**
```bash
conda env create -f environment.yml
conda activate clin-trial-sim-aws
```

---

## Step 2: Create an IAM User

1. Go to **IAM → Users → Create user**
2. Name the user (e.g. `trial-sim-user`)
3. Click **Attach policies directly**
4. Search for and attach the following policies:
   - `AmazonEC2ContainerRegistryFullAccess`
   - `AmazonS3FullAccess`
   - `AWSBatchFullAccess`
5. Click **Create user**

Then create an access key:
1. Click on your new user → **Security credentials**
2. Click **Create access key**
3. Select **Command Line Interface (CLI)**
4. Download or copy both the **Access Key ID** and **Secret Access Key**

Configure your local CLI:
```bash
aws configure
```

Enter your IAM credentials when prompted:
- AWS Access Key ID
- AWS Secret Access Key
- Default region (e.g. `us-east-2`)
- Default output format (press Enter for default)

---

## Step 3: Create an S3 Bucket

1. Go to **S3 → Create bucket**
2. Name your bucket (e.g. `trial-sim-results`) — must be globally unique
3. Select your region — must match what you set in `aws configure` (e.g. `us-east-2`)
4. Keep all other defaults
5. Click **Create bucket**

---

## Step 4: Build and Push Docker Image to ECR

**Create an ECR repository:**
1. Go to **ECR → Private Registry → Repositories → Create repository**
2. Repository name: `trial-sim`
3. Leave all other settings as default
4. Click **Create** and save the **Repository URI** for use below

**Build the Docker image locally:**
```bash
docker build -t trial-sim .
```

**Authenticate and push:**

Click **"View push commands"** in your ECR repository for your exact commands,
or follow this pattern:

```bash
# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-2 | \
  docker login --username AWS --password-stdin <YOUR_ACCOUNT_ID>.dkr.ecr.us-east-2.amazonaws.com

# Tag the image
docker tag trial-sim:latest <YOUR_REPOSITORY_URI>:latest

# Push to ECR
docker push <YOUR_REPOSITORY_URI>:latest
```

---

## Step 5: Configure AWS Batch

**Create a compute environment:**
1. Go to **Batch → Compute environments → Create**
2. Configure:
   - Compute environment configuration: **Amazon EC2**
   - Orchestration type: **Managed**
   - Compute environment name: `trial-sim-compute`
   - Service role: `AWSServiceRoleForBatch`
   - Instance role: `AmazonEC2ContainerServiceForEC2Role`
     - If it doesn't exist, create an IAM role and attach `AmazonS3FullAccess`
3. Leave everything else as default → **Create**
4. Wait until Status = **VALID**

**Create a job queue:**
1. Go to **Batch → Job queues → Create**
2. Configure:
   - Orchestration type: **EC2**
   - Job queue name: `trial-sim-queue`
   - Priority: `1`
   - Connected compute environment: `trial-sim-compute`
3. Click **Create**

**Create a job definition:**
1. Go to **Batch → Job definitions → Create**
2. Configure:
   - Orchestration type: **EC2**
   - Job definition name: `trial-sim-job`
   - Image: your ECR repository URI
   - vCPUs: `1`
   - Memory: `512`
3. Leave everything else as default → **Create**

---

## Step 6: Submit an Array Job

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

## Step 7: Visualize Results in SageMaker

1. Go to **SageMaker → Notebooks → Notebook instances → Create notebook instance**
2. Configure:
   - Notebook instance name: `trial-sim-notebook`
   - IAM role: create a new role → Specific S3 buckets → `trial-sim-results`
3. Leave everything else as default → **Create**
4. Once running, open **JupyterLab**
5. Upload `notebooks/power_curve.ipynb` from the cloned repo
6. Select the `conda_python3` kernel and run cells in order
   - Cell 3: set `selected_index` to the run you want to load (printed by Cell 2)

> ⚠️ When finished: select notebook instance → **Action → Stop** to avoid
> ongoing charges (~$0.05/hr while running).

---

## Troubleshooting

**`aws: command not found`:**
- Ensure the AWS CLI is installed and your terminal has been restarted after install
- Verify with `aws --version`

**Docker push rejected:**
- Re-run the ECR authentication command — tokens expire after 12 hours
- Ensure the region in the login command matches your ECR repository region

**Batch job stuck in RUNNABLE:**
- Check that your compute environment status is **VALID**
- Verify the instance role has `AmazonS3FullAccess` attached
- Check that the ECR image URI in the job definition is correct

**S3 upload fails from Batch job:**
- Confirm the instance role (not the IAM user) has `AmazonS3FullAccess`
- Verify the bucket name passed to `--bucket` matches your S3 bucket exactly
- Ensure the bucket region matches your `aws configure` region

---

## Estimated Costs

| Resource | Estimate |
|----------|----------|
| AWS Batch compute (30-scenario sweep, 10k iter) | < $1–2 total |
| S3 storage (CSV outputs at this scale) | < $0.01/month |
| SageMaker ml.t3.medium notebook | ~$0.05/hr |

> ⚠️ **Stop your SageMaker notebook instance when not in use** to avoid unnecessary charges.

*Costs based on us-east-2 on-demand pricing as of 2026.*