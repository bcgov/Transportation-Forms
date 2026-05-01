# `public-frontend/vendor/` — Vendored Static Assets

Per FEAT-0005 §3 (Vendored Assets — No CDN), the public-frontend MUST serve
all CSS, font, and JS assets from same-origin. This directory is the drop
target.

The Python SE does **not** commit binary or third-party assets (out of the
"no new dependencies without consent" policy and to keep the source tree
licence-clean). The DevOps build step (US-015 / US-017 — chart packaging
or Taskfile target) is responsible for placing the following files here
before image build:

| File | Source (suggested) | Notes |
|---|---|---|
| `bootstrap-theme.min.css` | https://github.com/bcgov/bootstrap-v5-theme `dist/css/bootstrap-theme.min.css` | BC Gov themed Bootstrap v5. SRI hash should be pinned in `index.html` if BC Gov publishes one. |
| `bootstrap.bundle.min.js` | https://github.com/twbs/bootstrap (matching minor) `dist/js/bootstrap.bundle.min.js` | Optional — only required if interactive Bootstrap components (modals, dropdowns) are introduced. Slice 2A does not load it. |
| `bc-sans.css` | https://github.com/bcgov/bc-sans `dist/bc-sans.css` | Defines `@font-face` rules pointing to `bc-sans.woff2`. |
| `bc-sans.woff2` (and any subsetted variants) | same as above | Referenced from `bc-sans.css`. |
| `bc-gov-logo.svg` | BC Gov design system | Used in header, favicon, and 404 chrome. |

## Pinned versions

The DevOps subagent should pin a single commit/tag per asset in the chart
or Taskfile so the public surface is reproducible. Suggested format in
`charts/public-frontend/values.yaml`:

```yaml
vendor:
  bootstrapTheme:
    version: "5.3.0"
    sha256: "<digest>"
  bcSans:
    version: "2.0.0"
    sha256: "<digest>"
```

## Why aren't these checked in?

1. **Licence hygiene** — committing third-party CSS/font/JS into our repo
   without a clear vendoring policy creates a licensing audit burden.
2. **Dependency policy** — the Python SE charter prohibits introducing
   new dependencies without written consent. Vendoring binary/CSS assets
   functionally adds dependencies.
3. **Build reproducibility** — pinning at chart/build time lets the
   DevOps Engineer roll forward asset versions without code review by
   the application engineer.

## CSP expectations (DevOps to honour)

Once the assets are in place, the NGINX edge (US-011) must serve them
under `Content-Security-Policy: default-src 'self'; img-src 'self' data:;
font-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self';
frame-ancestors 'none'; base-uri 'self'; form-action 'self';`.

If `bootstrap.bundle.min.js` is loaded, no CSP change is needed — it is
same-origin.

## Smoke-check at runtime

After build, the public-frontend container should pass:

```sh
curl -sf http://localhost:3000/vendor/bootstrap-theme.min.css | head -c 64
curl -sf http://localhost:3000/vendor/bc-sans.css | head -c 64
curl -sf http://localhost:3000/vendor/bc-gov-logo.svg | head -c 64
```

A `404` on any of these is a build-pipeline failure and must block the
release.
