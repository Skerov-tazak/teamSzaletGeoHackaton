# Map

**Owner:** Kuba

The interactive map of the farm: fields, their crops, their risk per threat, how that risk changes over the season, and the details of a selected field.

## What the rest of the page expects

**One function, `initMap()`,** exported from `frontend/src/map/index.ts`. `main.ts` calls it once.

```ts
export async function initMap(container: HTMLElement, ctx: AppContext): Promise<MapHandle>;
// ctx.api     typed calls to the platform API
// ctx.events  the event bus shared with the chat
// ctx.shell   shell events (sidebar layers, chat drawer)
// ctx.clock   { today, forecastDays }: the demo's date, never new Date()
```

The returned `MapHandle` lets `main.ts` reload the map when the demo date changes, focus a field, and re-measure the container after the map view was hidden:

```ts
interface MapHandle {
  reload(): Promise<void>;
  focusField(fieldId: number): void;
  setClock(clock: AppClock): void;
  invalidate(): void;
}
```

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

## What is built

- **Leaflet** (installed under [`frontend/`](../../package.json)). No framework, no other map library.
- **Base maps** (sidebar, radio): OpenStreetMap via CARTO raster tiles (the OSM Foundation tile server answers 403 to app-hosted requests — see its tile usage policy), OpenTopoMap, Esri World Imagery (orthophoto). Attribution is kept on the map; CARTO is the default because it is meant for app use.
- **Overlays** (sidebar, checkboxes):
  - `fields`: `GET /api/fields/`, click selects a field, tooltip shows the name;
  - `risks`: colour per field = the highest score across threats on `ctx.clock.today` (green < 0.33, amber < 0.66, red ≥ 0.66 — see [`src/risk.ts`](../risk.ts); the same cut-offs as the engine's `explanation.level`, agreed);
  - `ownParcels`: polygons uploaded in *Own data* (purple dashed outline, kept in `localStorage`).
- **Field card** (`details-panel`, top right): name, crop, area; the threats on the demo date with their scores, from `GET /api/fields/{id}/risks/{date}/`; the season chart (one line per threat, solid to today, dashed for the forecast) from `GET /api/fields/{id}/risks/?from={1 Jan of the season}&to={today}`.
- **Empty states**: a missing endpoint (`404`) or a stopped server shows a banner on the map instead of an exception; the map itself still works (base map, own parcels).

## Building

- **Plain TypeScript, no framework.**
- `npm install`, then `npm run build` (typecheck + esbuild) or `npm run watch`. The bundle goes to `frontend/static/frontend/dist/`: `main.js` and `main.css` (Leaflet's stylesheet is bundled too; the template links both). Leaflet's PNG sprites are emitted next to them (`--loader:.png=file`).
- **API types** are written by hand for now in [`src/types.ts`](../types.ts), following [docs/interfaces.md](../../../docs/interfaces.md). When the backend's schema is ready, generate `frontend/src/api/schema.d.ts` with `openapi-typescript` (see interfaces.md) and point the client at it.
- **"Why" panel:** show `explanation` version 1 ([database.md → Explanation, version 1](../../../docs/database.md#explanation-version-1)): `level` for the colour, `summary`, the `drivers` sorted by `effect` (their `label`), `action.text` and, for `treat`, `action.spray_window.date`, `growth_stage.name` and `confidence`. Ignore keys you don't know.
- *Still open:* the engine writes `level` as `medium` while `src/risk.ts` uses `mid` (the frontend switches to `medium`), and the explanation texts are still English (the engine switches to Polish).
