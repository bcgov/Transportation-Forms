# build-deploy.ps1
# Clean build and deploy to Rancher Desktop using Docker Compose.
# Tears down all containers and volumes, rebuilds all images from scratch,
# then starts the full stack.
#
# Usage:
#   .\archived\build-deploy.ps1
#
# Prerequisites:
#   - Rancher Desktop running with dockerd (moby) engine enabled
#   - .env file present in the project root with all required secrets

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

# ---------------------------------------------------------------------------
# 0. Verify Docker is reachable
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==> Checking Docker connectivity..."
docker info | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Docker is not reachable. Is Rancher Desktop running with dockerd enabled?" }
Write-Host "    Docker is reachable."
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Verify .env file exists
# ---------------------------------------------------------------------------
if (-not (Test-Path ".env")) {
    throw ".env file not found in project root. Copy .env.example to .env and fill in all required values."
}
Write-Host "==> .env file found."
Write-Host ""

# ---------------------------------------------------------------------------
# 2. Tear down existing containers and volumes (clean slate)
# ---------------------------------------------------------------------------
Write-Host "==> Stopping and removing existing containers, networks, and volumes..."
docker compose down --volumes --remove-orphans
if ($LASTEXITCODE -ne 0) { throw "docker compose down failed." }
Write-Host "    Cleaned up."
Write-Host ""

# ---------------------------------------------------------------------------
# 3. Build all images from scratch (no cache)
# ---------------------------------------------------------------------------
Write-Host "==> Building all images (no cache)..."
docker compose build --no-cache
if ($LASTEXITCODE -ne 0) { throw "docker compose build failed." }
Write-Host "==> Build complete."
Write-Host ""

# ---------------------------------------------------------------------------
# 4. Start all services (db + minio first, migrations, then app + frontend)
# ---------------------------------------------------------------------------
Write-Host "==> Starting all services..."
docker compose up -d
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed." }
Write-Host ""

# ---------------------------------------------------------------------------
# 5. Verify all services are healthy
# ---------------------------------------------------------------------------
Write-Host "==> Waiting for services to report healthy (up to 60s)..."
$timeout = 60
$elapsed = 0
$allHealthy = $false

while ($elapsed -lt $timeout) {
    $statuses = docker compose ps --format "{{.Service}}:{{.Health}}" 2>$null
    $unhealthy = $statuses | Where-Object { $_ -notmatch ":healthy$" -and $_ -match ":" }
    if (-not $unhealthy) {
        $allHealthy = $true
        break
    }
    Start-Sleep -Seconds 5
    $elapsed += 5
}

Write-Host ""
docker compose ps
Write-Host ""

if (-not $allHealthy) {
    Write-Host "WARNING: Some services may not have reached healthy state within ${timeout}s. Check 'docker compose ps' and logs."
} else {
    Write-Host "==> All services are healthy."
}

Write-Host ""
Write-Host "==> Deployment complete!"
Write-Host "    Frontend  : http://localhost:3000"
Write-Host "    Backend   : http://localhost:8000"
Write-Host "    MinIO API : http://localhost:9000"
Write-Host "    MinIO UI  : http://localhost:9001"
Write-Host ""
