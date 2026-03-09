// =============================================================================
// Azure Function App module  –  Consumption plan, Python 3.11
// Authentication: system-assigned managed identity (no shared keys)
// =============================================================================

param functionAppName string
param location string
param storageAccountName string
param appInsightsConnectionString string
param serviceBusNamespaceFqdn string
param serviceBusQueueName string

var hostingPlanName = 'asp-${functionAppName}'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource hostingPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: hostingPlanName
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    reserved: true // Linux
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  // System-assigned managed identity – roles granted in main.bicep
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: hostingPlan.id
    siteConfig: {
      pythonVersion: '3.11'
      linuxFxVersion: 'Python|3.11'
      appSettings: [
        // Managed-identity storage access – no account key required
        {
          name: 'AzureWebJobsStorage__accountName'
          value: storageAccount.name
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsightsConnectionString
        }
        // Managed-identity Service Bus access – FQDN, no SAS key
        {
          name: 'AZURE_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE'
          value: serviceBusNamespaceFqdn
        }
        {
          name: 'AZURE_SERVICEBUS_QUEUE_NAME'
          value: serviceBusQueueName
        }
      ]
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
    }
    httpsOnly: true
  }
}

output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output functionAppName string = functionApp.name
// Principal ID for role assignments in main.bicep
output principalId string = functionApp.identity.principalId
