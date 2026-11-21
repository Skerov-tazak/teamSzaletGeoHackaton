// The field panel: details, that day's threats with the "why" from explanation v1, the season chart and
// the field's background (crop history, soil). Pure rendering: index.ts loads the data and wires events.

import { renderSeasonChart, type ChartSeries } from "./chart";
import type { Driver, Explanation, FieldDayRisks, FieldDetail, FieldRiskSeries, Level } from "./contract";
import {
  ACTION_LABEL, CATEGORY_LABEL, LEVEL_LABEL, LEVEL_TITLE, addDays, cropName, daysBetween, esc, ha, longDate, pct,
  shortDate, weekday,
} from "./format";

/** Categorical slots 1–3 of the validated default palette (light, dark): fixed order, never cycled. */
const SERIES = ["var(--fup-series-1)", "var(--fup-series-2)", "var(--fup-series-3)"];

const TEXTURE_PL: Record<string, string> = {
  "sand": "piasek", "loamy sand": "piasek gliniasty", "sandy loam": "glina piaszczysta", "loam": "glina",
  "silt loam": "pył gliniasty", "silt": "pył", "sandy clay loam": "glina piaszczysto-ilasta", "clay loam": "glina ilasta",
  "silty clay loam": "glina ilasto-pylasta", "sandy clay": "ił piaszczysty", "silty clay": "ił pylasty", "clay": "ił",
};

export interface PanelData {
  detail: FieldDetail;
  day: FieldDayRisks;
  series: FieldRiskSeries | null;
  today: string;
  viewDate: string;
}

export interface PanelState {
  open: Set<string>;               // expanded threat codes
  range: "recent" | "season";
}

