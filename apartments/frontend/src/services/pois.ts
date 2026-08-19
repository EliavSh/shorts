// Points of interest + yad2 lookup tables used by map filters.
// (Lives in services/, NOT a data/ dir — shorts' .dockerignore strips
// apartments/**/data/ from the Docker build.)

export interface Stop { name: string; lat: number; lon: number; }

/** Line 836 (Egged, Tel Aviv ↔ Tiberias) — its Tel Aviv + Herzliya stops only,
 *  i.e. the דרך נמיר corridor from TLV Central up to צומת הרצליה. Pinned from the
 *  MOT GTFS via the Hasadna stride API. This is the app's default focus. */
export const LINE_836_STOPS: Stop[] = [
  { name: "ת.מרכזית תל אביב", lat: 32.054886, lon: 34.780031 },
  { name: "קניון עזריאלי", lat: 32.074453, lon: 34.791094 },
  { name: "סבידור/דרך נמיר", lat: 32.083482, lon: 34.795008 },
  { name: "סמינר הקיבוצים/דרך נמיר", lat: 32.103962, lon: 34.792661 },
  { name: "דרך נמיר/אינשטיין", lat: 32.113247, lon: 34.792778 },
  { name: "מכללת לוינסקי/דרך נמיר", lat: 32.136871, lon: 34.798587 },
  { name: "צומת הרצליה", lat: 32.165855, lon: 34.813911 },
];

/** A listing counts as "on the 836 corridor" if within this many metres of any
 *  of the stops above. */
export const LINE_836_RADIUS_M = 1500;

/** Default map center — roughly mid-corridor (north TLV) so TLV→Herzliya is in frame. */
export const CORRIDOR_CENTER = { lat: 32.105, lon: 34.795 };

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
