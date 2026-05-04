# syntax=docker/dockerfile:1.7
# public-frontend image
# Single-stage vanilla NGINX build

# Stage 1: Runtime
FROM nginx:1.27-alpine AS runtime

# Adapt for OpenShift's arbitrary-UID security model (OpenShift assigns a
# random UID at runtime; we run as non-root group 0).
USER 0
RUN set -eux; \
    mkdir -p /var/cache/nginx/proxy /var/run/nginx /var/log/nginx \
             /etc/nginx/conf.d/maps /etc/nginx/templates \
             /usr/share/nginx/html; \
    chgrp -R 0 /var/cache/nginx /var/run/nginx /var/log/nginx \
               /etc/nginx /usr/share/nginx/html; \
    chmod -R g+rwX /var/cache/nginx /var/run/nginx /var/log/nginx \
                   /etc/nginx /usr/share/nginx/html; \
    ln -sf /dev/stdout /var/log/nginx/access.log; \
    ln -sf /dev/stderr /var/log/nginx/error.log

# Bake SPA static assets
# Build context = repo root. readOnlyRootFilesystem=true at runtime, so the
# SPA tree must be present in the image layer (not a runtime volume).
COPY --chown=1001:0 public-frontend/index.html      /usr/share/nginx/html/index.html
COPY --chown=1001:0 public-frontend/css/            /usr/share/nginx/html/css/
COPY --chown=1001:0 public-frontend/js/             /usr/share/nginx/html/js/
COPY --chown=1001:0 public-frontend/fonts/          /usr/share/nginx/html/fonts/
COPY --chown=1001:0 public-frontend/assets/         /usr/share/nginx/html/assets/
COPY --chown=1001:0 public-frontend/robots.txt      /usr/share/nginx/html/robots.txt

# Custom main nginx.conf (http{}-level zones + map includes)
COPY --chown=1001:0 charts/public-frontend/files/nginx.conf      /etc/nginx/nginx.conf

# Entrypoint: render conf.d templates from envsubst, then exec
COPY --chown=1001:0 charts/public-frontend/files/entrypoint.sh   /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod g+rx /entrypoint.sh

# Drop back to a non-root UID; OpenShift will override at runtime, but this
# keeps the image safe to run on plain Kubernetes / Rancher Desktop.
USER 1001
EXPOSE 3000 3001
HEALTHCHECK NONE

ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]