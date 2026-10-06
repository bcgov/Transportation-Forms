#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# public-frontend entrypoint — DPR-2
#
# Renders ConfigMap-supplied templates into the writable conf.d
# emptyDir, then execs nginx. All inputs come from env vars set by the
# Helm chart Deployment.
# ─────────────────────────────────────────────────────────────────────────────
set -eu
. /usr/local/lib/ip-access.sh

if [ -f /vault/secrets/secrets.env ]; then
    . /vault/secrets/secrets.env
fi

if [ -z "${S3_INTERNAL_UPSTREAM:-}" ] && [ -n "${S3_ENDPOINT_URL:-}" ] && [ -n "${S3_BUCKET:-}" ]; then
    s3_endpoint="${S3_ENDPOINT_URL%/}"
    s3_bucket="${S3_BUCKET#/}"
    s3_bucket="${s3_bucket%/}"
    S3_INTERNAL_UPSTREAM="${s3_endpoint}/${s3_bucket}"
    export S3_INTERNAL_UPSTREAM
fi

: "${BACKEND_UPSTREAM_HOST:?BACKEND_UPSTREAM_HOST must be set}"
: "${BACKEND_UPSTREAM_PORT:=8000}"
: "${INTERNAL_AUTH_SECRET:?INTERNAL_AUTH_SECRET must be set}"
: "${PUBLIC_BASE_URL:=}"
: "${S3_INTERNAL_UPSTREAM:=}"

CONF_D=/etc/nginx/conf.d
TEMPLATES=/etc/nginx/templates

# Recreate dirs that live inside emptyDir mounts (/var/run, /var/cache/nginx).
mkdir -p "${CONF_D}/maps" "${CONF_D}/trust" "${CONF_D}/access" /var/run/nginx /var/cache/nginx/proxy

if [ -d /etc/ip-access ]; then
    ip_access_validate_file /etc/ip-access/trustedProxyCidrs "${CONF_D}/trusted.txt"
    {
        while IFS= read -r cidr; do printf 'set_real_ip_from %s;\n' "$cidr"; done < "${CONF_D}/trusted.txt"
        printf 'real_ip_header X-Forwarded-For;\nreal_ip_recursive on;\n'
    } > "${CONF_D}/trust/realip.conf"

    if [ "${IP_ACCESS_ENABLED:-false}" = true ]; then
        ip_access_validate_file /etc/ip-access/allowedClientCidrs "${CONF_D}/allowed.txt"
        {
            printf 'if ($http_x_forwarded_for = "") { return 403; }\n'
            while IFS= read -r cidr; do printf 'allow %s;\n' "$cidr"; done < "${CONF_D}/allowed.txt"
            printf 'deny all;\n'
        } > "${CONF_D}/access/allowlist.conf"
    fi
elif [ "${IP_ACCESS_ENABLED:-false}" = true ]; then
    printf 'IP access is enabled but /etc/ip-access is missing\n' >&2
    exit 1
fi

# Bot UA map — mounted via separate ConfigMap into ${TEMPLATES}/maps/.
if [ -d "${TEMPLATES}/maps" ]; then
    cp "${TEMPLATES}/maps/"*.conf "${CONF_D}/maps/" 2>/dev/null || true
fi

# Render default block containing upstream and server. All ${VAR} placeholders are filled from env at container start.
envsubst '${BACKEND_UPSTREAM_HOST} ${BACKEND_UPSTREAM_PORT} ${INTERNAL_AUTH_SECRET} ${S3_INTERNAL_UPSTREAM} ${PUBLIC_BASE_URL}' \
    < "${TEMPLATES}/default.conf.template" \
    > "${CONF_D}/00-default.conf"

nginx -t
exec "$@"
