export default function ScoreBadge({
  label,
  value,
  format,
}: {
  label: string;
  value: number | null;
  format: "pct" | "dec" | "raw";
}) {
  if (value === null || value === undefined) return null;
  const display =
    format === "pct"
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