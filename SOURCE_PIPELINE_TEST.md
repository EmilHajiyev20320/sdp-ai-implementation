# Source Ingestion + Bundle Creation — Testing Guide

## Overview

New pipeline: **sources → cleaned articles → bundle → AI model → article**

- **sources** collection: unified storage for all fetched articles (RSS, NewsData.io)
- **bundles** collection: unchanged; now can be created from stored sources
- **Existing endpoints** (`/admin/bundles/fetch`, `/admin/generate`) remain unchanged

---

## 1. Start Services

```powershell
# Terminal 1: Firebase emulators
cd firebase
firebase emulators:start   # Firestore on 8082, UI on 4000

# Terminal 2: Backend
cd C:\test-ai-publisher
pip install feedparser
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

---

## 2. Test RSS Fetch

Fetch from TechCrunch RSS and store in `sources`:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/sources/fetch-rss" -Method POST -ContentType "application/json" -Body '{"topic":"technology"}'
```

**Expected:** `ok: True`, `saved: N`, `skipped: 0` (first run). Run again to see dedup: `skipped` > 0.

---

## 3. Test NewsData.io Fetch (into sources)

Requires `NEWSDATA_API_KEY` in `.env`:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/sources/fetch-newsdata" -Method POST -ContentType "application/json" -Body '{"topic":"Edge computing","category":"technology"}'
```

**Expected:** `ok: True`, `saved: N`, `skipped: 0` (first run).

---

## 4. List Sources (Debug)

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/sources?limit=10" -Method GET
```

Or filter by topic:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/sources?topic=technology" -Method GET
```

---

## 5. Create Bundle from Sources

Create a bundle from stored sources with topic "technology":

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/bundles/create" -Method POST -ContentType "application/json" -Body '{"topic":"technology","max_sources":5}'
```

**Expected:** `ok: True`, `bundle_id: bundle_xxx`, `sources_count: 3-5`

If you get "Not enough sources", ensure you've run fetch-rss and/or fetch-newsdata with matching topic first.

---

## 6. Generate Article (unchanged)

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/generate" -Method POST -ContentType "application/json" -Body '{"bundle_id":"bundle_XXXXXXXXXXXX"}'
```

Use the `bundle_id` from step 5.

---

## 7. Full Pipeline (One-liner)

```powershell
# 1. Fetch RSS
Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/sources/fetch-rss" -Method POST -ContentType "application/json" -Body '{"topic":"technology"}'

# 2. Create bundle
$b = Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/bundles/create" -Method POST -ContentType "application/json" -Body '{"topic":"technology"}'

# 3. Generate
Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/generate" -Method POST -ContentType "application/json" -Body ('{"bundle_id":"' + $b.bundle_id + '"}')
```

---

## 8. Firestore Emulator UI

Open http://127.0.0.1:4000 and check:

- **sources** — Fetched articles (unified schema)
- **bundles** — Created bundles
- **articles** — Generated articles

---

## Endpoints Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/admin/sources` | GET | List sources (debug) |
| `/admin/sources/fetch-rss` | POST | Fetch RSS → store in sources |
| `/admin/sources/fetch-newsdata` | POST | Fetch NewsData.io → store in sources |
| `/admin/bundles` | GET | List bundles (for testing) |
| `/admin/bundles/create` | POST | Create bundle from stored sources |
| `/admin/bundles/fetch` | POST | *(existing)* Fetch NewsData.io → create bundle directly |
| `/admin/generate` | POST | *(existing)* Generate article from bundle |

---

## 9. Multi-Bundle Testing (Improved Pipeline)

### Real sources flow (RSS + NewsData → bundles → articles)

**Prerequisites:** Backend running, Ollama + LLaMA, NLLB translator. Optional: `NEWSDATA_API_KEY` for NewsData.

```powershell
# Full pipeline: fetch real sources, create bundles, generate articles
python scripts/test_pipeline.py --fetch --create --generate
```

This will:
1. **Fetch** from TechCrunch RSS and NewsData.io (if API key set) into `sources`
2. **Create** 3 bundles (explainer, global_news, az_tech) from stored sources
3. **Generate** articles for each bundle

With custom topic:
```powershell
python scripts/test_pipeline.py --fetch --create --generate --topic technology
```

### Seed test bundles (quick smoke test, mock data)

```powershell
python scripts/seed_test_bundles.py
# or
python scripts/test_pipeline.py --seed --generate
```

Creates 3 bundles with predefined snippets: `test_bundle_explainer`, `test_bundle_global`, `test_bundle_az_tech`.

### Generate for specific bundles

```powershell
python scripts/test_pipeline.py --generate --bundles bundle_xxx bundle_yyy
```

### Test all 3 modes via API

Create bundles with different modes:

```powershell
# explainer (default)
Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/bundles/create" -Method POST -ContentType "application/json" -Body '{"topic":"technology","mode":"explainer"}'

# global_news
Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/bundles/create" -Method POST -ContentType "application/json" -Body '{"topic":"technology","mode":"global_news"}'

# az_tech
Invoke-RestMethod -Uri "http://127.0.0.1:8000/admin/bundles/create" -Method POST -ContentType "application/json" -Body '{"topic":"technology","mode":"az_tech"}'
```

---

## 10. Quality Checks & Validation

Articles are validated before storage. Rejected if:

- **English word count** outside 350–750 (configurable via `ARTICLE_MIN_WORDS`, `ARTICLE_MAX_WORDS`)
- **Azerbaijani translation** empty or &lt; 50 words
- **No sources** attached to bundle
- **Degenerate repetition** (same 5-word phrase repeated 3+ times)

On success, `quality_flags` are stored with each article:

- `word_count_en`, `word_count_az`
- `has_sources`, `sources_count`
- `within_length`, `translation_ok`, `no_excessive_repetition`

Inspect in Firestore Emulator UI (articles collection) or via `GET /admin/articles/{article_id}`.

---

## 11. Full Test Flow (Emulator)

```powershell
# Terminal 1: Start Firestore emulator
cd firebase
firebase emulators:start

# Terminal 2: Start backend
cd C:\test-ai-publisher
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# Terminal 3: Run full test
python scripts/seed_test_bundles.py
python scripts/test_pipeline.py --generate
```

Check http://127.0.0.1:4000 for bundles and articles in Firestore.