const ICON = {
  high: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5 15 14H1z" fill="currentColor"/><path d="M8 6v3.6M8 11.4v.1" stroke="var(--fup-on-status)" stroke-width="1.6" stroke-linecap="round"/></svg>',
  medium: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.5" fill="currentColor"/><path d="M8 4.6v4M8 10.9v.1" stroke="var(--fup-on-status)" stroke-width="1.6" stroke-linecap="round"/></svg>',
  low: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.5" fill="currentColor"/><path d="m5 8.2 2 2 4-4.2" fill="none" stroke="var(--fup-on-status)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

const ACTION_ICON: Record<string, string> = {
  treat: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 16 15 5m-3-1 4 4M6 9l5 5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  monitor: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M2 10s3-5.5 8-5.5S18 10 18 10s-3 5.5-8 5.5S2 10 2 10Z" fill="none" stroke="currentColor" stroke-width="1.6"/><circle cx="10" cy="10" r="2.4" fill="currentColor"/></svg>',
  wait: '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M10 6v4l2.6 1.6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
};

export function levelPill(level: Level, extra = ""): string {
  return `<span class="fup-pill lvl-${level} ${extra}">${ICON[level]}${LEVEL_LABEL[level]}</span>`;
}

function driverRows(drivers: Driver[] | undefined): string {
  const list = drivers ?? [];
  const weighted = list.filter((d) => d.effect != null && d.effect > 0).sort((a, b) => (b.effect ?? 0) - (a.effect ?? 0));
  const context = list.filter((d) => d.effect == null || d.effect <= 0);
  const max = Math.max(0.0001, ...weighted.map((d) => d.effect ?? 0));
  const row = (d: Driver) => {
    const value = d.value != null && d.value !== "" ? `<span class="drv-val">${esc(typeof d.value === "number" ? +d.value.toFixed(2) : d.value)}${d.unit ? ` ${esc(d.unit)}` : ""}</span>` : "";
    const farmer = d.factor === "farmer_report" ? '<span class="drv-tag">zgłoszenie</span>' : "";
    return `<li class="drv"><div class="drv-head"><span class="drv-label">${farmer}${esc(d.label)}</span>${value}</div>` +
      `<div class="drv-bar"><span style="width:${((d.effect ?? 0) / max) * 100}%"></span></div>` +
      (d.text ? `<div class="drv-quote">„${esc(d.text)}”</div>` : "") +
      (d.threshold ? `<div class="drv-thr">${esc(d.threshold)}</div>` : "") + "</li>";
  };
  const ctx = (d: Driver) => {
    const value = d.value != null && d.value !== "" ? `: ${esc(typeof d.value === "number" ? +d.value.toFixed(1) : d.value)}${d.unit ? ` ${esc(d.unit)}` : ""}` : "";
    return `<li title="${esc(d.threshold ?? "")}">${esc(d.label)}${value}</li>`;
  };
  return (weighted.length ? `<h5>Co podnosi ryzyko</h5><ul class="drivers">${weighted.map(row).join("")}</ul>` : "") +
    (context.length ? `<h5>Kontekst</h5><ul class="context">${context.map(ctx).join("")}</ul>` : "");
}

function actionBox(e: Explanation, today: string): string {
  const a = e.action;
  if (!a) return "";
  const sw = a.spray_window;
  const window = sw
    ? `<div class="spray"><span class="spray-k">Najbliższe okno zabiegu</span><span class="spray-v">${weekday(sw.date)} ${shortDate(sw.date)}` +
      ` · ${sw.quality === "optimal" ? "warunki optymalne" : "warunki dopuszczalne"}</span></div>`
    : a.type === "treat" ? '<div class="spray none">Brak dobrego okna zabiegu w prognozie na 7 dni.</div>' : "";
  return `<div class="action act-${esc(a.type)}"><div class="act-icon">${ACTION_ICON[a.type] ?? ACTION_ICON.wait}</div><div>` +
    `<div class="act-title">${esc(ACTION_LABEL[a.type] ?? a.type)}</div><p>${esc(a.text)}</p>` +
    (a.threshold ? `<p class="act-thr"><b>Próg:</b> ${esc(a.threshold)}</p>` : "") + window + "</div></div>";
}

function meta(e: Explanation, today: string): string {
  const parts: string[] = [];
  if (e.growth_stage) parts.push(`<span><b>Faza:</b> ${esc(e.growth_stage.name)} (BBCH ${e.growth_stage.bbch})</span>`);
  if (e.confidence != null) {
    parts.push(`<span class="conf" title="Pewność oceny: metoda fazy wzrostu × jakość pogody × odległość prognozy">` +
      `<b>Pewność:</b> <span class="conf-bar"><span style="width:${Math.round(e.confidence * 100)}%"></span></span> ${pct(e.confidence)}</span>`);
  }
  if (e.forecast_lead_days) parts.push(`<span class="lead">prognoza +${e.forecast_lead_days} ${e.forecast_lead_days === 1 ? "dzień" : "dni"}</span>`);
  return `<div class="meta">${parts.join("")}</div>`;
}

function threatRow(r: FieldDayRisks["risks"][number], expanded: boolean, today: string): string {
  const e = r.explanation;
  const level = e.level;
  const name = e.threat?.name_pl ?? r.threat.name;
  const cat = CATEGORY_LABEL[r.threat.category] ?? r.threat.category;
  return `<li class="threat lvl-${level}${expanded ? " open" : ""}" data-code="${esc(r.threat.code)}">` +
    `<button class="threat-head" aria-expanded="${expanded}">` +
    `${levelPill(level)}<span class="threat-name">${esc(name)}<small>${esc(cat)}</small></span>` +
    `<span class="score"><span class="score-bar"><span style="width:${Math.round(r.score * 100)}%"></span></span>${r.score.toFixed(2)}</span>` +
    '<svg class="chev" viewBox="0 0 12 12" aria-hidden="true"><path d="m3 4.5 3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>' +
    "</button>" +
    `<div class="threat-body"><p class="summary">${esc(e.summary)}</p>${driverRows(e.drivers)}${actionBox(e, today)}${meta(e, today)}</div></li>`;
}

function about(d: FieldDetail): string {
  const hist = d.crop_history
    .filter((y) => y.classes.length)
    .map((y) => {
      const top = y.classes[0];
      return `<li><span class="yr">${y.year}</span>${esc(cropName(top))}<small>${Math.round(top.share * 100)}%</small></li>`;
    })
    .join("");
  const s = d.soil;
  const frac = (v: unknown) => (typeof v === "number" ? `${Math.round(v <= 1 ? v * 100 : v)}%` : "—");
  const soil = s
    ? `<dl class="soil"><div><dt>Tekstura</dt><dd>${esc(TEXTURE_PL[String(s.soil_texture ?? "").toLowerCase()] ?? s.soil_texture ?? "—")}</dd></div>` +
      `<div><dt>pH</dt><dd>${typeof s.ph === "number" ? s.ph.toFixed(1) : "—"}</dd></div>` +
      `<div><dt>Ił</dt><dd>${frac(s.clay)}</dd></div><div><dt>Piasek</dt><dd>${frac(s.sand)}</dd></div>` +
      `<div><dt>Pył</dt><dd>${frac(s.silt)}</dd></div></dl>`
    : '<p class="muted">Brak danych glebowych.</p>';
  return `<section class="sec"><h4>Historia upraw</h4><ul class="history">${hist || '<li class="muted">brak</li>'}</ul></section>` +
    `<section class="sec"><h4>Gleba</h4>${soil}</section>`;
}

export function renderPanel(host: HTMLElement, data: PanelData, state: PanelState, names: Map<string, string>): void {
  const { detail, day, series, today, viewDate } = data;
  const risks = day.risks;
  const worst = risks[0];
  const stage = risks.find((r) => r.explanation.growth_stage)?.explanation.growth_stage;
  const counts = { high: 0, medium: 0, low: 0 } as Record<Level, number>;
  risks.forEach((r) => counts[r.explanation.level]++);
  if (state.open.size === 0 && worst && worst.explanation.level !== "low") state.open.add(worst.threat.code);
  const lead = daysBetween(today, viewDate);
  const when = lead > 0 ? `prognoza na ${weekday(viewDate)} ${shortDate(viewDate)} (+${lead})` : longDate(viewDate);

  const overall = worst
    ? `<div class="overall lvl-${worst.explanation.level}"><div class="overall-k">${LEVEL_TITLE[worst.explanation.level]}</div>` +
      `<div class="overall-v">${esc(worst.explanation.threat?.name_pl ?? worst.threat.name)}</div>` +
      `<div class="overall-counts">${(["high", "medium", "low"] as Level[]).map((l) => `<span class="cnt lvl-${l}">${counts[l]} ${LEVEL_LABEL[l]}</span>`).join("")}</div></div>`
    : '<div class="overall empty">Brak ocen ryzyka na ten dzień.</div>';

  host.innerHTML =
    `<header class="p-head"><div><div class="p-crop">${esc(cropName(detail.crop))}</div><h3>${esc(detail.name)}</h3>` +
    `<div class="p-sub">${ha(detail.area_ha)}${stage ? ` · ${esc(stage.name)} (BBCH ${stage.bbch})` : ""}</div></div>` +
    '<button class="p-close" aria-label="Zamknij panel pola">×</button></header>' +
    `<div class="p-scroll">${overall}` +
    `<section class="sec"><h4>Zagrożenia <span class="when">${esc(when)}</span></h4>` +
    `<ul class="threats">${risks.map((r) => threatRow(r, state.open.has(r.threat.code), today)).join("") || ""}</ul></section>` +
    `<section class="sec"><div class="sec-row"><h4>Ryzyko w sezonie</h4><div class="seg" role="group" aria-label="Zakres wykresu">` +
    `<button data-range="recent" class="${state.range === "recent" ? "on" : ""}">3 miesiące</button>` +
    `<button data-range="season" class="${state.range === "season" ? "on" : ""}">cały sezon</button></div></div>` +
    `<div class="chart-host"></div><p class="chart-note">Trzy zagrożenia o najwyższym ryzyku tego dnia. Linia przerywana: najbliższe 7 dni z prognozy.</p></section>` +
    `${about(detail)}</div>`;

  const chartHost = host.querySelector<HTMLElement>(".chart-host")!;
  if (!series) {
    chartHost.innerHTML = '<div class="skeleton chart-skel"></div>';
    return;
  }
  const top = risks.slice(0, 3).map((r) => r.threat.code).sort();  // fixed slot order within the chart
  const picked: ChartSeries[] = top
    .map((code, k) => {
      const s = series.threats.find((t) => t.threat_code === code);
      return s ? { code, name: names.get(code) ?? code, color: SERIES[k], points: s.points } : null;
    })
    .filter((s): s is ChartSeries => s != null);
  const to = series.to;
  const from = state.range === "season" ? series.from : addDays(today, -90) > series.from ? addDays(today, -90) : series.from;
  if (picked.length) renderSeasonChart(chartHost, picked, from, to, today);
  else chartHost.innerHTML = '<p class="muted">Brak danych do wykresu.</p>';
}
