// Risk levels, as in explanation version 1 (docs/database.md): low < 0.33 <= medium < 0.66 <= high.
// Colour by `level` wherever the API gives it; levelOfScore() is only for places that have just a
// score (the season chart's points).

import type { RiskLevel } from "./api/types";

export const LEVELS: readonly RiskLevel[] = ["low", "medium", "high"];

export const CUT_OFFS = { medium: 0.33, high: 0.66 } as const;

export const LEVEL_COLOURS: Record<RiskLevel, string> = {
  low: "#43a047",
  medium: "#f9a825",
  high: "#e53935",
};

export const NO_DATA_COLOUR = "#90a4ae";

export const LEVEL_LABELS: Record<RiskLevel, string> = {
  low: "niskie",
  medium: "średnie",
  high: "wysokie",
};

export function isLevel(value: unknown): value is RiskLevel {
  return value === "low" || value === "medium" || value === "high";
}

export function levelOfScore(score: number): RiskLevel {
  return score < CUT_OFFS.medium ? "low" : score < CUT_OFFS.high ? "medium" : "high";
}

/** The highest of the levels, or null for none. */
export function highestLevel(levels: Iterable<RiskLevel>): RiskLevel | null {
  let best: RiskLevel | null = null;
  for (const level of levels) if (best === null || LEVELS.indexOf(level) > LEVELS.indexOf(best)) best = level;
  return best;
}
