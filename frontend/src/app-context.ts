// Map contract shared by main.ts, the map and the field details card
// (docs/interfaces.md -> The map module). main.ts calls initMap() once.

import type { Api } from "./api/client";
import type { AppClock } from "./clock";
import type { EventBus, ShellBus, ViewName } from "./events";
import type { LayerState } from "./layer-state";

export interface AppContext {
  api: Api;
  events: EventBus;
  /** Shell events (views, sidebar, chat drawer). */
  shell: ShellBus;
  clock: AppClock;
  /** The view shown in the content area; main.ts owns it, modules only read it. */
  view?: ViewName;
  /** The layers enabled in the sidebar; read by modules that redraw (own parcels). */
  layers?: LayerState;
}

export interface MapHandle {
  /** Reloads the field and risk layers (the demo date changed or an observation was recorded). */
  reload(): Promise<void>;
  /** Focuses a field and shows its details. */
  focusField(fieldId: number): void;
  /** The newest clock value, kept in sync by main.ts. */
  setClock(clock: AppClock): void;
  /** Re-measures the container (the map view was hidden and is back). */
  invalidate(): void;
}