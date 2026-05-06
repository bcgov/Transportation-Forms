# Public-Backend — NGINX Sidecar Edge Controls

> **US-007 / US-008** — Reference documentation for the NGINX sidecar that sits
> in front of `public-backend` inside the same Kubernetes pod.

## Architecture

```
Internet → OpenShift Route (TLS termination)
              ↓
         ┌─────────────── Pod ───────────────┐
         │  NGINX sidecar (:8080)             │ ← rate limit, cache, method
         │       ↓ localhost                  │    restrict, strip Set-Cookie
         │  public-backend (:8000)            │ ← FastAPI (read-only)
         └───────────────────────────────────┘
              ↓
         Read-only DB (SELECT only)
```

- **NGINX listens on port 8080** — the Kubernetes Service routes external
  traffic here.
- **public-backend listens on port 8000** — only reachable from localhost
  within the pod.

## NGINX Configuration

The full configuration is deployed via a `ConfigMap` and mounted into the
NGINX sidecar container at `/etc/nginx/nginx.conf`.

```nginx
# -------------------------------------------------------------------
# public-backend NGINX sidecar — edge controls
# -------------------------------------------------------------------

# Rate limiting zone: 10 requests/minute per client IP.
# Uses X-Forwarded-For because the upstream load-balancer (HAProxy route)
# terminates TLS and forwards the real IP in that header.
limit_req_zone $http_x_forwarded_for zone=public_api:10m rate=10r/m;

# Response cache (on-disk, max 100 MB).
proxy_cache_path /tmp/nginx-cache levels=1:2
                 keys_zone=api_cache:10m
                 max_size=100m
                 inactive=10m
                 use_temp_path=off;

server {
    listen 8080;

    # ---------------------------------------------------------------
    # Method restriction (defence-in-depth — also enforced by app)
    # ---------------------------------------------------------------
    if ($request_method !~ ^(GET|HEAD|OPTIONS)$) {
        return 405;
    }

    # ---------------------------------------------------------------
    # Public API location
    # ---------------------------------------------------------------
    location /api/public/ {
        # Rate limiting
        limit_req          zone=public_api burst=15 nodelay;
        limit_req_status   429;

        # Response caching (honours upstream Cache-Control / ETag)
        proxy_cache            api_cache;
        proxy_cache_key        "$scheme$request_method$host$request_uri";
        proxy_cache_valid      200 5m;
        proxy_cache_use_stale  error timeout updating;

        # Strip Set-Cookie in both directions
        proxy_hide_header      Set-Cookie;
        proxy_ignore_headers   Set-Cookie;

        # Propagate / generate X-Request-ID
        proxy_set_header  X-Request-ID  $request_id;
        proxy_set_header  Host          $host;
        proxy_set_header  X-Real-IP     $remote_addr;

        proxy_pass  http://127.0.0.1:8000;
    }

    # ---------------------------------------------------------------
    # Health probes — proxied to backend (no rate limit)
    # ---------------------------------------------------------------
    location = /healthz {
        proxy_pass  http://127.0.0.1:8000/healthz;
    }

    location = /readyz {
        proxy_pass  http://127.0.0.1:8000/readyz;
    }

    # ---------------------------------------------------------------
    # Default — deny everything else
    # ---------------------------------------------------------------
    location / {
        return 404;
    }
}
```

## Controls Summary

| Control | Mechanism | Details |
|---|---|---|
| **Rate limiting** | `limit_req_zone` / `limit_req` | 10 req/min per IP, burst 15 (nodelay). Returns **429** when exceeded. |
| **Method restriction** | `if ($request_method …)` | Only `GET`, `HEAD`, `OPTIONS` pass. All others → **405**. |
| **Response caching** | `proxy_cache` | Cache key = `scheme + method + host + URI + query`. Respects upstream `Cache-Control` / `ETag`. Stale responses on error/timeout. |
| **Set-Cookie stripping** | `proxy_hide_header` + `proxy_ignore_headers` | Ensures no session cookies leak to anonymous clients, even if the backend accidentally emits one. |
| **X-Request-ID** | `proxy_set_header` | NGINX generates `$request_id` (unique per request) and passes it to the backend. If the client provides one, the backend propagates it (defence-in-depth — backend also generates if absent). |
| **Health routing** | Dedicated `location` blocks | `/healthz` and `/readyz` proxied directly to backend without rate limiting so Kubernetes probes are never throttled. |

## Deployment Notes

- The NGINX container runs as a **non-root user** (UID 101, the default
  `nginx` user).
- The cache directory `/tmp/nginx-cache` must be writable by the NGINX user.
  In OpenShift this is handled by the default `emptyDir` volume.
- The ConfigMap should be mounted read-only at `/etc/nginx/nginx.conf`.
- The NGINX and public-backend containers share the same pod network
  namespace — `127.0.0.1:8000` is directly reachable.

## Testing

Refer to the test cases in
`/plan/features/FEAT-0004-public-readonly-forms-api/tests/TC-US-008-nginx-sidecar.md`
for the full acceptance test matrix.
