# OpenShift Deployment - Implementation Plan

**Reference:** [bcgov/quickstart-openshift](https://github.com/bcgov/quickstart-openshift)  
**Created:** 2026-03-27  
**Status:** APPROVED — All decisions confirmed. Ready for implementation.

---

## Current State Summary

| Component | Current Approach |
|---|---|
| Backend | Python 3.12 / FastAPI / Uvicorn / SQLAlchemy / Alembic |
| Frontend | Python FastAPI serving static HTML/CSS/JS (no build step, no SPA framework) |
| Database | Plain `postgres:16-alpine` as a single-replica k8s Deployment |
| Container Image | Single monolithic Dockerfile for both backend and frontend |
| CI/CD | Monolithic `ci.yml` + basic `deploy-dev-openshift.yml` |
| Helm Chart | Flat `helm/transportation-forms/` with 7 template files, no sub-charts |
| Environments | Dev only |
| Registry | ghcr.io (single image) / OpenShift internal registry (commented out) |
| Security Scanning | Bandit + Safety (Python-specific) |
| Probes | Readiness + Liveness (no startup probe) |
| Autoscaling | None (single replica) |

---

## Technology Decisions Requiring Confirmation

> **IMPORTANT:** Each decision below must be confirmed before any implementation begins. Respond with APPROVED / REJECTED / MODIFIED for each.

### Decision 1: Frontend Architecture

**Options:**

| Option | Description | Pros | Cons |
|---|---|---|---|
| **A) Keep Python/Uvicorn** | Keep `frontend/app.py` serving static files via FastAPI. Add a WAF sidecar or reverse proxy separately. | No frontend rewrite. Simpler for small static sites. | Diverges from quickstart pattern. No native WAF integration. Extra sidecar complexity. |
| **B) Switch to Caddy + Coraza WAF** | Replace `frontend/app.py` with a Caddy-based container that serves static files with built-in OWASP Coraza WAF protection. | Matches quickstart standard. Built-in WAF (SQLi, XSS, path traversal protection). Better static file performance. | Requires building custom Caddy binary. Adds Caddyfile + coraza.conf config. Removes Python frontend entirely. |

**Recommendation:** Option **B** — the frontend is purely static files (`index.html`, `form_demo.html`, CSS, assets). Caddy serves static files more efficiently and the Coraza WAF integration is a security requirement per quickstart standards.

**Decision needed:** B (APPROVED)

---

### Decision 2: Database — Crunchy PostgreSQL vs. Standard PostgreSQL

**Options:**

| Option | Description | Pros | Cons |
|---|---|---|---|
| **A) Adopt Crunchy PostgreSQL** | Use `bcgov/action-crunchy` Helm chart with Patroni-based HA, automated backups, monitoring. | BCGov standard. HA with automatic failover. Scheduled backups. Monitoring. Self-healing. | More complex setup. Requires S3 bucket for backups. Heavier resource usage. |
| **B) Keep Standard PostgreSQL** | Continue using `postgres:16-alpine` but improve with resource limits, better probes, and manual backup strategy. | Simpler. Lighter resources. Familiar. | No HA. No automatic failover. No built-in backup. Does not match quickstart standard. |

**Recommendation:** Option **A** for TEST/PROD environments. Option **B** can remain for local development via docker-compose.

**Decision needed:** A (APPROVED)

---

### Decision 3: Database Migrations Strategy

**Options:**

| Option | Description |
|---|---|
| **A) Keep Alembic, move to init container** | Continue using Alembic (already working), but run migrations in a Kubernetes init container instead of in `entrypoint.sh`. Backend container starts only after migrations succeed. |
| **B) Keep Alembic, run as separate Job** | Run migrations as a Kubernetes Job before deployment. More complex but better isolation. |
| **C) Switch to Flyway** | Replace Alembic with Flyway. Would require rewriting all 10 migration files. |

**Recommendation:** Option **A** — Alembic with init container. The [NR-RFC-AlertAuthoring](https://github.com/bcgov/nr-rfc-alertauthoring) project (referenced by the quickstart as an alternative backend example) uses Python + FastAPI + Alembic, validating this approach within the BCGov ecosystem. Switching to Flyway provides no clear benefit for a Python stack and would require significant rework.

**Decision needed:** A (APPROVED)

---

### Decision 4: Container Image Strategy

**Options:**

| Option | Description |
|---|---|
| **A) Separate images per component** | Build `backend`, `frontend`, and `migrations` as 3 separate container images published to ghcr.io using `bcgov/action-builder-ghcr`. |
| **B) Keep single image** | Continue using one Dockerfile. Different containers use different entrypoint commands. |

