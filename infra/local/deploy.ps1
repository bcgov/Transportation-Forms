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
. (Join-Path $PSScriptRoot "engagement-nginx.ps1")

$currentContext = (& kubectl config current-context)
if ($LASTEXITCODE -ne 0 -or $currentContext.Trim() -ne "rancher-desktop") {
    throw "Local deployment requires the rancher-desktop kubectl context."
}

function Invoke-CheckedCommand {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

function Get-KubernetesSecretEncodedValue {
    param([string]$SecretName, [string]$Key)
    $encodedValue = (& kubectl get secret $SecretName -o "jsonpath={.data.$Key}")
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($encodedValue)) {
        throw "Could not read key $Key from Kubernetes secret $SecretName."
    }
    return $encodedValue.Trim()
}

function Get-KubernetesSecretValue {
    param([string]$SecretName, [string]$Key)
    $encodedValue = Get-KubernetesSecretEncodedValue $SecretName $Key
    return [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($encodedValue))
}

function Restore-LocalAnalyticsSecret {
    param([string]$SecretName, [string]$Key, [string]$EncodedValue)
    $secretJson = (& kubectl get secret $SecretName -o json)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read Kubernetes secret $SecretName after Helm deployment."
    }
    $secret = $secretJson | ConvertFrom-Json
    if ($null -eq $secret.data -or [string]::IsNullOrWhiteSpace($secret.metadata.resourceVersion)) {
        throw "Kubernetes secret $SecretName is missing data or resourceVersion."
    }
    if ($secret.data.$Key -ceq $EncodedValue) {
        return
    }
    $secret.data | Add-Member -MemberType NoteProperty -Name $Key -Value $EncodedValue -Force
    $secret | ConvertTo-Json -Depth 100 -Compress | & kubectl replace -f -
    if ($LASTEXITCODE -ne 0) {
        throw "Could not restore key $Key in Kubernetes secret $SecretName."
    }
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
$crunchyCluster = "$CrunchyRelease-crunchy"
$crunchySecret = "$crunchyCluster-pguser-app"
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

$analyticsSecretName = "transportation-forms-secrets"
$analyticsKey = "ANALYTICS_DATABASE_URL"
$analyticsEncodedValue = Get-KubernetesSecretEncodedValue $analyticsSecretName $analyticsKey

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
    $s3EndpointEnv = [System.Environment]::GetEnvironmentVariable("S3_ENDPOINT_URL")
    $s3BucketEnv   = [System.Environment]::GetEnvironmentVariable("S3_BUCKET")
    if ([string]::IsNullOrWhiteSpace($s3EndpointEnv) -or [string]::IsNullOrWhiteSpace($s3BucketEnv)) {
        throw "S3_ENDPOINT_URL and S3_BUCKET must both be populated to configure public-frontend.s3.internalUpstream."
    }
    $s3EndpointRaw = $s3EndpointEnv.TrimEnd('/')
    $s3BucketRaw   = $s3BucketEnv.Trim('/')
    $s3InternalUpstreamFile = Write-HelmValueFile "s3-internal-upstream.txt" "$s3EndpointRaw/$s3BucketRaw"

    $nginxConfigName = "$ReleaseName-public-frontend-nginx"
    $existingNginxJson = (& kubectl get configmap $nginxConfigName -o json --ignore-not-found --show-managed-fields)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect local Public NGINX ConfigMap ownership."
    }
    if (-not [string]::IsNullOrWhiteSpace($existingNginxJson)) {
        $existingNginx = $existingNginxJson | ConvertFrom-Json
        $needsOwnershipHandoff = @($existingNginx.metadata.managedFields | Where-Object {
            $_.manager -eq "kubectl-replace" -and
            $null -ne $_.fieldsV1.'f:data'.'f:default.conf.template'
        }).Count -gt 0
        if ($needsOwnershipHandoff) {
            if (-not $existingNginx.data.'default.conf.template'.Contains('zone=engagement_signals:1m')) {
                throw "Unexpected ownership of local Public NGINX ConfigMap."
            }
            Write-Host "==> Restoring Helm ownership of local Public engagement edge..."
            $currentNginxJson = (& kubectl get configmap $nginxConfigName -o json)
            if ($LASTEXITCODE -ne 0) {
                throw "Could not read local Public NGINX ConfigMap."
            }
            $currentNginxJson | & kubectl apply --server-side --field-manager=helm --force-conflicts -f -
            if ($LASTEXITCODE -ne 0) {
                throw "Could not restore Helm ownership of local Public NGINX ConfigMap."
            }
        }
    }

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
        "--set-string", "global.crunchyCluster=$crunchyCluster",
        "--set-string", "public-backend.resources.app.limits.memory=512Mi",
        "--set-string", "public-frontend.resources.limits.memory=512Mi",
        "--timeout", "10m"
    )
} finally {
    try {
        # Helm owns this Secret and may remove keys added outside its chart.
        Restore-LocalAnalyticsSecret $analyticsSecretName $analyticsKey $analyticsEncodedValue
    } finally {
        $analyticsEncodedValue = $null
        foreach ($tempFile in $script:TempFiles) {
            Remove-Item -Force -ErrorAction SilentlyContinue $tempFile
        }

        if ((Test-Path $tempDir -PathType Container) -and -not (Get-ChildItem -Force -Path $tempDir | Select-Object -First 1)) {
            Remove-Item -Force -ErrorAction SilentlyContinue $tempDir
        }
    }
}

