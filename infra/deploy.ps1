param(
    [Parameter(Mandatory = $true)]
    [string]$SubscriptionId,

    [Parameter(Mandatory = $true)]
    [string]$ResourceGroupName
)

$ErrorActionPreference = "Stop"
$infraDirectory = $PSScriptRoot
$parametersPath = Join-Path $infraDirectory "main.parameters.json"

foreach ($name in @(
    "POSTGRES_ADMIN_PASSWORD",
    "APP_DATABASE_PASSWORD",
    "OIDC_CLIENT_SECRET",
    "APP_SESSION_SECRET"
)) {
    if (-not [Environment]::GetEnvironmentVariable($name)) {
        throw "Set $name in the current process environment before deploying."
    }
}

if ($env:POSTGRES_ADMIN_LOGIN -and $env:POSTGRES_ADMIN_LOGIN -notmatch "^[A-Za-z][A-Za-z0-9_]{2,31}$") {
    throw "POSTGRES_ADMIN_LOGIN must start with a letter and contain 3-32 letters, digits, or underscores."
}
if ($env:POSTGRES_ADMIN_PASSWORD.Length -lt 16) {
    throw "POSTGRES_ADMIN_PASSWORD must be at least 16 characters."
}
if ($env:APP_DATABASE_PASSWORD.Length -lt 16) {
    throw "APP_DATABASE_PASSWORD must be at least 16 characters."
}
if ($env:APP_SESSION_SECRET.Length -lt 32) {
    throw "APP_SESSION_SECRET must be at least 32 characters."
}

$parameters = Get-Content -LiteralPath $parametersPath -Raw | ConvertFrom-Json
if ($parameters.parameters.publicBaseUrl.value -notmatch "^https://[^/]+$") {
    throw "Set publicBaseUrl in infra/main.parameters.json to the exact HTTPS application origin."
}
if ($parameters.parameters.oidcTenantId.value -match "^REPLACE_" -or
    $parameters.parameters.oidcClientId.value -match "^REPLACE_" -or
    $parameters.parameters.oidcAllowedEmails.value -match "example\.com") {
    throw "Replace the Entra tenant, application, and QA email placeholders in infra/main.parameters.json."
}

$parameters.parameters | Add-Member -MemberType NoteProperty -Name postgresAdminLogin -Value @{ value = "burninadmin" } -Force
$parameters.parameters.postgresAdminLogin.value = if ($env:POSTGRES_ADMIN_LOGIN) {
    $env:POSTGRES_ADMIN_LOGIN
} else {
    "burninadmin"
}
foreach ($entry in @(
    @{ Name = "postgresAdminPassword"; Value = $env:POSTGRES_ADMIN_PASSWORD },
    @{ Name = "appDatabasePassword"; Value = $env:APP_DATABASE_PASSWORD },
    @{ Name = "oidcClientSecret"; Value = $env:OIDC_CLIENT_SECRET },
    @{ Name = "sessionSecret"; Value = $env:APP_SESSION_SECRET }
)) {
    $parameters.parameters | Add-Member -MemberType NoteProperty -Name $entry.Name -Value @{ value = $entry.Value } -Force
}

$parameterFile = New-TemporaryFile
$compiledTemplate = Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString() + ".json")
try {
    $parametersJson = $parameters | ConvertTo-Json -Depth 10
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($parameterFile.FullName, $parametersJson, $utf8WithoutBom)
    az account show --subscription $SubscriptionId --output none
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI is not authenticated for subscription $SubscriptionId. Run az login first."
    }
    az account set --subscription $SubscriptionId
    if ($LASTEXITCODE -ne 0) {
        throw "Could not select Azure subscription $SubscriptionId."
    }
    az bicep build --file (Join-Path $infraDirectory "main.bicep") --outfile $compiledTemplate
    if ($LASTEXITCODE -ne 0) {
        throw "Bicep compilation failed."
    }

    $region = $parameters.parameters.location.value
    az group create --name $ResourceGroupName --location $region --output none
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create or access resource group $ResourceGroupName."
    }
    $deploymentJson = az deployment group create `
        --resource-group $ResourceGroupName `
        --name "sih-burnin-production" `
        --template-file $compiledTemplate `
        --parameters "@$($parameterFile.FullName)" `
        --output json
    if ($LASTEXITCODE -ne 0) {
        throw "Azure deployment failed. Review the preceding Azure CLI error output."
    }
    $deployment = $deploymentJson | ConvertFrom-Json
    Write-Output "Deployment completed."
    Write-Output "Application URL: $($deployment.properties.outputs.containerAppUrl.value)"
    Write-Output "ACR login server: $($deployment.properties.outputs.acrLoginServer.value)"
    Write-Output "Container App: $($deployment.properties.outputs.containerAppName.value)"
    Write-Output "Migration job: $($deployment.properties.outputs.migrationJobName.value)"
    Write-Output "PostgreSQL server: $($deployment.properties.outputs.postgresServerName.value)"
    Write-Output "Key Vault: $($deployment.properties.outputs.keyVaultName.value)"
} finally {
    Remove-Item -LiteralPath $parameterFile.FullName -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $compiledTemplate -Force -ErrorAction SilentlyContinue
}
