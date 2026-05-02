import { apiFetch } from "@/lib/api";
import type { UndercoverageFlag } from "@/lib/types";
import Link from "next/link";

async function getUndercovered(): Promise<UndercoverageFlag[]> {
  try {
    return await apiFetch<UndercoverageFlag[]>("/events/undercovered");
  } catch {
    return [];
  }
}

export default async function UndercoveredPage() {
  const flags = await getUndercovered();

  return (
    <div>
      <h1 className="text-2xl font-bold text-stone-800 mb-2">
        ⚠️ Undercovered Stories
      </h1>
      <p className="text-stone-500 mb-6">
        Stories with high framing divergence but limited outlet coverage.
        Evidence-first, not bias-rating.
      </p>

      {flags.length === 0 ? (
        <div className="text-center py-12 text-stone-400">
          Nenhum flag ativo. Todos os eventos estão com boa cobertura.
        </div>
      ) : (
        <div className="space-y-4">
          {flags.map((f) => (
            <Link
              key={f.id}
              href={`/events/${f.event_id}`}
              className="block bg-white border border-stone-200 rounded-lg p-4 hover:border-amber-200 hover:shadow-sm transition-all"
            >
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-semibold text-stone-800">
                  {f.event_title}
                </h3>
                <span className="shrink-0 px-2 py-0.5 rounded text-xs font-bold bg-amber-100 text-amber-700">
                  {f.flag_type}
                </span>
              </div>

              <p className="text-sm text-stone-600 mt-2">{f.reason}</p>

              <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-stone-500">
                {f.coverage_breadth !== null && (
                  <span>Cobertura: {(f.coverage_breadth * 100).toFixed(0)}%</span>
                )}
                {f.undercoverage_score !== null && (
                  <span>Score: {f.undercoverage_score.toFixed(2)}</span>
                )}
                {Array.isArray(f.silent_outlets) &&
                  f.silent_outlets.length > 0 && (
                    <span>
                      Silent outlets:{" "}
                      {f.silent_outlets.slice(0, 5).join(", ")}
                      {f.silent_outlets.length > 5 &&
                        ` +${f.silent_outlets.length - 5}`}
                    </span>
                  )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}