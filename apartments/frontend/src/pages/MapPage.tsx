import { useEffect, useState } from "react";
import { useListings, useZones } from "@/hooks/useListings";
import { useGeolocation } from "@/hooks/useGeolocation";
import { useFilters } from "@/hooks/useFilters";
import { MapView } from "@/components/MapView";
import { ListingCard } from "@/components/ListingCard";
import { FilterBar } from "@/components/FilterBar";
import { GpsToggle } from "@/components/GpsToggle";
import { DetailPanel } from "@/components/DetailPanel";
import { MapLegend } from "@/components/MapLegend";
import { DesktopLayout } from "@/layouts/DesktopLayout";
import { MobileLayout } from "@/layouts/MobileLayout";
import { isMobile as detectMobile } from "@/services/platform";
import { haversineMeters } from "@/services/format";
import { SAVIDOR, SAVIDOR_RADIUS_M, RENOVATED_CONDITION_IDS } from "@/services/pois";
import type { DealType } from "@/types";

// Listings priced below this are junk (parking spots / storage / bad data),
// not real apartments — drop them everywhere.
const MIN_REAL_PRICE = 2000;
// Rent above this ₪/mo is out of scope (luxury / mis-listed) — drop in rent mode.
const MAX_RENT = 15000;
function isNearSavidor(lat?: number | null, lon?: number | null): boolean {
  if (lat == null || lon == null) return false;
  return haversineMeters(lat, lon, SAVIDOR.lat, SAVIDOR.lon) <= SAVIDOR_RADIUS_M;
}

