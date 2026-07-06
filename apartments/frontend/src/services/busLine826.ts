// Bus line 826 (אגד/Egged) — Tel Aviv Central → Yokneam Illit segment.
// Stops 1–25 of the full Tel Aviv ↔ Nof HaGalil route, sourced from the
// Israel MOT GTFS via the Hasadna open-bus stride API. Static snapshot.
export interface BusStop { seq: number; name: string; city: string; lat: number; lon: number; }

export const BUS_826_TLV_YOKNEAM: BusStop[] = [
  { seq: 1, name: "ת.מרכזית תל אביב קומה 7/רציפים", city: "תל אביב יפו", lat: 32.054886, lon: 34.780031 },
  { seq: 2, name: "קניון עזריאלי/דרך מנחם בגין", city: "תל אביב יפו", lat: 32.074453, lon: 34.791094 },
  { seq: 3, name: "ת. רכבת תל אביב - סבידור/דרך נמיר", city: "תל אביב יפו", lat: 32.083482, lon: 34.795008 },
  { seq: 4, name: "סמינר הקיבוצים/דרך נמיר", city: "תל אביב יפו", lat: 32.103962, lon: 34.792661 },
  { seq: 5, name: "דרך נמיר/אינשטיין", city: "תל אביב יפו", lat: 32.113247, lon: 34.792778 },
  { seq: 6, name: "מכללת לוינסקי/דרך נמיר", city: "תל אביב יפו", lat: 32.136871, lon: 34.798587 },
  { seq: 7, name: "מחלף גלילות מערב", city: "רמת השרון", lat: 32.14144, lon: 34.801762 },
  { seq: 8, name: "סינמה סיטי/כביש 2", city: "רמת השרון", lat: 32.148067, lon: 34.803856 },
  { seq: 9, name: "צומת הרצליה", city: "הרצליה", lat: 32.165855, lon: 34.813911 },
  { seq: 10, name: "מחלף נוף ים", city: "כפר שמריהו", lat: 32.187878, lon: 34.816094 },
  { seq: 11, name: "מכון וינגייט", city: "יקום", lat: 32.253013, lon: 34.836028 },
  { seq: 12, name: "מכון וינגייט/כביש 2 לצפון", city: "נתניה", lat: 32.262298, lon: 34.83878 },
  { seq: 13, name: "מחלף נתניה", city: "נתניה", lat: 32.324197, lon: 34.867696 },
  { seq: 14, name: "פנימיית הדסה נעורים", city: "בית ינאי", lat: 32.38219, lon: 34.865862 },
  { seq: 15, name: "מחלף ינאי לצפון", city: "עמק חפר", lat: 32.386814, lon: 34.868269 },
  { seq: 16, name: "צומת אולגה", city: "חדרה", lat: 32.438234, lon: 34.89157 },
  { seq: 17, name: "מחלף אור עקיבא", city: "אור עקיבא", lat: 32.506687, lon: 34.91377 },
  { seq: 18, name: "צומת פוריידיס", city: "פוריידיס", lat: 32.591896, lon: 34.947792 },
  { seq: 19, name: "צומת שפיה", city: "זכרון יעקב", lat: 32.582538, lon: 34.968475 },
  { seq: 20, name: "צומת בת שלמה", city: "בת שלמה", lat: 32.598208, lon: 35.005515 },
  { seq: 21, name: "מחלף אליקים", city: "מגידו", lat: 32.637507, lon: 35.066015 },
  { seq: 22, name: "התמר / הפעמונית", city: "יקנעם עילית", lat: 32.658906, lon: 35.106831 },
  { seq: 23, name: "צומת יקנעם עילית", city: "יקנעם עילית", lat: 32.661858, lon: 35.105401 },
  { seq: 24, name: "צומת יקנעם המושבה", city: "יקנעם עילית", lat: 32.667848, lon: 35.108626 },
  { seq: 25, name: "צומת התשבי", city: "יקנעם עילית", lat: 32.673179, lon: 35.10957 },
];
