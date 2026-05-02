# Phase 11 — Next.js Frontend Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a public Next.js frontend that consumes the FastAPI internal API to display Portugal Narrative OS data — daily digest, event details, outlet profiles, undercoverage flags, and full-text search.

**Architecture:** Next.js 14 App Router with TypeScript. Server-side data fetching from the FastAPI internal API (port 8000). No auth needed (this is the public face). Minimal, newspaper-inspired design using Tailwind CSS. Pure server components where possible — `"use client"` only for interactive elements (search form).

**Tech Stack:** Next.js 14, TypeScript, Tailwind CSS, `fetch()` for API calls (no additional HTTP libs).

**API Base URL:** `http://localhost:8000/api` (configured via `NEXT_PUBLIC_API_URL` env var).

---

## Task 1: Scaffold Next.js project

**Objective:** Create a fresh Next.js 14 project with TypeScript and Tailwind in the `web/` directory.

**Files:**
- Create: `web/` (entire Next.js app)

**Step 1: Initialize project**

```bash
cd /teamspace/studios/this_studio/pt-narrative-os
npx create-next-app@14 web --typescript --tailwind --eslint --app --src-dir --no-import-alias
```

**Step 2: Add API base URL env**

Create `web/.env.local`:
```
NEXT_PUBLIC_API_URL=http://localhost:8000/api
```

**Step 3: Clean up defaults**

Remove the default `src/app/page.tsx` boilerplate, keep the layout shell.

**Step 4: Create API fetch helper**

Create `web/src/lib/api.ts`:

```typescript
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    next: { revalidate: 300 }, // ISR: revalidate every 5 minutes
    ...options,
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
```

**Step 5: Create type definitions**

Create `web/src/lib/types.ts`:

```typescript
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
  top_events: any[];
  undercovered: any[];
  metadata: any;
}
```

**Step 6: Verify**

```bash
cd web && npm run build
```

Expected: build succeeds with no errors.

**Step 7: Commit**

```bash
git add web/
git commit -m "feat(web): scaffold Next.js 14 project with TypeScript and Tailwind"
```

---

## Task 2: Build nav layout shell

**Objective:** Create the root layout with navigation, header, and footer.

**Files:**
- Modify: `web/src/app/layout.tsx`
- Create: `web/src/components/Nav.tsx`

**Step 1: Create Nav component**

Create `web/src/components/Nav.tsx`:

```tsx
import Link from "next/link";

const links = [
  { href: "/", label: "📰 Digest" },
  { href: "/undercovered", label: "⚠️ Undercovered" },
  { href: "/outlets", label: "📡 Outlets" },
  { href: "/search", label: "🔍 Search" },
];

export default function Nav() {
  return (
    <nav className="border-b border-stone-200 bg-white sticky top-0 z-10">
      <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
        <Link href="/" className="font-bold text-lg text-stone-800">
          Portugal Narrative OS
        </Link>
        <div className="flex gap-4 text-sm">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="text-stone-600 hover:text-stone-900 transition-colors"
            >
              {l.label}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}
```

**Step 2: Update layout**

Modify `web/src/app/layout.tsx`:

```tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Nav from "@/components/Nav";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Portugal Narrative OS",
  description: "Portugal-first media narrative intelligence platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt">
      <body className={`${inter.className} bg-stone-50 text-stone-900 min-h-screen`}>
        <Nav />
        <main className="max-w-6xl mx-auto px-4 py-8">{children}</main>
        <footer className="border-t border-stone-200 py-6 text-center text-xs text-stone-400">
          Portugal Narrative OS — Evidence-first media comparison. Not a bias-rating app.
        </footer>
      </body>
    </html>
  );
}
```

**Step 3: Verify**

```bash
cd web && npm run build
```

**Step 4: Commit**

```bash
git add web/src/app/layout.tsx web/src/components/Nav.tsx
git commit -m "feat(web): add navigation layout shell"
```

---

## Task 3: Build reusable components

**Objective:** Create shared UI components used across pages.

**Files:**
- Create: `web/src/components/EventCard.tsx`
- Create: `web/src/components/ScoreBadge.tsx`
- Create: `web/src/components/OutletBadge.tsx`
- Create: `web/src/components/LusaBadge.tsx`

**Step 1: ScoreBadge**

Create `web/src/components/ScoreBadge.tsx`:

```tsx
export default function ScoreBadge({ label, value, format }: {
  label: string;
  value: number | null;
  format: "pct" | "dec" | "raw";
}) {
  if (value === null || value === undefined) return null;
  const display = format === "pct"
    ? `${(value * 100).toFixed(0)}%`
    : format === "dec"
      ? value.toFixed(2)
      : String(value);

  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-stone-100 text-stone-700">
      <span className="text-stone-400">{label}</span>
      {display}
    </span>
  );
}
```

