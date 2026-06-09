import { useQuery } from "@tanstack/react-query";
import { fetchListings } from "@/api/listings";
import { fetchZones } from "@/api/zones";
import type { Filters } from "@/types";

interface SpatialOpts {
  near_lat?: number;
  near_lon?: number;
  near_radius_m?: number;
}

export function useListings(filters: Filters, spatial: SpatialOpts = {}) {
  // Bucket spatial coords to ~150m so we don't refetch on every GPS jitter.
  const bucketed = bucketSpatial(spatial);
  return useQuery({
    queryKey: ["listings", filters, bucketed],
    queryFn: () => fetchListings({ ...filters, ...spatial }),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useZones(spatial: SpatialOpts = {}) {
  const bucketed = bucketSpatial(spatial);
  return useQuery({
    queryKey: ["zones", bucketed],
    queryFn: () => fetchZones(spatial),
    staleTime: 5 * 60_000,
  });
}

function bucketSpatial(s: SpatialOpts): SpatialOpts {
  if (s.near_lat == null || s.near_lon == null) return {};
  const round = (n: number) => Math.round(n * 700) / 700; // ~150m bucket
  return {
    near_lat: round(s.near_lat),
    near_lon: round(s.near_lon),
    near_radius_m: s.near_radius_m,
  };
}

