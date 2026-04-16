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
1. Build image with Docker on the GitHub runner
2. Push image to Artifact Registry
3. Deploy to Cloud Run

Then check Actions tab and Cloud Run revisions.

## 6) Production hardening checklist

These steps are optional for MVP, but recommended before calling the system production-ready.

### 6.1 Create a dedicated Cloud Run runtime service account

```bash
PROJECT_ID="tezsaniye-cf873"
REGION="us-central1"
SERVICE="ai-publisher"
RUNTIME_SA_NAME="ai-publisher-runtime"
RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT_ID"
gcloud iam service-accounts create "$RUNTIME_SA_NAME" --display-name="AI Publisher Runtime Service Account"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${RUNTIME_SA}" --role="roles/aiplatform.user"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${RUNTIME_SA}" --role="roles/datastore.user"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${RUNTIME_SA}" --role="roles/logging.logWriter"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${RUNTIME_SA}" --role="roles/monitoring.metricWriter"
gcloud run services update "$SERVICE" --region "$REGION" --service-account "$RUNTIME_SA"
```

### 6.2 Move API keys into Secret Manager

```bash
PROJECT_ID="tezsaniye-cf873"
REGION="us-central1"
SERVICE="ai-publisher"
RUNTIME_SA="ai-publisher-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud services enable secretmanager.googleapis.com
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${RUNTIME_SA}" --role="roles/secretmanager.secretAccessor"
gcloud run services update "$SERVICE" --region "$REGION" --set-secrets "NEWSAPI_API_KEY=NEWSAPI_API_KEY:latest,NEWSDATA_API_KEY=NEWSDATA_API_KEY:latest"
gcloud run services update "$SERVICE" --region "$REGION" --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},AI_BACKEND=gemini,GEMINI_USE_VERTEX=1"
```

### 6.3 Validate bundle generation uses raw_articles

```bash
curl -s -X POST "https://ai-publisher-975738038281.us-central1.run.app/admin/bundles/create" \
  -H "Content-Type: application/json" \
  -d '{"topic":"technology","mode":"explainer","max_sources":5,"min_sources":3,"days_back":7}'
```

Expected fields:
- `ok: true`
- `sources_count: 5`
- `raw_sources_used: 1` or more

### 6.4 Add monitoring and alerting in GCP Console

Create these checks and alerts:
1. Uptime check for `/admin/status`
2. Alert on Cloud Run 5xx rate
3. Alert on Vertex `ResourceExhausted` / 429 errors
4. Notification channel for email or Slack

### 6.5 Remove broad roles from default compute service account after validation

Only do this after runtime SA and smoke tests are confirmed working.

```bash
PROJECT_ID="tezsaniye-cf873"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
DEFAULT_COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud projects remove-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${DEFAULT_COMPUTE_SA}" --role="roles/editor"
gcloud projects remove-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${DEFAULT_COMPUTE_SA}" --role="roles/storage.admin"
```