**Step 2: OutletBadge**

Create `web/src/components/OutletBadge.tsx`:

```tsx
import Link from "next/link";

export default function OutletBadge({ name, slug }: { name: string; slug: string }) {
  return (
    <Link
      href={`/outlets/${slug}`}
      className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700 hover:bg-blue-100 transition-colors"
    >
      {name}
    </Link>
  );
}
```

**Step 3: LusaBadge**

Create `web/src/components/LusaBadge.tsx`:

```tsx
export default function LusaBadge({ cited, likely }: { cited: boolean; likely: boolean }) {
  if (!cited && !likely) return null;
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">
      Lusa {cited ? "cit" : "≈"}
    </span>
  );
}
```

**Step 4: EventCard**

Create `web/src/components/EventCard.tsx`:

```tsx
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
        <span>{event.first_seen_at ? new Date(event.first_seen_at).toLocaleDateString("pt-PT") : "—"}</span>
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
```

**Step 5: Verify**

```bash
cd web && npm run build
```

**Step 6: Commit**

```bash
git add web/src/components/
git commit -m "feat(web): add reusable UI components (EventCard, badges)"
```

---

## Task 4: Build homepage (daily digest)

**Objective:** Fetch today's digest and display top events.

**Files:**
- Modify: `web/src/app/page.tsx`

**Step 1: Implement page**

Write `web/src/app/page.tsx`:

```tsx
import { apiFetch } from "@/lib/api";
import type { Digest, EventListItem } from "@/lib/types";
import EventCard from "@/components/EventCard";

async function getDigest(): Promise<Digest> {
  try {
    return await apiFetch<Digest>("/digest/today");
  } catch {
    return { digest_date: new Date().toISOString().split("T")[0], top_events: [], undercovered: [], metadata: {} };
  }
}

async function getRecentEvents(): Promise<EventListItem[]> {
  try {
    const data = await apiFetch<{ items: EventListItem[] }>("/events?page_size=20");
    return data.items;
  } catch {
    return [];
  }
}

export default async function HomePage() {
  const [digest, events] = await Promise.all([getDigest(), getRecentEvents()]);

  const displayEvents = digest.top_events?.length ? digest.top_events : events;

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-stone-800">
          📰 Digest de Hoje
        </h1>
        <p className="text-stone-500 mt-1">
          {digest.digest_date
            ? new Date(digest.digest_date + "T00:00:00").toLocaleDateString("pt-PT", {
                weekday: "long", year: "numeric", month: "long", day: "numeric",
              })
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
          {displayEvents.map((event: any) => (
            <EventCard key={event.id} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}
```

**Step 2: Verify**

```bash
cd web && npm run build
```

**Step 3: Commit**

```bash
git add web/src/app/page.tsx
git commit -m "feat(web): build homepage with daily digest"
```

---

## Task 5: Build event detail page

**Objective:** Full event view with summaries, articles list, documents, and scores.

**Files:**
- Create: `web/src/app/events/[id]/page.tsx`

**Step 1: Implement page**

Create `web/src/app/events/[id]/page.tsx`:

```tsx
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

export default async function EventPage({ params }: { params: { id: string } }) {
  const event = await getEvent(params.id);

  if (!event) {
    return (
      <div className="text-center py-12">
        <h1 className="text-xl font-bold text-stone-800">Evento não encontrado</h1>
        <Link href="/" className="text-blue-600 hover:underline mt-4 inline-block">
          ← Voltar
        </Link>
      </div>
    );
  }

  const dateStr = event.first_seen_at
    ? new Date(event.first_seen_at).toLocaleDateString("pt-PT", {
        year: "numeric", month: "long", day: "numeric",
      })
    : null;

  return (
    <div>
      <Link href="/" className="text-sm text-stone-500 hover:text-stone-700 mb-4 inline-block">
        ← Digest
      </Link>

      <h1 className="text-2xl font-bold text-stone-800 mt-2">{event.canonical_title}</h1>
      {dateStr && <p className="text-stone-500 mt-1">{dateStr}</p>}

      <div className="flex flex-wrap gap-2 mt-3 mb-6">
        <span className="text-sm text-stone-500">
          {event.article_count} artigos · {event.outlet_count} outlets
        </span>
      </div>

      {/* Scores */}
      {event.scores && (
        <div className="flex flex-wrap gap-2 mb-6">
          <ScoreBadge label="Cobertura" value={event.scores.coverage_breadth} format="pct" />
          <ScoreBadge label="Divergência" value={event.scores.framing_divergence} format="dec" />
          <ScoreBadge label="Evidência" value={event.scores.evidence_density} format="pct" />
          <ScoreBadge label="Dep. Lusa" value={event.scores.lusa_dependency} format="pct" />
          {event.scores.undercoverage_score !== null && (
            <ScoreBadge label="Undercover" value={event.scores.undercoverage_score} format="dec" />
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
                  <span className="text-xs text-stone-400">{a.word_count} palavras</span>
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
                  <a href={d.url} target="_blank" rel="noopener" className="text-blue-600 hover:underline">
                    {d.title}
                  </a>
                ) : (
                  <span>{d.title}</span>
                )}
                <span className="text-stone-400 ml-2 text-xs">via {d.matched_by}</span>
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
```

