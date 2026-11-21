# Decision engine

**Owner:** Bartek

Turns each field's data into risk assessments per threat and day, each with an explanation of why. It may combine rules from the guides, ML models and agents.

## What the rest of the system expects

**One function, `predict()`,** that computes risks and writes them all at once, overwriting earlier ones. Details: [docs/interfaces.md → Decision engine](../docs/interfaces.md#decision-engine).

```python
def predict(field_ids: list[int] | None = None, start: date | None = None, end: date | None = None) -> int:
    """Compute risks (default: all fields, whole season up to today + 7), bulk-overwrite them in Risk, return rows written."""
```

- **Work through the days in order, each one as of that day:** only the weather observed up to that day, plus the forecast issued that day. The query helpers take an `as_of` date for this: `WeatherDaily.objects.observed(as_of=day)`, `WeatherForecastDaily.objects.current(as_of=day)`.
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

## What is built (v0.1, rules from the guides)

```bash
python manage.py engine_load_threats   # Threat rows for every rule in engine/catalog.py (upsert by code)
python manage.py predict               # all fields, 1 September .. today + 7
python manage.py predict --fields 3 --start 2025-05-01 --end 2025-06-30
python manage.py test engine           # synthetic weather, no data needed
```

From Python (the assistant after recording an observation): `from engine import predict; predict(field_ids=[3], start=day)`.

| File | What |
|------|------|
| [`catalog.py`](catalog.py) | Every threat rule: temperature / humidity ranges, susceptible growth stages, multipliers, the guide's thresholds, **sources with page numbers**. Numbers the guides don't give are marked as team assumptions. |
| [`phenology.py`](phenology.py) | Growth stage (BBCH) per day from degree days and a typical sowing date (wheat 1 Oct, maize 25 Apr). |
| [`features.py`](features.py) | Weather features per day, all trailing windows (a day never sees later weather). |
| [`scoring.py`](scoring.py) | Score + explanation per field, threat and day; spraying window from the forecast. |
| [`compute.py`](compute.py) | `predict()`: loads, scores, bulk-overwrites `Risk`. |
| [`satellite/`](satellite/) | Sentinel-2 NDVI from Earth Search (only the needed window), season calendar grid. For the crop model. |
| [`management/commands/engine_dev_seed.py`](management/commands/engine_dev_seed.py) | **Dev only:** a 6-field farm near Krapkowice (Opolskie) with weather, soil and crop history, until the platform import exists. |

Threats (16): wheat — fusarium head blight, septoria leaf blotch, brown rust, yellow rust, powdery mildew, tan spot, take-all, snow mould; maize — seedling blight, fusarium ear rot, fusarium stalk rot, crazy top, European corn borer, western corn rootworm, aphids, frit fly. Codes like `wheat.fusarium_head_blight`.

### What the score means (proposal)

`score` (0–1) = how favourable the last days were for this threat on this field: **weather (or pest activity) × growth-stage weight × field multipliers** (previous crop, monoculture, heavy soil), capped at 1. It is an index, not a probability. Levels (proposal, to agree with Kuba): **low < 0.3 ≤ medium < 0.6 ≤ high**.

### `Risk.explanation` format (proposal, version 1)

```jsonc
{
  "version": 1,
  "summary": "High risk of Fusarium head blight (fuzarioza kłosów): hours at 15-25 °C with wet leaves (RH >= 95 % or rain) in the last 5 days: 16 h; crop at flowering, BBCH 63.",
  "level": "high",                     // low / medium / high
  "score": 1.0,
  "threat": {"code": "wheat.fusarium_head_blight", "name_pl": "fuzarioza kłosów", "name_en": "Fusarium head blight", "category": "fungal"},
  "as_of": "2025-06-07",               // assessed with weather up to this day
  "crop": {"code": 1110, "source": "field"},
  "growth_stage": {"bbch": 63, "name": "flowering", "method": "degree days, typical sowing date", "sowing_assumed": "2024-10-01", "confidence": 0.6},
  "drivers": [                         // why: one entry per factor, biggest first
    {"factor": "condition_hours", "label": "Hours at 15-25 °C with wet leaves ...", "value": 16, "unit": "h",
     "threshold": "4 h starts the risk, 16 h = full risk", "effect": 1.0},
    {"factor": "growth_stage", "label": "Growth stage BBCH 63 (flowering); susceptible BBCH 61-69", "value": 63, "unit": "BBCH", "effect": 0.0},
    {"factor": "previous_crop", "label": "Previous crop was maize (residue carries the fungus)", "multiplier": 1.5, "effect": 0.33},
    {"factor": "rain_days", "label": "Days with >= 1 mm rain in the window", "value": 2, "unit": "days", "effect": null}
  ],
  "action": {"type": "treat",          // wait / monitor / treat
             "text": "High risk: inspect the field now; if the threshold is exceeded, a treatment is justified.",
             "threshold": "Infection happens at flowering (BBCH 61-69) ...",   // quoted from the guide
             "spray_window": {"date": "2025-06-08", "rule": "1-25 °C, no rain, wind <= 14.4 km/h (4 m/s)", "conditions": {...}, "source": {...}}},
  "severity": 0.15,                    // potential yield loss if it happens (assumption)
  "expected_loss": 0.15,               // score x severity, for ranking fields
  "confidence": 0.6,                   // lower when the stage is estimated or hourly data is missing
  "sources": [{"document": "metodyka_-_PSZENICA_-_www.pdf", "page": 74, "note": "Tabela 26: ..."}],  // same shape as the chat's guide citations
  "notes": ["Maize residue ... raises the risk"],
  "assumptions": {"hours_low": 4, "hours_high": 16, ...},
  "model": "rules", "model_version": "0.1.0"
}
```

`effect` = how much the score would drop without that factor (`null` for context-only values). The map can show `summary` + the drivers; the assistant can cite `sources` directly. No product or dose advice anywhere.

### Data findings (for Jan + Szymek)

- **The weather packages contain no precipitation** (daily or hourly): `total_precipitation` / `precipitation` stay empty. Rain only comes from IMERG. The engine uses the weather value if present, else IMERG. The forecast (seeded from daily weather) therefore has no rain either.
- **Soil `clay`, `sand` are fractions (0.18), not % as in the doc;** `om` is 2.5–12 (looks like %). `BAND_om` / `BAND_pH` / `BAND_cec` are text (`"low"`, `"moderate"`, `"high"`), but the model columns are floats; the source names are upper-case (`BAND_*`, `soilTexture`).
- **Grid `lat` / `lon` are decimals** in `weather_grids.parquet` (cast to float).
- **Hourly year files overlap** by one UTC hour at New Year (unique constraint).
- Weather 2025 is complete (1 Jan – 31 Dec) for daily and hourly; IMERG covers 2020–2025.

### Crop model (satellite) — first results

[`cropmodel.py`](cropmodel.py): LightGBM on the half-month NDVI curve of the season known so far (one model for every day; slots after today are empty). Trained on 30 random 3×3 km windows across Opolskie, seasons 2020, 2022, 2023 (pixels, crop-map labels); tested on 2024 in 6 windows never seen in training.

| As of (2024) | wheat / maize / other: accuracy | "wheat" correct (precision) | "maize" correct | wheat vs maize, when it says one of them |
|---|---|---|---|---|
| 31 Mar | 0.72 | 0.44 | 0.21 | 0.82 |
| 30 Apr | 0.72 | 0.52 | 0.26 | 0.93 |
| 31 May | 0.75 | 0.51 | 0.46 | 0.98 |
| 30 Jun | 0.78 | 0.56 | 0.54 | 0.98 |
| 31 Aug | 0.82 | 0.60 | 0.73 | 0.99 |

Reading: **wheat vs maize is reliable from late May; wheat vs other winter cereals (barley, triticale, rye) and maize vs other summer crops (sugar beet, potato) are not** from NDVI alone. So the satellite *proposes* the crop and the farmer confirms it. Next steps for accuracy: red-edge / SWIR bands, timing normalised by degree days, field-level averaging (pixel numbers above are a lower bound).

**Data problem:** the organisers' 2021 crop map is pixel-identical to the 2022 map (the 2021 package holds the 2022 data; its labels fit the 2022 imagery). Season 2021 is excluded from training; `FieldCropYear` rows for 2021 are wrong too.
