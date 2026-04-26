# pt-media-os V1 — Full Product Requirements Document (PRD)

_Last updated: 2026-04-25_

## 1. Vision & strategic goal

Build a text-first Portugal media narrative intelligence product that helps users see how the same event is covered differently across outlets and flags likely undercovered angles with evidence. The system should surface subtle differences in framing, emphasis, and omission across Portuguese news sources without depending on live TV capture in V1.

## 2. Scope

### 2.1 In-scope (V1)

- Ingest articles from selected Portuguese online news outlets.
- Normalize and deduplicate content.
- Cluster articles into events.
- Extract entities, quotes, topics, and claims.
- Generate framing and undercoverage scores.
- Produce short AI-generated comparative summaries.
- Store full provenance for every AI result.
- Provide event- and outlet-level views.
- Human review gate before any content goes public.

### 2.2 Out-of-scope (for V1)

- Live TV capture.
- Diarization or speaker identification.
- Commentator stance tracking.
- OAuth or user accounts.
- Model abstraction layers like LiteLLM.
- Multi-language expansion beyond Portuguese.
- Mobile app.
- Object storage (raw HTML stored in Postgres).
- Search index (Postgres full-text search in V1).

These can be considered for future phases.

## 3. Personas

### 3.1 Civic researcher

A journalist, researcher, or policy analyst who studies Portuguese media coverage.

- Goal: compare how different outlets frame a story and identify missing angles.
- Pain points: hard to systematically track coverage across many outlets.

### 3.2 Media watchdog

Someone monitoring media plurality, bias, and transparency.

- Goal: detect patterns of omission, repeated narratives, or one-sided framing.
- Pain points: reactive monitoring without structured data.

### 3.3 Interested citizen

An engaged reader who wants to understand how media covers key events.

- Goal: see a balanced view of how different outlets treat the same story.
- Pain points: echo-chambers and opaque framing.

## 4. User scenarios

### 4.1 Discover and explore an event

1. User goes to a search page.
2. Enters a topic or event name.
3. System returns a list of clustered events.
4. User selects an event and sees all articles, outlet coverage, and key claims.

### 4.2 Compare coverage across outlets

1. User opens an event page.
2. System shows articles grouped by outlet.
3. User can toggle between article text, extracted claims, and AI summaries.
4. System highlights differences in framing, emphasis, and omission.

### 4.3 Investigate undercoverage

1. User reviews an event page.
2. System highlights outlets that barely or never covered the event.
3. System flags likely undercovered story angles.
4. User can explore suggested next questions or missing perspectives.

### 4.4 Trace provenance

1. User reads an AI-generated summary on an event page.
2. User clicks a "provenance" link.
3. System shows the ai_run that produced the output: model, provider, prompt version, latency, input article, raw model response.
4. User can trace every claim back to a specific source article.

## 5. Functional requirements

### 5.1 Ingestion

- The system must ingest articles from a configurable list of Portuguese online outlets.
- The system must store raw text, title, author, canonical URL, publication date, and outlet.
- The system must deduplicate based on URL hash.

### 5.2 Clustering & events

- The system must cluster articles into events based on topic and similarity.
- The system must allow re-clustering as new articles arrive.
- The system must expose a stable event ID for each event.
- Events must go through a review gate before publication.

### 5.3 Entity and claim extraction

- The system must extract named entities (people, organizations, places, laws, institutions).
- The system must extract quote-like claims and attribute them to speakers when possible.
- The system must link claims and entities to the source article.
- Entity deduplication uses exact lowercase name match across articles.

### 5.4 Scoring and framing

- The system must generate framing scores per event and outlet.
- The system must flag events where some outlets appear undercovered.
- The system must provide short, explainable reasons for scores.
- Undercoverage flags must be stored as separate records with reason, flag_type, and silent_outlets.

### 5.5 Summaries and surfaces

- The system must generate short, comparative summaries for each event.
- The system must show an event view with outlet coverage, key claims, and AI-generated explanations.
- The system must allow filtering by outlet, topic, date, and type of claim.
- The system must expose provenance for each AI-generated sentence or claim via the /events/{id}/provenance endpoint.

