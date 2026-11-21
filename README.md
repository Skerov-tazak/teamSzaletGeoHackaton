<div align="center">

<img src="logo/cropilot-logo-wektorowe-svg.svg" alt="Cropilot" width="420"/>

# Cropilot - Field Under Pressure — team Szalet

Farmer dashboard for maize and winter wheat: a map of a farm's fields and their crop risks, plus an AI assistant grounded in the official crop-protection guides. See [architecture_overview.md](architecture_overview.md) for the components and how they fit together.

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/) [![Django](https://img.shields.io/badge/Django-5.2-092E20?logo=django&logoColor=white)](https://www.djangoproject.com/) [![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/) [![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/) [![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://www.docker.com/) [![Leaflet](https://img.shields.io/badge/Maps-Leaflet-1B873F?logo=leaflet&logoColor=white)](https://leafletjs.com/) [![Qdrant](https://img.shields.io/badge/Vector%20DB-Qdrant-DC382D?logo=qdrant&logoColor=white)](https://qdrant.tech/) [![Hackathon](https://img.shields.io/badge/Hackathon-Field%20Under%20Pressure%202026-FF6B35)](https://geo-hackathon.g.location360.ag/)

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
| [scenarios/README.md](scenarios/README.md) | Demo scenarios: the `scenario` command and the scenario file format |
| [docs/demo-script.md](docs/demo-script.md) | The presentation walkthrough for `demo_2024`, step by step with the chat messages |
| <http://localhost:8000/api/docs/> | Live API documentation, generated from the code (while the server runs) |
| [Organiser dataset docs](field-under-pressure-materials/data/README.md) | The hackathon datasets: weather, soil, cropland, satellite, crop-protection guides |

## Repository layout

```text
fieldpressure/      Django project: settings, root URLs
core/               platform: every farm data model, data import commands, API
engine/             decision engine (Django app; its only model is its own cache, RiskSnapshot)
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
   The demo date and the farm come from a scenario: see [Running a demo](#running-a-demo). Until one is loaded, anything that needs "today" raises `ClockNotSetError` (the API answers `503`). For frontend work without the datasets, `python manage.py assistant_dev_seed` fills a synthetic farm (5 fields, threats, risks) and sets the date.
6. **Frontend build:**
   ```bash
   cd frontend && npm install && npm run build && cd ..
   ```
   The build checks that the committed API types are current, type-checks, and bundles into `frontend/static/frontend/dist/` (Leaflet for the map, marked + DOMPurify for chat answers, and `vega-embed` for chat charts in a separate chunk that loads only when a message has a chart).
7. **Run:** `python manage.py runserver`, then open <http://localhost:8000>. The header should say "Platforma OK".
8. **Assistant's guide index** (only if you work on or demo the chat): `python manage.py rag_ingest`. Takes ~4 min the first time (downloads the embedding model), then ~1 min. Details: [assistant/README_RAG.md](assistant/README_RAG.md).

## Running a demo

A demo is a scenario (`scenarios/definitions/<name>.json`: the fields, the season, the starting demo date) loaded from the real datasets into a database, then the app. Run everything from the repo root with the venv active. The presentation walkthrough for `demo_2024` is in [docs/demo-script.md](docs/demo-script.md).

### 1. Get the data (once per machine)

The import reads the hackathon datasets from `DATA_DIR` (default `../field-under-pressure-data`, next to the repo; see `.env.example`). Only the Opolskie part is needed: about 5.9 GB of the organisers' 158 GB.

Download it with the organisers' presigned URL list (a text file of `key<TAB>url` lines, e.g. `dhub-pl-hackathon-2026_presigned_urls.txt` in the repo root). **The links stop working within hours** even though they say otherwise, so ask for a fresh list and use it straight away. Interrupted downloads resume when you rerun it.

```bash
grep -E '^(cropland/|soil_isric_250_v2/soil_Opolskie|weather_data/(daily|hourly)/20[0-9]{2}/weather_(daily|hourly)_20[0-9]{2}_Opolskie|weather_data/(imerg|weather_grids))' dhub-pl-hackathon-2026_presigned_urls.txt | while IFS=$'\t' read -r key url; do mkdir -p "../field-under-pressure-data/raw/$(dirname "$key")"; curl -fsSL -C - -o "../field-under-pressure-data/raw/$key" "$url"; done
```

Then unpack the soil table and the weather grid, and clip the crop maps to Opolskie (about 1 min):

```bash
unzip -o ../field-under-pressure-data/raw/soil_isric_250_v2/soil_Opolskie_isric_250_v2.zip -d ../field-under-pressure-data/soil
unzip -o ../field-under-pressure-data/raw/weather_data/weather_grids.zip -d ../field-under-pressure-data/weather
python engine/scripts/clip_cropland.py ../field-under-pressure-data/raw/cropland ../field-under-pressure-data/cropland
```

`DATA_DIR` then holds `raw/` (the organisers' zips, read directly for weather and IMERG), `soil/Opolskie_isric_250_v2.parquet`, `weather/weather_grids.parquet` and `cropland/cropland_<year>.tif`.

### 2. Load a scenario and run the app

```bash
docker compose up -d                                                    # the database
python manage.py scenario list                                          # the scenarios
python manage.py scenario switch demo_2024 --strict-data --reset-chat   # ~40 s (small scenarios) to ~2 min (demo_2024)
python manage.py engine_precompute_dates                                # 1-2 min: date arrows then take ~0.3 s instead of ~5 s
python manage.py runserver                                              # then open http://localhost:8000
```

Replace `demo_2024` with any name from `scenario list`. If the LLM keys are in `../.env` rather than `.env`, start the server with `set -a; . ../.env; set +a; python manage.py runserver`.

- **Always pass `--strict-data`:** without it, a missing data file is silently replaced with invented data.
- **`switch` wipes the database it runs on** (all fields, farmer reports, weather and risks). Don't run it on the shared `fieldpressure` database while someone else uses it: use your own database (below).
- **Field ids change on every switch:** refer to fields by name.
- The date cache covers the demo date − 7 … + 30 days; moving the date outside it takes ~5 s per step again.

### 3. Reset between rehearsals

Clears farmer reports and chats, keeps the weather (~40 s):

```bash
python manage.py scenario switch demo_2024 --strict-data --keep-weather --reset-chat
python manage.py engine_precompute_dates
```

### 4. A separate database per test

Every command reads the database name from `POSTGRES_DB` (default `fieldpressure`), so a test can run in its own database inside the same Postgres container:

```bash
docker compose exec db createdb -U fieldpressure fieldpressure_demo
POSTGRES_DB=fieldpressure_demo python manage.py migrate
POSTGRES_DB=fieldpressure_demo python manage.py scenario switch demo_2024 --strict-data --reset-chat
POSTGRES_DB=fieldpressure_demo python manage.py engine_precompute_dates
POSTGRES_DB=fieldpressure_demo python manage.py runserver
docker compose exec db dropdb -U fieldpressure fieldpressure_demo       # afterwards (stop the server first)
```

## Day to day

| What | Command |
|------|---------|
| Start / stop the database | `docker compose up -d` / `docker compose stop` |
| Wipe the database completely | `docker compose down -v` (also wipes the assistant's index: rerun `python manage.py rag_ingest`) |
| Rebuild the assistant's guide index | `python manage.py rag_ingest` |
| Run the backend | `python manage.py runserver` |
| Load or switch the demo scenario | `python manage.py scenario switch <name> --strict-data` (see [Running a demo](#running-a-demo)) |
| Make demo date moves instant (after every switch) | `python manage.py engine_precompute_dates` |
| After pulling main | `python manage.py migrate` (new migrations, e.g. the engine's cache table) |
| Rebuild TypeScript on every save | `cd frontend && npm run watch` |
| Type-check TypeScript | `cd frontend && npm run typecheck` |
| After changing an API endpoint: regenerate the schema and the TypeScript types (commit both) | `python manage.py spectacular --file frontend/openapi.yml`, then `cd frontend && npm run api:types` |
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
