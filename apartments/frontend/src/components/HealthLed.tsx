import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchHealth, fetchStatus } from "@/api/meta";
import type { SourceHealth } from "@/types";

const DOT_COLOR: Record<SourceHealth["status"], string> = {
  green: "#16a34a",
  yellow: "#eab308",
  red: "#dc2626",
};

const STRIP_BG: Record<SourceHealth["status"], string> = {
  green: "bg-emerald-700/90",
  yellow: "bg-amber-600/90",
  red: "bg-red-700/90",
};

const STRIP_LABEL: Record<SourceHealth["status"], string> = {
  green: "All sources fresh",
  yellow: "Some sources stale",
  red: "Source(s) stalled",
};

// Friendlier short labels for the heartbeat pills.
const SOURCE_LABEL: Record<string, string> = {
  yad2: "yad2",
  yad2_sold: "sold",
  pinui_binui: "zones",
  madlan: "madlan",
  nadlan: "nadlan",
};

function rollup(sources: SourceHealth[]): SourceHealth["status"] {
  if (sources.some((s) => s.status === "red")) return "red";
  if (sources.some((s) => s.status === "yellow")) return "yellow";
  return "green";
}

function fmtAge(h: number | null): string {
  if (h == null) return "never";
  if (h < 1) return `${Math.max(1, Math.round(h * 60))}m ago`;
  if (h < 24) return `${Math.round(h)}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

/**
 * Slim full-width heartbeat strip. Per-source pills are always visible (no
 * hover-only labels — mobile-first). Tapping a pill expands a small card with
 * the source's full reason / last-success / age, anchored under the strip.
 */
export function HealthLed() {
  const [openSource, setOpenSource] = useState<string | null>(null);
  const [showStatus, setShowStatus] = useState(false);
  const { data } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
  });

  if (!data || data.length === 0) {
    return (
      <div className="flex h-6 w-full items-center justify-center bg-slate-800 text-xs text-slate-400">
        Heartbeat: loading…
      </div>
    );
  }

  const overall = rollup(data);
  const open = data.find((s) => s.source === openSource) ?? null;

  return (
    <div className="relative w-full">
      <div
        className={`flex h-7 w-full items-center gap-2 px-3 text-xs text-white ${STRIP_BG[overall]}`}
      >
        <button
          onClick={() => setShowStatus(true)}
          className="font-medium underline-offset-2 hover:underline"
          title="System status"
        >
          {STRIP_LABEL[overall]} ⓘ
        </button>
        <span className="ml-auto flex items-center gap-2">
          {data.map((s) => {
            const isOpen = openSource === s.source;
            return (
              <button
                key={s.source}
                onClick={() => setOpenSource(isOpen ? null : s.source)}
                aria-expanded={isOpen}
                className={`flex items-center gap-1 rounded-full px-2 py-0.5 transition ${
                  isOpen
                    ? "bg-white/20"
                    : "hover:bg-white/10 active:bg-white/20"
                }`}
              >
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: DOT_COLOR[s.status] }}
                />
                <span>{SOURCE_LABEL[s.source] ?? s.source}</span>
              </button>
            );
          })}
        </span>
      </div>

      {open && (
        <div className="absolute right-2 top-full z-50 mt-1 w-72 rounded-md border border-slate-700 bg-slate-900 p-3 text-xs text-slate-200 shadow-xl">
          <div className="flex items-start justify-between gap-2">
            <div className="font-semibold">{open.source}</div>
            <button
              onClick={() => setOpenSource(null)}
              className="text-slate-500 hover:text-slate-300"
              aria-label="Close"
            >
              ✕
            </button>
          </div>
          <div className="mt-1 flex items-center gap-2">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: DOT_COLOR[open.status] }}
            />
            <span className="capitalize">{open.status}</span>
            <span className="text-slate-500">·</span>
            <span>{fmtAge(open.age_hours)}</span>
          </div>
          {open.reason && (
            <div className="mt-1 text-slate-400">{open.reason}</div>
          )}
          {open.ended_at && (
            <div className="mt-1 text-slate-500">
              Last run: {new Date(open.ended_at).toLocaleString()}
            </div>
          )}
        </div>
      )}

      {showStatus && <StatusModal onClose={() => setShowStatus(false)} />}
    </div>
  );
}

/** Consolidated system status (was previously pushed to Telegram): DB counts,
 *  enrichment coverage and the recent scrape-run log. */
function StatusModal({ onClose }: { onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["system-status"],
    queryFn: fetchStatus,
    refetchInterval: 30_000,
  });
  return (
    <div className="fixed inset-0 z-[1100] flex items-start justify-center bg-black/60 p-3" onClick={onClose}>
      <div
        className="mt-10 w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-900 p-4 text-sm text-slate-200 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <div className="text-base font-semibold">System status</div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200" aria-label="Close">✕</button>
        </div>
        {isLoading || !data ? (
          <div className="text-slate-500">Loading…</div>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-2 mb-3">
              <Stat label="Sale" value={data.counts.sale} />
              <Stat label="Rent" value={data.counts.rent} />
              <Stat label="Transactions" value={data.counts.transactions} />
            </div>
            <div className="mb-3 text-xs text-slate-400">
              Rent enriched — costs: <b className="text-slate-200">{data.enrichment.rent_with_costs ?? 0}</b>{" "}
              · amenities: <b className="text-slate-200">{data.enrichment.rent_with_amenities ?? 0}</b>
            </div>
            <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Recent scrape runs</div>
            <div className="max-h-72 overflow-auto rounded border border-slate-800">
              {data.recent_runs.length === 0 ? (
                <div className="p-3 text-slate-500">No runs recorded.</div>
              ) : (
                <table className="w-full text-xs">
                  <tbody>
                    {data.recent_runs.map((r, i) => (
                      <tr key={i} className="border-b border-slate-800 last:border-0">
                        <td className="py-1 px-2">
                          <span
                            className="mr-1 inline-block h-2 w-2 rounded-full align-middle"
                            style={{ backgroundColor: r.status === "success" ? "#16a34a" : r.captcha ? "#dc2626" : "#eab308" }}
                          />
                          {r.source}
                        </td>
                        <td className="py-1 px-2 text-slate-400">{r.status}{r.captcha ? " (captcha)" : ""}</td>
                        <td className="py-1 px-2 text-slate-400">{r.rows_scraped ?? "—"} rows</td>
                        <td className="py-1 px-2 text-slate-500 whitespace-nowrap">
                          {r.ended_at ? new Date(r.ended_at).toLocaleString() : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="mt-2 text-[11px] text-slate-600">Server time {data.server_time}</div>
          </>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-lg bg-slate-800/60 p-2 text-center">
      <div className="text-lg font-semibold text-slate-100">{value?.toLocaleString() ?? "—"}</div>
      <div className="text-[11px] text-slate-400">{label}</div>
    </div>
  );
}
