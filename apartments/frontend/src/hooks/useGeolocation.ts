import { useEffect, useRef, useState } from "react";
import type { GpsCoords } from "@/types";

interface Options {
  enableHighAccuracy?: boolean;
  debounceMs?: number;
  minDeltaMeters?: number;
}

/**
 * Live geolocation via navigator.geolocation.watchPosition.
 *
 * - `enabled`: start/stop watching declaratively
 * - emits new coords only when distance moved >= minDeltaMeters (default 5m),
 *   debounced by debounceMs (default 500ms) so the map doesn't recenter on
 *   GPS jitter.
 */
export function useGeolocation(enabled: boolean, opts: Options = {}) {
  const { enableHighAccuracy = true, debounceMs = 500, minDeltaMeters = 5 } = opts;
  const [coords, setCoords] = useState<GpsCoords | null>(null);
  const [error, setError] = useState<string | null>(null);
  const watchIdRef = useRef<number | null>(null);
  const lastEmitRef = useRef<{ ts: number; coords: GpsCoords | null }>({ ts: 0, coords: null });
  const pendingRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled || !("geolocation" in navigator)) {
      if (watchIdRef.current != null) {
        navigator.geolocation.clearWatch(watchIdRef.current);
        watchIdRef.current = null;
      }
      return;
    }

    const onSuccess: PositionCallback = (pos) => {
      const next: GpsCoords = {
        lat: pos.coords.latitude,
        lon: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
        timestamp: pos.timestamp,
      };

      // Skip if we haven't moved enough.
      const last = lastEmitRef.current.coords;
      if (last) {
        const dist = haversine(last.lat, last.lon, next.lat, next.lon);
        if (dist < minDeltaMeters) return;
      }

      // Debounce.
      if (pendingRef.current != null) window.clearTimeout(pendingRef.current);
      pendingRef.current = window.setTimeout(() => {
        lastEmitRef.current = { ts: Date.now(), coords: next };
        setCoords(next);
        setError(null);
      }, debounceMs);
    };

    const onError: PositionErrorCallback = (err) => {
      setError(err.message);
    };

    watchIdRef.current = navigator.geolocation.watchPosition(onSuccess, onError, {
      enableHighAccuracy,
      maximumAge: 0,
      timeout: 15_000,
    });

    return () => {
      if (watchIdRef.current != null) {
        navigator.geolocation.clearWatch(watchIdRef.current);
        watchIdRef.current = null;
      }
      if (pendingRef.current != null) window.clearTimeout(pendingRef.current);
    };
  }, [enabled, enableHighAccuracy, debounceMs, minDeltaMeters]);

  return { coords, error, watching: enabled && watchIdRef.current != null };
}

function haversine(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6_371_000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
