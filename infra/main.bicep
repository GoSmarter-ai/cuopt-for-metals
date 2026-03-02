// =============================================================================
// cuopt-for-metals  –  Main Bicep template
// Deploys: Service Bus, Azure Function App, Container Apps Job
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
    serviceBusConnectionString: serviceBus.outputs.connectionString
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
    logAnalyticsWorkspaceId: logAnalytics.id
    logAnalyticsWorkspaceKey: logAnalytics.listKeys().primarySharedKey
    serviceBusConnectionString: serviceBus.outputs.connectionString
    serviceBusQueueName: serviceBus.outputs.queueName
    solverImage: solverImage
    stockLengthMm: stockLengthMm
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output functionAppUrl string = functionApp.outputs.functionAppUrl
output serviceBusNamespace string = serviceBus.outputs.namespaceName
output containerAppsJobName string = containerAppsJob.outputs.jobName
