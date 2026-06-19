# Backend CI/CD Setup Guide

This document covers the one-time manual steps required to activate the
`.github/workflows/deploy-backend.yml` pipeline. None of this can be automated
because it involves creating GCP credentials and configuring GitHub secrets,
both of which require human interaction in the respective consoles.

---

## What the pipeline does

On every push to `main` (and on manual trigger via Actions → Run workflow):

1. Checks out the repo.
2. Authenticates to GCP using a Service Account key stored as a GitHub secret.
3. Installs Python 3.11 + `requirements.txt` on the runner.
4. Runs `python manage.py migrate --noinput` against the production Neon database
   directly from the GitHub Actions runner. Migrations run **before** the new
   Cloud Run revision is deployed, so the schema is always ahead of the code.
5. Calls `gcloud run deploy --source .`, which triggers a Cloud Build job that
   builds the Dockerfile and rolls a new Cloud Run revision. Existing Cloud Run
   environment variables are **not touched** by this command.

---

## Step 1 — Create the deploy Service Account

In the [GCP Console → IAM & Admin → Service Accounts](https://console.cloud.google.com/iam-admin/serviceaccounts):

1. Click **Create Service Account**.
2. Name: `github-deploy` (or similar), ID: `github-deploy`.
3. Click **Create and Continue**.
4. Grant the following roles (all required):

   | Role | Why |
   |------|-----|
   | `roles/run.admin` | Deploy and manage Cloud Run services |
   | `roles/cloudbuild.builds.editor` | Submit and manage Cloud Build jobs triggered by `--source .` |
   | `roles/iam.serviceAccountUser` | Allow Cloud Build to act as the Cloud Run service's runtime SA |
   | `roles/artifactregistry.writer` | Push built container images to Artifact Registry (used by Cloud Build internally) |

   > If your project still uses Container Registry (gcr.io) instead of Artifact Registry,
   > substitute `roles/storage.admin` for `roles/artifactregistry.writer`.

5. Click **Done**.

---

## Step 2 — Create a JSON key for the Service Account

1. In the Service Accounts list, click on `github-deploy`.
2. Go to the **Keys** tab → **Add Key** → **Create new key** → **JSON**.
3. Download the key file. Keep it safe — treat it like a password.
4. You will paste the entire contents of this JSON file into a GitHub secret (next step).

---

## Step 3 — Add GitHub Secrets

In the GitHub repo (`Nard248/JokesForBackEnd`) → **Settings → Secrets and variables → Actions → New repository secret**, add:

| Secret name | Value |
|-------------|-------|
| `GCP_SA_KEY` | The full JSON content of the key file from Step 2 |
| `GCP_PROJECT` | `332865216810` (GCP project number) or the project ID string |
| `DATABASE_URL` | The Neon connection string (same value as in your `.env` / Cloud Run env) |

These three secrets are the only additions needed. All other environment variables
(`SECRET_KEY`, `RESEND_API_KEY`, `ALLOWED_HOSTS`, etc.) stay where they are —
configured on the Cloud Run service via the GCP console — and the workflow never
overwrites them.

---

## Step 4 — Verify the first run

1. Push any change to `main` (or trigger manually via Actions → Deploy Backend to Cloud Run → Run workflow).
2. Watch the job log. The **Run database migrations** step should show Django printing applied migrations (or "No migrations to apply.").
3. The **Deploy to Cloud Run** step will print a Cloud Build log URL and end with a service URL. Confirm traffic is routing to the new revision in Cloud Run → Revisions.

---

## Frontend deploy ordering

The frontend (Firebase via its own GH Actions workflow) can deploy at any time —
it is a static SPA. However, note that recent backend changes introduced
`date_of_birth` as a required registration field. If the frontend and backend
deploy out of order:

- **Frontend before backend**: registration calls will fail (new field sent to old endpoint that doesn't accept it).
- **Backend before frontend**: registration calls will fail (old form doesn't send the new required field).

**Safe approach**: deploy both together in the same release, or deploy the backend first and keep the frontend pointed at the old build until it is ready.

---

## Upgrading to Workload Identity Federation (recommended)

The current setup uses a long-lived JSON key. Workload Identity Federation (WIF)
is more secure because it issues short-lived tokens and requires no key files.

1. In GCP Console → IAM & Admin → **Workload Identity Federation** → Create a Pool.
   - Name: `github-actions-pool`
   - Provider: OIDC, issuer `https://token.actions.githubusercontent.com`
2. Add an attribute mapping:
   - `google.subject` → `assertion.sub`
   - `attribute.repository` → `assertion.repository`
3. Grant the `github-deploy` service account the role `roles/iam.workloadIdentityUser`
   scoped to the pool, bound to the repo principal:
   ```
   principalSet://iam.googleapis.com/projects/332865216810/locations/global/workloadIdentityPools/<pool-id>/attribute.repository/Nard248/JokesForBackEnd
   ```
4. In `.github/workflows/deploy-backend.yml`, replace the `credentials_json` auth step with:
   ```yaml
   - name: Authenticate to Google Cloud
     uses: google-github-actions/auth@v2
     with:
       workload_identity_provider: 'projects/332865216810/locations/global/workloadIdentityPools/<pool-id>/providers/<provider-id>'
       service_account: 'github-deploy@<project-id>.iam.gserviceaccount.com'
   ```
   Also add `permissions: { id-token: write, contents: read }` at the job level.
5. Delete the `GCP_SA_KEY` secret from GitHub — it is no longer needed.

---

## Rollback

Cloud Run keeps previous revisions. To roll back immediately:

```bash
# List revisions
gcloud run revisions list --service jokesforbackend --region us-east1

# Route 100% traffic to a previous revision
gcloud run services update-traffic jokesforbackend \
  --region us-east1 \
  --to-revisions <previous-revision-name>=100
```

Note: rolling back the code does **not** roll back database migrations. If a
migration was destructive, a separate database restore is required.
