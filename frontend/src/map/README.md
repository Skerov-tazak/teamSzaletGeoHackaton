# Map

**Owner:** Kuba

The interactive map of the farm: fields, their crops, their risk per threat, how that risk changes over the season, and the details of a selected field.

## What the rest of the page expects

**One function, `initMap()`,** exported from `frontend/src/map/index.ts`. `main.ts` calls it once. Details: [docs/interfaces.md → Frontend modules](../../../docs/interfaces.md#frontend-modules).

```ts
export function initMap(container: HTMLElement, ctx: AppContext): void;
// ctx.api     typed calls to the platform API
// ctx.events  the event bus shared with the chat
// ctx.clock   { today, forecastDays }: the demo's date, never new Date()
```

The map draws itself inside `container` and talks to the rest of the page only through `ctx`.

**Events** ([docs/interfaces.md → Events](../../../docs/interfaces.md#events-between-map-and-chat)):

| You send | When |
|----------|------|
| `field:selected` `{ fieldId }` | the user clicks a field; `{ fieldId: null }` when they click empty map |

| You handle | What to do |
|------------|------------|
| `field:focus` `{ fieldId }` | zoom to and highlight the field, then send `field:selected` for it |
| `date:changed` `{ today }` | reload the risks for the new date (`ctx.clock` is already updated) |
| `risks:updated` `{ fieldIds }` | reload those fields' risks |

**Data** ([docs/interfaces.md → Platform API](../../../docs/interfaces.md#platform-api), example responses included):

- `GET /api/fields/`: every field as GeoJSON (EPSG:4326, coordinates **[lon, lat]**), with name, crop and area;
- `GET /api/risks/?date=`: every field's risk per threat on one day, for colouring;
- `GET /api/fields/{id}/`, `/risks/?from=&to=`, `/risks/{date}/`: details, the season chart and the "why" panel;
- `GET /api/threats/`: names and categories for the legend.

Risk scores are 0–1. "Season so far" is up to today; "coming days" are today + 1 … today + 7. The API never returns anything later ([why and how](../../../docs/interfaces.md#no-data-after-the-forecast)), so you don't need your own checks; to see later days, the demo date has to move.

## Building

- **Plain TypeScript, no framework.** Map libraries (Leaflet, MapLibre, …) are fine: install them with `npm install` in [`frontend/`](../../), and esbuild bundles them into `static/frontend/dist/main.js`.
- **API types are generated** from the backend's schema, so they always match it; don't write them by hand.
- **Colours and the "why" panel** come from `explanation` version 1 ([database.md → Explanation, version 1](../../../docs/database.md#explanation-version-1)): `level` for the colour (`low` / `medium` / `high`, cut-offs 0.33 / 0.66, agreed), `summary`, the `drivers` sorted by `effect` (their `label`), `action.text` and, for `treat`, `action.spray_window.date`, `growth_stage.name` and `confidence`. Ignore keys you don't know.
- *Still open:* the explanation texts are still English (the engine switches to Polish).

## Development (until the platform API exists)

The module above is built: [`index.ts`](index.ts) (`initMap`), [`panel.ts`](panel.ts) (field panel and "why"),
[`chart.ts`](chart.ts) (season chart), [`map.css`](map.css). It follows this README and interfaces.md exactly;
nothing outside `map/` is needed except [`../events.ts`](../events.ts), the `EventBus` copied verbatim from
interfaces.md.

**Running it without the platform API:**

```bash
python manage.py engine_dev_seed --season 2024 --today 2024-06-15 --crop-from-map --fields-per-crop 2
python manage.py predict --season
cd frontend && npm install && npm run map:dev     # or map:watch
python manage.py engine_mock_api                  # http://127.0.0.1:8001/
```

`engine_mock_api` (development only, not wired into Django's URLs) answers the agreed endpoints with exactly the
agreed shapes and rules (cut-off at today + 7, `{"detail"}` errors), from the real database; `PUT /api/clock/`
calls `engine.clock_moved()`. [`dev/`](dev/) is a stand-in page: it builds the `AppContext`, has the demo date
control (what `main.ts` will do) and buttons that send the chat's events. Its tests: `engine/test_mock_api.py`.

**What changes when the platform's pieces land (nothing in the map's behaviour):**

- **Types:** [`contract.ts`](contract.ts) holds the response types written from interfaces.md's examples. Once
  `api/schema.d.ts` is generated, import the types from there and delete them here.
- **`ctx.api`:** the map calls `getThreats()`, `getFields()`, `getField(id)`, `getRisks(date)`,
  `getFieldRisks(id, {from, to})`, `getFieldDayRisks(id, date)` (`MapApi` in `contract.ts`), one per agreed endpoint.
  If `api/client.ts` names them differently, only these calls change.
- **`level` in `/api/risks/?date=`** (implementation-plan decision 10): used when present; until then the colour
  comes from the score with the agreed cut-offs, which is the same level by construction.
