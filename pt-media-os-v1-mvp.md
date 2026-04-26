# Portugal Narrative OS — Strict V1 MVP

_Last updated: 2026-04-25_

## One-line product

A Portugal-first, text-only media comparison platform that clusters articles by event, compares framing across outlets, links to primary-source records, and flags likely undercovered stories with explainable evidence.

## V1 scope

V1 is deliberately narrow. It does not include TV capture, diarization, commentator graphs, browser extensions, or social-media monitoring.

### Included

- Selected Portuguese news outlets.
- Selected institutional sources: Assembleia da República open data and ERC transparency data.
- Event clustering.
- Framing comparison.
- Undercoverage detection.
- Basic outlet ownership context.
- Lightweight Lusa source tagging.
- Human-readable explainers.
- Human review gate before publication.
- Full AI provenance tracking.

### Excluded for later

- Full TV stream capture.
- Automated commentator ingestion.
- Panel diversity scoring.
- Real-time alerts.
- Personalized news-diet tracking.
- Market-wide ideological labels.
- Object storage (raw HTML in Postgres).
- External search index (Postgres full-text search in V1).

## Primary user

A politically engaged Portuguese reader, journalist, researcher, or political staffer who wants to compare how the same event is covered and inspect the original records behind it.

## Core value

1. Show how the same event is framed differently across Portuguese outlets.
2. Show what the official record says.
3. Show what may be undercovered.
4. Show where every AI-generated claim comes from.

## Core data sources

- Portuguese news outlets (RSS/Atom feeds, sitemap parsing).
- Lusa (detected via explicit credit and embedding similarity).
- Assembleia da República open data (XML/JSON).
- ERC transparency portal (manual entry in V1; automated scraping deferred).
- A limited set of official institutions and reference sources.

## Core workflow

1. Ingest source content.
2. Normalize text and metadata.
3. Cluster articles into events.
4. Compare framing and coverage.
5. Link primary sources.
6. Flag likely coverage gaps.
7. Generate AI summaries (after scoring).
8. Present for human review.
9. Publish approved events to daily feed and public API.

## Minimal features

- Daily feed of top event clusters.
- Event page with source list, short summary, framing comparison, and linked documents.
- Undercovered stories page.
- Outlet page with ownership context and source mix.
- Provenance view: trace any AI output to its model run and source article.
- Simple scoring dimensions:
  - coverage breadth
  - framing divergence
  - evidence density
  - undercoverage likelihood

## Architecture

### Storage

- **Postgres** for all data: entities, metadata, raw HTML, embeddings (pgvector), and full-text search.
- No object storage in V1.
- No external search index in V1.

### Services

| Service | Trigger | Input → Output |
|---|---|---|
| Ingestion | cron 15–30min | feeds → raw_items |
| Normalization | poll raw_items | raw_items → articles |
| Clustering | poll articles | articles → embeddings + events |
| Analysis | poll embedded articles | articles → article_analysis + entities + claims |
| Enrichment | poll events | events → event_documents + lusa metrics |
| Scoring | poll events | events → event_scores + undercoverage_flags |
| Generation | poll scored events | events → event_summaries |
| Review UI | manual | review → publish/reject |
| Digest builder | cron daily | events → daily_digests |

### Auth

- Review UI: HTTP Basic Auth (REVIEW_USERNAME, REVIEW_PASSWORD_HASH).
- Public API: read-only, no auth in V1.

### Later

Keep the schema open for future panels, commentators, and TV ingestion, but do not implement them in V1.

## Success criteria

V1 succeeds if users repeatedly say:

- I can compare coverage faster.
- I can see what is missing.
- I can find the primary source behind the story.
- I can trust the AI output because I can see where it came from.
- This is useful enough to check daily.
