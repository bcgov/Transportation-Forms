param(
    [Parameter(Mandatory=$true)]
    [string]$PgoVersion
)

$ErrorActionPreference = "Stop"

function Invoke-CheckedCommand {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

Write-Host "==> Installing or upgrading PGO operator..."
Invoke-CheckedCommand "helm" @(
    "upgrade", "--install", "pgo",
    "oci://registry.developers.crunchydata.com/crunchydata/pgo",
    "--version", $PgoVersion,
    "-n", "postgres-operator",
    "--create-namespace",
    "--timeout", "120s",
    "--wait"
)

Write-Host "==> Waiting for PGO operator deployment..."
Invoke-CheckedCommand "kubectl" @(
    "wait", "--for=condition=Available", "deployment/pgo",
    "-n", "postgres-operator", "--timeout=120s"
)
