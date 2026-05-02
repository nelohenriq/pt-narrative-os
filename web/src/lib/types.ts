export interface EventListItem {
  id: string;
  canonical_title: string;
  article_count: number;
  outlet_count: number;
  coverage_breadth: number | null;
  framing_divergence: number | null;
  undercoverage_score: number | null;
  status: string;
  first_seen_at: string | null;
  reviewed_at: string | null;
}

export interface EventDetail {
  id: string;
  canonical_title: string;
  article_count: number;
  outlet_count: number;
  status: string;
  is_published: boolean;
  first_seen_at: string | null;
  last_seen_at: string | null;
  scores: EventScores | null;
  summaries: Summary[];
  articles: ArticleRef[];
  documents: DocumentRef[];
}

export interface EventScores {
  coverage_breadth: number;
  framing_divergence: number | null;
  evidence_density: number | null;
  lusa_dependency: number | null;
  undercoverage_score: number | null;
  explanation: string | null;
}

export interface Summary {
  type: string;
  content: string;
  model: string;
  prompt_version: string;
  ai_run_id: string;
}

export interface ArticleRef {
  id: string;
  title: string;
  url: string;
  outlet: string;
  outlet_slug: string;
  published_at: string | null;
  word_count: number;
  lusa_cited: boolean;
  lusa_likely: boolean;
}

export interface DocumentRef {
  id: string;
  title: string;
  source_type: string;
  url: string;
  matched_by: string;
}

export interface OutletItem {
  id: string;
  name: string;
  slug: string;
  type: string;
  website_url: string;
  feed_url: string;
  erc_reference: string;
}

export interface OutletDetail extends OutletItem {
  ownership: Ownership[];
  recent_events: EventListItem[];
}

export interface Ownership {
  owner_name: string;
  owner_slug: string;
  owner_type: string;
  stake_pct: number | null;
  confidence: number | null;
  source: string;
}

export interface UndercoverageFlag {
  id: string;
  event_id: string;
  event_title: string;
  reason: string;
  flag_type: string;
  silent_outlets: string[];
  coverage_breadth: number | null;
  undercoverage_score: number | null;
}

export interface SearchResult {
  query: string;
  events: EventListItem[];
  articles: {
    id: string;
    title: string;
    url: string;
    outlet: string;
    published_at: string | null;
  }[];
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Digest {
  digest_date: string;
  top_events: unknown[];
  undercovered: unknown[];
  metadata: unknown;
}