// The field details card ("why" panel) next to the map, shown when a field is selected.
// Data: GET /api/fields/{id}/, /risks/{date}/ and /risks/?from=&to= (docs/interfaces.md).

import type { Api } from "../api/client";
import { humaniseError } from "../api/client";
import type { FieldDayRisks, FieldRisksSeries } from "../types";
import { el } from "../ui/dom";
import { riskColour } from "../risk";

export interface FieldDetailsCardOptions {
  api: Api;
  container: HTMLElement;
  today: string | null;
  forecastDays: number;
  seasonStart(date: string): string;
  onClose: () => void;
  onThreatClick(threatCode: string): void;
}

export class FieldDetailsCard {
  private readonly root: HTMLElement;
  private readonly options: FieldDetailsCardOptions;
  private readonly container: HTMLElement;

  constructor(options: FieldDetailsCardOptions) {
    this.options = { ...options };
    this.container = options.container;
    this.container.replaceChildren();
    this.root = el("div", "details-card");
    this.container.append(this.root);
    this.container.hidden = true;
  }

  setToday(today: string | null): void {
    this.options.today = today;
  }

  hide(): void {
    this.container.hidden = true;
  }

  async show(fieldId: number): Promise<void> {
    const { api, today, forecastDays, seasonStart } = this.options;
    this.container.hidden = false;
    this.root.replaceChildren(el("p", "muted", "Wczytywanie działki…"));

    let details;
    try {
      details = await api.getField(fieldId);
    } catch (error) {
      this.root.replaceChildren(this.header(`Działka #${fieldId}`), el("p", "error", humaniseError(error)));
      return;
    }

    const header = this.header(details.name || `Działka #${fieldId}`);
    const meta = el("dl", "details-meta");
    meta.append(this.metaRow("Uprawa", details.crop ? `${details.crop.name} (${details.crop.code})` : "—"));
    meta.append(this.metaRow("Powierzchnia", `${details.area_ha.toFixed(1).replace(".", ",")} ha`));

    const section = el("section", "details-section");
    if (!today) {
      section.append(
        el("h3", undefined, "Ryzyko"),
        el("p", "muted", "Data demo niedostępna (/api/clock/), więc nie można pokazać ryzyka."),
      );
    } else {
      section.append(el("h3", undefined, `Ryzyko na ${today}`));
      const risksLoaded = this.renderDayRisks(fieldId, today);
      section.append(risksLoaded);

      const chart = el("div", "details-chart");
      chart.append(el("p", "muted", "Wczytywanie wykresu sezonu…"));
      section.append(el("h3", undefined, "Sezon"), chart);
      void this.loadSeason(fieldId, seasonStart(today), today, forecastDays, chart);
    }

    this.root.replaceChildren(header, meta, section);
  }

  private header(title: string): HTMLElement {
    const header = el("header", "details-header");
    const close = el("button", "icon-button", "×");
    close.type = "button";
    close.title = "Zamknij";
    close.addEventListener("click", this.options.onClose);
    header.append(el("h2", undefined, title), close);
    return header;
  }

  private metaRow(label: string, value: string): DocumentFragment {
    const fragment = document.createDocumentFragment();
    fragment.append(el("dt", undefined, label), el("dd", undefined, value));
    return fragment;
  }

  private renderDayRisks(fieldId: number, today: string): HTMLElement {
    const list = el("ul", "risk-list");
    list.append(el("li", "muted", "Wczytywanie…"));
    this.options.api
      .getFieldRisksOn(fieldId, today)
      .then((day: FieldDayRisks) => {
        list.replaceChildren();
        if (day.risks.length === 0) {
          list.append(el("li", "muted", "Brak danych o ryzyku dla tej działki."));
          return;
        }
        for (const risk of [...day.risks].sort((a, b) => b.score - a.score)) {
          const item = el("li", "risk-item");
          const dot = el("span", "risk-dot");
          dot.style.background = riskColour(risk.score);
          const label = el("button", "risk-link", risk.threat.name);
          label.type = "button";
          label.addEventListener("click", () => this.options.onThreatClick(risk.threat.code));
          item.append(dot, label, el("span", "risk-score", risk.score.toFixed(2)));
          list.append(item);
        }
      })
      .catch((error: unknown) => {
        list.replaceChildren(el("li", "muted", humaniseError(error)));
      });
    return list;
  }

  private async loadSeason(
    fieldId: number,
    from: string,
    to: string,
    forecastDays: number,
    host: HTMLElement,
  ): Promise<void> {
    try {
      const series = await this.options.api.getFieldRisks(fieldId, from, to);
      host.replaceChildren(renderSeasonChart(series, to, forecastDays));
    } catch (error) {
      host.replaceChildren(el("p", "muted", humaniseError(error)));
    }
  }
}

const CHART_WIDTH = 280;
const CHART_HEIGHT = 110;
const COLOURS = ["#2e7d32", "#1565c0", "#6a1b9a", "#ef6c00", "#00838f"];

/** One line per threat over the season; the days after today are dashed (coming days). */
function renderSeasonChart(series: FieldRisksSeries, today: string, forecastDays: number): SVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`);
  svg.setAttribute("class", "season-chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Ryzyko w sezonie");

  const allPoints = series.threats.flatMap((threat) => threat.points);
  if (allPoints.length === 0) {
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", "8");
    text.setAttribute("y", "20");
    text.setAttribute("class", "chart-empty");
    text.textContent = "Brak danych o ryzyku w sezonie.";
    svg.append(text);
    return svg;
  }

  const dates = allPoints.map((point) => Date.parse(`${point.date}T00:00:00Z`));
  const minDate = Math.min(...dates);
  const maxDate = Math.max(...dates);
  const span = Math.max(1, maxDate - minDate);
  const x = (date: string) => ((Date.parse(`${date}T00:00:00Z`) - minDate) / span) * (CHART_WIDTH - 16) + 8;
  const y = (score: number) => CHART_HEIGHT - 10 - score * (CHART_HEIGHT - 24);

  const todayX = x(today);
  const grid = document.createElementNS("http://www.w3.org/2000/svg", "line");
  grid.setAttribute("x1", String(todayX));
  grid.setAttribute("x2", String(todayX));
  grid.setAttribute("y1", "4");
  grid.setAttribute("y2", String(CHART_HEIGHT - 4));
  grid.setAttribute("class", "chart-today");
  svg.append(grid);

  series.threats.slice(0, 5).forEach((threat, index) => {
    for (const split of [0, 1]) {
      const points = threat.points.filter((point) => (split === 0 ? point.date <= today : point.date >= today));
      if (points.length < 2) continue;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      line.setAttribute("points", points.map((point) => `${x(point.date)},${y(point.score)}`).join(" "));
      line.setAttribute("fill", "none");
      line.setAttribute("stroke", COLOURS[index]);
      line.setAttribute("stroke-width", "1.6");
      if (split === 1) line.setAttribute("stroke-dasharray", "4 3");
      svg.append(line);
    }
  });

  const caption = document.createElementNS("http://www.w3.org/2000/svg", "text");
  caption.setAttribute("x", String(CHART_WIDTH - 8));
  caption.setAttribute("y", "12");
  caption.setAttribute("text-anchor", "end");
  caption.setAttribute("class", "chart-caption");
  caption.textContent = `prognoza +${forecastDays} dni →`;
  svg.append(caption);

  return svg;
}
