// Points of interest + yad2 lookup tables used by map filters.
// (Lives in services/, NOT a data/ dir — shorts' .dockerignore strips
// apartments/**/data/ from the Docker build.)

/** סבידור תחנת מוניות — the taxi/sherut stand at Tel Aviv Savidor Center.
 *  Centroid of the station's GTFS platform stops (A/B/C + הורדה forecourt),
 *  pinned from the MOT GTFS via the Hasadna stride API. */
export const SAVIDOR = { lat: 32.083, lon: 34.7962 };

/** Radius for the "near Savidor" proximity filter. */
export const SAVIDOR_RADIUS_M = 2000;

/** yad2 propertyCondition.id → מצב הנכס, verified empirically against item
 *  pages (2026-07): 1=חדש מקבלן (לא גרו בנכס), 2=משופץ, 3=במצב שמור,
 *  6=חדש (גרו בנכס). 4/5 not observed (likely דרוש שיפוץ tiers). */
export const CONDITION_LABEL: Record<number, string> = {
  1: "חדש מקבלן (לא גרו בנכס)",
  2: "משופץ",
  3: "במצב שמור",
  4: "דרוש שיפוץ",
  5: "דרוש שיפוץ",
  6: "חדש (גרו בנכס)",
};

/** "Renovated" preset = משופץ + the new/like-new tiers (user's definition). */
export const RENOVATED_CONDITION_IDS = [1, 2, 6];
