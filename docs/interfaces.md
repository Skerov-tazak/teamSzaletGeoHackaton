# Interfaces

Field Under Pressure · owners: Jan + Szymek · last updated 20 Nov 2026

How the components talk to each other: the frontend modules, the events between map and chat, the platform API, the chat, the assistant's data access and the decision engine. The tables behind all of this are in [database.md](database.md).

## Status

| Piece | Status | Built by |
|-------|--------|----------|
| [Event bus](#events-between-map-and-chat) (`frontend/src/events.ts`) | To build | Jan + Szymek |
| [Page and app context](#frontend-modules) (`main.ts`, `api/`) | To build | Jan + Szymek |
| [Map module](#the-map-module) (`initMap`) | To build | Kuba |
| [Platform API](#platform-api) | `GET /api/health/` exists; the rest to build | Jan + Szymek |
| [Demo date control](#clock) (`PUT /api/clock/` + header control) | To build | Jan + Szymek |
| [Chat endpoints, chat tables, placeholder answer](#chat) | To build | Jan + Szymek |
| [`answer()`](#the-answer-function), MCP tools, RAG | To build | Ola |
| [Read-only database user](#free-form-lookups-read-only-sql) | To build | Jan + Szymek |
| [Observation table](#writing-observations) | Open: columns wait for the engine's needs | Jan + Szymek (schema), Ola (writes), Bartek (reads) |
| [`as_of` on the query helpers](#as_of-on-the-helpers) | To build | Jan + Szymek |
| [`predict()`](#decision-engine) | To build | Bartek |
| [API without authentication](#general-rules) | To build (settings change) | Jan + Szymek |

## General rules

- **No logins, no tokens.** The API is open; it's a single-farm demo. Nothing needs a CSRF token.
- **JSON** with snake_case keys; dates as `YYYY-MM-DD`; timestamps in ISO 8601, UTC.
- **Units** are the database's (source units), under the database column names. See [database.md](database.md#unit-traps).
- **GeoJSON** coordinates are **[lon, lat]**, EPSG:4326.
- **Nothing after the forecast.** The API never returns data after today + 7. A range's `to` is cut off there; a single `date` after it is a 400 error.
- **Errors** use Django REST Framework's format: `{"detail": "..."}` with a 4xx status.
- **TypeScript types are generated, not written.** `openapi-typescript` turns `/api/schema/` into `frontend/src/api/schema.d.ts` (one npm script). If the backend changes, regenerate; the type checker shows what broke.

## Frontend modules

```text
frontend/src/
  main.ts      starts the page: creates the context, mounts chat + map, demo date control
  api/         typed API client + generated types
  events.ts    typed event bus
  chat/        chat window
  map/         map (Kuba)
```

Every module gets the same context and talks to the rest of the page only through it:

```ts
interface AppContext {
  api: Api;                                         // typed calls to the platform API
  events: EventBus;                                 // see below
  clock: { today: string; forecastDays: number };   // updated by main.ts on "date:changed"
}
```

### The map module

The map module exports one function. `main.ts` calls it once with the map's container:

```ts
// frontend/src/map/index.ts
export function initMap(container: HTMLElement, ctx: AppContext): void;
```

The map draws itself inside `container`, loads its data through `ctx.api`, and sends and receives events through `ctx.events`. It never reads the date from `new Date()`: the demo's date is `ctx.clock.today`.

## Events between map and chat

The modules never call each other. They send custom events through one shared, private `EventTarget` (created in `main.ts`, passed in the context; not `document`, so nothing can clash with browser or library events). A typed wrapper makes a wrong event name or payload a type error:

```ts
// frontend/src/events.ts
export interface AppEvents {
  "field:selected": { fieldId: number | null };   // null = no field selected
  "field:focus": { fieldId: number };
  "date:changed": { today: string };
  "risks:updated": { fieldIds: number[] };
}

export class EventBus {
  private target = new EventTarget();

  emit<K extends keyof AppEvents>(type: K, detail: AppEvents[K]): void {
    this.target.dispatchEvent(new CustomEvent(type, { detail }));
  }

  on<K extends keyof AppEvents>(type: K, handler: (detail: AppEvents[K]) => void): () => void {
    const listener = (event: Event) => handler((event as CustomEvent<AppEvents[K]>).detail);
    this.target.addEventListener(type, listener);
    return () => this.target.removeEventListener(type, listener); // call to stop listening
  }
}
```

| Event | Payload | Sent by | Handled by |
|-------|---------|---------|------------|
| `field:selected` | `{ fieldId: number \| null }` | map: the user clicks a field (or empty map: `null`) | chat: shows "Asking about: …" and sends `field_id` with the next message |
| `field:focus` | `{ fieldId: number }` | chat: an answer has `focus_field_id`, or the user clicks a risk citation | map: zooms to and highlights the field, then sends `field:selected` itself |
| `date:changed` | `{ today: "YYYY-MM-DD" }` | `main.ts`, after the demo date control saved the new date | map: reloads; `main.ts` updates `ctx.clock` first |
| `risks:updated` | `{ fieldIds: number[] }` | chat: an answer has `updated_field_ids` (an observation was recorded) | map: reloads those fields |

Events are handled synchronously, in the order they are sent. Selecting a field is always optional: with no field selected, the chat still works.

## Platform API

Built by Jan + Szymek with Django REST Framework. Once an endpoint exists, its exact schema is at <http://localhost:8000/api/docs/>. The examples below are the agreed shapes.

| Request | Returns | Used by |
|---------|---------|---------|
| `GET /api/health/` | `{status, database}` | the page's status line (exists) |
| `GET /api/clock/` | the demo's date | everyone |
| `PUT /api/clock/` | sets the demo's date | demo date control |
| `GET /api/threats/` | every threat | legend, filters |
| `GET /api/fields/` | every field as GeoJSON | map |
| `GET /api/fields/{id}/` | one field's details | field panel |
| `GET /api/risks/?date=` | every field's risks on one day | colouring the map |
| `GET /api/fields/{id}/risks/?from=&to=` | one field's risks over time | season chart |
| `GET /api/fields/{id}/risks/{date}/` | one field's risks on one day, with explanations | "why" panel |
| `GET /api/fields/{id}/weather/?from=&to=` | observed + forecast weather | later, shape not defined yet |

### Clock

```json
// GET /api/clock/
{"today": "2024-05-15", "forecast_days": 7}

// PUT /api/clock/   body: {"today": "2024-06-01"}   → returns the same shape as GET
```

The demo date control in the page header sends the `PUT`; on success `main.ts` updates `ctx.clock` and sends `date:changed`. Risks for the whole season are precomputed by the seed (see [Decision engine](#decision-engine)), so moving the date is instant.

### Threats

```json
// GET /api/threats/
[
  {"code": "wheat.septoria_leaf_blotch", "name": "septorioza paskowana liści pszenicy",
   "crop": {"code": 1110, "name": "Wheat"}, "category": "fungal"}
]
```

### Fields

```json
// GET /api/fields/
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": 3,
      "geometry": {"type": "Polygon", "coordinates": [[[19.95, 50.03], [19.96, 50.03], [19.96, 50.04], [19.95, 50.03]]]},
      "properties": {"id": 3, "name": "North field", "crop": {"code": 1110, "name": "Wheat"}, "area_ha": 20.4}
    }
  ]
}
```

```json
// GET /api/fields/3/
{
  "id": 3,
  "name": "North field",
  "crop": {"code": 1110, "name": "Wheat"},
  "area_ha": 20.4,
  "centroid": {"lat": 50.035, "lon": 19.955},
  "weather_grid_id": "…",
  "crop_history": [
    {"year": 2023, "classes": [{"code": 1130, "name": "Maize", "share": 0.92}, {"code": 0, "name": "No cropland", "share": 0.08}]}
  ],
  "soil": {"ph": 6.4, "soil_texture": "silt loam", "clay": 18.2, "sand": 21.0, "silt": 60.8, "om": 24.1, "cec": 14.3, "bulk_density": 1.32}
}
```

`soil` holds the root-zone columns of [SoilCell](database.md#soilcell), averaged over the field's cells, in the same units.

### Risks

```json
// GET /api/risks/?date=2024-05-15        (date defaults to today; at most today + 7)
{"date": "2024-05-15", "risks": [{"field_id": 3, "threat_code": "wheat.septoria_leaf_blotch", "score": 0.72}]}
```

```json
// GET /api/fields/3/risks/?from=2024-04-01&to=2024-05-22     (to is cut off at today + 7)
{
  "field_id": 3, "from": "2024-04-01", "to": "2024-05-22",
  "threats": [{"threat_code": "wheat.septoria_leaf_blotch", "points": [{"date": "2024-04-01", "score": 0.1}]}]
}
```

```json
// GET /api/fields/3/risks/2024-05-15/
{
  "field_id": 3, "date": "2024-05-15",
  "risks": [
    {"threat": {"code": "wheat.septoria_leaf_blotch", "name": "septorioza paskowana liści pszenicy", "category": "fungal"},
     "score": 0.72, "explanation": {}}
  ]
}
```

Scores are 0–1. Days up to today are the season so far; today + 1 … today + 7 are the coming days. The `explanation` format is still open ([database.md](database.md#open-questions)).

## Chat

Chats are stored like in any chat app. The HTTP endpoints, the tables and a placeholder answer are built by Jan + Szymek, so the chat window works before the assistant is ready. Ola replaces the placeholder with [`answer()`](#the-answer-function).

### Endpoints

```json
// POST /api/chat/
{"conversation_id": 12, "message": "Why is the north field at risk?", "field_id": 3}
// conversation_id: null starts a new conversation
// field_id: null when no field is selected
```

```json
// response
{
  "conversation_id": 12,
  "message": {
    "id": 57,
    "role": "assistant",
    "text": "Markdown answer…",
    "citations": [
      {"type": "guide", "document": "metodyka_-_PSZENICA_-_www.pdf", "page": 34},
      {"type": "risk", "field_id": 3, "threat_code": "wheat.septoria_leaf_blotch", "date": "2024-05-15"}
    ],
    "focus_field_id": null,
    "updated_field_ids": [],
    "created_at": "2024-05-15T10:42:00Z"
  }
}
```

| Request | Returns |
|---------|---------|
| `POST /api/chat/` | sends a message, returns the assistant's answer (above) |
| `GET /api/chat/conversations/` | `[{id, title, updated_at}]`, newest first. The title is the start of the first message |
| `GET /api/chat/conversations/{id}/` | `{id, title, messages: [...]}`, each message in the shape above (user messages have empty `citations`) |

**Citations** are agreed by Jan + Szymek; **Ola to confirm.** Two types:

- `guide`: a passage of a guide PDF. `document` is the file name in `field-under-pressure-materials/metodyki/`, `page` is the page number (1-based).
- `risk`: a risk row the answer relies on (`field_id`, `threat_code`, `date`). The chat shows it as a link; clicking it sends `field:focus`.

**Not in this version:** charts (maybe a separate endpoint later) and streaming. The answer appears all at once after a "thinking…" indicator.

**In the browser:** the user's message appears immediately, then the indicator, then the answer. The markdown is turned into HTML and sanitised (DOMPurify) before it goes into the page; the model's output is never inserted as raw HTML. `focus_field_id` → `field:focus`; `updated_field_ids` → `risks:updated`.

### Chat tables

They live in the `assistant` app, not `core`: they are specific to the assistant, so Ola owns them. Jan + Szymek create the first version; after that only Ola changes them.

| Table | Columns |
|-------|---------|
| `Conversation` | `title`, `created_at`, `updated_at` |
| `Message` | `conversation`, `role` (`user` / `assistant`), `text`, `citations` (JSON), `field` (the field selected when sent, nullable), `focus_field` (nullable), `created_at` |

### The `answer()` function

Everything the assistant does (prompts, RAG, MCP tools) sits behind one function that Ola implements. The platform calls it from `POST /api/chat/`:

```python
# assistant/answer.py (Ola)
from dataclasses import dataclass, field as dataclass_field

from assistant.models import Conversation
from core.models import Field


@dataclass
class Reply:
    text: str                                                    # markdown
    citations: list[dict] = dataclass_field(default_factory=list)
    focus_field_id: int | None = None
    updated_field_ids: list[int] = dataclass_field(default_factory=list)


def answer(conversation: Conversation, message: str, selected_field: Field | None) -> Reply:
    ...
```

The platform saves the user's message before calling `answer()` (it is the last message in `conversation`) and saves the reply afterwards.

## The assistant's data access

Ola owns everything MCP: which tools exist, what they allow and what they refuse. The platform provides two pieces of infrastructure for it.

### Free-form lookups: read-only SQL

For questions no specific tool covers, the assistant can run **SQL**, never ORM code. ORM queries are Python, and running model-written Python is running arbitrary code. SQL through a read-only database user is safe because Postgres enforces it:

- a separate database user that can only `SELECT` from the platform tables;
- every query stopped after a time limit (e.g. 2 s);
- results capped (e.g. 500 rows).

The platform adds the user and a second database connection, `readonly`, in the settings. The MCP tool runs queries only through `django.db.connections["readonly"]`.

### Writing observations

The assistant changes data only through narrow tools, for example "record an observation". Observations go into an `Observation` table in `core` (farm data that the engine reads); its columns wait for the engine's needs. After recording one, the tool calls `engine.predict(field_ids=[field.id], start=observation_date)` and the answer returns that field in `updated_field_ids`, so the map reloads it.

## Decision engine

The engine exposes one function. It computes risks and writes them all at once, overwriting earlier ones:

```python
# engine (Bartek)
def predict(field_ids: list[int] | None = None, start: date | None = None, end: date | None = None) -> int:
    """
    Compute risks for the given fields (default: all) from start to end (default: the whole
    season up to today + 7), and overwrite them in the Risk table in one bulk write.
    Returns the number of rows written.
    """
```

It works through the days in order, each one **as of that day**: only the weather observed up to that day, plus the forecast issued that day. It can be called from anywhere:

| When | Call |
|------|------|
| After the seed / import | `predict()` over the whole season, so moving the demo date is instant |
| After an observation is recorded | `predict(field_ids=[field.id], start=observation_date)` |
| By hand | a management command, e.g. `python manage.py predict` |

### `as_of` on the helpers

`.observed()` and `.current()` cut at the clock's today, which would stop `predict()` from working through a whole season. So they get an optional `as_of` date that defaults to `clock.today()`:

```python
WeatherDaily.objects.observed(as_of=day)          # weather up to that day
WeatherForecastDaily.objects.current(as_of=day)   # the forecast issued that day
```

Only the engine passes `as_of`; everyone else calls the helpers without it.
