// Page header: the top menu switches between the map and the data sections. The account
// button opens the local account dialog; the assistant button toggles the chat drawer.

import type { AppContext } from "../app-context";
import type { ViewName } from "../events";
import { byId, el } from "../ui/dom";

const VIEWS: ViewName[] = ["map", "crops", "own-data"];

const VIEW_TITLES: Record<ViewName, string> = {
  map: "Mapa",
  crops: "Moje uprawy",
  "own-data": "Own data",
};

export function initHeader(ctx: AppContext): void {
  const nav = byId("main-nav");
  const views: Record<ViewName, HTMLElement> = {
    map: byId("view-map"),
    crops: byId("view-crops"),
    "own-data": byId("view-own-data"),
  };

  const setView = (view: ViewName): void => {
    for (const name of VIEWS) views[name].hidden = name !== view;
    for (const button of nav.querySelectorAll<HTMLButtonElement>("button[data-view]")) {
      const active = button.dataset.view === view;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-current", active ? "page" : "false");
    }
    ctx.view = view;
    document.title = `Field Under Pressure – ${VIEW_TITLES[view]}`;
    byId("layers-sidebar").hidden = view !== "map";
    byId("layers-toggle").hidden = view !== "map";
    if (view === "map") {
      // Leaflet needs a size update after the container is shown again.
      window.dispatchEvent(new Event("resize"));
    }
    ctx.shell.emit("view:changed", { view });
  };

  nav.addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>("button[data-view]");
    if (button?.dataset.view) setView(button.dataset.view as ViewName);
  });

  byId<HTMLButtonElement>("brand-button").addEventListener("click", () => setView("map"));

  byId("layers-toggle").addEventListener("click", () => ctx.shell.emit("layers-panel:toggle", {}));

  observeChatDrawer();

  setView("map");
}

/** The chat toggle stays in the header on every view; its label follows the drawer. */
function observeChatDrawer(): void {
  const drawer = byId("chat-drawer");
  const toggle = byId<HTMLButtonElement>("chat-toggle");
  const sync = (): void => toggle.setAttribute("aria-expanded", drawer.hidden ? "false" : "true");
  new MutationObserver(sync).observe(drawer, { attributes: true, attributeFilter: ["hidden"] });
  sync();
}
