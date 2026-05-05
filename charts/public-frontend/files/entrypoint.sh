#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# public-frontend entrypoint — DPR-2
#
# Renders ConfigMap-supplied templates into the writable conf.d
# emptyDir, then execs nginx. All inputs come from env vars set by the
# Helm chart Deployment.
# ─────────────────────────────────────────────────────────────────────────────
set -eu

: "${BACKEND_UPSTREAM_HOST:?BACKEND_UPSTREAM_HOST must be set}"
: "${BACKEND_UPSTREAM_PORT:=8000}"
: "${INTERNAL_AUTH_SECRET:?INTERNAL_AUTH_SECRET must be set}"
: "${PUBLIC_BASE_URL:=}"
: "${S3_INTERNAL_UPSTREAM:=}"

CONF_D=/etc/nginx/conf.d
TEMPLATES=/etc/nginx/templates

# Recreate dirs that live inside emptyDir mounts (/var/run, /var/cache/nginx).
mkdir -p "${CONF_D}/maps" /var/run/nginx /var/cache/nginx/proxy

# Bot UA map — mounted via separate ConfigMap into ${TEMPLATES}/maps/.
if [ -d "${TEMPLATES}/maps" ]; then
    cp "${TEMPLATES}/maps/"*.conf "${CONF_D}/maps/" 2>/dev/null || true
fi

# Render default block containing upstream and server. All ${VAR} placeholders are filled from env at container start.
envsubst '${BACKEND_UPSTREAM_HOST} ${BACKEND_UPSTREAM_PORT} ${INTERNAL_AUTH_SECRET} ${S3_INTERNAL_UPSTREAM} ${PUBLIC_BASE_URL}' \
    < "${TEMPLATES}/default.conf.template" \
    > "${CONF_D}/00-default.conf"

exec "$@"
