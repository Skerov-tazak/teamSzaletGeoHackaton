"""
Demo farm on the organisers' REAL data (DATA_DIR, see engine/README.md -> data files):

* fields: real parcels SW of Krapkowice (Opolskie) cut from the 2024 crop map (the engine's parcel
  finder: one class in 2024 and in 2023, 5-40 ha), with the demo farm's names;
* crop history 2020-2024: shares of crop-map classes inside each polygon (FieldCropYear);
* this season's crop (2025): there is no 2025 crop map, so the crop is what the farmer declares;
  the plan below picks parcels whose real 2024 crop gives each field its story (wheat after maize, …);
* weather: daily + hourly packages 2023-2025 for the fields' grid cells, rain from IMERG (the
  packages have none), forecasts = observed weather issued day by day (as the platform seed does);
* soil: ISRIC 250 m values for the fields' H3 cells;
* farmer reports: the same chat reports as the simulated farm (core.Observation).

Needs in DATA_DIR: cropland/cropland_<2020..2024>.tif (engine/scripts/clip_cropland.py),
weather/weather_grids.parquet, soil/Opolskie_isric_250_v2.parquet, raw/weather_data/... zips.
"""
from __future__ import annotations

from datetime import date

from django.db import transaction

from . import simfarm

REGION = "Opolskie"
BBOX = (17.62, 50.32, 17.74, 50.40)  # farmland SW of Krapkowice (engine calibration area)
TODAY = simfarm.TODAY
WEATHER_YEARS = [2023, 2024, 2025]
W, M, R = 1110, 1130, 1430

# name, crop 2025 (farmer), preferred real crop 2024 (in order), story
PLAN = [
    ("Za Stodołą", W, [M], "pszenica po kukurydzy — resztki kukurydzy przenoszą fuzariozę"),
    ("Przy Odrze", W, [R, 1320, 1310, 1120], "pszenica po roślinie niezbożowej"),
    ("Długie", W, [W, 1120, 1150], "zboże po zbożu — łamliwość źdźbła, zgorzel podstawy źdźbła"),
    ("Kukurydza Krępna", M, [M], "kukurydza po kukurydzy — omacnica, stonka, fuzariozy"),
    ("Pod Lasem", M, [W, 1120], "kukurydza po zbożu"),
    ("Kukurydza przy Drodze", M, [M, W], "kukurydza"),
]
NAMES = [p[0] for p in PLAN]


def _seed_cmd():
    from engine.management.commands.engine_dev_seed import Command, data_dir
    return Command(), data_dir()


def check_files() -> list[str]:
    """Missing input files (empty list = ready)."""
    _, D = _seed_cmd()
    need = [D / "cropland" / f"cropland_{y}.tif" for y in range(2020, 2025)]
    need += [D / "weather" / "weather_grids.parquet", D / "soil" / f"{REGION}_isric_250_v2.parquet",
             D / "raw" / "weather_data" / "imerg_precipitation_daily.zip",
             D / "raw" / "weather_data" / "imerg_precipitation_hourly.zip"]
    for y in WEATHER_YEARS:
        need += [D / "raw" / "weather_data" / kind / str(y) / f"weather_{kind}_{y}_{REGION}.zip" for kind in ("daily", "hourly")]
    return [str(p) for p in need if not p.exists()]


@transaction.atomic
def wipe() -> int:
    from core.models import (Field, Observation, Risk, SoilCell, WeatherDaily, WeatherForecastDaily, WeatherGrid,
                             WeatherHourly)
    n = simfarm.wipe()
    fields = Field.objects.filter(name__in=NAMES)
    grids = set(fields.values_list("weather_grid_id", flat=True))
    cells = [c for f in fields for c in f.h3_cells]
    n += Observation.objects.filter(field__in=fields).delete()[0]
    n += Risk.objects.filter(field__in=fields).delete()[0]
    n += fields.delete()[0]
    n += SoilCell.objects.filter(h3_index_10__in=cells).delete()[0]
    unused = [g for g in grids if not Field.objects.filter(weather_grid_id=g).exists()]
    for model in (WeatherHourly, WeatherForecastDaily, WeatherDaily):
        n += model.objects.filter(grid_id__in=unused).delete()[0]
    n += WeatherGrid.objects.filter(grid_id__in=unused).delete()[0]
    return n


def _pick_parcels(cmd, D) -> list[tuple[tuple, dict]]:
    parcels = cmd.parcels(D, BBOX, 2024, 12, codes=(W, 1120, 1150, M, R, 1310, 1320))
    used, out = set(), []
    for plan in PLAN:
        _, _, prefer, _ = plan
        pick = next((i for code in prefer for i, p in enumerate(parcels) if i not in used and p["crop_prev"] == code), None)
        if pick is None:  # no parcel with the preferred 2024 crop: any free one
            pick = next((i for i in range(len(parcels)) if i not in used), None)
        if pick is None:
            raise RuntimeError(f"Za mało działek na mapie upraw w {BBOX} dla pola {plan[0]}.")
        used.add(pick)
        out.append((plan, parcels[pick]))
    return out


@transaction.atomic
def build(today: date = TODAY, log=print) -> dict:
    import pandas as pd

    from core.models import Clock, CropClass, FieldCropYear

    missing = check_files()
    if missing:
        raise FileNotFoundError("Brak plików z danymi organizatorów:\n  " + "\n  ".join(missing))
    wipe()
    cmd, D = _seed_cmd()
    cmd.stdout.write = lambda msg, *a, **k: log(str(msg).rstrip())
    for code, name in simfarm.LEGEND.items():
        CropClass.objects.update_or_create(code=code, defaults={"name": name})
    grids = pd.read_parquet(D / "weather" / "weather_grids.parquet", columns=["grid_id", "lat", "lon"])
    grids[["lat", "lon"]] = grids[["lat", "lon"]].astype(float)
    fields = []
    for i, ((name, crop, _, story), parcel) in enumerate(_pick_parcels(cmd, D), 1):
        f = cmd.make_field(D, parcel | {"crop": crop}, i, grids, name=name)
        hist = []
        for y in range(2020, 2025):
            top = FieldCropYear.objects.filter(field=f, year=y).order_by("-share").first()
            hist.append(f"{y}: {simfarm.LEGEND.get(top.crop_class_id, top.crop_class_id) if top else '?'}")
        log(f"field {f.id}: {f.name} ({simfarm.LEGEND[crop]} 2025, {f.area_ha} ha, grid {f.weather_grid_id}) — "
            f"{story}; mapa upraw: {', '.join(hist)}")
        fields.append(f)
    grid_ids = sorted({f.weather_grid_id for f in fields})
    cmd.load_weather(D, REGION, grid_ids, WEATHER_YEARS)
    cmd.seed_forecast(grid_ids, date(WEATHER_YEARS[0], 12, 1), date(WEATHER_YEARS[-1], 12, 31))
    cmd.load_soil(D, REGION, {c for f in fields for c in f.h3_cells})
    Clock.objects.update_or_create(pk=1, defaults={"today": today})
    return {"fields": fields, "today": today}


def add_observations(log=print) -> int:
    return simfarm.add_observations(log=log, field_filter={"name__in": NAMES})
