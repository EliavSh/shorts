import { api } from "./client";

export interface ZoneFeature {
  type: "Feature";
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
  properties: {
    id: number;
    zone_name: string | null;
    city: string | null;
    status: string | null;
    track: string | null;
    planning_status: string | null;
    units_existing: number | null;
    units_added: number | null;
    units_total: number | null;
    centroid: [number, number] | null;
  };
}

export interface ZonesCollection {
  type: "FeatureCollection";
  features: ZoneFeature[];
}

export async function fetchZones(opts: {
  near_lat?: number;
  near_lon?: number;
  near_radius_m?: number;
} = {}): Promise<ZonesCollection> {
  const { data } = await api.get<ZonesCollection>("/zones", { params: opts });
  return data;
}
