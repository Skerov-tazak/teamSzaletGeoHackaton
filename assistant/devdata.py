"""
Synthetic demo data for developing and testing the assistant. NOT the platform's seed.

Used by `python manage.py assistant_dev_seed` (local development, until the platform's import and
the decision engine exist) and by the assistant's tests (a small window). Everything it creates is
marked as synthetic: weather grids start with "DEV_", threats have source "dev_seed", risk
explanations say "dev_seed (syntetyczne)".

Risks are written here only because the engine (Bartek) does not exist yet; in the real system
only the engine writes the Risk table.
"""
from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction

DEV_GRID_PREFIX = "DEV_"
DEV_SOURCE = "dev_seed"

CROP_WHEAT, CROP_MAIZE = 1110, 1130

DEV_FIELDS = [
    # name, crop, area_ha, (lon, lat) of the south-west corner
    ("Pole Północne", CROP_WHEAT, 20.4, (19.950, 50.040)),
    ("Pole przy Lesie", CROP_WHEAT, 12.4, (19.962, 50.036)),
    ("Pole Długie", CROP_WHEAT, 8.7, (19.944, 50.031)),
    ("Kukurydza Zachód", CROP_MAIZE, 15.2, (19.935, 50.025)),
    ("Kukurydza Wschód", CROP_MAIZE, 10.9, (19.970, 50.027)),
]

# English slugs for the codes of the threats we create (only when no real Threat exists).
CODE_HINTS = {
    "septorioza paskowana": "septoria_leaf_blotch", "rdza brunatna": "brown_rust", "rdza żółta": "yellow_rust",
    "mączniak prawdziwy": "powdery_mildew", "fuzarioza kłosów": "fusarium_head_blight",
    "łamliwość źdźbła": "eyespot", "brunatna plamistość": "tan_spot", "septorioza plew": "glume_blotch",
    "fuzarioza kolb": "fusarium_ear_rot", "fuzarioza łodyg": "fusarium_stalk_rot", "zgorzel siewek": "seedling_blight",
    "omacnica": "european_corn_borer", "drobna plamistość": "northern_leaf_spot", "żółta plamistość": "eyespot_maize",
    "rdza kukurydzy": "common_rust", "szalonych wiech": "crazy_top", "mszyce": "aphids", "stonka": "rootworm",
    "ploniarka": "frit_fly", "drutowce": "wireworms", "pędraki": "white_grubs",
}


def _slug(text: str) -> str:
    low = text.lower()
    for k, v in CODE_HINTS.items():
        if k in low:
            return v
    t = low.translate(str.maketrans("ąćęłńóśźż", "acelnoszz"))
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:40]


def _category(threat_type: str, name: str) -> str:
    low = name.lower()
    if threat_type == "szkodnik" or any(w in low for w in ("mszyc", "stonk", "omacnic", "ploniark", "drutow",
                                                           "pędrak", "rolnic", "wciornast", "ślimak", "dzik")):
        return "pest"
    if "bakter" in low:
        return "bacterial"
    if any(w in low for w in ("mozaika", "karłowato", "wirus")):
        return "viral"
    return "fungal"


@dataclass
class DevWorld:
    today: date
    fields: list
    threats: list
    n_risks: int


def _weather_for(day: date, rnd: random.Random) -> dict:
    doy = day.timetuple().tm_yday
    base = 10 + 9 * math.sin((doy - 100) / 365 * 2 * math.pi)  # ~10 °C in April -> ~19 °C in July
    avg = base + rnd.uniform(-3.5, 3.5)
    rain = rnd.choice([0, 0, 0, 0, 0.4, 1.5, 4, 9, 16])
    rh = min(99.0, 62 + rain * 2.2 + rnd.uniform(-8, 10))
    return {
        "avg_temperature": round(avg, 1), "min_temperature": round(avg - rnd.uniform(4, 8), 1),
        "max_temperature": round(avg + rnd.uniform(4, 9), 1), "total_precipitation": float(rain),
        "avg_relative_humidity": round(rh, 1), "max_relative_humidity": round(min(100.0, rh + 12), 1),
        "min_relative_humidity": round(max(20.0, rh - 25), 1), "avg_wind_speed": round(rnd.uniform(5, 22), 1),
    }