**Step 2: Verify**

```bash
cd web && npm run build
```

**Step 3: Commit**

```bash
git add web/src/app/events/
git commit -m "feat(web): build event detail page"
```

---

## Task 6: Build undercovered page

**Objective:** List all events flagged as undercovered.

**Files:**
- Create: `web/src/app/undercovered/page.tsx`

**Step 1: Implement page**

Create `web/src/app/undercovered/page.tsx`:

```tsx
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
      <h1 className="text-2xl font-bold text-stone-800 mb-2">⚠️ Undercovered Stories</h1>
      <p className="text-stone-500 mb-6">
        Stories with high framing divergence but limited outlet coverage. Evidence-first, not bias-rating.
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
                <h3 className="font-semibold text-stone-800">{f.event_title}</h3>
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
                {Array.isArray(f.silent_outlets) && f.silent_outlets.length > 0 && (
                  <span>
                    Silent outlets: {f.silent_outlets.slice(0, 5).join(", ")}
                    {f.silent_outlets.length > 5 && ` +${f.silent_outlets.length - 5}`}
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
```

**Step 2: Verify**

```bash
cd web && npm run build
```

**Step 3: Commit**

```bash
git add web/src/app/undercovered/
git commit -m "feat(web): build undercovered page"
```

---

## Task 7: Build outlet list and outlet detail page

**Objective:** Outlet directory and individual outlet profiles with ownership.

**Files:**
- Create: `web/src/app/outlets/page.tsx`
- Create: `web/src/app/outlets/[slug]/page.tsx`

**Step 1: Outlet list page**

Create `web/src/app/outlets/page.tsx`:

```tsx
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
        {outlets.length} outlets monitorizados. Inclui contexto de propriedade via ERC.
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
                {o.type === "newspaper" ? "📄 Jornal" :
                 o.type === "tv" ? "📺 TV" :
                 o.type === "radio" ? "📻 Rádio" :
                 o.type === "online" ? "🌐 Online" : o.type}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
```

**Step 2: Outlet detail page**

Create `web/src/app/outlets/[slug]/page.tsx`:

```tsx
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

export default async function OutletPage({ params }: { params: { slug: string } }) {
  const outlet = await getOutlet(params.slug);

  if (!outlet) {
    return (
      <div className="text-center py-12">
        <h1 className="text-xl font-bold text-stone-800">Outlet não encontrado</h1>
        <Link href="/outlets" className="text-blue-600 hover:underline mt-4 inline-block">
          ← Outlets
        </Link>
      </div>
    );
  }

  return (
    <div>
      <Link href="/outlets" className="text-sm text-stone-500 hover:text-stone-700 mb-4 inline-block">
        ← Outlets
      </Link>

      <h1 className="text-2xl font-bold text-stone-800 mt-2">{outlet.name}</h1>
      <p className="text-stone-500 mt-1">
        {outlet.type === "newspaper" ? "📄 Jornal" :
         outlet.type === "tv" ? "📺 TV" :
         outlet.type === "radio" ? "📻 Rádio" :
         outlet.type === "online" ? "🌐 Online" : outlet.type}
        {outlet.website_url && (
          <> · <a href={outlet.website_url} target="_blank" rel="noopener" className="text-blue-600 hover:underline">
            website ↗
          </a></>
        )}
      </p>

      {/* Ownership */}
      {outlet.ownership.length > 0 && (
        <section className="mt-6 mb-8">
          <h2 className="text-lg font-semibold text-stone-700 mb-3">Propriedade</h2>
          <div className="bg-white border border-stone-200 rounded-lg divide-y divide-stone-100">
            {outlet.ownership.map((o, i) => (
              <div key={i} className="p-3 flex items-center justify-between gap-3">
                <div>
                  <span className="text-sm font-medium text-stone-800">{o.owner_name}</span>
                  <span className="text-xs text-stone-400 ml-2">
                    {o.owner_type === "company" ? "Empresa" :
                     o.owner_type === "individual" ? "Individual" :
                     o.owner_type === "state" ? "Estado" : o.owner_type}
                  </span>
                </div>
                <div className="text-xs text-stone-500 shrink-0">
                  {o.stake_pct !== null && <span>{o.stake_pct}%</span>}
                  {o.confidence !== null && (
                    <span className="ml-2">confiança: {(o.confidence * 100).toFixed(0)}%</span>
                  )}
                </div>
              </div>
            ))}
          </div>
          {outlet.ownership[0]?.source && (
            <p className="text-xs text-stone-400 mt-1">Fonte: {outlet.ownership[0].source}</p>
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
```

