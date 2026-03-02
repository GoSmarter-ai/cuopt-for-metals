// =============================================================================
// Container Apps Job module  –  Service Bus triggered cuOpt solver
// =============================================================================

param environmentName string
param jobName string
param location string
param logAnalyticsWorkspaceId string
@secure()
param logAnalyticsWorkspaceKey string
@secure()
param serviceBusConnectionString string
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
              metadata: {
                queueName: serviceBusQueueName
                messageCount: '1'
              }
              auth: [
                {
                  secretRef: 'servicebus-connection'
                  triggerParameter: 'connection'
                }
              ]
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
            {
              name: 'AZURE_SERVICEBUS_CONNECTION_STRING'
              secretRef: 'servicebus-connection'
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
