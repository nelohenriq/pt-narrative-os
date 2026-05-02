# CLAUDE.md — Portugal Narrative OS

This file is for Claude Code, Codex CLI, or any coding agent working on this project. Read this before touching any code.

---

## What this project is

A Portugal-first media intelligence platform that:
- Ingests articles from selected Portuguese news outlets and institutional sources.
- Clusters articles into events using semantic embeddings.
- Compares how different outlets frame the same event.
- Links events to primary-source records (parliamentary data, official documents).
- Flags likely undercovered stories with explainable evidence.

This is NOT a bias-rating app. It is an evidence-first comparison tool.

---

## Tech stack

- Python 3.12
- Postgres + pgvector (vector similarity search)
- trafilatura (article body extraction)
- Ollama (local models: nomic-embed-text:v1.5, qwen2.5:7b-instruct)
- OpenAI Python SDK (used directly for all AI providers — no LiteLLM)
- FastAPI (internal API + review UI)
- Next.js (public frontend — separate from backend)
- APScheduler or cron for service scheduling

---

## Project structure

```
pt-narrative-os/
├── CLAUDE.md
├── tasks.md
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── db/
│   ├── migrations/
│   │   └── 001_initial.sql      ← all schemas
│   └── seed/
│       └── outlets.sql           ← 20 Portuguese outlets + owners
├── services/
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── feed_reader.py        ← RSS/Atom ingestion
│   │   └── institutional.py      ← AR open data ingestion
│   ├── normalization/
│   │   └── parser.py             ← trafilatura + language detection + Lusa regex
│   ├── clustering/
│   │   ├── embedder.py           ← batch embedding via Ollama
│   │   └── clusterer.py          ← assign articles to events
│   ├── analysis/
│   │   └── article_analyzer.py   ← entity/claim/frame extraction
│   ├── enrichment/
│   │   └── enricher.py           ← link source_documents + compute Lusa metrics
│   ├── scoring/
│   │   └── scorer.py             ← coverage_breadth, framing_divergence, evidence_density, undercoverage
│   ├── generation/
│   │   └── generator.py          ← summaries, framing comparison, undercoverage cards
│   └── digest/
│       └── digest_builder.py     ← daily homepage feed
├── ai/
│   ├── __init__.py
│   ├── clients.py                ← AsyncOpenAI clients per provider
│   └── router.py                 ← task → model mapping + call() + fallback
├── prompts/
│   ├── v1_extractor_fast.py      ← entity/claim/frame extraction prompt
│   ├── v1_embedding.py           ← embedding config + prefix
│   ├── v1_summary_fast.py        ← event summary prompt
│   ├── v1_framing_analyst.py     ← framing comparison prompt
│   └── v1_undercoverage_card.py  ← undercoverage explanation prompt
├── api/
│   ├── main.py                   ← FastAPI app
│   └── routes/
│       ├── events.py
│       ├── outlets.py
│       ├── search.py
│       ├── digest.py
│       └── undercoverage.py
├── review/
│   └── app.py                    ← internal review UI (FastAPI + HTMX, HTTP Basic Auth)
├── docs/
│   ├── event-lifecycle.md        ← event + article status state machines
│   └── institutional-sources.md  ← AR + ERC endpoint reference
└── web/
    └── (Next.js public frontend — separate subfolder/repo)
```

---

## AI / Model architecture

### IMPORTANT RULES

- We do NOT use LiteLLM. Do not add it.
- We do NOT use tool-calls / function-calling — use JSON response_format instead.
- We call providers DIRECTLY via AsyncOpenAI with custom base_url and api_key.
- All provider clients are defined in ai/clients.py.
- All task routing is in ai/router.py.

### Provider priority per task

| Task | Primary | Fallback |
|---|---|---|
| Embeddings | Ollama (nomic-embed-text:v1.5) | NVIDIA NIM (nv-embedqa-e5-v5) |
| Fast extraction | Ollama (qwen2.5:7b-instruct) | NVIDIA NIM (llama-3.3-70b-instruct) |
| Framing analysis | NVIDIA NIM (mistral-small-4-119b) | Groq (llama-3.3-70b-versatile) |
| Summaries | NVIDIA NIM (deepseek-r1) | Groq (llama-3.3-70b-versatile) |
| Fallback | OpenRouter (llama-3.3-70b-instruct) | — |

### NVIDIA NIM notes

