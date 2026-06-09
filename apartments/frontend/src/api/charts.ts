import { api } from "./client";
import type { BuildingTransaction, CityStat, PriceEvent, VelocityCell } from "@/types";

export async function fetchPriceHistory(listingId: string): Promise<PriceEvent[]> {
  const { data } = await api.get<PriceEvent[]>(`/charts/price-history/${encodeURIComponent(listingId)}`);
  return data;
}

export async function fetchBuildingHistory(opts: {
  street: string; number: number; city: string; radius?: number;
}): Promise<BuildingTransaction[]> {
  const { data } = await api.get<BuildingTransaction[]>("/charts/building-history", { params: opts });
  return data;
}

export async function fetchCityStats(): Promise<CityStat[]> {
  const { data } = await api.get<CityStat[]>("/charts/city-stats");
  return data;
}

export async function fetchVelocity(opts: {
  days?: number;
  near_lat?: number; near_lon?: number; near_radius_m?: number;
} = {}): Promise<VelocityCell[]> {
  const { data } = await api.get<VelocityCell[]>("/charts/velocity", { params: opts });
  return data;
}
