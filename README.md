# cuopt-for-metals

A reference implementation demonstrating how to run an event-driven
**1D cutting-stock optimisation** job on Azure using
[NVIDIA cuOpt](https://developer.nvidia.com/cuopt-logistics-optimization).

## What it does

A client POSTs a list of metal bar/sheet cutting orders to an
**Azure Function** (HTTP API). The function validates the request and places
a message on an **Azure Service Bus** queue. A KEDA-triggered
**Azure Container Apps Job** picks up the message, runs the cuOpt solver to
find the optimal cutting pattern that minimises waste, and writes the result
back for consumption.

```
Client → Azure Function → Service Bus → Container Apps Job (cuOpt solver)
```

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Local dev setup, running tests, and deploying to Azure |
| [Infrastructure Reference](docs/infrastructure.md) | Every Azure resource, the security model, and observability |
| [Infrastructure README](infra/README.md) | Quick deploy commands and parameter reference |

## Repository layout

```
.devcontainer/          Dev container for VS Code / GitHub Codespaces
docs/                   Project documentation
  getting-started.md
  infrastructure.md
infra/                  Azure Bicep IaC
  main.bicep            Orchestration template (incl. all RBAC assignments)
  main.bicepparam       Deployment parameters
  modules/
    servicebus.bicep
    function.bicep
    container-apps-job.bicep
src/
  azure-function/       HTTP ingest function (Python, Azure Functions v4)
  cuopt-solver/         cuOpt solver container (Python)
data/
  input/                Sample cutting-order JSON files
evaluation/             Evaluation framework and metrics
tests/                  Unit and integration tests
```

## Security

All inter-component authentication uses **Azure managed identities with
least-privilege RBAC**. No connection strings, SAS tokens, or account keys
are stored in application settings. See
[Infrastructure Reference → Security model](docs/infrastructure.md#security-model)
for the full role assignment table.
