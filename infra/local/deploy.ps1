param(
    [Parameter(Mandatory=$true)]
    [string]$ReleaseName,

    [Parameter(Mandatory=$true)]
    [string]$Chart,

    [Parameter(Mandatory=$true)]
    [string]$Tag,

    [Parameter(Mandatory=$true)]
    [string]$CrunchyRelease
)

$ErrorActionPreference = "Stop"

function Invoke-CheckedCommand {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

function Get-KubernetesSecretValue {
    param([string]$SecretName, [string]$Key)
    $encodedValue = (& kubectl get secret $SecretName -o "jsonpath={.data.$Key}")
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($encodedValue)) {
        throw "Could not read key $Key from Kubernetes secret $SecretName."
    }
    return [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($encodedValue.Trim()))
}

function Write-HelmValueFile {
    param([string]$Name, [string]$Value)
    $path = "infra/local/.tmp/$Name"
    [System.IO.File]::WriteAllText($path, $Value, $script:Utf8NoBom)
    $script:TempFiles += $path
    return $path
}

$requiredEnvNames = @(
    "SECRET_KEY",
    "S3_ENDPOINT_URL",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_BUCKET",
    "KEYCLOAK_SERVER_URL",
    "KEYCLOAK_REALM",
    "KEYCLOAK_CLIENT_ID",
    "KEYCLOAK_CLIENT_SECRET",
    "KEYCLOAK_REDIRECT_URI",
    "INITIAL_ADMIN_EMAIL"
)

$missingEnvNames = @($requiredEnvNames | Where-Object {
    [string]::IsNullOrWhiteSpace([System.Environment]::GetEnvironmentVariable($_))
})
if ($missingEnvNames.Count -gt 0) {
    throw "Missing required .env values: $($missingEnvNames -join ', ')"
}

Write-Host "==> Extracting DATABASE_URL from Crunchy secret..."
$crunchySecret = "$CrunchyRelease-crunchy-pguser-app"
$dbUri = Get-KubernetesSecretValue $crunchySecret "uri"

$dbUriMatch = [regex]::Match($dbUri, "^(?<scheme>[^:]+://)(?<auth>.+@)(?<hosts>[^/]+)(?<path>/.*)$")
if (-not $dbUriMatch.Success) {
    throw "Crunchy DATABASE_URL format was not recognized."
}

$primaryHost = $dbUriMatch.Groups["hosts"].Value.Split(",")[0]
if ($primaryHost -notmatch ":\d+$") {
    $primaryHost = $primaryHost + ":5432"
}
$primaryDbUri = (
    $dbUriMatch.Groups["scheme"].Value +
    $dbUriMatch.Groups["auth"].Value +
    $primaryHost +
    $dbUriMatch.Groups["path"].Value
).Replace(",", "%2C")

Write-Host "==> Resolving JWT PEM keys..."
$jwtPrivateKeyPem = [System.Environment]::GetEnvironmentVariable("JWT_PRIVATE_KEY_PEM")
$jwtPublicKeyPem = [System.Environment]::GetEnvironmentVariable("JWT_PUBLIC_KEY_PEM")
if ([string]::IsNullOrWhiteSpace($jwtPrivateKeyPem) -or [string]::IsNullOrWhiteSpace($jwtPublicKeyPem)) {
    Write-Host "JWT PEM not in .env; loading from Kubernetes secret pemkeys..."
    $jwtPrivateKeyPem = Get-KubernetesSecretValue "pemkeys" "JWT_PRIVATE_KEY_PEM"
    $jwtPublicKeyPem = Get-KubernetesSecretValue "pemkeys" "JWT_PUBLIC_KEY_PEM"
}

if ([string]::IsNullOrWhiteSpace($jwtPrivateKeyPem) -or [string]::IsNullOrWhiteSpace($jwtPublicKeyPem)) {
    throw "JWT_PRIVATE_KEY_PEM and JWT_PUBLIC_KEY_PEM must both be populated."
}

$tempDir = "infra/local/.tmp"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
$script:TempFiles = @()
$script:Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

