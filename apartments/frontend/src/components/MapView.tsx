import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import {
  Circle,
  CircleMarker,
  MapContainer,
  Marker,
  Polyline,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import L from "leaflet";
import type { GpsCoords, ListingWithScore } from "@/types";
import type { ZonesCollection } from "@/api/zones";
import { ZonesLayer } from "@/components/ZonesLayer";
import { LINE_836_STOPS, LINE_836_RADIUS_M, CORRIDOR_CENTER } from "@/services/pois";

// Bucket markers into ~300 m grid cells; cluster when ≥7.
const GRID_DEG = 0.003;
const MIN_CLUSTER_SIZE = 7;

const gpsIcon = L.divIcon({
  html: '<div class="gps-dot"></div>',
  iconSize: [14, 14],
  className: "",
});

function clusterIcon(count: number): L.DivIcon {
  const size = count >= 100 ? 56 : count >= 30 ? 48 : 40;
  const color = count >= 30 ? "#1d4ed8" : "#2563eb";
  return L.divIcon({
    html: `<div style="
      width:${size}px;height:${size}px;border-radius:50%;
      background:${color};border:3px solid white;color:white;font-weight:700;
      display:flex;align-items:center;justify-content:center;font-size:14px;
      box-shadow:0 2px 6px rgba(0,0,0,0.35);
      ">${count}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    className: "",
  });
}

// Rent has no market/sold comparison, so color rentals by rent-per-m² RELATIVE
// to the other rentals currently shown: cheapest = green, priciest = red (same
// red→yellow→green intuition as the sale gap map). Returns an id→color map;
// empty for sale listings (they fall back to gapColor).
function buildRentColorScale(listings: ListingWithScore[]): Map<string, string> {
  const rent = listings.filter(
    (l) => l.deal_type === "rent" && l.price_per_sqm != null && (l.price_per_sqm as number) > 0,
  );
  const m = new Map<string, string>();
  if (rent.length < 3) return m; // too few to rank meaningfully
  const sorted = rent.map((l) => l.price_per_sqm as number).sort((a, b) => a - b);
  const pctOf = (v: number) => {
    let lo = 0, hi = sorted.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (sorted[mid] <= v) lo = mid + 1;
      else hi = mid;
    }
    return lo / sorted.length; // 0 = cheapest … 1 = priciest
  };
  for (const l of rent) {
    const hue = Math.round(120 * (1 - pctOf(l.price_per_sqm as number))); // 120 green → 0 red
    m.set(l.id, `hsl(${hue}, 68%, 45%)`);
  }
  return m;
}

function gapColor(gap: number | null | undefined): string {
  // Tiered scale (negative gap = below market = good for buyer):
  //   <= -25%   premium deal (deep emerald)
  //   -25..-10  standard deal (green)
  //   -10..+10  near market (yellow)
  //   >= +10    overpriced (red)
  //   null      unscored (slate)
  if (gap == null) return "#94a3b8";
  if (gap <= -25) return "#15803d";  // premium
  if (gap <= -10) return "#22c55e";  // good deal
  if (gap >= 10) return "#dc2626";   // overpriced
  return "#eab308";                   // near market
}

/**
 * Render a listing pin as an SVG divIcon: colored center dot + a percentile
 * ring drawn as a partial-circumference stroke. The ring fills clockwise from
 * 12 o'clock; a 90th-percentile listing's ring is 90% complete.
 *
 * The base CircleMarker can't render arcs; divIcon lets us pack the dot and
 * ring into one inline SVG without creating two Leaflet layers per marker.
 */
function pinIcon(
  fill: string,
  radiusPx: number,
  percentileRank: number | null | undefined,
  selected: boolean,
): L.DivIcon {
  // SVG viewBox is 28x28 (so the ring at r=12 has circumference 75.4).
  const ringR = 12;
  const C = 2 * Math.PI * ringR;
  const dotR = 7;
  // White ring on a dark track reads on every gap-tier color (was amber on
  // yellow before — invisible on yellow pins).
  const trackColor = "#0f172a";        // dark slate background
  const ringFill = "#ffffff";          // bright white progress arc
  const size = (radiusPx + 4) * 2;
  // Always render the track so every pin has a consistent ring visual.
  // Only ~58% of listings have a percentile_rank (the rest don't have enough
  // comparable transactions in their cohort), so without an always-on track
  // the user sees an inconsistent mix of rings/no-rings and assumes a bug.
  const trackRing = `<circle cx="14" cy="14" r="${ringR}" fill="none" stroke="${trackColor}" stroke-width="3" opacity="0.55"/>`;
  const fillRing =
    percentileRank == null
      ? ""
      : `<circle cx="14" cy="14" r="${ringR}" fill="none" stroke="${ringFill}" stroke-width="3"
              stroke-dasharray="${(percentileRank * C).toFixed(1)} ${C.toFixed(1)}"
              stroke-linecap="round" transform="rotate(-90 14 14)"/>`;
  const ring = trackRing + fillRing;
  // The pulsing amber halo for selection is rendered via the .marker-selected
  // CSS class on the icon wrapper (see globals.css), not as an extra SVG ring.
  const html = `
    <svg width="${size}" height="${size}" viewBox="0 0 28 28">
      ${ring}
      <circle cx="14" cy="14" r="${dotR}" fill="${fill}" stroke="${selected ? "#fbbf24" : "white"}" stroke-width="${selected ? 3 : 2}"/>
    </svg>
  `;
  return L.divIcon({
    html,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    className: selected ? "marker-selected" : "",
  });
}

// Line-836 corridor overlay: the TLV→Herzliya stops (דרך נמיר), a connecting
// polyline, and the filter-radius circle around each stop.
function Line836Layer() {
  const path = LINE_836_STOPS.map((s) => [s.lat, s.lon] as [number, number]);
  return (
    <>
      <Polyline positions={path} pathOptions={{ color: "#d97706", weight: 3, opacity: 0.6 }} />
      {LINE_836_STOPS.map((s, i) => (
        <Fragment key={i}>
          <Circle
            center={[s.lat, s.lon]}
            radius={LINE_836_RADIUS_M}
            pathOptions={{ color: "#d97706", fillColor: "#f59e0b", fillOpacity: 0.04, weight: 1, dashArray: "5 6" }}
          />
          <CircleMarker
            center={[s.lat, s.lon]}
            radius={6}
            pathOptions={{ color: "#92400e", fillColor: "#f59e0b", fillOpacity: 1, weight: 2 }}
          >
            <Tooltip direction="top">{`🚌 836 · ${s.name}`}</Tooltip>
          </CircleMarker>
        </Fragment>
      ))}
    </>
  );
}

interface Props {
  listings: ListingWithScore[];
  zones?: ZonesCollection | null;
  show836?: boolean;
  gps?: GpsCoords | null;
  radiusMeters?: number;
  follow: boolean;
  onFollowChange: (follow: boolean) => void;
  onListingClick?: (id: string) => void;
  /** Called when the user taps the map background (not a marker). Used to
   *  dismiss the detail panel by tapping the map. */
  onBackgroundClick?: () => void;
  /** Reports the current map center on every moveend. Used by the filter
   *  sheet's "use current map area" button. */
  onMapMove?: (lat: number, lon: number) => void;
  selectedId?: string | null;
  defaultZoom?: number;
  trackingZoom?: number;
  isMobile?: boolean;
}

/** Flies to the selected listing whenever it changes, regardless of whether
 *  the selection came from a map tap or the listings drawer. Skips fly when
 *  the listing has no coords. Keeps current zoom unless we're zoomed out.
 *
 *  IMPORTANT: the listings array is read through a ref, NOT included in the
 *  effect deps. Every flyTo fires a moveend event which causes the parent
 *  to re-render and pass a *new* listings array reference. Including the
 *  array in deps would re-fire the effect on every map move and the map
 *  would jitter on a tight feedback loop. We only want the effect to fire
 *  when the *selection* changes. */
function FocusController({
  listings,
  selectedId,
}: {
  listings: ListingWithScore[];
  selectedId?: string | null;
}) {
  const map = useMap();
  const listingsRef = useRef(listings);
  listingsRef.current = listings;
  useEffect(() => {
    if (!selectedId) return;
    const l = listingsRef.current.find((x) => x.id === selectedId);
    if (!l || l.lat == null || l.lon == null) return;
    const targetZoom = Math.max(map.getZoom(), 16);
    map.flyTo([l.lat, l.lon], targetZoom, { duration: 0.5 });
  }, [selectedId, map]);
  return null;
}

/** Snaps the map to GPS when in follow mode. On the first fix in follow
 *  mode we honour `trackingZoom`. Subsequent fixes preserve user's zoom. */
function FollowController({
  gps,
  follow,
  trackingZoom,
}: {
  gps?: GpsCoords | null;
  follow: boolean;
  trackingZoom?: number;
}) {
  const map = useMap();
  const firstFixRef = useRef(true);
  useEffect(() => {
    if (!follow || !gps) {
      firstFixRef.current = true;
      return;
    }
    const z =
      firstFixRef.current && trackingZoom != null
        ? trackingZoom
        : map.getZoom() ?? trackingZoom ?? 15;
    map.setView([gps.lat, gps.lon], z, { animate: true });
    firstFixRef.current = false;
  }, [gps, follow, map, trackingZoom]);
  return null;
}

function ManualInteractionWatcher({
  onFollowChange,
  onBackgroundClick,
  onMapMove,
}: {
  onFollowChange: (follow: boolean) => void;
  onBackgroundClick?: () => void;
  onMapMove?: (lat: number, lon: number) => void;
}) {
  useMapEvents({
    dragstart: () => onFollowChange(false),
    zoomstart: (e) => {
      // @ts-expect-error leaflet — originalEvent only on user interactions
      if (e?.originalEvent) onFollowChange(false);
    },
    // Map-background click (NOT marker click — Leaflet stops propagation on
    // markers by default). Used to dismiss the detail panel by tapping the map.
    click: () => onBackgroundClick?.(),
    // Report center on every move so the FilterBar can offer a "use current
    // map area as search center" button without having to introspect Leaflet
    // from outside MapView.
    moveend: (e) => {
      const c = e.target.getCenter();
      onMapMove?.(c.lat, c.lng);
    },
  });
  return null;
}

/** Tracks the live zoom level so markers scale with it. */
function useLiveZoom(initial: number): number {
  const map = useMap();
  const [z, setZ] = useState(initial);
  useMapEvents({
    zoomend: () => setZ(map.getZoom()),
  });
  return z;
}

interface ClusterCell {
  lat: number;
  lon: number;
  members: ListingWithScore[];
}

function bucketize(listings: ListingWithScore[]): ClusterCell[] {
  const cells = new Map<string, ListingWithScore[]>();
  for (const l of listings) {
    if (l.lat == null || l.lon == null) continue;
    const lat_g = Math.round(l.lat / GRID_DEG);
    const lon_g = Math.round(l.lon / GRID_DEG);
    const key = `${lat_g},${lon_g}`;
    const arr = cells.get(key);
    if (arr) arr.push(l);
    else cells.set(key, [l]);
  }
  const out: ClusterCell[] = [];
  for (const [key, members] of cells) {
    const [lat_g, lon_g] = key.split(",").map(Number);
    out.push({
      lat: (lat_g + 0.5) * GRID_DEG,
      lon: (lon_g + 0.5) * GRID_DEG,
      members,
    });
  }
  return out;
}

function MarkersLayer({
  listings,
  isMobile,
  onListingClick,
  selectedId,
}: {
  listings: ListingWithScore[];
  isMobile: boolean;
  onListingClick?: (id: string) => void;
  selectedId?: string | null;
}) {
  const map = useMap();
  const zoom = useLiveZoom(map.getZoom());

  const cells = useMemo(() => bucketize(listings), [listings]);
  // Rent color map (empty for sale — those use gapColor).
  const rentColors = useMemo(() => buildRentColorScale(listings), [listings]);

  // Marker pixel radius: bigger on mobile, scales with zoom for finger-friendly tap.
  const radius = useMemo(() => {
    const base = isMobile ? 11 : 7;
    if (zoom >= 17) return base + 3;
    if (zoom >= 15) return base + 1;
    if (zoom >= 13) return base;
    return base - 1;
  }, [zoom, isMobile]);

  return (
    <>
      {cells.map((cell, i) => {
        // Cluster when we have enough markers in this 300 m grid AND we aren't
        // zoomed in close enough to see them individually (≥16 always splits).
        if (cell.members.length >= MIN_CLUSTER_SIZE && zoom < 16) {
          return (
            <Marker
              key={`c${i}`}
              position={[cell.lat, cell.lon]}
              icon={clusterIcon(cell.members.length)}
              eventHandlers={{
                click: () => {
                  map.setView([cell.lat, cell.lon], Math.min(zoom + 2, 17), {
                    animate: true,
                  });
                },
              }}
            />
          );
        }
        return cell.members.map(
          (l) =>
            l.lat &&
            l.lon && (
              <Marker
                key={l.id}
                position={[l.lat, l.lon]}
                icon={pinIcon(
                  rentColors.get(l.id) ?? gapColor(l.score?.gap_percent),
                  radius,
                  l.deal_type === "rent" ? null : (l.score?.percentile_rank ?? null),
                  selectedId === l.id,
                )}
                eventHandlers={{ click: () => onListingClick?.(l.id) }}
                title={isMobile ? undefined : (l.address ?? l.title ?? l.id).slice(0, 60)}
              />
            )
        );
      })}
    </>
  );
}

export function MapView({
  listings,
  zones,
  show836 = false,
  gps,
  radiusMeters = 2000,
  follow,
  onFollowChange,
  onListingClick,
  onBackgroundClick,
  onMapMove,
  selectedId,
  defaultZoom = 15,
  trackingZoom,
  isMobile = false,
}: Props) {
  const center: [number, number] = useMemo(() => {
    if (gps) return [gps.lat, gps.lon];
    // Default focus: the Herzliya–Tel Aviv corridor (the area of interest).
    return [CORRIDOR_CENTER.lat, CORRIDOR_CENTER.lon];
  }, [gps]);

  return (
    <div className="relative h-full w-full isolate">
      <MapContainer
        center={center}
        zoom={defaultZoom}
        className="h-full w-full"
        scrollWheelZoom
        // Hide Leaflet's default top-left +/- controls. They collide with our
        // Zones / Refresh chip strip on mobile and pinch-to-zoom is fine for
        // touch users; desktop users still have scroll-wheel zoom.
        zoomControl={false}
      >
        <TileLayer
          attribution="&copy; OpenStreetMap"
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FollowController gps={gps} follow={follow} trackingZoom={trackingZoom} />
        <FocusController listings={listings} selectedId={selectedId} />
        <ManualInteractionWatcher
          onFollowChange={onFollowChange}
          onBackgroundClick={onBackgroundClick}
          onMapMove={onMapMove}
        />
        {zones && zones.features.length > 0 && <ZonesLayer zones={zones} />}
        {show836 && <Line836Layer />}
        {gps && (
          <>
            <Marker position={[gps.lat, gps.lon]} icon={gpsIcon} />
            <Circle
              center={[gps.lat, gps.lon]}
              radius={radiusMeters}
              pathOptions={{ color: "#2563eb", fillOpacity: 0.05, weight: 1 }}
            />
          </>
        )}
        <MarkersLayer
          listings={listings}
          isMobile={isMobile}
          onListingClick={onListingClick}
          selectedId={selectedId}
        />
      </MapContainer>

      {gps && !follow && (
        <button
          onClick={() => onFollowChange(true)}
          aria-label="Recenter on my location"
          className="absolute right-3 bottom-3 z-[400] flex h-12 w-12 items-center justify-center rounded-full bg-white text-slate-800 shadow-lg hover:bg-slate-100 active:scale-95 transition"
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
          </svg>
        </button>
      )}
    </div>
  );
}
