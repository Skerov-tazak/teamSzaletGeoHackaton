# AI assistant

**Owner:** Ola

The chatbot. It answers from the official guides (RAG) and from the platform's data (through MCP): it explains risks, answers questions with citations, produces summaries and charts, and records the farmer's observations.

## Talking to the rest of the system

- The guide PDFs and the risk spreadsheet are in the organiser submodule: [`field-under-pressure-materials/metodyki/`](../field-under-pressure-materials/metodyki/) (available in code as `settings.MATERIALS_DIR`).
- The platform's tables (fields, weather, soil, threats, risks) are described in [docs/database.md](../docs/database.md).
- This app has no models or migrations of its own; ask Jan or Szymek for schema changes. The database image includes pgvector, if you want the RAG index in Postgres.
- *To be defined in the interfaces step:* the chat endpoint and the message format the frontend accepts (text, citations, charts), who writes the MCP server and which tools it exposes, and where the RAG index lives.
