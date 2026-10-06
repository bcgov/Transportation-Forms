#!/bin/sh
set -eu

. /usr/local/lib/ip-access.sh

policy_dir=/config/ip-access
mkdir -p "$policy_dir/global" "$policy_dir/site"

if [ -d /etc/ip-access ]; then
    ip_access_validate_file /etc/ip-access/trustedProxyCidrs "$policy_dir/trusted.txt"
    {
        printf 'trusted_proxies static'
        while IFS= read -r cidr; do printf ' %s' "$cidr"; done < "$policy_dir/trusted.txt"
        printf '\ntrusted_proxies_strict\nclient_ip_headers X-Forwarded-For\n'
    } > "$policy_dir/global/trust.caddy"

    if [ "${IP_ACCESS_ENABLED:-false}" = true ]; then
        ip_access_validate_file /etc/ip-access/allowedClientCidrs "$policy_dir/allowed.txt"
        {
            printf '@missing_xff not header X-Forwarded-For *\n'
            printf 'abort @missing_xff\n'
            printf '@unlisted not client_ip'
            while IFS= read -r cidr; do printf ' %s' "$cidr"; done < "$policy_dir/allowed.txt"
            printf '\nabort @unlisted\n'
        } > "$policy_dir/site/allowlist.caddy"
    fi
elif [ "${IP_ACCESS_ENABLED:-false}" = true ]; then
    printf 'IP access is enabled but /etc/ip-access is missing\n' >&2
    exit 1
fi

exec "$@"