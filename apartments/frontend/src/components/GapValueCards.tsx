import type { DealCard } from "@/types";
import { fmtPrice, fmtPercent } from "@/services/format";

interface Props {
  deals: DealCard[];
  onSelect?: (id: string) => void;
}

export function GapValueCards({ deals, onSelect }: Props) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {deals.map((d) => (
        <button
          key={d.listing.id}
          onClick={() => onSelect?.(d.listing.id)}
          className="rounded-lg border border-slate-800 bg-slate-900 p-3 text-left transition hover:border-blue-500"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate font-semibold">{d.listing.address ?? "—"}</div>
              <div className="text-xs text-slate-400">{d.listing.city ?? "—"}</div>
            </div>
            {d.score.gap_percent != null && (
              <span className="rounded-full bg-green-700/30 px-2 py-0.5 text-xs font-medium text-green-400">
                {fmtPercent(d.score.gap_percent, true)}
              </span>
            )}
          </div>
          <div className="mt-2 flex items-baseline justify-between text-sm">
            <span className="text-slate-300">{fmtPrice(d.listing.price)}</span>
            {d.score.value_add_gap && (
              <span className="text-xs text-slate-400">
                ₪{Math.round(d.score.value_add_gap).toLocaleString()} below market
              </span>
            )}
          </div>
          <div className="mt-2 text-xs text-slate-400">{d.explanation}</div>
        </button>
      ))}
    </div>
  );
}
