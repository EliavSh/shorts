import { api } from "./client";
import type { DealCard, ScrapeGraphPoint } from "@/types";

export async function fetchScrapeGraph(days = 30, city?: string): Promise<ScrapeGraphPoint[]> {
  const { data } = await api.get<ScrapeGraphPoint[]>("/analytics/scrape-graph", {
    params: { days, city },
  });
  return data;
}

export async function fetchKpis(): Promise<{
  active_listings: number;
  added_today: number;
  removed_today: number;
  last_successful_run: string | null;
}> {
  const { data } = await api.get("/analytics/kpis");
  return data;
}

export async function fetchDeals(
  sort: "gap" | "motivation" | "value_add" = "gap",
  limit = 50
): Promise<DealCard[]> {
  const { data } = await api.get<DealCard[]>("/deals", { params: { sort, limit } });
  return data;
}
