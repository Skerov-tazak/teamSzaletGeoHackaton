// Small DOM and date helpers for the page and the chat (the map has its own, in map/format.ts).

type Child = Node | string | number | null | undefined | false;
type Attrs = Record<string, string | number | boolean | null | undefined | EventListener>;

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Attrs = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") element.addEventListener(key.slice(2), value);
    else if (key === "class") element.className = String(value);
    else element.setAttribute(key, value === true ? "" : String(value));
  }
  append(element, ...children);
  return element;
}

export function append(parent: Node & ParentNode, ...children: Child[]): void {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    parent.append(typeof child === "number" ? String(child) : child);
  }
}

// --- Dates as YYYY-MM-DD strings. Never the browser's own date: the demo's date comes from the API.

/** The date `days` after a YYYY-MM-DD date (pure calendar arithmetic). */
export function shiftDate(iso: string, days: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

export const isIsoDate = (value: string): boolean => /^\d{4}-\d{2}-\d{2}$/.test(value);

/** 2024-05-15 -> 15.05.2024 */
export function formatDate(iso: string): string {
  return isIsoDate(iso) ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : iso;
}
