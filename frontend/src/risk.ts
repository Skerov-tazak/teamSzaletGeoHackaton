// Risk colour scale shared by the map, the legend and the charts (score 0-1).
// The cut-offs themselves are still open with the decision engine (docs/database.md -> Open questions).

export type RiskLevel = "low" | "mid" | "high";

export const RISK_COLOURS: Record<RiskLevel, string> = {
  low: "#4caf50",
  mid: "#f9a825",
  high: "#c62828",
};

export const RISK_LABELS: Record<RiskLevel, string> = {
  low: "niskie (0–0,33)",
  mid: "średnie (0,33–0,66)",
  high: "wysokie (> 0,66)",
};

export function riskLevel(score: number | null | undefined): RiskLevel | null {
  if (score === null || score === undefined || Number.isNaN(score)) return null;
  if (score < 0.33) return "low";
  if (score < 0.66) return "mid";
  return "high";
}

export function riskColour(score: number | null | undefined): string {
  const level = riskLevel(score);
  return level ? RISK_COLOURS[level] : "#9e9e9e";
}

export function maxScore(scores: Iterable<number>): number | null {
  let max: number | null = null;
  for (const score of scores) {
    if (max === null || score > max) max = score;
  }
  return max;
}
