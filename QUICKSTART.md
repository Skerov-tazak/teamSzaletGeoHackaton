# Quick Start Guide

## One Command to Start Everything

### macOS/Linux

```bash
./start.sh
```

### Windows

```bash
start.bat
```

## What the script does

The startup script automates all the setup steps from the README:

1. ✅ Checks prerequisites (Python 3.11+, Docker, Node.js 18+)
2. ✅ Creates a Python virtual environment if needed
3. ✅ Installs Python dependencies
4. ✅ Creates `.env` from `.env.example` if missing
5. ✅ Starts Docker services (Postgres + Qdrant) in the background
6. ✅ Waits for the database to be ready
7. ✅ Runs database migrations
8. ✅ Creates admin user (username: `admin`, password: `admin`)
9. ✅ Sets the demo date
10. ✅ Seeds development data (5 fields with risks)
11. ✅ Builds the frontend TypeScript
12. ✅ Optionally builds the RAG index (may take 2-4 min on first run)

After the script finishes, you'll see:

```
════════════════════════════════════════════
✓ Application ready!
════════════════════════════════════════════

Start the backend server:
  python manage.py runserver
```

## Next Steps

### 1. Start the Backend (in Terminal 1)

```bash
python manage.py runserver
```

You'll see:
```
Starting development server at http://127.0.0.1:8000/
Quit the server with CONTROL-C.
```

### 2. (Optional) Watch Frontend Changes (in Terminal 2)

```bash
cd frontend && npm run watch
```

This rebuilds TypeScript on every file save.

### 3. Open in Browser

- **Dashboard:** http://localhost:8000
- **API Docs:** http://localhost:8000/api/docs/
- **Django Admin:** http://localhost:8000/admin/ (admin/admin)
- **Qdrant Dashboard:** http://localhost:6333/dashboard

## Troubleshooting

### "Database did not become ready"

The Docker Postgres service may need more time to start. Try:

```bash
docker compose stop
docker compose up -d
# wait 30 seconds
python manage.py migrate
python manage.py runserver
```

### "Port 5433 already in use"

If you have a local Postgres running on the same machine:

1. Stop the conflicting service, or
2. Edit `docker-compose.yml` and change the host port from `5433` to `5434`, then update `.env` to match

### "File not found: .env"

The script creates `.env` from `.env.example`. If this fails, copy manually:

```bash
cp .env.example .env
```

### "Module not found" or import errors after pull

The dependencies or database schema may have changed. Rebuild from scratch:

```bash
source .venv/bin/activate    # or: .venv\Scripts\activate on Windows
pip install -r requirements.txt
python manage.py migrate
```

### "admin user password doesn't work"

The default is set by the script. If you need to reset:

```bash
python manage.py shell
>>> from django.contrib.auth.models import User
>>> User.objects.get(username='admin').set_password('newpassword')
>>> User.objects.get(username='admin').save()
>>> exit()
```

## Clean Up

### Stop all services (keep data)

```bash
docker compose stop
```

### Stop and wipe all data (database + RAG index)

```bash
docker compose down -v
```

Then run `./start.sh` again to rebuild.

### Remove Python virtual environment

```bash
rm -rf .venv    # macOS/Linux
rmdir .venv     # Windows
```

Then run `./start.sh` to recreate.

## For Each Component

| Task | Command |
|------|---------|
| Run the backend | `python manage.py runserver` |
| Watch frontend on save | `cd frontend && npm run watch` |
| Type-check TypeScript | `cd frontend && npm run typecheck` |
| Rebuild the guide index | `python manage.py rag_ingest` |
| Run tests | `python manage.py test` |
| Check database status | `docker compose ps` |
| View database | Use `psql` or pgAdmin at port 5433 |

## Notes

- The script sets the demo date to **2024-05-15** (the replay date for the hackathon season).
- The admin user credentials are **admin / admin** — change them in production.
- All data is kept in Docker volumes (`pgdata` and `qdrant_storage`), which survive `docker compose stop` but are deleted by `docker compose down -v`.
- If you need LLM features (chat), add API keys to `.env`:
  - `GEMINI_API_KEY` (and `GEMINI_MODEL`)
  - `GROQ_API_KEY` (and `GROQ_MODEL`)
  
  See `.env.example` for details.

## Still having issues?

Refer to the main [README.md](README.md) for detailed setup steps.
