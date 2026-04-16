# GitHub -> GCP Auto Deploy Setup

This project includes a GitHub Actions workflow at `.github/workflows/deploy-cloud-run.yml`.

## 1) Create GitHub repository and push this code

Run from your local terminal:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/<YOUR_REPO>.git
git push -u origin main
```

## 2) Create deploy service account in GCP

```bash
PROJECT_ID="tezsaniye-cf873"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
SA_NAME="github-deployer"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create "$SA_NAME" --display-name="GitHub Actions Deployer"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudbuild.builds.editor"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/iam.serviceAccountUser"
```

## 3) Configure Workload Identity Federation (no JSON key)

```bash
PROJECT_ID="tezsaniye-cf873"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
POOL_ID="github-pool"
PROVIDER_ID="github-provider"
REPO="<YOUR_GITHUB_USERNAME>/<YOUR_REPO>"
SA_EMAIL="github-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam workload-identity-pools create "$POOL_ID" \
  --project="$PROJECT_ID" \
  --location="global" \
  --display-name="GitHub Pool"

gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
  --project="$PROJECT_ID" \
  --location="global" \
  --workload-identity-pool="$POOL_ID" \
  --display-name="GitHub Provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository"

gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${REPO}"
```

Build this provider string for GitHub secret:

```bash
echo "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"
```

## 4) Add GitHub repository secrets and variables

GitHub repository -> Settings -> Secrets and variables -> Actions

Secrets:
- `GCP_WIF_PROVIDER` = output from previous command
- `GCP_SERVICE_ACCOUNT` = `github-deployer@tezsaniye-cf873.iam.gserviceaccount.com`

Variables:
- `GCP_PROJECT_ID` = `tezsaniye-cf873`
- `GCP_REGION` = `us-central1`
- `CLOUD_RUN_SERVICE` = `ai-publisher`
- `ARTIFACT_REPO` = `ai-publisher`

## 5) Test deployment

Push a commit to `main`. The workflow should:
1. Build image with Cloud Build
2. Push image to Artifact Registry
3. Deploy to Cloud Run

Then check Actions tab and Cloud Run revisions.
