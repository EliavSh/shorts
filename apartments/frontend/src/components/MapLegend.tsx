import { useState } from "react";

const COLOR_TIERS: { color: string; label: string; gap: string }[] = [
  { color: "#15803d", label: "Premium deal",  gap: "≥ 25 % below market" },
  { color: "#22c55e", label: "Good deal",     gap: "10 – 25 % below" },
  { color: "#eab308", label: "Near market",   gap: "within ±10 %" },
  { color: "#dc2626", label: "Overpriced",    gap: "> 10 % above market" },
  { color: "#94a3b8", label: "Unscored",      gap: "no comparable transactions yet" },
];

/**
 * A small "?" badge that, when tapped, explains what the pin colors and the
 * white percentile ring around each pin actually mean. New users open the
 * SPA and see colored dots — this is how they figure out what they're looking
 * at without polluting the chrome with a permanent legend.
 */
export function MapLegend({ mode = "sale" }: { mode?: "sale" | "rent" }) {
  const [open, setOpen] = useState(false);
  const isRent = mode === "rent";
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        aria-label="Show map legend"
        className="pointer-events-auto flex h-9 w-9 items-center justify-center rounded-full bg-slate-900/90 text-base font-semibold text-slate-200 shadow active:scale-95"
      >
        ?
      </button>
      {open && (
        <div
          className="fixed inset-0 z-[1100] bg-black/60 flex items-end sm:items-center justify-center pb-safe"
          onClick={() => setOpen(false)}
        >
          <div
            className="m-3 max-w-md w-full rounded-2xl bg-slate-900 border border-slate-700 p-4 text-sm text-slate-200 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="font-semibold text-base">Map legend</div>
              <button
                onClick={() => setOpen(false)}
                className="text-slate-400 hover:text-slate-200"
                aria-label="Close legend"
              >
                ✕
              </button>
            </div>

            {isRent ? (
              <>
                <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">
                  Pin color = rent per m² vs. other rentals shown
                </div>
                <ul className="space-y-1.5 mb-3">
                  <li className="flex items-center gap-2">
                    <span className="inline-block h-3.5 w-3.5 shrink-0 rounded-full border border-white" style={{ background: "hsl(120,68%,45%)" }} />
                    <span className="text-slate-100">Green</span>
                    <span className="ml-auto text-xs text-slate-400">cheapest ₪/m²</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="inline-block h-3.5 w-3.5 shrink-0 rounded-full border border-white" style={{ background: "hsl(60,68%,45%)" }} />
                    <span className="text-slate-100">Yellow</span>
                    <span className="ml-auto text-xs text-slate-400">mid-range</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="inline-block h-3.5 w-3.5 shrink-0 rounded-full border border-white" style={{ background: "hsl(0,68%,45%)" }} />
                    <span className="text-slate-100">Red</span>
                    <span className="ml-auto text-xs text-slate-400">priciest ₪/m²</span>
                  </li>
                </ul>
                <div className="text-xs text-slate-400">
                  Rentals have no recorded-sale comparison, so the scale is
                  relative to the rentals currently on screen — cheaper rent per
                  m² is greener. Tap a pin for rent, ועד בית / ארנונה and total.
                </div>
              </>
            ) : (
              <>
                <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">
                  Pin color = price vs. market
                </div>
                <ul className="space-y-1.5 mb-4">
                  {COLOR_TIERS.map((t) => (
                    <li key={t.label} className="flex items-center gap-2">
                      <span
                        className="inline-block h-3.5 w-3.5 shrink-0 rounded-full border border-white"
                        style={{ background: t.color }}
                      />
                      <span className="text-slate-100">{t.label}</span>
                      <span className="ml-auto text-xs text-slate-400">{t.gap}</span>
                    </li>
                  ))}
                </ul>

                <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">
                  White ring = percentile rank
                </div>
                <div className="flex items-center gap-3">
                  <RingExample percentile={0.9} />
                  <div className="text-xs text-slate-300">
                    The ring fills clockwise to the listing's percentile vs.
                    comparable recorded sales on the same street/block. A near-full
                    ring means this listing is cheaper than most comparable
                    apartments locally. Tap a pin to also see the wider
                    same-city, same-rooms-bucket comparison.
                  </div>
                </div>

                <div className="mt-3 text-xs text-slate-500">
                  Tap an amber pulsing pin to see its full details, transaction
                  history and percentile cohort.
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

/** Tiny inline SVG demoing what a percentile ring looks like. */
function RingExample({ percentile }: { percentile: number }) {
  const r = 12;
  const C = 2 * Math.PI * r;
  return (
    <svg width="36" height="36" viewBox="0 0 28 28" className="shrink-0">
      <circle cx="14" cy="14" r={r} fill="none" stroke="#0f172a" strokeWidth="3" opacity="0.55" />
      <circle
        cx="14"
        cy="14"
        r={r}
        fill="none"
        stroke="#fff"
        strokeWidth="3"
        strokeDasharray={`${(percentile * C).toFixed(1)} ${C.toFixed(1)}`}
        strokeLinecap="round"
        transform="rotate(-90 14 14)"
      />
      <circle cx="14" cy="14" r="7" fill="#22c55e" stroke="white" strokeWidth="2" />
    </svg>
  );
}
