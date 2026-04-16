# Weekly report summary — AI publisher test environment

## Objective
Set up a **Level A local test environment** for the AI content pipeline: end-to-end flow from bundle → English article (mock) → Azerbaijani translation (mock) → store in Firestore → read back, without the full app or Airflow, and without real Firebase credentials.

## What was done

### 1. Repo and structure
- Confirmed/used structure: `backend/` (FastAPI), `scripts/` (seed script), `firebase/` (emulator config).
- Added `requirements.txt` (google-cloud-firestore, fastapi, uvicorn).

### 2. Firebase Emulators
- **firebase.json**: Configured Firestore (port 8081; 8080 was in use), Auth (9099), and Emulator UI (4000).
- Emulator runs with default project **demo-no-project** (no Firebase project linked).

### 3. Backend (FastAPI)
- **POST /admin/generate**: Reads bundle from Firestore, runs mock English generation and mock AZ translation, writes result to `articles` collection.
- **GET /admin/articles/{article_id}**: Read-back endpoint for generated articles.
- **GET /admin/status**: Returns `FIRESTORE_EMULATOR_HOST` and project (for debugging).
- Backend and scripts **default to the emulator** (no real credentials): set `FIRESTORE_EMULATOR_HOST=127.0.0.1:8081` and `GOOGLE_CLOUD_PROJECT=demo-no-project` so the Emulator UI and app use the same project.

### 4. Seed script
- **scripts/seed_bundle.py**: Inserts test bundle `test_bundle_001` (Edge computing explainer, 2 sources, constraints). Uses emulator by default.

### 5. Documentation and runbook
- **TEST_ENV.md**: Step-by-step Level A runbook for Windows (PowerShell): start emulators → seed → start backend → call generate → read back → verify in Emulator UI. Includes troubleshooting (project ID mismatch, status endpoint).

## Issues resolved

| Issue | Cause | Fix |
|-------|--------|-----|
| “No emulators to start” | firebase.json had no emulator products | Added auth, firestore, ui to firebase.json. |
| Firestore port in use | Port 8080 taken | Set Firestore to port 8081 in firebase.json. |
| ImportError: firestore from google.cloud | google-cloud-firestore not installed | Added to requirements.txt; `pip install -r requirements.txt`. |
| DefaultCredentialsError when running seed/backend | App tried real Firebase | Set FIRESTORE_EMULATOR_HOST (and default project) in code and docs so emulator is used by default. |
| curl failed in PowerShell | `curl` is alias for Invoke-WebRequest; different syntax | Documented Invoke-RestMethod and curl.exe with correct quoting. |
| uvicorn not found | Not on PATH | Use `python -m uvicorn`; added uvicorn to requirements.txt. |
| Emulator UI empty despite successful API calls | App used project **demo-sdp**; emulator and UI use **demo-no-project** | Switched app default to **demo-no-project** so UI and backend share same project. |

## Current state
- Level A works end-to-end on Windows: Firebase Emulators (Firestore + UI), seed script, FastAPI backend, generate + read-back; data visible in Emulator UI at http://127.0.0.1:4000.
- Ready for **Level B**: swap mock generation/translation for real LLaMA-3 and NLLB using the same Firestore and API flow.

## Files touched/added
- `firebase/firebase.json` — emulator config (Firestore 8081, Auth, UI 4000).
- `backend/main.py` — generate + get article + status; emulator defaults.
- `scripts/seed_bundle.py` — test bundle; emulator default.
- `requirements.txt` — firestore, fastapi, uvicorn.
- `TEST_ENV.md` — Level A runbook and troubleshooting.
- `.env` — FIRESTORE_EMULATOR_HOST, GOOGLE_CLOUD_PROJECT (demo-no-project) for reference.