**Recommendation:** Option **A** — matches quickstart pattern. Allows independent scaling, smaller image sizes, and smart build triggers (only rebuild what changed).

**Decision needed:** A (APPROVED)

---

### Decision 5: Container Registry

**Options:**

| Option | Description |
|---|---|
| **A) ghcr.io** | Publish to GitHub Container Registry (ghcr.io). OpenShift imports images from ghcr.io. Quickstart standard. |
| **B) OpenShift internal registry** | Push directly to OpenShift's internal image registry. Current deploy workflow has this commented out. |

**Recommendation:** Option **A** — ghcr.io is the quickstart standard. Images are versioned, publicly accessible for workflows, and independent of the cluster.

**Decision needed:** A (APPROVED)

---

### Decision 6: Security Scanning Toolchain

**Options:**

| Option | Description |
|---|---|
| **A) Add Trivy + CodeQL, keep Bandit/Safety** | Add Trivy vulnerability/secret/misconfig scanning and CodeQL SARIF reporting alongside existing Python-specific tools. |
| **B) Replace with Trivy + CodeQL only** | Drop Bandit/Safety in favor of Trivy + CodeQL exclusively. |
| **C) Keep current only** | Only Bandit + Safety. |
| **D) Add Trivy + CodeQL, drop Safety** | Keep Bandit, add Trivy + CodeQL and remove Safety. |

**Recommendation:** Option **D** — Trivy and CodeQL cover container/infrastructure-level scanning that Bandit/Safety don't address. The Python-specific tools still add value for source code analysis.

**Decision needed:** D (MODIFIED, APPROVED)

---

### Decision 7: Code Quality — SonarCloud

**Options:**

| Option | Description |
|---|---|
| **A) Adopt SonarCloud** | Set up SonarCloud project (monorepo with backend + frontend components). Requires requesting project from BCDevOps. |
| **B) Keep Codecov only** | Continue with current Codecov coverage reporting only. |

**Decision needed:** A (APPROVED)

---

### Decision 8: Penetration Testing — OWASP ZAP

**Options:**

| Option | Description |
|---|---|
| **A) Add ZAP scans** | Add OWASP ZAP full scans to scheduled workflow, targeting TEST environment. |
| **B) Skip for now** | Defer penetration testing. |

**Decision needed:** A (APPROVED)

---

### Decision 9: Monitoring — Prometheus Metrics

**Options:**

| Option | Description |
|---|---|
| **A) Add Prometheus metrics** | Add `/metrics` endpoint to backend (e.g. via `prometheus-fastapi-instrumentator`). |
| **B) Skip for now** | No metrics export initially. |

**Decision needed:** B (APPROVED)

---

### Decision 10: Dependency Management — Renovate

**Options:**

| Option | Description |
|---|---|
| **A) Adopt Renovate** | Add `renovate.json`, opt in with BCDevOps for automated dependency PRs. |
| **B) Manual updates** | Continue managing dependencies manually. |

**Decision needed:** A (APPROVED)

---

## Implementation Tasks

> Tasks below are ordered by dependency. Each phase must be completed before starting the next. Tasks within a phase can be parallelized where indicated.

---

### Phase 1: Repository & Workflow Foundation

These changes establish the PR-based workflow structure and can proceed regardless of most technology decisions.

#### Task 1.1: Create GitHub Environments
- [ ] Create `test` environment in GitHub repo settings (Settings → Environments → New environment)
- [ ] Create `prod` environment in GitHub repo settings
- [ ] Configure `prod` with required reviewers (manual approval gate)
- [ ] Set up per-environment secrets:
  - Repository-level: `vars.OC_SERVER`, `secrets.OC_NAMESPACE` (DEV), `secrets.OC_TOKEN` (DEV)
  - `test` environment: `secrets.OC_NAMESPACE` (TEST), `secrets.OC_TOKEN` (TEST)
  - `prod` environment: `secrets.OC_NAMESPACE` (PROD), `secrets.OC_TOKEN` (PROD)

