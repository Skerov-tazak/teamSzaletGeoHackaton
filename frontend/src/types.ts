// Shapes returned by the platform API (docs/interfaces.md -> Platform API and Chat).
// When the backend generates types with openapi-typescript, these are the shapes to compare against.

export interface Health {
  status: string;
  database: boolean;
}

export interface Clock {
  today: string; // YYYY-MM-DD, the demo's date (never the browser's)
  forecast_days: number;
}

export interface Crop {
  code: number;
  name: string;
}

export interface Threat {
  code: string;
  name: string;
  crop: Crop;
  category: "fungal" | "bacterial" | "viral" | "pest" | string;
}

export type Geometry =
  | { type: "Polygon"; coordinates: number[][][] }
  | { type: "MultiPolygon"; coordinates: number[][][][] };

export interface FieldProperties {
  id: number;
  name: string;
  crop: Crop | null;
  area_ha: number;
}

export interface FieldFeature {
  type: "Feature";
  id: number;
  geometry: Geometry;
  properties: FieldProperties;
}

export interface FieldCollection {
  type: "FeatureCollection";
  features: FieldFeature[];
}

export interface CropYearShare {
  code: number;
  name: string;
  share: number;
}

export interface CropYear {
  year: number;
  classes: CropYearShare[];
}

export interface Soil {
  ph: number | null;
  soil_texture: string | null;
  clay: number | null;
  sand: number | null;
  silt: number | null;
  om: number | null;
  cec: number | null;
  bulk_density: number | null;
}

export interface FieldDetails {
  id: number;
  name: string;
  crop: Crop | null;
  area_ha: number;
  centroid: { lat: number; lon: number };
  weather_grid_id?: string | null;
  crop_history?: CropYear[];
  soil?: Soil | null;
}

export interface RiskRow {
  field_id: number;
  threat_code: string;
  score: number;
}

export interface DayRisks {
  date: string;
  risks: RiskRow[];
}

export interface RiskPoint {
  date: string;
  score: number;
}

export interface FieldThreatSeries {
  threat_code: string;
  points: RiskPoint[];
}

export interface FieldRisksSeries {
  field_id: number;
  from: string;
  to: string;
  threats: FieldThreatSeries[];
}

export interface RiskWithExplanation {
  threat: { code: string; name: string; category: string };
  score: number;
  explanation: Record<string, unknown>;
}

export interface FieldDayRisks {
  field_id: number;
  date: string;
  risks: RiskWithExplanation[];
}

export type Citation =
  | { type: "guide"; document: string; page: number }
  | { type: "risk"; field_id: number; threat_code: string; date: string };

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  citations: Citation[];
  focus_field_id: number | null;
  updated_field_ids: number[];
  created_at: string;
}

export interface ChatReply {
  conversation_id: number;
  message: ChatMessage;
}

export interface ConversationSummary {
  id: number;
  title: string;
  updated_at: string;
}

export interface Conversation {
  id: number;
  title: string;
  messages: ChatMessage[];
}
