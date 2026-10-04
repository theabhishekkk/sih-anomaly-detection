targetScope = 'resourceGroup'

@description('Azure region; verify Container Apps, PostgreSQL v17, and quota availability before deployment.')
param location string = 'centralindia'

@description('Short environment label used to make globally unique Azure resource names.')
@minLength(3)
@maxLength(20)
param environmentName string = 'sihprod'

@description('The initial Microsoft container-app sample image is replaced by the reviewed application image after provisioning.')
param bootstrapImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Exact HTTPS origin of the deployed application, including any custom domain.')
param publicBaseUrl string = 'https://burnin.example.com'

@description('PostgreSQL administrator login. Use a unique deployment-only administrator.')
@minLength(1)
param postgresAdminLogin string

@secure()
@description('PostgreSQL administrator password; supplied at deployment time and stored in Key Vault.')
param postgresAdminPassword string

@secure()
@description('Password for the least-privilege application database account.')
param appDatabasePassword string

@description('Microsoft Entra tenant ID.')
param oidcTenantId string

@description('Microsoft Entra application (client) ID.')
param oidcClientId string

@secure()
@description('Microsoft Entra OIDC client secret; supplied at deployment time and stored in Key Vault.')
param oidcClientSecret string

@description('Comma-separated, exact email allowlist for QA access.')
param oidcAllowedEmails string

@secure()
@description('At least 32 random characters; supplied at deployment time and stored in Key Vault.')
@minLength(32)
param sessionSecret string

var resourceToken = uniqueString(subscription().id, resourceGroup().id, location, environmentName)
var acrName = 'azacr${resourceToken}'
var keyVaultName = 'azkv${resourceToken}'
var migrationKeyVaultName = 'azmkv${resourceToken}'
var identityName = 'azmi${resourceToken}'
var migrationIdentityName = 'azmig${resourceToken}'
var logAnalyticsName = 'azlaw${resourceToken}'
var containerEnvironmentName = 'azcae${resourceToken}'
var containerAppName = 'azaca${resourceToken}'
var migrationJobName = 'azjob${resourceToken}'
var postgresServerName = 'azpg${resourceToken}'
var databaseName = 'azdb${resourceToken}'
var databaseAppUser = 'burnin_app_${resourceToken}'
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Standard'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
}

resource migrationIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: migrationIdentityName
  location: location
}

resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, appIdentity.id, acrPullRoleId)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource migrationAcrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, migrationIdentity.id, acrPullRoleId)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: migrationIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    retentionInDays: 30
    sku: {
      name: 'PerGB2018'
    }
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'azai${resourceToken}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerEnvironmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }
}

resource migrationKeyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: migrationKeyVaultName
  location: location
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }
}

resource keyVaultSecretsUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, appIdentity.id, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource migrationKeyVaultSecretsUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(migrationKeyVault.id, migrationIdentity.id, keyVaultSecretsUserRoleId)
  scope: migrationKeyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: migrationIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: postgresServerName
  location: location
  sku: {
    name: 'Standard_D2ds_v5'
    tier: 'GeneralPurpose'
  }
  properties: {
    version: '17'
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    storage: {
      storageSizeGB: 32
      autoGrow: 'Enabled'
      tier: 'P4'
    }
    backup: {
      backupRetentionDays: 35
      geoRedundantBackup: 'Enabled'
    }
    network: {
      publicNetworkAccess: 'Enabled'
    }
    highAvailability: {
      mode: 'ZoneRedundant'
      standbyAvailabilityZone: '2'
    }
  }
}

resource postgresDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgresServer
  name: databaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource postgresAzureServicesFirewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgresServer
  name: 'azfw${resourceToken}'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource databaseUrlSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'azapp${resourceToken}'
  properties: {
    value: 'postgresql+psycopg://${databaseAppUser}:${uriComponent(appDatabasePassword)}@${postgresServer.properties.fullyQualifiedDomainName}:5432/${databaseName}?sslmode=require'
  }
  dependsOn: [
    keyVaultSecretsUserAssignment
    postgresDatabase
  ]
}

resource migrationDatabaseUrlSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: migrationKeyVault
  name: 'azmurl${resourceToken}'
  properties: {
    value: 'postgresql+psycopg://${databaseAppUser}:${uriComponent(appDatabasePassword)}@${postgresServer.properties.fullyQualifiedDomainName}:5432/${databaseName}?sslmode=require'
  }
  dependsOn: [
    migrationKeyVaultSecretsUserAssignment
    postgresDatabase
  ]
}

resource adminDatabaseUrlSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: migrationKeyVault
  name: 'azadm${resourceToken}'
  properties: {
    value: 'postgresql+psycopg://${postgresAdminLogin}:${uriComponent(postgresAdminPassword)}@${postgresServer.properties.fullyQualifiedDomainName}:5432/${databaseName}?sslmode=require'
  }
  dependsOn: [
    migrationKeyVaultSecretsUserAssignment
    postgresDatabase
  ]
}

