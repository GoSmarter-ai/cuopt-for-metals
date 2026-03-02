// =============================================================================
// Service Bus module  –  namespace + queue
// =============================================================================

param namespaceName string
param location string
param queueName string = 'cutting-jobs'

@description('SKU for the Service Bus namespace')
@allowed(['Basic', 'Standard', 'Premium'])
param sku string = 'Standard'

resource namespace 'Microsoft.ServiceBus/namespaces@2021-11-01' = {
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

resource queue 'Microsoft.ServiceBus/namespaces/queues@2021-11-01' = {
  parent: namespace
  name: queueName
  properties: {
    maxDeliveryCount: 5
    lockDuration: 'PT5M'
    defaultMessageTimeToLive: 'P1D'
    deadLetteringOnMessageExpiration: true
  }
}

output namespaceName string = namespace.name
output namespaceId string = namespace.id
// Fully-qualified hostname used by managed-identity clients (no shared keys exposed)
output namespaceFqdn string = '${namespace.name}.servicebus.windows.net'
output queueName string = queue.name
