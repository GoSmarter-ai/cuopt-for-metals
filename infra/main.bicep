// =============================================================================
// cuopt-for-metals  –  Main Bicep template
// Deploys: Service Bus, Azure Function App, Container Apps Job
// Authentication: managed identity throughout – no shared keys or SAS tokens
// =============================================================================

targetScope = 'resourceGroup'

@description('Short environment tag, e.g. dev, staging, prod')
@allowed(['dev', 'staging', 'prod'])
param environmentName string = 'dev'

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Name prefix for all resources')
param projectName string = 'cuoptmetals'

@description('Container image for the cuOpt solver (registry/image:tag)')
param solverImage string = 'cuoptmetals.azurecr.io/cuopt-solver:latest'

@description('Default stock length in mm')
param stockLengthMm int = 6000

// ---------------------------------------------------------------------------
// Derived names (keep consistent across modules)
// ---------------------------------------------------------------------------
var baseName = '${projectName}${environmentName}'
var serviceBusNamespaceName = 'sb-${baseName}'
var functionAppName = 'fn-${baseName}'
var containerAppsEnvName = 'cae-${baseName}'
var containerAppsJobName = 'caj-${baseName}'
var storageAccountName = toLower('st${baseName}')
var logAnalyticsName = 'log-${baseName}'
var appInsightsName = 'appi-${baseName}'

// ---------------------------------------------------------------------------
// Built-in role definition IDs (stable GUIDs, same in every Azure tenant)
// ---------------------------------------------------------------------------
var roleIds = {
  // Service Bus
  serviceBusDataSender:   '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
  serviceBusDataReceiver: '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'
  // Storage (required by Azure Functions managed-identity host)
  storageBlobDataOwner:        'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  storageQueueDataContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  storageTableDataContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
}

// ---------------------------------------------------------------------------
// Shared Log Analytics Workspace + App Insights
// ---------------------------------------------------------------------------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ---------------------------------------------------------------------------
// Service Bus
// ---------------------------------------------------------------------------
module serviceBus 'modules/servicebus.bicep' = {
  name: 'serviceBusDeploy'
  params: {
    namespaceName: serviceBusNamespaceName
    location: location
    queueName: 'cutting-jobs'
  }
}

// ---------------------------------------------------------------------------
// Storage Account (required by Function App)
// ---------------------------------------------------------------------------
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

// ---------------------------------------------------------------------------
// Azure Function App
// ---------------------------------------------------------------------------
module functionApp 'modules/function.bicep' = {
  name: 'functionAppDeploy'
  params: {
    functionAppName: functionAppName
    location: location
    storageAccountName: storageAccount.name
    appInsightsConnectionString: appInsights.properties.ConnectionString
    serviceBusNamespaceFqdn: serviceBus.outputs.namespaceFqdn
    serviceBusQueueName: serviceBus.outputs.queueName
  }
}

// ---------------------------------------------------------------------------
// Container Apps Environment + Job
// ---------------------------------------------------------------------------
module containerAppsJob 'modules/container-apps-job.bicep' = {
  name: 'containerAppsJobDeploy'
  params: {
    environmentName: containerAppsEnvName
    jobName: containerAppsJobName
    location: location
    logAnalyticsWorkspaceId: logAnalytics.properties.customerId
    logAnalyticsWorkspaceKey: logAnalytics.listKeys().primarySharedKey
    serviceBusNamespaceFqdn: serviceBus.outputs.namespaceFqdn
    serviceBusQueueName: serviceBus.outputs.queueName
    solverImage: solverImage
    stockLengthMm: stockLengthMm
  }
}

// ---------------------------------------------------------------------------
// Role assignments – Service Bus
// Use existing reference so we can scope assignments to the namespace resource
// ---------------------------------------------------------------------------
resource sbNamespaceRef 'Microsoft.ServiceBus/namespaces@2021-11-01' existing = {
  name: serviceBusNamespaceName
}

// Function App → Azure Service Bus Data Sender
resource sbSenderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sbNamespaceRef.id, functionApp.outputs.principalId, roleIds.serviceBusDataSender)
  scope: sbNamespaceRef
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.serviceBusDataSender)
    principalId: functionApp.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

// Container Apps Job → Azure Service Bus Data Receiver
resource sbReceiverRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sbNamespaceRef.id, containerAppsJob.outputs.principalId, roleIds.serviceBusDataReceiver)
  scope: sbNamespaceRef
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.serviceBusDataReceiver)
    principalId: containerAppsJob.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Role assignments – Storage Account (Azure Functions managed-identity host)
// ---------------------------------------------------------------------------

// Function App → Storage Blob Data Owner
resource storageBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.outputs.principalId, roleIds.storageBlobDataOwner)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageBlobDataOwner)
    principalId: functionApp.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

// Function App → Storage Queue Data Contributor
resource storageQueueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.outputs.principalId, roleIds.storageQueueDataContributor)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageQueueDataContributor)
    principalId: functionApp.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

// Function App → Storage Table Data Contributor
resource storageTableRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.outputs.principalId, roleIds.storageTableDataContributor)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageTableDataContributor)
    principalId: functionApp.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output functionAppUrl string = functionApp.outputs.functionAppUrl
output serviceBusNamespace string = serviceBus.outputs.namespaceName
output containerAppsJobName string = containerAppsJob.outputs.jobName
