// "My parcels" overlay: the polygons uploaded in the Own data section (kept in localStorage
// until the backend accepts uploads).

import L, { type LayerGroup, type PathOptions } from "leaflet";
import { listParcels } from "../own-data/store";

const STYLE: PathOptions = { color: "#6a1b9a", weight: 3, dashArray: "6 4", fillOpacity: 0.12, fillColor: "#8e24aa" };

export function createOwnParcelsLayer(options: { pane?: string } = {}): LayerGroup {
  const group: LayerGroup = L.layerGroup();
  for (const parcel of listParcels()) {
    if (!parcel.geometry) continue;
    const layer = L.geoJSON(
      { type: "Feature", properties: { name: parcel.name }, geometry: parcel.geometry } as unknown as GeoJSON.GeoJsonObject,
      { style: STYLE, pane: options.pane },
    );
    layer.bindTooltip(`${parcel.name} (moja działka)`, { sticky: true });
    layer.addTo(group);
  }
  return group;
}
