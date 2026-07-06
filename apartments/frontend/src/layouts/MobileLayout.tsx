import { ReactNode, useState } from "react";
import { BottomSheet } from "@/components/BottomSheet";
import { PersistentSheet } from "@/components/PersistentSheet";
import { MapLegend } from "@/components/MapLegend";

interface Props {
  map: ReactNode;
  filters: ReactNode;
  list: ReactNode;
  /** Short summary string for the persistent peek strip ("248 listings · sorted by gap"). */
  listingsSummary: string;
  detail?: ReactNode;
  onDetailClose: () => void;
  gpsToggle: ReactNode;
  zonesVisible: boolean;
  onZonesToggle: () => void;
  busVisible: boolean;
  onBusToggle: () => void;
  nearBus826: boolean;
  onNearBusToggle: () => void;
  onRefresh: () => void;
  loading: boolean;
}

/**
 * Map-first mobile shell.
 *
 * The screen is the map. Three things float above it:
 *   - top chip strip (zones / refresh / loading hint)
 *   - bottom persistent listings drawer (peek shows a summary; pull up to see the list)
 *   - floating action buttons (filter FAB bottom-left, GPS toggle bottom-right)
 * Tapping a listing opens the detail panel as a *modal* bottom-sheet on top.
 *
 * No tab bar — the map is the implicit home, and Map / Listings / Filters
 * are no longer peer destinations.
 */
export function MobileLayout({
  map,
  filters,
  list,
  listingsSummary,
  detail,
  onDetailClose,
  gpsToggle,
  zonesVisible,
  onZonesToggle,
  busVisible,
  onBusToggle,
  nearBus826,
  onNearBusToggle,
  onRefresh,
  loading,
}: Props) {
  const [filtersOpen, setFiltersOpen] = useState(false);

  return (
    <div className="relative h-full">
      <div className="absolute inset-0">{map}</div>

      {/* Top chip strip: zones, refresh, loading */}
      <div className="absolute left-2 right-2 top-2 z-30 flex items-center gap-2 pointer-events-none">
        <button
          onClick={onZonesToggle}
          className={`pointer-events-auto min-h-[36px] rounded-full px-3 py-1 text-xs font-medium shadow ${
            zonesVisible ? "bg-purple-600 text-white" : "bg-slate-900/90 text-slate-200"
          }`}
        >
          🏛 Zones
        </button>
        <button
          onClick={onBusToggle}
          className={`pointer-events-auto min-h-[36px] rounded-full px-3 py-1 text-xs font-medium shadow ${
            busVisible ? "bg-amber-500 text-white" : "bg-slate-900/90 text-slate-200"
          }`}
        >
          🚌 826
        </button>
        <button
          onClick={onNearBusToggle}
          className={`pointer-events-auto min-h-[36px] rounded-full px-3 py-1 text-xs font-medium shadow ${
            nearBus826 ? "bg-amber-600 text-white" : "bg-slate-900/90 text-slate-200"
          }`}
        >
          📍 Near 826
        </button>
        <button
          onClick={onRefresh}
          className="pointer-events-auto min-h-[36px] rounded-full bg-slate-900/90 px-3 py-1 text-xs font-medium text-slate-200 shadow"
        >
          ↻ Refresh
        </button>
        {loading && (
          <div className="pointer-events-none rounded-full bg-slate-900/90 px-3 py-1 text-xs text-slate-200 shadow">
            Loading…
          </div>
        )}
        <span className="ml-auto pointer-events-auto">
          <MapLegend />
        </span>
      </div>

      {/* Floating filter FAB sits ~10px above the 80px peek drawer */}
      <button
        onClick={() => setFiltersOpen(true)}
        aria-label="Open filters"
        className="absolute left-3 z-[920] flex h-12 w-12 items-center justify-center rounded-full bg-slate-900 text-white shadow-lg active:scale-95 transition"
        style={{ bottom: "calc(5rem + 0.75rem)" }}
      >
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M3 6h18M6 12h12M10 18h4" />
        </svg>
      </button>

      {/* Floating GPS toggle, mirrored above the peek drawer on the right */}
      <div
        className="absolute right-3 z-[920]"
        style={{ bottom: "calc(5rem + 0.75rem)" }}
      >
        {gpsToggle}
      </div>

      {/* Persistent bottom drawer with the listings list. Always on screen. */}
      <PersistentSheet
        peek={
          <div className="flex items-center justify-between text-slate-300">
            <span className="font-medium">{listingsSummary}</span>
            <span className="text-xs text-slate-500">drag up for list</span>
          </div>
        }
      >
        {list}
      </PersistentSheet>

      {/* Filters slide-over (modal — closes after apply/dismiss) */}
      <BottomSheet open={filtersOpen} onOpenChange={setFiltersOpen} title="Filters">
        {filters}
      </BottomSheet>

      {/* Detail panel — opens on listing tap, closes on swipe-down or ✕ */}
      <BottomSheet
        open={!!detail}
        onOpenChange={(o) => {
          if (!o) onDetailClose();
        }}
        title="Listing"
      >
        {detail}
      </BottomSheet>
    </div>
  );
}
