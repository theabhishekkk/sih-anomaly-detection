$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$ollamaCommand = Get-Command ollama.exe -ErrorAction SilentlyContinue
$ollamaPath = if ($ollamaCommand) { $ollamaCommand.Source } else { $null }
if (-not $ollamaPath) {
    $possiblePaths = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )
    foreach ($candidate in $possiblePaths) {
        if (Test-Path -LiteralPath $candidate) {
            $ollamaPath = $candidate
            break
        }
    }
}

if (-not $ollamaPath) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Install Ollama from https://ollama.com/download/windows, then rerun this script."
    }
    & $winget.Source install --id Ollama.Ollama --exact --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        throw "Ollama installation failed with exit code $LASTEXITCODE."
    }
    $possiblePaths = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )
    foreach ($candidate in $possiblePaths) {
        if (Test-Path -LiteralPath $candidate) {
            $ollamaPath = $candidate
            break
        }
    }
    if (-not $ollamaPath) {
        throw "Ollama installed but ollama.exe was not found. Open a new terminal and rerun."
    }
}

$pythonPath = Join-Path $repoRoot "backend\venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Create the project environment first: python -m venv backend\venv; then install backend\requirements.txt."
}

$ollamaApi = "http://127.0.0.1:11434/api/tags"
$ollamaReady = $false
try {
    $null = Invoke-RestMethod -Uri $ollamaApi -TimeoutSec 2
    $ollamaReady = $true
} catch {
    $null = Start-Process -FilePath $ollamaPath -ArgumentList "serve" -WindowStyle Hidden -PassThru
}

for ($attempt = 0; $attempt -lt 45 -and -not $ollamaReady; $attempt++) {
    Start-Sleep -Seconds 2
    try {
        $null = Invoke-RestMethod -Uri $ollamaApi -TimeoutSec 2
        $ollamaReady = $true
    } catch {
        continue
    }
}
if (-not $ollamaReady) {
    throw "Ollama did not start at http://127.0.0.1:11434. Start Ollama and retry."
}

Write-Host "Preparing free local AI model qwen3:4b. The first download is several GB."
& $ollamaPath pull qwen3:4b
if ($LASTEXITCODE -ne 0) {
    throw "Could not download qwen3:4b. Check your connection and available disk space."
}

$port = if ($env:PORT) { $env:PORT } else { "8000" }
$env:APP_ENV = "development"
$env:OLLAMA_MODEL = "qwen3:4b"
$env:OLLAMA_URL = "http://127.0.0.1:11434"
$env:WEB_CONCURRENCY = "1"
Set-Location $repoRoot
Write-Host "Starting Burn-in Intelligence with local Ollama AI at http://127.0.0.1:$port"
& $pythonPath -m uvicorn backend.app:app --host 127.0.0.1 --port $port --workers 1
