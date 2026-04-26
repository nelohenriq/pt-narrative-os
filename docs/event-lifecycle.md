# pt-media-os V1 — Event Lifecycle & Article Status Flow

_Last updated: 2026-04-25_

---

## Article Status Flow

```
                  ┌──────────┐
                  │ pending  │  ← created by normalization service
                  └────┬─────┘
                       │ embedding service computes vector
                       ▼
                  ┌──────────┐
                  │ embedded │  ← embedding stored, ready for analysis
                  └────┬─────┘
                       │ analysis service extracts entities/claims/frames
                       ▼
              ┌────────┴────────┐
              │                 │
         ┌────▼─────┐    ┌─────▼────┐
         │ analyzed │    │  failed  │
         └──────────┘    └──────────┘
```

### Status definitions

| Status | Meaning | Who sets it | Next states |
|---|---|---|---|
| `pending` | Article normalized but not yet embedded | Normalization service | `embedded`, `failed` |
| `embedded` | Embedding computed and stored | Embedding service | `analyzed`, `failed` |
| `analyzed` | AI extraction complete (entities, claims, frames) | Analysis service | terminal |
| `failed` | Processing failed after retries | Any service (on error) | can be reset to `pending` for reprocessing |

### Retry policy
- A service that encounters a transient error (network, rate limit) retries 3 times with exponential backoff.
- After 3 failures, status is set to `failed` with `error_msg` populated.
- Failed articles can be reset to `pending` via the review UI or a manual script to trigger reprocessing.

### What each service polls for

| Service | Poll condition |
|---|---|
| Embedding | `status = 'pending' AND embedding IS NULL` |
| Analysis | `status = 'embedded' AND article_analysis.id IS NULL` |
| Clustering | `status = 'embedded' AND event_articles.id IS NULL` |

---

## Event Status Flow

```
  ┌───────────┐
  │ candidate  │  ← 1 article, <6 hours old
  └─────┬──────┘
        │ 6 hours pass AND article_count >= 2 AND outlet_count >= 2
        ▼
  ┌───────────┐
  │ unreviewed │  ← meets minimum criteria, awaiting human review
  └─────┬──────┘
        │ reviewer action
   ┌────┴─────┐
   │          │
   ▼          ▼
┌──────────────────────┐   ┌──────────────────────┐
│ reviewed_published    │   │ reviewed_rejected     │
│ is_reviewed=TRUE      │   │ is_reviewed=TRUE      │
│ is_published=TRUE     │   │ is_published=FALSE     │
└──────────────────────┘   └──────────────────────┘
```

### Status definitions

| Status | is_reviewed | is_published | Meaning |
|---|---|---|---|
| `candidate` | FALSE | FALSE | Newly created event with <2 articles from <2 outlets, or <6h old |
| `unreviewed` | FALSE | FALSE | Meets minimum criteria (2+ articles from 2+ outlets, 6+ hours old), awaiting review |
| `reviewed_published` | TRUE | TRUE | Reviewed and approved for public display |
| `reviewed_rejected` | TRUE | FALSE | Reviewed but rejected — not shown publicly |

### Promotion rules (candidate → unreviewed)

An event is promoted from `candidate` to `unreviewed` when ALL of:
1. `article_count >= 2`
2. `outlet_count >= 2` (at least 2 distinct outlets)
3. At least 6 hours since the event was created
4. Scoring service has computed `event_scores` for this event

This check runs as part of the scoring service — after computing scores, it checks if the event should be promoted.

### Review actions

Via the review UI (requires HTTP Basic Auth):

| Action | Effect |
|---|---|
| **Approve** | Set `status = 'reviewed_published'`, `is_reviewed = TRUE`, `is_published = TRUE`, `reviewed_at = now()`, `reviewed_by = <username>` |
| **Reject** | Set `status = 'reviewed_rejected'`, `is_reviewed = TRUE`, `is_published = FALSE`, `reviewed_at = now()`, `reviewed_by = <username>`, `review_note = <reason>` |
| **Edit summary** | Modify the `event_summaries` row in-place before approving |
| **Request re-generation** | Delete `event_summaries` rows, reset event to `unreviewed` — generation service will re-run |

### Downgrade (published → unreviewed)

If new articles are added to a published event after its review:
- The event stays `reviewed_published` but `is_reviewed` is NOT automatically changed.
- The review UI shows a "new articles since review" badge.
- A reviewer can choose to re-review and re-approve, or leave the event as-is.

### What happens to never-reviewed events

Events that remain in `unreviewed` for more than 7 days:
- They stay in the database but are flagged as stale in the review UI.
- No automatic deletion — the reviewer can still approve them.
- The digest builder only includes `is_published = TRUE` events.

---

## Pipeline Trigger Mechanism

Services use Postgres-based polling (no message queue in V1):

| Service | Trigger | Poll interval |
|---|---|---|
| Ingestion | Cron schedule | 30 min |
| Normalization | Poll `raw_items.status = 'pending'` | 5 min |
| Embedding | Poll `articles.status = 'pending' AND embedding IS NULL` | 5 min |
| Clustering | Poll `articles.status = 'embedded' AND NOT in event_articles` | 5 min |
| Analysis | Poll `articles.status = 'embedded' AND NOT in article_analysis` | 5 min |
| Enrichment | Poll `events.status IN ('candidate', 'unreviewed')` with no `event_documents` | 10 min |
| Scoring | Poll events where `event_scores.id IS NULL` OR articles changed since last score | 10 min |
| Generation | Poll events where `is_reviewed = FALSE` AND scores exist AND `event_summaries` incomplete | 10 min |
| Promotion | After scoring: check if candidate events meet promotion criteria | runs with scoring |
| Digest builder | Cron schedule | daily 07:00 UTC |

### Enrichment completion signal

The scoring service knows enrichment is done by checking:
```sql
SELECT e.id FROM events e
LEFT JOIN event_documents ed ON ed.event_id = e.id
WHERE e.status IN ('candidate', 'unreviewed')
  AND e.updated_at > COALESCE(
    (SELECT MAX(computed_at) FROM event_scores es WHERE es.event_id = e.id),
    '1970-01-01'::timestamptz
  )
```
This re-scores events that have been updated (new articles, new documents) since the last score computation.