#### Task 1.2: Rename Default Branch (if applicable)
- [ ] Confirm whether to rename `master` → `main` to match quickstart convention
- [ ] If yes, update all workflow triggers and branch references

#### Task 1.3: Add PR Validation Workflow
- [ ] Create `.github/workflows/pr-validate.yml`
- [ ] Use `bcgov/quickstart-openshift-helpers/.github/workflows/.pr-validate.yml`
- [ ] Enforce conventional commit format in PR titles
- [ ] Add markdown links to PR environments (frontend + backend URLs)

#### Task 1.4: Add Renovate Configuration
- [ ] Create `renovate.json` extending `bcgov/renovate-config`
- [ ] Submit opt-in request to BCDevOps via GitHub issue

---

### Phase 2: Container Image Restructuring

**Depends on:** Decision 1 (Frontend), Decision 4 (Image Strategy)

#### Task 2.1: Create Backend Dockerfile
- [ ] Create `backend/Dockerfile` — multi-stage build:
  - Stage 1 (`build`): Install dependencies, copy source
  - Stage 2 (`runtime`): Minimal Python base image, copy only needed artifacts
- [ ] Add `backend/.dockerignore`
- [ ] Ensure non-root user (UID 1001, GID 0 for OpenShift compatibility)
- [ ] Set `HEALTHCHECK` for Docker/Trivy compliance
- [ ] Backend listens on port 3000 (quickstart standard) or 8000 (current) — **confirm port**

#### Task 2.2: Create Frontend Dockerfile (Caddy + Coraza WAF)
- [ ] Create `frontend/Dockerfile` — multi-stage build:
  - Stage 1: Copy static files
  - Stage 2: Build custom Caddy binary with Coraza WAF plugin
  - Stage 3: Alpine runtime with custom Caddy, static files, Caddyfile, coraza.conf
- [ ] Create `frontend/Caddyfile` — configure:
  - Serve static files from `/srv`
  - Reverse proxy `/api/*` to backend service
  - TLS off (handled by OpenShift route)
  - Health endpoint on separate port (3001)
- [ ] Create `frontend/coraza.conf` — OWASP Coraza WAF rules
- [ ] Create `frontend/.dockerignore`
- [ ] Ensure OpenShift-compatible file permissions (UID 1001, GID 0)

#### Task 2.3: Create Migrations Dockerfile
- [ ] Create `migrations/Dockerfile` — minimal Python image with Alembic + psycopg2 only
- [ ] Copy `alembic/` directory and `alembic.ini`
- [ ] Entrypoint: `alembic upgrade head`
- [ ] Create `migrations/.dockerignore`

#### Task 2.4: Update Root Docker Compose
- [ ] Update `docker-compose.yml` to build from individual Dockerfiles (`backend/Dockerfile`, `frontend/Dockerfile`)
- [ ] Add migrations service that runs before backend

#### Task 2.5: Remove Monolithic Dockerfile
- [ ] Delete or rename root `Dockerfile` after new per-component Dockerfiles are verified

---

### Phase 3: Helm Chart Restructuring

**Depends on:** Decision 2 (Database), Phase 2 (Dockerfiles)

#### Task 3.1: Restructure Helm Chart Directory
- [ ] Move chart from `helm/transportation-forms/` to `charts/app/`
- [ ] Create subdirectory structure:
  ```
  charts/
    app/
      Chart.yaml
      values.yaml
      values-test.yaml     (new)
      values-prod.yaml     (new)
      templates/
        _helpers.tpl       (new — shared template helpers)
        knp.yaml           (new — network policies)
        secret.yaml        (new — managed secrets template)
        backend/
          templates/
            deployment.yaml
            service.yaml
        frontend/
          templates/
            deployment.yaml
            service.yaml
    crunchy/
      values.yml
      values-test.yml
      values-prod.yml
  ```

#### Task 3.2: Create `_helpers.tpl`
- [ ] Define common template helpers:
  - `fullname`, `labels`, `selectorLabels`, `chart`, `name`
  - Use `global.repository`, `global.tag`, `global.registry` pattern from quickstart

