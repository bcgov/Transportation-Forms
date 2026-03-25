# Transportation Forms

## DEV CD Deployment (OpenShift + Helm)

This repository includes a DEV-only GitHub Actions deployment workflow at `.github/workflows/deploy-dev-openshift.yml`.
On each push to `master`, it builds a container image, pushes it to the OpenShift internal registry, then deploys with Helm using `helm/transportation-forms`.

### Required GitHub Secrets

Set these repository secrets before enabling deployment:

- `OPENSHIFT_SERVER` - OpenShift API URL (for example: `https://api.<cluster-domain>:6443`)
- `OPENSHIFT_TOKEN` - Service account or user token with deploy permissions in DEV namespace
- `OPENSHIFT_DEV_NAMESPACE` - Target DEV project/namespace name

### Deploy Trigger Behavior

- Automatic deploy: push to `master`
- Manual deploy: Actions -> **Deploy DEV OpenShift** -> **Run workflow**
	- Optional input: `image_tag` (if omitted, workflow uses `shortsha-timestamp`)

The workflow includes an optional CI gate that waits for the existing `CI/CD Pipeline` workflow to complete successfully for the same commit before deploying.

### Manual Dispatch Notes

When running manually, leave `image_tag` empty to auto-generate one, or provide a deterministic tag to redeploy a known image name/version.

### Verify Deployment in OpenShift

After a successful run, verify rollout in DEV:

```bash
oc project <OPENSHIFT_DEV_NAMESPACE>
oc get pods
oc rollout status deployment/app
oc rollout status deployment/frontend
helm list -n <OPENSHIFT_DEV_NAMESPACE>
```

The workflow summary also prints namespace, image, Helm release, and rollout status.
