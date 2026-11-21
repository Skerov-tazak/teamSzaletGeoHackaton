# Field Under Pressure — team Szalet

Farmer dashboard for maize and winter wheat: a map of a farm's fields and their crop risks, plus an AI assistant grounded in the official crop-protection guides. See [architecture_overview.md](architecture_overview.md) for the components and how they fit together.

Hackathon: [Field Under Pressure](https://geo-hackathon.g.location360.ag/), 20–22 Nov 2026.

## Team

| Component | Owner | Folder |
|-----------|-------|--------|
| Platform (database, backend, data import, API) | Jan + Szymek | [`core/`](core/), [`fieldpressure/`](fieldpressure/) |
| Frontend | Jan + Szymek | [`frontend/`](frontend/) |
| Map | Kuba | [`frontend/src/map/`](frontend/src/map/) |
| Decision engine | Bartek | [`engine/`](engine/) |
| AI assistant | Ola | [`assistant/`](assistant/) |

## Documentation

| Document | What's in it |
|----------|--------------|
| [architecture_overview.md](architecture_overview.md) | The product, the five components and how they work together |
| [docs/database.md](docs/database.md) | Every table, column and unit; rules for every component; query helpers |
| [docs/interfaces.md](docs/interfaces.md) | How the components talk: frontend modules, map–chat events, platform API, chat, assistant data access, `predict()` |
| [docs/engine-predict-review.md](docs/engine-predict-review.md) | `predict()`: how it should work vs how it works today, with failing contract tests (for Bartek) |
| [engine/README.md](engine/README.md) | Decision engine: what it must provide and how it reads and writes data |
| [assistant/README.md](assistant/README.md) | AI assistant: the `answer()` function, chat tables, MCP rules |
| [frontend/src/map/README.md](frontend/src/map/README.md) | Map: `initMap()`, events, data endpoints |
| <http://localhost:8000/api/docs/> | Live API documentation, generated from the code (while the server runs) |
| [Organiser dataset docs](field-under-pressure-materials/data/README.md) | The hackathon datasets: weather, soil, cropland, satellite, crop-protection guides |

## Repository layout

```text
fieldpressure/      Django project: settings, root URLs
core/               platform: every farm data model, data import commands, API
engine/             decision engine (Django app, no models of its own)
assistant/          AI assistant (Django app; owns only the chat tables)
frontend/           dashboard page (Django template) + TypeScript
  src/              TypeScript sources, built into static/frontend/dist/
  src/map/          map module
docs/               shared documentation (database.md, interfaces.md)
field-under-pressure-materials/   organiser materials (git submodule): guide PDFs, risk spreadsheet, dataset docs
docker-compose.yml  local Postgres + Qdrant (the assistant's vector store)
```

## First-time setup

You need Python 3.11+ (the assistant's PDF library needs it; `.python-version` says 3.12), Node.js 18+ and Docker (Docker Desktop on Mac/Windows).

1. **Clone with the submodule** (it holds the organiser materials):
   ```bash
   git clone --recursive <this repo's URL>
   ```
   Already cloned without it? Run `git submodule update --init`.
2. **Python environment** (Python 3.11+; `.python-version` pins 3.12):
   ```bash
   uv venv --seed                     # with uv: Python 3.12, pip included
   # or without uv: python3.12 -m venv .venv   (plain `python3` may be an older version)
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   python --version                   # must say 3.11 or newer
   pip install -r requirements.txt    # or: uv pip install -r requirements.txt
   ```
   If `pip install` complains about `pymupdf==2.1` and the error mentions `Python.framework/Versions/3.10` (or any path outside `.venv`), you are using the system `pip`, not the venv's: the venv was created without pip (`uv venv` without `--seed`). Fix: `uv pip install pip`, then `hash -r`.
3. **Settings:** `cp .env.example .env` (the defaults work as-is for local development).
4. **Database:** `docker compose up -d` (starts Postgres and Qdrant, the assistant's vector store), then `python manage.py migrate`.
5. **Admin user** (to browse data at `/admin/`): `python manage.py createsuperuser`.
   Then set the demo date: run the server (step 7), open <http://localhost:8000/admin/> → Platform → Clocks → Add. Until a seed does this for you, anything that needs "today" raises `ClockNotSetError`.
6. **Frontend build:**
   ```bash
   cd frontend && npm install && npm run build && cd ..
   ```
7. **Run:** `python manage.py runserver`, then open <http://localhost:8000>. The page should say "Platform OK".
8. **Assistant's guide index** (only if you work on or demo the chat): `python manage.py rag_ingest`. Takes ~4 min the first time (downloads the embedding model), then ~1 min. Details: [assistant/README_RAG.md](assistant/README_RAG.md).

## Day to day

| What | Command |
|------|---------|
| Start / stop the database | `docker compose up -d` / `docker compose stop` |
| Wipe the database completely | `docker compose down -v` (also wipes the assistant's index: rerun `python manage.py rag_ingest`) |
| Rebuild the assistant's guide index | `python manage.py rag_ingest` |
| Run the backend | `python manage.py runserver` |
| Rebuild TypeScript on every save | `cd frontend && npm run watch` |
| Type-check TypeScript | `cd frontend && npm run typecheck` |
| Run tests | `python manage.py test` |

Useful pages while the server runs:

- <http://localhost:8000/> — the dashboard
- <http://localhost:8000/api/docs/> — interactive API documentation (generated from the code)
- <http://localhost:8000/admin/> — browse and edit every table

## Team conventions

- **Farm data models live in [`core/`](core/)** and are described in [docs/database.md](docs/database.md). Only Jan and Szymek create migrations there, so migrations never conflict. Need a new table or column? Ask them. The one exception: the chat tables live in [`assistant/`](assistant/) and belong to Ola.
- **Never use `date.today()`.** The demo replays a past season; get the current date from `core.clock.today()` (in the frontend: from the API, never `new Date()`).
- **Read weather through the helpers:** `WeatherDaily.objects.observed()` (never past today) and `WeatherForecastDaily.objects.current()` (the next 7 days). All helpers, the rules and who writes which table: [docs/database.md → Rules for every component](docs/database.md#rules-for-every-component).
- **Values are in source units** (e.g. wind in km/h). Convert in your own code, never in the database.
- **Work in your own folder.** Each component's README says how it talks to the rest of the system; the full contracts are in [docs/interfaces.md](docs/interfaces.md).
- **No logins, no tokens.** The API is open: it's a demo, not a product.
- **Python packages:** add yours to your section of [`requirements.txt`](requirements.txt).
- **Never commit data or secrets.** Downloaded datasets go in `DATA_DIR` (outside the repo, see `.env.example`); keys go in `.env`.
- The Postgres container listens on **port 5433**, so it doesn't clash with a locally installed Postgres on 5432.
