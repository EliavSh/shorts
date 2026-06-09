import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CityStat } from "@/types";

interface Props {
  data: CityStat[];
  metric: "count" | "avg_price" | "avg_ppsqm";
  title: string;
}

export function CityStatsChart({ data, metric, title }: Props) {
  const sorted = [...data].sort((a, b) => (b[metric] ?? 0) - (a[metric] ?? 0)).slice(0, 20);
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h3 className="mb-2 text-sm font-medium text-slate-300">{title}</h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={sorted} margin={{ top: 4, right: 4, bottom: 60, left: 0 }}>
          <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
          <XAxis dataKey="city" angle={-45} textAnchor="end" interval={0} tick={{ fill: "#94a3b8", fontSize: 10 }} />
          <YAxis tick={{ fill: "#94a3b8", fontSize: 10 }} />
          <Tooltip
            contentStyle={{ background: "#0f172a", border: "1px solid #334155", color: "#e2e8f0" }}
            formatter={(v: number) =>
              metric === "count"
                ? [v.toLocaleString(), "count"]
                : metric === "avg_price"
                ? [`₪${(v / 1_000_000).toFixed(2)}M`, "avg price"]
                : [`₪${v.toLocaleString()}/m²`, "avg ₪/m²"]
            }
          />
          <Bar dataKey={metric} fill="#60a5fa" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
