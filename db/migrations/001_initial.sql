-- pt-media-os V1 — Initial Schema
-- Postgres 15+ with pgvector extension
-- Last updated: 2026-04-25

-- ============================================================================
-- EXTENSIONS
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================================
-- ENUMS
-- ============================================================================

CREATE TYPE raw_item_status AS ENUM ('pending', 'parsed', 'failed', 'skipped');

CREATE TYPE article_status AS ENUM ('pending', 'embedded', 'analyzed', 'failed');

CREATE TYPE event_status AS ENUM ('candidate', 'unreviewed', 'reviewed_published', 'reviewed_rejected');

CREATE TYPE entity_type AS ENUM ('person', 'organization', 'place', 'law', 'institution');

CREATE TYPE claim_type AS ENUM ('quote', 'assertion', 'statistic', 'allegation', 'denial');

CREATE TYPE speaker_type AS ENUM ('official', 'expert', 'anonymous', 'unknown');

CREATE TYPE document_ref_type AS ENUM ('law', 'vote', 'report', 'decree', 'resolution', 'other');

CREATE TYPE source_document_type AS ENUM ('parliamentary', 'regulatory', 'government', 'judicial', 'erc');

CREATE TYPE summary_type AS ENUM ('event_summary', 'framing_comparison', 'undercoverage_card');

CREATE TYPE outlet_type AS ENUM ('newspaper', 'news_site', 'tv_online', 'radio_online', 'agency', 'magazine');

CREATE TYPE ai_run_status AS ENUM ('pending', 'completed', 'failed');

-- ============================================================================
-- OWNERSHIP LAYER
-- ============================================================================

