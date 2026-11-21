// Season chart of one field: risk score (0–1) per threat over time. Solid up to today (season so far),
// dashed for the coming days (today + 1 … + 7), the agreed level cut-offs as bands, crosshair + tooltip.

import { CUT_HIGH, CUT_MEDIUM, LEVEL_LABEL, addDays, daysBetween, esc, levelOf, monthShort, shortDate } from "./format";

export interface ChartSeries {
  code: string;
  name: string;
  color: string;           // categorical slot, assigned by the caller in a fixed order
  points: { date: string; score: number }[];
}

const SVG = "http://www.w3.org/2000/svg";
const H = 210;
const M = { top: 18, right: 58, bottom: 24, left: 34 };

function el<K extends keyof SVGElementTagNameMap>(name: K, attrs: Record<string, string | number>, parent?: Element) {
  const node = document.createElementNS(SVG, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  parent?.appendChild(node);
  return node;
}

export function renderSeasonChart(host: HTMLElement, series: ChartSeries[], from: string, to: string, today: string): void {
  host.replaceChildren();
  host.classList.add("fup-chart");
  const W = Math.max(280, Math.round(host.clientWidth || 360));   // drawn at its real width: text stays 11 px
  const span = Math.max(1, daysBetween(from, to));
  const iw = W - M.left - M.right;
  const ih = H - M.top - M.bottom;
  const x = (d: string) => M.left + (daysBetween(from, d) / span) * iw;
  const y = (s: number) => M.top + (1 - s) * ih;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Ryzyko w sezonie" }, host);

  // level bands + their labels on the right
  const bands: [number, number, keyof typeof LEVEL_LABEL][] = [[CUT_HIGH, 1, "high"], [CUT_MEDIUM, CUT_HIGH, "medium"], [0, CUT_MEDIUM, "low"]];
  for (const [lo, hi, lvl] of bands) {
    el("rect", { x: M.left, y: y(hi), width: iw, height: y(lo) - y(hi), class: `band band-${lvl}` }, svg);
    const t = el("text", { x: M.left + iw + 8, y: (y(lo) + y(hi)) / 2 + 4, class: "band-label" }, svg);
    t.textContent = LEVEL_LABEL[lvl];
  }
  for (const s of [0, CUT_MEDIUM, CUT_HIGH, 1]) {
    el("line", { x1: M.left, x2: M.left + iw, y1: y(s), y2: y(s), class: s === 0 ? "axis" : "grid" }, svg);
    const t = el("text", { x: M.left - 6, y: y(s) + 4, class: "tick", "text-anchor": "end" }, svg);
    t.textContent = s.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  }

  // month ticks
  let d = from.slice(0, 8) + "01";
  if (d < from) d = addDays(d, 32).slice(0, 8) + "01";
  const step = span > 200 ? 2 : 1;
  let i = 0;
  while (d <= to) {
    if (i++ % step === 0) {
      el("line", { x1: x(d), x2: x(d), y1: M.top + ih, y2: M.top + ih + 4, class: "axis" }, svg);
      const t = el("text", { x: x(d), y: H - 8, class: "tick", "text-anchor": "middle" }, svg);
      t.textContent = monthShort(d);
    }
    d = addDays(d, 32).slice(0, 8) + "01";
  }

  // future shade + today line
  if (today < to) {
    el("rect", { x: x(today), y: M.top, width: x(to) - x(today), height: ih, class: "future" }, svg);
  }
  if (today >= from && today <= to) {
    el("line", { x1: x(today), x2: x(today), y1: M.top - 4, y2: M.top + ih, class: "today" }, svg);
    const t = el("text", { x: x(today), y: M.top - 4, class: "today-label", "text-anchor": "middle" }, svg);
    t.textContent = "dziś";
  }

  // lines: solid to today, dashed after
  const path = (pts: { date: string; score: number }[]) =>
    pts.map((p, k) => `${k ? "L" : "M"}${x(p.date).toFixed(1)},${y(p.score).toFixed(1)}`).join("");
  for (const s of series) {
    const pts = s.points.filter((p) => p.date >= from && p.date <= to);
    const past = pts.filter((p) => p.date <= today);
    const future = pts.filter((p) => p.date >= today);
    if (past.length > 1) el("path", { d: path(past), class: "line", stroke: s.color }, svg);
    if (future.length > 1) el("path", { d: path(future), class: "line dashed", stroke: s.color }, svg);
    const last = past[past.length - 1];
    if (last) el("circle", { cx: x(last.date), cy: y(last.score), r: 4, fill: s.color, class: "dot" }, svg);
  }

  // hover: crosshair + tooltip
  const cross = el("line", { y1: M.top, y2: M.top + ih, class: "cross", visibility: "hidden" }, svg);
  const marks = series.map((s) => el("circle", { r: 4, fill: s.color, class: "dot", visibility: "hidden" }, svg));
  const tip = document.createElement("div");
  tip.className = "fup-tip";
  tip.hidden = true;
  host.appendChild(tip);
  const hit = el("rect", { x: M.left, y: 0, width: iw, height: H, fill: "transparent" }, svg);
  const byDate = series.map((s) => new Map(s.points.map((p) => [p.date, p.score])));

  hit.addEventListener("pointermove", (ev) => {
    const box = svg.getBoundingClientRect();
    const px = ((ev.clientX - box.left) / box.width) * W;
    const day = addDays(from, Math.round(((px - M.left) / iw) * span));
    if (day < from || day > to) return;
    cross.setAttribute("x1", String(x(day)));
    cross.setAttribute("x2", String(x(day)));
    cross.setAttribute("visibility", "visible");
    const rows: string[] = [];
    series.forEach((s, k) => {
      const v = byDate[k].get(day);
      if (v == null) {
        marks[k].setAttribute("visibility", "hidden");
        return;
      }
      marks[k].setAttribute("cx", String(x(day)));
      marks[k].setAttribute("cy", String(y(v)));
      marks[k].setAttribute("visibility", "visible");
      rows.push(`<div class="tip-row"><span class="swatch" style="background:${s.color}"></span><span class="tip-name">${esc(s.name)}</span>` +
        `<span class="tip-val">${v.toFixed(2)} · ${LEVEL_LABEL[levelOf(v)]}</span></div>`);
    });
    const when = day > today ? ` · prognoza +${daysBetween(today, day)}` : day === today ? " · dziś" : "";
    tip.innerHTML = `<div class="tip-date">${shortDate(day)}${when}</div>${rows.join("") || '<div class="tip-row">brak danych</div>'}`;
    tip.hidden = false;
    const hostBox = host.getBoundingClientRect();
    const left = ev.clientX - hostBox.left;
    const onRight = left < hostBox.width / 2;      // beside the cursor, never over the hovered point
    tip.style.left = onRight ? `${left + 14}px` : "";
    tip.style.right = onRight ? "" : `${hostBox.width - left + 14}px`;
  });
  hit.addEventListener("pointerleave", () => {
    cross.setAttribute("visibility", "hidden");
    marks.forEach((m) => m.setAttribute("visibility", "hidden"));
    tip.hidden = true;
  });

  // legend: identity never by colour alone
  const legend = document.createElement("div");
  legend.className = "fup-legend";
  legend.innerHTML = series.map((s) => `<span class="leg"><span class="swatch" style="background:${s.color}"></span>${esc(s.name)}</span>`).join("") +
    '<span class="leg muted"><span class="dash"></span>prognoza</span>';
  host.appendChild(legend);
}
