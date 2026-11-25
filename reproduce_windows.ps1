# Reproduces the fraud prototype end to end on native Windows, following the README setup steps.
# Run from any folder:  powershell -ExecutionPolicy Bypass -File reproduce_windows.ps1
# Takes roughly 20 minutes: about 3 for evaluation and 10 for the replay.
# Everything it installs or writes stays inside this folder (.tools\ and .venv\); delete them to undo.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# uv, the package cache and the Kaggle CLI's environment and config would otherwise land in the user profile.
$tools = Join-Path $PSScriptRoot ".tools"
$env:UV_INSTALL_DIR = "$tools\bin"
$env:UV_NO_MODIFY_PATH = "1"
$env:UV_DISABLE_UPDATE = "1"   # no updater receipt in %LOCALAPPDATA%
$env:UV_CACHE_DIR = "$tools\cache"
$env:UV_TOOL_DIR = "$tools\tools"
$env:KAGGLE_CONFIG_DIR = "$tools\kaggle"
$env:MLFLOW_DISABLE_TELEMETRY = "true"   # MLflow otherwise writes an installation ID to the profile
$env:Path = "$tools\bin;$env:Path"
$ProgressPreference = "SilentlyContinue"   # 5.1's download progress bar slows Invoke-WebRequest badly

# uv's own Python builds are unsigned and Smart App Control blocks them (astral-sh/uv#22869), so every
# uv command, uvx included, uses python.org's signed build instead, unpacked from its NuGet zip.
$pythonUrl = "https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg"
$pythonSha256 = "0eb85c2dfccccf1b17352de4c397f69194035b7d37149eacc16f1147d93de3b8"
$env:UV_PYTHON = "$tools\python-org\tools\python.exe"
$env:UV_PYTHON_DOWNLOADS = "never"   # fail loudly rather than fall back to an unsigned build

# Windows PowerShell 5.1 doesn't stop on a failing native command, so every uv call is checked here.
function Invoke-Step([string]$Title, [string[]]$UvArgs) {
    Write-Host "`n== $Title ==" -ForegroundColor Cyan
    & "$tools\bin\uv.exe" @UvArgs
    if ($LASTEXITCODE -ne 0) { throw "$Title failed (exit code $LASTEXITCODE)" }
}

# 1. uv, always the project's own copy, so a machine-wide uv of another version plays no part.
if (-not (Test-Path "$tools\bin\uv.exe")) {
    Write-Host "== Installing uv into .tools ==" -ForegroundColor Cyan
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
}

if (-not (Test-Path $env:UV_PYTHON)) {
    Write-Host "== Installing Python 3.12.10 (python.org, signed) into .tools ==" -ForegroundColor Cyan
    Invoke-WebRequest $pythonUrl -OutFile "$tools\python.zip"
    if ((Get-FileHash "$tools\python.zip" -Algorithm SHA256).Hash -ne $pythonSha256) {
        throw "The Python download failed its SHA-256 check"
    }
    Expand-Archive "$tools\python.zip" "$tools\python-org" -Force
    Remove-Item "$tools\python.zip"
}

Invoke-Step "Install dependencies" @("sync")
# A valid file already in data\raw\creditcard.csv is accepted as-is, so a manual download works too.
Invoke-Step "Get the data" @("run", "scripts/fraud/get_data.py", "--source", "kaggle")
Invoke-Step "Data report" @("run", "--group", "analysis", "scripts/fraud/data_understanding.py")
Invoke-Step "Verify the complaint slice" @("run", "scripts/triage/get_complaints.py")
Invoke-Step "Train the shortlisted models" @("run", "scripts/fraud/train.py")
Invoke-Step "Write the decision report" @("run", "scripts/fraud/evaluate.py")

# 7. Serve in the background, logging to files so the replay panel has the console to itself.
Write-Host "`n== Start the scoring API ==" -ForegroundColor Cyan
$api = Start-Process "$tools\bin\uv.exe" -ArgumentList "run", "uvicorn", "payguard.fraud.api:app" -PassThru `
    -WindowStyle Hidden -RedirectStandardOutput "api.out.log" -RedirectStandardError "api.err.log"
try {
    $deadline = (Get-Date).AddSeconds(60)
    while ($true) {
        try { Invoke-RestMethod http://127.0.0.1:8000/v1/health | Out-Null; break }
        catch {
            if ($api.HasExited -or (Get-Date) -gt $deadline) { throw "API didn't start; see api.err.log" }
            Start-Sleep -Seconds 1
        }
    }
    Invoke-Step "Replay the demo slice (about 10 minutes)" @("run", "scripts/fraud/replay.py")
}
finally {
    # Killing uv alone could leave its python child serving, so the whole process tree goes.
    taskkill /PID $api.Id /T /F | Out-Null
}

# Last, with the API stopped, so the tests can't load the machine during the replay.
Invoke-Step "Run the tests" @("run", "pytest")

Write-Host "`nDone. Reports are in reports\fraud\. Browse the runs with:" -ForegroundColor Green
Write-Host '  $env:MLFLOW_DISABLE_TELEMETRY="true"; .venv\Scripts\mlflow.exe ui --backend-store-uri sqlite:///mlflow.db'
