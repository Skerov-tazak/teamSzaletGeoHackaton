// Development page for the map module (served by `python manage.py engine_mock_api`, or by Django once the
// platform API exists). It does what main.ts and the chat will do, nothing more:
//   - builds the AppContext of interfaces.md: { api, events, clock } (clock from GET /api/clock/);
//   - the demo date control: PUT /api/clock/ -> update ctx.clock in place -> send date:changed;
//   - stands in for the chat: sends field:focus and risks:updated, logs field:selected.
// Not part of the product: main.ts (Jan + Szymek) replaces it.

import { EventBus } from "../../events";
import type { AppContext, MapApi } from "../contract";
import { addDays, longDate } from "../format";
import { initMap } from "../index";
import "./harness.css";

class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { headers: { Accept: "application/json", "Content-Type": "application/json" }, ...init });
  } catch {
    throw new ApiError(0, "serwer nie odpowiada");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, (body as { detail?: string }).detail ?? res.statusText);
  return body as T;
}

const qs = (params: Record<string, string | undefined>) => {
  const p = Object.entries(params).filter(([, v]) => v);
  return p.length ? `?${new URLSearchParams(p as [string, string][])}` : "";
};

/** One call per agreed endpoint (interfaces.md → Platform API). */
const api: MapApi & { getClock(): Promise<{ today: string; forecast_days: number }>; putClock(today: string): Promise<{ today: string; forecast_days: number }> } = {
  getClock: () => request("/api/clock/"),
  putClock: (today) => request("/api/clock/", { method: "PUT", body: JSON.stringify({ today }) }),
  getThreats: () => request("/api/threats/"),
  getFields: () => request("/api/fields/"),
  getField: (id) => request(`/api/fields/${id}/`),
  getRisks: (date) => request(`/api/risks/${qs({ date })}`),
  getFieldRisks: (id, range) => request(`/api/fields/${id}/risks/${qs({ from: range?.from, to: range?.to })}`),
  getFieldDayRisks: (id, date) => request(`/api/fields/${id}/risks/${date}/`),
};

const $ = <T extends HTMLElement>(sel: string) => document.querySelector<T>(sel)!;
const log = (line: string) => {
  const li = document.createElement("li");
  li.textContent = line;
  $("#event-log").prepend(li);
};

async function start(): Promise<void> {
  const events = new EventBus();
  let clockRow: { today: string; forecast_days: number };
  try {
    clockRow = await api.getClock();
  } catch (e) {
    $("#date-label").textContent = `Brak daty demo: ${(e as ApiError).detail}`;
    return;
  }
  const ctx: AppContext = { api, events, clock: { today: clockRow.today, forecastDays: clockRow.forecast_days } };

  // the date control, as main.ts will do it
  const input = $<HTMLInputElement>("#date-input");
  const label = $("#date-label");
  const control = $("#date-control");
  const show = () => {
    input.value = ctx.clock.today;
    label.textContent = longDate(ctx.clock.today);
  };
  const move = async (today: string) => {
    if (!today || today === ctx.clock.today) return show();
    control.classList.add("busy");
    control.querySelectorAll("button, input").forEach((el) => ((el as HTMLInputElement).disabled = true));
    try {
      const row = await api.putClock(today);
      ctx.clock.today = row.today;            // in place: the modules hold the same object
      ctx.clock.forecastDays = row.forecast_days;
      events.emit("date:changed", { today: row.today });
      log(`date:changed → ${row.today}`);
    } catch (e) {
      log(`PUT /api/clock/ nie powiódł się: ${(e as ApiError).detail}`);
    } finally {
      control.classList.remove("busy");
      control.querySelectorAll("button, input").forEach((el) => ((el as HTMLInputElement).disabled = false));
      show();
    }
  };
  $("#date-prev").addEventListener("click", () => void move(addDays(ctx.clock.today, -1)));
  $("#date-next").addEventListener("click", () => void move(addDays(ctx.clock.today, 1)));
  $("#date-week").addEventListener("click", () => void move(addDays(ctx.clock.today, 7)));
  input.addEventListener("change", () => void move(input.value));
  show();

  // the chat's side of the events
  events.on("field:selected", ({ fieldId }) => {
    log(`field:selected ← ${fieldId ?? "null"}`);
    $("#asking").textContent = fieldId == null ? "Pytasz o całe gospodarstwo" : `Pytasz o pole #${fieldId}`;
  });
  const fields = await api.getFields().catch(() => null);
  const pick = $<HTMLSelectElement>("#chat-field");
  pick.innerHTML = (fields?.features ?? []).map((f) => `<option value="${f.id}">${f.properties.name}</option>`).join("");
  $("#chat-focus").addEventListener("click", () => {
    const id = Number(pick.value);
    log(`field:focus → ${id}`);
    events.emit("field:focus", { fieldId: id });
  });
  $("#chat-updated").addEventListener("click", () => {
    const id = Number(pick.value);
    log(`risks:updated → [${id}]`);
    events.emit("risks:updated", { fieldIds: [id] });
  });

  initMap($("#map"), ctx);
}

void start();
