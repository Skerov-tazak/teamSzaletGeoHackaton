// The map of the farm (owner: Kuba; contract: frontend/src/map/README.md). Fields from the API,
// coloured by their highest risk level on the demo's date, and a panel for the selected field.
//   sends   field:selected (click on a field; null for empty map)
//   handles field:focus, date:changed, risks:updated

import type { FeatureCollection } from "geojson";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { errorMessage } from "../api/client";
import type { FieldFeature, RiskLevel } from "../api/types";
import type { AppContext } from "../context";
import { h } from "../dom";
import { highestLevel, LEVEL_COLOURS, LEVEL_LABELS, LEVELS, NO_DATA_COLOUR } from "../risk";
import { FieldPanel } from "./panel";

// Base maps. OpenStreetMap's own tiles (light demo use, attribution kept) and Esri's imagery, where the
// fields themselves are visible. (CARTO's tiles now need an API key.)
const BASE_MAPS = {
  Mapa: L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }),
  Satelita: L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: "Zdjęcia &copy; Esri, Maxar, Earthstar Geographics" },
  ),
};
const POLAND: L.LatLngExpression = [52.1, 19.4];

export function initMap(container: HTMLElement, ctx: AppContext): void {
  const canvas = h("div", { class: "map-canvas" });
  const status = h("div", { class: "map-status", role: "status", hidden: true });
  const panelElement = h("aside", { class: "field-panel", "aria-label": "Szczegóły pola" });
  container.replaceChildren(canvas, status, panelElement);

  const map = L.map(canvas, { center: POLAND, zoom: 6, zoomControl: false });
  L.control.zoom({ position: "topleft", zoomInTitle: "Przybliż", zoomOutTitle: "Oddal" }).addTo(map);
  L.control.scale({ position: "bottomright", imperial: false }).addTo(map);
  BASE_MAPS.Mapa.addTo(map);
  L.control.layers(BASE_MAPS, undefined, { position: "topleft" }).addTo(map);
  map.attributionControl.setPrefix(false);
  new ResizeObserver(() => map.invalidateSize()).observe(container);

  const legend = new L.Control({ position: "bottomleft" });
  legend.onAdd = () =>
    h(
      "div",
      { class: "map-legend" },
      h("strong", {}, "Ryzyko"),
      ...[...LEVELS].reverse().map((level) => h("div", {}, h("span", { class: "swatch", style: `background:${LEVEL_COLOURS[level]}` }), LEVEL_LABELS[level])),
      h("div", {}, h("span", { class: "swatch", style: `background:${NO_DATA_COLOUR}` }), "brak danych"),
    );
  legend.addTo(map);

  // --- state
  const layers = new Map<number, L.Path>();
  let fields: FieldFeature[] = [];
  let levels = new Map<number, RiskLevel>();
  let selectedId: number | null = null;
  let pendingFocus: number | null = null;
  let risksToken = 0;
  const threatNames = new Map<string, string>();
  void ctx.api.getThreats().then(
    (threats) => threats.forEach((threat) => threatNames.set(threat.code, threat.name)),
    () => undefined, // names are a nicety: codes are shown instead
  );

  const panel = new FieldPanel(panelElement, ctx, () => select(null, true), (code) => threatNames.get(code) ?? code);

  const showStatus = (text: string | null, retry?: () => void) => {
    status.hidden = text === null;
    status.replaceChildren();
    if (text === null) return;
    status.append(text);
    if (retry) {
      const button = h("button", { type: "button" }, "Spróbuj ponownie");
      button.addEventListener("click", retry);
      status.append(" ", button);
    }
  };

  const styleFor = (fieldId: number): L.PathOptions => {
    const level = levels.get(fieldId);
    const fill = level ? LEVEL_COLOURS[level] : NO_DATA_COLOUR;
    return fieldId === selectedId
      ? { color: "#0d47a1", weight: 4, fillColor: fill, fillOpacity: 0.6 }
      : { color: "#263238", weight: 1.5, fillColor: fill, fillOpacity: 0.45 };
  };

  const restyle = () => {
    for (const [fieldId, layer] of layers) layer.setStyle(styleFor(fieldId));
    if (selectedId !== null) layers.get(selectedId)?.bringToFront();
  };

  function select(fieldId: number | null, emit: boolean): void {
    const changed = fieldId !== selectedId;
    selectedId = fieldId;
    restyle();
    if (fieldId === null) panel.hide();
    else if (changed || panel.openFieldId === null) panel.show(fieldId);
    if (emit) ctx.events.emit("field:selected", { fieldId });
  }

  const focus = (fieldId: number) => {
    const layer = layers.get(fieldId);
    if (!layer) {
      pendingFocus = fieldId; // fields not loaded yet: focus once they are
      return;
    }
    const bounds = (layer as unknown as L.Polygon).getBounds();
    map.fitBounds(bounds, { maxZoom: 16, padding: [40, 40] });
    select(fieldId, true);
  };

  // --- data
  const loadRisks = async () => {
    const token = ++risksToken;
    try {
      const day = await ctx.api.getRisks(ctx.clock.today);
      if (token !== risksToken) return; // a newer date was asked for meanwhile
      const perField = new Map<number, RiskLevel[]>();
      for (const risk of day.risks) perField.set(risk.field_id, [...(perField.get(risk.field_id) ?? []), risk.level]);
      levels = new Map();
      for (const [fieldId, fieldLevels] of perField) {
        const level = highestLevel(fieldLevels);
        if (level) levels.set(fieldId, level);
      }
      restyle();
      if (fields.length) showStatus(null);
    } catch (error) {
      if (token !== risksToken) return;
      showStatus(`Nie udało się wczytać ryzyk: ${errorMessage(error)}`, () => void loadRisks());
    }
  };

  const loadFields = async () => {
    showStatus("Wczytywanie pól…");
    try {
      const collection = await ctx.api.getFields();
      fields = collection.features;
      layers.clear();
      const geo = L.geoJSON(collection as unknown as FeatureCollection, {
        style: (feature) => styleFor(Number(feature?.id)),
        onEachFeature: (feature, layer) => {
          const fieldId = Number(feature.id);
          const name = (feature.properties as { name?: string } | null)?.name ?? `Pole #${fieldId}`;
          layers.set(fieldId, layer as L.Path);
          layer.bindTooltip(name, { sticky: true, direction: "top" });
          layer.on("click", (event: L.LeafletMouseEvent) => {
            L.DomEvent.stopPropagation(event);
            select(fieldId, true);
          });
        },
      }).addTo(map);
      if (!fields.length) {
        showStatus("Brak pól w bazie. Uruchom seed, np. python manage.py assistant_dev_seed.");
        return;
      }
      showStatus(null);
      map.fitBounds(geo.getBounds(), { padding: [30, 30], maxZoom: 15 });
      restyle();
      if (pendingFocus !== null) {
        const fieldId = pendingFocus;
        pendingFocus = null;
        focus(fieldId);
      }
    } catch (error) {
      showStatus(`Nie udało się wczytać pól: ${errorMessage(error)}`, () => void loadFields());
    }
  };

  // --- events
  map.on("click", () => {
    if (selectedId !== null) select(null, true);
  });
  ctx.events.on("field:focus", ({ fieldId }) => focus(fieldId));
  ctx.events.on("date:changed", () => {
    void loadRisks(); // ctx.clock.today is already the new date
    panel.reload();
  });
  ctx.events.on("risks:updated", ({ fieldIds }) => {
    // /api/risks/ answers for the whole farm in one small request; only the open panel needs more
    void loadRisks();
    if (panel.openFieldId !== null && fieldIds.includes(panel.openFieldId)) panel.reload();
  });

  void loadFields();
  void loadRisks();
}
