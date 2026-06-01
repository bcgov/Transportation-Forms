$ErrorActionPreference = "Stop"

param(
    [Parameter(Mandatory=$true)]
    [string]$CachePath,

    [Parameter(Mandatory=$true)]
    [string]$ExpectedRef,

    [Parameter(Mandatory=$true)]
    [string]$ReleaseName
)

function Invoke-CheckedCommand {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

$shouldClone = $true

if (Test-Path $CachePath) {
    $currentRef = (& git -C $CachePath describe --tags --exact-match 2>$null)
    if ($LASTEXITCODE -eq 0 -and $currentRef.Trim() -eq $ExpectedRef) {
        $shouldClone = $false
        Write-Host "==> Using cached action-crunchy chart at $ExpectedRef."
    } else {
        Write-Host "==> Removing stale action-crunchy cache."
        Remove-Item -Recurse -Force $CachePath
    }
}

if ($shouldClone) {
    Write-Host "==> Cloning action-crunchy $ExpectedRef..."
    Invoke-CheckedCommand "git" @(
        "clone", "--branch", $ExpectedRef, "--depth", "1",
        "https://github.com/bcgov/action-crunchy.git", $CachePath
    )
}

$networkPolicyTemplate = "$CachePath/charts/crunchy/templates/knp.yaml"
if (Test-Path $networkPolicyTemplate) {
    Remove-Item -Force $networkPolicyTemplate
}

$postgresClusterTemplate = "$CachePath/charts/crunchy/templates/postgrescluster.yaml"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$templateContent = [System.IO.File]::ReadAllText($postgresClusterTemplate)
[System.IO.File]::WriteAllText(
    $postgresClusterTemplate,
    $templateContent.Replace("openshift: true", "openshift: false"),
    $utf8NoBom
)

Write-Host "==> Deploying Crunchy PostgreSQL..."
Invoke-CheckedCommand "helm" @(
    "upgrade", "--install", $ReleaseName,
    "$CachePath/charts/crunchy",
    "-f", "infra/charts/crunchy/values.yml",
    "-f", "infra/local/crunchy-overrides.yaml",
    "--timeout", "5m"
)

Write-Host "==> Waiting for Crunchy PostgreSQL primary pod..."
$primarySelector = "postgres-operator.crunchydata.com/role=master,postgres-operator.crunchydata.com/cluster=$ReleaseName-crunchy"
& kubectl wait "--for=condition=Ready" pod -l $primarySelector "--timeout=180s"
if ($LASTEXITCODE -ne 0) {
    $postgresSelector = "postgres-operator.crunchydata.com/data=postgres,postgres-operator.crunchydata.com/cluster=$ReleaseName-crunchy"
    Invoke-CheckedCommand "kubectl" @(
        "wait", "--for=condition=Ready", "pod", "-l", $postgresSelector, "--timeout=180s"
    )
}
