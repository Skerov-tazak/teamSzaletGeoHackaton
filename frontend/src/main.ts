// Entry point of the frontend bundle (built to static/frontend/dist/main.js).
// Starts the page: the context, the event buses, the header, the map, the chat and the
// Own data / crops sections (contracts in docs/interfaces.md).

import { api } from "./api/client";
import { loadClock, type AppClock } from "./clock";

// Leaflet's CSS is bundled too (esbuild emits static/frontend/dist/main.css, linked by the template).
import "leaflet/dist/leaflet.css";
import type { AppContext } from "./app-context";
import { EventBus, ShellBus } from "./events";
import type { LayerState } from "./layer-state";
import { initChat } from "./chat";
import { initCrops } from "./crops";
import { initMap } from "./map";
import { initOwnData } from "./own-data";
import { initHeader } from "./ui/header";
import { initAccount } from "./ui/account-dialog";
import { LayersPanel, showClockNote } from "./ui/layers";
import { byId } from "./ui/dom";

async function start(): Promise<void> {
  const events = new EventBus();
  const shell = new ShellBus();
  const clock: AppClock = { today: null, forecastDays: 7 };
  const layers: LayerState = { basemap: "osm", fields: true, risks: true, ownParcels: true };
  const ctx: AppContext = { api, events, shell, clock, view: "map", layers };

  // Build the page first; the platform's date arrives when /api/clock/ answers.
  initHeader(ctx);
  initAccount(ctx);
  initOwnData(ctx);
  initCrops(ctx);
  initChat(ctx);

  // The sidebar starts open; its header button (emitted by LayersPanel) and the floating toggle open/close it.
  const sidebar = byId("layers-sidebar");
  const sidebarToggle = byId<HTMLButtonElement>("layers-toggle");
  const setSidebar = (open: boolean): void => {
    sidebar.classList.toggle("is-open", open);
    sidebarToggle.setAttribute("aria-expanded", open ? "true" : "false");
  };
  shell.on("layers-panel:toggle", () => setSidebar(!sidebar.classList.contains("is-open")));
  shell.on("view:changed", ({ view }) => {
    // Only the map has layers; the panel state itself is kept.
    sidebar.hidden = view !== "map";
    sidebarToggle.hidden = view !== "map";
  });

  const layersPanel = new LayersPanel((state) => {
    Object.assign(layers, state);
    shell.emit("layers:changed", state);
  }, layers, () => shell.emit("layers-panel:toggle", {}));
  showClockNote(clock.today, clock.forecastDays);
  setSidebar(true);

  const mapContainer = byId("map");
  const map = await initMap(mapContainer, ctx);

  shell.on("view:changed", ({ view }) => {
    if (view === "map") map.invalidate();
  });

  // A hidden map has no size: re-measure once the browser has laid the page out.
  window.addEventListener("load", () => map.invalidate());
  requestAnimationFrame(() => map.invalidate());

  layersPanel.update({ ...layers });

  // The demo date comes from the platform; without /api/clock/ the map keeps its neutral colours.
  const platformClock = await loadClock(api);
  ctx.clock = platformClock;
  map.setClock(platformClock);
  showClockNote(platformClock.today, platformClock.forecastDays);
}

void start();