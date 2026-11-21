// The field panel: details, that day's threats with the "why" from explanation version 1, and the
// season chart. Drawn inside the map's container; reloads when the date or the field's risks change.

import { errorMessage } from "../api/client";
import type { ExplanationDriver, ExplanationV1, FieldDayRisk, FieldDetail, FieldRiskSeries } from "../api/types";
import type { AppContext } from "../context";
import { CATEGORY_LABELS, cropName, formatDate, formatNumber, formatPercent, h, shiftDate } from "../dom";
import { isLevel, LEVEL_COLOURS, LEVEL_LABELS, levelOfScore } from "../risk";
import { seasonChart } from "./season-chart";

const ACTION_LABELS: Record<string, string> = { wait: "Czekaj", monitor: "Obserwuj", treat: "Zabieg" };

function levelBadge(level: keyof typeof LEVEL_LABELS): HTMLElement {
  return h("span", { class: `level-badge level-${level}`, style: `--level:${LEVEL_COLOURS[level]}` }, LEVEL_LABELS[level]);
}

function sortedDrivers(drivers: ExplanationDriver[] | undefined): ExplanationDriver[] {
  return [...(drivers ?? [])]
    .filter((driver) => typeof driver?.label === "string" && driver.label)
    .sort((a, b) => (b.effect ?? -1) - (a.effect ?? -1));
}

/** The "why" of one risk, from explanation version 1. Unknown keys are ignored. */
function whyPanel(risk: FieldDayRisk): HTMLElement {
  const why = (risk.explanation ?? {}) as ExplanationV1;
  const body = h("div", { class: "why" });
  if (why.summary) body.append(h("p", { class: "why-summary" }, why.summary));

  const drivers = sortedDrivers(why.drivers);
  if (drivers.length) {
    body.append(
      h("h4", {}, "Dlaczego"),
      h("ul", { class: "why-drivers" }, ...drivers.map((d) => h("li", { class: d.effect === null || d.effect === undefined ? "context" : "" }, d.label ?? ""))),
    );
  }

  const action = why.action;
  if (action?.text) {
    const label = ACTION_LABELS[action.type ?? ""] ?? "Zalecenie";
    const block = h("div", { class: `why-action action-${action.type ?? "other"}` }, h("strong", {}, `${label}: `), action.text);
    if (action.type === "treat" && action.spray_window?.date) {
      block.append(h("div", { class: "spray-window" }, `Okno zabiegu: ${formatDate(action.spray_window.date)}`));
    }
    body.append(block);
  }

  const facts: string[] = [];
  if (why.growth_stage?.name) {
    const bbch = typeof why.growth_stage.bbch === "number" ? ` (BBCH ${why.growth_stage.bbch})` : "";
    facts.push(`Faza: ${why.growth_stage.name}${bbch}`);
  }
  if (typeof why.confidence === "number") facts.push(`Pewność: ${formatPercent(why.confidence)}`);
  if (facts.length) body.append(h("p", { class: "why-facts" }, facts.join(" · ")));
  if (!body.childElementCount) body.append(h("p", { class: "muted" }, "Brak wyjaśnienia dla tego ryzyka."));
  return body;
}

function soilLine(field: FieldDetail): string | null {
  const soil = field.soil;
  if (!soil) return null;
  const parts: string[] = [];
  if (soil.soil_texture) parts.push(soil.soil_texture);
  if (soil.ph !== null) parts.push(`pH ${formatNumber(soil.ph)}`);
  const fractions = [["glina", soil.clay], ["pył", soil.silt], ["piasek", soil.sand]] as const;
  const shares = fractions.filter(([, value]) => value !== null).map(([name, value]) => `${name} ${formatPercent(value as number)}`);
  if (shares.length) parts.push(shares.join(", "));
  if (soil.om !== null) parts.push(`materia organiczna ${formatNumber(soil.om)} g/kg`);
  return parts.length ? parts.join(" · ") : null;
}

function cropHistoryLine(field: FieldDetail): string | null {
  const years = field.crop_history.slice(-4).map((year) => {
    const top = year.classes[0];
    return top ? `${year.year}: ${cropName(top)} (${formatPercent(top.share)})` : `${year.year}: —`;
  });
  return years.length ? years.join(", ") : null;
}

export class FieldPanel {
  private fieldId: number | null = null;
  private token = 0;
  private chartThreat: string | null = null;

  constructor(
    private readonly container: HTMLElement,
    private readonly ctx: AppContext,
    private readonly onClose: () => void,
    private readonly threatName: (code: string) => string,
  ) {
    container.hidden = true;
  }

  get openFieldId(): number | null {
    return this.fieldId;
  }

  show(fieldId: number): void {
    if (fieldId !== this.fieldId) this.chartThreat = null;
    this.fieldId = fieldId;
    this.container.hidden = false;
    void this.load();
  }

  reload(): void {
    if (this.fieldId !== null) void this.load();
  }

