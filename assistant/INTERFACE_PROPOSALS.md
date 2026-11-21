# Interface proposals from the assistant (Ola)

Changes to shared contracts that the assistant needs. Nothing here is applied to other people's
code: each item says what the assistant does **until** it is accepted. For Jan, Szymek, Bartek, Kuba.

| # | Proposal | For | Status |
|---|----------|-----|--------|
| 1 | `core.Observation` table | Jan + Szymek (schema), Bartek (reads) | proposed |
| 2 | Read-only database role + `readonly` connection | Jan + Szymek | proposed (needed before the SQL tool is enabled) |
| 3 | Risk levels (cut-offs of the 0–1 score) | Bartek, Kuba | assistant uses provisional cut-offs |
| 4 | `Risk.explanation` format | Bartek, Kuba | assistant reads the starting-point format defensively |
| 5 | Guide citation: extra keys `printed_page`, `section`; spreadsheet citations | Jan + Szymek (chat UI) | proposed |
| 6 | `Reply` extensions: `chart`, `pending_action`, `meta` | Jan + Szymek (chat endpoint/UI) | proposed |
| 7 | Chart format: Vega-Lite v5 | Jan + Szymek, Kuba | proposed |
| 8 | Chat endpoint `POST /api/chat/` built in the `assistant` app | Jan + Szymek | assistant builds it to the agreed contract unless you prefer to |

---

## 1. `core.Observation`

Agreed in docs/database.md ("Farmer reports go into an `Observation` table in `core`"), columns open.
Proposal (what the assistant's `record_observation` tool writes):

| Column | Type | Notes |
|--------|------|-------|
| `field` | FK Field, CASCADE | |
| `date` | DateField | the day the farmer saw it (demo calendar), ≤ today |
| `category` | Char: `choroba` / `szkodnik` / `chwasty` / `uszkodzenie` / `inne` | |
| `threat` | FK Threat, nullable, SET_NULL | when the farmer named a known threat of the field's crop |
| `severity` | Char: `niskie` / `srednie` / `wysokie`, blank | |
| `note` | Text | the farmer's words |
| `details` | JSON | the extracted draft, anything else |
| `source` | Char, e.g. `assistant` | who recorded it |
| `idempotency_key` | Char(64), unique | a repeated "yes" in the chat must not create a duplicate |
| `created_at` | DateTime auto | UTC |

**Until it exists:** the assistant writes the same columns into an interim table
`assistant.Observation` (owned by Ola, migration `assistant/0002`). Moving the rows later is a
plain copy. After saving, the tool calls `engine.predict(field_ids=[id], start=date)` when the
engine exists; until then it reports `reassessment.status = "unavailable"`.

**Question for Bartek:** which of these columns does the engine need, and should observations
change the risk directly (e.g. a confirmed disease sets a floor on its score)?

## 2. Read-only role and `connections["readonly"]`

docs/interfaces.md promises a `readonly` connection with a SELECT-only user, a statement time
limit and a row cap. Today `settings.DATABASES` has only `default` (the owner role, full rights).

**Proposal:** a Postgres role `fieldpressure_ro` with `GRANT SELECT` on the `core_*` tables only
(no `assistant_*`, `auth_*`, `django_*`), `ALTER ROLE … SET statement_timeout = '3s'`, and
`DATABASES["readonly"]` pointing at it (credentials from `.env`).

**Until it exists:** the SQL tool (`run_readonly_sql`) is **disabled** — it requires both
`ASSISTANT_ENABLE_SQL=1` and a `readonly` database. The assistant's typed tools read through the
ORM helpers (`season_so_far()`, `coming_days()`, `observed()`, `current()`) on `default` and never write.
The SQL tool itself also validates queries (one SELECT, allowlisted `core_*` tables, no system
functions) and runs them in a read-only transaction with a 3 s timeout and a row cap.
