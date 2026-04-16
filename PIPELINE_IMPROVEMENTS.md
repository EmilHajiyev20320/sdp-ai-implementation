# Pipeline Improvements Summary

## 1. Backend Inspection (What Was Improved)

| Area | Before | After |
|------|--------|-------|
| **Writer prompt** | Generic, no mode-specific instructions, weak structure | `backend/prompts.py`: mode-specific (global_news, explainer, az_tech), clear structure, Sources section |
| **Bundle selection** | Shuffle only, no dedup | `bundle_creator.py`: filter trivial snippets, dedupe similar sources, limit same publisher (max 2) |
| **Validation** | Inline word count + translation sanity | `article_validator.py`: word count, translation length, sources, repetition checks |
| **Quality tracking** | Basic flags | Full `quality_flags` from validator (word_count_en/az, has_sources, etc.) |
| **Multi-bundle testing** | Single seed_bundle.py | `seed_test_bundles.py` + `test_pipeline.py` for all 3 modes |
| **Bundle listing** | None | `GET /admin/bundles` |

---

## 2. Quality Checks & Thresholds

| Check | Threshold | Action |
|-------|-----------|--------|
| English word count | 350–750 (env: ARTICLE_MIN_WORDS, ARTICLE_MAX_WORDS) | Reject |
| Azerbaijani word count | ≥ 50 | Reject if below |
| Sources present | ≥ 1 valid (url or snippet) | Reject |
| Repetition | Same 5-word phrase &lt; 3 times | Reject if exceeded |

---

## 3. Files Changed/Added

- **Added:** `backend/prompts.py` – mode-specific writer prompts
- **Added:** `backend/article_validator.py` – validation before storage
- **Added:** `scripts/seed_test_bundles.py` – seed 3 bundles (all modes)
- **Added:** `scripts/test_pipeline.py` – batch generate
- **Modified:** `backend/main.py` – use prompts, validator, add GET /admin/bundles
- **Modified:** `backend/bundle_creator.py` – dedup, snippet filter, publisher limit
- **Modified:** `SOURCE_PIPELINE_TEST.md` – multi-bundle testing, quality checks