try {
    $databaseUrlFile = Write-HelmValueFile "database-url.txt" $primaryDbUri
    $secretKeyFile = Write-HelmValueFile "secret-key.txt" ([System.Environment]::GetEnvironmentVariable("SECRET_KEY"))
    $jwtPrivateKeyFile = Write-HelmValueFile "jwt-private-key.pem" $jwtPrivateKeyPem
    $jwtPublicKeyFile = Write-HelmValueFile "jwt-public-key.pem" $jwtPublicKeyPem
    $s3EndpointFile = Write-HelmValueFile "s3-endpoint-url.txt" ([System.Environment]::GetEnvironmentVariable("S3_ENDPOINT_URL"))
    $s3AccessKeyFile = Write-HelmValueFile "s3-access-key.txt" ([System.Environment]::GetEnvironmentVariable("S3_ACCESS_KEY"))
    $s3SecretKeyFile = Write-HelmValueFile "s3-secret-key.txt" ([System.Environment]::GetEnvironmentVariable("S3_SECRET_KEY"))
    $s3BucketFile = Write-HelmValueFile "s3-bucket.txt" ([System.Environment]::GetEnvironmentVariable("S3_BUCKET"))
    $keycloakServerUrlFile = Write-HelmValueFile "keycloak-server-url.txt" ([System.Environment]::GetEnvironmentVariable("KEYCLOAK_SERVER_URL"))
    $keycloakRealmFile = Write-HelmValueFile "keycloak-realm.txt" ([System.Environment]::GetEnvironmentVariable("KEYCLOAK_REALM"))
    $keycloakClientIdFile = Write-HelmValueFile "keycloak-client-id.txt" ([System.Environment]::GetEnvironmentVariable("KEYCLOAK_CLIENT_ID"))
    $keycloakClientSecretFile = Write-HelmValueFile "keycloak-client-secret.txt" ([System.Environment]::GetEnvironmentVariable("KEYCLOAK_CLIENT_SECRET"))
    $keycloakRedirectUriFile = Write-HelmValueFile "keycloak-redirect-uri.txt" ([System.Environment]::GetEnvironmentVariable("KEYCLOAK_REDIRECT_URI"))
    $initialAdminEmailFile = Write-HelmValueFile "initial-admin-email.txt" ([System.Environment]::GetEnvironmentVariable("INITIAL_ADMIN_EMAIL"))
    $publicBaseUrlFile = Write-HelmValueFile "public-base-url.txt" "http://forms-public.localhost"

    # FEAT-0005 Gap A: NGINX /internal-s3/ proxy_pass needs <endpoint>/<bucket>
    # (path-style addressing). Concat the two .env values into a single file
    # so `--set-file` keeps the value out of process args / shell history.
    $s3EndpointRaw = [System.Environment]::GetEnvironmentVariable("S3_ENDPOINT_URL").TrimEnd('/')
    $s3BucketRaw   = [System.Environment]::GetEnvironmentVariable("S3_BUCKET").Trim('/')
    $s3InternalUpstreamFile = Write-HelmValueFile "s3-internal-upstream.txt" "$s3EndpointRaw/$s3BucketRaw"

    Write-Host "==> Deploying application with Helm..."
    Invoke-CheckedCommand "helm" @(
        "upgrade", "--install", $ReleaseName, $Chart,
        "-f", "$Chart/values.yaml",
        "-f", "$Chart/values-local.yaml",
        "--set-string", "backend.image.tag=$Tag",
        "--set-string", "backend.image.migrationsTag=$Tag",
        "--set-string", "frontend.image.tag=$Tag",
        "--set-string", "public-backend.image.tag=$Tag",
        "--set-string", "public-frontend.image.tag=$Tag",
        "--set-file", "backend.secrets.databaseUrl=$databaseUrlFile",
        "--set-file", "backend.secrets.secretKey=$secretKeyFile",
        "--set-file", "backend.secrets.jwtPrivateKeyPem=$jwtPrivateKeyFile",
        "--set-file", "backend.secrets.jwtPublicKeyPem=$jwtPublicKeyFile",
        "--set-file", "backend.secrets.s3EndpointUrl=$s3EndpointFile",
        "--set-file", "backend.secrets.s3AccessKey=$s3AccessKeyFile",
        "--set-file", "backend.secrets.s3SecretKey=$s3SecretKeyFile",
        "--set-file", "backend.secrets.s3Bucket=$s3BucketFile",
        "--set-file", "backend.secrets.keycloakServerUrl=$keycloakServerUrlFile",
        "--set-file", "backend.secrets.keycloakRealm=$keycloakRealmFile",
        "--set-file", "backend.secrets.keycloakClientId=$keycloakClientIdFile",
        "--set-file", "backend.secrets.keycloakClientSecret=$keycloakClientSecretFile",
        "--set-file", "backend.secrets.keycloakRedirectUri=$keycloakRedirectUriFile",
        "--set-file", "backend.secrets.initialAdminEmail=$initialAdminEmailFile",
        "--set-file", "public-frontend.s3.internalUpstream=$s3InternalUpstreamFile",
        "--set-file", "public-frontend.publicBaseUrl=$publicBaseUrlFile",
        "--set-file", "public-backend.publicBaseUrl=$publicBaseUrlFile",
        "--set-string", "public-backend.resources.app.limits.memory=512Mi",
        "--set-string", "public-frontend.resources.limits.memory=512Mi",
        "--timeout", "10m"
    )
} finally {
    foreach ($tempFile in $script:TempFiles) {
        Remove-Item -Force -ErrorAction SilentlyContinue $tempFile
    }

    if ((Test-Path $tempDir -PathType Container) -and -not (Get-ChildItem -Force -Path $tempDir | Select-Object -First 1)) {
        Remove-Item -Force -ErrorAction SilentlyContinue $tempDir
    }
}

$deployments = @(
    "$ReleaseName-backend",
    "$ReleaseName-frontend",
    "$ReleaseName-public-backend",
    "$ReleaseName-public-frontend"
)

Write-Host "==> Restarting deployments to pick up local image changes..."
foreach ($deployment in $deployments) {
    Invoke-CheckedCommand "kubectl" @("rollout", "restart", "deployment/$deployment")
}

Write-Host "==> Waiting for rollouts to complete..."
foreach ($deployment in $deployments) {
    Invoke-CheckedCommand "kubectl" @("rollout", "status", "deployment/$deployment", "--timeout=300s")
}

Invoke-CheckedCommand "kubectl" @("apply", "-f", "infra/local/ingress.yaml")

Write-Host "Deployment complete."
Write-Host "Internal app:  http://localhost/"
Write-Host "Public portal: http://forms-public.localhost/"
