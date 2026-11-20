# Decision engine

**Owner:** Bartek

Turns each field's data into risk assessments per threat and day, each with an explanation of why. It may combine rules from the guides, ML models and agents.

## Talking to the rest of the system

- **Database only through the Django ORM,** using the models in [`core/models.py`](../core/models.py). Every table, column and unit is described in [docs/database.md](../docs/database.md); start with its [rules](../docs/database.md#rules-for-every-component) and [helper methods](../docs/database.md#using-the-models). This app has no models or migrations of its own; ask Jan or Szymek for schema changes.
- **The date is `core.clock.today()`,** never `date.today()`.
- **Inputs, all through helpers:**
  - observed weather: `WeatherDaily.objects.observed()`, `WeatherHourly.objects.observed()` (never past today);
  - forecast: `WeatherForecastDaily.objects.current()` (today + 1 … today + 7);
  - soil: `field.soil_cells()` (average them);
  - crop history: `field.crop_years`;
  - threats: `Threat.objects.filter(crop=field.crop)`. Refer to threats by `code`, never by `id`.
- **Units are the dataset's** (wind in km/h, radiation in MJ/m², humidity in %). Convert in your code when a rule from the guides uses another unit.
- **Output: the `Risk` table, which only the engine writes.** One row per field, threat and day, with a score from 0 to 1 and an explanation, overwritten on every recompute. Use `Risk.objects.update_or_create(...)` for single rows, or `bulk_create(..., update_conflicts=True, ...)` for a whole season (examples in the database doc). The database rejects scores outside 0–1.
- *Still open* (see the database doc's open questions): what the score means, the explanation format, which extra field data the engine needs (sowing date, growth stage, reported infestations), and how the engine is triggered (season backfill, and reassessment after a farmer's observation).
