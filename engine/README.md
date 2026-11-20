# Decision engine

**Owner:** Bartek

Turns each field's data into risk assessments per threat and day, each with an explanation of why. It may combine rules from the guides, ML models and agents.

## Talking to the rest of the system

- Reads and writes the database only through the Django ORM, using the models in [`core/models.py`](../core/models.py). Every table, column and unit is described in [docs/database.md](../docs/database.md). This app has no models or migrations of its own; ask Jan or Szymek for schema changes.
- Writes its results to the `Risk` table: one row per field, threat and day, with a score from 0 to 1, overwritten on every recompute.
- The current date comes from `core.clock.today()`. Observed weather is only available up to today; the next 7 days are in `WeatherForecastDaily`.
- *Still open* (see the database doc's open questions): what the score means, the explanation format, which extra field data the engine needs (sowing date, growth stage, reported infestations), and how the engine is triggered (season backfill, and reassessment after a farmer's observation).
