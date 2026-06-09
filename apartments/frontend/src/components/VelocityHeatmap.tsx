import { Rectangle } from "react-leaflet";
import type { VelocityCell } from "@/types";

interface Props {
  cells: VelocityCell[];
  mode: "absolute" | "delta";
}

function color(cell: VelocityCell, mode: "absolute" | "delta", maxAbs: number): { fill: string; opacity: number } {
  if (mode === "delta") {
    if (cell.delta > 0) return { fill: "#16a34a", opacity: Math.min(0.7, cell.delta / Math.max(1, maxAbs)) };
    if (cell.delta < 0) return { fill: "#dc2626", opacity: Math.min(0.7, -cell.delta / Math.max(1, maxAbs)) };
    return { fill: "#94a3b8", opacity: 0.05 };
  }
  return { fill: "#3b82f6", opacity: Math.min(0.7, cell.count / Math.max(1, maxAbs)) };
}

export function VelocityHeatmap({ cells, mode }: Props) {
  const maxAbs =
    mode === "delta"
      ? Math.max(1, ...cells.map((c) => Math.abs(c.delta)))
      : Math.max(1, ...cells.map((c) => c.count));

  return (
    <>
      {cells.map((c, i) => {
        const half = c.size_deg / 2;
        const { fill, opacity } = color(c, mode, maxAbs);
        return (
          <Rectangle
            key={i}
            bounds={[
              [c.lat - half, c.lon - half],
              [c.lat + half, c.lon + half],
            ]}
            pathOptions={{
              color: fill,
              weight: 0.5,
              fillColor: fill,
              fillOpacity: opacity,
            }}
          />
        );
      })}
    </>
  );
}
