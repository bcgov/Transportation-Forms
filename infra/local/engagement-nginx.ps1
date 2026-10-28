function Replace-LocalNginxAnchor {
    param([string]$Text, [string]$Anchor, [string]$Replacement)

    $first = $Text.IndexOf($Anchor, [System.StringComparison]::Ordinal)
    if ($first -lt 0 -or $Text.IndexOf($Anchor, $first + $Anchor.Length, [System.StringComparison]::Ordinal) -ge 0) {
        throw "Local Public NGINX template anchor missing or ambiguous."
    }
    return $Text.Replace($Anchor, $Replacement)
}

function Set-LocalEngagementBodyLimit {
    param([string]$Template)

    $newline = if ($Template.Contains("`r`n")) { "`r`n" } else { "`n" }
    $oversizeLocation = @'
    location @engagement_oversized {
        client_max_body_size 0;
        limit_req zone=engagement_signals burst=20 nodelay;
        limit_conn engagement_connections 20;
        limit_req_status 429;
        limit_conn_status 429;
        access_log off;
        error_log /dev/null crit;
        try_files /__engagement_oversized__ =413;
    }

'@.Replace("`r`n", "`n").Replace("`n", $newline)

    $Template = Replace-LocalNginxAnchor $Template `
        ('    location = /api/public/v1/engagement/signal {' + $newline + '        client_max_body_size 0;') `
        ('    location = /api/public/v1/engagement/signal {' + $newline +
            '        client_max_body_size 1k;' + $newline +
            '        error_page 413 = @engagement_oversized;')
    $Template = Replace-LocalNginxAnchor $Template `
        '    location /api/public/v1/ {' `
        ($oversizeLocation + $newline + '    location /api/public/v1/ {')
    return Set-LocalEngagementResponses $Template
}

function Enable-LocalEngagementRecursiveErrors {
    param([string]$Template)

    if (-not $Template.Contains('    location = /api/public/v1/engagement/signal {')) {
        throw "Local Public NGINX signal location is missing."
    }
    if ($Template.Contains('        recursive_error_pages on;')) {
        throw "Local Public NGINX recursive error routing is already enabled."
    }
    $newline = if ($Template.Contains("`r`n")) { "`r`n" } else { "`n" }
    return Replace-LocalNginxAnchor $Template `
        '        client_max_body_size 1k;' `
        ('        recursive_error_pages on;' + $newline +
            '        client_max_body_size 1k;')
}

function Set-LocalEngagementResponses {
    param([string]$Template)

    $newline = if ($Template.Contains("`r`n")) { "`r`n" } else { "`n" }
    $handlers = @'
    location @engagement_body_rejected {
        access_log off;
        error_log /dev/null crit;
        default_type application/json;
        add_header Cache-Control "no-store" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
        add_header X-Frame-Options "DENY" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
        add_header Permissions-Policy "geolocation=(), camera=(), microphone=(), payment=()" always;
        add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
        return 413 '{"accepted":false}';
    }

    location @engagement_rate_rejected {
        access_log off;
        error_log /dev/null crit;
        default_type application/json;
        add_header Cache-Control "no-store" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
        add_header X-Frame-Options "DENY" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
        add_header Permissions-Policy "geolocation=(), camera=(), microphone=(), payment=()" always;
        add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
        return 429 '{"accepted":false}';
    }

'@.Replace("`r`n", "`n").Replace("`n", $newline)

    $Template = Replace-LocalNginxAnchor $Template `
        ('        error_page 413 = @engagement_oversized;' + $newline) `
        ('        error_page 413 = @engagement_oversized;' + $newline +
            '        error_page 429 = @engagement_rate_rejected;' + $newline)
    if (-not $Template.Contains('    location @engagement_oversized {')) {
        throw "Local Public NGINX oversized handler is missing."
    }
    $Template = Replace-LocalNginxAnchor $Template `
        '        client_max_body_size 0;' `
        ('        client_max_body_size 0;' + $newline +
            '        error_page 429 = @engagement_rate_rejected;')
    $Template = Replace-LocalNginxAnchor $Template `
        '        try_files /__engagement_oversized__ =413;' `
        '        try_files /__engagement_oversized__ @engagement_body_rejected;'
    $Template = Replace-LocalNginxAnchor $Template `
        '    location /api/public/v1/ {' `
        ($handlers + $newline + '    location /api/public/v1/ {')
    return Enable-LocalEngagementRecursiveErrors $Template
}

