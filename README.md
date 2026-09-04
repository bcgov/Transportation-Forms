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
| `dev.yml` | Push to `master` | Conditionally build changed images and deploy DEV |
| `tst.yml` | Push tag matching `v*-rc.*` | Promote DEV-validated image digests to TST |
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
| Secret | `SECRET_KEY` | Application secret key |
| Secret | `JWT_PRIVATE_KEY_PEM` | Application JWT RS256 private key PEM |
| Secret | `JWT_PUBLIC_KEY_PEM` | Matching application JWT RS256 public key PEM |
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

- **`test`** — `OC_NAMESPACE`, `OC_SERVER`, and the application secrets listed above using the same names, scoped to TST values
- **`prod`** — same as test but suffixed `_PROD`, with required reviewers for manual approval

## DEV-to-TST Promotion

TST deployments are immutable promotions. The `tst.yml` workflow does not
build or retag images. It resolves `backend`, `migrations`, `frontend`,
`public-backend`, and `public-frontend` to OCI digests associated with the
release-candidate commit.

### One-Time Setup

After merging the consolidated builder change, run `Deploy to DEV` manually on
that commit with `force_build_all=true`. This establishes the OCI revision
labels required by `bcgov/actions/image-tracker@v0.5.0`; images produced only by
the previous `v4.2.1` builder may not contain those labels.

The GitHub `test` environment must contain `OC_NAMESPACE`, `OC_SERVER`, and all
application secrets listed under Repository-Level. Set the repository variable
`TARGET_ENV_DOMAIN` when the Silver default
`apps.silver.devops.gov.bc.ca` is not appropriate.

### Release Procedure

1. Merge the intended release commit to `master`.
2. Wait for `dev.yml` to complete successfully for that exact commit SHA.
3. Create and push an RC tag on that same commit:

```bash
git tag vX.Y.Z-rc.N <commit-sha>
git push origin vX.Y.Z-rc.N
```

Lightweight and annotated tags are supported. The workflow resolves the tag to
its commit and requires an exact successful `dev.yml` run before deployment.

Before `tst.yml` exists on `master`, test the complete workflow from its feature
branch with an explicit test tag:

```bash
git tag test-tst-<name>
git push origin test-tst-<name>
```

This runs the workflow and Helm chart from the tagged feature-branch commit,
but deploys the five immutable images from the latest successful `master` DEV
run. Delete the test tag after validation. Normal RC tags and manual dispatches
still require the selected commit to have an exact successful DEV run.

### Failure, Retry, and Rollback

- Missing DEV run: run or rerun `dev.yml` for the tagged commit. Do not move the tag.
- Unresolved package: confirm the one-time forced DEV rebuild completed for all five packages.
- Deployment failure: fix the environment or chart issue, then rerun the failed jobs for the same tag.
- New candidate: create the next `vX.Y.Z-rc.N` tag on a commit with a successful exact-SHA DEV run.

```bash
helm history transportation-forms-test -n <test-namespace>
helm rollback transportation-forms-test <revision> -n <test-namespace> --wait
```

Production release automation is deferred.

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
helm lint infra/charts/app

# Dry-run render (DEV defaults)
helm template transportation-forms infra/charts/app

# Render with TEST values
helm template transportation-forms infra/charts/app -f infra/charts/app/values.yaml -f infra/charts/app/values-test.yaml

# Deploy (CI/CD does this automatically)
helm upgrade --install transportation-forms-dev infra/charts/app --namespace <ns>
```

## Verify Deployment in OpenShift

```bash
oc project <namespace>
oc get pods
helm list -n <namespace>
```
