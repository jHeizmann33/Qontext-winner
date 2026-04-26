$ErrorActionPreference = "Stop"

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontend = Join-Path $project "frontend"

Set-Location $frontend

if (-not (Test-Path "node_modules")) {
    Write-Host "Installing frontend dependencies..."
    npm install --cache .npm-cache
}

Write-Host "Starting Qontext demo UI on http://127.0.0.1:5173"
Write-Host "The UI expects the Qontext API on http://127.0.0.1:8000"

npm run dev
