# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# public-frontend image — DPR-2 (FEAT-0005)
#
# Single-NGINX edge: serves the static SPA (index.html / css / js / vendor /
# robots.txt), terminates :3000 public traffic through Coraza WAF, proxies
# /api/public/v1/* to the in-cluster public-backend Service, and exposes
# :3001 for unauthenticated /healthz probes.
#
# Base image: owasp/coraza-nginx (user-approved dependency — DPR-3 will switch
# to digest-pinned tags once mirrored to GHCR).
# ─────────────────────────────────────────────────────────────────────────────
FROM owasp/coraza-nginx:latest

# Adapt for OpenShift's arbitrary-UID security model (OpenShift assigns a
# random UID at runtime; we run as non-root group 0).
USER 0
RUN set -eux; \
    mkdir -p /var/cache/nginx/proxy /var/run/nginx /var/log/nginx \
             /etc/nginx/conf.d/maps /etc/nginx/templates /etc/coraza \
             /usr/share/nginx/html; \
    chgrp -R 0 /var/cache/nginx /var/run/nginx /var/log/nginx \
               /etc/nginx /etc/coraza /usr/share/nginx/html; \
    chmod -R g+rwX /var/cache/nginx /var/run/nginx /var/log/nginx \
                   /etc/nginx /etc/coraza /usr/share/nginx/html; \
    # Forward NGINX logs to stdout/stderr (defensive — upstream image already
    # does this for /var/log/nginx/{access,error}.log).
    ln -sf /dev/stdout /var/log/nginx/access.log; \
    ln -sf /dev/stderr /var/log/nginx/error.log

# ── Bake SPA static assets ───────────────────────────────────────────────────
# Build context = repo root. readOnlyRootFilesystem=true at runtime, so the
# SPA tree must be present in the image layer (not a runtime volume).
COPY --chown=1001:0 public-frontend/index.html      /usr/share/nginx/html/index.html
COPY --chown=1001:0 public-frontend/css/            /usr/share/nginx/html/css/
COPY --chown=1001:0 public-frontend/js/             /usr/share/nginx/html/js/
COPY --chown=1001:0 public-frontend/vendor/         /usr/share/nginx/html/vendor/
COPY --chown=1001:0 public-frontend/robots.txt      /usr/share/nginx/html/robots.txt

# ── Custom main nginx.conf (http{}-level zones + map includes) ───────────────
COPY --chown=1001:0 charts/public-frontend/files/nginx.conf      /etc/nginx/nginx.conf

# ── Entrypoint: render conf.d / coraza templates from envsubst, then exec ──
COPY --chown=1001:0 charts/public-frontend/files/entrypoint.sh   /entrypoint.sh
RUN chmod g+rx /entrypoint.sh

# Drop back to a non-root UID; OpenShift will override at runtime, but this
# keeps the image safe to run on plain Kubernetes / Rancher Desktop.
USER 1001
EXPOSE 3000 3001
HEALTHCHECK NONE
ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
