import { ReactNode } from "react";

interface Props {
  filters: ReactNode;
  list: ReactNode;
  main: ReactNode;
  detail?: ReactNode;
}

export function DesktopLayout({ filters, list, main, detail }: Props) {
  return (
    <div className="grid h-full" style={{ gridTemplateColumns: "350px 1fr 400px" }}>
      <aside className="border-r border-slate-800 bg-slate-950 overflow-y-auto">
        <section className="border-b border-slate-800">{filters}</section>
        <section>{list}</section>
      </aside>
      <main className="relative bg-slate-900">{main}</main>
      <aside
        className={`border-l border-slate-800 bg-slate-950 overflow-y-auto transition-transform ${
          detail ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {detail}
      </aside>
    </div>
  );
}
