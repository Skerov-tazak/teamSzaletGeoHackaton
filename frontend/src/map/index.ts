// The map module (docs/interfaces.md → The map module, frontend/src/map/README.md).
//
//   initMap(container, ctx): void   called once by main.ts
//
// Draws inside `container` only, reads data only through ctx.api, talks to the rest of the page only
// through ctx.events, and never reads the browser's date: the demo's date is ctx.clock.today.
//
//   sends    field:selected { fieldId }   a click on a field; { fieldId: null } on empty map or closing the panel
//   handles  field:focus { fieldId }      zoom to + highlight the field, open its panel, then send field:selected
//            date:changed { today }       reload colours and the open panel (ctx.clock is already updated)
//            risks:updated { fieldIds }   reload those fields (colours, and the panel if it shows one of them)

import L from "leaflet";
import "leaflet/dist/leaflet.css";

import type { AppContext, DayRisks, FieldCollection, FieldDayRisks, FieldDetail, FieldFeature, FieldRiskSeries, Level, Threat } from "./contract";
import {
  CATEGORY_LABEL, LEVEL_LABEL, addDays, cropName, daysBetween, esc, ha, levelOf, longDate, shortDate, weekday,
} from "./format";
import { levelPill, renderPanel, type PanelState } from "./panel";
import "./map.css";

type FieldLevel = { level: Level | null; score: number; top: string | null };

/** Status colours (fixed, never themed); the level always comes with its label too. */
const FILL: Record<Level | "none", string> = { high: "#d03b3b", medium: "#fab219", low: "#0ca30c", none: "#8a8f87" };

const BASEMAPS = {
  satellite: {
    label: "Satelita",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Zdjęcia © Esri, Maxar, Earthstar Geographics",
  },
  map: {
    label: "Mapa",
    url: "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
    attribution: "© OpenStreetMap, © CARTO",
  },
} as const;

