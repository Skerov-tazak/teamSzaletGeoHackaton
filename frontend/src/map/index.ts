// The interactive map of the farm: fields, their crops, risk per threat and the details of a
// selected field. Owner: Kuba. Contract: docs/interfaces.md -> The map module.

import L, { type LayerGroup, type Map as LeafletMap, type TileLayer } from "leaflet";
import type { AppContext, MapHandle } from "../app-context";
import { humaniseError } from "../api/client";
import { loadClock } from "../clock";
import { maxScore, riskColour } from "../risk";
import type { FieldCollection, FieldFeature } from "../types";
import type { LayerState } from "../layer-state";
import { byId } from "../ui/dom";
import { FieldDetailsCard } from "./field-details";
import { createOwnParcelsLayer } from "./own-parcels";

// Basemaps. OSM's public tile server (tile.openstreetmap.org) answers 403 to apps that don't follow
// https://operations.osmfoundation.org/policies/tiles/ — it is not meant for app hosting, so the
// default uses CARTO's OSM-based raster tiles (free for light/demo use, attribution kept on the map).
const BASEMAPS = {
  osm: {
    url: "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    maxZoom: 20,
  },
  topo: {
    url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attribution:
      'Dane: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, SRTM | Styl: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)',
    maxZoom: 17,
  },
  satellite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Kafle &copy; Esri &mdash; Esri, Maxar, Earthstar Geographics",
    maxZoom: 19,
  },
} as const;

const BASE_STYLE: L.PathOptions = {
  color: "#2e7d32",
  weight: 2,
  fillColor: "#66bb6a",
  fillOpacity: 0.15,
};

const POLAND_CENTER: L.LatLngExpression = [52.1, 19.4];

