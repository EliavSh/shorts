import {
  CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis
} from "recharts";
import type { BuildingTransaction } from "@/types";

interface Props {
  transactions: BuildingTransaction[];
}

export function BuildingHistoryChart({ transactions }: Props) {
  if (!transactions.length) return <div className="text-sm text-slate-500">No building history.</div>;
  const data = transactions.map((t) => ({
    x: new Date(t.date).getTime(),
    y: t.ppsqm ?? 0,
    rooms: t.rooms ?? 0,
    address: t.address,
    date: t.date,
  }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <ScatterChart margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
        <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
        <XAxis
          type="number" dataKey="x" name="Date" domain={["auto", "auto"]}
          tickFormatter={(t) => new Date(t).toISOString().slice(0, 7)}
          tick={{ fill: "#94a3b8", fontSize: 10 }}
        />
        <YAxis
          type="number" dataKey="y" name="₪/m²"
          tick={{ fill: "#94a3b8", fontSize: 10 }}
          tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
        />
        <ZAxis dataKey="rooms" range={[40, 120]} />
        <Tooltip
          cursor={{ stroke: "#475569" }}
          contentStyle={{ background: "#0f172a", border: "1px solid #334155", color: "#e2e8f0" }}
          formatter={(v: number, name: string) =>
            name === "Date" ? [new Date(v).toISOString().slice(0, 10), "date"]
              : name === "₪/m²" ? [`₪${v.toLocaleString()}/m²`, "₪/m²"]
              : [v, name]
          }
        />
        <Scatter data={data} fill="#60a5fa" />
      </ScatterChart>
    </ResponsiveContainer>
  );
}
