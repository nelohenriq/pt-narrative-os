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