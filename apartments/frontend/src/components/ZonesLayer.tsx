import { GeoJSON } from "react-leaflet";
import type { ZonesCollection } from "@/api/zones";

interface Props {
  zones: ZonesCollection;
}

export function ZonesLayer({ zones }: Props) {
  return (
    <GeoJSON
      data={zones as unknown as GeoJSON.GeoJsonObject}
      style={() => ({
        color: "#a855f7",
        weight: 1.5,
        fillColor: "#a855f7",
        fillOpacity: 0.18,
        opacity: 0.9,
      })}
      onEachFeature={(feature, layer) => {
        const p = feature.properties as ZonesCollection["features"][0]["properties"];
        const html = `
          <div style="font-size:12px;line-height:1.4">
            <strong>${escape(p.zone_name ?? "Pinui Binui")}</strong><br/>
            <span style="color:#94a3b8">${escape(p.city ?? "")}</span><br/>
            ${p.planning_status ? `Status: ${escape(p.planning_status)}<br/>` : ""}
            ${p.units_total ? `Units total: ${p.units_total.toLocaleString()}<br/>` : ""}
            ${p.units_added ? `Units added: ${p.units_added.toLocaleString()}` : ""}
          </div>
        `;
        layer.bindPopup(html);
      }}
    />
  );
}

function escape(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!)
  );
}
