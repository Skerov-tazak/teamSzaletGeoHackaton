// The demo date control in the header: ‹ [date] › +7 dni -> PUT /api/clock/. The date box opens the
// browser's date picker. Moving the date makes the engine recompute risks, which can take seconds, so the
// control is disabled and shows that it is working until the request returns.

import { errorMessage } from "./api/client";
import type { Clock } from "./api/types";
import type { AppContext } from "./context";
import { h, isIsoDate, longDate, shiftDate } from "./dom";

const TYPING_PAUSE_MS = 700; // the input fires "change" for every typed part of a date

export function initDateControl(container: HTMLElement, ctx: AppContext, onSaved: (clock: Clock) => void): void {
  const label = h("span", { class: "date-label" });
  const input = h("input", { type: "date", value: ctx.clock.today, "aria-label": "Wybierz datę demo" });
  const box = h("label", { class: "date-box", title: "Zmień datę demo" }, label, input);
  const back = h("button", { type: "button", class: "step", title: "Dzień wcześniej", "aria-label": "Dzień wcześniej" }, "‹");
  const next = h("button", { type: "button", class: "step", title: "Dzień później", "aria-label": "Dzień później" }, "›");
  const week = h("button", { type: "button", class: "wide", title: "Tydzień później" }, "+7 dni");
  const status = h("span", { class: "date-status", role: "status" });
  container.replaceChildren(back, box, next, week, status);

  let busy = false;
  let pending: number | undefined;

  const show = () => {
    input.value = ctx.clock.today;
    label.textContent = longDate(ctx.clock.today);
  };

  const setBusy = (value: boolean) => {
    busy = value;
    for (const control of [input, back, next, week]) control.disabled = value;
    container.classList.toggle("busy", value);
    container.setAttribute("aria-busy", String(value));
  };

  const save = async (today: string) => {
    window.clearTimeout(pending);
    if (busy || !isIsoDate(today) || today === ctx.clock.today) return show();
    setBusy(true);
    label.textContent = longDate(today);
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
      setBusy(false);
      show();
    }
  };

  input.addEventListener("change", () => {
    window.clearTimeout(pending);
    pending = window.setTimeout(() => void save(input.value), TYPING_PAUSE_MS);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") void save(input.value);
  });
  // a click anywhere on the box opens the picker (the input itself is invisible, on top of the label)
  input.addEventListener("click", () => {
    try {
      input.showPicker();
    } catch {
      // older browsers: the focused input still takes typing
    }
  });
  back.addEventListener("click", () => void save(shiftDate(ctx.clock.today, -1)));
  next.addEventListener("click", () => void save(shiftDate(ctx.clock.today, 1)));
  week.addEventListener("click", () => void save(shiftDate(ctx.clock.today, 7)));
  show();
}
