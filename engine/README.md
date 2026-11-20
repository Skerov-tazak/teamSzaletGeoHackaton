# Decision engine

**Owner:** Bartek

Turns each field's data into risk assessments per threat and day, each with an explanation of why. It may combine rules from the guides, ML models and agents.

## What the rest of the system expects

**One function, `predict()`,** that computes risks and writes them all at once, overwriting earlier ones. Details: [docs/interfaces.md → Decision engine](../docs/interfaces.md#decision-engine).

```python
def predict(field_ids: list[int] | None = None, start: date | None = None, end: date | None = None) -> int:
    """Compute risks (default: all fields, whole season up to today + 7), bulk-overwrite them in Risk, return rows written."""
```

- **Work through the days in order, each one as of that day:** only the weather observed up to that day, plus the forecast issued that day. The query helpers will take an `as_of` date for this (the platform adds it).
- **It's called** after the seed (whole season, so moving the demo date is instant), after the assistant records an observation (that field, from the observation's date), and by hand. A management command such as `python manage.py predict` would be handy.

## Talking to the rest of the system

- **Database only through the Django ORM,** using the models in [`core/models.py`](../core/models.py). Every table, column and unit is described in [docs/database.md](../docs/database.md); start with its [rules](../docs/database.md#rules-for-every-component) and [helper methods](../docs/database.md#using-the-models). This app has no models or migrations of its own; ask Jan or Szymek for schema changes.
- **The date is `core.clock.today()`,** never `date.today()`.
- **Inputs, all through helpers:**
  - observed weather: `WeatherDaily.objects.observed()`, `WeatherHourly.objects.observed()` (never past the day you're assessing);
  - forecast: `WeatherForecastDaily.objects.current()` (the next 7 days);
  - soil: `field.soil_cells()` (average them);
  - crop history: `field.crop_years`;
  - threats: `Threat.objects.filter(crop=field.crop)`. Refer to threats by `code`, never by `id`;
  - farmer reports: the planned `Observation` table (tell us which columns you need).
- **Units are the dataset's** (wind in km/h, radiation in MJ/m², humidity in %). Convert in your code when a rule from the guides uses another unit.
- **Output: the `Risk` table, which only the engine writes.** One row per field, threat and day, with a score from 0 to 1 and an explanation. Write in bulk with `bulk_create(..., update_conflicts=True, ...)` (example in the database doc). The database rejects scores outside 0–1.
- *Still open, and yours to propose* (see the [database doc's open questions](../docs/database.md#open-questions)): what the score means, the explanation format (the map and the assistant both show it), and which extra field data you need (sowing date, growth stage, the columns of `Observation`).