### 5.6 Review gate

- The system must provide a review interface (internal, HTTP Basic Auth) where a human can approve or reject events before publication.
- Only reviewed and approved events appear in the public API and daily digest.
- Reviewers can edit AI-generated summaries before publishing.
- Reviewers can request re-generation of summaries.

## 6. Non-functional requirements

### 6.1 Performance

- Clustering and AI tasks should complete within minutes for small batches.
- Event page load times should be under 2 seconds for typical events.
- Search should respond within 1 second for common queries.

### 6.2 Reliability

- Ingestion services should be idempotent and resumable.
- AI pipelines should retry transient failures (3 retries with exponential backoff).
- Data should be backed up regularly (pg_dump daily cron).

### 6.3 Auditability and safety

- Every AI-generated output must be traceable to a specific `ai_run` entry.
- Prompts and model metadata must be versioned (v1, v2, etc. in prompt filenames).
- The system should avoid hallucinating entities or claims not grounded in the source text.
- Failed AI runs must be logged with error messages for debugging.

### 6.4 Extensibility

- Sources, outlets, and models should be configured via simple configuration files.
- The schema and pipeline should allow future addition of TV transcript ingestion, commentator profiles, and richer ownership data.
- Embedding dimension (768) is pinned to nomic-embed-text; a migration is needed if switching models.

## 7. Success criteria

### 7.1 User metrics

- Users can reliably identify framing differences across outlets.
- Users can understand which events are undercovered.
- At least 80% of users say the summaries help them see additional angles.

### 7.2 System quality

- The system can cluster 100–1,000 real Portuguese articles into meaningful events.
- The system can generate explainable summaries with at least 90% factual grounding in the source text.
- AI-generated outputs are always traceable to raw articles and model runs.

## 8. Acceptance criteria

- Event page renders for at least 10 real Portuguese events with at least 3 articles each.
- Each event page shows coverage by outlet and extracted claims.
- Each event page includes at least one AI-generated comparison summary.
- Undercoverage flags are visible for events where some outlets are clearly missing.
- Every AI-generated sentence or claim can be traced back to an article and an `ai_run` record.
- The provenance endpoint returns model, provider, prompt version, and latency for each AI output.
- The review UI requires authentication and prevents unapproved events from appearing publicly.

## 9. Milestones

### 9.1 Phase 0 — Setup

- Define final schema (001_initial.sql).
- Create database and migrations.
- Set up local Ollama and at least one hosted provider (NIM or Groq).
- Implement basic ingestion for 3–5 Portuguese outlets.

### 9.2 Phase 1 — Core pipeline

- Implement article normalization and deduplication.
- Implement event clustering.
- Implement basic entity and claim extraction.
- Implement basic scoring and undercoverage flags.
- Implement AI-generated summaries.

### 9.3 Phase 2 — Quality and UX

- Improve summarization and framing quality.
- Build the event and outlet comparison UI.
- Add filtering and search.
- Polish the provenance view.
- Begin user testing with personas.

### 9.4 Future phases (out of V1 scope)

- TV transcript ingestion.
- Commentator profiles and stance tracking.
- Browser extension.
- Advanced exports and API.
- Multi-language expansion.
- Institutional dashboards.

## 10. Assumptions and constraints

- V1 focuses on text; TV capture is deferred.
- Models are called directly, not via abstraction layers.
- Portuguese is the primary language.
- The system assumes a small-to-medium initial dataset (hundreds to thousands of articles).
- The team has access to local GPU resources or at least Ollama.
- Embedding dimension is 768 (nomic-embed-text).
- Postgres only for V1 storage — no object storage or external search index.

## 11. Versioning and change history

- Version: 0.2 (V1 PRD with audit fixes).
- Last updated: 2026-04-25.
- Author: project team.
- Changes from 0.1: added provenance user scenario (4.4), added review gate functional requirement (5.6), added provenance API endpoint, added review UI auth requirement, clarified undercoverage flag storage, pinned embedding dimension to 768, removed object storage and search index from V1 scope, added entity dedup strategy.