CREATE TABLE owners (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,
    owner_type      TEXT,  -- 'person', 'company', 'group', 'state'
    country         TEXT DEFAULT 'PT',
    erc_reference   TEXT,  -- ERC registry ID if available
    confidence      REAL DEFAULT 0.5,  -- confidence in ownership data (0-1)
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE outlets (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,
    country         TEXT NOT NULL DEFAULT 'PT',
    language        TEXT NOT NULL DEFAULT 'pt',
    outlet_type     outlet_type NOT NULL DEFAULT 'newspaper',
    website_url     TEXT NOT NULL,
    feed_url        TEXT,  -- RSS/Atom feed URL — used by ingestion service
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    erc_reference   TEXT,  -- ERC registry reference
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE outlet_ownership (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    outlet_id       UUID NOT NULL REFERENCES outlets(id) ON DELETE CASCADE,
    owner_id        UUID NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
    stake_pct       REAL,  -- percentage of ownership (0-100), NULL if unknown
    effective_date  DATE,
    source          TEXT,  -- where this data came from (ERC, public records, etc.)
    confidence      REAL DEFAULT 0.5,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(outlet_id, owner_id)
);

-- ============================================================================
-- INGESTION LAYER
-- ============================================================================

CREATE TABLE raw_items (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    outlet_id       UUID NOT NULL REFERENCES outlets(id) ON DELETE CASCADE,
    canonical_url   TEXT NOT NULL,
    url_hash        TEXT NOT NULL,  -- SHA256 of canonical_url, for dedup
    title           TEXT,
    raw_html        TEXT,  -- full HTML for future reprocessing
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at    TIMESTAMPTZ,
    status          raw_item_status NOT NULL DEFAULT 'pending',
    error_msg       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(url_hash)
);

-- ============================================================================
-- ARTICLES LAYER
-- ============================================================================

CREATE TABLE articles (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_item_id     UUID REFERENCES raw_items(id) ON DELETE SET NULL,
    outlet_id       UUID NOT NULL REFERENCES outlets(id) ON DELETE CASCADE,
    canonical_url   TEXT NOT NULL UNIQUE,
    url_hash        TEXT NOT NULL,  -- SHA256 of canonical_url
    content_hash    TEXT,  -- SHA256 of cleaned_text, for content dedup
    title           TEXT NOT NULL,
    author          TEXT,
    published_at    TIMESTAMPTZ,
    raw_text        TEXT,  -- raw extracted text before cleaning
    cleaned_text    TEXT NOT NULL,  -- trafilatura-extracted body
    language        TEXT NOT NULL DEFAULT 'pt',
    word_count      INTEGER,
    lusa_cited      BOOLEAN NOT NULL DEFAULT FALSE,  -- explicit "Lusa"/"agência Lusa" credit detected
    lusa_likely     BOOLEAN NOT NULL DEFAULT FALSE,  -- similarity to known Lusa wire > 0.88
    embedding       vector(768),  -- nomic-embed-text produces 768-dim vectors
    status          article_status NOT NULL DEFAULT 'pending',
    error_msg       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- EVENTS LAYER
-- ============================================================================

CREATE TABLE events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    canonical_title TEXT NOT NULL,
    centroid        vector(768),  -- recomputed as articles are added/removed
    first_seen_at   TIMESTAMPTZ,  -- min(published_at) of member articles
    last_seen_at    TIMESTAMPTZ,  -- max(published_at) of member articles
    article_count   INTEGER NOT NULL DEFAULT 0,  -- denormalized count
    outlet_count    INTEGER NOT NULL DEFAULT 0,  -- denormalized count of distinct outlets
    status          event_status NOT NULL DEFAULT 'candidate',
    is_reviewed     BOOLEAN NOT NULL DEFAULT FALSE,
    is_published    BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_at     TIMESTAMPTZ,
    reviewed_by     TEXT,  -- reviewer identifier (basic auth username)
    review_note     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE event_articles (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id        UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    article_id      UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    relevance_score REAL,  -- cosine similarity to event centroid
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(event_id, article_id)
);

-- ============================================================================
-- ENTITY AND CLAIM EXTRACTION
-- ============================================================================

CREATE TABLE entities (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    entity_type     entity_type NOT NULL,
    canonical_slug  TEXT NOT NULL UNIQUE,
    mention_count   INTEGER NOT NULL DEFAULT 0,  -- denormalized total across all articles
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE article_entities (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    article_id      UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    entity_id       UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    mention_count   INTEGER NOT NULL DEFAULT 1,
    confidence      REAL NOT NULL DEFAULT 0.5,
    ai_run_id       UUID,  -- provenance: which AI run extracted this
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(article_id, entity_id)
);

CREATE TABLE claims (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    article_id      UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    event_id        UUID REFERENCES events(id) ON DELETE SET NULL,  -- set after clustering
    claim_text      TEXT NOT NULL,
    claim_type      claim_type NOT NULL DEFAULT 'assertion',
    speaker         TEXT,
    speaker_type    speaker_type NOT NULL DEFAULT 'unknown',
    attribution_text TEXT,  -- raw attribution from article ("segundo o ministro...")
    confidence      REAL NOT NULL DEFAULT 0.5,
    ai_run_id       UUID,  -- provenance
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- ARTICLE ANALYSIS (AI extraction results — single JSON blob per article)
-- ============================================================================

CREATE TABLE article_analysis (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    article_id      UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    ai_run_id       UUID NOT NULL,  -- provenance: always trace to a run
    analysis_json   JSONB NOT NULL,  -- full extraction result (see pipeline doc schema)
    persons         JSONB,  -- extracted persons array
    organizations   JSONB,  -- extracted organizations array
    topics          JSONB,  -- extracted topics array
    quotes          JSONB,  -- extracted quotes array
    source_types    JSONB,  -- ["official", "expert", ...]
    stance_flags    JSONB,  -- entity polarity flags
    loaded_terms    JSONB,  -- loaded/loaded language terms
    frame_labels    JSONB,  -- frame classification labels
    cites_document  BOOLEAN DEFAULT FALSE,
    document_refs   JSONB,  -- [{type, label, url_hint}, ...]
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(article_id)  -- one analysis per article; re-analysis replaces
);

-- ============================================================================
-- SOURCE DOCUMENTS (institutional records)
-- ============================================================================

CREATE TABLE source_documents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_type     source_document_type NOT NULL,
    title           TEXT NOT NULL,
    external_id     TEXT,  -- ID in the original system (e.g., AR document ID)
    canonical_url   TEXT,
    published_at    TIMESTAMPTZ,
    body_text       TEXT,
    metadata        JSONB,  -- flexible: vote results, ERC fields, etc.
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_type, external_id)
);

CREATE TABLE event_documents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id        UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    document_id     UUID NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
    relevance_score REAL,
    matched_by      TEXT,  -- 'topic', 'entity', 'time_overlap'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(event_id, document_id)
);

-- ============================================================================
-- SCORING
-- ============================================================================

CREATE TABLE event_scores (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id        UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    coverage_breadth    REAL,  -- outlets_covering / total_active_outlets (0-1)
    framing_divergence  REAL,  -- variance in frame_labels across outlets (0-1)
    evidence_density    REAL,  -- articles_citing_documents / total_articles (0-1)
    lusa_dependency     REAL,  -- (lusa_likely + lusa_cited) / total_articles (0-1)
    undercoverage_score REAL,  -- composite undercoverage signal (0-1)
    explanation     TEXT,  -- short explainable reason for scores
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(event_id)  -- one score row per event; recompute replaces
);

-- ============================================================================
-- UNDERCOVERAGE FLAGS
-- ============================================================================

CREATE TABLE undercoverage_flags (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id        UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    reason          TEXT NOT NULL,  -- e.g. "low coverage breadth with institutional backing"
    flag_type       TEXT NOT NULL,  -- 'low_breadth', 'lusa_silent', 'institutional_only'
    silent_outlets  JSONB,  -- list of outlet slugs that did not cover this event
    linked_document_id UUID REFERENCES source_documents(id) ON DELETE SET NULL,
    is_published    BOOLEAN NOT NULL DEFAULT FALSE,  -- only show after event review
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- EVENT SUMMARIES (AI-generated user-facing content)
-- ============================================================================

CREATE TABLE event_summaries (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id        UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    summary_type    summary_type NOT NULL,
    content         TEXT NOT NULL,
    ai_run_id       UUID NOT NULL,  -- provenance: always trace to a run
    model_name      TEXT NOT NULL,  -- which model generated this
    prompt_version  TEXT NOT NULL,  -- which prompt version was used
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(event_id, summary_type)  -- one summary of each type per event
);

-- ============================================================================
-- AI RUNS (audit trail for every AI call)
-- ============================================================================

CREATE TABLE ai_runs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_name       TEXT NOT NULL,  -- e.g. 'extract_entities', 'generate_summary'
    provider        TEXT NOT NULL,  -- 'ollama', 'nvidia_nim', 'groq', 'openrouter'
    model_name      TEXT NOT NULL,  -- e.g. 'nomic-embed-text', 'mistral-small-4-119b'
    article_id      UUID REFERENCES articles(id) ON DELETE SET NULL,
    event_id        UUID REFERENCES events(id) ON DELETE SET NULL,
    prompt_version  TEXT NOT NULL,
    prompt_hash     TEXT,  -- SHA256 of the rendered prompt
    input_token_count  INTEGER,
    output_token_count INTEGER,
    latency_ms      INTEGER,
    cost_estimate   REAL,  -- estimated cost in USD
    status          ai_run_status NOT NULL DEFAULT 'pending',
    error_message   TEXT,
    temperature     REAL,
    response_format JSONB,  -- e.g. {"type": "json_object"}
    raw_response    JSONB,  -- store raw model output for debugging
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- DAILY DIGESTS
-- ============================================================================

CREATE TABLE daily_digests (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    digest_date     DATE NOT NULL,
    top_events      JSONB NOT NULL,  -- ordered list of top event IDs + metadata
    undercovered    JSONB,  -- list of published undercoverage flags
    metadata        JSONB,  -- summary stats, counts, etc.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(digest_date)
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Primary query patterns
CREATE INDEX idx_outlets_slug ON outlets(slug);
CREATE INDEX idx_outlets_active ON outlets(active) WHERE active = TRUE;

CREATE INDEX idx_raw_items_status ON raw_items(status);
CREATE INDEX idx_raw_items_outlet ON raw_items(outlet_id);
CREATE INDEX idx_raw_items_url_hash ON raw_items(url_hash);

CREATE INDEX idx_articles_status ON articles(status);
CREATE INDEX idx_articles_outlet ON articles(outlet_id);
CREATE INDEX idx_articles_published_at ON articles(published_at DESC NULLS LAST);
CREATE INDEX idx_articles_url_hash ON articles(url_hash);
CREATE INDEX idx_articles_content_hash ON articles(content_hash) WHERE content_hash IS NOT NULL;
CREATE INDEX idx_articles_lusa_cited ON articles(lusa_cited) WHERE lusa_cited = TRUE;
CREATE INDEX idx_articles_lusa_likely ON articles(lusa_likely) WHERE lusa_likely = TRUE;

-- Vector similarity index (HNSW for V1 scale)
CREATE INDEX idx_articles_embedding ON articles
    USING hnsw (embedding vector_cosine_ops)
    WITH (ef_construction = 64, m = 16)
    WHERE embedding IS NOT NULL;

CREATE INDEX idx_events_status ON events(status);
CREATE INDEX idx_events_published ON events(is_published) WHERE is_published = TRUE;
CREATE INDEX idx_events_reviewed ON events(is_reviewed) WHERE is_reviewed = FALSE;
CREATE INDEX idx_events_first_seen ON events(first_seen_at DESC);
CREATE INDEX idx_events_centroid ON events
    USING hnsw (centroid vector_cosine_ops)
    WITH (ef_construction = 64, m = 16)
    WHERE centroid IS NOT NULL;

CREATE INDEX idx_event_articles_event ON event_articles(event_id);
CREATE INDEX idx_event_articles_article ON event_articles(article_id);

CREATE INDEX idx_entities_slug ON entities(canonical_slug);
CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_name_gin ON entities USING gin(to_tsvector('portuguese', name));

CREATE INDEX idx_article_entities_article ON article_entities(article_id);
CREATE INDEX idx_article_entities_entity ON article_entities(entity_id);

CREATE INDEX idx_claims_article ON claims(article_id);
CREATE INDEX idx_claims_event ON claims(event_id) WHERE event_id IS NOT NULL;

CREATE INDEX idx_article_analysis_article ON article_analysis(article_id);

CREATE INDEX idx_source_documents_type ON source_documents(source_type);
CREATE INDEX idx_source_documents_external ON source_documents(source_type, external_id);
CREATE INDEX idx_source_documents_published ON source_documents(published_at DESC NULLS LAST);

CREATE INDEX idx_event_documents_event ON event_documents(event_id);

CREATE INDEX idx_event_scores_event ON event_scores(event_id);

CREATE INDEX idx_undercoverage_flags_event ON undercoverage_flags(event_id);
CREATE INDEX idx_undercoverage_flags_published ON undercoverage_flags(is_published) WHERE is_published = TRUE;

CREATE INDEX idx_event_summaries_event ON event_summaries(event_id);
CREATE INDEX idx_event_summaries_type ON event_summaries(event_id, summary_type);

CREATE INDEX idx_ai_runs_task ON ai_runs(task_name);
CREATE INDEX idx_ai_runs_article ON ai_runs(article_id) WHERE article_id IS NOT NULL;
CREATE INDEX idx_ai_runs_event ON ai_runs(event_id) WHERE event_id IS NOT NULL;
CREATE INDEX idx_ai_runs_status ON ai_runs(status);
CREATE INDEX idx_ai_runs_created ON ai_runs(created_at DESC);

CREATE INDEX idx_daily_digests_date ON daily_digests(digest_date DESC);

-- ============================================================================
-- TRIGGER: auto-update updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_outlets_updated BEFORE UPDATE ON outlets
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_raw_items_updated BEFORE UPDATE ON raw_items
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_articles_updated BEFORE UPDATE ON articles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_events_updated BEFORE UPDATE ON events
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_entities_updated BEFORE UPDATE ON entities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_source_documents_updated BEFORE UPDATE ON source_documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
