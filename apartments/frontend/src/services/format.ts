// Sale prices are large → abbreviate to millions (₪2.35M). Rents are small →
// show exact shekels (₪14,700). Pick per mode via fmtAmount.
export const fmtPrice = (n?: number | null) =>
  n ? `₪${(n / 1_000_000).toFixed(2)}M` : "—";

/** Exact shekels with thousands separators: ₪14,700. */
export const fmtMoney = (n?: number | null) =>
  n != null ? `₪${Math.round(n).toLocaleString()}` : "—";

/** Mode-aware amount: exact ₪ for rent, abbreviated ₪M for sale. */
export const fmtAmount = (n: number | null | undefined, dealType?: string | null) =>
  dealType === "rent" ? fmtMoney(n) : fmtPrice(n);

export const fmtPpsqm = (n?: number | null) =>
  n ? `₪${Math.round(n).toLocaleString()}/m²` : "—";

export const fmtPercent = (n?: number | null, signed = false) => {
  if (n == null) return "—";
  const sign = signed && n > 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}%`;
};

/** Compact distance label: "120 m", "1.4 km". */
export const fmtDistance = (meters?: number | null): string => {
  if (meters == null || !Number.isFinite(meters)) return "";
  if (meters < 1000) return `${Math.round(meters)} m`;
  return `${(meters / 1000).toFixed(meters < 10_000 ? 1 : 0)} km`;
};

export function haversineMeters(
  lat1: number, lon1: number, lat2: number, lon2: number
): number {
  const R = 6_371_000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