#### Task 3.3: Rewrite Backend Deployment Template
- [ ] Use `global.registry`/`global.repository`/`global.tag` for image references
- [ ] Add `deploymentStrategy` support (Recreate for DEV, RollingUpdate for PROD)
- [ ] Add resource requests/limits
- [ ] Add startup probe alongside readiness and liveness probes
- [ ] Add pod affinity/anti-affinity rules
- [ ] Add HPA template (enabled via values for TEST/PROD)
- [ ] Add PDB template (enabled via values for PROD)
- [ ] Remove hardcoded namespace — let Helm `--namespace` handle it

#### Task 3.4: Rewrite Frontend Deployment Template
- [ ] Same patterns as Task 3.3 (strategy, resources, probes, HPA, PDB)
- [ ] Configure appropriate container port based on Decision 1

#### Task 3.5: Add OpenShift Route Templates
- [ ] Create route template for frontend with:
  - TLS edge termination
  - HAProxy rate-limiting annotations
  - Cookie-based session affinity off
- [ ] Create route template for backend API (if exposed directly)
- [ ] Parameterize domain in values (`apps.silver.devops.gov.bc.ca` or `apps.gold.devops.gov.bc.ca`)

#### Task 3.6: Add Network Policy Template
- [ ] Create `knp.yaml` allowing:
  - Frontend → Backend traffic
  - Backend → Database traffic
  - Ingress → Frontend traffic
  - Deny all other inter-pod traffic by default

#### Task 3.7: Add Secrets Template
- [ ] Create `secret.yaml` managed by Helm
- [ ] Add `global.secrets.persist` toggle (false for PR envs, true for long-lived envs)
- [ ] Migrate secrets from manual `k8s/secrets.yaml` to Helm-managed secret

#### Task 3.8: Create Environment-Specific Values Files
- [ ] `values.yaml` — base/DEV defaults
- [ ] `values-test.yaml` — TEST overrides (autoscaling enabled, 2+ replicas)
- [ ] `values-prod.yaml` — PROD overrides (autoscaling enabled, 3+ replicas, RollingUpdate, PDB enabled)

#### Task 3.9: Add Crunchy PostgreSQL Chart
- [ ] Create `charts/crunchy/values.yml` — base configuration
- [ ] Create `charts/crunchy/values-test.yml` — TEST (2 replicas)
- [ ] Create `charts/crunchy/values-prod.yml` — PROD (3+ replicas, S3 backup config)
- [ ] Configure connection to use `pgbouncer` user for deployed environments

#### Task 3.10: Database Migration Handling (Alembic Init Container)
- [ ] Add init container to backend deployment that runs `alembic upgrade head` using the migrations image
- [ ] Remove migration logic from `entrypoint.sh`
- [ ] Update `entrypoint.sh` to only start Uvicorn (no migrations, no seeding in production)

#### Task 3.11: Clean Up Old k8s Manifests
- [ ] Archive or remove `k8s/` directory (replaced by Helm chart)
- [ ] Archive or remove `build-deploy.ps1` (replaced by Helm-based deployment workflows)

---

### Phase 4: CI/CD Workflow Implementation

**Depends on:** Phase 2 (Dockerfiles), Phase 3 (Helm chart)

#### Task 4.1: Create Reusable Deployer Workflow
- [ ] Create `.github/workflows/.deployer.yml`
- [ ] Accept inputs: `environment`, `tag`, `params`, `triggers`, `db_triggers`, `db_user`
- [ ] Use `bcgov/action-oc-runner` for Helm deploy via `oc` CLI
- [ ] Use `bcgov/action-crunchy` for Crunchy PostgreSQL database deployment
- [ ] Support `helm package` → `helm upgrade --install` pattern
- [ ] Output: `tag`, `triggered`

#### Task 4.2: Create Reusable Tests Workflow
- [ ] Create `.github/workflows/.tests.yml`
- [ ] Accept `target` input (PR number, test, or prod)
- [ ] Include integration tests (curl health checks)
- [ ] Include load tests if k6 test files are created

