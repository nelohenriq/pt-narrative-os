# tasks.md — Portugal Narrative OS V1 Implementation Tasks

Prioritized task list for coding agents and developers. Work top to bottom. Do not skip ahead.

---

## Phase 0 — Project setup

- [ ] Initialize Python 3.12 project with uv and pyproject.toml
- [ ] Run `docker compose up` to start Postgres+pgvector, Ollama, Redis
- [ ] Verify Ollama models pulled: nomic-embed-text, mistral
- [ ] Run db/migrations/001_initial.sql to create all tables
- [ ] Run db/seed/outlets.sql to seed 20 Portuguese outlets + owners
- [ ] Copy .env.example to .env and fill in API keys
- [ ] Verify NVIDIA NIM API key works with a test embedding call
- [ ] Verify Groq API key works with a test chat call
- [ ] Write tests/db_test.py — verify all tables exist and have expected columns
- [ ] Create empty services/ subdirectories with __init__.py files

---

## Phase 1 — AI client infrastructure

- [ ] Implement ai/clients.py — AsyncOpenAI clients for Ollama, NIM, Groq, OpenRouter
- [ ] Implement ai/router.py — call() with task map and fallback chain
- [ ] Write tests/test_ai_clients.py — mock test of client creation and routing
- [ ] Verify embedding call through router returns 768-dim vector
- [ ] Verify chat call through router returns valid JSON

---

## Phase 2 — Ingestion

- [ ] Implement services/ingestion/feed_reader.py
  - Fetch RSS/Atom feeds per outlet
  - Parse with feedparser
  - Compute SHA256 url_hash for dedup
  - Insert into raw_items with status=pending
  - Skip if url_hash already exists
  - Handle outlets without RSS by attempting /sitemap.xml parsing
- [ ] Implement services/ingestion/institutional.py
  - Fetch AR open data XML/JSON (Diplomas Aprovados + Atividades)
  - Parse into source_documents rows
  - Dedup by source_type + external_id
- [ ] Add cron/scheduler to run ingestion every 30 minutes
- [ ] Write tests/test_ingestion.py — mock feed test, dedup test

---

## Phase 3 — Normalization

- [ ] Implement services/normalization/parser.py
  - Extract body text using trafilatura
  - Detect language (confirm Portuguese or skip)
  - Detect explicit Lusa credit (regex: "Lusa", "agência Lusa", "©Lusa")
  - Compute word_count and content_hash
  - Skip items with word_count < 80
  - Insert into articles with status=pending
  - Update raw_items status to parsed
- [ ] Write tests/test_normalization.py — trafilatura on sample HTML

---

## Phase 4 — Embedding & Clustering

- [ ] Implement services/clustering/embedder.py
  - Batch embed articles via Ollama nomic-embed-text (search_document prefix)
  - Store vector(768) in articles.embedding
  - Detect lusa_likely via cosine similarity to Lusa wires (>0.88 threshold)
  - Update articles.status to 'embedded'
- [ ] Implement services/clustering/clusterer.py
  - For each new embedded article, find nearest event by centroid similarity (>0.85)
  - Within 72h time window
  - If match: add to event via event_articles, recompute centroid
  - If no match: create new event with status='candidate'
  - Update event article_count and outlet_count denormalized fields
- [ ] Write tests/test_clustering.py — cosine similarity test, event creation test

---

## Phase 5 — Article Analysis

- [ ] Implement services/analysis/article_analyzer.py
  - Build extraction prompt from prompts/v1_extractor_fast.py
  - Call extractor_fast model (Ollama mistral, fallback NIM)
  - Use response_format=json_object, temperature=0.1
  - Parse JSON response, validate against expected schema
  - Insert into article_analysis
  - Upsert entities into entities table (exact lowercase name match for dedup)
  - Insert into article_entities with confidence
  - Insert claims into claims table
  - Create ai_runs row for auditability
  - Update articles.status to 'analyzed'
