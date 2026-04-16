# Weekly Report — AI Publisher (My Part)

**Week of:** March 2026  
**Project:** SDP AI Publisher  
**Role:** AI pipeline implementation

---

## Summary

I set up and implemented the end-to-end AI pipeline for the AI Publisher: fetching news from NewsData.io, generating English articles with Ollama, translating to Azerbaijani with NLLB, and storing results in Firestore. The pipeline runs locally with Firebase emulators and is ready for further integration.

---

## Accomplishments

### 1. Local test environment

- Configured Firebase emulators (Firestore on port 8081, UI on 4000) for local development without production credentials.
- Set up environment variables so the backend uses the emulator and stores data in the correct project.

### 2. Ollama integration (English article writer)

- Installed and configured Ollama for local LLM inference.
- Pulled the `llama3.2:3b` model for article generation.
- Implemented `writer_ollama.py` to call Ollama’s API with a journalist-style prompt (mode, topic, sources, length rules).
- The writer produces 400–700 word articles in English from source snippets.

### 3. NLLB translator (English → Azerbaijani)

- Integrated the NLLB-200 distilled model (Hugging Face) for English → Azerbaijani (Latin) translation.
- Implemented chunked translation (paragraph-by-paragraph, ~80 words per chunk) to reduce repetition and hallucinations.
- Added anti-repetition settings: `repetition_penalty=1.5`, `no_repeat_ngram_size=4`.
- Added post-processing to strip repetitive patterns (e.g. repeated words like "birincə").
- Fixed URL corruption: the Sources section is no longer translated; URLs are kept as-is and the header is translated to "Mənbələr".

### 4. NewsData.io integration

- Registered for a NewsData.io API key and integrated the API.
- Implemented `newsdata_client.py` to fetch articles by topic, category, and query.
- Added `POST /admin/bundles/fetch` to fetch articles and create bundles in Firestore.
- Mapped API responses to the bundle format (sources with URL, publisher, snippet, date).

### 5. FastAPI backend and workflow

- Implemented the main workflow in `main.py`:
  - `POST /admin/bundles/fetch` — fetch articles and create a bundle
  - `POST /admin/generate` — generate article from a bundle (Ollama + NLLB)
  - `GET /admin/articles/{id}` — retrieve a generated article
  - `GET /admin/status` — check Firestore and API key status
- Added quality checks: word count (350–750), translation sanity, bundle existence.
- Added error handling for NewsData.io (401, request failures, missing key).

### 6. Environment and configuration

- Added `.env` support with `python-dotenv` so API keys and config are loaded from a file.
- Created `.env.example` as a template.
- Added `.env` to `.gitignore` to avoid committing secrets.

---

## Challenges and solutions

| Challenge | Solution |
|-----------|----------|
| NLLB corrupted URLs (e.g. www.www.www...) | Strip Sources section before translation; append with "Mənbələr:" and original URLs |
| NLLB repeated phrases (e.g. "birincə, birincə...") | Chunked translation, repetition penalty, no-repeat n-grams, post-processing |
| Ollama sometimes produced &lt;400 words | Relaxed word count to 350–750 |
| NewsData.io 401 errors | Switched auth to query param, added error handling and status check |
| Env vars had to be set manually each time | Added `.env` and `python-dotenv` |

---

## Technical stack

- **Writer:** Ollama + LLaMA 3.2 (3B)
- **Translator:** NLLB-200 distilled (Hugging Face)
- **News source:** NewsData.io API
- **Storage:** Firebase Firestore (emulator)
- **Backend:** FastAPI, Python 3.11

---

## Next steps (for future weeks)

- Consider Google Cloud Translation API for production (more stable than local NLLB).
- Consider Vertex AI (e.g. Gemini) for production article generation.
- Integrate with the main app and/or Airflow when ready.