#### Task 4.3: Create PR Open Workflow
- [ ] Create `.github/workflows/pr-open.yml`
- [ ] Trigger: `pull_request` (opened, reopened, synchronize, ready_for_review)
- [ ] Concurrency: group by PR number, cancel in-progress
- [ ] Jobs:
  1. **Builds** — matrix build for `[backend, frontend, migrations]` using `bcgov/action-builder-ghcr`, tag with PR number
  2. **Deploys** — call `.deployer.yml` with PR-specific namespace, `secrets.persist=false`
  3. **Tests** — call `.tests.yml` (only if deploy was triggered)
  4. **Results** — aggregate pass/fail

#### Task 4.4: Create PR Close Workflow
- [ ] Create `.github/workflows/pr-close.yml`
- [ ] Trigger: `pull_request` types `[closed]`
- [ ] Use `bcgov/quickstart-openshift-helpers/.github/workflows/.pr-close.yml`
- [ ] Clean up Helm releases and OpenShift objects for the PR
- [ ] On merge: retag successful PR images as `latest`
- [ ] Packages list: `backend frontend migrations`
- [ ] Clean up Crunchy PR database user via `bcgov/action-crunchy`

#### Task 4.5: Create Merge Workflow
- [ ] Create `.github/workflows/merge.yml`
- [ ] Trigger: `push` to `main` (or `master`)
- [ ] Jobs:
  1. **Deploy TEST** — call `.deployer.yml` with `environment: test`
  2. **Tests** — run tests against TEST deployment
  3. **Deploy PROD** — call `.deployer.yml` with `environment: prod`, `RollingUpdate` strategy, autoscaling enabled, PDB enabled
  4. **Promote** — retag images as `prod`

#### Task 4.6: Refactor Analysis Workflow
- [ ] Rename/refactor `ci.yml` → `.github/workflows/analysis.yml`
- [ ] Trigger: `pull_request` + `push` to main + weekly schedule
- [ ] Jobs:
  1. **Backend Tests** — Python tests with pytest + coverage (keep existing logic)
  2. **Frontend Tests** — if applicable (currently static HTML, may be limited)
  3. **Trivy** — vulnerability, secret, misconfig scanning with SARIF upload
  4. **Results** — aggregate gate
- [ ] Keep Bandit as part of backend tests; remove Safety (Decision 6 = D)
- [ ] Add SonarCloud integration
- [ ] Remove Docker build job from this workflow (moved to PR Open)

#### Task 4.7: Create Scheduled Workflow
- [ ] Create `.github/workflows/scheduled.yml`
- [ ] Cron: weekly (e.g., Saturday 3 AM PST)
- [ ] Jobs:
  1. **PR Purge** — clean up stale PR Helm releases older than 1 week
  2. **SchemaSpy** — generate DB documentation to GitHub Pages (optional)
  3. **ZAP Scans** — OWASP ZAP full scans against TEST environment

#### Task 4.8: Create Demo Route Workflow (optional)
- [ ] Create `.github/workflows/demo.yml`
- [ ] Assign long-lived demo route to a specific PR via `demo` label

#### Task 4.9: Remove Old Workflows
- [ ] Remove `deploy-dev-openshift.yml` (replaced by PR Open + Merge workflows)
- [ ] Remove or rename `ci.yml` (replaced by `analysis.yml`)

---

### Phase 5: Security Hardening

**Depends on:** Phase 2 (Dockerfiles)

#### Task 5.1: Container Security — Backend
- [ ] Multi-stage Dockerfile with minimal runtime image
- [ ] Run as non-root (UID 1001 in root group for OpenShift)
- [ ] No `--reload` flag in production entrypoint
- [ ] Strip unnecessary packages from runtime stage

#### Task 5.2: Container Security — Frontend (Caddy + Coraza WAF)
- [ ] Coraza WAF rules in `frontend/coraza.conf`
- [ ] OpenShift-compatible permissions (`chown 1001:0`, `chmod 755`)
- [ ] High ports only (3000/3001) — no privilege escalation
- [ ] Strip file capabilities from Caddy binary

#### Task 5.3: Add Trivy Scanning
- [ ] Add Trivy step to `analysis.yml`
- [ ] Configure: `vuln,secret,misconfig` scanners, `CRITICAL,HIGH` severity
- [ ] Upload SARIF to GitHub Security tab
- [ ] Create `.trivyignore` for known false positives if needed
- [ ] Create `.github/trivy.yaml` for custom Trivy config

