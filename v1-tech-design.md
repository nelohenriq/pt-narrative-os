# pt-media-os V1 — Technical Design Document

_Last updated: 2026-04-25_

## 1. Overall architecture

The system is event-driven and centered on the event graph, with three main layers:

- **Data layer**: ingestion, storage, and indexing.
- **Intelligence layer**: clustering, extraction, and scoring.
- **Product layer**: API, UI, and exports.

Services communicate via Postgres polling (no message queue in V1) and a shared Postgres database.

## 2. Services and components

### 2.1 Ingestion services

- `feed_reader` — Polls RSS/Atom feeds from configured outlets. Downloads HTML, stores in `raw_items`. Deduplicates by `url_hash`.
- `institutional` — Fetches AR open data (Diplomas Aprovados, Atividades). Stores in `source_documents`. Deduplicates by `source_type + external_id`.

### 2.2 Normalization service

- `parser` — Reads `raw_items` with status=pending. Extracts body with trafilatura, detects language, detects Lusa credit. Creates `articles` with status=pending. Marks raw_items as parsed.

### 2.3 Clustering and event graph

- `embedder` — Reads articles with status=pending and no embedding. Computes vector(768) embeddings via Ollama nomic-embed-text. Detects `lusa_likely`. Updates status to 'embedded'.
- `clusterer` — Reads embedded articles not yet in `event_articles`. Finds nearest event by centroid similarity (>0.85 within 72h). Creates new events or adds to existing. Recomputes centroids.

### 2.4 Analysis service

- `article_analyzer` — Reads articles with status=embedded and no `article_analysis` row. Calls AI to extract entities, claims, quotes, topics, frames. Stores results in `article_analysis`, `entities`, `article_entities`, `claims`. Updates status to 'analyzed'.

### 2.5 Enrichment service

- `enricher` — Reads candidate/unreviewed events with no `event_documents`. Links `source_documents` to events by topic/entity match. Computes `lusa_dependency`.

### 2.6 Scoring service

- `scorer` — Reads events without scores or with stale scores. Computes `coverage_breadth`, `framing_divergence`, `evidence_density`, `lusa_dependency`, `undercoverage_score`. Creates `undercoverage_flags` when criteria met. Promotes candidate events to unreviewed when criteria met.

### 2.7 Generation service

- `generator` — Reads unreviewed events with scores and incomplete `event_summaries`. Generates event_summary, framing_comparison, undercoverage_card (if flag exists). Creates `ai_runs` rows for auditability.

### 2.8 API and UI layer

- `api-service` — FastAPI REST API. Exposes events, outlets, articles, scores, search, provenance. See tasks.md Phase 9 for endpoint list.
- `review-ui` — FastAPI + HTMX. HTTP Basic Auth. List/approve/reject events. Edit summaries.
- `web-ui` — Next.js frontend. Displays event pages, outlet comparison, undercoverage flags, and provenance.

### 2.9 Background and maintenance

- `digest_builder` — Cron daily. Builds homepage feed from published events.
- `migration_runner` — Applies database migrations at startup (handled by docker-entrypoint-initdb.d in V1).

## 3. Data flow

1. **Ingestion**: `feed_reader` → `raw_items` (pending) → `institutional` → `source_documents`
2. **Normalization**: `parser` reads `raw_items` → creates `articles` (pending) → marks raw_items as parsed
3. **Embedding**: `embedder` reads `articles` (pending, no embedding) → stores embedding → updates status to embedded
4. **Clustering**: `clusterer` reads embedded articles → creates/updates `events` + `event_articles`
5. **Analysis**: `article_analyzer` reads embedded articles → creates `article_analysis`, `entities`, `article_entities`, `claims` → updates status to analyzed
6. **Enrichment**: `enricher` reads events → creates `event_documents`, computes `lusa_dependency`
7. **Scoring**: `scorer` reads events → creates `event_scores`, `undercoverage_flags` → promotes candidate events
8. **Generation**: `generator` reads unreviewed events → creates `event_summaries`
9. **Review**: human approves → `is_published = TRUE`
10. **Digest**: `digest_builder` reads published events → creates `daily_digests`
11. **UI/API**: clients read from `events`, `articles`, `event_scores`, `event_summaries`, `daily_digests`

This flow keeps ingestion and analysis decoupled and supports re-processing events as models improve.

## 4. Folder structure

```
pt-narrative-os/
├── CLAUDE.md
├── tasks.md
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── db/
│   ├── migrations/
│   │   └── 001_initial.sql
│   └── seed/
│       └── outlets.sql
├── services/
│   ├── ingestion/
│   ├── normalization/
│   ├── clustering/
│   ├── analysis/
│   ├── enrichment/
│   ├── scoring/
│   ├── generation/
│   └── digest/
├── ai/
│   ├── clients.py
│   └── router.py
├── prompts/
├── api/
│   └── routes/
├── review/
├── docs/
└── web/
```

## 5. AI provider integration

- All AI calls go through a single `AIClient` factory (ai/clients.py) that returns an OpenAI-compatible client per provider.
- All task routing is in ai/router.py with fallback chains.
- Each service picks the appropriate provider based on task:

| Task | Primary | Fallback |
|---|---|---|
| Embeddings | Ollama (nomic-embed-text, 768-dim) | NVIDIA NIM (nv-embedqa-e5-v5) |
| Fast extraction | Ollama (mistral) | NVIDIA NIM (llama-3.3-70b-instruct) |
| Framing analysis | NVIDIA NIM (mistral-small-4-119b) | Groq (llama-3.3-70b-versatile) |
| Summaries | NVIDIA NIM (deepseek-r1) | Groq (llama-3.3-70b-versatile) |
| Fallback | OpenRouter (llama-3.3-70b-instruct) | — |

- All calls are logged in `ai_runs` with task, model, provider, latency, cost, prompt_version.
- All calls use `response_format={"type": "json_object"}, temperature=0.1`.
- No tool-calls / function-calling.

## 6. Database design

See db/migrations/001_initial.sql for the complete schema. Key design decisions:

- **18 tables** covering: ownership (owners, outlets, outlet_ownership), ingestion (raw_items), articles (articles, article_analysis, entities, article_entities, claims), events (events, event_articles, source_documents, event_documents, event_scores, undercoverage_flags, event_summaries), AI audit (ai_runs), and frontend (daily_digests).
- **UUIDs** for all primary keys.
- **vector(768)** for embeddings (matching nomic-embed-text output).
- **HNSW indexes** on embedding columns for fast similarity search.
- **Status enums** for article and event lifecycle tracking.
- **ai_runs table** for full auditability of every AI call.

## 7. Non-functional considerations

- **Idempotent consumers**: each service can safely reprocess articles/events by checking existing state.
- **Schema evolution**: migrations are versioned in db/migrations/.
- **Auditability**: every AI output traces back to an `ai_run` with prompt_version.
- **Local dev**: `docker compose up` starts Postgres+pgvector, Ollama, Redis.
- **Auth**: Review UI uses HTTP Basic Auth. Public API is read-only.
- **Event lifecycle**: events go through candidate → unreviewed → reviewed_published/reviewed_rejected. See docs/event-lifecycle.md.
