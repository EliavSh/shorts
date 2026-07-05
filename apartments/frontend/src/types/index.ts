// TypeScript mirrors of the Pydantic schemas in scanner/api/schemas.py

export interface Listing {
  id: string;
  title?: string | null;
  address?: string | null;
  city?: string | null;
  neighborhood?: string | null;
  rooms?: number | null;
  sqm?: number | null;
  floor?: number | null;
  price?: number | null;
  price_per_sqm?: number | null;
  url?: string | null;
  posted_at?: string | null;
  lat?: number | null;
  lon?: number | null;
  is_active?: boolean | null;
  first_seen?: string | null;
  last_seen?: string | null;
  is_new_construction?: boolean | null;
  has_balcony?: boolean | null;
  direction?: string | null;
  deal_type?: "sale" | "rent" | null;
  vaad_bayit?: number | null;
  arnona?: number | null;
}

export type DealType = "sale" | "rent";

export interface ListingScore {
  listing_id: string;
  gap_percent?: number | null;
  nadlan_median_ppsqm?: number | null;
  /** Street-level (near) cohort percentile — drives the map ring. */
  percentile_rank?: number | null;
  z_score?: number | null;
  motivation_score?: number | null;
  value_add_gap?: number | null;
  days_on_market?: number | null;
  n_cohort_sales?: number | null;
  near_scope?: string | null;
  near_n_sales?: number | null;
  near_median_ppsqm?: number | null;
  /** Wider rooms-aware cohort percentile (same city + same rooms bucket). */
  area_percentile_rank?: number | null;
  area_n_sales?: number | null;
  area_median_ppsqm?: number | null;
}

export interface ListingWithScore extends Listing {
  score?: ListingScore | null;
}

export interface PercentileScope {
  percentile: number;
  n_sales: number;
  median_price: number;
  p25: number;
  p75: number;
  scope: "building" | "street_block" | "street" | "rooms_cohort";
  label: string;
}

/**
 * Dual-scope percentile: `near` is the street-level cohort that drives the
 * map ring; `area` is the same-city, same-rooms-bucket cohort. Either may be
 * null when its threshold isn't met.
 */
export interface PercentileResponse {
  near: PercentileScope | null;
  area: PercentileScope | null;
  cohort_points: [number, number][];
}

export interface ScrapeGraphPoint {
  date: string;
  added: number;
  removed: number;
  active: number;
}

export interface DealCard {
  listing: Listing;
  score: ListingScore;
  explanation: string;
}

export interface Filters {
  // Sale (asking prices) vs rent (monthly rent) — the top-level mode. Defaults
  // to "sale" server-side when omitted.
  deal_type?: DealType;
  city?: string;
  neighborhood?: string;
  min_rooms?: number;
  max_rooms?: number;
  min_price?: number;
  max_price?: number;
  // Rent-mode budget filter: total monthly cost = rent + ועד בית + ארנונה.
  min_total?: number;
  max_total?: number;
  include_new_construction?: boolean;  // default true
  only_new_construction?: boolean;
  restrict_to_zones?: boolean;
  // Client-side preset: filter to listings with gap_percent <= -10 and sort
  // ascending by gap. Equivalent to the old standalone Deals page.
  top_deals_only?: boolean;
}

export interface SourceHealth {
  source: string;
  status: "green" | "yellow" | "red";
  reason: string;
  ended_at: string | null;
  age_hours: number | null;
}

export interface Freshness {
  sources: Record<string, { last_success: string | null; successful_runs: number }>;
  counts: { active_listings: number; transactions: number; zones: number };
}

export interface CityStat {
  city: string;
  count: number;
  avg_price: number | null;
  avg_ppsqm: number | null;
  avg_rooms: number | null;
}

export interface VelocityCell {
  lat: number;
  lon: number;
  count: number;
  delta: number;
  size_deg: number;
}

export interface PriceEvent {
  event_type: string;
  price: number;
  date: string;
}

export interface BuildingTransaction {
  address: string;
  price: number;
  sqm: number;
  ppsqm: number | null;
  rooms: number | null;
  date: string;
}

export interface GpsCoords {
  lat: number;
  lon: number;
  accuracy: number;
  timestamp: number;
}
