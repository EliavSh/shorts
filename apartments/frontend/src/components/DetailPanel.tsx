import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchListing, fetchPercentile } from "@/api/listings";
import { fetchBuildingHistory, fetchPriceHistory } from "@/api/charts";
import { fmtPercent, fmtPpsqm, fmtPrice } from "@/services/format";
import { PriceHistoryChart } from "@/components/PriceHistoryChart";
import { BuildingHistoryChart } from "@/components/BuildingHistoryChart";

interface Props {
  listingId: string;
  onClose: () => void;
}

type Scope = "building" | "block";

export function DetailPanel({ listingId, onClose }: Props) {
  const [scope, setScope] = useState<Scope>("block");

  const listing = useQuery({
    queryKey: ["listing", listingId],
    queryFn: () => fetchListing(listingId),
  });
  const percentile = useQuery({
    queryKey: ["percentile", listingId],
    queryFn: () => fetchPercentile(listingId),
    retry: false,
  });
  const priceHistory = useQuery({
    queryKey: ["price-history", listingId],
    queryFn: () => fetchPriceHistory(listingId),
    retry: false,
  });
  const addrParts = parseAddress(listing.data?.address ?? "");
  const buildingHistory = useQuery({
    queryKey: ["building-history", addrParts?.street, addrParts?.number, listing.data?.city, scope],
    queryFn: () => fetchBuildingHistory({
      street: addrParts!.street,
      number: addrParts!.number,
      city: listing.data!.city!,
      // building scope = exact same building (radius 0); block = ±10 house numbers
      radius: scope === "building" ? 0 : 10,
    }),
    enabled: !!addrParts && !!listing.data?.city,
    retry: false,
  });

  const l = listing.data;
  const balconyText =
    l?.has_balcony == null ? null : l.has_balcony ? "Yes" : "No";
  const constructionText =
    l?.is_new_construction == null
      ? null
      : l.is_new_construction
      ? "First-hand (new construction)"
      : "Second-hand";

  // Tier label + color for the gap percent — same scale as map pin colors.
  const gap = l?.score?.gap_percent ?? null;
  const tier = gapTier(gap);
  const near = percentile.data?.near ?? null;
  const area = percentile.data?.area ?? null;
  const nearScopeLabel: Record<string, string> = {
    building: "this building",
    street_block: "this street block (±5 houses)",
    street: "this street",
  };
  const nearScopeName =
    near?.scope ? nearScopeLabel[near.scope] ?? near.scope : null;

  return (
    <div className="p-4">
      <div className="flex items-start justify-between gap-2 mb-1">
        <h2 className="text-lg font-semibold">{l?.address ?? listingId}</h2>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-200" aria-label="Close">✕</button>
      </div>
      {l?.last_seen && (
        <div className="mb-3 inline-flex items-center gap-1 rounded-full bg-slate-800/70 px-2 py-0.5 text-xs text-slate-300">
          <span>🕒</span>
          <span>Updated {fmtRelativeTime(l.last_seen)}</span>
        </div>
      )}

      {/* Core specs (always available for any listing) */}
      {l && (
        <dl className="grid grid-cols-2 gap-y-1 text-sm">
          <FieldRow label="Price" value={fmtPrice(l.price)} />
          <FieldRow label="₪/m²" value={fmtPpsqm(l.price_per_sqm)} />
          <FieldRow label="Rooms" value={l.rooms} />
          <FieldRow label="Sqm" value={l.sqm} />
          <FieldRow label="City" value={l.city} />
          <FieldRow label="Gap" value={fmtPercent(l.score?.gap_percent, true)} />
        </dl>
      )}

      {/* Dual-scope explainer: gap-tier + near (street-level) + area (rooms cohort). */}
      {l && (
        <div className="mt-3 rounded border border-slate-800 p-3 space-y-2 text-sm">
          <div className="flex items-center gap-2">
            <span
              className="inline-block h-3.5 w-3.5 rounded-full border border-white"
              style={{ background: tier.color }}
            />
            <span className="font-medium text-slate-100">{tier.label}</span>
            <span className="text-xs text-slate-400">{tier.detail}</span>
          </div>

          {percentile.isLoading && !percentile.data && (
            <div className="text-xs italic text-slate-500">
              Loading cohort comparison…
            </div>
          )}

          {/* Near (street-level) row */}
          {near ? (
            <ScopeRow
              prefix="Near"
              detail={nearScopeName ?? near.scope}
              percentile={near.percentile}
              n={near.n_sales}
              median={near.median_price}
              ringNote
            />
          ) : (
            !percentile.isLoading && (
              <div className="text-xs italic text-slate-500">
                Near — not enough recorded sales on this street to compare.
              </div>
            )
          )}

          {/* Area (rooms-cohort) row */}
          {area ? (
            <ScopeRow
              prefix="Wider"
              detail={area.label}
              percentile={area.percentile}
              n={area.n_sales}
              median={area.median_price}
            />
          ) : (
            !percentile.isLoading && (
              <div className="text-xs italic text-slate-500">
                Wider — too few same-rooms sales in this city to compare.
              </div>
            )
          )}

          {/* Interpretive line — only when we can actually compare both. */}
          {near && area && (
            <div className="pt-1 text-xs text-slate-300">
              → {interpretCohorts(near.percentile, area.percentile)}
            </div>
          )}
        </div>
      )}

      {/* Property metadata — explicit nulls show as "Not provided" */}
      {l && (
        <div className="mt-3 rounded border border-slate-800 p-3">
          <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">
            Property details
          </div>
          <dl className="grid grid-cols-2 gap-y-1 text-sm">
            <FieldRow label="Floor" value={l.floor} />
            <FieldRow label="Type" value={constructionText} />
            <FieldRow label="Balcony" value={balconyText} />
            <FieldRow label="Direction" value={l.direction} />
          </dl>
        </div>
      )}

      {priceHistory.data && priceHistory.data.length > 1 && (
        <div className="mt-4 rounded border border-slate-800 p-3">
          <div className="mb-2 text-sm text-slate-400">Price history</div>
          <PriceHistoryChart events={priceHistory.data} />
        </div>
      )}
      {buildingHistory.data && (
        <div className="mt-4 rounded border border-slate-800 p-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-sm text-slate-400">
              {scope === "building" ? "Building history (5 yrs)" : "Block history (5 yrs)"}
            </div>
            <ScopeToggle scope={scope} setScope={setScope} />
          </div>
          {buildingHistory.data.length > 0 ? (
            <BuildingHistoryChart transactions={buildingHistory.data} />
          ) : (
            <div className="text-xs text-slate-500">
              No transactions in this {scope}.
            </div>
          )}
        </div>
      )}
      {l?.url && (
        <a
          href={l.url}
          target="_blank"
          rel="noreferrer"
          className="mt-4 block rounded bg-blue-600 px-3 py-2 text-center text-sm font-medium"
        >
          Open original listing →
        </a>
      )}
    </div>
  );
}

