// Small DOM helpers shared by the modules.

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function byId<T extends HTMLElement = HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing element #${id} in the page template`);
  return node as T;
}

export function formatArea(ha: number): string {
  return `${ha.toFixed(1).replace(".", ",")} ha`;
}

export function formatDate(date: string | null): string {
  if (!date) return "—";
  const [year, month, day] = date.split("-");
  return `${day}.${month}.${year}`;
}