- Base URL: https://integrate.api.nvidia.com/v1
- API key env var: NVIDIA_NIM_API_KEY
- Free tier: 1,000 credits (~5,000 on request), 40 RPM
- Tool-calling is unreliable on NIM — always use response_format={"type":"json_object"}

### Structured outputs

All AI extraction must return JSON. Always use:
```python
response_format={"type": "json_object"}, temperature=0.1
```

---

## Database

- Postgres with pgvector extension.
- All schemas in db/migrations/001_initial.sql.
- UUIDs for all primary keys (uuid_generate_v4()).
- Timestamps in UTC (TIMESTAMPTZ).
- **Embeddings stored as vector(768)** — nomic-embed-text produces 768-dim vectors.

### Key tables

- **owners** — media company/individual ownership entities
- **outlets** — tracked media sources (with feed_url for RSS ingestion)
- **outlet_ownership** — many-to-many outlet-owner links with confidence
- **raw_items** — raw fetched content (status: pending → parsed → failed → skipped)
- **articles** — normalized content + embeddings (status: pending → embedded → analyzed → failed)
- **article_analysis** — AI extraction results (single JSONB row per article)
- **entities** — deduplicated named entities (person, org, place, law, institution)
- **article_entities** — article-entity links with confidence
- **claims** — extracted quotes/assertions with speaker attribution
- **events** — event clusters (status: candidate → unreviewed → reviewed_published → reviewed_rejected)
- **event_articles** — articles belonging to events with relevance scores
- **source_documents** — parliamentary and official records
- **event_documents** — source docs linked to events
- **event_scores** — per-event scores (coverage_breadth, framing_divergence, evidence_density, lusa_dependency, undercoverage_score)
- **event_summaries** — AI-generated user-facing content (event_summary, framing_comparison, undercoverage_card)
- **undercoverage_flags** — coverage gap flags with reasons
- **ai_runs** — audit trail for every AI call (task, model, provider, latency, cost)
- **daily_digests** — pre-computed homepage feed

### Status flows

See docs/event-lifecycle.md for full state machines.

**Articles**: `pending → embedded → analyzed | failed`
**Events**: `candidate → unreviewed → reviewed_published | reviewed_rejected`

Events are only published (is_published=TRUE) after human review via the review UI.

---

## Services

Each service is a standalone Python module in services/.

| Service | Trigger | Input → Output |
|---|---|---|
| ingestion | cron 15–30min | feeds → raw_items |
| normalization | poll raw_items pending | raw_items → articles |
| clustering | poll articles without embedding | articles → embeddings + events |
| analysis | poll articles with embedding | articles → article_analysis |
| enrichment | poll unreviewed events | events → event_documents + lusa metrics |
| scoring | poll events without scores | events → event_scores |
| generation | poll unreviewed events with scores | events → event_summaries |
| digest_builder | cron daily 07:00 | events → daily_digests |

---

## What NOT to do

- Do NOT add LiteLLM.
- Do NOT use tool-calls / function-calling on any NIM-routed task.
- Do NOT expose raw article HTML or API keys in any API response.
- Do NOT auto-publish events without is_reviewed = TRUE.
- Do NOT label outlets with ideological scores in V1.
- Do NOT add social media monitoring in V1.
- Do NOT add TV stream capture in V1.
- Do NOT add browser extensions in V1.
- Do NOT treat ERC ownership data as ground truth — always show confidence level.
- Do NOT add object storage or search index in V1 — Postgres only.

---

## Environment variables (.env)

See .env.example for the complete list. Key variables:

```
DATABASE_URL=postgresql://ptmedia:ptmedia@localhost:5432/pt_media_os
OLLAMA_HOST=http://localhost:11434
NVIDIA_NIM_API_KEY=nvapi-...
GROQ_API_KEY=gsk_...
OPENROUTER_API_KEY=sk-or-...
REVIEW_USERNAME=admin
REVIEW_PASSWORD_HASH=...
```

---

## Code style

- Async everywhere (asyncio, asyncpg or SQLAlchemy async).
- Type hints on all function signatures.
- Each service has its own module — no shared mutable globals.
- Keep prompts in prompts/ subfolder — never hardcoded in logic.
- Log errors per-item; never let one failure crash the whole batch.
- Every AI call must create an ai_runs row for auditability.
- Prompt versions are tracked in prompts/ filenames (v1_, v2_, etc.) and logged in ai_runs.prompt_version.
