// Own-data storage. Profile, parcels and the upload queue are kept in localStorage for now:
// the real account (backend contract, parcel parsing) comes in a later iteration.

import type { Geometry } from "../types";

export interface ParcelRecord {
  id: string;
  name: string;
  areaHa: number | null;
  geometry: Geometry | null;
  uploadedAt: string; // ISO timestamp of the local upload action
  format: UploadFormat;
  fileNames: string[];
}

export type UploadFormat = "shp" | "zip" | "gpkg" | "geojson";

interface OwnDataStore {
  parcels: ParcelRecord[];
}

const KEY = "fup.ownData.v1";

function read(): OwnDataStore {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { parcels: [] };
    const parsed = JSON.parse(raw) as Partial<OwnDataStore>;
    return { parcels: Array.isArray(parsed.parcels) ? parsed.parcels : [] };
  } catch {
    return { parcels: [] };
  }
}

function write(store: OwnDataStore): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(store));
  } catch {
    // storage full or blocked: the list still updates in memory for this session
  }
}

export function listParcels(): ParcelRecord[] {
  return read().parcels;
}

export function addParcel(parcel: Omit<ParcelRecord, "id" | "uploadedAt">): ParcelRecord {
  const store = read();
  const record: ParcelRecord = {
    ...parcel,
    id: `p-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    uploadedAt: new Date().toISOString(),
  };
  store.parcels.unshift(record);
  write(store);
  return record;
}

export function removeParcel(id: string): ParcelRecord[] {
  const store = read();
  store.parcels = store.parcels.filter((parcel) => parcel.id !== id);
  write(store);
  return store.parcels;
}

export function totalAreaHa(): number {
  return read().parcels.reduce((sum, parcel) => sum + (parcel.areaHa ?? 0), 0);
}
