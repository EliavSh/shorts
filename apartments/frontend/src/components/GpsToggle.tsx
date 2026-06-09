interface Props {
  active: boolean;
  onToggle: () => void;
  error?: string | null;
}

export function GpsToggle({ active, onToggle, error }: Props) {
  return (
    <button
      onClick={onToggle}
      title={error ?? (active ? "Live GPS on" : "Enable live GPS")}
      className={`min-h-[44px] min-w-[44px] rounded-full px-4 py-2 text-sm font-medium shadow-lg transition-colors ${
        active
          ? "bg-blue-600 text-white"
          : "bg-slate-800 text-slate-200 hover:bg-slate-700"
      }`}
    >
      {active ? "📍 Tracking" : "📍 Locate"}
    </button>
  );
}