**Step 3: Verify**

```bash
cd web && npm run build
```

**Step 4: Commit**

```bash
git add web/src/app/outlets/
git commit -m "feat(web): build outlet list and detail pages"
```

---

## Task 8: Build search page

**Objective:** Full-text search across events and articles. Client component for interactivity.

**Files:**
- Create: `web/src/app/search/page.tsx`

**Step 1: Implement search page**

Create `web/src/app/search/page.tsx`:

```tsx
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

  const doSearch = useCallback(async (q: string) => {
    if (q.length < 2) {
      setResults(null);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/search?q=${encodeURIComponent(q)}`);
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data = await res.json();
      setResults(data);
    } catch (e: any) {
      setError(e.message);
      setResults(null);
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-bold text-stone-800 mb-2">🔍 Search</h1>
      <p className="text-stone-500 mb-6">
        Full-text search across events and articles.
      </p>

      <form
        onSubmit={(e) => { e.preventDefault(); doSearch(query); }}
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
              <p className="text-stone-400 text-sm">Nenhum evento encontrado.</p>
            ) : (
              <div className="space-y-2">
                {results.events.map((e) => (
                  <Link
                    key={e.id}
                    href={`/events/${e.id}`}
                    className="block bg-white border border-stone-200 rounded-lg p-3 hover:border-stone-300 transition-colors"
                  >
                    <h3 className="text-sm font-medium text-stone-800">{e.canonical_title}</h3>
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
              <p className="text-stone-400 text-sm">Nenhum artigo encontrado.</p>
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
                    <h3 className="text-sm font-medium text-stone-800">{a.title}</h3>
                    <div className="text-xs text-stone-400 mt-1">
                      {a.outlet}
                      {a.published_at && (
                        <> · {new Date(a.published_at).toLocaleDateString("pt-PT")}</>
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
```

**Step 2: Verify**

```bash
cd web && npm run build
```

**Step 3: Commit**

```bash
git add web/src/app/search/
git commit -m "feat(web): build search page"
```

---

## Task 9: Final integration — verify full build + add README

**Objective:** Ensure the full app builds cleanly and document how to run it.

**Files:**
- Create: `web/README.md` (or append to project root README)

**Step 1: Run full build verification**

```bash
cd web && npm run build
```

Expected: All pages build successfully with no TypeScript errors, no ESLint warnings.

**Step 2: Add project README**

Add to project root or `web/README.md`:

```markdown
# Portugal Narrative OS — Frontend

Next.js 14 public frontend for the Portugal Narrative OS platform.

## Setup

```bash
cd web
cp .env.example .env.local  # configure NEXT_PUBLIC_API_URL
npm install
npm run dev
```

Open http://localhost:3000.

The FastAPI backend must be running on port 8000:
```bash
cd .. && uvicorn api.main:app --port 8000
```

## Pages

| Route | Description |
|---|---|
| `/` | Daily digest homepage |
| `/events/[id]` | Event detail: summaries, articles, scores, documents |
| `/undercovered` | Undercoverage flags |
| `/outlets` | Outlet directory |
| `/outlets/[slug]` | Outlet profile with ownership context |
| `/search` | Full-text search |

## Architecture

- **App Router** with server components by default
- **ISR** via `fetch({ next: { revalidate: 300 } })` — pages revalidate every 5 min
- **Client components** only where interactivity is needed (search)
- **Tailwind CSS** for styling, newspaper-inspired dark-on-light design
```

**Step 3: Commit**

```bash
git add web/README.md
git commit -m "docs(web): add frontend README"
```

---

## Post-Phase 11: What remains

After Phase 11, the remaining tasks from `tasks.md` are:

- **Cross-cutting:**
  - CI setup (ruff, mypy, pytest)
  - Structured JSON logging
  - Database backup cron
  - Project README.md

---

## Verification Checklist

- [ ] `npm run build` succeeds
- [ ] Homepage renders (even with no data — shows empty state)
- [ ] `/outlets` lists all 20 outlets
- [ ] `/outlets/publico` shows Público profile with ownership
- [ ] `/search` is interactive and calls the API
- [ ] `/events/{uuid}` shows event detail (when data exists)
- [ ] `/undercovered` shows empty state (when no flags exist)