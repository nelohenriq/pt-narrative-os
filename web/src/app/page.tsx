import { apiFetch } from "@/lib/api";
import type { Digest, EventListItem } from "@/lib/types";
import EventCard from "@/components/EventCard";

async function getDigest(): Promise<Digest> {
  try {
    return await apiFetch<Digest>("/digest/today");
  } catch {
    return {
      digest_date: new Date().toISOString().split("T")[0],
      top_events: [],
      undercovered: [],
      metadata: {},
    };
  }
}

async function getRecentEvents(): Promise<EventListItem[]> {
  try {
    const data = await apiFetch<{ items: EventListItem[] }>(
      "/events?page_size=20"
    );
    return (data as { items: EventListItem[] }).items;
  } catch {
    return [];
  }
}

export default async function HomePage() {
  const [digest, events] = await Promise.all([getDigest(), getRecentEvents()]);

  const displayEvents =
    digest.top_events && digest.top_events.length > 0
      ? (digest.top_events as EventListItem[])
      : events;

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-stone-800">📰 Digest de Hoje</h1>
        <p className="text-stone-500 mt-1">
          {digest.digest_date
            ? new Date(digest.digest_date + "T00:00:00").toLocaleDateString(
                "pt-PT",
                {
                  weekday: "long",
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                }
              )
            : "Hoje"}
        </p>
      </div>

      {displayEvents.length === 0 ? (
        <div className="text-center py-12 text-stone-400">
          <p className="text-lg">Nenhum evento ainda.</p>
          <p className="text-sm mt-2">
            O pipeline está a processar os primeiros artigos. Volta em breve.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {displayEvents.map((event) => (
            <EventCard key={event.id} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}