def _risk(threat, weather: list[dict], day_idx: int) -> tuple[float, dict]:
    """Toy rule: temperature inside the favourable range x wetness of the last 3 days."""
    w = weather[day_idx]
    last3 = weather[max(0, day_idx - 2): day_idx + 1]
    rain3 = sum(x["total_precipitation"] for x in last3)
    rh3 = sum(x["avg_relative_humidity"] for x in last3) / len(last3)
    t = w["avg_temperature"]
    tmin, tmax = threat.temp_min_c, threat.temp_max_c
    if tmin is not None and tmax is not None:
        temp_fit = 1.0 if tmin <= t <= tmax else max(0.0, 1 - min(abs(t - tmin), abs(t - tmax)) / 6)
        thr = f"{tmin:g}–{tmax:g} °C"
    else:
        temp_fit = max(0.0, min(1.0, (t - 8) / 12))
        thr = "ciepło"
    if threat.category == "pest":
        score = 0.75 * temp_fit + 0.25 * (1 - min(rain3, 20) / 20)
    else:
        wet = 0.6 * min(rh3, 100) / 100 + 0.4 * min(rain3, 15) / 15
        score = temp_fit * (0.25 + 0.75 * wet)
    score = round(max(0.0, min(1.0, score)), 3)
    factors = [
        {"variable": "avg_temperature", "value": t, "unit": "°C", "threshold": thr},
        {"variable": "avg_relative_humidity", "value": round(rh3, 1), "unit": "%", "threshold": "≥ 80 (średnia 3 dni)"},
        {"variable": "total_precipitation", "value": round(rain3, 1), "unit": "mm", "threshold": "suma 3 dni"},
    ]
    in_range = "w zakresie sprzyjającym" if temp_fit >= 1 else "poza zakresem sprzyjającym"
    summary = (f"Średnia temperatura {t:.1f} °C {in_range} ({thr}); wilgotność względna {rh3:.0f}% "
               f"i opady {rain3:.1f} mm w ostatnich 3 dniach.")
    return score, {"summary": summary, "factors": factors, "source": "dev_seed (syntetyczne)"}


def _threat_rows(crop_sheet: str) -> list[dict]:
    from assistant.rag import config
    if not config.RISK_JSON.exists():
        from assistant.rag import excel_parse
        excel_parse.run()
    rows = json.loads(config.RISK_JSON.read_text())
    return [r for r in rows if r["kind"] == "row" and r["crop"] == crop_sheet
            and r["threat_type"] in ("choroba", "szkodnik") and "," not in r["threat"]]


