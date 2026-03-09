# Getting Started

This guide walks you through setting up your development environment and
deploying the cuOpt for Metals solution to Azure, whether you are working
locally, in GitHub Codespaces, or a CI/CD pipeline.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | [python.org](https://www.python.org/downloads/) |
| Azure CLI | latest | [docs.microsoft.com](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) |
| Azure Functions Core Tools | v4 | [docs.microsoft.com](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local) |
| Docker | 24+ | [docker.com](https://www.docker.com/get-started/) |
| Bicep CLI | latest | bundled with Azure CLI (`az bicep install`) |

---

## 1. Local development (devcontainer)

The fastest way to get a fully configured environment is through the included
devcontainer, which works with **VS Code Dev Containers** and
**GitHub Codespaces**.

### Option A – GitHub Codespaces

1. Click **Code → Codespaces → Create codespace on main** in the GitHub UI.
2. Wait for the container to build (~2 min).
3. All tools (Azure CLI, Functions Core Tools, Python 3.11, Docker-in-Docker)
   are pre-installed and ready to use in the integrated terminal.

### Option B – VS Code Dev Containers (local)

1. Install the
   [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers).
2. Open the repository folder in VS Code.
3. When prompted, click **Reopen in Container** (or run
   `Dev Containers: Reopen in Container` from the command palette).
4. The container builds and all dependencies are installed automatically via
   `postCreateCommand`.

### Option C – plain local setup

```bash
# Clone and enter the repo
git clone https://github.com/GoSmarter-ai/cuopt-for-metals.git
cd cuopt-for-metals

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# Install all dependencies
pip install -r requirements-dev.txt
pip install -r src/azure-function/requirements.txt
pip install -r src/cuopt-solver/requirements.txt
```

---

## 2. Environment variables for local development

Create a `.env` file (never commit this) based on the template below.
For local testing you can point at an existing Azure Service Bus namespace
or use the [Service Bus emulator](https://learn.microsoft.com/en-us/azure/service-bus-messaging/overview-emulator).

```dotenv
# Service Bus – use the fully-qualified namespace hostname (no SAS key needed
# when running under your own Azure identity via `az login`)
AZURE_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE=sb-cuoptmetalsdev.servicebus.windows.net
AZURE_SERVICEBUS_QUEUE_NAME=cutting-jobs

# Default stock length (mm) used when not specified per-request
STOCK_LENGTH_MM=6000
```

Log in to Azure so `DefaultAzureCredential` can pick up your user token:

```bash
az login
```

---

## 3. Running the Azure Function locally

```bash
cd src/azure-function
func start
```

The function host starts on `http://localhost:7071`. Test it:

```bash
# Health check
curl http://localhost:7071/api/health

# Submit a sample job
curl -X POST http://localhost:7071/api/jobs \
  -H "Content-Type: application/json" \
  -d @../../data/input/example_orders.json
```

---

## 4. Running the solver locally

```bash
cd src/cuopt-solver
python solver.py --input ../../data/input/example_orders.json
```

---

## 5. Running tests

```bash
# From the repository root
pytest tests/ -v --cov=src
```

---

## 6. Deploying to Azure

### 6.1 Login and select subscription

```bash
az login
az account set --subscription "<your-subscription-id>"
```

### 6.2 Create a resource group

```bash
az group create \
  --name rg-cuopt-metals \
  --location australiaeast
```

### 6.3 Edit deployment parameters

Open `infra/main.bicepparam` and review/update:

```
param environmentName = 'dev'
param location       = 'australiaeast'
param projectName    = 'cuoptmetals'
param solverImage    = '<your-registry>/cuopt-solver:latest'
param stockLengthMm  = 6000
```

### 6.4 Deploy the infrastructure

```bash
az deployment group create \
  --resource-group rg-cuopt-metals \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam
```

The deployment takes 3–5 minutes. Outputs include:

| Output | Description |
|--------|-------------|
| `functionAppUrl` | Base URL of the Function App |
| `serviceBusNamespace` | Service Bus namespace name |
| `containerAppsJobName` | Container Apps Job name |

### 6.5 Build and push the solver container

```bash
# Set your registry name (e.g. from ACR)
REGISTRY=cuoptmetals.azurecr.io

az acr login --name cuoptmetals

docker build -t $REGISTRY/cuopt-solver:latest src/cuopt-solver/
docker push $REGISTRY/cuopt-solver:latest
```

### 6.6 Deploy the Function App code

```bash
cd src/azure-function
func azure functionapp publish fn-cuoptmetalsdev
```

### 6.7 Test the live endpoint

```bash
FUNCTION_URL=$(az deployment group show \
  --resource-group rg-cuopt-metals \
  --name main \
  --query properties.outputs.functionAppUrl.value -o tsv)

curl "$FUNCTION_URL/api/health"

curl -X POST "$FUNCTION_URL/api/jobs?code=<function-key>" \
  -H "Content-Type: application/json" \
  -d @data/input/example_orders.json
```

---

## 7. Teardown

```bash
az group delete --name rg-cuopt-metals --yes --no-wait
```

---

## Troubleshooting

| Symptom | Resolution |
|---------|-----------|
| `CredentialUnavailableError` locally | Run `az login` first |
| Function starts but cannot send to Service Bus | Ensure your Azure user has the **Azure Service Bus Data Sender** role on the namespace |
| Container Apps Job never triggers | Check the job's KEDA scale rule in the Azure portal; verify the managed identity has **Azure Service Bus Data Receiver** role |
| `AzureWebJobsStorage` errors on startup | Ensure the Function App's managed identity has **Storage Blob Data Owner**, **Storage Queue Data Contributor**, and **Storage Table Data Contributor** on the storage account (these are granted automatically by the Bicep deployment) |
