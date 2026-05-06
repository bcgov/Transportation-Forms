---
description: "Use when editing Taskfile, Helm local values, Ingress, Crunchy overrides, or any local deployment files under infra/local/. Covers Taskfile conventions, local Helm patterns, and k3s compatibility."
applyTo: "infra/local/**"
---

# Local Deployment File Guidelines

## Taskfile conventions (infra/local/Taskfile.yml)
- Keep tasks simple and composable — each task does one thing
- Use `deps` and `sources` for dependency ordering
- Read environment from dotenv (`../../.env`), not hardcoded values
- Do not duplicate logic that exists in Helm values or Dockerfiles
- Preserve the orchestration pattern: `all` → `setup:pgo` → `build` + `deploy:db` → `deploy`
- Variables: `TAG=local`, `RELEASE_NAME=transportation-forms-local`, `CHART=infra/charts/app`

## Helm local values (infra/charts/app/values-local.yaml)
- Only modify `values-local.yaml` — never touch base `values.yaml` or environment overlays
- Disable OpenShift-only features (Routes, NetworkPolicy) via values — do not remove them from templates
- Keep resource requests minimal but non-zero
- Ensure keys mirror the structure in `values.yaml`

## Ingress (infra/local/ingress.yaml)
- Replaces OpenShift Routes for k3s — do not add OpenShift-specific annotations
- Service names must match Helm release: `transportation-forms-local-app-{component}`
- SSL redirect disabled for local dev

## Crunchy overrides (infra/local/crunchy-overrides.yaml)
- Use `storageClassName: local-path` (k3s default), not `netapp-block-standard`
- Do not change user/database names — must match OpenShift Crunchy config

## Post-renderer (infra/local/patch-openshift.sh)
- Must remain a simple `sed` replacement (`openshift: true` → `openshift: false`)
- Must be executable (`chmod +x`)
- Do not add complex logic — keep it a single-purpose filter
