// "Moje uprawy": the fields of the farm with their crop, area and the highest risk on the
// demo's date. Clicking a row goes back to the map and focuses the field.

import type { AppContext } from "../app-context";
import { humaniseError } from "../api/client";
import { maxScore, riskColour, riskLevel, RISK_LABELS } from "../risk";
import type { FieldFeature } from "../types";
import { byId, el, formatArea } from "../ui/dom";

export function initCrops(ctx: AppContext): void {
  const listHost = byId("crops-list");
  const summaryHost = byId("crops-summary");

  const load = async (): Promise<void> => {
    listHost.replaceChildren(el("p", "muted", "Wczytywanie działek…"));
    try {
      const collection = await ctx.api.getFields();
      const today = ctx.clock.today;
      const scores = new Map<number, number>();

      if (today) {
        try {
          const risks = await ctx.api.getRisks(today);
          const perField = new Map<number, number[]>();
          for (const risk of risks.risks) {
            const values = perField.get(risk.field_id) ?? [];
            values.push(risk.score);
            perField.set(risk.field_id, values);
          }
          for (const [fieldId, values] of perField) {
            const value = maxScore(values);
            if (value !== null) scores.set(fieldId, value);
          }
        } catch {
          // risks are optional here; the fields still show
        }
      }

      summaryHost.textContent =
        `${collection.features.length} działek · ` +
        `${formatArea(collection.features.reduce((sum, feature) => sum + feature.properties.area_ha, 0))} · ` +
        (today ? `ryzyko na ${today}` : "data demo niedostępna");

      listHost.replaceChildren();
      if (collection.features.length === 0) {
        listHost.append(el("p", "muted", "Brak działek w odpowiedzi API."));
        return;
      }
      for (const feature of collection.features) listHost.append(renderRow(feature, scores.get(feature.properties.id)));
    } catch (error) {
      summaryHost.textContent = "";
      listHost.replaceChildren(el("p", "error", humaniseError(error)));
    }
  };

  const renderRow = (feature: FieldFeature, score: number | undefined): HTMLElement => {
    const row = el("button", "crop-row");
    row.type = "button";
    row.addEventListener("click", () => {
      ctx.shell.emit("view:changed", { view: "map" });
      ctx.events.emit("field:focus", { fieldId: feature.properties.id });
    });

    const dot = el("span", "risk-dot");
    dot.style.background = score === undefined ? "#9e9e9e" : riskColour(score);
    dot.title = score === undefined ? "brak danych o ryzyku" : `ryzyko ${score.toFixed(2)}`;

    const text = el("div", "crop-row-text");
    text.append(el("strong", undefined, feature.properties.name));
    text.append(
      el(
        "span",
        "muted",
        `${feature.properties.crop?.name ?? "brak uprawy"} · ${formatArea(feature.properties.area_ha)}`,
      ),
    );

    const level = riskLevel(score ?? null);
    row.append(dot, text, el("span", "risk-badge", level ? RISK_LABELS[level] : "—"));
    return row;
  };

  ctx.shell.on("view:changed", ({ view }) => {
    if (view === "crops") void load();
  });

  ctx.events.on("risks:updated", () => {
    if (ctx.view === "crops") void load();
  });
}