Write-Host "==> Wiring local analytics Secret into backend deployments..."
foreach ($component in @("backend", "public-backend")) {
    Invoke-CheckedCommand "kubectl" @(
        "set", "env", "deployment/$ReleaseName-$component",
        "--containers=$component",
        "--from=secret/$analyticsSecretName",
        "--keys=$analyticsKey"
    )
}

$staffOrigin = [System.Environment]::GetEnvironmentVariable("STAFF_ENGAGEMENT_ORIGIN")
if ([string]::IsNullOrWhiteSpace($staffOrigin)) {
    $staffOrigin = "http://localhost"
}
$staffInterval = [System.Environment]::GetEnvironmentVariable("STAFF_ENGAGEMENT_CACHE_CHECK_MINUTES")
$publicInterval = [System.Environment]::GetEnvironmentVariable("PUBLIC_ENGAGEMENT_CACHE_CHECK_MINUTES")
if ([string]::IsNullOrWhiteSpace($staffInterval)) { $staffInterval = "5" }
if ([string]::IsNullOrWhiteSpace($publicInterval)) { $publicInterval = "5" }

Write-Host "==> Configuring local engagement origins and cache intervals..."
Invoke-CheckedCommand "kubectl" @(
    "set", "env", "deployment/$ReleaseName-backend", "--containers=backend",
    "STAFF_ENGAGEMENT_ORIGIN=$staffOrigin",
    "STAFF_ENGAGEMENT_CACHE_CHECK_MINUTES=$staffInterval"
)
Invoke-CheckedCommand "kubectl" @(
    "set", "env", "deployment/$ReleaseName-public-backend", "--containers=public-backend",
    "PUBLIC_ENGAGEMENT_CACHE_CHECK_MINUTES=$publicInterval"
)

Write-Host "==> Installing local-only Public engagement edge configuration..."
$traefikJson = (& kubectl get pods -n kube-system -l "app.kubernetes.io/name=traefik" -o json)
if ($LASTEXITCODE -ne 0) {
    throw "Could not list local Traefik pods."
}
$traefikPods = ($traefikJson | ConvertFrom-Json).items
$trustedProxyAddresses = @($traefikPods | Where-Object {
    $_.status.phase -eq "Running" -and -not [string]::IsNullOrWhiteSpace($_.status.podIP)
} | ForEach-Object { $_.status.podIP })

$nginxConfigJson = (& kubectl get configmap $nginxConfigName -o json)
if ($LASTEXITCODE -ne 0) {
    throw "Could not read local Public NGINX ConfigMap."
}
$nginxConfig = $nginxConfigJson | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($nginxConfig.data.'default.conf.template')) {
    throw "Local Public NGINX ConfigMap has no default template."
}
$engagementTemplate = Get-LocalEngagementNginxTemplate `
    $nginxConfig.data.'default.conf.template' $trustedProxyAddresses
if ($engagementTemplate -cne $nginxConfig.data.'default.conf.template') {
    $nginxConfig.data.'default.conf.template' = $engagementTemplate
    $nginxConfig | ConvertTo-Json -Depth 100 -Compress | & kubectl apply --server-side --field-manager=helm --force-conflicts -f -
    if ($LASTEXITCODE -ne 0) {
        throw "Could not apply local Public engagement edge configuration."
    }
} else {
    Write-Host "Local Public engagement edge configuration is already current."
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