resource appDatabasePasswordSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: migrationKeyVault
  name: 'azpwd${resourceToken}'
  properties: {
    value: appDatabasePassword
  }
  dependsOn: [
    migrationKeyVaultSecretsUserAssignment
  ]
}

resource oidcClientSecretResource 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'azoidc${resourceToken}'
  properties: {
    value: oidcClientSecret
  }
  dependsOn: [
    keyVaultSecretsUserAssignment
  ]
}

resource appSessionSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'azses${resourceToken}'
  properties: {
    value: sessionSecret
  }
  dependsOn: [
    keyVaultSecretsUserAssignment
  ]
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${appIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        {
          server: registry.properties.loginServer
          identity: appIdentity.id
        }
      ]
      secrets: [
        {
          name: 'database-url'
          keyVaultUrl: databaseUrlSecret.properties.secretUriWithVersion
          identity: appIdentity.id
        }
        {
          name: 'oidc-client-secret'
          keyVaultUrl: oidcClientSecretResource.properties.secretUriWithVersion
          identity: appIdentity.id
        }
        {
          name: 'app-session-secret'
          keyVaultUrl: appSessionSecret.properties.secretUriWithVersion
          identity: appIdentity.id
        }
      ]
      ingress: {
        external: true
        allowInsecure: false
        targetPort: 80
        transport: 'auto'
        corsPolicy: {
          allowedOrigins: [
            publicBaseUrl
          ]
          allowedMethods: [
            'GET'
            'POST'
            'OPTIONS'
          ]
          allowedHeaders: [
            'Content-Type'
            'X-CSRF-Token'
          ]
          allowCredentials: true
          maxAge: 600
        }
      }
    }
    template: {
      revisionSuffix: 'bootstrap'
      containers: [
        {
          name: 'burnin-api'
          image: bootstrapImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/health'
                port: 8000
              }
              periodSeconds: 5
              timeoutSeconds: 3
              failureThreshold: 30
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health/ready'
                port: 8000
              }
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 3
            }
          ]
          env: [
            {
              name: 'APP_ENV'
              value: 'production'
            }
            {
              name: 'DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'APP_SESSION_SECRET'
              secretRef: 'app-session-secret'
            }
            {
              name: 'OIDC_TENANT_ID'
              value: oidcTenantId
            }
            {
              name: 'OIDC_CLIENT_ID'
              value: oidcClientId
            }
            {
              name: 'OIDC_CLIENT_SECRET'
              secretRef: 'oidc-client-secret'
            }
            {
              name: 'OIDC_ALLOWED_EMAILS'
              value: oidcAllowedEmails
            }
            {
              name: 'PUBLIC_BASE_URL'
              value: publicBaseUrl
            }
            {
              name: 'PORT'
              value: '8000'
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: applicationInsights.properties.ConnectionString
            }
            {
              name: 'WEB_CONCURRENCY'
              value: '2'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [
          {
            name: 'http-concurrency'
            http: {
              metadata: {
                concurrentRequests: '60'
              }
            }
          }
        ]
      }
    }
  }
  dependsOn: [
    acrPullAssignment
    keyVaultSecretsUserAssignment
    postgresAzureServicesFirewall
  ]
}

resource migrationJob 'Microsoft.App/jobs@2024-03-01' = {
  name: migrationJobName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${migrationIdentity.id}': {}
    }
  }
  properties: {
    environmentId: containerEnvironment.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: migrationIdentity.id
        }
      ]
      secrets: [
        {
          name: 'database-url'
          keyVaultUrl: migrationDatabaseUrlSecret.properties.secretUriWithVersion
          identity: migrationIdentity.id
        }
        {
          name: 'admin-database-url'
          keyVaultUrl: adminDatabaseUrlSecret.properties.secretUriWithVersion
          identity: migrationIdentity.id
        }
        {
          name: 'app-database-password'
          keyVaultUrl: appDatabasePasswordSecret.properties.secretUriWithVersion
          identity: migrationIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'database-migrations'
          image: bootstrapImage
          command: ['python']
          args: ['-m', 'backend.initialize_production_db']
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            {
              name: 'DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'DATABASE_ADMIN_URL'
              secretRef: 'admin-database-url'
            }
            {
              name: 'DATABASE_APP_USER'
              value: databaseAppUser
            }
            {
              name: 'DATABASE_APP_PASSWORD'
              secretRef: 'app-database-password'
            }
          ]
        }
      ]
    }
  }
  dependsOn: [
    acrPullAssignment
    migrationAcrPullAssignment
    migrationKeyVaultSecretsUserAssignment
    postgresAzureServicesFirewall
  ]
}

output resourceToken string = resourceToken
output acrName string = registry.name
output acrLoginServer string = registry.properties.loginServer
output keyVaultName string = keyVault.name
output migrationKeyVaultName string = migrationKeyVault.name
output containerAppName string = containerApp.name
output migrationJobName string = migrationJob.name
output postgresServerName string = postgresServer.name
output containerAppUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