export async function initMap(container: HTMLElement, ctx: AppContext): Promise<MapHandle> {
  const map = L.map(container, { center: POLAND_CENTER, zoom: 7, zoomControl: false });
  L.control.zoom({ position: "bottomright" }).addTo(map);
  L.control.scale({ position: "bottomleft" }).addTo(map);

  const createBasemap = (name: LayerState["basemap"]): TileLayer => {
    const config = BASEMAPS[name];
    return L.tileLayer(config.url, {
      attribution: config.attribution,
      maxZoom: config.maxZoom,
      subdomains: "abc",
      detectRetina: true,
    });
  };

  let layerState: LayerState = { basemap: "osm", fields: true, risks: true, ownParcels: true };
  let basemap = createBasemap(layerState.basemap).addTo(map);
  basemap.bringToBack();

  map.createPane("ownPane").style.zIndex = "410";
  map.createPane("selectedPane").style.zIndex = "450";

  const fieldsLayer: LayerGroup = L.layerGroup().addTo(map);
  const ownLayer: LayerGroup = createOwnParcelsLayer({ pane: "ownPane" }).addTo(map);
  const geoLayers = new Map<number, L.GeoJSON>();

  const statusElement = byId("map-status");
  const selectedBanner = byId("map-selection");
  selectedBanner.hidden = true;

  let selectedFieldId: number | null = null;
  let fields: FieldFeature[] = [];
  let dayScores = new Map<number, number>();

  const showStatus = (message: string | null): void => {
    statusElement.textContent = message ?? "";
    statusElement.hidden = message === null;
  };

  const styleFor = (feature: FieldFeature): L.PathOptions => {
    const score = layerState.risks ? dayScores.get(feature.properties.id) : undefined;
    if (feature.properties.id === selectedFieldId) {
      return {
        ...BASE_STYLE,
        color: "#0d47a1",
        fillColor: riskColour(score ?? null),
        fillOpacity: score === undefined ? 0.25 : 0.5,
        weight: 3,
      };
    }
    if (score === undefined) return BASE_STYLE;
    return { ...BASE_STYLE, color: "#455a64", fillColor: riskColour(score), fillOpacity: 0.55 };
  };

  const applyStyles = (): void => {
    for (const feature of fields) {
      geoLayers.get(feature.properties.id)?.setStyle(styleFor(feature));
    }
  };

  const details = new FieldDetailsCard({
    api: ctx.api,
    container: byId("details-panel"),
    today: ctx.clock.today,
    forecastDays: ctx.clock.forecastDays,
    seasonStart: (date) => `${date.slice(0, 4)}-01-01`,
    onClose: () => selectField(null, false),
    onThreatClick: () => ctx.shell.emit("chat:toggle", { open: true }),
  });

  const selectField = (fieldId: number | null, emit = true): void => {
    const changed = selectedFieldId !== fieldId;
    selectedFieldId = fieldId;
    applyStyles();
    if (fieldId === null) {
      details.hide();
      selectedBanner.hidden = true;
    } else {
      void details.show(fieldId);
      const name = fields.find((feature) => feature.properties.id === fieldId)?.properties.name;
      selectedBanner.textContent = `Wybrana działka: ${name ?? `#${fieldId}`} — asystent zapyta o nią.`;
      selectedBanner.hidden = false;
    }
    if (emit && changed) ctx.events.emit("field:selected", { fieldId });
  };

  const loadRisks = async (): Promise<void> => {
    dayScores = new Map();
    const today = ctx.clock.today;
    if (!today) {
      applyStyles();
      return;
    }
    try {
      const response = await ctx.api.getRisks(today);
      const perField = new Map<number, number[]>();
      for (const risk of response.risks) {
        const scores = perField.get(risk.field_id) ?? [];
        scores.push(risk.score);
        perField.set(risk.field_id, scores);
      }
      for (const [fieldId, scores] of perField) {
        const value = maxScore(scores);
        if (value !== null) dayScores.set(fieldId, value);
      }
      showStatus(null);
    } catch (error) {
      showStatus(`Ryzyko niedostępne: ${humaniseError(error)}`);
    }
    applyStyles();
  };

  const fitToFields = (): void => {
      // LayerGroup has no getBounds(); a feature group of the drawn fields does.
      const bounds = L.featureGroup([...geoLayers.values()]).getBounds();
    if (bounds.isValid()) map.fitBounds(bounds.pad(0.2));
  };

  const loadFields = async (): Promise<void> => {
    fieldsLayer.clearLayers();
    geoLayers.clear();
    try {
      const collection: FieldCollection = await ctx.api.getFields();
      fields = collection.features;
      showStatus(fields.length === 0 ? "Brak działek w odpowiedzi API." : null);
      for (const feature of fields) {
        const layer = L.geoJSON(feature as unknown as GeoJSON.GeoJsonObject, {
          style: () => styleFor(feature),
          onEachFeature: (_geoFeature, geoLayer) => {
            geoLayer.on("click", () => selectField(feature.properties.id));
            geoLayer.bindTooltip(feature.properties.name, { sticky: true });
            const score = dayScores.get(feature.properties.id);
            geoLayer.bindPopup(
              `<strong>${escapeHtml(feature.properties.name)}</strong><br>` +
                `${escapeHtml(feature.properties.crop?.name ?? "brak uprawy")} · ` +
                `${feature.properties.area_ha.toFixed(1)} ha` +
                (score === undefined ? "" : `<br>Ryzyko: <strong>${score.toFixed(2)}</strong>`),
            );
          },
        });
        layer.addTo(fieldsLayer);
        geoLayers.set(feature.properties.id, layer);
      }
      applyStyles();
      fitToFields();
    } catch (error) {
      fields = [];
      showStatus(`Działki niedostępne: ${humaniseError(error)}`);
    }
  };

  const focusField = (fieldId: number): void => {
    const layer = geoLayers.get(fieldId);
    if (layer) map.fitBounds(layer.getBounds().pad(1), { maxZoom: 15 });
    selectField(fieldId);
  };

  // --- Events -------------------------------------------------------------------------------

  ctx.events.on("field:focus", ({ fieldId }) => focusField(fieldId));
  ctx.events.on("date:changed", () => {
    details.setToday(ctx.clock.today);
    void loadRisks().then(() => {
      if (selectedFieldId !== null) void details.show(selectedFieldId);
    });
  });
  ctx.events.on("risks:updated", ({ fieldIds }) => {
    void loadRisks().then(() => {
      if (selectedFieldId !== null && fieldIds.includes(selectedFieldId)) void details.show(selectedFieldId);
    });
  });
  ctx.shell.on("layers:changed", (state) => {
    const risksChanged = state.risks !== layerState.risks;
    if (state.basemap !== layerState.basemap) {
      basemap.remove();
      basemap = createBasemap(state.basemap).addTo(map);
      basemap.bringToBack();
    }
    if (state.fields !== layerState.fields) toggleLayer(map, fieldsLayer, state.fields);
    if (state.ownParcels !== layerState.ownParcels) toggleLayer(map, ownLayer, state.ownParcels);
    layerState = state;
    if (risksChanged) applyStyles();
  });

  map.on("click", () => selectField(null));

  map.on("click", () => selectField(null));

  // The demo's date is the platform's, so re-read it before colouring the map.
  ctx.clock = await loadClock(ctx.api);
  details.setToday(ctx.clock.today);

  await Promise.all([loadFields(), loadRisks()]);

  return {
    async reload() {
      await loadFields();
      await loadRisks();
    },
    focusField(fieldId) {
      focusField(fieldId);
    },
    setClock(clock) {
      ctx.clock = clock;
      details.setToday(clock.today);
      void loadRisks().then(() => {
        if (selectedFieldId !== null) void details.show(selectedFieldId);
      });
    },
    invalidate() {
      map.invalidateSize();
    },
  };
}

function toggleLayer(map: LeafletMap, layer: LayerGroup, visible: boolean): void {
  if (visible && !map.hasLayer(layer)) layer.addTo(map);
  if (!visible && map.hasLayer(layer)) map.removeLayer(layer);
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      default:
        return "&#39;";
    }
  });
}
