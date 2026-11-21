// Small DOM and formatting helpers shared by the modules. Text always goes in as text nodes.

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

/** Days from `a` to `b` (both YYYY-MM-DD). */
export function daysBetween(a: string, b: string): number {
  const toUtc = (iso: string) => {
    const [year, month, day] = iso.split("-").map(Number);
    return Date.UTC(year, month - 1, day);
  };
  return Math.round((toUtc(b) - toUtc(a)) / 86_400_000);
}

export const isIsoDate = (value: string): boolean => /^\d{4}-\d{2}-\d{2}$/.test(value);

/** 2024-05-15 -> 15.05.2024 */
export function formatDate(iso: string): string {
  return isIsoDate(iso) ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : iso;
}

export function formatNumber(value: number, digits = 1): string {
  return value.toLocaleString("pl-PL", { maximumFractionDigits: digits });
}

export function formatPercent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

// --- Polish labels for codes the API returns in English.

const CROP_NAMES: Record<number, string> = { 0: "brak uprawy", 1110: "pszenica", 1130: "kukurydza" };

export function cropName(crop: { code: number; name: string }): string {
  return CROP_NAMES[crop.code] ?? crop.name;
}

export const CATEGORY_LABELS: Record<string, string> = {
  fungal: "choroba grzybowa",
  bacterial: "choroba bakteryjna",
  viral: "choroba wirusowa",
  pest: "szkodnik",
};