@transaction.atomic
def build(start: date = date(2024, 4, 1), end: date = date(2024, 8, 31), today: date | None = date(2024, 5, 15),
          fields=DEV_FIELDS, seed: int = 7, max_threats_per_crop: int | None = None) -> DevWorld:
    """Create (or replace) the synthetic world. Returns what was created."""
    from core.models import (Clock, CropClass, Field, Risk, Threat, WeatherDaily, WeatherForecastDaily,
                             WeatherGrid)

    wipe()
    rnd = random.Random(seed)
    crops = {
        CROP_WHEAT: CropClass.objects.get_or_create(code=CROP_WHEAT, defaults={"name": "Wheat"})[0],
        CROP_MAIZE: CropClass.objects.get_or_create(code=CROP_MAIZE, defaults={"name": "Maize"})[0],
    }
    prefix = {CROP_WHEAT: "wheat", CROP_MAIZE: "maize"}
    threats = {CROP_WHEAT: [], CROP_MAIZE: []}
    for code, sheet in ((CROP_WHEAT, "pszenica"), (CROP_MAIZE, "kukurydza")):
        rows = _threat_rows(sheet)[: max_threats_per_crop or None]
        for r in rows:
            existing = Threat.objects.filter(crop=crops[code], name__iexact=r["threat"]).first()
            if existing:
                threats[code].append(existing)
                continue
            tcode, n = f"{prefix[code]}.{_slug(r['threat'])}", 2
            while Threat.objects.filter(code=tcode).exists():
                tcode, n = f"{prefix[code]}.{_slug(r['threat'])}_{n}", n + 1
            t = Threat.objects.create(
                code=tcode, crop=crops[code], name=r["threat"],
                category=_category(r["threat_type"], r["threat"]),
                temperature_text=r["temperature_raw"] or "", temp_min_c=r["temp_min_c"], temp_max_c=r["temp_max_c"],
                humidity_text=r["humidity_raw"] or "", other_factors=r["other_factors"] or "",
                source=DEV_SOURCE,
            )
            threats[code].append(t)

    grid = WeatherGrid.objects.create(grid_id=f"{DEV_GRID_PREFIX}G1", lat=50.03, lon=19.95, time_zone="Europe/Warsaw")
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    weather = [_weather_for(d, rnd) for d in days]
    WeatherDaily.objects.bulk_create([WeatherDaily(grid=grid, date=d, **w) for d, w in zip(days, weather)])
    fc = []
    for i, issued in enumerate(days):
        for k in range(1, 8):
            if i + k < len(days):
                fc.append(WeatherForecastDaily(grid=grid, issued_on=issued, date=days[i + k], **weather[i + k]))
    WeatherForecastDaily.objects.bulk_create(fc, batch_size=2000)

    created_fields = []
    for name, crop_code, area, (lon, lat) in fields:
        d = 0.006
        geom = {"type": "Polygon", "coordinates": [[[lon, lat], [lon + d, lat], [lon + d, lat + d / 1.6],
                                                    [lon, lat + d / 1.6], [lon, lat]]]}
        created_fields.append(Field.objects.create(
            name=name, geometry=geom, area_ha=area, centroid_lat=lat + d / 3.2, centroid_lon=lon + d / 2,
            weather_grid=grid, h3_cells=[], crop=crops[crop_code]))

    risks = []
    for f in created_fields:
        frnd = random.Random(f"{seed}-{f.name}")
        for t in threats[f.crop_id]:
            bias = frnd.uniform(-0.12, 0.12)  # fields differ a little
            for i, d in enumerate(days):
                score, expl = _risk(t, weather, i)
                risks.append(Risk(field=f, threat=t, date=d, score=round(max(0, min(1, score + bias)), 3),
                                  explanation=expl))
    Risk.objects.bulk_create(risks, batch_size=5000)

    if today is not None:
        Clock.objects.update_or_create(pk=1, defaults={"today": today})
    return DevWorld(today=today, fields=created_fields, threats=threats[CROP_WHEAT] + threats[CROP_MAIZE],
                    n_risks=len(risks))


@transaction.atomic
def wipe() -> int:
    """Delete everything the dev seed created (DEV_ grids and their fields/weather/risks, dev threats)."""
    from core.models import Field, Risk, Threat, WeatherDaily, WeatherForecastDaily, WeatherGrid

    grids = WeatherGrid.objects.filter(grid_id__startswith=DEV_GRID_PREFIX)
    fields = Field.objects.filter(weather_grid__in=grids)
    n = Risk.objects.filter(field__in=fields).delete()[0]
    n += fields.delete()[0]
    n += WeatherForecastDaily.objects.filter(grid__in=grids).delete()[0]
    n += WeatherDaily.objects.filter(grid__in=grids).delete()[0]
    n += grids.delete()[0]
    n += Threat.objects.filter(source=DEV_SOURCE, risks__isnull=True).delete()[0]
    return n
