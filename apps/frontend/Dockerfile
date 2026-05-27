# ── Stage 1: Build custom Caddy with Coraza WAF plugin ───────────────────────
FROM caddy:2.11.3-builder AS caddy-build

RUN apk add --no-cache ca-certificates libcap
# FEAT-0015: pin Coraza-Caddy plugin to a tagged release for reproducibility.
RUN xcaddy build \
    --with github.com/corazawaf/coraza-caddy/v2@v2.2.0
# Strip file capabilities here so the final image does not need libcap
RUN setcap -r /usr/bin/caddy


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM caddy:2.11.3-alpine AS runtime

# Replace the default Caddy binary with our custom build (includes Coraza WAF)
COPY --from=caddy-build /usr/bin/caddy /usr/bin/caddy

# Copy static web assets
COPY apps/frontend/index.html      /srv/index.html
COPY apps/frontend/css/            /srv/static/css/
COPY apps/frontend/assets/         /srv/static/assets/
COPY apps/frontend/js/             /srv/static/js/

# Copy Caddy and WAF configuration
COPY apps/frontend/Caddyfile       /etc/caddy/Caddyfile
COPY apps/frontend/coraza.conf     /etc/caddy/coraza.conf

# OpenShift compatibility: UID 1001, root group (GID 0).
# Caddy data/config dirs must be writable by the container user.
RUN chown -R 1001:0 /srv /etc/caddy /data /config && \
    chmod -R g=u   /srv /etc/caddy /data /config

USER 1001

# 3000 – primary HTTP port (static files + reverse proxy to backend)
# 3001 – health check port (isolated from WAF)
EXPOSE 3000 3001

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://localhost:3001/healthz || exit 1