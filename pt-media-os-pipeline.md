# Portugal Narrative OS — V1 Pipeline Services

_Last updated: 2026-04-25_

---

## Overview

The pipeline is a sequence of async services, each reading from and writing to Postgres. Services are triggered either on a schedule or by checking for unprocessed rows. No heavy message bus in V1 — simple Postgres-based job queues are enough.

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Ingestion   │──▶│ Normalization│──▶│  Clustering   │──▶│   Analysis   │
│  Service     │   │  Service     │   │  Service      │   │  Service     │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
                                                          │
        ┌──────────────┐   ┌──────────────┐   ┌──────────▼─────┐
        │    Digest    │◀──│   Scoring    │◀──│  Enrichment    │
        │  Builder     │   │  Service     │   │  Service       │
        └──────────────┘   └──────────────┘   └────────────────┘
                                  │
                          ┌───────▼───────┐
                          │  Generation   │
                          │  Service      │
                          └───────────────┘
```

Each service is a standalone Python module that can be run as a cron job or a daemon.

---

## Service 1 — Ingestion

**Purpose**: Fetch raw content from all active outlets and institutional sources.

**Trigger**: Cron every 15–30 minutes for news outlets; every 2–6 hours for institutional sources.

**Output**: Rows in `raw_items` with status `pending`; rows in `source_documents`.

### Steps

1. Load all active outlets from `outlets` table.
2. For each outlet with a `feed_url`, fetch and parse RSS/Atom/JSON feed.
3. For each item in the feed:
   a. Compute SHA256 of canonical URL.
   b. Skip if `url_hash` already in `raw_items` (dedup by url_hash).
   c. Fetch full article HTML (if needed).
   d. Insert into `raw_items` with status `pending`.
4. For outlets without `feed_url`, attempt `/sitemap.xml` parsing.
5. For institutional sources (AR open data):
   a. Fetch latest XML/JSON from AR endpoints (see docs/institutional-sources.md).
   b. Parse into `source_documents` records.
   c. Skip if already present (dedup by `source_type` + `external_id`).

### Error handling

- Per-outlet failure should not stop the run.
- Log errors per outlet; mark `raw_items` rows as `failed` with error_msg.
- Retry failed outlets on next run.

### Key rules

- Always respect robots.txt and reasonable rate limits.
- Store full raw HTML in `raw_items.raw_html` for future reprocessing.
- Never deduplicate on title — URLs only.
- Lusa wire content republished across outlets with DIFFERENT URLs is NOT deduplicated — this is the comparison point.

---

## Service 2 — Normalization

**Purpose**: Extract clean text, metadata, and prepare articles for analysis.

**Trigger**: Poll `raw_items` where `status = 'pending'`.

**Output**: Rows in `articles` with status `pending`.

### Steps

1. Load a batch of `raw_items` with status `pending` (batch size from env: `NORMALIZATION_BATCH_SIZE`).
2. For each item:
   a. Extract article body using trafilatura.
   b. Detect language (confirm Portuguese or skip).
   c. Extract author, published_at, word_count.
   d. Detect explicit Lusa credit (regex: "Lusa", "agência Lusa", "©Lusa").
   e. Compute SHA256 content_hash of cleaned_text.
   f. Insert into `articles` with status `pending`.
   g. Update `raw_items` status to `parsed`.
3. Skip items with `word_count < 80` (too short to be substantive). Mark as `skipped`.

### Tools

- trafilatura — best-in-class article extraction for Portuguese content.
- langdetect or lingua — language detection.
- Simple regex for Lusa citation detection.

---

## Service 3 — Embedding & Clustering

**Purpose**: Generate embeddings and cluster articles into events.

**Trigger**: Poll `articles` where `status = 'pending'` AND `embedding IS NULL`.

**Output**: Updated `articles.embedding`; new or updated rows in `events` and `event_articles`.

### 3a — Embedding

1. Load batch of articles without embeddings (batch size from env: `EMBEDDING_BATCH_SIZE`).
2. Call embedding model (Ollama nomic-embed-text, fallback NIM).
   - Use `search_document: ` prefix per prompts/v1_embedding.py.
   - Text = prefix + title + " — " + first 512 chars of body.
3. Store vector in `articles.embedding` (vector(768)).
4. Also check similarity to known Lusa wires:
   a. Find nearest Lusa article by cosine similarity.
   b. If similarity > `LUSA_SIMILARITY_THRESHOLD` (0.88) and not already citing Lusa, set `lusa_likely = TRUE`.
5. Update `articles.status` to `'embedded'`.

### 3b — Clustering

1. Load all articles from the last 72 hours with embeddings that are not yet in `event_articles`.
2. For each new article, find existing events whose centroid is within cosine distance threshold (`CLUSTERING_SIMILARITY_THRESHOLD` = 0.85):
   a. Also check that the article's `published_at` is within 72 hours of the event's `first_seen_at`.
3. If a close event exists:
   a. Add article to event via `event_articles` with `relevance_score`.
   b. Recompute event centroid (average of all member article embeddings).
   c. Update `article_count` and `outlet_count` on the event.
   d. Update `first_seen_at` and `last_seen_at` if needed.
4. If no close event:
   a. Create a new `events` row with status `candidate`.
   b. Add article as first member via `event_articles`.
5. Events with only 1 article after 6 hours stay as candidate events (not promoted until scoring criteria met).

### Clustering parameters (from .env)

- `CLUSTERING_SIMILARITY_THRESHOLD`: 0.85 cosine similarity for same-event match.
- `CLUSTERING_TIME_WINDOW_HOURS`: only cluster articles published within 72 hours.
- `CLUSTERING_MIN_ARTICLES`: 2 (minimum articles to promote event from candidate).
- `CLUSTERING_MIN_OUTLETS`: 2 (minimum distinct outlets for event promotion).

---

## Service 4 — Article Analysis

**Purpose**: Extract entities, quotes, topics, source signals, and framing from each article.

**Trigger**: Poll `articles` where `status = 'embedded'` AND no row in `article_analysis`.

**Output**: Rows in `article_analysis`, `entities`, `article_entities`, `claims`.

### Steps

For each article:

1. Build analysis prompt with article title + body using prompts/v1_extractor_fast.py.
2. Call extractor_fast model (Ollama mistral, fallback NIM Llama 3.3 70B).
3. Use JSON output mode: `response_format={"type": "json_object"}, temperature=0.1`.
4. Parse and validate JSON response. Expected schema:

```json
{
  "persons": [{"name": "", "role": "", "sentiment": "positive|neutral|negative"}],
  "organizations": [{"name": "", "type": ""}],
  "topics": [{"label": "", "confidence": 0.0}],
  "quotes": [{"text": "", "speaker": "", "speaker_type": "official|expert|anonymous|unknown"}],
  "cites_document": true,
  "document_refs": [{"type": "law|vote|report|decree|resolution|other", "label": "", "url_hint": ""}],
  "source_types": ["official", "expert"],
  "stance_flags": [{"entity": "", "polarity": "positive|neutral|negative", "confidence": 0.0}],
  "loaded_terms": [{"term": "", "context": ""}],
  "frame_labels": [{"label": "conflict|economic|human_interest|procedural|morality|governance", "confidence": 0.0}]
}
```

5. Insert full JSON into `article_analysis.analysis_json`.
6. Upsert extracted entities into `entities` table (exact lowercase name match for dedup).
   - If entity exists, increment `mention_count`.
   - Insert `article_entities` row with confidence.
7. Insert claims/quotes into `claims` table.
8. Create `ai_runs` row for auditability (task_name, provider, model, latency, tokens, prompt_version).
9. Update `articles.status` to `'analyzed'`.

---

## Service 5 — Enrichment

**Purpose**: Link events to source documents; compute Lusa dependency.

**Trigger**: Poll `events` where `status IN ('candidate', 'unreviewed')` AND no rows in `event_documents`.

**Output**: Rows in `event_documents`; updated `event_scores.lusa_dependency`.

### Steps

1. For each qualifying event:
   a. Collect all topics and entities from its articles (via `article_analysis` and `article_entities`).
   b. Query `source_documents` by topic/entity text match and time overlap (±7 days of event window).
   c. Score relevance; insert top matches into `event_documents` with `matched_by` field.
2. Compute lusa_dependency:
   - `(articles_lusa_likely + articles_lusa_cited) / total_articles_in_event`
   - Store in `event_scores.lusa_dependency` (create row if not exists).

---

## Service 6 — Scoring

**Purpose**: Compute all event-level scores; promote candidate events; flag undercoverage.

**Trigger**: Poll events where `event_scores.id IS NULL` OR `event_scores.computed_at < events.updated_at`.

**Output**: Rows in `event_scores`; rows in `undercoverage_flags` (when triggered); event status promotion.

### Score computation

#### Coverage breadth
```
outlets_covering = count distinct outlet_id in event_articles
total_tracked = count active outlets
coverage_breadth = outlets_covering / total_tracked
```

#### Framing divergence
1. Collect `frame_labels` from `article_analysis` for all articles in event.
2. Measure variance across outlets:
   - High variance in frame labels = high divergence.
   - Agreement (all "conflict" or all "economic") = low divergence.
3. Normalize 0.0–1.0.

#### Evidence density
```
articles_with_docs = count articles where cites_document = TRUE
evidence_density = articles_with_docs / total_articles_in_event
```

#### Undercoverage signal

Flag event as undercovered if ANY of:
- `coverage_breadth < 0.25` AND event has 1+ linked `source_document`
- Event appears only in institutional source + 1 outlet
- `lusa_silent`: Lusa has no known wire for this event type/topic in same window AND event has substantive institutional backing

When undercoverage is flagged:
1. Compute `undercoverage_score` (0-1 composite).
2. Insert row into `undercoverage_flags` with reason, flag_type, and silent_outlets.

### Event promotion

After scoring, check if candidate events should be promoted:
- `article_count >= CLUSTERING_MIN_ARTICLES` (default: 2)
- `outlet_count >= CLUSTERING_MIN_OUTLETS` (default: 2)
- Event created > 6 hours ago
- `event_scores` row exists

If all criteria met: set `status = 'unreviewed'`.

---

## Service 7 — Generation

**Purpose**: Generate user-facing summaries, framing comparisons, and undercoverage cards.

**Trigger**: Poll events where `is_reviewed = FALSE` AND `event_scores` exists AND `event_summaries` incomplete.

**Output**: Rows in `event_summaries`.

### 7a — Event summary

1. Collect: event title, top articles (title + excerpt), linked documents.
2. Call summary_fast model (NIM Llama 3.3 70B, Groq fallback).
3. Prompt from prompts/v1_summary_fast.py.
4. Insert as `summary_type = 'event_summary'`.

### 7b — Framing comparison

1. Collect article titles + first 200 chars per outlet.
2. Call framing_analyst model (NIM Mistral-Small, Groq fallback).
3. Prompt from prompts/v1_framing_analyst.py.
4. Insert as `summary_type = 'framing_comparison'`.

### 7c — Undercoverage card (only if undercoverage_flag exists)

1. Collect undercoverage_flag reason + linked document title + silent outlets.
2. Call summary_premium model (NIM DeepSeek R1, Groq fallback).
3. Prompt from prompts/v1_undercoverage_card.py.
4. Insert as `summary_type = 'undercoverage_card'`.

All generation calls:
- Use `response_format={"type": "json_object"}, temperature=0.1`.
- Create `ai_runs` rows for auditability.
- Store `prompt_version` in `event_summaries`.

---

## Service 8 — Digest Builder

**Purpose**: Build the daily homepage feed.

**Trigger**: Cron once daily (07:00 UTC / 08:00 Lisbon time).

**Output**: Row in `daily_digests`.

### Steps

1. Query published events from last 24 hours.
2. Sort by: `coverage_breadth DESC` (top events), `framing_divergence DESC` (most divergent).
3. Separately list `undercoverage_flags` where `is_published = TRUE`.
4. Serialize to JSONB and insert into `daily_digests`.

---

## Review Interface

A minimal internal web UI for a human reviewer before anything goes public:

- **Auth**: HTTP Basic Auth (REVIEW_USERNAME / REVIEW_PASSWORD_HASH from .env).
- List of unreviewed events with scores.
- Click event → see articles, framing, linked docs, and generated summaries.
- Approve → set `status = 'reviewed_published'`, `is_reviewed = TRUE`, `is_published = TRUE`.
- Edit summary inline before publishing.
- Reject → set `status = 'reviewed_rejected'`, `is_reviewed = TRUE`, `is_published = FALSE` with note.
- Request re-generation → delete event_summaries rows, event stays `unreviewed`.
- "New articles since review" badge for published events that received new articles.

This is the single most important trust/quality gate in V1.

---

## Folder Structure

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
│   │   ├── __init__.py
│   │   ├── feed_reader.py
│   │   └── institutional.py
│   ├── normalization/
│   │   └── parser.py
│   ├── clustering/
│   │   ├── embedder.py
│   │   └── clusterer.py
│   ├── analysis/
│   │   └── article_analyzer.py
│   ├── enrichment/
│   │   └── enricher.py
│   ├── scoring/
│   │   └── scorer.py
│   ├── generation/
│   │   └── generator.py
│   └── digest/
│       └── digest_builder.py
├── ai/
│   ├── __init__.py
│   ├── clients.py
│   └── router.py
├── prompts/
│   ├── v1_extractor_fast.py
│   ├── v1_embedding.py
│   ├── v1_summary_fast.py
│   ├── v1_framing_analyst.py
│   └── v1_undercoverage_card.py
├── api/
│   ├── main.py
│   └── routes/
│       ├── events.py
│       ├── outlets.py
│       ├── search.py
│       ├── digest.py
│       └── undercoverage.py
├── review/
│   └── app.py
├── docs/
│   ├── event-lifecycle.md
│   └── institutional-sources.md
└── web/
    └── (Next.js public frontend)
```

---

## Tech Stack Summary

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.12 | AI ecosystem, async support |
| DB | Postgres + pgvector | Relational + vector in one place |
| Article extraction | trafilatura | Best PT content extraction |
| Embeddings | Ollama (nomic-embed-text) | Local, free, fast, 768-dim |
| AI router | Direct AsyncOpenAI SDK | No abstraction overhead |
| Local models | Ollama | nomic-embed-text + mistral |
| Cloud AI | NVIDIA NIM → Groq → OpenRouter | Free tier first |
| API | FastAPI | Fast, async, schema validation |
| Frontend | Next.js | Separate, calls internal API |
| Review UI | FastAPI + HTMX | Simple, internal, HTTP Basic Auth |
| Scheduling | APScheduler or cron | Simple V1 scheduling |
