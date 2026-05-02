"use client";

import { useState, useCallback } from "react";
import type { SearchResult } from "@/lib/types";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const doSearch = useCallback(
    async (q: string) => {
      if (q.length < 2) {
        setResults(null);
        return;
      }
      setLoading(true);
      setError("");
      try {
        const res = await fetch(`${API_URL}/search?q=${encodeURIComponent(q)}`);
        if (!res.ok) throw new Error(`API ${res.status}`);
        const data = (await res.json()) as SearchResult;
        setResults(data);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Unknown error");
        setResults(null);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  return (
    <div>
      <h1 className="text-2xl font-bold text-stone-800 mb-2">🔍 Search</h1>
      <p className="text-stone-500 mb-6">
        Full-text search across events and articles.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          doSearch(query);
        }}
        className="flex gap-2 mb-8"
      >
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Pesquisar eventos e artigos..."
          className="flex-1 px-4 py-2 border border-stone-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          type="submit"
          disabled={loading || query.length < 2}
          className="px-5 py-2 bg-stone-800 text-white rounded-lg text-sm font-medium hover:bg-stone-700 disabled:opacity-40 transition-colors"
        >
          {loading ? "..." : "Pesquisar"}
        </button>
      </form>

      {error && <p className="text-red-500 text-sm mb-4">{error}</p>}

      {results && (
        <div className="space-y-8">
          {/* Events */}
          <section>
            <h2 className="text-lg font-semibold text-stone-700 mb-3">
              Eventos ({results.events.length})
            </h2>
            {results.events.length === 0 ? (
              <p className="text-stone-400 text-sm">
                Nenhum evento encontrado.
              </p>
            ) : (
              <div className="space-y-2">
                {results.events.map((e) => (
                  <Link
                    key={e.id}
                    href={`/events/${e.id}`}
                    className="block bg-white border border-stone-200 rounded-lg p-3 hover:border-stone-300 transition-colors"
                  >
                    <h3 className="text-sm font-medium text-stone-800">
                      {e.canonical_title}
                    </h3>
                    <div className="text-xs text-stone-400 mt-1">
                      {e.article_count} artigos · {e.outlet_count} outlets
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </section>

          {/* Articles */}
          <section>
            <h2 className="text-lg font-semibold text-stone-700 mb-3">
              Artigos ({results.articles.length})
            </h2>
            {results.articles.length === 0 ? (
              <p className="text-stone-400 text-sm">
                Nenhum artigo encontrado.
              </p>
            ) : (
              <div className="space-y-2">
                {results.articles.map((a) => (
                  <a
                    key={a.id}
                    href={a.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block bg-white border border-stone-200 rounded-lg p-3 hover:border-stone-300 transition-colors"
                  >
                    <h3 className="text-sm font-medium text-stone-800">
                      {a.title}
                    </h3>
                    <div className="text-xs text-stone-400 mt-1">
                      {a.outlet}
                      {a.published_at && (
                        <>
                          {" "}
                          ·{" "}
                          {new Date(a.published_at).toLocaleDateString(
                            "pt-PT"
                          )}
                        </>
                      )}
                    </div>
                  </a>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}