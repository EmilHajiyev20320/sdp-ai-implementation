# Deploying to Google Cloud (Cloud Run + Firestore + Vertex Gemini)

## What runs where

- **API**: Cloud Run container (this repo’s `Dockerfile`) — FastAPI + Firestore + Vertex AI Gemini for writing and translation.
- **Firestore**: Native mode in your GCP project (not the emulator). Create a database in the same project as Cloud Run.
- **LLM**: Vertex AI Gemini — set `GEMINI_USE_VERTEX=1`, `GOOGLE_CLOUD_PROJECT`, `GEMINI_LOCATION` (e.g. `us-central1`), and grant the Cloud Run service account **Vertex AI User**.

## Environment variables (production)

| Variable | Purpose |
|----------|---------|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID (set automatically on Cloud Run if configured). |
| `AI_BACKEND` | `gemini` to force Gemini; `auto` picks Gemini when Vertex or API key is configured. |
| `GEMINI_USE_VERTEX` | `1` for Vertex AI (recommended on GCP). |
| `GEMINI_LOCATION` | Region, e.g. `us-central1`. |
| `GEMINI_MODEL` | e.g. `gemini-2.5-flash` (must exist in that region). |
| `NEWSDATA_API_KEY` | Optional; for NewsData ingestion. |
| `USE_FIRESTORE_EMULATOR` | **Unset** in production (omit or empty). |

Do **not** set `FIRESTORE_EMULATOR_HOST` in production.

## Local vs GCP Firestore

- **Local emulator**: `USE_FIRESTORE_EMULATOR=1` in `.env` (see `.env.example`).
- **GCP**: leave `USE_FIRESTORE_EMULATOR` unset; use a real project and credentials (ADC or service account).

## Build and deploy (example)

```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/ai-publisher
gcloud run deploy ai-publisher \
  --image gcr.io/PROJECT_ID/ai-publisher \
  --region us-central1 \
  --set-env-vars "AI_BACKEND=gemini,GEMINI_USE_VERTEX=1,GEMINI_LOCATION=us-central1,GEMINI_MODEL=gemini-2.5-flash" \
  --service-account YOUR_RUN_SA@PROJECT_ID.iam.gserviceaccount.com
```

Grant that service account **Cloud Datastore User** (Firestore) and **Vertex AI User**.

## Alternative: Google AI Studio API key

For non-Vertex setups, set `GEMINI_API_KEY` and leave `GEMINI_USE_VERTEX` unset. Suitable for local or small VMs; on GCP, Vertex is usually preferred.

## Production hardening checklist

Use this after the app is already working end to end.

### 1) Dedicated Cloud Run runtime service account

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

### 2) Secret Manager for API keys

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

### 3) Monitoring and alerts

Create these in the GCP Console:
1. Uptime check for `/admin/status`
2. Alert on Cloud Run 5xx rate
3. Alert on Vertex `ResourceExhausted` / 429 errors
4. Notification channel for email or Slack

### 4) Remove broad default compute roles after validation

```bash
PROJECT_ID="tezsaniye-cf873"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
DEFAULT_COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud projects remove-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${DEFAULT_COMPUTE_SA}" --role="roles/editor"
gcloud projects remove-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${DEFAULT_COMPUTE_SA}" --role="roles/storage.admin"
```
