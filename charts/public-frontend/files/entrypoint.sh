#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# public-frontend entrypoint — DPR-2
#
# Renders ConfigMap-supplied templates into the writable conf.d / coraza
# emptyDirs, then execs nginx. All inputs come from env vars set by the
# Helm chart Deployment.
# ─────────────────────────────────────────────────────────────────────────────
set -eu

: "${BACKEND_UPSTREAM_HOST:?BACKEND_UPSTREAM_HOST must be set}"
: "${BACKEND_UPSTREAM_PORT:=8000}"
: "${INTERNAL_AUTH_SECRET:?INTERNAL_AUTH_SECRET must be set}"
: "${PUBLIC_BASE_URL:=}"
: "${CORAZA_RULE_ENGINE:=DetectionOnly}"
: "${S3_INTERNAL_UPSTREAM:=}"

CONF_D=/etc/nginx/conf.d
TEMPLATES=/etc/nginx/templates
CORAZA_DIR=/etc/coraza

mkdir -p "${CONF_D}/maps" "${CORAZA_DIR}"

# Static (non-templated) server config.
cp "${TEMPLATES}/default.conf" "${CONF_D}/default.conf"

# Bot UA map — mounted via separate ConfigMap into ${TEMPLATES}/maps/.
if [ -d "${TEMPLATES}/maps" ]; then
    cp "${TEMPLATES}/maps/"*.conf "${CONF_D}/maps/" 2>/dev/null || true
fi

# Render upstream block + auth-header snippet. Prefixed 00- so it sorts before
# default.conf (the `upstream { }` must be parsed before any `proxy_pass` to it).
envsubst '${BACKEND_UPSTREAM_HOST} ${BACKEND_UPSTREAM_PORT} ${INTERNAL_AUTH_SECRET} ${S3_INTERNAL_UPSTREAM} ${PUBLIC_BASE_URL}' \
    < "${TEMPLATES}/upstream.conf.template" \
    > "${CONF_D}/00-upstream.conf"

# Render Coraza directives with the per-env rule engine mode.
envsubst '${CORAZA_RULE_ENGINE}' \
    < "${TEMPLATES}/coraza.conf.template" \
    > "${CORAZA_DIR}/main.conf"

exec "$@"
