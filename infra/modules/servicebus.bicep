// =============================================================================
// Service Bus module  –  namespace + queue
// =============================================================================

param namespaceName string
param location string
param queueName string = 'cutting-jobs'

@description('SKU for the Service Bus namespace')
@allowed(['Basic', 'Standard', 'Premium'])
param sku string = 'Standard'

resource namespace 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: namespaceName
  location: location
  sku: {
    name: sku
    tier: sku
  }
  properties: {
    minimumTlsVersion: '1.2'
  }
}

resource queue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: namespace
  name: queueName
  properties: {
    maxDeliveryCount: 5
    lockDuration: 'PT5M'
    defaultMessageTimeToLive: 'P1D'
    deadLetteringOnMessageExpiration: true
  }
}

resource authRule 'Microsoft.ServiceBus/namespaces/AuthorizationRules@2022-10-01-preview' existing = {
  parent: namespace
  name: 'RootManageSharedAccessKey'
}

output namespaceName string = namespace.name
output queueName string = queue.name
output connectionString string = authRule.listKeys().primaryConnectionString
