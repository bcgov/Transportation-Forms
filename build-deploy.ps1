# build-deploy.ps1
# Full ordered build and deploy to Rancher Desktop.
# Applies: namespace -> secrets -> infra (postgres, minio) -> app -> frontend
#
# Usage:
#   .\build-deploy.ps1              # auto-generates tag from git SHA + timestamp
#   .\build-deploy.ps1 -Tag mybuild # use a custom tag

param(
    [string]$Tag = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# 0. Verify kubectl is reachable (Rancher Desktop must be running)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==> Checking Rancher Desktop / kubectl connectivity..."
kubectl cluster-info --request-timeout=10s | Out-Null
if ($LASTEXITCODE -ne 0) { throw "kubectl cannot reach the cluster. Is Rancher Desktop running?" }
Write-Host "    Cluster is reachable."
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Determine unique image tag
# ---------------------------------------------------------------------------
if (-not $Tag) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $gitSha = ""
    try {
        $gitSha = (git rev-parse --short HEAD 2>$null).Trim()
    } catch {}

    if ($gitSha) {
        $Tag = "$gitSha-$timestamp"
    } else {
        $Tag = "build-$timestamp"
    }
}

$IMAGE = "transportation-forms-app:$Tag"
Write-Host "==> Image tag : $Tag"
Write-Host "==> Full image: $IMAGE"
Write-Host ""

# ---------------------------------------------------------------------------
# 2. Build the Docker image
# ---------------------------------------------------------------------------
Write-Host "==> Building Docker image..."
docker build -t $IMAGE .
if ($LASTEXITCODE -ne 0) { throw "Docker build failed." }
Write-Host "==> Build complete: $IMAGE"
Write-Host ""

# ---------------------------------------------------------------------------
# 3. Apply namespace (idempotent - safe to re-run)
# ---------------------------------------------------------------------------
Write-Host "==> Applying namespace..."
kubectl apply -f k8s/namespace.yaml
if ($LASTEXITCODE -ne 0) { throw "Failed to apply namespace." }

# ---------------------------------------------------------------------------
# 4. Apply secrets (must exist before any deployment references them)
# ---------------------------------------------------------------------------
$secretsFile = "k8s/secrets.yaml"
if (-not (Test-Path $secretsFile)) {
    throw "k8s/secrets.yaml not found. Copy k8s/secrets.example.yaml to k8s/secrets.yaml and fill in values."
}
Write-Host "==> Applying secrets..."
kubectl apply -f $secretsFile
if ($LASTEXITCODE -ne 0) { throw "Failed to apply secrets." }

# ---------------------------------------------------------------------------
# 5. Apply infrastructure (PostgreSQL and MinIO)
# ---------------------------------------------------------------------------
Write-Host "==> Applying infrastructure (postgres, minio)..."
kubectl apply -f k8s/postgres.yaml
if ($LASTEXITCODE -ne 0) { throw "Failed to apply postgres." }
kubectl apply -f k8s/minio.yaml
if ($LASTEXITCODE -ne 0) { throw "Failed to apply minio." }

Write-Host "==> Waiting for infrastructure to be ready (up to 120s)..."
kubectl rollout status deployment/postgres -n transportation-forms --timeout=120s
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL did not become ready in time." }
kubectl rollout status deployment/minio    -n transportation-forms --timeout=120s
if ($LASTEXITCODE -ne 0) { throw "MinIO did not become ready in time." }
Write-Host "    Infrastructure ready."
Write-Host ""

# ---------------------------------------------------------------------------
# 6. Apply app and frontend with the new image tag
# ---------------------------------------------------------------------------
Write-Host "==> Deploying app and frontend (namespace: transportation-forms)..."

foreach ($file in @("k8s/app.yaml", "k8s/frontend.yaml")) {
    Write-Host "    Applying $file ..."
    (Get-Content $file) -replace "IMAGE_TAG", $Tag | kubectl apply -f -
    if ($LASTEXITCODE -ne 0) { throw "kubectl apply failed for $file." }
}

# ---------------------------------------------------------------------------
# 7. Wait for application rollouts
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==> Waiting for app rollouts (up to 180s)..."
kubectl rollout status deployment/app      -n transportation-forms --timeout=180s
if ($LASTEXITCODE -ne 0) { throw "App deployment did not roll out in time." }
kubectl rollout status deployment/frontend -n transportation-forms --timeout=180s
if ($LASTEXITCODE -ne 0) { throw "Frontend deployment did not roll out in time." }

Write-Host ""
Write-Host "==> Deployment complete!"
Write-Host "    Frontend : http://localhost:30800"
Write-Host "    Backend  : http://localhost:30300"
Write-Host "    MinIO    : http://localhost:30900  (console: http://localhost:30901)"
Write-Host ""
