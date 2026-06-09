import { Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Scatter, ComposedChart } from "recharts";
import type { PriceEvent } from "@/types";

interface Props {
  events: PriceEvent[];
}

export function PriceHistoryChart({ events }: Props) {
  if (!events.length) return <div className="text-sm text-slate-500">No price events.</div>;
  const data = events.map((e) => ({ ...e, price_m: e.price / 1_000_000 }));
  return (
    <ResponsiveContainer width="100%" height={180}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
        <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
        <XAxis dataKey="date" tick={{ fill: "#94a3b8", fontSize: 10 }} />
        <YAxis tick={{ fill: "#94a3b8", fontSize: 10 }} unit="M" />
        <Tooltip
          contentStyle={{ background: "#0f172a", border: "1px solid #334155", color: "#e2e8f0" }}
          formatter={(v: number) => [`₪${v.toFixed(2)}M`, "price"]}
        />
        <Line type="monotone" dataKey="price_m" stroke="#60a5fa" strokeWidth={2} dot={{ r: 3 }} />
        <Scatter dataKey="price_m" fill="#dc2626" />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
