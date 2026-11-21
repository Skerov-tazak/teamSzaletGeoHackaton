# Decision engine

**Owner:** Bartek · version 0.5 · data checklist: `python manage.py engine_check_data` · history and findings: [CHANGELOG.md](CHANGELOG.md)

The engine turns each field's data into a **risk per threat and day, each with an explanation of why**, and writes them to the `Risk` table. The map and the assistant only read those rows; they never compute risk themselves.

It is a **rule-based (expert) system** built from the official guides (metodyki integrowanej ochrony, `ryzyka_zebrane.xlsx`, the GIORiN guide): there are no observations of diseases in the data to train a model on. Two parts use data-driven models: the **crop** of a field (Sentinel-2 + LightGBM, trained on the crop maps) and the **growth stage** (degree days, calibrated to the field's satellite curve). Farmer reports from the chat adjust the risks.

## Contents

1. [Quick start](#quick-start)
2. [Interface](#interface)
3. [When and how to run it](#when-and-how-to-run-it)
4. [Data to load](#data-to-load)
5. [What it writes: Risk and the explanation](#what-it-writes-risk-and-the-explanation)
6. [How it works](#how-it-works)
7. [Threats](#threats)
8. [Assumptions, limits, validation](#assumptions-limits-validation)
9. [Open items for other components](#open-items-for-other-components)

## Quick start

```bash
# prerequisites: the data in "Data to load" (check: python manage.py engine_check_data)
python manage.py engine_load_threats                 # Threat rows for every rule (upsert by code)
python manage.py engine_fetch_ndvi --season 2025     # optional: satellite curves per field (needs network)
python manage.py predict                             # all fields, 1 September .. today + 7
python manage.py engine_summary --date 2025-06-05    # fields ranked by urgency, with reasons
python manage.py test engine                         # synthetic data, no downloads needed
```

No platform import yet? `python manage.py engine_dev_seed` builds a **development-only** farm (5 fields near Krapkowice, Opolskie, season 2025) with weather, soil, crop history and the clock.

## Interface

Everything other components call. All functions use `core.clock.today()`, never the real date.

### `predict()` — compute and write risks

```python
from engine import predict

n = predict(field_ids=None, start=None, end=None, observations=None)  # -> number of Risk rows written
```

| Argument | Default | Meaning |
|---|---|---|
| `field_ids` | all fields | Fields to recompute. Fields of the same crop within 3 km are added when a symptoms report on one of them spreads ([below](#farmer-reports)). |
| `start` | 1 September of the current season | First day to compute. |
| `end` | today + 7 | Last day to compute. |
| `observations` | the `Observation` table | Farmer reports to use instead of the table (tests, scripted demos). |

- Writes in **one transaction**: deletes this range's rows for these fields, then bulk-inserts the new ones. Re-running is safe and gives the same result.
- **Each day is computed as of that day:** only weather up to that day, reports dated up to that day, satellite stages confirmed up to that day. Later data never changes an earlier day ([details](#as-of-every-day)).
- Days after `today` get lower confidence (forecast, [details](#confidence)).
- Speed: a full season for 5 fields takes a few seconds.

### `what_if()` — dry run for the assistant

```python
from engine import what_if
from engine.observations import Report

what_if(field_id=15, day=date(2025, 6, 8), hypothetical=[
    Report(observed_on=date(2025, 6, 6), kind="treatment", threat_code="wheat.fusarium_head_blight", field_id=15)])
# -> [{"threat_code", "score_now", "score_if", "change", "level_if", "summary_if"}, ...]  (highest first)
```

Answers "what if I spray on Friday / sowed later / the neighbour has it". **Writes nothing.**

### `engine.summary` — one answer per field and day

```python
from engine.summary import field_day, farm_ranking

field_day(field_id, day)   # dict below
farm_ranking(day)          # list of field_day dicts, most urgent first, with "rank"
```

`field_day` is a pure read of `Risk` and the satellite cache; nothing is stored:

| Key | Content |
|---|---|
| `max_score`, `level` | Highest threat score of the day and its level. |
| `expected_loss`, `expected_loss_pct` | Share of the yield at risk: `1 - Π(1 - score × severity)` over all threats. Used to rank fields. |
| `top_threats` | Top 3 threats by expected loss, each with score, level, summary, action. |
| `actions` | `treat` / `monitor` actions, with the guide's threshold and the spraying window. |
| `why` | One line for lists ("Fusarium head blight high (0.75); Grain aphids medium (0.53)"). |
| `growth_stage` | BBCH, name, method, confidence. |
| `harvest` | From BBCH 83: wheat — ready / next dry day / sprouting risk; maize — safe storage days of undried grain. |
| `crop_check` | Does the satellite curve fit the field's crop, plus the crop model's answer and probabilities. |
| `field_id`, `name`, `date`, `crop`, `confidence` | Identification; lowest confidence of the day's threats. |

### `engine.observations.Report` — farmer reports

```python
Report(observed_on: date, kind: str, threat_code: str | None = None, severity: float | None = None,
       distance_m: float | None = None, details: dict = {}, text: str = "", field_id: int | None = None)
```

`kind` is one of `symptoms`, `absence`, `neighbour`, `treatment`, `field_fact`, `event`; effects are in [Farmer reports](#farmer-reports). `field_id=None` means the whole farm.

### Other functions

| Function | Use |
|---|---|
| `engine.cropmodel.predict_field(field, season, today)` | Crop model for one field as of a day: `{"crop", "label", "confidence", "probabilities", ...}`. |
| `engine.harvest.safe_storage_days(moisture_pct, grain_temp_c)` | Maize grain storage table (Tab. 37). |
| `engine.compute.adjust_for_lead(explanation, days_ahead)` | Recompute the forecast confidence of a stored row after the clock moved. |

### Management commands

| Command | What |
|---|---|
| `predict [--fields 1 2] [--start D] [--end D]` | `predict()` from the shell. |
| `engine_load_threats` | Create / update the `Threat` rows of all 25 rules (by `code`; other rows untouched). |
| `engine_fetch_ndvi [--season Y] [--fields ...]` | Download and cache each field's Sentinel-2 NDVI series (network). |
| `engine_summary [--date D] [--json]` | Print the field ranking. |
| `engine_check_data [--season Y]` | Check that every table / file the engine needs is loaded; lists what is missing per field. |
| `engine_dev_seed` | **Development only**: demo farm + data. The platform's import replaces it. |

## When and how to run it

`predict()` is the only thing that writes. It must run whenever an input of a field changes:

| When | Call | Who |
|---|---|---|
| **After the seed / import** (historical demo) | `predict()` for the **previous season first**, then the current one (whole season, including the maize harvest): `predict(start=date(2024, 1, 15), end=date(2024, 8, 31))`, then `predict(start=date(2024, 9, 1), end=date(2025, 10, 31))` | platform seed |
| **Daily, in live mode** (after the new forecast is stored) | `predict(start=today - 30 days)` | daily job |
| **After the assistant records a report** | `predict(field_ids=[field.id], start=report.observed_on)`; return that field (and nearby fields it spread to) in `updated_field_ids` | assistant tool |
| **After the farmer changes a field's crop** (`Field.crop`) | `predict(field_ids=[field.id], start=season start)` | platform (API) |
| **After `engine_fetch_ndvi`** (new satellite scenes) | `predict(field_ids=..., start=season start)` | daily job / by hand |
| **After threats, rules or imported data change** | `predict()` | by hand |

**Moving the demo date does not need a recompute:** the season is precomputed and the API hides days after today + 7. Only the forecast confidence of coming days refers to the clock at compute time (`forecast_lead_days`); `adjust_for_lead()` can refresh it when serving.

**Order of a fresh setup:**

```bash
python manage.py migrate
# platform import (exact spec: "Data to load"): CropClass, WeatherGrid, Field, FieldCropYear, SoilCell,
#                  WeatherDaily (+ IMERG), WeatherHourly (+ IMERG), WeatherForecastDaily, Clock
python manage.py engine_load_threats            # or the platform's Threat fixture with the same codes
python manage.py engine_fetch_ndvi --season 2024
python manage.py engine_fetch_ndvi --season 2025   # both optional (network)
python manage.py engine_check_data              # must end with "Everything the engine requires is present."
python manage.py predict --start 2024-01-15 --end 2024-08-31   # last season first (carry-over)
python manage.py predict --start 2024-09-01 --end 2025-10-31   # this season, including the maize harvest
```

Last season goes first because this season reads last season's risks: a pathogen that peaked on the field carries over in the residue.

## Data to load

Everything below must be in place **before** `predict()` runs. Check it with:

```bash
python manage.py engine_check_data        # per field: OK / MISSING (required) / OPTIONAL; exit code 1 if something required is missing
```

The engine reads only through the Django ORM and the platform helpers (`.observed(as_of=...)`, `.current(as_of=...)`, `field.soil_cells()`, `field.crop_years`); it never reads the raw files itself, except the two `DATA_DIR` files at the end.

### Which rows: scope and dates

- **Cells:** weather only for the grid cells the fields point to (`Field.weather_grid`), soil only for the fields' H3 cells (`Field.h3_cells`). One weather cell usually serves the whole farm.
- **Dates** (season = harvest year; wheat 1 Sep – 31 Aug, maize to 31 Dec):

| Data | From | To |
|---|---|---|
| `WeatherDaily`, `WeatherHourly` | **45 days before the season start** (trailing windows); for the demo season 2025: **2024-07-18** | the last day you compute: for a precomputed demo season **2025-10-31** (maize harvest); live: today |
| same, previous season (carry-over) | 2023-07-18 | 2024-08-31 |
| `WeatherForecastDaily` | issued on **every day** from the season start | issued on the last computed day (each issue covers +1 … +7) |
| `FieldCropYear` | at least the previous season (2024 for season 2025); ideally the 5 previous years (2020–2024) | |

### Tables, sources and columns

**Required** = no risks (or wrong risks) without it. Source paths are as in the organisers' package (`DATA_DIR/raw/...`).

| Table | Required | Rows | Columns the engine reads (format) | Source file → how |
|---|---|---|---|---|
| `Clock` | **yes** | 1 | `today` (date) | set by the seed: the demo date, e.g. 2025-06-15 |
| `CropClass` | **yes** | all 21 legend codes (at least every code in `FieldCropYear`) | `code`, `name` | cropland legend (`data/cropland.md`): 0 No cropland, 1110 Wheat, 1120 Barley, 1130 Maize, … |
| `Threat` | **yes** | 25 | `code` = the codes in [Threats](#threats), `crop` | `python manage.py engine_load_threats` (or a fixture with **the same codes**) |
| `WeatherGrid` | **yes** | the fields' cells | `grid_id`, `lat`, `lon` (floats) | `weather_data/weather_grids.zip` → `weather_grids.parquet` (`grid_id`, `lat`, `lon` are **decimals → cast to float**, `l1_name` = voivodeship) |
| `Field` | **yes** | the farm's fields | `geometry` (GeoJSON Polygon/MultiPolygon, EPSG:4326, **[lon, lat]**, non-empty), `centroid_lat/lon`, `area_ha` (EPSG:2180), `weather_grid` (**nearest grid point to the centroid**), `h3_cells` (**H3 level 10 cells whose centre is inside the polygon** — `h3.geo_to_cells(polygon, 10)`; the centroid's cell if none), `crop` (**this season's crop**: 1110 or 1130 get risks, other codes get none) | polygons drawn by us; crop from the farmer or the crop model (`field_day()["crop_check"]`) |
| `FieldCropYear` | **yes** | per field × year × class | `year`, `crop_class`, `share` (0–1, shares of a year sum to 1) | `cropland/cropland_pl_4326_<year>.zip` (48 GeoTIFF tiles, EPSG:4326, uint16 codes): pixels of each class inside the polygon ÷ all pixels. **2021 is a copy of 2022** in the package — store it but expect it to be wrong |
| `WeatherDaily` | **yes** | per cell × day | `avg_temperature`, `min_temperature`, `max_temperature` (°C), `avg_relative_humidity` (%), `eto` (mm/day), `avg_wind_speed` (km/h), `avg_soil_temperature_level_1`, `min_soil_temperature_level_1` (°C), `avg_soil_moisture_level_1` (m³/m³, 0–1), `avg_snow_depth` (mm w.e.), **precipitation: `total_precipitation` or `imerg_total_precipitation`** (mm/day) | `weather_data/daily/<year>/weather_daily_<year>_<Region>.zip` (same column names; **no precipitation in it**) + `weather_data/imerg_precipitation_daily.zip` → `daily/<year>/precip_daily_<year>_<Region>.zip` (nested zip) → `total_precipitation` **stored as `imerg_total_precipitation`**, joined on `grid_id` + `date` |
| `WeatherHourly` | recommended | per cell × hour | `utc_time` (aware, UTC), `date` (local Europe/Warsaw date), `temperature` (°C), `relative_humidity` (%), **`precipitation` or `imerg_precipitation`** (mm/h) | `weather_data/hourly/<year>/weather_hourly_<year>_<Region>.zip` (`utc_time` is naive UTC → make aware; drop `local_time`; year files **overlap by one hour** at New Year → ignore duplicates) + `imerg_precipitation_hourly.zip` → `hourly/<year>/precip_hourly_<year>_<Region>.zip` → `precipitation` stored as `imerg_precipitation`, joined on `grid_id` + `utc_time`. Without it infection hours are estimated from daily values (confidence × 0.7) |
| `WeatherForecastDaily` | **yes** (without it: no spraying window, no harvest dry days) | per cell × issue day × 7 | `max_temperature`, `min_temperature`, `avg_wind_speed`, `avg_relative_humidity`, `total_precipitation` | demo: for every day D copy `WeatherDaily` of D+1 … D+7 with `issued_on = D` (all daily columns except IMERG). Live: a real forecast |
| `SoilCell` | optional | the fields' H3 cells | `clay`, `sand` (fraction 0–1 **or** %; both accepted), `ph` | `soil_isric_250_v2/soil_<Region>_isric_250_v2.zip` → parquet keyed by `h3_index_10`; rename `soilTexture` → `soil_texture`; `BAND_om`/`BAND_pH`/`BAND_cec` are **text** (`low`/`moderate`/`high`) while the model columns are floats — leave them empty or change the model. Used only for the heavy-soil multiplier |
| `Observation` | optional (planned) | farmer reports | see [below](#observation-rows) | written by the assistant's tool |
| `Risk` | — | written by `predict()` | — | last season's rows are read back for carry-over, so compute the previous season first |

`<Region>` in file names is the voivodeship without Polish letters (`Opolskie`, `Dolnoslaskie`, `Slaskie`; some packages spell `Łódzkie` as `odzkie` and `Małopolskie` as `Maopolskie`).

### Observation rows

Proposed table (Jan + Szymek: schema; Ola: writes). The engine reads it only through `engine/observations.py`, so a renamed column is a one-line change there.

| Column | Type | Content |
|---|---|---|
| `field` | FK Field, null | the field; null = the whole farm / "nearby" |
| `observed_on` | date | the day the farmer saw it (not the day they wrote) |
| `recorded_at` | datetime | when it was stored |
| `kind` | text | `symptoms`, `absence`, `neighbour`, `treatment`, `field_fact`, `event` |
| `threat_code` | text, null | e.g. `wheat.brown_rust`; null = all threats (`absence`) / all fungal (`treatment`) |
| `severity` | float 0–1, null | `symptoms`: how bad (the chat may map low/medium/high → 0.3/0.6/0.9) |
| `distance_m` | float, null | `neighbour`: distance to the reported case |
| `details` | JSON | `field_fact`: `{"sowing_date": "2024-09-25"}`, `{"tillage": "reduced"}` or `"plough"`, `{"resistant_to": ["wheat.brown_rust"]}`; `event`: `{"type": "hail" \| "lodging" \| "flood"}` |
| `text` | text | the farmer's own words (shown in the explanation) |

After storing a row: `predict(field_ids=[field.id], start=observed_on)`.

### Files in `DATA_DIR` (optional, not in git)

`DATA_DIR` is set in `.env` (default `../field-under-pressure-data`).

| File | Used for | How to produce |
|---|---|---|
| `satellite/fields/field<id>_<polygon hash>_s<season>.parquet` (columns `date`, `ndvi`, `ndvi_p25`, `ndvi_p75`, `clear_share`, `pixels`) | growth-stage calibration, crop check | `python manage.py engine_fetch_ndvi --season 2025` (and `--season 2024`) after the fields exist; needs internet (Earth Search, no account). A new polygon gets a new hash, so re-run after redrawing a field |
| `models/crop_lgbm.txt` + `models/crop_model.json` (≈ 15 MB) | crop check | copy from Bartek, or train: put the organisers' zips in `DATA_DIR/raw/` (`cropland/`, `weather_data/daily/<year>/`), then `python engine/scripts/clip_cropland.py DATA_DIR/raw/cropland DATA_DIR/cropland`, `python engine/scripts/build_crop_samples.py DATA_DIR` (internet), `python -m engine.cropmodel train DATA_DIR`; also needs `DATA_DIR/weather/weather_grids.parquet` |

Without them the engine still runs: stages from degree days only, no crop check.

**The dev seed** (`engine_dev_seed`, development only) reads: `DATA_DIR/cropland/cropland_<year>.tif` (from `clip_cropland.py`), `DATA_DIR/weather/weather_grids.parquet`, `DATA_DIR/raw/weather_data/{daily,hourly}/<year>/*.zip`, `DATA_DIR/raw/weather_data/imerg_precipitation_{daily,hourly}.zip`, `DATA_DIR/soil/<Region>_isric_250_v2.parquet`.

Units stay the dataset's (wind km/h, RH %, radiation MJ/m²); the engine converts where a guide uses another unit (wind 4 m/s = 14.4 km/h).

## What it writes: Risk and the explanation

One `Risk` row per **field × threat × day**: `score` (0–1), `explanation` (JSON below), `computed_at`.

**Score** = how favourable the recent days were for this threat on this field: **weather or pest activity × growth-stage weight × field multipliers**, adjusted by farmer reports, capped at 1. An index, not a probability. **Levels:** low < 0.3 ≤ medium < 0.6 ≤ high (to agree with the map).

**`explanation` (version 1):**

```jsonc
{
  "version": 1,
  "summary": "High risk of Fusarium head blight (fuzarioza kłosów): hours at 15-25 °C with wet leaves (RH >= 95 % or rain) in the last 5 days: 16 h; crop at flowering, BBCH 63; previous crop was maize (residue carries the fungus).",
  "level": "high",
  "score": 0.83,
  "threat": {"code": "wheat.fusarium_head_blight", "name_pl": "fuzarioza kłosów", "name_en": "Fusarium head blight", "category": "fungal"},
  "as_of": "2025-06-07",
  "crop": {"code": 1110, "source": "field"},              // "crop map" for past seasons
  "growth_stage": {"bbch": 63, "name": "flowering", "method": "degree days calibrated to the satellite: NDVI peak 0.91 on 2025-05-24 (heading)",
                   "sowing_assumed": "2024-10-01", "confidence": 0.8},
  "drivers": [                                              // WHY: one entry per factor
    {"factor": "condition_hours", "label": "Hours at 15-25 °C with wet leaves ...", "value": 16, "unit": "h",
     "threshold": "4 h starts the risk, 16 h = full risk", "effect": 1.0},
    {"factor": "growth_stage", "label": "Growth stage BBCH 63 (flowering); susceptible BBCH 61-69", "value": 63, "unit": "BBCH", "effect": 0.0},
    {"factor": "previous_crop", "label": "Previous crop was maize (residue carries the fungus)", "multiplier": 1.5, "effect": 0.21},
    {"factor": "farmer_report", "kind": "neighbour", "label": "Reported Fusarium head blight about 400 m away on 2025-06-03 ...",
     "observed_on": "2025-06-03", "text": "Sąsiad ma fuzariozę...", "effect": 0.28},
    {"factor": "rain_days", "label": "Days with >= 1 mm rain in the window ...", "value": 2, "unit": "days", "effect": null}
  ],
  "action": {
    "type": "treat",                                        // wait / monitor / treat
    "text": "High risk: inspect the field now; if the threshold is exceeded, a treatment is justified.",
    "threshold": "Heading: ... (guide's threshold for this stage)",
    "spray_window": {"date": "2025-06-08", "quality": "optimal", "conditions": {...}, "rule": "1-25 °C, next night >= 1 °C, ...",
                     "note": null, "source": {"document": "...", "page": 216}}
  },
  "severity": 0.15,                 // potential yield loss if it happens (team assumption)
  "expected_loss": 0.12,            // score x severity
  "confidence": 0.8,                // stage method x data quality x forecast distance; 1.0 when the farmer saw it
  "confidence_observed": 0.8,       // only on days after today: confidence before the forecast discount
  "forecast_lead_days": 3,          // only on days after today
  "sources": [{"document": "metodyka_-_PSZENICA_-_www.pdf", "page": 74, "note": "Tabela 26 ..."}],   // same shape as chat citations
  "notes": ["Each 1 % of infected ears can add about 0.3 mg/kg DON ..."],
  "assumptions": {"hours_low": 4, "hours_high": 16, ...},   // the team's own numbers in this rule
  "model": "rules", "model_version": "0.1.0"
}
```

- `effect` = how much the score would drop without that factor; `null` = context only. The map can show `summary` and the drivers; the assistant can cite `sources` directly.
- No product names or doses anywhere (shared principle).

## How it works

```text
for each field, for each season in [start, end]:
    crop        = Field.crop (current season) | crop map (past seasons)
    weather     = daily + hourly for the field's grid cell (observed)
    stage       = BBCH from degree days                         (phenology.py)
                  → shifted through satellite anchors            (satellite/fieldndvi.py, from the day they are confirmed)
                  → farmer's sowing date if reported             (from the day it was reported)
    context     = previous crop, maize years in a row, soil, last season's peaks
    reports     = farmer reports + symptoms spread from nearby fields
    for each threat rule of the crop                             (catalog.py)
        base    = weather / activity term per day, trailing windows only     (scoring.py)
        score   = base × stage weight × multipliers, then report effects, capped at 1
        explanation: summary, drivers with effects, action + spraying window, sources
write all rows (replace the range)                               (compute.py)
```

### As of every day

Every feature for day D is a **trailing** value over days ≤ D (sums or means over the last N days), so a whole season is computed in one pass without look-ahead. Reports affect days ≥ their `observed_on`; satellite stage anchors apply from the scene that confirmed them; the spraying window uses the forecast issued on D. A test changes the weather after D and checks that D's risks stay the same.

### Growth stage

- **Degree days** (base 0 °C for wheat, 6 °C for maize) from a typical sowing date (wheat 1 Oct, maize 25 Apr). Confidence 0.6.
- **Satellite anchors** from the field's NDVI curve: wheat — spring peak (May–June, ≥ 0.7) = heading BBCH 55, NDVI < 0.5 afterwards = ripening BBCH 83; maize — rise from bare soil after sowing = BBCH 13, summer peak = flowering BBCH 65. The degree-day curve is shifted through the anchor from the day it is confirmed. Confidence 0.8.
- **Farmer's sowing date** replaces the typical one. Confidence 0.85.
- The wheat table was calibrated to the satellite: heading ~1060, ripening ~2135 degree days since 1 January.
- Maize seasons run to 31 December (harvest Sep–Nov); wheat seasons 1 Sep – 31 Aug. Seasons after the current one are not computed (crop unknown).

### Rule kinds

| Kind | Weather / activity term | Example |
|---|---|---|
| `infection_hours` | Hours in the last N days with temperature in the guide's range **and** wet leaves (RH ≥ 95 % or rain) / humid air (RH ≥ 85 % or rain) / humid but dry (RH 50–95 %, no rain); ramp from `hours_low` to `hours_high`. Rain-splash diseases also need rain days. Wheat leaf diseases switch off in cold weather (7-day mean < 3–8 °C). Maize fusarioses also rise with drought (30-day rain − evapotranspiration). | head blight, septoria, rusts |
| `soil_days` | Days with cold (< 12 °C) and wet (≥ 0.30 m³/m³) topsoil | maize seedling blight |
| `snow_days` | Days at ~0–5 °C, wet or under snow, soil not frozen | snow mould |
| `flood` | Days with saturated topsoil or ≥ 30 mm rain | crazy top |
| `vector_days` | Autumn days warm enough for aphids to fly (max ≥ 12 °C) since emergence | barley yellow dwarf virus |
| `pest_activity` | Activity window from degree days (base 10 °C) or the crop stage, × warmth, × local pressure from the field's history | corn borer, rootworm, aphids |

**Growth-stage weight:** 1 inside the threat's susceptible BBCH range, ramping to 0 outside it; 0 before sowing.

**Multipliers (from the field):** previous crop maize (head blight ×1.5, foot rot ×1.3), cereal after cereal (take-all ×1.5, eyespot ×1.5, tan spot ×1.3), maize monoculture (fusarioses ×1.3, corn borer ×1.4; rootworm only from the 2nd maize year), heavy soil (crazy top ×1.3), **last season's peak of the same pathogen ≥ 0.6** (×1.2; Fusarium is shared by maize and wheat).

### Farmer reports

| `kind` | Example from the chat | Effect | Duration |
|---|---|---|---|
| `symptoms` | "I see brown rust on the north field" | score at least 0.6 + 0.3 × severity; confidence 1; spreads to same-crop fields within 3 km as `neighbour` | full 10 days, gone by day 21 |
| `absence` | "Inspected, clean" (`threat_code` empty = all) | × 0.5 | back to normal by day 10 |
| `neighbour` | "My neighbour has head blight" | × (1 + 0.5 × closeness), closeness 1 up to 500 m, 0 at 3 km | full 7 days, gone by day 21 |
| `treatment` | "Sprayed against septoria on 10 May" (empty = all fungal) | × 0.3; action becomes "wait" | full 14 days, gone by day 21 |
| `field_fact` | `{"sowing_date": "2024-09-25"}`, `{"tillage": "reduced"}`, `{"resistant_to": [codes]}` | real sowing date; reduced tillage × 1.3 for residue diseases; resistant variety × 0.6 | rest of the season |
| `event` | `{"type": "hail" / "lodging" / "flood"}` | hail: fungal × 1.3; lodging: fungal × 1.2; flood: crazy top at least 0.7 | 14–28 days |

Every applied report is a driver with its `effect`, and its label is added to the summary. The numbers are team assumptions.

### Actions and spraying window

- `wait` (low, outside the susceptible stage, or protected by a recent treatment), `monitor` (medium; or high but no in-season treatment exists), `treat` (high: inspect now and treat if the guide's threshold is exceeded).
- The threshold shown is the guide's **for the current stage** (Tabela 30 wheat, Tab. 31 maize).
- Spraying window (Tabela 40 kukurydza / 42 pszenica): first forecast day with 1–25 °C, next night ≥ 1 °C, RH 50–95 %, no rain, wind ≤ 4 m/s; "optimal" at 12–20 °C, RH 75–95 %, wind 0.5–1.5 m/s.

### Confidence

`confidence` = stage confidence (0.6 degree days / 0.8 satellite / 0.85 farmer's sowing date) × 0.7 if hourly weather was missing × (1 − 0.06 × days ahead, at least 0.4) for coming days; 1.0 when the farmer reported symptoms.

### Crop

The engine uses `Field.crop`. The crop model ([`cropmodel.py`](cropmodel.py)) checks it: LightGBM on the half-month NDVI curve of the season known so far (slots after today empty), the previous crop, and NDVI at fixed degree-day points; trained on 30 windows × seasons 2020, 2022, 2023 of the crop maps across Opolskie. Its answer is in `field_day()["crop_check"]`, so the farmer can confirm or correct the crop; a corrected crop needs a `predict()` for that field.

## Threats

25 rules in [`catalog.py`](catalog.py), each with the guide's numbers, page-level sources and the team's assumptions marked.

| Crop | Category | Threats (`code`) |
|---|---|---|
| Wheat | fungal | `wheat.fusarium_head_blight`, `wheat.septoria_leaf_blotch`, `wheat.glume_blotch`, `wheat.brown_rust`, `wheat.yellow_rust`, `wheat.powdery_mildew`, `wheat.tan_spot`, `wheat.eyespot`, `wheat.fusarium_foot_rot`, `wheat.take_all`, `wheat.snow_mould` |
| Wheat | pest | `wheat.aphids`, `wheat.cereal_leaf_beetle` |
| Wheat | viral | `wheat.barley_yellow_dwarf` |
| Maize | fungal | `maize.seedling_blight`, `maize.fusarium_ear_rot`, `maize.fusarium_stalk_rot`, `maize.northern_leaf_blight`, `maize.eyespot`, `maize.common_rust`, `maize.crazy_top` |
| Maize | pest | `maize.european_corn_borer`, `maize.western_corn_rootworm`, `maize.aphids`, `maize.frit_fly` |

Main sources: metodyka PSZENICA (Tabela 25–33, 42, rozdz. 13), Metodyka kukurydzy 2019 (pp. 81–140, Tab. 31, 37, 40), `ryzyka_zebrane.xlsx`, GIORiN (Fusarium species, DON).

## Assumptions, limits, validation

- **Not validated against real outbreaks**: the data has none. Ranges and stages come from the guides; *how many hours make a risk high* is the team's choice, calibrated on 2025 near Krapkowice (a dry April, a wet June). Each explanation lists these numbers under `assumptions`.
- Severities (yield loss if a threat materialises) are team assumptions; they only rank fields.
- **The forecast has no precipitation** (the weather data has none; IMERG is not forecast), so the spraying window cannot check rain — the window says so.
- In the historical demo the forecast is the observed weather (a perfect forecast); live forecasts are less certain, hence the lower confidence of coming days.
- Weather is one 4 km cell: fields of one farm share it; they differ by crop, stage, history, soil and reports.
- **Crop model on 534 fields never seen in training (2024):** wheat / maize / other right 74 % by end of May, 77 % by end of August; "wheat" correct 71–80 %, "maize" 86–97 %; wheat vs maize 99–100 % from end of May. Wheat vs other winter cereals is the weak spot, hence the farmer's confirmation.
- Weather risks without a disease (frost, drought, heat) are not threats yet: `Threat.Category` has no such category.

## Open items for other components

| Item | Who | Engine side |
|---|---|---|
| **API endpoints for risks** (`/api/risks/?date=`, `/api/fields/{id}/risks/`, `/api/fields/{id}/risks/{date}/`), optionally `field_day` / `farm_ranking` | Jan + Szymek | ready: `Risk` rows, `engine.summary` |
| **`Observation` table** — columns and values in [Observation rows](#observation-rows) | Jan + Szymek (schema), Ola (writes) | ready: read only through `observations.load_all()` |
| Assistant tools: record a report → `predict(field_ids=[...], start=observed_on)`; "what if" → `what_if()`; "which field first" → `farm_ranking()` | Ola | ready |
| Map: colour by `level` (cut-offs 0.3 / 0.6), "why" panel from `summary` + `drivers`, crop check from `field_day()["crop_check"]` | Kuba | ready |
| Threat codes: use `engine_load_threats`, or a fixture with the same codes | Jan + Szymek | ready |
| New categories `weather` / `soil` / `harvest` for frost, drought, harvest risks | Jan + Szymek | rules would follow |
| **Data issues found:** the weather packages have **no precipitation** (only IMERG); soil `clay`/`sand` are fractions, `BAND_*` are text; grid lat/lon are decimals; hourly year files overlap by one hour; **the 2021 crop map is identical to 2022** (`FieldCropYear` 2021 is wrong) | Jan + Szymek, organisers | handled in the engine |
