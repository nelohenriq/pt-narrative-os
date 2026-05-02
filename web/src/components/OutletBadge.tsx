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