export function MapPage({ mode = "sale" }: { mode?: DealType }) {
  const mobile = useIsMobileReactive();
  const { filters, update } = useFilters();
  // Deal/sold analysis only exists for sale listings; rent is listings-only.
  const dealsEnabled = mode === "sale";
  const [gpsEnabled, setGpsEnabled] = useState<boolean>(() => detectMobile());
  const [follow, setFollow] = useState(true);
  const [zonesVisible, setZonesVisible] = useState(true);
  // Default focus: rentals within walking distance of Savidor's taxi station.
  const [nearSavidor, setNearSavidor] = useState(true);
  // Renovated preset: only משופץ / חדש condition listings.
  const [renovatedOnly, setRenovatedOnly] = useState(false);
  const { coords, error: gpsError } = useGeolocation(gpsEnabled);
  const [selected, setSelected] = useState<string | null>(null);

  // Manual "search this map area" override. When set, takes precedence over
  // the user's GPS coords for both the spatial query and the distance sort.
  // Cleared by tapping "Clear custom search area" in the FilterBar.
  const [searchCenter, setSearchCenter] = useState<{ lat: number; lon: number } | null>(null);
  // Live map center, reported on each moveend by MapView. Used as the source
  // of "this view" when the user taps "Search this map area".
  const [mapCenter, setMapCenter] = useState<{ lat: number; lon: number } | null>(null);

  // Effective search center: explicit override > GPS coords > nothing.
  const center = searchCenter ?? (coords ? { lat: coords.lat, lon: coords.lon } : null);

  // Spatial query: tighter radius on mobile when we have a center to query
  // around; wider net or full set when there's nothing to anchor to.
  const spatial = center
    ? {
        near_lat: center.lat,
        near_lon: center.lon,
        near_radius_m: mobile ? 3000 : 5000,
      }
    : {};
  const listings = useListings({ ...filters, deal_type: mode }, spatial);
  const zonesQuery = useZones(spatial);

  // Compute distances once, drive both sort and per-card display.
  const withDistance = (() => {
    const raw = (listings.data ?? []).filter((l) => {
      const p = l.price ?? 0;
      if (p < MIN_REAL_PRICE) return false;
      if (mode === "rent" && p > MAX_RENT) return false; // sale prices are millions
      return true;
    });
    if (!center) return raw.map((l) => ({ ...l, _dist: null as number | null }));
    return raw.map((l) => ({
      ...l,
      _dist:
        l.lat != null && l.lon != null
          ? haversineMeters(center.lat, center.lon, l.lat, l.lon)
          : null,
    }));
  })();

  // Client-side ordering:
  //   - Top deals preset overrides everything: order by gap ascending.
  //   - Otherwise, if we have a center, sort closest first.
  const filteredListings = (() => {
    // Optional spatial filter: only listings near Savidor's taxi station.
    let base = nearSavidor
      ? withDistance.filter((l) => isNearSavidor(l.lat, l.lon))
      : withDistance;
    if (renovatedOnly) {
      base = base.filter(
        (l) => l.property_condition != null && RENOVATED_CONDITION_IDS.includes(l.property_condition),
      );
    }
    if (dealsEnabled && filters.top_deals_only) {
      return base
        .filter((l) => l.score?.gap_percent != null && l.score.gap_percent <= -10)
        .slice()
        .sort((a, b) => a.score!.gap_percent! - b.score!.gap_percent!);
    }
    if (center) {
      return base.slice().sort((a, b) => {
        const da = a._dist ?? Infinity;
        const db = b._dist ?? Infinity;
        return da - db;
      });
    }
    return base;
  })();

  useEffect(() => {
    if (coords && gpsEnabled) setFollow(true);
  }, [coords, gpsEnabled]);

  const cities = unique(
    (listings.data ?? []).map((l) => l.city).filter(Boolean) as string[]
  );
  // (cities pulled from raw, not filteredListings, so the city dropdown
  // doesn't shrink when "Top deals only" is on.)

  const map = (
    <MapView
      listings={filteredListings}
      zones={zonesVisible ? zonesQuery.data : null}
      showSavidor={nearSavidor}
      gps={coords}
      onListingClick={(id) => {
        setSelected(id);
        // Stop GPS auto-recenter while inspecting a listing — otherwise the
        // FollowController fights the FocusController on every GPS update.
        setFollow(false);
      }}
      onBackgroundClick={() => setSelected(null)}
      onMapMove={(lat, lon) => setMapCenter({ lat, lon })}
      selectedId={selected}
      follow={follow}
      onFollowChange={setFollow}
      defaultZoom={mobile ? 13 : 12}
      trackingZoom={mobile ? 17 : undefined}
      isMobile={mobile}
    />
  );
  // Counts surfaced as badges in FilterBar so the user knows up-front how
  // many listings each preset would surface (avoids enabling a preset and
  // finding 0 results).
  const rawListings = listings.data ?? [];
  const firstHandCount = rawListings.filter((l) => l.is_new_construction).length;
  const topDealsCount = rawListings.filter(
    (l) => l.score?.gap_percent != null && l.score.gap_percent <= -10,
  ).length;

  const filterBar = (
    <FilterBar
      filters={filters}
      onChange={update}
      cities={cities}
      mapCenter={mapCenter}
      searchCenterActive={!!searchCenter}
      onSetSearchCenter={(c) => {
        setSearchCenter(c);
        // Disengage GPS-tracking when the user picks a custom area; otherwise
        // the map will keep snapping back to their physical location.
        if (c) setFollow(false);
      }}
      firstHandCount={firstHandCount}
      topDealsCount={topDealsCount}
      showDeals={dealsEnabled}
    />
  );
  const list = (
    <div className="space-y-1 p-2">
      {filteredListings.slice(0, 200).map((l) => (
        <ListingCard
          key={l.id}
          listing={l}
          selected={selected === l.id}
          onSelect={(id) => setSelected(id)}
          distanceM={l._dist}
        />
      ))}
    </div>
  );
  const detail = selected ? (
    <DetailPanel listingId={selected} onClose={() => setSelected(null)} />
  ) : undefined;
  const gpsToggle = (
    <GpsToggle
      active={gpsEnabled}
      onToggle={() => setGpsEnabled((v) => !v)}
      error={gpsError}
    />
  );

  const isLoading = listings.isLoading || (listings.isFetching && !listings.data);

  const visibleCount = filteredListings.length;
  const noun = mode === "rent" ? "rentals" : "listings";
  const listingsSummary = dealsEnabled && filters.top_deals_only
    ? `🔥 ${visibleCount} deals (sorted by gap)`
    : visibleCount === 0
    ? `No ${noun} — adjust filters`
    : `${visibleCount.toLocaleString()} ${noun} on screen`;

  if (mobile) {
    return (
      <MobileLayout
        map={map}
        filters={filterBar}
        list={list}
        listingsSummary={listingsSummary}
        detail={detail}
        onDetailClose={() => setSelected(null)}
        gpsToggle={gpsToggle}
        zonesVisible={zonesVisible}
        onZonesToggle={() => setZonesVisible((v) => !v)}
        nearSavidor={nearSavidor}
        onSavidorToggle={() => setNearSavidor((v) => !v)}
        renovatedOnly={renovatedOnly}
        onRenovatedToggle={() => setRenovatedOnly((v) => !v)}
        onRefresh={() => {
          listings.refetch();
          zonesQuery.refetch();
        }}
        loading={isLoading}
      />
    );
  }
  return (
    <>
      <div className="absolute right-4 top-4 z-30 flex gap-2 items-center">
        <button
          onClick={() => setZonesVisible((v) => !v)}
          className={`min-h-[36px] rounded-full px-3 py-1 text-sm shadow ${
            zonesVisible ? "bg-purple-600 text-white" : "bg-slate-800 text-slate-300"
          }`}
        >
          🏛 Zones
        </button>
        <button
          onClick={() => setNearSavidor((v) => !v)}
          className={`min-h-[36px] rounded-full px-3 py-1 text-sm shadow ${
            nearSavidor ? "bg-amber-600 text-white" : "bg-slate-800 text-slate-300"
          }`}
        >
          🚕 סבידור
        </button>
        <button
          onClick={() => setRenovatedOnly((v) => !v)}
          className={`min-h-[36px] rounded-full px-3 py-1 text-sm shadow ${
            renovatedOnly ? "bg-sky-600 text-white" : "bg-slate-800 text-slate-300"
          }`}
        >
          🛠 משופץ
        </button>
        <MapLegend mode={mode} />
        {gpsToggle}
      </div>
      {isLoading && (
        <div className="absolute left-1/2 top-4 z-30 -translate-x-1/2 rounded-full bg-slate-900/90 px-3 py-1 text-xs text-slate-200 shadow">
          Loading nearby listings…
        </div>
      )}
      <DesktopLayout filters={filterBar} list={list} main={map} detail={detail} />
    </>
  );
}

function unique<T>(xs: T[]): T[] {
  return Array.from(new Set(xs));
}

function useIsMobileReactive() {
  const [m, setM] = useState(detectMobile());
  useEffect(() => {
    const onResize = () => setM(detectMobile());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return m;
}
