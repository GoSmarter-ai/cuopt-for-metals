// =============================================================================
// Container Apps Job module  –  Service Bus triggered cuOpt solver
// Authentication: system-assigned managed identity (no shared keys / SAS)
// =============================================================================

param environmentName string
param jobName string
param location string
param logAnalyticsWorkspaceId string
@secure()
param logAnalyticsWorkspaceKey string
// Fully-qualified Service Bus namespace hostname (no SAS key)
param serviceBusNamespaceFqdn string
param serviceBusQueueName string
param solverImage string
param stockLengthMm int = 6000

@description('Maximum number of parallel job replicas')
param maxParallelism int = 1

@description('Number of messages per replica execution')
param messagesPerExecution int = 1

resource containerAppsEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspaceId
        sharedKey: logAnalyticsWorkspaceKey
      }
    }
  }
}

resource containerAppsJob 'Microsoft.App/jobs@2024-03-01' = {
  name: jobName
  location: location
  // System-assigned managed identity – Service Bus Data Receiver role granted in main.bicep
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    environmentId: containerAppsEnv.id
    configuration: {
      triggerType: 'Event'
      replicaTimeout: 1800   // 30 min max per job
      replicaRetryLimit: 2
      eventTriggerConfig: {
        replicaCompletionCount: messagesPerExecution
        parallelism: maxParallelism
        scale: {
          minExecutions: 0
          maxExecutions: 10
          pollingInterval: 30
          rules: [
            {
              name: 'servicebus-trigger'
              type: 'azure-servicebus'
              // Managed-identity KEDA trigger: namespace FQDN, no connection string
              metadata: {
                queueName: serviceBusQueueName
                namespace: serviceBusNamespaceFqdn
                messageCount: '1'
              }
              // No auth block needed – Container Apps uses the job's system-assigned
              // managed identity automatically when 'namespace' is set and no
              // 'connection' key is provided.
            }
          ]
        }
      }
    }
    template: {
      containers: [
        {
          name: 'cuopt-solver'
          image: solverImage
          resources: {
            cpu: json('2.0')
            memory: '4Gi'
          }
          env: [
            // Managed-identity Service Bus access – FQDN, no SAS key
            {
              name: 'AZURE_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE'
              value: serviceBusNamespaceFqdn
            }
            {
              name: 'AZURE_SERVICEBUS_QUEUE_NAME'
              value: serviceBusQueueName
            }
            {
              name: 'STOCK_LENGTH_MM'
              value: string(stockLengthMm)
            }
          ]
        }
      ]
      initContainers: []
    }
  }
}

output jobName string = containerAppsJob.name
output environmentName string = containerAppsEnv.name
// Principal ID for role assignments in main.bicep
output principalId string = containerAppsJob.identity.principalId