export function initMap(container: HTMLElement, ctx: AppContext): void {
  const { api, events, clock } = ctx;

  // --- DOM -------------------------------------------------------------------------------------
  container.classList.add("fup-map");
  container.innerHTML = `
    <div class="fup-canvas"></div>
    <aside class="fup-card fup-side" aria-label="Pola gospodarstwa">
      <div class="side-head">
        <div class="side-title">Twoje pola</div>
        <div class="side-date"></div>
      </div>
      <div class="side-counts"></div>
      <div class="side-filter" role="group" aria-label="Koloruj według"></div>
      <ol class="side-list"></ol>
      <div class="fup-legend-box" aria-label="Legenda"></div>
    </aside>
    <div class="fup-card fup-days" role="group" aria-label="Dzień na mapie"></div>
    <div class="fup-card fup-base" role="group" aria-label="Podkład mapy"></div>
    <aside class="fup-card fup-panel" aria-label="Szczegóły pola" hidden></aside>
    <div class="fup-toast" role="status" hidden></div>`;
  const $ = <T extends HTMLElement>(sel: string) => container.querySelector<T>(sel)!;
  const canvas = $<HTMLDivElement>(".fup-canvas");
  const side = { date: $(".side-date"), counts: $(".side-counts"), filter: $(".side-filter"), list: $(".side-list") };
  const daysBox = $(".fup-days");
  const panel = $<HTMLElement>(".fup-panel");
  const toast = $(".fup-toast");

  // --- state -----------------------------------------------------------------------------------
  let fields: FieldFeature[] = [];
  const threats = new Map<string, Threat>();
  const threatNames = new Map<string, string>();
  let viewDate = clock.today;                    // today or one of the coming days
  let dayRisks: DayRisks | null = null;
  let category = "all";
  let selected: number | null = null;
  let basemap: keyof typeof BASEMAPS = "satellite";
  const layers = new Map<number, L.GeoJSON>();
  const labels = new Map<number, L.Tooltip>();
  const detailCache = new Map<number, FieldDetail>();
  const seriesCache = new Map<number, FieldRiskSeries>();
  const panelState: PanelState = { open: new Set(), range: "recent" };
  let panelToken = 0;

  // --- Leaflet ---------------------------------------------------------------------------------
  const map = L.map(canvas, { zoomControl: false, attributionControl: true, minZoom: 6, maxZoom: 18 }).setView([50.36, 17.68], 13);
  L.control.zoom({ position: "topright" }).addTo(map);
  map.attributionControl.setPrefix(false);
  let tiles = L.tileLayer(BASEMAPS[basemap].url, { attribution: BASEMAPS[basemap].attribution, maxZoom: 19 }).addTo(map);
  map.on("click", () => select(null, { emit: true }));
  new ResizeObserver(() => map.invalidateSize()).observe(container);

  function showError(msg: string): void {
    toast.textContent = msg;
    toast.hidden = false;
    window.clearTimeout((toast as unknown as { _t?: number })._t);
    (toast as unknown as { _t?: number })._t = window.setTimeout(() => (toast.hidden = true), 6000);
  }
  const fail = (what: string) => (e: unknown) => {
    const detail = (e as { detail?: string })?.detail ?? (e as Error)?.message ?? String(e);
    showError(`${what}: ${detail}`);
  };

  // --- colours ---------------------------------------------------------------------------------
  function fieldLevel(fieldId: number): FieldLevel {
    let best: FieldLevel = { level: null, score: -1, top: null };
    for (const r of dayRisks?.risks ?? []) {
      if (r.field_id !== fieldId) continue;
      if (category !== "all" && threats.get(r.threat_code)?.category !== category) continue;
      const level = r.level ?? levelOf(r.score);   // the endpoint carries only the score (interfaces.md)
      if (best.level === null || r.score > best.score) best = { level, score: r.score, top: r.threat_code };
    }
    return best;
  }

  function styleFor(id: number): L.PathOptions {
    const { level } = fieldLevel(id);
    const isSel = id === selected;
    return {
      className: `fup-field ${level ? `lvl-${level}` : "lvl-none"}${isSel ? " is-selected" : ""}`,
      color: isSel ? "#ffffff" : "rgba(255,255,255,0.85)",
      weight: isSel ? 3.5 : 1.5,
      fillColor: FILL[level ?? "none"],
      fillOpacity: isSel ? 0.62 : 0.48,
    };
  }

  function recolour(ids?: number[]): void {
    for (const [id, layer] of layers) {
      if (ids && !ids.includes(id)) continue;
      layer.setStyle(styleFor(id));
      // className on an existing path is not updated by setStyle: set it on the element
      layer.eachLayer((l) => {
        const el = (l as L.Path & { _path?: SVGElement })._path;
        if (el) el.setAttribute("class", `leaflet-interactive ${styleFor(id).className}`);
      });
    }
    renderSide();
  }

  // --- side card ---------------------------------------------------------------------------------
  function renderSide(): void {
    const lead = daysBetween(clock.today, viewDate);
    side.date.innerHTML = lead > 0
      ? `Prognoza na <b>${weekday(viewDate)} ${shortDate(viewDate)}</b> · +${lead} ${lead === 1 ? "dzień" : "dni"}`
      : `Stan na <b>${longDate(viewDate)}</b>`;
    const rows = fields.map((f) => ({ f, lv: fieldLevel(f.id) }))
      .sort((a, b) => (b.lv.score - a.lv.score) || a.f.properties.name.localeCompare(b.f.properties.name, "pl"));
    const counts: Record<Level, number> = { high: 0, medium: 0, low: 0 };
    rows.forEach((r) => r.lv.level && counts[r.lv.level]++);
    side.counts.innerHTML = (["high", "medium", "low"] as Level[])
      .map((l) => `<div class="count lvl-${l}"><span class="count-n">${counts[l]}</span><span class="count-k">${LEVEL_LABEL[l]}</span></div>`).join("");
    side.list.innerHTML = rows.map(({ f, lv }) => {
      const top = lv.top ? threatNames.get(lv.top) ?? lv.top : "brak zagrożeń w tej kategorii";
      return `<li><button class="field-row${f.id === selected ? " on" : ""}" data-id="${f.id}">` +
        `<span class="fr-dot ${lv.level ? `lvl-${lv.level}` : "lvl-none"}"></span>` +
        `<span class="fr-main"><span class="fr-name">${esc(f.properties.name)}</span>` +
        `<span class="fr-sub">${esc(cropName(f.properties.crop))} · ${ha(f.properties.area_ha)}</span>` +
        `<span class="fr-top">${esc(top)}</span></span>` +
        (lv.level ? levelPill(lv.level, "sm") : '<span class="fup-pill lvl-none sm">—</span>') + "</button></li>";
    }).join("");
  }

  function renderFilter(): void {
    const cats = [...new Set([...threats.values()].map((t) => t.category))].sort();
    side.filter.innerHTML = ["all", ...cats].map((c) =>
      `<button data-cat="${esc(c)}" class="${c === category ? "on" : ""}">${c === "all" ? "wszystkie" : esc(CATEGORY_LABEL[c] ?? c)}</button>`).join("");
  }

  side.filter.addEventListener("click", (ev) => {
    const b = (ev.target as HTMLElement).closest<HTMLButtonElement>("button[data-cat]");
    if (!b) return;
    category = b.dataset.cat!;
    renderFilter();
    recolour();
  });
  side.list.addEventListener("click", (ev) => {
    const b = (ev.target as HTMLElement).closest<HTMLButtonElement>("button[data-id]");
    if (b) focusField(Number(b.dataset.id));
  });

  // --- day strip: today + the coming days ----------------------------------------------------------
  function renderDays(): void {
    const n = clock.forecastDays;
    const items = Array.from({ length: n + 1 }, (_, k) => addDays(clock.today, k));
    daysBox.innerHTML = '<span class="days-k">Dzień</span>' + items.map((d, k) =>
      `<button data-day="${d}" class="${d === viewDate ? "on" : ""}${k ? "" : " today"}">` +
      `<span class="d-w">${k ? weekday(d) : "dziś"}</span><span class="d-n">${shortDate(d)}</span></button>`).join("");
  }
  daysBox.addEventListener("click", (ev) => {
    const b = (ev.target as HTMLElement).closest<HTMLButtonElement>("button[data-day]");
    if (!b || b.dataset.day === viewDate) return;
    viewDate = b.dataset.day!;
    renderDays();
    void loadDay();
  });

  // --- legend + basemap --------------------------------------------------------------------------
  $(".fup-legend-box").innerHTML = '<div class="lg-title">Kolor pola = najwyższe ryzyko na nim</div><div class="lg-items">' +
    (["high", "medium", "low"] as Level[]).map((l) => `<span class="lg-row"><span class="lg-sw lvl-${l}"></span>${LEVEL_LABEL[l]}</span>`).join("") +
    '<span class="lg-row"><span class="lg-sw lvl-none"></span>brak oceny</span></div>';
  const baseBox = $(".fup-base");
  function renderBase(): void {
    baseBox.innerHTML = (Object.keys(BASEMAPS) as (keyof typeof BASEMAPS)[]).map((k) =>
      `<button data-base="${k}" class="${k === basemap ? "on" : ""}">${BASEMAPS[k].label}</button>`).join("");
  }
  baseBox.addEventListener("click", (ev) => {
    const b = (ev.target as HTMLElement).closest<HTMLButtonElement>("button[data-base]");
    if (!b || b.dataset.base === basemap) return;
    basemap = b.dataset.base as keyof typeof BASEMAPS;
    map.removeLayer(tiles);
    tiles = L.tileLayer(BASEMAPS[basemap].url, { attribution: BASEMAPS[basemap].attribution, maxZoom: 19 }).addTo(map);
    container.dataset.base = basemap;
    renderBase();
  });
  renderBase();
  container.dataset.base = basemap;
  for (const el of [".fup-side", ".fup-days", ".fup-base", ".fup-panel"]) {
    L.DomEvent.disableClickPropagation($(el));
    L.DomEvent.disableScrollPropagation($(el));
  }

  // --- fields ------------------------------------------------------------------------------------
  function drawFields(fc: FieldCollection): void {
    fields = fc.features;
    for (const f of fields) {
      const layer = L.geoJSON(f as GeoJSON.Feature, { style: () => styleFor(f.id), bubblingMouseEvents: false } as L.GeoJSONOptions);
      layer.on("click", () => focusField(f.id, { zoom: false }));
      layer.on("mouseover", () => container.querySelector(`.field-row[data-id="${f.id}"]`)?.classList.add("hover"));
      layer.on("mouseout", () => container.querySelector(`.field-row[data-id="${f.id}"]`)?.classList.remove("hover"));
      const tip = L.tooltip({ permanent: true, direction: "center", className: "fup-label", opacity: 1 }).setContent(esc(f.properties.name));
      layer.bindTooltip(tip);
      layer.addTo(map);
      layers.set(f.id, layer);
      labels.set(f.id, tip);
    }
    const all = L.featureGroup([...layers.values()]);
    if (fields.length) {
      const narrow = container.clientWidth <= 860;
      const sideH = $(".fup-side").offsetHeight;
      map.fitBounds(all.getBounds(), narrow
        ? { paddingTopLeft: [20, sideH + 30], paddingBottomRight: [20, 80] }
        : { paddingTopLeft: [340, 40], paddingBottomRight: [60, 90] });
    }
    const toggleLabels = () => container.classList.toggle("labels-off", map.getZoom() < 13);
    map.on("zoomend", toggleLabels);
    toggleLabels();
  }

  async function loadDay(): Promise<void> {
    container.classList.add("is-loading");
    try {
      dayRisks = await api.getRisks(viewDate);
      recolour();
      if (selected != null) void loadPanel(selected);
    } catch (e) {
      fail("Nie udało się wczytać ryzyk")(e);
    } finally {
      container.classList.remove("is-loading");
    }
  }

  // --- selection + panel ---------------------------------------------------------------------------
  function select(id: number | null, opts: { emit: boolean }): void {
    if (id === selected && id !== null) return;
    const prev = selected;
    selected = id;
    panelState.open.clear();
    recolour([prev, id].filter((x): x is number => x != null));
    if (id == null) {
      panel.hidden = true;
      container.classList.remove("has-panel");
    } else {
      layers.get(id)?.bringToFront();
      void loadPanel(id);
    }
    if (opts.emit) events.emit("field:selected", { fieldId: id });
  }

  /** Zoom so the field sits in the part of the map the cards and the panel leave free. */
  function flyTo(id: number): void {
    const layer = layers.get(id);
    if (!layer) return;
    const narrow = container.clientWidth <= 860;
    const pad = narrow
      ? { paddingTopLeft: [24, 24] as L.PointTuple, paddingBottomRight: [24, Math.round(container.clientHeight * 0.62) + 24] as L.PointTuple }
      : { paddingTopLeft: [340, 60] as L.PointTuple, paddingBottomRight: [440, 100] as L.PointTuple };
    map.flyToBounds(layer.getBounds(), { ...pad, maxZoom: 15, duration: 0.6 });
  }

  function focusField(id: number, opts: { zoom?: boolean } = {}): void {
    if (!layers.has(id)) return;
    if (opts.zoom !== false) flyTo(id);
    if (selected !== id) select(id, { emit: true });
  }

  async function loadPanel(id: number): Promise<void> {
    const token = ++panelToken;
    panel.hidden = false;
    container.classList.add("has-panel");
    if (!panel.innerHTML || panel.dataset.field !== String(id)) {
      panel.innerHTML = '<div class="p-loading"><div class="skeleton h"></div><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton tall"></div></div>';
    }
    panel.dataset.field = String(id);
    try {
      const detailP = detailCache.get(id) ? Promise.resolve(detailCache.get(id)!) : api.getField(id);
      const dayP: Promise<FieldDayRisks> = api.getFieldDayRisks(id, viewDate);
      const [detail, day] = await Promise.all([detailP, dayP]);
      if (token !== panelToken) return;
      detailCache.set(id, detail);
      const draw = (series: FieldRiskSeries | null) =>
        renderPanel(panel, { detail, day, series, today: clock.today, viewDate }, panelState, threatNames);
      draw(seriesCache.get(id) ?? null);
      if (!seriesCache.get(id)) {
        const series = await api.getFieldRisks(id, { to: addDays(clock.today, clock.forecastDays) });
        if (token !== panelToken) return;
        seriesCache.set(id, series);
        draw(series);
      }
    } catch (e) {
      if (token === panelToken) {
        panel.innerHTML = '<div class="p-error">Nie udało się wczytać pola.</div>';
        fail("Nie udało się wczytać pola")(e);
      }
    }
  }

  panel.addEventListener("click", (ev) => {
    const t = ev.target as HTMLElement;
    if (t.closest(".p-close")) return select(null, { emit: true });
    const head = t.closest<HTMLButtonElement>(".threat-head");
    if (head) {
      const li = head.closest<HTMLElement>(".threat")!;
      const code = li.dataset.code!;
      const open = !li.classList.contains("open");
      li.classList.toggle("open", open);
      head.setAttribute("aria-expanded", String(open));
      if (open) panelState.open.add(code); else panelState.open.delete(code);
      return;
    }
    const range = t.closest<HTMLButtonElement>("button[data-range]");
    if (range && selected != null) {
      panelState.range = range.dataset.range as PanelState["range"];
      void loadPanel(selected);
    }
  });

  // --- events from the page ------------------------------------------------------------------------
  events.on("field:focus", ({ fieldId }) => {
    if (!layers.has(fieldId)) return;
    flyTo(fieldId);
    if (selected !== fieldId) select(fieldId, { emit: false });
    events.emit("field:selected", { fieldId });   // the map sends it itself after focusing (interfaces.md)
  });

  events.on("date:changed", () => {
    viewDate = clock.today;                       // ctx.clock is already updated by main.ts
    seriesCache.clear();
    renderDays();
    void loadDay();
  });

  events.on("risks:updated", ({ fieldIds }) => {
    fieldIds.forEach((id) => seriesCache.delete(id));
    void (async () => {
      try {
        dayRisks = await api.getRisks(viewDate);
        recolour(fieldIds);
        for (const id of fieldIds) {
          layers.get(id)?.eachLayer((l) => {
            const el = (l as L.Path & { _path?: SVGElement })._path;
            el?.classList.add("pulse");
            window.setTimeout(() => el?.classList.remove("pulse"), 2400);
          });
        }
        if (selected != null && fieldIds.includes(selected)) void loadPanel(selected);
      } catch (e) {
        fail("Nie udało się odświeżyć ryzyk")(e);
      }
    })();
  });

  // --- start ---------------------------------------------------------------------------------------
  renderDays();
  void (async () => {
    container.classList.add("is-loading");
    try {
      const [fc, th] = await Promise.all([api.getFields(), api.getThreats()]);
      th.forEach((t) => {
        threats.set(t.code, t);
        threatNames.set(t.code, t.name);
      });
      renderFilter();
      drawFields(fc);
      await loadDay();
    } catch (e) {
      fail("Nie udało się wczytać mapy")(e);
    } finally {
      container.classList.remove("is-loading");
    }
  })();
}

