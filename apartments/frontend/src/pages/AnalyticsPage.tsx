import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { MapContainer, TileLayer } from "react-leaflet";
import { fetchKpis, fetchScrapeGraph } from "@/api/analytics";
import { fetchCityStats, fetchVelocity } from "@/api/charts";
import { ScrapeGraph } from "@/components/ScrapeGraph";
import { CityStatsChart } from "@/components/CityStatsChart";
import { VelocityHeatmap } from "@/components/VelocityHeatmap";

export function AnalyticsPage() {
  const [velocityMode, setVelocityMode] = useState<"absolute" | "delta">("delta");

  const kpis = useQuery({ queryKey: ["kpis"], queryFn: fetchKpis, refetchInterval: 15_000 });
  const graph = useQuery({
    queryKey: ["scrape-graph", 30],
    queryFn: () => fetchScrapeGraph(30),
    refetchInterval: 15_000,
  });
  const cityStats = useQuery({
    queryKey: ["city-stats"],
    queryFn: fetchCityStats,
    refetchInterval: 60_000,
  });
  const velocity = useQuery({
    queryKey: ["velocity", 7],
    queryFn: () => fetchVelocity({ days: 7 }),
    refetchInterval: 60_000,
  });

  return (
    <div className="p-6 space-y-6 overflow-y-auto h-full">
      <h1 className="text-2xl font-semibold">Scrape Analytics</h1>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi label="Active listings" value={kpis.data?.active_listings.toLocaleString() ?? "—"} />
        <Kpi label="Added today" value={kpis.data?.added_today ?? "—"} />
        <Kpi label="Removed today" value={kpis.data?.removed_today ?? "—"} />
        <Kpi label="Last run" value={kpis.data?.last_successful_run?.slice(0, 16) ?? "—"} />
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="mb-3 text-lg">Listings added vs. removed (30d)</h2>
        {graph.data ? <ScrapeGraph data={graph.data} /> : <div className="text-slate-500">Loading…</div>}
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg">Velocity heatmap (7d)</h2>
          <div className="flex gap-1 text-sm">
            {(["delta", "absolute"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setVelocityMode(m)}
                className={`min-h-[36px] rounded px-3 py-1 ${
                  velocityMode === m ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-300"
                }`}
              >
                {m === "delta" ? "Δ vs prior 7d" : "absolute"}
              </button>
            ))}
          </div>
        </div>
        <div className="h-[400px] rounded overflow-hidden">
          <MapContainer center={[32.0853, 34.7818]} zoom={11} className="h-full w-full">
            <TileLayer
              attribution="&copy; OpenStreetMap"
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {velocity.data && <VelocityHeatmap cells={velocity.data} mode={velocityMode} />}
          </MapContainer>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          {velocityMode === "delta"
            ? "Green = more new listings this week than last; red = fewer."
            : "Density of listings added in the last 7 days."}
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <CityStatsChart data={cityStats.data ?? []} metric="count" title="Active listings per city (top 20)" />
        <CityStatsChart data={cityStats.data ?? []} metric="avg_ppsqm" title="Avg ₪/m² per city" />
      </div>
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}
