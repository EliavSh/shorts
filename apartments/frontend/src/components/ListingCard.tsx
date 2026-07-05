import type { ListingWithScore } from "@/types";
import { fmtDistance, fmtPrice, fmtPpsqm, fmtPercent } from "@/services/format";

interface Props {
  listing: ListingWithScore;
  selected?: boolean;
  onSelect?: (id: string) => void;
  /** Optional distance from the user's GPS / search center (meters). */
  distanceM?: number | null;
}

export function ListingCard({ listing, selected, onSelect, distanceM }: Props) {
  const isRent = listing.deal_type === "rent";
  const gap = listing.score?.gap_percent;
  const gapClass =
    gap == null
      ? "text-slate-400"
      : gap <= -10
      ? "text-market-under"
      : gap >= 10
      ? "text-market-over"
      : "text-market-at";

  return (
    <button
      onClick={() => onSelect?.(listing.id)}
      className={`w-full text-left rounded-lg border px-3 py-2 transition-colors min-h-[44px] ${
        selected ? "border-blue-500 bg-slate-800" : "border-slate-700 bg-slate-900 hover:bg-slate-800"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold text-slate-100 truncate">{listing.address ?? "—"}</span>
        <span className="text-sm text-slate-300 whitespace-nowrap">
          {fmtPrice(listing.price)}{isRent && <span className="text-slate-500">/mo</span>}
        </span>
      </div>
      <div className="mt-1 flex justify-between text-xs text-slate-400">
        <span>
          {listing.rooms ?? "—"} rooms · {listing.sqm ?? "—"} m²
          {!isRent && <> · {fmtPpsqm(listing.price_per_sqm)}</>}
        </span>
        {!isRent && <span className={gapClass}>{fmtPercent(gap, true)}</span>}
      </div>
      {distanceM != null && (
        <div className="mt-0.5 text-xs text-slate-500">
          📍 {fmtDistance(distanceM)} away
        </div>
      )}
    </button>
  );
}
