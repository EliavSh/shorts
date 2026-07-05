import { useQuery } from "@tanstack/react-query";
import type { Filters } from "@/types";
import { fetchNeighborhoods } from "@/api/meta";

interface Props {
  filters: Filters;
  onChange: (patch: Partial<Filters>) => void;
  cities?: string[];
  /** Current map center, surfaced from MapView. Lets the user pin the search
   *  area to wherever they're currently looking, without enabling GPS. */
  mapCenter?: { lat: number; lon: number } | null;
  /** True when a custom search center is currently active. */
  searchCenterActive?: boolean;
  /** Set the search center to (lat, lon). Pass null to clear. */
  onSetSearchCenter?: (c: { lat: number; lon: number } | null) => void;
  /** Optional badge showing how many of the currently-loaded listings are
   *  first-hand (new construction) — surfaced next to the toggle. */
  firstHandCount?: number;
  /** Optional badge showing how many of the currently-loaded listings are
   *  top-deals (≥10 % below market) — surfaced next to the toggle. */
  topDealsCount?: number;
  /** Sale-only affordances (deals preset, pinui-binui zones). Hidden in rent
   *  mode, which is listings-only. */
  showDeals?: boolean;
}

export function FilterBar({
  filters,
  onChange,
  cities = [],
  mapCenter,
  searchCenterActive,
  onSetSearchCenter,
  firstHandCount,
  topDealsCount,
  showDeals = true,
}: Props) {
  // Sale prices step in ₪100k; monthly rents step in ₪500.
  const priceStep = showDeals ? 100_000 : 500;
  // Sale filters base price; rent filters the *total* monthly cost
  // (rent + ועד בית + ארנונה).
  const isRent = !showDeals;
  const minKey: "min_price" | "min_total" = isRent ? "min_total" : "min_price";
  const maxKey: "max_price" | "max_total" = isRent ? "max_total" : "max_price";
  const neighborhoods = useQuery({
    queryKey: ["neighborhoods", filters.city ?? null],
    queryFn: () => fetchNeighborhoods(filters.city),
    enabled: !!filters.city,
    staleTime: 5 * 60_000,
  });

  return (
    <div className="space-y-3 p-4">
      {/* Search-area control. Most users will use this to "browse some other
          area" without enabling GPS / travel mode. */}
      <div className="rounded border border-slate-700 bg-slate-800/40 p-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs uppercase tracking-wide text-slate-400">
            Search area
          </span>
          {searchCenterActive && (
            <span className="rounded-full bg-blue-900/60 px-2 py-0.5 text-[10px] font-medium text-blue-100">
              Custom area
            </span>
          )}
        </div>
        <div className="flex flex-col gap-2">
          <button
            type="button"
            disabled={!mapCenter}
            onClick={() => mapCenter && onSetSearchCenter?.(mapCenter)}
            className="rounded bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:bg-slate-700 disabled:text-slate-400"
          >
            📍 Search this map area
          </button>
          {searchCenterActive && (
            <button
              type="button"
              onClick={() => onSetSearchCenter?.(null)}
              className="rounded border border-slate-600 px-3 py-2 text-sm text-slate-300 hover:bg-slate-700"
            >
              Clear custom search area
            </button>
          )}
          <p className="text-xs text-slate-500">
            Pan / zoom the map to where you want to look, then tap the button
            above. No GPS required.
          </p>
        </div>
      </div>

      <label className="block text-sm">
        <span className="text-slate-400">City</span>
        <select
          value={filters.city ?? ""}
          onChange={(e) => onChange({ city: e.target.value || undefined, neighborhood: undefined })}
          className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-2 py-2 text-slate-100"
        >
          <option value="">Any</option>
          {cities.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>

      {filters.city && (neighborhoods.data?.length ?? 0) > 0 && (
        <label className="block text-sm">
          <span className="text-slate-400">Neighborhood</span>
          <select
            value={filters.neighborhood ?? ""}
            onChange={(e) => onChange({ neighborhood: e.target.value || undefined })}
            className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-2 py-2 text-slate-100"
          >
            <option value="">Any</option>
            {(neighborhoods.data ?? []).map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
      )}

      <div className="grid grid-cols-2 gap-2 text-sm">
        <label>
          <span className="text-slate-400">Min rooms</span>
          <input
            type="number" step={0.5} value={filters.min_rooms ?? ""}
            onChange={(e) => onChange({ min_rooms: e.target.value ? Number(e.target.value) : undefined })}
            className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-2 py-2"
          />
        </label>
        <label>
          <span className="text-slate-400">Max rooms</span>
          <input
            type="number" step={0.5} value={filters.max_rooms ?? ""}
            onChange={(e) => onChange({ max_rooms: e.target.value ? Number(e.target.value) : undefined })}
            className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-2 py-2"
          />
        </label>
        <label>
          <span className="text-slate-400">{showDeals ? "Min price" : "Min total ₪/mo"}</span>
          <input
            type="number" step={priceStep} value={filters[minKey] ?? ""}
            onChange={(e) => onChange({ [minKey]: e.target.value ? Number(e.target.value) : undefined })}
            className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-2 py-2"
          />
        </label>
        <label>
          <span className="text-slate-400">{showDeals ? "Max price" : "Max total ₪/mo"}</span>
          <input
            type="number" step={priceStep} value={filters[maxKey] ?? ""}
            onChange={(e) => onChange({ [maxKey]: e.target.value ? Number(e.target.value) : undefined })}
            className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-2 py-2"
          />
        </label>
      </div>

      {/* Featured presets — visually pulled forward so they're discoverable. */}
      <div className="space-y-2 pt-2 border-t border-slate-800">
        <div className="text-xs uppercase tracking-wide text-slate-500">
          Quick presets
        </div>
        {showDeals && (
          <label className="flex items-center gap-2 min-h-[44px] rounded-lg bg-emerald-900/30 px-3 border border-emerald-900/40">
            <input
              type="checkbox"
              checked={!!filters.top_deals_only}
              onChange={(e) => onChange({ top_deals_only: e.target.checked })}
              className="h-5 w-5"
            />
            <div className="flex-1">
              <div className="text-sm font-medium text-slate-100">🔥 Top deals only</div>
              <div className="text-xs text-slate-400">≥ 10 % below market, sorted by gap</div>
            </div>
            {topDealsCount != null && (
              <span className="rounded-full bg-emerald-900/60 px-2 py-0.5 text-xs font-medium text-emerald-100">
                {topDealsCount}
              </span>
            )}
          </label>
        )}
        <label className="flex items-center gap-2 min-h-[44px] rounded-lg bg-blue-900/30 px-3 border border-blue-900/40">
          <input
            type="checkbox"
            checked={!!filters.only_new_construction}
            onChange={(e) => onChange({ only_new_construction: e.target.checked })}
            className="h-5 w-5"
          />
          <div className="flex-1">
            <div className="text-sm font-medium text-slate-100">🏗 First-hand only</div>
            <div className="text-xs text-slate-400">brand-new (yad-rishona) listings</div>
          </div>
          {firstHandCount != null && (
            <span className="rounded-full bg-blue-900/60 px-2 py-0.5 text-xs font-medium text-blue-100">
              {firstHandCount}
            </span>
          )}
        </label>
      </div>

      <div className="space-y-2 text-sm pt-2 border-t border-slate-800">
        <label className="flex items-center gap-2 min-h-[36px]">
          <input
            type="checkbox"
            checked={filters.include_new_construction !== false}
            onChange={(e) => onChange({ include_new_construction: e.target.checked })}
            className="h-5 w-5"
          />
          <span>Include new-construction listings</span>
        </label>
        {showDeals && (
          <label className="flex items-center gap-2 min-h-[36px]">
            <input
              type="checkbox"
              checked={!!filters.restrict_to_zones}
              onChange={(e) => onChange({ restrict_to_zones: e.target.checked })}
              className="h-5 w-5"
            />
            <span>Only listings inside Pinui Binui zones (~80 m)</span>
          </label>
        )}
      </div>

      <div className="pt-3 border-t border-slate-800">
        <button
          type="button"
          onClick={() =>
            onChange({
              city: undefined,
              neighborhood: undefined,
              min_rooms: undefined,
              max_rooms: undefined,
              min_price: undefined,
              max_price: undefined,
              min_total: undefined,
              max_total: undefined,
              include_new_construction: true,
              only_new_construction: false,
              restrict_to_zones: false,
              top_deals_only: false,
            })
          }
          className="w-full rounded border border-slate-600 px-3 py-2 text-sm text-slate-300 hover:bg-slate-700"
        >
          ↺ Reset all filters
        </button>
      </div>
    </div>
  );
}
