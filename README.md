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

## Repository layout

```text
fieldpressure/      Django project: settings, root URLs
core/               platform: every model, data import commands, API
engine/             decision engine (Django app, no models of its own)
assistant/          AI assistant (Django app, no models of its own)
frontend/           dashboard page (Django template) + TypeScript
  src/              TypeScript sources, built into static/frontend/dist/
  src/map/          map module
field-under-pressure-materials/   organiser materials (git submodule): guide PDFs, risk spreadsheet, dataset docs
docker-compose.yml  local Postgres
```

## First-time setup

You need Python 3.10+, Node.js 18+ and Docker (Docker Desktop on Mac/Windows).

1. **Clone with the submodule** (it holds the organiser materials):
   ```bash
   git clone --recursive <this repo's URL>
   ```
   Already cloned without it? Run `git submodule update --init`.
2. **Python environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. **Settings:** `cp .env.example .env` (the defaults work as-is for local development).
4. **Database:** `docker compose up -d`, then `python manage.py migrate`.
5. **Admin user** (to browse data at `/admin/`): `python manage.py createsuperuser`.
6. **Frontend build:**
   ```bash
   cd frontend && npm install && npm run build && cd ..
   ```
7. **Run:** `python manage.py runserver`, then open <http://localhost:8000>. The page should say "Platform OK".

## Day to day

| What | Command |
|------|---------|
| Start / stop the database | `docker compose up -d` / `docker compose stop` |
| Wipe the database completely | `docker compose down -v` |
| Run the backend | `python manage.py runserver` |
| Rebuild TypeScript on every save | `cd frontend && npm run watch` |
| Type-check TypeScript | `cd frontend && npm run typecheck` |
| Run tests | `python manage.py test` |

Useful pages while the server runs:

- <http://localhost:8000/> — the dashboard
- <http://localhost:8000/api/docs/> — interactive API documentation (generated from the code)
- <http://localhost:8000/admin/> — browse and edit every table

## Team conventions

- **All models live in [`core/`](core/).** Only Jan and Szymek create migrations, so migrations never conflict. Need a new table or column? Ask them.
- **Work in your own folder.** Each component's README says how it talks to the rest of the system.
- **Python packages:** add yours to your section of [`requirements.txt`](requirements.txt).
- **Never commit data or secrets.** Downloaded datasets go in `DATA_DIR` (outside the repo, see `.env.example`); keys go in `.env`.
- The Postgres container listens on **port 5433**, so it doesn't clash with a locally installed Postgres on 5432.
