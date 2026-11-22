// Entry point of the frontend bundle (built to static/frontend/dist/main.js).
// Creates the event bus and the context, loads the demo date, mounts the chat and the map once, and
// runs the demo date control (docs/interfaces.md -> Frontend modules).

import { Api, errorMessage } from "./api/client";
import type { Clock } from "./api/types";
import { initChat } from "./chat";
import type { AppContext } from "./context";
import { initDateControl } from "./date-control";
import { h } from "./dom";
import { EventBus } from "./events";
import { initMap } from "./map";

function byId(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (!element) throw new Error(`#${id} is missing from the page template`);
  return element;
}

function setStatus(element: HTMLElement, text: string, state: "ok" | "error" | "busy"): void {
  element.textContent = text;
  element.title = text; // the header may cut a long message short
  element.dataset.state = state;
}

async function showPlatformStatus(api: Api, element: HTMLElement): Promise<void> {
  try {
    const health = await api.health();
    if (health.database) setStatus(element, "Platforma OK", "ok");
    else setStatus(element, "Brak połączenia z bazą danych. Czy działa docker compose up -d?", "error");
  } catch (error) {
    setStatus(element, `Platforma niedostępna: ${errorMessage(error)}`, "error");
  }
}

async function start(): Promise<void> {
  const status = byId("platform-status");
  const main = byId("app-main");
  const api = new Api();
  const events = new EventBus();

  // Safety net: an error nobody caught still becomes a visible message, never a silent failure.
  window.addEventListener("unhandledrejection", (event) => {
    event.preventDefault();
    setStatus(status, `Błąd: ${errorMessage(event.reason)}`, "error");
  });

  void showPlatformStatus(api, status);

  let clock: Clock;
  try {
    clock = await api.getClock();
  } catch (error) {
    // No date, no date-dependent requests (and never the browser's date).
    setStatus(status, "Nie można wczytać daty demo", "error");
    main.replaceChildren(
      h(
        "div",
        { class: "page-error" },
        h("h2", {}, "Nie można wczytać daty demo"),
        h("p", {}, errorMessage(error)),
        h("p", {}, "Ustaw datę w /admin/ (Platform → Clocks) albo uruchom seed, a potem odśwież stronę."),
      ),
    );
    return;
  }

  const ctx: AppContext = { api, events, clock: { today: clock.today, forecastDays: clock.forecast_days } };

  initDateControl(byId("date-control"), ctx, (saved) => {
    // Update the object the modules already hold, then tell them.
    ctx.clock.today = saved.today;
    ctx.clock.forecastDays = saved.forecast_days;
    events.emit("date:changed", { today: saved.today });
  });

  initChat(byId("chat"), ctx);
  initMap(byId("map"), ctx);
}

void start();
