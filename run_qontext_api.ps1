$ErrorActionPreference = "Stop"

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $project

$localPy = Join-Path $project ".local-py"

if (-not (Test-Path $localPy)) {
    Write-Host "Installing local Python dependencies into .local-py ..."
    python -m pip install --disable-pip-version-check --target .local-py fastapi uvicorn networkx
}

Write-Host "Starting Qontext API on http://127.0.0.1:8000"
Write-Host "Docs: http://127.0.0.1:8000/docs"

python .\run_qontext_api.py
