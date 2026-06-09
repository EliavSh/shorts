import { ReactNode, useState } from "react";

interface Props {
  /** Always-visible peek content (e.g. summary line). Stays on screen. */
  peek: ReactNode;
  /** Full content shown when the user taps the handle to expand. */
  children: ReactNode;
}

/**
 * A persistent bottom drawer that stays at a small peek height by default
 * and expands to ~85vh when the user taps the handle. Hand-rolled with CSS
 * transforms instead of Vaul because Vaul's controlled snapPoints kept
 * auto-opening to the largest snap on mount, leaving the user trapped.
 *
 * Behavior:
 *   - Initial state: collapsed (only the peek strip + handle are visible).
 *   - Tap handle: toggles between collapsed and expanded.
 *   - Always present, never closes — hence "persistent".
 */
export function PersistentSheet({ peek, children }: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={`fixed bottom-0 left-0 right-0 z-[900] rounded-t-2xl bg-slate-900 pb-safe shadow-[0_-4px_20px_rgba(0,0,0,0.5)] transition-[height] duration-300 ${
        expanded ? "h-[85vh]" : "h-20"
      }`}
    >
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        aria-label={expanded ? "Collapse listings" : "Expand listings"}
        className="flex w-full flex-col items-center pt-2 pb-1"
      >
        <span className="h-1.5 w-12 rounded-full bg-slate-600" />
      </button>
      <div
        onClick={() => setExpanded((e) => !e)}
        className="cursor-pointer px-4 pb-2 text-sm text-slate-200 select-none"
      >
        {peek}
      </div>
      {expanded && (
        <div className="overflow-y-auto px-2 pb-4 h-[calc(100%-72px)]">
          {children}
        </div>
      )}
    </div>
  );
}