#### Task 5.4: Add CodeQL Scanning
- [ ] Enable CodeQL via GitHub default code scanning OR add explicit workflow
- [ ] Configure for Python language

#### Task 5.5: Branch Protection Rules
- [ ] Create ruleset for `main` (or `master`):
  - Require PR before merging
  - Require 1+ approval
  - Require conversation resolution
  - Require status checks: `Analysis Results`, `PR Results`, `Validate Results`
  - Require code scanning results: `Trivy` (if adopted)
  - Block force pushes
  - Restrict deletions
  - Require linear history

---

### Phase 6: Operational Readiness

**Depends on:** Phase 3 (Helm), Phase 4 (Workflows)

#### Task 6.1: Resource Tuning
- [ ] Define CPU/memory requests and limits in values.yaml for:
  - Backend: requests `50m CPU / 128Mi`, limits `250m CPU / 512Mi` (tune based on load)
  - Frontend: requests `25m CPU / 64Mi`, limits `100m CPU / 256Mi`
- [ ] Verify resource allocation does not exceed namespace quotas

#### Task 6.2: Autoscaling Configuration
- [ ] Add HPA templates to Helm chart
- [ ] DEV: disabled (1 replica)
- [ ] TEST: enabled (min 2, max 5)
- [ ] PROD: enabled (min 3, max 7, target 80% CPU)

#### Task 6.3: Pod Disruption Budgets
- [ ] Add PDB templates to Helm chart
- [ ] PROD only: `minAvailable: 1` for both backend and frontend

#### Task 6.4: Rolling Update Strategy
- [ ] DEV/TEST: `Recreate` (faster, acceptable downtime)
- [ ] PROD: `RollingUpdate` with `maxSurge: 1`, `maxUnavailable: 0` (zero-downtime)

#### Task 6.5: Startup Probes
- [ ] Add startup probes to backend deployment:
  - `httpGet /health`, `failureThreshold: 30`, `periodSeconds: 2`
  - Allows up to 60s for initial startup (Alembic migrations, cold start)
- [ ] Add startup probes to frontend deployment

#### Task 6.6: SchemaSpy Setup (optional)
- [ ] Configure SchemaSpy in scheduled workflow
- [ ] Enable GitHub Pages on `gh-pages` branch

---

### Phase 7: Testing & Validation

#### Task 7.1: Local Validation
- [ ] Build all container images locally with `docker compose`
- [ ] Verify backend starts and passes health check
- [ ] Verify frontend serves static files correctly
- [ ] Verify migrations run successfully in init container
- [ ] Verify database connectivity

#### Task 7.2: Helm Chart Validation
- [ ] Run `helm lint charts/app/`
- [ ] Run `helm template` and verify generated manifests
- [ ] Verify values-test.yaml and values-prod.yaml overrides render correctly

#### Task 7.3: CI/CD Pipeline Validation
- [ ] Open a test PR and verify:
  - PR Validate workflow runs and checks PR title
  - Analysis workflow runs (lint, test, security scan)
  - PR Open workflow builds images and deploys to DEV
  - Tests run against PR deployment
- [ ] Merge test PR and verify:
  - PR Close cleans up PR environment
  - Merge workflow deploys to TEST, runs tests, deploys to PROD
  - Images are tagged as `prod`

#### Task 7.4: Disaster Recovery Test (Crunchy PostgreSQL)
- [ ] Test Crunchy PostgreSQL failover
- [ ] Test backup/restore from S3
- [ ] Document DR procedure

---

## Files to Create / Modify / Delete

