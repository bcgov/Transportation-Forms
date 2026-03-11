# build-deploy.ps1
# Builds and deploys the Transportation Forms app with a unique image tag per run.
# Usage:
#   .\build-deploy.ps1              # auto-generates tag from git SHA + timestamp
#   .\build-deploy.ps1 -Tag mybuild # use a custom tag

param(
    [string]$Tag = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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
Write-Host ""
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
# 3. Apply Kubernetes manifests with tag substituted
# ---------------------------------------------------------------------------
Write-Host "==> Deploying to Rancher Desktop (namespace: transportation-forms)..."

foreach ($file in @("k8s/app.yaml", "k8s/frontend.yaml")) {
    Write-Host "    Applying $file ..."
    (Get-Content $file) -replace "IMAGE_TAG", $Tag | kubectl apply -f -
    if ($LASTEXITCODE -ne 0) { throw "kubectl apply failed for $file." }
}

Write-Host ""
Write-Host "==> Waiting for rollouts..."
kubectl rollout status deployment/app      -n transportation-forms --timeout=120s
kubectl rollout status deployment/frontend -n transportation-forms --timeout=120s

Write-Host ""
Write-Host "==> Deployment complete!"
Write-Host "    Frontend : http://localhost:30800"
Write-Host "    Backend  : http://localhost:30300"
Write-Host ""
