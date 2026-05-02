import { apiFetch } from "@/lib/api";
import type { OutletItem } from "@/lib/types";
import Link from "next/link";

async function getOutlets(): Promise<OutletItem[]> {
  try {
    return await apiFetch<OutletItem[]>("/outlets");
  } catch {
    return [];
  }
}

export default async function OutletsPage() {
  const outlets = await getOutlets();

  return (
    <div>
      <h1 className="text-2xl font-bold text-stone-800 mb-2">📡 Outlets</h1>
      <p className="text-stone-500 mb-6">
        {outlets.length} outlets monitorizados. Inclui contexto de propriedade
        via ERC.
      </p>

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {outlets.map((o) => (
          <Link
            key={o.slug}
            href={`/outlets/${o.slug}`}
            className="bg-white border border-stone-200 rounded-lg p-4 hover:border-stone-300 hover:shadow-sm transition-all"
          >
            <h3 className="font-semibold text-stone-800">{o.name}</h3>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              <span className="text-xs px-1.5 py-0.5 rounded bg-stone-100 text-stone-500">
                {o.type === "newspaper"
                  ? "📄 Jornal"
                  : o.type === "tv"
                    ? "📺 TV"
                    : o.type === "radio"
                      ? "📻 Rádio"
                      : o.type === "online"
                        ? "🌐 Online"
                        : o.type}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}