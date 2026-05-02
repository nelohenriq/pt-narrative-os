import Link from "next/link";
import ScoreBadge from "./ScoreBadge";
import type { EventListItem } from "@/lib/types";

export default function EventCard({ event }: { event: EventListItem }) {
  const isUndercovered = (event.undercoverage_score ?? 0) > 0.3;

  return (
    <Link
      href={`/events/${event.id}`}
      className="block bg-white rounded-lg border border-stone-200 p-4 hover:border-stone-300 hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold text-stone-800 leading-snug flex-1">
          {event.canonical_title}
        </h3>
        {isUndercovered && (
          <span className="shrink-0 px-2 py-0.5 rounded text-xs font-bold bg-amber-100 text-amber-700">
            ⚠
          </span>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-stone-500">
        <span>{event.article_count} artigos</span>
        <span>·</span>
        <span>{event.outlet_count} outlets</span>
        <span>·</span>
        <span>
          {event.first_seen_at
            ? new Date(event.first_seen_at).toLocaleDateString("pt-PT")
            : "—"}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        <ScoreBadge label="Cobertura" value={event.coverage_breadth} format="pct" />
        <ScoreBadge label="Divergência" value={event.framing_divergence} format="dec" />
        {event.undercoverage_score !== null && (
          <ScoreBadge label="Undercover" value={event.undercoverage_score} format="dec" />
        )}
      </div>
    </Link>
  );
}