# AI assistant

**Owner:** Ola

The chatbot. It answers from the official guides (RAG) and from the platform's data (through MCP): it explains risks, answers questions with citations, produces summaries and charts, and records the farmer's observations.

## Talking to the rest of the system

- **Guides:** the PDFs and the risk spreadsheet are in the organiser submodule: [`field-under-pressure-materials/metodyki/`](../field-under-pressure-materials/metodyki/) (available in code as `settings.MATERIALS_DIR`).
- **Platform data:** every table, column and unit is described in [docs/database.md](../docs/database.md); start with its [rules](../docs/database.md#rules-for-every-component) and [helper methods](../docs/database.md#using-the-models). The assistant only reads platform tables.
- **The date is `core.clock.today()`,** never `date.today()`. The demo replays a past season, so "this week" or "yesterday" in a farmer's question means relative to that date.
- **Read through the helpers,** so the assistant never sees data the farmer couldn't have yet:
  - risks: `field.risks.season_so_far()` and `field.risks.coming_days()`, each with its `explanation` (the same reasons the map shows);
  - weather: `WeatherDaily.objects.observed()` and `WeatherForecastDaily.objects.current()`;
  - soil: `field.soil_cells()`; crop history: `field.crop_years`; threats: `Threat` (refer to them by `code`).
- **Units are the dataset's** (wind in km/h, humidity in %, risk score 0–1). Say the unit when quoting a value.
- This app has no models or migrations of its own; ask Jan or Szymek for schema changes. The database image includes pgvector, if you want the RAG index in Postgres.
- *To be defined in the interfaces step:* the chat endpoint and the message format the frontend accepts (text, citations, charts), who writes the MCP server and which tools it exposes, where the RAG index lives, and how farmer observations are stored.
