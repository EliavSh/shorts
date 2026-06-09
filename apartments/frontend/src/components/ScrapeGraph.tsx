import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ScrapeGraphPoint } from "@/types";

interface Props {
  data: ScrapeGraphPoint[];
}

export function ScrapeGraph({ data }: Props) {
  return (
    <ResponsiveContainer width="100%" height={320}>
      <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
        <XAxis dataKey="date" tick={{ fill: "#94a3b8", fontSize: 11 }} />
        <YAxis yAxisId="bars" tick={{ fill: "#94a3b8", fontSize: 11 }} />
        <YAxis
          yAxisId="active"
          orientation="right"
          tick={{ fill: "#94a3b8", fontSize: 11 }}
        />
        <Tooltip
          contentStyle={{
            background: "#0f172a",
            border: "1px solid #334155",
            borderRadius: 6,
            color: "#e2e8f0",
          }}
          formatter={(value: number, name: string) => [value.toLocaleString(), name]}
        />
        <Legend wrapperStyle={{ color: "#94a3b8" }} />
        <Bar yAxisId="bars" dataKey="added" name="Added" fill="#16a34a" />
        <Bar yAxisId="bars" dataKey="removed" name="Removed" fill="#dc2626" />
        <Line
          yAxisId="active"
          type="monotone"
          dataKey="active"
          name="Active total"
          stroke="#60a5fa"
          strokeWidth={2}
          dot={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
