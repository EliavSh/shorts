import { api } from "./client";
import type { Freshness, SourceHealth } from "@/types";

export async function fetchNeighborhoods(city?: string): Promise<string[]> {
  const { data } = await api.get<string[]>("/meta/neighborhoods", { params: { city } });
  return data;
}

export async function fetchCities(): Promise<{ city: string; count: number }[]> {
  const { data } = await api.get("/meta/cities");
  return data;
}

export async function fetchHealth(): Promise<SourceHealth[]> {
  const { data } = await api.get<SourceHealth[]>("/meta/health");
  return data;
}

export async function fetchFreshness(): Promise<Freshness> {
  const { data } = await api.get<Freshness>("/meta/freshness");
  return data;
}
