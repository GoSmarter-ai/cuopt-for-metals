# cuOpt for Metals – Azure Infrastructure

This directory contains all Azure infrastructure defined as Bicep IaC.

## Resources

| Module | File | Description |
|--------|------|-------------|
| Main template | `main.bicep` | Orchestrates all modules |
| Service Bus | `modules/servicebus.bicep` | Namespace + queue for job messages |
| Function App | `modules/function.bicep` | HTTP-triggered ingest function |
| Container Apps Job | `modules/container-apps-job.bicep` | cuOpt solver job |

## Deploying

```bash
# Log in
az login

# Create resource group
az group create --name rg-cuopt-metals --location australiaeast

# Deploy
az deployment group create \
  --resource-group rg-cuopt-metals \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam
```

## Parameters

Copy `main.bicepparam` and fill in your values before deploying.
