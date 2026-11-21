// Typed events between the map and the chat, exactly as in docs/interfaces.md
// (Events between map and chat), plus the shell events main.ts uses to talk to its views.
// The modules never call each other; they send custom events through one private EventTarget
// (not document, so nothing can clash with browser or library events).

import type { LayerState } from "./layer-state";

export type ViewName = "map" | "crops" | "own-data";

export interface AppEvents {
  "field:selected": { fieldId: number | null }; // null = no field selected
  "field:focus": { fieldId: number };
  "date:changed": { today: string };
  "risks:updated": { fieldIds: number[] };
}

/** Events of the app shell (header, sidebar, chat drawer). */
export interface ShellEvents {
  "layers:changed": LayerState;
  "layers-panel:toggle": Record<string, never>;
  "chat:toggle": { open: boolean };
  "view:changed": { view: ViewName };
  "user:changed": { name: string | null };
}

export class EventBus {
  private target = new EventTarget();

  emit<K extends keyof AppEvents>(type: K, detail: AppEvents[K]): void {
    this.target.dispatchEvent(new CustomEvent(type, { detail }));
  }

  on<K extends keyof AppEvents>(type: K, handler: (detail: AppEvents[K]) => void): () => void {
    const listener = (event: Event) => handler((event as CustomEvent<AppEvents[K]>).detail);
    this.target.addEventListener(type, listener);
    return () => this.target.removeEventListener(type, listener);
  }
}

/** Same bus, typed with the shell events. main.ts owns both instances. */
export class ShellBus {
  private target = new EventTarget();

  emit<K extends keyof ShellEvents>(type: K, detail: ShellEvents[K]): void {
    this.target.dispatchEvent(new CustomEvent(type, { detail }));
  }

  on<K extends keyof ShellEvents>(type: K, handler: (detail: ShellEvents[K]) => void): () => void {
    const listener = (event: Event) => handler((event as CustomEvent<ShellEvents[K]>).detail);
    this.target.addEventListener(type, listener);
    return () => this.target.removeEventListener(type, listener);
  }
}