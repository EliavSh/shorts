import { useState } from "react";
import { MapPage } from "@/pages/MapPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { HealthLed } from "@/components/HealthLed";
import { FreshnessFooter } from "@/components/FreshnessFooter";
import type { DealType } from "@/types";

// Two orthogonal dimensions:
//   mode — For sale vs For rent (the primary switch). Rent is listings-only.
//   page — Map vs Analytics. Analytics (deal/sold analysis) is sale-only, so
//          it's hidden in rent mode and everything collapses to the map.
type Page = "map" | "analytics";

export function App() {
  const [mode, setMode] = useState<DealType>("rent");
  const [page, setPage] = useState<Page>("map");

  const showAnalytics = mode === "sale";
  const effectivePage: Page = showAnalytics ? page : "map";

  return (
    <div className="flex h-full flex-col">
      {/* Full-width heartbeat strip at the very top — overall + per-source */}
      <HealthLed />
      <header className="flex items-center justify-between border-b border-slate-800 bg-slate-950 px-4 py-2 gap-3">
        <div className="flex items-center gap-3">
          <div className="font-semibold tracking-tight">Apartment Scanner</div>
          <ModeToggle mode={mode} onChange={setMode} />
        </div>
        {showAnalytics && (
          <nav className="flex gap-1 text-sm">
            <NavBtn active={effectivePage === "map"} onClick={() => setPage("map")}>Map</NavBtn>
            <NavBtn active={effectivePage === "analytics"} onClick={() => setPage("analytics")}>Analytics</NavBtn>
          </nav>
        )}
      </header>
      <main className="flex-1 overflow-hidden relative">
        {effectivePage === "map" ? <MapPage mode={mode} /> : <AnalyticsPage />}
      </main>
      <footer className="border-t border-slate-800 bg-slate-950">
        <FreshnessFooter />
      </footer>
    </div>
  );
}

function ModeToggle({ mode, onChange }: { mode: DealType; onChange: (m: DealType) => void }) {
  return (
    <div className="flex rounded-full bg-slate-800 p-0.5 text-sm" role="tablist" aria-label="Sale or rent">
      {(["sale", "rent"] as DealType[]).map((m) => (
        <button
          key={m}
          role="tab"
          aria-selected={mode === m}
          onClick={() => onChange(m)}
          className={`min-h-[32px] rounded-full px-4 py-1 font-medium transition ${
            mode === m ? "bg-emerald-600 text-white shadow" : "text-slate-300 hover:text-white"
          }`}
        >
          {m === "sale" ? "For sale" : "For rent"}
        </button>
      ))}
    </div>
  );
}

function NavBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`min-h-[36px] rounded px-3 py-1 ${active ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"}`}
    >
      {children}
    </button>
  );
}