### New Files
| File | Phase | Purpose |
|---|---|---|
| `backend/Dockerfile` | 2 | Backend-specific multi-stage Dockerfile |
| `backend/.dockerignore` | 2 | Exclude unnecessary files from backend image |
| `frontend/Dockerfile` | 2 | Frontend Caddy + Coraza WAF Dockerfile |
| `frontend/.dockerignore` | 2 | Exclude unnecessary files from frontend image |
| `frontend/Caddyfile` | 2 | Caddy server config |
| `frontend/coraza.conf` | 2 | Coraza WAF rules |
| `migrations/Dockerfile` | 2 | Migrations image with Alembic |
| `migrations/.dockerignore` | 2 | Exclude unnecessary files from migrations image |
| `charts/app/Chart.yaml` | 3 | Helm chart metadata |
| `charts/app/values.yaml` | 3 | Base/DEV values |
| `charts/app/values-test.yaml` | 3 | TEST overrides |
| `charts/app/values-prod.yaml` | 3 | PROD overrides |
| `charts/app/templates/_helpers.tpl` | 3 | Shared template helpers |
| `charts/app/templates/knp.yaml` | 3 | Network policies |
| `charts/app/templates/secret.yaml` | 3 | Helm-managed secrets |
| `charts/app/templates/backend/templates/deployment.yaml` | 3 | Backend deployment |
| `charts/app/templates/backend/templates/service.yaml` | 3 | Backend service |
| `charts/app/templates/frontend/templates/deployment.yaml` | 3 | Frontend deployment |
| `charts/app/templates/frontend/templates/service.yaml` | 3 | Frontend service |
| `charts/crunchy/values.yml` | 3 | Crunchy base config |
| `charts/crunchy/values-test.yml` | 3 | Crunchy TEST config |
| `charts/crunchy/values-prod.yml` | 3 | Crunchy PROD config |
| `.github/workflows/.deployer.yml` | 4 | Reusable Helm deploy workflow |
| `.github/workflows/.tests.yml` | 4 | Reusable test workflow |
| `.github/workflows/pr-open.yml` | 4 | PR build + deploy |
| `.github/workflows/pr-close.yml` | 4 | PR cleanup + image promotion |
| `.github/workflows/pr-validate.yml` | 4 | PR title + description validation |
| `.github/workflows/merge.yml` | 4 | TEST + PROD deployment |
| `.github/workflows/analysis.yml` | 4 | Tests + security scanning |
| `.github/workflows/scheduled.yml` | 4 | Cleanup + recurring scans |
| `.trivyignore` | 5 | Trivy false positive exclusions |
| `renovate.json` | 1 | Renovate config |

### Modified Files
| File | Phase | Change |
|---|---|---|
| `docker-compose.yml` | 2 | Update to use per-component Dockerfiles |
| `entrypoint.sh` | 3 | Remove migration and seed logic; backend startup only |

### Deleted / Archived Files
| File | Phase | Reason |
|---|---|---|
| `Dockerfile` (root) | 2 | Replaced by per-component Dockerfiles |
| `k8s/*.yaml` | 3 | Replaced by Helm chart templates |
| `build-deploy.ps1` | 3 | Replaced by Helm-based CI/CD workflows |
| `helm/transportation-forms/` | 3 | Replaced by `charts/app/` |
| `.github/workflows/ci.yml` | 4 | Replaced by `analysis.yml` |
| `.github/workflows/deploy-dev-openshift.yml` | 4 | Replaced by `pr-open.yml` + `merge.yml` |

---

## Implementation Order Summary

```
Phase 1: Repository & Workflow Foundation          (no code dependencies)
   ↓
Phase 2: Container Image Restructuring             (depends on Decisions 1, 4)
   ↓
Phase 3: Helm Chart Restructuring                  (depends on Phase 2, Decision 2)
   ↓
Phase 4: CI/CD Workflow Implementation             (depends on Phases 2 + 3)
   ↓
Phase 5: Security Hardening                        (depends on Phase 2)
   ↓
Phase 6: Operational Readiness                     (depends on Phases 3 + 4)
   ↓
Phase 7: Testing & Validation                      (depends on all above)
```

---

## Decisions Checklist

| # | Decision | Approved | Choice |
|---|---|---|---|
| 1 | Frontend Architecture | ✅ | **B** — Caddy + Coraza WAF |
| 2 | Database | ✅ | **A** — Crunchy PostgreSQL (HA) |
| 3 | Migrations | ✅ | **A** — Alembic init container |
| 4 | Container Images | ✅ | **A** — Separate per component |
| 5 | Container Registry | ✅ | **A** — ghcr.io |
| 6 | Security Scanning | ✅ | **D** — Bandit + Trivy + CodeQL, drop Safety |
| 7 | Code Quality | ✅ | **A** — SonarCloud |
| 8 | Penetration Testing | ✅ | **A** — OWASP ZAP |
| 9 | Monitoring | ✅ | **B** — Skip Prometheus (for now) |
| 10 | Dependency Management | ✅ | **A** — Renovate |
