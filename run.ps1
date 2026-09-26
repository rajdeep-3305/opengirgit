# One-command OpenGirGit for Windows: create a virtualenv, install both
# requirement sets, start the API server and launch the overlay client.
#
#   .\run.ps1                 # full stack (default)
#   .\run.ps1 --check         # validate prerequisites only
#   .\run.ps1 --no-server     # client only
#   .\run.ps1 --no-client     # server only
#
# Environment overrides: PYTHON, HOST, PORT, OPENGIRGIT_SERVER_URL, OPENGIRGIT_VENV.
param(
    [switch]$Check,
    [switch]$NoServer,
    [switch]$NoClient
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = if ($env:OPENGIRGIT_VENV) { $env:OPENGIRGIT_VENV } else { Join-Path $Root ".venv" }
$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$HostAddr = if ($env:HOST) { $env:HOST } else { "127.0.0.1" }
$Port = if ($env:PORT) { $env:PORT } else { "8000" }
$ServerUrl = if ($env:OPENGIRGIT_SERVER_URL) { $env:OPENGIRGIT_SERVER_URL } else { "http://${HostAddr}:${Port}" }
$env:HOST = $HostAddr
$env:PORT = $Port

& $Python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.10+ is required (found: $(& $Python -V 2>&1))"
}

Write-Host "python:  $(& $Python -V 2>&1)"
Write-Host "venv:    $Venv"
if (-not $NoServer) { Write-Host "server:  $ServerUrl" }
if (-not $NoClient) { Write-Host "client:  overlay" }

if ($Check) {
    Write-Host "check: OK"
    exit 0
}

$Py = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "creating virtualenv..."
    & $Python -m venv $Venv
}
& $Py -m pip install --quiet --upgrade pip

$Stamp = Join-Path $Venv ".requirements.sha256"
$Hashes = @(
    (Get-FileHash -Algorithm SHA256 (Join-Path $Root "server\requirements.txt")).Hash,
    (Get-FileHash -Algorithm SHA256 (Join-Path $Root "client\requirements.txt")).Hash
) -join "-"
if ((-not (Test-Path $Stamp)) -or ((Get-Content $Stamp -Raw).Trim() -ne $Hashes)) {
    Write-Host "installing dependencies (first run also fetches the faster-whisper wheel)..."
    & $Py -m pip install --quiet -r (Join-Path $Root "server\requirements.txt") -r (Join-Path $Root "client\requirements.txt")
    Set-Content -Path $Stamp -Value $Hashes -NoNewline
}

$ServerProcess = $null
try {
    if (-not $NoServer) {
        Write-Host "starting API server..."
        $ServerProcess = Start-Process -FilePath $Py -ArgumentList "run.py" `
            -WorkingDirectory (Join-Path $Root "server") -PassThru -NoNewWindow
        $Healthy = $false
        foreach ($i in 1..60) {
            try {
                Invoke-WebRequest -UseBasicParsing "$ServerUrl/api/health" -TimeoutSec 2 | Out-Null
                $Healthy = $true
                break
            } catch {
                if ($ServerProcess.HasExited) { throw "the server exited during startup" }
                Start-Sleep -Milliseconds 500
            }
        }
        if (-not $Healthy) { throw "server did not answer on $ServerUrl/api/health" }
        Write-Host "server ready: $ServerUrl"
    }

    if (-not $NoClient) {
        $EnvFile = Join-Path $Root "client\.env"
        if (-not (Test-Path $EnvFile)) {
            Set-Content -Path $EnvFile -Value "OPENGIRGIT_SERVER_URL=$ServerUrl"
            Write-Host "wrote client\.env (OPENGIRGIT_SERVER_URL=$ServerUrl)"
        }
        Write-Host "starting client overlay..."
        Push-Location (Join-Path $Root "client")
        try {
            & $Py main.py
        } finally {
            Pop-Location
        }
    }
} finally {
    if ($ServerProcess -and -not $ServerProcess.HasExited) {
        Write-Host "stopping server..."
        Stop-Process -Id $ServerProcess.Id -Force
    }
}
