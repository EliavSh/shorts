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

export interface SystemStatus {
  server_time: string;
  counts: { sale: number | null; rent: number | null; transactions: number | null };
  enrichment: { rent_with_costs: number | null; rent_with_amenities: number | null };
  recent_runs: {
    source: string;
    status: string;
    ended_at: string | null;
    rows_scraped: number | null;
    rows_inserted: number | null;
    error: string | null;
    captcha: boolean;
  }[];
}

export async function fetchStatus(): Promise<SystemStatus> {
  const { data } = await api.get<SystemStatus>("/meta/status");
  return data;
}
