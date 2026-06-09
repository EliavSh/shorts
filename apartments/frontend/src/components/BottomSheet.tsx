import { Drawer } from "vaul";
import { ReactNode, useState } from "react";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  children: ReactNode;
}

const SNAP_POINTS = [0.45, 0.95];

export function BottomSheet({ open, onOpenChange, title, children }: Props) {
  const [snap, setSnap] = useState<number | string | null>(SNAP_POINTS[0]);
  return (
    <Drawer.Root
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (o) setSnap(SNAP_POINTS[0]);
      }}
      snapPoints={SNAP_POINTS}
      activeSnapPoint={snap}
      setActiveSnapPoint={setSnap}
    >
      <Drawer.Portal>
        <Drawer.Overlay className="fixed inset-0 bg-black/50 z-[1000]" />
        <Drawer.Content className="fixed bottom-0 left-0 right-0 z-[1010] rounded-t-2xl bg-slate-900 flex flex-col pb-safe">
          <div className="mx-auto mt-2 h-1.5 w-12 rounded-full bg-slate-700" />
          {title && (
            <Drawer.Title className="px-4 pt-3 pb-1 text-lg font-semibold text-slate-100">
              {title}
            </Drawer.Title>
          )}
          <div className="overflow-y-auto px-2 pb-4">{children}</div>
        </Drawer.Content>
      </Drawer.Portal>
    </Drawer.Root>
  );
}
