# Infrastructure Reference

This document describes every Azure resource deployed by the Bicep templates in
`infra/`, including resource naming, security model, configuration, and the data
flow between components.

---

## Architecture overview

```
                            ┌─────────────────────────────────────────┐
                            │           Azure Resource Group           │
                            │                                          │
  HTTP client               │  ┌──────────────────┐                   │
  (curl / app)  ──POST──►   │  │  Azure Function   │  system-assigned  │
                            │  │  fn-cuoptmetals*  │  managed identity │
                            │  │  (Python 3.11)    │                   │
                            │  └────────┬──────────┘                   │
                            │           │ send message                  │
                            │           ▼                               │
                            │  ┌──────────────────┐                   │
                            │  │  Service Bus      │                   │
                            │  │  sb-cuoptmetals*  │                   │
                            │  │  queue: cutting-  │                   │
                            │  │  jobs             │                   │
                            │  └────────┬──────────┘                   │
                            │           │ KEDA event trigger            │
                            │           ▼                               │
                            │  ┌──────────────────┐                   │
                            │  │ Container Apps    │  system-assigned  │
                            │  │ Job               │  managed identity │
                            │  │ caj-cuoptmetals*  │                   │
                            │  │ (cuopt-solver     │                   │
                            │  │  container)       │                   │
                            │  └──────────────────┘                   │
                            │                                          │
                            │  Shared: Log Analytics + App Insights    │
                            │          Storage Account (fn host)       │
                            └─────────────────────────────────────────┘
```

---

## Resource inventory

All resource names follow the pattern `<type>-<projectName><environmentName>`.
With the default values (`projectName=cuoptmetals`, `environmentName=dev`) the
names are:

| Resource type | Name | SKU / tier |
|---------------|------|-----------|
| Log Analytics Workspace | `log-cuoptmetalsdev` | PerGB2018, 30-day retention |
| Application Insights | `appi-cuoptmetalsdev` | Workspace-based |
| Storage Account | `stcuoptmetalsdev` | Standard LRS |
| Service Bus Namespace | `sb-cuoptmetalsdev` | Standard |
| Service Bus Queue | `cutting-jobs` | (see below) |
| App Service Plan | `asp-fn-cuoptmetalsdev` | Y1 (Consumption / Linux) |
| Function App | `fn-cuoptmetalsdev` | Python 3.11 |
| Container Apps Environment | `cae-cuoptmetalsdev` | Consumption |
| Container Apps Job | `caj-cuoptmetalsdev` | Event-triggered |

---

## Bicep module breakdown

### `infra/main.bicep`

Orchestrates all modules and owns:

- The **Log Analytics workspace** and **Application Insights** component (shared
  observability layer).
- The **Storage Account** (required by the Azure Functions host).
- All **role assignments** – no module grants its own permissions; all RBAC is
  wired centrally so it is easy to audit.

**Parameters**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `environmentName` | `dev` | `dev`, `staging`, or `prod` |
| `location` | resource group location | Azure region |
| `projectName` | `cuoptmetals` | Resource name prefix (≤12 chars, lowercase alphanumeric) |
| `solverImage` | `cuoptmetals.azurecr.io/cuopt-solver:latest` | Container image for the solver job |
| `stockLengthMm` | `6000` | Default stock bar length in mm |

**Outputs**

| Output | Description |
|--------|-------------|
| `functionAppUrl` | HTTPS base URL of the Function App |
| `serviceBusNamespace` | Service Bus namespace name |
| `containerAppsJobName` | Container Apps Job name |

---

### `infra/modules/servicebus.bicep`

Creates a **Service Bus Standard namespace** and a single queue.

**Queue settings**

| Setting | Value | Reason |
|---------|-------|--------|
| `maxDeliveryCount` | 5 | Retries before dead-lettering |
| `lockDuration` | 5 minutes | Gives the solver enough time to start before the lock expires |
| `defaultMessageTimeToLive` | 1 day | Expired jobs are removed automatically |
| `deadLetteringOnMessageExpiration` | true | Failed jobs are preserved for inspection |

**Outputs consumed by `main.bicep`**

| Output | Description |
|--------|-------------|
| `namespaceFqdn` | Fully-qualified hostname (e.g. `sb-cuoptmetalsdev.servicebus.windows.net`) – used as the managed-identity endpoint; **no SAS key is exposed** |
| `namespaceId` | Resource ID for scoping role assignments |
| `queueName` | Queue name (`cutting-jobs`) |

---

