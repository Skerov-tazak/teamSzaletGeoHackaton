# AI assistant

**Owner:** Ola

The chatbot. It answers from the official guides (RAG) and from the platform's data (through MCP): it explains risks, answers questions with citations, and records the farmer's observations.

> **Ola, please confirm or change** (details in [docs/interfaces.md → Chat](../docs/interfaces.md#chat)):
> 1. The **citation format**: `{"type": "guide", "document": "<pdf file name>", "page": 34}` and `{"type": "risk", "field_id": 3, "threat_code": "...", "date": "YYYY-MM-DD"}`.
> 2. The **`answer()` function** you implement (below), with the platform owning the HTTP endpoints and the chat tables.
> 3. **Free-form lookups as read-only SQL**, not ORM code (below).

## What the rest of the system expects

**One function, `answer()`,** in `assistant/answer.py`. The platform's `POST /api/chat/` saves the user's message, calls it, and saves and returns the reply. Until it exists, the endpoint returns a placeholder answer.

```python
def answer(conversation: Conversation, message: str, selected_field: Field | None) -> Reply:
    # Reply: text (markdown), citations, focus_field_id (optional), updated_field_ids
```

- `selected_field` is `None` when the farmer hasn't selected a field (On the frontend map by clicking).
- `focus_field_id` makes the map zoom to a field (if for example the chatbot mentions it); `updated_field_ids` makes the frontend reload fields whose risks changed (requeries the db for new risk assessment).
- Not in this version: charts and streaming. The answer appears all at once after a "thinking…" indicator.

## Talking to the rest of the system

- **Chat tables are yours:** `Conversation` and `Message` live in this app (not `core`). The first version is in [`models.py`](models.py) for convenience (details in [docs/interfaces.md → Chat tables](../docs/interfaces.md#chat-tables)); from now on you change them and create their migrations.
- **MCP is yours:** which tools exist, what they allow and what they refuse.
  - **Free-form lookups** run as **SQL through the read-only connection** `django.db.connections["readonly"]`: that database user can only `SELECT`, and queries are time-limited and row-capped. Never run model-written ORM/Python code: that is arbitrary code execution. The platform provides the read-only user.
  - **Changes** only through narrow tools, e.g. "record an observation" into the planned `Observation` table in `core`. After recording one, call `engine.predict(field_ids=[field.id], start=observation_date)` and return the field in `updated_field_ids`.
- **Guides:** the PDFs and the risk spreadsheet are in the organiser submodule: [`field-under-pressure-materials/metodyki/`](../field-under-pressure-materials/metodyki/) (available in code as `settings.MATERIALS_DIR`). The database image includes pgvector, if you want the RAG index in Postgres.
- **Platform data:** every table, column and unit is described in [docs/database.md](../docs/database.md); start with its [rules](../docs/database.md#rules-for-every-component) and [helper methods](../docs/database.md#using-the-models).
- **The date is `core.clock.today()`,** never `date.today()`. The demo replays a past season, so "this week" or "yesterday" in a farmer's question means relative to that date.
- **Read through the helpers,** so the assistant never sees data the farmer couldn't have yet:
  - risks: `field.risks.season_so_far()` and `field.risks.coming_days()`, each with its `explanation` (the same reasons the map shows);
  - weather: `WeatherDaily.objects.observed()` and `WeatherForecastDaily.objects.current()`;
  - soil: `field.soil_cells()`; crop history: `field.crop_years`; threats: `Threat` (refer to them by `code`).
- **Units are the dataset's** (wind in km/h, humidity in %, risk score 0–1). Say the unit when quoting a value.
