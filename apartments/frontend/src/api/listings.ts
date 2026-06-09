import { api } from "./client";
import type { Filters, ListingWithScore, PercentileResponse } from "@/types";

export async function fetchListings(
  filters: Filters & { near_lat?: number; near_lon?: number; near_radius_m?: number } = {},
  limit = 2000,
): Promise<ListingWithScore[]> {
  const { data } = await api.get<ListingWithScore[]>("/listings", {
    params: { ...filters, limit },
  });
  return data;
}

export async function fetchListing(id: string): Promise<ListingWithScore> {
  const { data } = await api.get<ListingWithScore>(`/listings/${encodeURIComponent(id)}`);
  return data;
}

export async function fetchPercentile(listingId: string): Promise<PercentileResponse> {
  const { data } = await api.get<PercentileResponse>(
    `/transactions/percentile/${encodeURIComponent(listingId)}`
  );
  return data;
}