  hide(): void {
    this.token++;
    this.fieldId = null;
    this.container.hidden = true;
    this.container.replaceChildren();
  }

  private header(title: string): HTMLElement {
    const close = h("button", { type: "button", class: "panel-close", "aria-label": "Zamknij", title: "Zamknij" }, "×");
    close.addEventListener("click", () => this.onClose());
    return h("header", { class: "panel-header" }, h("h2", {}, title), close);
  }

  private async load(): Promise<void> {
    const fieldId = this.fieldId;
    if (fieldId === null) return;
    const token = ++this.token;
    const today = this.ctx.clock.today;
    if (!this.container.childElementCount) {
      this.container.replaceChildren(this.header("Wczytywanie…"), h("p", { class: "muted" }, "Wczytywanie pola…"));
    } else {
      this.container.classList.add("loading");
    }
    try {
      const [field, day, series] = await Promise.all([
        this.ctx.api.getField(fieldId),
        this.ctx.api.getFieldDayRisks(fieldId, today),
        this.ctx.api.getFieldRisks(fieldId, { to: shiftDate(today, this.ctx.clock.forecastDays) }),
      ]);
      if (token !== this.token) return;
      this.render(field, day.risks, series, today);
    } catch (error) {
      if (token !== this.token) return;
      this.container.replaceChildren(
        this.header(`Pole #${fieldId}`),
        h("p", { class: "panel-error" }, `Nie udało się wczytać pola: ${errorMessage(error)}`),
      );
    } finally {
      if (token === this.token) this.container.classList.remove("loading");
    }
  }

  private render(field: FieldDetail, risks: FieldDayRisk[], series: FieldRiskSeries, today: string): void {
    const meta = h("p", { class: "panel-meta" }, `${cropName(field.crop)} · ${formatNumber(field.area_ha)} ha`);

    // that day's threats, highest first
    const threats = h("section", { class: "panel-section" }, h("h3", {}, `Zagrożenia ${formatDate(today)}`));
    if (!risks.length) threats.append(h("p", { class: "muted" }, "Brak ocen ryzyka na ten dzień."));
    const chartSlot = h("div", { class: "chart-slot" });
    const select = h("select", { class: "chart-threat", "aria-label": "Zagrożenie na wykresie" });

    for (const risk of risks) {
      const why = (risk.explanation ?? {}) as ExplanationV1;
      const level = isLevel(why.level) ? why.level : levelOfScore(risk.score);
      const summary = h(
        "summary",
        {},
        levelBadge(level),
        h("span", { class: "threat-name" }, risk.threat.name),
        h("span", { class: "threat-score", title: "Wskaźnik ryzyka 0–1" }, formatNumber(risk.score, 2)),
      );
      const details = h(
        "details",
        { class: "threat" },
        summary,
        h("p", { class: "threat-category muted" }, CATEGORY_LABELS[risk.threat.category] ?? risk.threat.category),
        whyPanel(risk),
      );
      details.addEventListener("toggle", () => {
        if (details.open) {
          this.chartThreat = risk.threat.code;
          select.value = risk.threat.code;
          drawChart();
        }
      });
      threats.append(details);
    }

    // season chart: the chosen threat, or today's highest
    const season = h("section", { class: "panel-section" }, h("h3", {}, "Przebieg sezonu"));
    const byCode = new Map(series.threats.map((t) => [t.threat_code, t.points]));
    const codes = [...byCode.keys()];
    const preferred = this.chartThreat ?? risks[0]?.threat.code ?? codes[0] ?? null;
    this.chartThreat = preferred && byCode.has(preferred) ? preferred : codes[0] ?? null;
    select.replaceChildren(...codes.map((code) => h("option", { value: code }, this.threatName(code))));
    if (this.chartThreat) select.value = this.chartThreat;
    const drawChart = () => {
      const points = this.chartThreat ? byCode.get(this.chartThreat) ?? [] : [];
      chartSlot.replaceChildren(
        points.length
          ? seasonChart(points, today, series.to, this.threatName(this.chartThreat ?? ""))
          : h("p", { class: "muted" }, "Brak danych o ryzyku w tym okresie."),
      );
    };
    select.addEventListener("change", () => {
      this.chartThreat = select.value;
      drawChart();
    });
    if (codes.length > 1) season.append(select);
    season.append(chartSlot, h("p", { class: "chart-legend muted" }, "linia ciągła: sezon do dziś · przerywana: najbliższe dni"));
    drawChart();

    // the field itself
    const facts = h("section", { class: "panel-section" }, h("h3", {}, "Pole"));
    const soil = soilLine(field);
    const history = cropHistoryLine(field);
    facts.append(h("p", {}, h("strong", {}, "Gleba: "), soil ?? "brak danych"));
    facts.append(h("p", {}, h("strong", {}, "Uprawy: "), history ?? "brak danych"));

    this.container.replaceChildren(this.header(field.name), meta, threats, season, facts);
  }
}
