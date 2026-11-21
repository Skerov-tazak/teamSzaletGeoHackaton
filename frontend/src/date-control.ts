// The demo date control in the header: a date input and ±1 day buttons -> PUT /api/clock/.
// Moving the date makes the engine recompute risks, which can take seconds, so the control is
// disabled and shows that it is working until the request returns.

import { errorMessage } from "./api/client";
import type { Clock } from "./api/types";
import type { AppContext } from "./context";
import { h, isIsoDate, shiftDate } from "./dom";

const TYPING_PAUSE_MS = 700; // the input fires "change" for every typed part of a date

export function initDateControl(container: HTMLElement, ctx: AppContext, onSaved: (clock: Clock) => void): void {
  const input = h("input", { type: "date", value: ctx.clock.today, "aria-label": "Data demo" });
  const back = h("button", { type: "button", title: "Dzień wcześniej", "aria-label": "Dzień wcześniej" }, "◀");
  const next = h("button", { type: "button", title: "Dzień później", "aria-label": "Dzień później" }, "▶");
  const status = h("span", { class: "date-status", role: "status" });
  container.replaceChildren(h("span", { class: "date-label" }, "Data demo"), back, input, next, status);

  let busy = false;
  let pending: number | undefined;

  const setBusy = (value: boolean) => {
    busy = value;
    for (const control of [input, back, next]) control.disabled = value;
    container.classList.toggle("busy", value);
  };

  const save = async (today: string) => {
    window.clearTimeout(pending);
    if (busy || !isIsoDate(today) || today === ctx.clock.today) return;
    setBusy(true);
    status.textContent = "Przeliczanie ryzyk…";
    status.dataset.state = "busy";
    try {
      const clock = await ctx.api.putClock(today);
      onSaved(clock);
      status.textContent = "";
      delete status.dataset.state;
    } catch (error) {
      status.textContent = `Nie zmieniono daty: ${errorMessage(error)}`;
      status.dataset.state = "error";
    } finally {
      input.value = ctx.clock.today;
      setBusy(false);
    }
  };

  input.addEventListener("change", () => {
    window.clearTimeout(pending);
    pending = window.setTimeout(() => void save(input.value), TYPING_PAUSE_MS);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") void save(input.value);
  });
  back.addEventListener("click", () => void save(shiftDate(ctx.clock.today, -1)));
  next.addEventListener("click", () => void save(shiftDate(ctx.clock.today, 1)));
}
