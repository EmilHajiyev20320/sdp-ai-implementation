# Level A — Local test environment (Firebase Emulators + Mock AI)

End-to-end test: **bundle → English article → Azerbaijani translation → store → read back**.

Use this on **Windows (PowerShell)**. Ports: Firestore **8082** (see `firebase/firebase.json`), Backend **8000**, Emulator UI **4000**.

---

## 1. One-time setup

```powershell
# From project root
cd c:\test-ai-publisher
pip install -r requirements.txt
```

Firebase CLI: if not installed, `npm install -g firebase-tools` then `firebase login`. Emulator config is in `firebase/firebase.json` (Firestore on 8082, UI on 4000).

---

## 2. Run Level A test (in order)

### Terminal 1 — Start Firebase Emulators

```powershell
cd c:\test-ai-publisher\firebase
firebase emulators:start
```

Leave running. You should see Firestore (8082) and UI (4000). Open http://localhost:4000 to use the Emulator UI.

---

### Terminal 2 — Seed one test bundle

```powershell
cd c:\test-ai-publisher
python scripts/seed_bundle.py
```

Expected: `Seeded bundle: test_bundle_001`. The script uses the emulator automatically (no credentials needed).

---

### Terminal 3 — Start the backend

**Important:** Start this *after* the emulator is already running.

```powershell
cd c:\test-ai-publisher\backend
$env:USE_FIRESTORE_EMULATOR = "1"
$env:FIRESTORE_EMULATOR_HOST = "127.0.0.1:8082"
$env:GOOGLE_CLOUD_PROJECT = "demo-no-project"
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Or use a root `.env` with `USE_FIRESTORE_EMULATOR=1` (see `.env.example`). For **Gemini**, set `GEMINI_API_KEY` or use `AI_BACKEND=ollama` with Ollama + `pip install -r requirements-local.txt` for NLLB.

---

### Terminal 4 — Trigger generation and read back

**Generate article from bundle:**

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/generate" -Method POST -ContentType "application/json" -Body '{"bundle_id":"test_bundle_001"}'
```

You should get something like: `ok : True`, `article_id : art_xxxxxxxxxx`.

**Read back the article** (replace `art_xxxxxxxxxx` with the returned `article_id`):

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/articles/art_xxxxxxxxxx" -Method GET
```

You should see the full article (title_en, body_en, title_az, body_az, etc.).

---

## 3. Verify in Emulator UI

1. Open http://127.0.0.1:4000 (or http://localhost:4000)
2. Go to **Firestore** → **Data**
3. Check:
   - `bundles/test_bundle_001` — your seed data
   - `articles/<article_id>` — the generated article

If both are there, the pipeline (bundle → mock English → mock AZ → store → read) is working.

**If the UI shows no data** — The backend might be talking to real Firestore (or the wrong host). Check:
- `Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/status" -Method GET`  
  You should see `firestore_emulator_host : 127.0.0.1:8081` and `project : demo-no-project`. If project is not `demo-no-project`, the Emulator UI will show no data (it only shows the emulator’s project). Restart the backend with `$env:GOOGLE_CLOUD_PROJECT = "demo-no-project"` and `$env:FIRESTORE_EMULATOR_HOST = "127.0.0.1:8081"`.
- Run the steps in order: emulator first → seed → backend → generate. Then seed and generate again and refresh the Emulator UI.

---

## Differences from the original (bash) plan

| Item | Original plan | This repo (Windows) |
|------|----------------|---------------------|
| Firestore port | 8080 | **8081** (8080 was in use) |
| Env vars | `export FIRESTORE_EMULATOR_HOST=...` | Set in scripts or in PowerShell: `$env:FIRESTORE_EMULATOR_HOST = "localhost:8081"` |
| Backend run | `uvicorn backend.main:app --port 8000` | From `backend/`: `python -m uvicorn main:app --reload --port 8000` |
| curl | `curl -X POST ... -d '...'` | Use `Invoke-RestMethod` or `curl.exe` with proper quoting |

---

## Next: Level B

When Level A works, switch to real models: LLaMA-3 for English generation and NLLB for translation, keeping the same Firestore + backend structure.
