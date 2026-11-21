// The sidebar's layer panel: base map, overlays, risk legend and the demo date.
// Every group collapses from its header (▲/▼), and the state survives re-renders (a checkbox
// change re-renders the panel, so the collapsed groups are kept in the instance).

import { byId, el } from "../ui/dom";
import { RISK_COLOURS, RISK_LABELS } from "../risk";
import type { LayerState } from "../layer-state";

const BASEMAPS: { value: LayerState["basemap"]; label: string }[] = [
  { value: "osm", label: "OpenStreetMap (CARTO)" },
  { value: "topo", label: "OpenTopoMap" },
  { value: "satellite", label: "Ortofoto (Esri)" },
];

const OVERLAYS: { key: keyof Omit<LayerState, "basemap">; label: string }[] = [
  { key: "fields", label: "Działki (API)" },
  { key: "risks", label: "Ryzyko upraw (kolor)" },
  { key: "ownParcels", label: "Moje działki (Own data)" },
];

type GroupId = "basemap" | "overlays" | "legend" | "date";

const GROUP_TITLES: Record<GroupId, string> = {
  basemap: "Mapa bazowa",
  overlays: "Warstwy",
  legend: "Legenda ryzyka",
  date: "Data demonstracji",
};

export class LayersPanel {
  private state: LayerState;
  // "Legenda ryzyka" and the demo date start collapsed; the switches stay open.
  private readonly collapsed = new Set<GroupId>(["legend", "date"]);

  constructor(
    private readonly onChange: (state: LayerState) => void,
    initial: LayerState,
    private readonly onToggle?: () => void,
  ) {
    this.state = { ...initial };
    this.render();
  }

  update(state: LayerState): void {
    this.state = { ...state };
    this.render();
  }

  private set(patch: Partial<LayerState>): void {
    this.state = { ...this.state, ...patch };
    this.render();
    this.onChange({ ...this.state });
  }

  private toggleGroup(id: GroupId): void {
    if (this.collapsed.has(id)) {
      this.collapsed.delete(id);
    } else {
      this.collapsed.add(id);
    }
    this.render();
  }

  /** A collapsible group: a header button (▲/▼) plus a body that is hidden when collapsed. */
  private group(id: GroupId, body: HTMLElement[], className = "layers-group"): HTMLElement {
    const isCollapsed = this.collapsed.has(id);
    const section = el("section", `${className} collapsible${isCollapsed ? " is-collapsed" : ""}`);

    const headerButton = el("button", "group-toggle");
    headerButton.type = "button";
    headerButton.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
    headerButton.setAttribute("aria-controls", `layer-group-${id}`);
    headerButton.title = isCollapsed ? "Rozwiń grupę" : "Zwiń grupę";
    headerButton.append(
      el("span", "group-title", GROUP_TITLES[id]),
      el("span", "group-arrow", isCollapsed ? "▼" : "▲"),
    );
    headerButton.addEventListener("click", () => this.toggleGroup(id));

    const content = el("div", "group-body");
    content.id = `layer-group-${id}`;
    content.hidden = isCollapsed;
    for (const item of body) content.append(item);

    section.append(headerButton, content);
    return section;
  }

  private render(): void {
    const container = byId("layers-panel");
    container.replaceChildren();

    const header = el("div", "layers-header");
    header.append(el("h2", undefined, "Warstwy"));
    if (this.onToggle) {
      const close = el("button", "icon-button layers-close", "‹");
      close.type = "button";
      close.title = "Schowaj panel";
      close.addEventListener("click", this.onToggle);
      header.append(close);
    }

    const basemapOptions = BASEMAPS.map((basemap) =>
      this.radioOption("basemap", basemap.value, basemap.label, this.state.basemap === basemap.value, () =>
        this.set({ basemap: basemap.value }),
      ),
    );

    const overlayOptions = OVERLAYS.map((overlay) =>
      this.checkboxOption(overlay.label, this.state[overlay.key], () =>
        this.set({ [overlay.key]: !this.state[overlay.key] } as Partial<LayerState>),
      ),
    );

    container.append(
      header,
      this.group("basemap", basemapOptions),
      this.group("overlays", overlayOptions),
      this.group("legend", [this.legendBody()]),
      this.group("date", [this.dateBody()]),
    );
  }

  private radioOption(
    name: string,
    value: string,
    label: string,
    checked: boolean,
    onPick: () => void,
  ): HTMLLabelElement {
    const wrapper = el("label", "layer-option");
    const input = el("input");
    input.type = "radio";
    input.name = name;
    input.value = value;
    input.checked = checked;
    input.addEventListener("change", onPick);
    wrapper.append(input, el("span", undefined, label));
    return wrapper;
  }

  private checkboxOption(label: string, checked: boolean, onToggle: () => void): HTMLLabelElement {
    const wrapper = el("label", "layer-option");
    const input = el("input");
    input.type = "checkbox";
    input.checked = checked;
    input.addEventListener("change", onToggle);
    wrapper.append(input, el("span", undefined, label));
    return wrapper;
  }

  private legendBody(): HTMLElement {
    const body = el("div");
    for (const level of ["high", "mid", "low"] as const) {
      const item = el("div", "legend-item");
      const swatch = el("span", "legend-swatch");
      swatch.style.background = RISK_COLOURS[level];
      item.append(swatch, el("span", undefined, RISK_LABELS[level]));
      body.append(item);
    }
    return body;
  }

  private dateBody(): HTMLElement {
    const body = el("div");
    body.append(el("p", "date-note", "Pobierana z platformy (/api/clock/)"));
    return body;
  }
}

/** Keeps the demo-date note in the sidebar in sync with the API clock. */
export function showClockNote(today: string | null, forecastDays: number): void {
  const note = document.querySelector<HTMLElement>("#layers-panel .date-note");
  if (!note) return;
  note.textContent = today
    ? `Dziś (demo): ${today}. Prognoza: ${forecastDays} dni.`
    : "Data demo niedostępna — endpoint /api/clock/ jeszcze nie istnieje.";
}