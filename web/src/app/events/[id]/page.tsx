import { apiFetch } from "@/lib/api";
import type { EventDetail } from "@/lib/types";
import Link from "next/link";
import OutletBadge from "@/components/OutletBadge";
import LusaBadge from "@/components/LusaBadge";
import ScoreBadge from "@/components/ScoreBadge";

async function getEvent(id: string): Promise<EventDetail | null> {
  try {
    return await apiFetch<EventDetail>(`/events/${id}`);
  } catch {
    return null;
  }
}

export default async function EventPage({
  params,
}: {
  params: { id: string };
}) {
  const event = await getEvent(params.id);

  if (!event) {
    return (
      <div className="text-center py-12">
        <h1 className="text-xl font-bold text-stone-800">
          Evento não encontrado
        </h1>
        <Link
          href="/"
          className="text-blue-600 hover:underline mt-4 inline-block"
        >
          ← Voltar
        </Link>
      </div>
    );
  }

  const dateStr = event.first_seen_at
    ? new Date(event.first_seen_at).toLocaleDateString("pt-PT", {
        year: "numeric",
        month: "long",
        day: "numeric",
      })
    : null;

  return (
    <div>
      <Link
        href="/"
        className="text-sm text-stone-500 hover:text-stone-700 mb-4 inline-block"
      >
        ← Digest
      </Link>

      <h1 className="text-2xl font-bold text-stone-800 mt-2">
        {event.canonical_title}
      </h1>
      {dateStr && <p className="text-stone-500 mt-1">{dateStr}</p>}

      <div className="flex flex-wrap gap-2 mt-3 mb-6">
        <span className="text-sm text-stone-500">
          {event.article_count} artigos · {event.outlet_count} outlets
        </span>
      </div>

      {/* Scores */}
      {event.scores && (
        <div className="flex flex-wrap gap-2 mb-6">
          <ScoreBadge
            label="Cobertura"
            value={event.scores.coverage_breadth}
            format="pct"
          />
          <ScoreBadge
            label="Divergência"
            value={event.scores.framing_divergence}
            format="dec"
          />
          <ScoreBadge
            label="Evidência"
            value={event.scores.evidence_density}
            format="pct"
          />
          <ScoreBadge
            label="Dep. Lusa"
            value={event.scores.lusa_dependency}
            format="pct"
          />
          {event.scores.undercoverage_score !== null && (
            <ScoreBadge
              label="Undercover"
              value={event.scores.undercoverage_score}
              format="dec"
            />
          )}
        </div>
      )}

      {/* AI Summaries */}
      {event.summaries.length > 0 && (
        <section className="mb-8">
          <h2 className="text-lg font-semibold text-stone-700 mb-3">Análise</h2>
          <div className="space-y-3">
            {event.summaries.map((s, i) => (
              <div
                key={i}
                className="bg-white border border-stone-200 rounded-lg p-4"
              >
                <div className="text-xs text-stone-400 uppercase tracking-wide mb-2">
                  {s.type.replace(/_/g, " ")} — {s.model}
                </div>
                <p className="text-sm whitespace-pre-wrap leading-relaxed text-stone-700">
                  {s.content}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Articles */}
      <section className="mb-8">
        <h2 className="text-lg font-semibold text-stone-700 mb-3">
          Artigos ({event.articles.length})
        </h2>
        <div className="space-y-2">
          {event.articles.map((a) => (
            <div
              key={a.id}
              className="flex items-start justify-between gap-3 bg-white border border-stone-200 rounded-lg p-3"
            >
              <div className="min-w-0 flex-1">
                <a
                  href={a.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm font-medium text-stone-800 hover:text-blue-600 line-clamp-2"
                >
                  {a.title}
                </a>
                <div className="flex flex-wrap items-center gap-2 mt-1.5">
                  <OutletBadge name={a.outlet} slug={a.outlet_slug} />
                  <LusaBadge cited={a.lusa_cited} likely={a.lusa_likely} />
                  <span className="text-xs text-stone-400">
                    {a.word_count} palavras
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Documents */}
      {event.documents.length > 0 && (
        <section className="mb-8">
          <h2 className="text-lg font-semibold text-stone-700 mb-3">
            Documentos ({event.documents.length})
          </h2>
          <div className="space-y-2">
            {event.documents.map((d) => (
              <div
                key={d.id}
                className="bg-white border border-stone-200 rounded-lg p-3 text-sm"
              >
                <span className="text-xs px-1.5 py-0.5 rounded bg-stone-100 text-stone-500 mr-2">
                  {d.source_type}
                </span>
                {d.url ? (
                  <a
                    href={d.url}
                    target="_blank"
                    rel="noopener"
                    className="text-blue-600 hover:underline"
                  >
                    {d.title}
                  </a>
                ) : (
                  <span>{d.title}</span>
                )}
                <span className="text-stone-400 ml-2 text-xs">
                  via {d.matched_by}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Provenance link */}
      <Link
        href={`/events/${event.id}/provenance`}
        className="text-sm text-stone-400 hover:text-stone-600 underline"
      >
        Provenance → AI audit trail
      </Link>
    </div>
  );
}