import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchDeals } from "@/api/analytics";
import { GapValueCards } from "@/components/GapValueCards";
import { fmtPercent, fmtPpsqm, fmtPrice } from "@/services/format";
import type { DealCard } from "@/types";

type SortKey = "gap" | "motivation" | "value_add";

export function DealsPage() {
  const [sort, setSort] = useState<SortKey>("gap");
  const { data, isLoading } = useQuery({
    queryKey: ["deals", sort],
    queryFn: () => fetchDeals(sort, 100),
    refetchInterval: 60_000,
  });

  const deals = data ?? [];
  const top = deals.slice(0, 12);

  return (
    <div className="h-full overflow-y-auto p-4 space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Top Deals</h1>
          <p className="text-sm text-slate-400">{deals.length} qualifying listings · sort by</p>
        </div>
        <div className="flex gap-1">
          {(["gap", "motivation", "value_add"] as SortKey[]).map((k) => (
            <button
              key={k}
              onClick={() => setSort(k)}
              className={`min-h-[36px] rounded px-3 py-1 text-sm ${
                sort === k ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-300"
              }`}
            >
              {k === "gap" ? "Gap %" : k === "motivation" ? "🔥 Motivation" : "₪ below market"}
            </button>
          ))}
          <button
            onClick={() => downloadCsv(deals)}
            className="min-h-[36px] rounded bg-slate-800 px-3 py-1 text-sm text-slate-300 hover:bg-slate-700"
          >
            Export CSV
          </button>
        </div>
      </header>

      <section>
        <h2 className="mb-2 text-sm uppercase tracking-wide text-slate-400">Gap-to-Value cards</h2>
        {isLoading && <div className="text-slate-500">Loading deals…</div>}
        <GapValueCards deals={top} />
      </section>

      <section>
        <h2 className="mb-2 text-sm uppercase tracking-wide text-slate-400">Full ranked table</h2>
        <div className="overflow-x-auto rounded-lg border border-slate-800">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-950 text-slate-400">
              <tr>
                <Th>Address</Th>
                <Th>City</Th>
                <Th>Rooms</Th>
                <Th>m²</Th>
                <Th>Price</Th>
                <Th>₪/m²</Th>
                <Th>Gap</Th>
                <Th>🔥</Th>
                <Th>₪ below mkt</Th>
                <Th>DOM</Th>
                <Th>n cohort</Th>
              </tr>
            </thead>
            <tbody>
              {deals.map((d) => (
                <tr key={d.listing.id} className="border-t border-slate-800 hover:bg-slate-900">
                  <Td>
                    {d.listing.url ? (
                      <a className="text-blue-400 hover:underline" target="_blank" rel="noreferrer" href={d.listing.url}>
                        {d.listing.address ?? "—"}
                      </a>
                    ) : (
                      d.listing.address ?? "—"
                    )}
                  </Td>
                  <Td>{d.listing.city ?? "—"}</Td>
                  <Td>{d.listing.rooms ?? "—"}</Td>
                  <Td>{d.listing.sqm ?? "—"}</Td>
                  <Td>{fmtPrice(d.listing.price)}</Td>
                  <Td>{fmtPpsqm(d.listing.price_per_sqm)}</Td>
                  <Td className={d.score.gap_percent != null && d.score.gap_percent <= -10 ? "text-green-400" : ""}>
                    {fmtPercent(d.score.gap_percent, true)}
                  </Td>
                  <Td><MotivationBar value={d.score.motivation_score ?? null} /></Td>
                  <Td>{d.score.value_add_gap ? `₪${Math.round(d.score.value_add_gap).toLocaleString()}` : "—"}</Td>
                  <Td>{d.score.days_on_market ?? "—"}</Td>
                  <Td>{d.score.n_cohort_sales ?? "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-2 py-2 text-left text-xs font-medium uppercase tracking-wide whitespace-nowrap">{children}</th>;
}

function Td({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <td className={`px-2 py-2 whitespace-nowrap ${className}`}>{children}</td>;
}

function MotivationBar({ value }: { value: number | null }) {
  if (value == null) return <span className="text-slate-500">—</span>;
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="flex items-center gap-1">
      <div className="h-2 w-16 rounded-full bg-slate-800">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, background: pct > 70 ? "#dc2626" : pct > 40 ? "#eab308" : "#16a34a" }}
        />
      </div>
      <span className="text-xs text-slate-400 tabular-nums">{Math.round(pct)}</span>
    </div>
  );
}

function downloadCsv(deals: DealCard[]) {
  const header = ["id", "address", "city", "rooms", "sqm", "price", "ppsqm",
    "gap_percent", "motivation_score", "value_add_gap", "days_on_market",
    "n_cohort_sales", "z_score", "url"];
  const rows = deals.map((d) => [
    d.listing.id, d.listing.address ?? "", d.listing.city ?? "",
    d.listing.rooms ?? "", d.listing.sqm ?? "", d.listing.price ?? "",
    d.listing.price_per_sqm ?? "",
    d.score.gap_percent ?? "", d.score.motivation_score ?? "",
    d.score.value_add_gap ?? "", d.score.days_on_market ?? "",
    d.score.n_cohort_sales ?? "", d.score.z_score ?? "",
    d.listing.url ?? "",
  ]);
  const csv = [header, ...rows].map((r) =>
    r.map((cell) => {
      const s = String(cell ?? "");
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(",")
  ).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `deals_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
