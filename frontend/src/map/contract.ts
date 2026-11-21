// What the map needs from the rest of the page, written from docs/interfaces.md and
// docs/database.md ("Explanation, version 1"). These types are temporary: once api/ has the types
// generated from /api/schema/ (openapi-typescript), import them from there instead; the shapes are the same.

import type { Geometry } from "geojson";

import type { EventBus } from "../events";

// --- Platform API responses (interfaces.md → Platform API) ----------------------------------------

export interface CropRef {
  code: number;
  name: string;
}

/** GET /api/clock/ */
export interface Clock {
  today: string;
  forecast_days: number;
}

/** GET /api/threats/ (one entry) */
export interface Threat {
  code: string;
  name: string;
  crop: CropRef;
  category: string;
}

/** GET /api/fields/ (one feature): coordinates [lon, lat], EPSG:4326 */
export interface FieldFeature {
  type: "Feature";
  id: number;
  geometry: Geometry;
  properties: { id: number; name: string; crop: CropRef | null; area_ha: number };
}

export interface FieldCollection {
  type: "FeatureCollection";
  features: FieldFeature[];
}

/** GET /api/fields/{id}/ */
export interface FieldDetail {
  id: number;
  name: string;
  crop: CropRef | null;
  area_ha: number;
  centroid: { lat: number; lon: number };
  weather_grid_id: string;
  crop_history: { year: number; classes: (CropRef & { share: number })[] }[];
  soil: Record<string, number | string | null> | null;
}

/** GET /api/risks/?date= */
export interface DayRisks {
  date: string;
  risks: { field_id: number; threat_code: string; score: number; level?: Level }[];
}

/** GET /api/fields/{id}/risks/?from=&to= */
export interface FieldRiskSeries {
  field_id: number;
  from: string;
  to: string;
  threats: { threat_code: string; points: { date: string; score: number }[] }[];
}

/** GET /api/fields/{id}/risks/{date}/ */
export interface FieldDayRisks {
  field_id: number;
  date: string;
  risks: { threat: { code: string; name: string; category: string }; score: number; explanation: Explanation }[];
}

// --- Explanation, version 1 (database.md). Readers ignore keys they don't know. --------------------

export type Level = "low" | "medium" | "high";

export interface Driver {
  factor: string;
  label: string;
  value?: number | string | null;
  unit?: string | null;
  threshold?: string | null;
  multiplier?: number | null;
  effect: number | null;
  kind?: string;
  observed_on?: string;
  text?: string;
}

export interface SprayWindow {
  date: string;
  quality: "optimal" | "acceptable" | string;
  conditions?: unknown;
  rule?: string;
  note?: string;
}

export interface Explanation {
  version: number;
  summary: string;
  level: Level;
  score: number;
  threat?: { code: string; name_pl?: string; name_en?: string; category?: string };
  as_of?: string;
  crop?: { code: number; source: string };
  growth_stage?: { bbch: number; name: string; method?: string; sowing_assumed?: string | null; confidence?: number };
  drivers?: Driver[];
  action?: { type: "wait" | "monitor" | "treat" | string; text: string; threshold?: string | null; spray_window?: SprayWindow | null };
  severity?: number;
  expected_loss?: number;
  confidence?: number;
  confidence_observed?: number;
  forecast_lead_days?: number;
  notes?: string[];
}

// --- The context every module gets (interfaces.md → Frontend modules) ------------------------------

/** The calls of `ctx.api` the map uses: one per agreed endpoint. */
export interface MapApi {
  getThreats(): Promise<Threat[]>;
  getFields(): Promise<FieldCollection>;
  getField(id: number): Promise<FieldDetail>;
  getRisks(date?: string): Promise<DayRisks>;
  getFieldRisks(id: number, range?: { from?: string; to?: string }): Promise<FieldRiskSeries>;
  getFieldDayRisks(id: number, date: string): Promise<FieldDayRisks>;
}

export interface AppContext {
  api: MapApi;                                      // typed calls to the platform API
  events: EventBus;
  clock: { today: string; forecastDays: number };   // updated by main.ts on "date:changed"
}
