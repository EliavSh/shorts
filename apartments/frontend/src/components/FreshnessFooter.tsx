import { useQuery } from "@tanstack/react-query";
import { fetchFreshness } from "@/api/meta";

function ago(ts: string | null): string {
  if (!ts) return "never";
  const dt = new Date(ts);
  const h = (Date.now() - dt.getTime()) / 3_600_000;
  if (h < 1) return `${Math.round(h * 60)}m ago`;
  if (h < 24) return `${h.toFixed(1)}h ago`;
  return `${(h / 24).toFixed(1)}d ago`;
}

export function FreshnessFooter() {
  const { data } = useQuery({
    queryKey: ["freshness"],
    queryFn: fetchFreshness,
    refetchInterval: 60_000,
  });

  if (!data) return null;
  const sources = Object.entries(data.sources);

  return (
    <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-[11px] text-slate-500 px-3 py-2">
      <span>{data.counts.active_listings.toLocaleString()} active listings</span>
      <span>·</span>
      <span>{data.counts.transactions.toLocaleString()} transactions</span>
      <span>·</span>
      <span>{data.counts.zones.toLocaleString()} zones</span>
      {sources.map(([src, info]) => (
        <span key={src}>· <span className="text-slate-400">{src}</span> {ago(info.last_success)}</span>
      ))}
    </div>
  );
}
