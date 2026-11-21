# AGENTS.md

Guidance for coding agents working in **Field Under Pressure — team Szalet**.
Read this first, then the document that owns the area you touch.

## What this project is

A farmer dashboard for maize and winter wheat: an interactive map of the farm's fields with crop
risk per threat, plus an AI assistant grounded in the official crop-protection guides.
The demo replays a past season. See [architecture_overview.md](architecture_overview.md) and
[README.md](README.md).

## Repo map and owners

| Area | Folder | Owner | You may change it? |
|------|--------|-------|--------------------|
| Platform: models, migrations, API, import | [`core/`](core/), [`fieldpressure/`](fieldpressure/) | Jan + Szymek | Only when the task says so; no new migrations without them |
| Frontend shell, chat window, Own data, crops | [`frontend/`](frontend/) (except `src/map/`) | Jan + Szymek | Yes |
| Map | [`frontend/src/map/`](frontend/src/map/) | Kuba | Yes (owner has a skill; keep its README in sync) |
| Decision engine | [`engine/`](engine/) | Bartek | Only with the task's scope |
| AI assistant (chat tables, RAG, MCP) | [`assistant/`](assistant/) | Ola | Only the chat tables and `answer()` |
| Contracts, DB documentation | [`docs/interfaces.md`](docs/interfaces.md), [`docs/database.md`](docs/database.md) | Jan + Szymek | Update when you change a contract |

Organiser materials are a git submodule ([`field-under-pressure-materials/`](field-under-pressure-materials/));
never edit or download datasets into the repo.

## Hard rules

1. **Never use `date.today()` or `new Date()` for the demo date.** The demo replays a past season.
   Python: `core.clock.today()`. Frontend: `ctx.clock.today`, loaded from `GET /api/clock/` —
   never the browser clock.
2. **Read weather only through the helpers:** `WeatherDaily.objects.observed()` and
   `WeatherForecastDaily.objects.current()` (they take `as_of` only for the engine).
3. **Nothing after today + 7** may reach the frontend; the API enforces it, the UI must not invent dates.
4. **Units are source units** (wind in km/h, humidity 0–100 %, cloud cover 0–1, area in ha).
   Convert in your own code, never in the database.
5. **No logins, no tokens** for the platform API — it is an open single-farm demo.
   The frontend account is a *local* (`localStorage`) shell only; it must not block any section.
6. **Never commit secrets or data.** Keys go in `.env`, datasets in `DATA_DIR` (outside the repo).
7. **Work in your own folder** and keep the documentation of that component current.

## Frontend (main working area)

### Stack

Plain TypeScript + esbuild, **no framework**. Leaflet for the map, `marked` + `DOMPurify` for chat
markdown. One Django template renders the page; the bundle adds behaviour.

```text
frontend/templates/frontend/index.html   the whole page (ids are the JS contract)
frontend/static/frontend/style.css       app styles — plain CSS, no preprocessor
frontend/src/main.ts                     bootstrap: context, buses, header, map, chat, sections
frontend/src/app-context.ts              AppContext / MapHandle types
frontend/src/api/client.ts               typed fetch client (ApiError carries the status)
frontend/src/types.ts                    response shapes from docs/interfaces.md
frontend/src/events.ts                   EventBus (map↔chat) and ShellBus (shell events)
frontend/src/layer-state.ts              sidebar layer switches
frontend/src/clock.ts                    demo date loader (never new Date())
frontend/src/risk.ts                     score → colour scale shared by map and legend
frontend/src/account.ts                  local account (localStorage, SHA-256 of the password)
frontend/src/chat/                       chat drawer + conversation history
frontend/src/crops/                      "Moje uprawy" list
frontend/src/own-data/                   upload tab + stored parcels (localStorage)
frontend/src/map/                        map (Kuba): layers, field card, own parcels
frontend/src/ui/                         header, layers panel, account dialog, DOM helpers
```

### Commands

```powershell
cd frontend
npm install            # once
npm run build          # typecheck (tsc --noEmit) + esbuild -> static/frontend/dist/
npm run typecheck      # types only
npm run watch          # rebuild on save
```

Backend: `.venv\Scripts\python.exe manage.py runserver` after `docker compose up -d` and
`manage.py migrate`. The template links `static/frontend/dist/main.css` (Leaflet's stylesheet is
bundled there) and `main.js`, so **rebuild after editing `src/`**; editing `style.css` or the
template needs only a page reload.

### Architecture rules

- `main.ts` owns the `AppContext` (`api`, `events`, `shell`, `clock`, `view`, `layers`) and passes it
  to modules. Modules never import each other's internals.
- Map ↔ chat talk **only** through `EventBus`: `field:selected`, `field:focus`, `date:changed`,
  `risks:updated`. Shell events (`view:changed`, `layers:changed`, `layers-panel:toggle`,
  `chat:toggle`, `user:changed`) go through `ShellBus`.
- DOM access uses ids from the template via `byId()` / `el()` from `src/ui/dom.ts`.
  When you add or rename an id, update the template and JS in the same change.
- Chat answers are markdown: always `DOMPurify.sanitize(marked.parse(text))`. Never inject raw HTML.
- API shapes are written in `src/types.ts` following `docs/interfaces.md`; when the backend learns to
  emit an OpenAPI schema, generate `frontend/src/api/schema.d.ts` with `openapi-typescript`.
- A missing endpoint must degrade to a visible empty/error state (see `humaniseError`), never to an
  unhandled rejection that stops `start()` from finishing.
- UI copy is Polish; code, comments and docs are English.

### Layout expectations

- Header: brand left, **navigation centred horizontally**, account + *Asystent* right.
- Layers panel: slides in from the left over the map; opens with `☰ Warstwy`, closes with `‹`.
- Chat: drawer on the right, opened by *Asystent*, `Esc` closes it.
- Sections *Moje uprawy* and *Own data* open freely (no account gate).

## Definition of done

- `npm run build` passes (strict TypeScript, no errors).
- If a page id changed: `byId` lookups in JS still resolve (every id used in `src/` exists in the template).
- If a contract changed: `docs/interfaces.md` and the component README (`frontend/src/map/README.md`
  for the map) are updated.
- No `new Date()` for demo data, no secrets, no committed build artefacts beyond the ignored ones.

## Environment notes (Windows)

- `.venv` is at the repo root; Postgres comes from `docker compose up -d` on port **5433**.
- Without a database the server fails after `System check identified no issues`; the frontend cannot
  render. Start Docker first.
- Node is used only as an npm driver (`npm`/`npx` resolve through `node` on `PATH`). If `node` is not
  on `PATH`, install Node 18+ (or use `fnm use 22`).