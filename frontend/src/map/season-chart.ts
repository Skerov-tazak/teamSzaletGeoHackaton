// The season chart of one threat: SVG, solid up to today, dashed for the coming days, with the level
// bands and the 0.33 / 0.66 lines. Dates are YYYY-MM-DD strings; x is days since the first one.

import type { RiskPoint } from "../api/types";
import { daysBetween, formatDate, formatNumber } from "../dom";
import { CUT_OFFS, LEVEL_COLOURS, levelOfScore } from "../risk";

const SVG = "http://www.w3.org/2000/svg";
const MONTHS = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];

const WIDTH = 340;
const HEIGHT = 160;
const PAD = { left: 30, right: 8, top: 10, bottom: 22 };

function svg<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number>): SVGElementTagNameMap[K] {
  const element = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
  return element;
}

/** Points are sorted by date; `today` and `last` (today + 7) bound what is solid and what is dashed. */
export function seasonChart(points: RiskPoint[], today: string, last: string, title: string): SVGSVGElement {
  const root = svg("svg", { viewBox: `0 0 ${WIDTH} ${HEIGHT}`, class: "season-chart", role: "img" });
  const label = svg("title", {});
  label.textContent = title;
  root.append(label);

  const first = points.length ? points[0].date : today;
  const span = Math.max(1, daysBetween(first, last));
  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const x = (date: string) => PAD.left + (daysBetween(first, date) / span) * plotW;
  const y = (score: number) => PAD.top + (1 - Math.max(0, Math.min(1, score))) * plotH;

  // level bands and lines
  const bands: [number, number, string][] = [
    [0, CUT_OFFS.medium, LEVEL_COLOURS.low],
    [CUT_OFFS.medium, CUT_OFFS.high, LEVEL_COLOURS.medium],
    [CUT_OFFS.high, 1, LEVEL_COLOURS.high],
  ];
  for (const [low, high, colour] of bands) {
    root.append(svg("rect", { x: PAD.left, y: y(high), width: plotW, height: y(low) - y(high), fill: colour, opacity: 0.1 }));
  }
  for (const cut of [CUT_OFFS.medium, CUT_OFFS.high]) {
    root.append(svg("line", { x1: PAD.left, x2: WIDTH - PAD.right, y1: y(cut), y2: y(cut), class: "cut-line" }));
    const text = svg("text", { x: PAD.left - 4, y: y(cut) + 3, class: "axis-label", "text-anchor": "end" });
    text.textContent = formatNumber(cut, 2);
    root.append(text);
  }
  for (const value of [0, 1]) {
    const text = svg("text", { x: PAD.left - 4, y: y(value) + 3, class: "axis-label", "text-anchor": "end" });
    text.textContent = String(value);
    root.append(text);
  }

  // month ticks
  let [year, month] = first.split("-").map(Number);
  for (let i = 0; i < 24; i++) {
    const tick = `${year}-${String(month).padStart(2, "0")}-01`;
    if (tick > last) break;
    if (tick >= first) {
      const tx = x(tick);
      root.append(svg("line", { x1: tx, x2: tx, y1: PAD.top + plotH, y2: PAD.top + plotH + 3, class: "tick" }));
      const text = svg("text", { x: tx + 2, y: HEIGHT - 6, class: "axis-label" });
      text.textContent = MONTHS[month - 1];
      root.append(text);
    }
    month = month === 12 ? 1 : month + 1;
    if (month === 1) year++;
  }

  // today
  const todayX = x(today);
  root.append(svg("line", { x1: todayX, x2: todayX, y1: PAD.top, y2: PAD.top + plotH, class: "today-line" }));
  const todayText = svg("text", { x: todayX + 3, y: PAD.top + 9, class: "axis-label today-label" });
  todayText.textContent = "dziś";
  root.append(todayText);

  // the line: season so far (solid) and coming days (dashed), sharing today's point
  const past = points.filter((p) => p.date <= today);
  const coming = points.filter((p) => p.date >= today);
  const path = (series: RiskPoint[]) => series.map((p) => `${x(p.date).toFixed(1)},${y(p.score).toFixed(1)}`).join(" ");
  if (past.length) root.append(svg("polyline", { points: path(past), class: "risk-line" }));
  if (coming.length) root.append(svg("polyline", { points: path(coming), class: "risk-line coming" }));

  const now = points.find((p) => p.date === today);
  if (now) {
    const dot = svg("circle", { cx: x(now.date), cy: y(now.score), r: 3.5, fill: LEVEL_COLOURS[levelOfScore(now.score)], class: "today-dot" });
    const tip = svg("title", {});
    tip.textContent = `${formatDate(today)}: ${formatNumber(now.score, 2)}`;
    dot.append(tip);
    root.append(dot);
  }
  return root;
}