### `infra/modules/function.bicep`

Creates the **Consumption-plan Linux Function App** running Python 3.11.

**Identity**  
A **system-assigned managed identity** is enabled on the Function App. All
Azure SDK clients in the application code use `DefaultAzureCredential`, which
automatically picks up this identity in Azure and falls back to your local
Azure CLI session during development.

**Key app settings**

| Setting | Value | Purpose |
|---------|-------|---------|
| `AzureWebJobsStorage__accountName` | storage account name | Managed-identity storage access (no account key) |
| `AZURE_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE` | `sb-*.servicebus.windows.net` | Managed-identity Service Bus access (no SAS token) |
| `AZURE_SERVICEBUS_QUEUE_NAME` | `cutting-jobs` | Target queue |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | from App Insights | Telemetry |

**Outputs consumed by `main.bicep`**

| Output | Description |
|--------|-------------|
| `principalId` | Object ID of the system-assigned identity (used to assign RBAC roles) |
| `functionAppUrl` | HTTPS base URL |

---

### `infra/modules/container-apps-job.bicep`

Creates a **Container Apps Environment** and an **event-triggered Container
Apps Job** that runs the cuOpt solver container.

**Identity**  
A **system-assigned managed identity** is enabled. The KEDA Service Bus scaler
uses this identity to poll the queue message count (no connection string stored
in the job configuration).

**KEDA scale rule**

```
type: azure-servicebus
metadata:
  namespace: <FQDN>      # e.g. sb-cuoptmetalsdev.servicebus.windows.net
  queueName:  cutting-jobs
  messageCount: 1        # 1 pending message = start 1 replica
```

The scale rule uses `namespace` (FQDN) instead of `connection` (SAS), relying
on the Container Apps platform to authenticate via the job's managed identity.

**Job settings**

| Setting | Value | Reason |
|---------|-------|--------|
| `replicaTimeout` | 1800 s | 30-minute cap per optimisation run |
| `replicaRetryLimit` | 2 | Automatic retry on transient failure |
| `minExecutions` | 0 | Scale to zero when queue is empty |
| `maxExecutions` | 10 | Cap parallel solver instances |
| `pollingInterval` | 30 s | How often KEDA checks the queue |

**Environment variables injected into the container**

| Variable | Value | Description |
|----------|-------|-------------|
| `AZURE_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE` | `sb-*.servicebus.windows.net` | Used by the solver to receive messages |
| `AZURE_SERVICEBUS_QUEUE_NAME` | `cutting-jobs` | Queue to receive from |
| `STOCK_LENGTH_MM` | `6000` | Default stock bar length |

> **Note on Log Analytics key**: The Container Apps Environment API currently
> requires the Log Analytics workspace shared key to configure platform-level
> log routing. This is a platform limitation; the key is only used by the Azure
> control plane during provisioning and is not exposed to application code.

---

## Security model

All inter-component authentication uses **Azure RBAC with managed identities**.
No connection strings, SAS tokens, or account keys are stored in application
settings or environment variables.

### Role assignments (granted by `main.bicep`)

| Principal | Resource | Role | Purpose |
|-----------|----------|------|---------|
| Function App MI | Service Bus Namespace | **Azure Service Bus Data Sender** | Enqueue optimisation jobs |
| Container Apps Job MI | Service Bus Namespace | **Azure Service Bus Data Receiver** | Receive and complete jobs |
| Function App MI | Storage Account | **Storage Blob Data Owner** | Azure Functions host blob storage |
| Function App MI | Storage Account | **Storage Queue Data Contributor** | Azure Functions host queue storage |
| Function App MI | Storage Account | **Storage Table Data Contributor** | Azure Functions host table storage |

### Network security defaults

- Function App: HTTPS only, FTPS disabled, TLS 1.2 minimum.
- Storage Account: public blob access disabled, TLS 1.2 minimum.
- Service Bus: TLS 1.2 minimum.

---

## Observability

All resources stream logs and metrics to a shared **Log Analytics workspace**
(`log-cuoptmetalsdev`). The **Application Insights** instance is workspace-based
and used by the Function App for distributed tracing, live metrics, and
failure alerting.

**Useful Kusto queries**

```kusto
// Function App exceptions
exceptions
| where cloud_RoleName startswith "fn-cuoptmetals"
| order by timestamp desc

// Container Apps Job executions
ContainerAppSystemLogs_CL
| where RevisionName_s startswith "caj-cuoptmetals"
| order by TimeGenerated desc
```