function Get-LocalEngagementNginxTemplate {
    param([string]$Template, [string[]]$TrustedProxyAddresses)

    if ($TrustedProxyAddresses.Count -eq 0) {
        throw "Local Traefik has no running pod IP."
    }

    $trustedProxies = foreach ($address in ($TrustedProxyAddresses | Sort-Object -Unique)) {
        $parsedAddress = $null
        if (-not [System.Net.IPAddress]::TryParse($address, [ref]$parsedAddress)) {
            throw "Traefik pod IP is invalid."
        }
        "    set_real_ip_from $parsedAddress;"
    }

    if ($Template.Contains('zone=engagement_signals:1m')) {
        $required = @(
            'limit_req_zone $binary_remote_addr zone=engagement_signals:1m rate=100r/m;',
            '    location = /api/public/v1/engagement/signal {',
            '        client_max_body_size 1k;',
            '        recursive_error_pages on;',
            '        limit_req zone=engagement_signals burst=20 nodelay;',
            '    location @engagement_body_rejected {',
            '    location @engagement_rate_rejected {',
            '        return 413 ''{"accepted":false}'';',
            '        return 429 ''{"accepted":false}'';'
        )
        foreach ($marker in $required) {
            if (-not $Template.Contains($marker)) {
                throw "Existing local Public NGINX engagement overlay is incomplete or stale."
            }
        }
        $proxyPattern = '(?m)(?:^    set_real_ip_from [^;\r\n]+;\r*\n)+(?=    real_ip_header X-Forwarded-For;)'
        $proxyBlocks = [regex]::Matches($Template, $proxyPattern)
        if ($proxyBlocks.Count -ne 1) {
            throw "Existing local Public NGINX trusted proxy block is missing or ambiguous."
        }
        $existingProxies = @([regex]::Matches($proxyBlocks[0].Value, 'set_real_ip_from ([^;\r\n]+);') |
            ForEach-Object { "    set_real_ip_from $($_.Groups[1].Value);" })
        if ([string]::Join('|', $existingProxies) -ne [string]::Join('|', $trustedProxies)) {
            $newline = if ($Template.Contains("`r`n")) { "`r`n" } else { "`n" }
            $replacement = ($trustedProxies -join $newline) + $newline
            return [regex]::Replace($Template, $proxyPattern, $replacement)
        }
        return $Template
    }

    $map = @'
limit_req_zone $binary_remote_addr zone=engagement_signals:1m rate=100r/m;
limit_conn_zone $binary_remote_addr zone=engagement_connections:1m;

map "$request_method:$uri" $engagement_method_allowed {
    default 0;
    ~^(GET|HEAD|OPTIONS): 1;
    ~^.+:/api/public/v1/engagement/signal$ 1;
}

'@
    $signalLocation = @'
    location = /api/public/v1/engagement/signal {
        client_max_body_size 0;
        limit_req zone=engagement_signals burst=20 nodelay;
        limit_conn engagement_connections 20;
        limit_req_status 429;
        limit_conn_status 429;
        limit_req_log_level info;
        access_log off;
        error_log /dev/null crit;
        proxy_request_buffering off;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $request_id;
        proxy_set_header X-Internal-Auth $internal_auth_value;
        proxy_hide_header Set-Cookie;
        proxy_hide_header X-Powered-By;
        proxy_hide_header Server;
        proxy_http_version 1.1;
        proxy_pass http://upstream_public_backend;
    }

'@
    $newline = if ($Template.Contains("`r`n")) { "`r`n" } else { "`n" }
    $map = $map.Replace("`n", $newline)
    $signalLocation = $signalLocation.Replace("`n", $newline)
    $proxyConfig = ($trustedProxies -join $newline) + $newline + @'
    real_ip_header X-Forwarded-For;
    real_ip_recursive on;
'@.Replace("`n", $newline)

    $Template = Replace-LocalNginxAnchor $Template `
        'map $request_method $internal_auth_value {' `
        ($map + $newline + 'map $request_method $internal_auth_value {')
    $Template = Replace-LocalNginxAnchor $Template `
        'if ($request_method !~ ^(GET|HEAD|OPTIONS)$) {' `
        'if ($engagement_method_allowed = 0) {'
    $Template = Replace-LocalNginxAnchor $Template `
        '    include /etc/nginx/conf.d/access/*.conf;' `
        ('    include /etc/nginx/conf.d/access/*.conf;' + $newline + $proxyConfig)
    $Template = Replace-LocalNginxAnchor $Template `
        '    location /api/public/v1/ {' `
        ($signalLocation + $newline + '    location /api/public/v1/ {')
    return Set-LocalEngagementBodyLimit $Template
}