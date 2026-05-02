import { apiFetch } from "@/lib/api";
import type { OutletDetail } from "@/lib/types";
import Link from "next/link";
import EventCard from "@/components/EventCard";

async function getOutlet(slug: string): Promise<OutletDetail | null> {
  try {
    return await apiFetch<OutletDetail>(`/outlets/${slug}`);
  } catch {
    return null;
  }
}

export default async function OutletPage({
  params,
}: {
  params: { slug: string };
}) {
  const outlet = await getOutlet(params.slug);

  if (!outlet) {
    return (
      <div className="text-center py-12">
        <h1 className="text-xl font-bold text-stone-800">
          Outlet não encontrado
        </h1>
        <Link
          href="/outlets"
          className="text-blue-600 hover:underline mt-4 inline-block"
        >
          ← Outlets
        </Link>
      </div>
    );
  }

  return (
    <div>
      <Link
        href="/outlets"
        className="text-sm text-stone-500 hover:text-stone-700 mb-4 inline-block"
      >
        ← Outlets
      </Link>

      <h1 className="text-2xl font-bold text-stone-800 mt-2">{outlet.name}</h1>
      <p className="text-stone-500 mt-1">
        {outlet.type === "newspaper"
          ? "📄 Jornal"
          : outlet.type === "tv"
            ? "📺 TV"
            : outlet.type === "radio"
              ? "📻 Rádio"
              : outlet.type === "online"
                ? "🌐 Online"
                : outlet.type}
        {outlet.website_url && (
          <>
            {" "}
            ·{" "}
            <a
              href={outlet.website_url}
              target="_blank"
              rel="noopener"
              className="text-blue-600 hover:underline"
            >
              website ↗
            </a>
          </>
        )}
      </p>

      {/* Ownership */}
      {outlet.ownership.length > 0 && (
        <section className="mt-6 mb-8">
          <h2 className="text-lg font-semibold text-stone-700 mb-3">
            Propriedade
          </h2>
          <div className="bg-white border border-stone-200 rounded-lg divide-y divide-stone-100">
            {outlet.ownership.map((o, i) => (
              <div
                key={i}
                className="p-3 flex items-center justify-between gap-3"
              >
                <div>
                  <span className="text-sm font-medium text-stone-800">
                    {o.owner_name}
                  </span>
                  <span className="text-xs text-stone-400 ml-2">
                    {o.owner_type === "company"
                      ? "Empresa"
                      : o.owner_type === "individual"
                        ? "Individual"
                        : o.owner_type === "state"
                          ? "Estado"
                          : o.owner_type}
                  </span>
                </div>
                <div className="text-xs text-stone-500 shrink-0">
                  {o.stake_pct !== null && <span>{o.stake_pct}%</span>}
                  {o.confidence !== null && (
                    <span className="ml-2">
                      confiança: {(o.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
          {outlet.ownership[0]?.source && (
            <p className="text-xs text-stone-400 mt-1">
              Fonte: {outlet.ownership[0].source}
            </p>
          )}
        </section>
      )}

      {/* Recent events */}
      <section>
        <h2 className="text-lg font-semibold text-stone-700 mb-3">
          Eventos recentes ({outlet.recent_events.length})
        </h2>
        {outlet.recent_events.length === 0 ? (
          <p className="text-stone-400 text-sm">Nenhum evento recente.</p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {outlet.recent_events.map((e) => (
              <EventCard key={e.id} event={e} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}