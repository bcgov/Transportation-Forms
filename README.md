# Transportation Forms

BC Transportation Forms — FastAPI backend, Caddy + Coraza WAF frontend, Crunchy PostgreSQL HA.

## Architecture

| Component | Technology |
|---|---|
| **Backend** | Python 3.12 / FastAPI / Uvicorn / SQLAlchemy / Alembic |
| **Frontend** | Caddy 2 + Coraza WAF serving static HTML/CSS/JS |
| **Database** | Crunchy PostgreSQL HA (TEST/PROD) · plain `postgres:16-alpine` (local dev) |
| **Migrations** | Alembic via Kubernetes init container |
| **Registry** | ghcr.io — separate images: `backend`, `frontend`, `migrations` |

## CI/CD Workflows

| Workflow | Trigger | Purpose |
|---|---|---|
| `analysis.yml` | PR + push to `master` + weekly | Lint, pytest (80% coverage), Bandit, Trivy, CodeQL, SonarCloud |
| `pr-validate.yml` | PR open / edit | Enforce conventional commit format in PR titles |
| `pr-open.yml` | PR opened / updated | Build images, deploy PR env to DEV, integration tests |
| `pr-close.yml` | PR closed | Clean up PR env, promote images to `latest` on merge |
| `merge.yml` | Push to `master` | Deploy TEST → integration tests → Deploy PROD (manual approval) |
| `scheduled.yml` | Weekly (Saturday 03:00 UTC) | Stale PR purge, SchemaSpy, OWASP ZAP scans |
| `demo.yml` | PR label `demo` | Assign long-lived demo route to a PR |

## Required GitHub Configuration

### Repository-Level

| Type | Name | Description |
|---|---|---|
| Variable | `OC_SERVER` | OpenShift API URL |
| Variable | `OC_NAMESPACE` | DEV namespace |
| Variable | `TARGET_ENV_DOMAIN` | Route domain (e.g. `apps.silver.devops.gov.bc.ca`) |
| Secret | `OC_TOKEN` | DEV service account token |
| Secret | `DATABASE_URL` | DEV PostgreSQL connection string |
| Secret | `SECRET_KEY` | JWT signing secret |
| Secret | `S3_ENDPOINT_URL` | S3-compatible endpoint URL |
| Secret | `S3_ACCESS_KEY` | S3-compatible access key |
| Secret | `S3_SECRET_KEY` | S3-compatible secret key |
| Secret | `S3_BUCKET` | S3-compatible bucket name |
| Secret | `KEYCLOAK_SERVER_URL` | Keycloak base URL |
| Secret | `KEYCLOAK_REALM` | Keycloak realm |
| Secret | `KEYCLOAK_CLIENT_ID` | Keycloak client ID |
| Secret | `KEYCLOAK_CLIENT_SECRET` | Keycloak client secret |
| Secret | `KEYCLOAK_REDIRECT_URI` | OAuth2 redirect URI |

### GitHub Environments

- **`test`** — `OC_TOKEN_TEST`, `OC_NAMESPACE` (test), all application secrets suffixed `_TEST`
- **`prod`** — same as test but suffixed `_PROD`, with required reviewers for manual approval

## Local Development

```bash
# Start all services (migrations → backend → frontend + db + minio)
docker compose up -d

# Backend logs
docker compose logs -f app

# Frontend logs (Caddy)
docker compose logs -f frontend

# Stop everything
docker compose down
```

- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8000
- **API docs:** http://localhost:8000/api/v1/docs
- **MinIO console (local dev only):** http://localhost:9001

## Helm Chart

```bash
# Lint
helm lint charts/app

# Dry-run render (DEV defaults)
helm template transportation-forms charts/app

# Render with TEST values
helm template transportation-forms charts/app -f charts/app/values.yaml -f charts/app/values-test.yaml

# Deploy (CI/CD does this automatically)
helm upgrade --install transportation-forms-dev charts/app --namespace <ns>
```

## Verify Deployment in OpenShift

```bash
oc project <namespace>
oc get pods
helm list -n <namespace>
```
