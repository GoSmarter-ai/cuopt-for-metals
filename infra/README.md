# cuOpt for Metals – Azure Infrastructure

This directory contains all Azure infrastructure defined as Bicep IaC.

> **Full reference**: see [`docs/infrastructure.md`](../docs/infrastructure.md)  
> **Deployment walkthrough**: see [`docs/getting-started.md`](../docs/getting-started.md)

## Resources deployed

| Module | File | Description |
|--------|------|-------------|
| Main template | `main.bicep` | Orchestrates all modules and owns all RBAC role assignments |
| Service Bus | `modules/servicebus.bicep` | Standard namespace + `cutting-jobs` queue |
| Function App | `modules/function.bicep` | HTTP-triggered ingest function (Python 3.11, Consumption plan) |
| Container Apps Job | `modules/container-apps-job.bicep` | KEDA-triggered cuOpt solver job |

## Security model – managed identity throughout

**No connection strings, SAS tokens, or account keys** are stored in application
settings or environment variables. Every component authenticates via its
**system-assigned managed identity** with least-privilege RBAC roles:

| Principal | Role | Resource |
|-----------|------|----------|
| Function App | Azure Service Bus Data **Sender** | Service Bus Namespace |
| Function App | Storage Blob Data Owner + Queue/Table Contributor | Storage Account |
| Container Apps Job | Azure Service Bus Data **Receiver** | Service Bus Namespace |

Role assignments are declared in `main.bicep` so they are easy to audit in
one place.

## Quick deploy

```bash
# Log in
az login
az account set --subscription "<your-subscription-id>"

# Create resource group
az group create --name rg-cuopt-metals --location australiaeast

# Edit parameters (solver image, region, env name)
# vi infra/main.bicepparam

# Deploy
az deployment group create \
  --resource-group rg-cuopt-metals \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam
```

## Parameters

Edit `main.bicepparam` before deploying:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `environmentName` | `dev` | `dev`, `staging`, or `prod` |
| `location` | resource group location | Azure region |
| `projectName` | `cuoptmetals` | Resource name prefix (≤12 chars) |
| `solverImage` | `cuoptmetals.azurecr.io/cuopt-solver:latest` | Solver container image |
| `stockLengthMm` | `6000` | Default stock length in mm |
