export default function LusaBadge({ cited, likely }: { cited: boolean; likely: boolean }) {
  if (!cited && !likely) return null;
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">
      Lusa {cited ? "cit" : "≈"}
    </span>
  );
}