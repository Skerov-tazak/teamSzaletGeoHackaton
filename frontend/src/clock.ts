// The demo's date comes from the platform (`/api/clock/`), never from `new Date()`.

import type { Api } from "./api/client";
import type { Clock } from "./types";

export interface AppClock {
  /** The demo's today (YYYY-MM-DD), or null while unknown (the API has no `/api/clock/` yet). */
  today: string | null;
  forecastDays: number;
}

export async function loadClock(api: Api): Promise<AppClock> {
  try {
    const clock: Clock = await api.getClock();
    return { today: clock.today, forecastDays: clock.forecast_days };
  } catch {
    // The endpoint does not exist yet. Never fall back to the browser's date: the demo
    // replays a past season, and the API is the only source of "today".
    return { today: null, forecastDays: 7 };
  }
}

/** `YYYY-MM-DD` shifted by whole days, without touching the browser's clock. */
export function shiftDate(date: string, days: number): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  parsed.setUTCDate(parsed.getUTCDate() + days);
  return parsed.toISOString().slice(0, 10);
}

/** First day of the season we ask for in charts (the API clamps `to` to today + 7). */
export const SEASON_START = "-01-01";

export function seasonStartOf(date: string): string {
  return `${date.slice(0, 4)}${SEASON_START}`;
}
