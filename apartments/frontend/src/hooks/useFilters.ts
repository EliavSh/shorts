import { useState, useCallback } from "react";
import type { Filters } from "@/types";

export function useFilters(initial: Filters = {}) {
  const [filters, setFilters] = useState<Filters>(initial);
  const update = useCallback((patch: Partial<Filters>) => {
    setFilters((f) => ({ ...f, ...patch }));
  }, []);
  const reset = useCallback(() => setFilters({}), []);
  return { filters, setFilters, update, reset };
}