- [ ] Write tests/test_analysis.py — mock AI response, verify DB writes

---

## Phase 6 — Enrichment & Scoring

- [ ] Implement services/enrichment/enricher.py
  - Link source_documents to events by topic/entity match + time overlap
  - Compute lusa_dependency: (lusa_likely + lusa_cited) / total_articles_in_event
  - Insert into event_documents
- [ ] Implement services/scoring/scorer.py
  - coverage_breadth: outlets_covering / total_active_outlets
  - framing_divergence: variance in frame_labels across outlets (0-1)
  - evidence_density: articles_citing_documents / total_articles
  - undercoverage_score: composite signal (see pipeline doc)
  - Create undercoverage_flags rows when undercoverage detected
  - Insert into event_scores
  - Promote candidate events to 'unreviewed' if they meet criteria
- [ ] Write tests/test_scoring.py — verify score formulas

---

## Phase 7 — Generation

- [ ] Implement services/generation/generator.py
  - event_summary: NIM Llama 3.3 70B, prompts/v1_summary_fast.py
  - framing_comparison: NIM Mistral-Small, prompts/v1_framing_analyst.py
  - undercoverage_card: NIM DeepSeek R1, prompts/v1_undercoverage_card.py (only if flag exists)
  - All use response_format=json_object
  - All create ai_runs rows
  - All insert into event_summaries with prompt_version
- [ ] Write tests/test_generation.py — mock AI, verify summary storage

---

## Phase 8 — Review UI

- [x] Implement review/app.py — FastAPI + HTMX
  - HTTP Basic Auth using REVIEW_USERNAME and REVIEW_PASSWORD_HASH
  - List unreviewed events with scores
  - Event detail view with articles, scores, summaries
  - Approve: set status='reviewed_published', is_reviewed=TRUE, is_published=TRUE
  - Reject: set status='reviewed_rejected', is_reviewed=TRUE, is_published=FALSE
  - Edit summary inline before publishing
  - Request re-generation: delete event_summaries, reset to 'unreviewed'
- [x] Write tests/test_review.py — auth test, approve/reject test (16/16 pass)

---

## Phase 9 — API

- [x] Implement api/main.py — FastAPI app
- [x] GET /digest/today — today's daily_digest
- [x] GET /events — paginated published events list
- [x] GET /events/{id} — event detail with articles, scores, summaries, documents
- [x] GET /events/{id}/provenance — trace AI outputs back to ai_runs and source articles
- [x] GET /events/undercovered — published undercoverage flags
- [x] GET /outlets — list all active outlets
- [x] GET /outlets/{slug} — outlet profile with ownership and recent events
- [x] GET /search?q= — full-text search across events and articles
- [x] Query params for filtering: outlet, topic, date_from, date_to, claim_type
- [ ] Write tests/test_api.py — endpoint integration tests (need running API server)

---

## Phase 10 — Digest Builder

- [ ] Implement services/digest/digest_builder.py
  - Build daily digest from published events
  - Sort by coverage_breadth DESC, framing_divergence DESC
  - Include undercoverage list
  - Insert into daily_digests
- [ ] Add cron to run daily at 07:00 UTC

---

## Phase 11 — Frontend (Next.js)

- [ ] Set up Next.js app in web/ subfolder
- [ ] Homepage — daily digest feed
- [ ] Event page — summary, outlet list, framing comparison, linked docs
- [ ] Undercovered page
- [ ] Outlet page — ownership context + recent events
- [ ] Search page

---

## Cross-cutting tasks (do alongside above)

- [ ] Set up CI: lint (ruff), type check (mypy), test (pytest) on push
- [ ] Add logging configuration (structured JSON logs, per-service loggers)
- [ ] Add error monitoring: log all ai_runs with status='failed'
- [ ] Set up database backup cron (pg_dump daily)
- [ ] Write README.md with setup instructions and architecture overview
