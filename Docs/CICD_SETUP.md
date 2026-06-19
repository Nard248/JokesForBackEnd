# Backend CI/CD Setup Guide — GCP Cloud Build (Native)

The `.github/workflows/deploy-backend.yml` GitHub Actions pipeline has been
replaced with a GCP-native Cloud Build pipeline (`/cloudbuild.yaml` at the repo
root). No GitHub secrets, no SA key files, and no external runner are required.

---

## What the pipeline does

On every push to `main` (once the trigger below is configured), Cloud Build:

1. **Migrates** — runs `pip install -r requirements.txt` then
   `python manage.py migrate --noinput` inside a `python:3.11-slim` container,
   pulling `DATABASE_URL` directly from Secret Manager. Migrations always run
   **before** the new revision is served.
2. **Builds** the Docker image and tags it to Artifact Registry:
   `us-east1-docker.pkg.dev/<PROJECT_ID>/cloud-run-source-deploy/jokesforbackend:<SHORT_SHA>`
3. **Pushes** the image.
4. **Deploys** to Cloud Run (`jokesforbackend`, region `us-east1`).
   The deploy does **not** pass `--set-env-vars`, so all existing Cloud Run
   environment variables are preserved exactly as configured on the service.

---

## Step 1 — Create the Artifact Registry repository (if it doesn't exist)

```bash
gcloud artifacts repositories create cloud-run-source-deploy \
  --repository-format=docker \
  --location=us-east1 \
  --project=<PROJECT_ID>
```

If the repository already exists, skip this step.

---

## Step 2 — Create the DATABASE_URL secret in Secret Manager

1. Go to **GCP Console → Secret Manager → Create Secret**.
2. Name: `DATABASE_URL`.
3. Value: the Neon connection string (same value previously stored as the
   GitHub secret and in Cloud Run's env).
4. Click **Create Secret**.

Grant the Cloud Build service account access to the secret:

```bash
gcloud secrets add-iam-policy-binding DATABASE_URL \
  --member="serviceAccount:332865216810@cloudbuild.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project=<PROJECT_ID>
```

---

## Step 3 — Grant the Cloud Build service account the required roles

The default Cloud Build SA (`332865216810@cloudbuild.gserviceaccount.com`) needs:

| Role | Purpose |
|------|---------|
| `roles/run.admin` | Deploy and manage Cloud Run services |
| `roles/iam.serviceAccountUser` | Allow Cloud Build to act as the Cloud Run runtime SA |
| `roles/artifactregistry.writer` | Push built images to Artifact Registry |
| `roles/secretmanager.secretAccessor` | Read `DATABASE_URL` during the migrate step (granted in Step 2) |

Apply with:

```bash
PROJECT_ID=<your-project-id>
CB_SA=332865216810@cloudbuild.gserviceaccount.com

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$CB_SA" --role="roles/run.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$CB_SA" --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$CB_SA" --role="roles/artifactregistry.writer"
```

---

## Step 4 — Connect the repository and create the trigger

**Option A — via Cloud Build console (recommended):**

1. Go to **GCP Console → Cloud Build → Triggers → Connect Repository**.
2. Choose **GitHub (Cloud Build GitHub App)** and authorise the app if prompted.
3. Select repository `Nard248/JokesForBackEnd`.
4. Click **Create a trigger** on the next screen:
   - **Event**: Push to a branch
   - **Branch**: `^main$`
   - **Build configuration**: Cloud Build configuration file (yaml or json)
   - **Cloud Build configuration file location**: `/cloudbuild.yaml`

   > Do **not** choose the "Dockerfile" auto-detect option — that skips the
   > migration step entirely and will deploy schema-breaking revisions.

5. Save the trigger.

**Option B — via Cloud Run console:**

1. Go to **Cloud Run → service `jokesforbackend` → Edit & Deploy New Revision**.
2. Scroll to **Continuous deployment** → **Set up with Cloud Build**.
3. Connect the GitHub repo, select branch `main`, and point to
   **Cloud Build configuration file** (`/cloudbuild.yaml`).

---

## Frontend deploy ordering

The frontend (Firebase) can deploy at any time since it is a static SPA.
However, recent backend changes introduced `date_of_birth` as a required
registration field. If the frontend and backend deploy out of order:

- **Frontend before backend**: registration calls will fail (new field sent to
  old endpoint that doesn't accept it).
- **Backend before frontend**: registration calls will fail (old form doesn't
  send the new required field).

**Safe approach**: deploy the backend first, then the frontend in the same
release window, or deploy both together.

---

## Rollback

Cloud Run keeps all previous revisions. To immediately route traffic away from a
bad revision:

```bash
# List revisions
gcloud run revisions list --service jokesforbackend --region us-east1

# Send 100% traffic to a previous revision
gcloud run services update-traffic jokesforbackend \
  --to-revisions=<prev-revision-name>=100 \
  --region us-east1
```

Note: rolling back the code does **not** roll back database migrations. If a
migration was destructive, a separate database restore is required.
