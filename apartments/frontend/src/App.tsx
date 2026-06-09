import { useState } from "react";
import { MapPage } from "@/pages/MapPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { HealthLed } from "@/components/HealthLed";
import { FreshnessFooter } from "@/components/FreshnessFooter";

// "Deals" used to be a peer top-level destination; it's now a filter preset
// inside Map (the 🔥 Top deals only toggle in FilterBar). Map and Analytics
// are the only two real modes — everything else is a facet of Map.
type Page = "map" | "analytics";

export function App() {
  const [page, setPage] = useState<Page>("map");

  return (
    <div className="flex h-full flex-col">
      {/* Full-width heartbeat strip at the very top — overall + per-source */}
      <HealthLed />
      <header className="flex items-center justify-between border-b border-slate-800 bg-slate-950 px-4 py-2 gap-3">
        <div className="font-semibold tracking-tight">Apartment Scanner</div>
        <nav className="flex gap-1 text-sm">
          <NavBtn active={page === "map"} onClick={() => setPage("map")}>Map</NavBtn>
          <NavBtn active={page === "analytics"} onClick={() => setPage("analytics")}>Analytics</NavBtn>
        </nav>
      </header>
      <main className="flex-1 overflow-hidden relative">
        {page === "map" ? <MapPage /> : <AnalyticsPage />}
      </main>
      <footer className="border-t border-slate-800 bg-slate-950">
        <FreshnessFooter />
      </footer>
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