/** Renders a label/value pair. Null/undefined values show as muted "Not provided"
 *  so the user sees explicitly "we don't have this" rather than a missing row. */
function FieldRow({ label, value }: { label: string; value: unknown }) {
  const isMissing = value == null || value === "" || value === "—";
  return (
    <>
      <dt className="text-slate-400">{label}</dt>
      <dd className={isMissing ? "italic text-slate-500" : ""}>
        {isMissing ? "Not provided" : String(value)}
      </dd>
    </>
  );
}

function ScopeToggle({ scope, setScope }: { scope: Scope; setScope: (s: Scope) => void }) {
  return (
    <div className="inline-flex overflow-hidden rounded border border-slate-700 text-xs">
      {(["building", "block"] as const).map((s) => (
        <button
          key={s}
          onClick={() => setScope(s)}
          className={`px-2 py-0.5 ${
            scope === s ? "bg-slate-700 text-white" : "text-slate-400 hover:text-slate-200"
          }`}
        >
          {s === "building" ? "This building" : "Block (±10)"}
        </button>
      ))}
    </div>
  );
}

/** One row of the dual-scope cohort card. */
function ScopeRow({
  prefix,
  detail,
  percentile,
  n,
  median,
  ringNote,
}: {
  prefix: string;
  detail: string;
  percentile: number;
  n: number;
  median: number;
  ringNote?: boolean;
}) {
  const pct = Math.round(percentile * 100);
  return (
    <div className="text-xs text-slate-400">
      <span className="text-slate-200">{prefix}</span>{" "}
      <span className="text-slate-500">({detail})</span>: cheaper than{" "}
      <span className="text-slate-200">{pct}%</span> of{" "}
      {n} recent sales (median{" "}
      <span className="text-slate-200">{fmtPpsqm(median)}</span>)
      {ringNote && (
        <span className="text-slate-500">
          {" "}— this is what fills the white ring on the map.
        </span>
      )}
    </div>
  );
}

/** One-line plain-English summary comparing the near and area percentiles.
 *  Helps the user form a mental model: "is this listing cheap for its block?
 *  Is the block itself cheap for the wider city-rooms cohort?". */
function interpretCohorts(near: number, area: number): string {
  const blockSide =
    near < 0.4
      ? "this listing is on the cheap side of its block"
      : near > 0.6
      ? "this listing is on the pricey side of its block"
      : "this listing is around the middle of its block";
  const areaSide =
    near < area - 0.15
      ? "and the block itself is cheaper than the wider city–rooms cohort"
      : near > area + 0.15
      ? "and the block itself is pricier than the wider city–rooms cohort"
      : "and the block tracks the wider city–rooms cohort";
  return `${blockSide}, ${areaSide}.`;
}

/** Same tiering as the map pin gapColor in MapView, in plain words. */
function gapTier(gap: number | null | undefined): {
  color: string;
  label: string;
  detail: string;
  textClass: string;
} {
  if (gap == null)
    return {
      color: "#94a3b8",
      label: "Unscored",
      detail: "no comparable transactions yet",
      textClass: "text-slate-300",
    };
  if (gap <= -25)
    return {
      color: "#15803d",
      label: "🟢 Premium deal",
      detail: "≥ 25 % below market",
      textClass: "text-emerald-400",
    };
  if (gap <= -10)
    return {
      color: "#22c55e",
      label: "🟢 Good deal",
      detail: "10 – 25 % below market",
      textClass: "text-green-400",
    };
  if (gap >= 10)
    return {
      color: "#dc2626",
      label: "🔴 Overpriced",
      detail: "> 10 % above market",
      textClass: "text-red-400",
    };
  return {
    color: "#eab308",
    label: "🟡 Near market",
    detail: "within ±10 % of comparable sales",
    textClass: "text-yellow-400",
  };
}

function parseAddress(addr: string): { street: string; number: number } | null {
  const m = addr.match(/^\s*([^\d,]+?)\s+(\d+)/);
  if (!m) return null;
  return { street: m[1].trim(), number: parseInt(m[2], 10) };
}

function fmtRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffMs = Date.now() - then;
  const min = Math.floor(diffMs / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  return new Date(iso).toLocaleDateString();
}
