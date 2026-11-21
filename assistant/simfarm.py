"""
Realistic SIMULATED farm for demos and chat testing, until the platform imports the organisers' data.

What is simulated (inputs only — the decision engine computes the risks):
* a farm of 6 fields SW of Krapkowice (Opolskie), where the engine was calibrated: 3 winter wheat,
  3 maize, each with a 2020–2024 crop history that matters to the engine's rules (wheat after maize,
  cereal after cereal, maize monoculture, a good rotation);
* weather for one 4 km grid cell, 2023-07-01 … 2025-10-31: daily + hourly, with a climatology of
  Opole (monthly temperatures and precipitation), persistent anomalies, a wet/dry Markov chain, a soil
  moisture bucket and snow; season 2025 has the pattern the engine was calibrated on (dry April, wet
  first half of June); forecasts are the observed weather issued day by day (as the platform does);
* soil cells (H3 level 10) with loess-loam values typical for the area, in the real files' formats
  (sand/silt/clay as fractions 0–1, BAND_* as text);
* a few farmer reports in core.Observation (docs/database.md -> Observation);
* Clock = 2025-06-10 (winter wheat flowering in a wet spell, maize at a few leaves).

Then the real engine runs: engine_load_threats + predict (previous season first, then 2025).
Everything is marked: weather grid "SIM_…", reports details.source = "sim_farm".
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction

SIM_GRID = "SIM_KRAPKOWICE"
TZ = ZoneInfo("Europe/Warsaw")
WEATHER_START, WEATHER_END = date(2023, 7, 1), date(2025, 10, 31)
FORECAST_FROM = date(2024, 1, 15)
TODAY = date(2025, 6, 10)

LEGEND = {0: "No cropland", 1110: "Wheat", 1120: "Barley", 1130: "Maize", 1140: "Rice", 1150: "Other cereals",
          1210: "Fresh vegetables", 1220: "Dry pulses", 1310: "Potatoes", 1320: "Sugar beet", 1410: "Sunflower",
          1420: "Soybeans", 1430: "Rapeseed", 1440: "Flax, cotton and hemp", 2100: "Grapes", 2200: "Olives",
          2310: "Fruits", 2320: "Nuts", 3100: "Unclassified arable crop", 3200: "Unclassified permanent crop"}
W, B, M, R, S = 1110, 1120, 1130, 1430, 1320


@dataclass
class SimField:
    name: str
    crop: int
    corner: tuple[float, float]      # lon, lat of the SW corner
    size: tuple[float, float]        # degrees lon, lat
    history: dict[int, int]          # year -> crop class (2020..2024)
    story: str                       # why this field is interesting


FIELDS = [
    SimField("Za Stodołą", W, (17.668, 50.352), (0.0062, 0.0030), {2020: M, 2021: W, 2022: R, 2023: W, 2024: M},
             "pszenica po kukurydzy — resztki kukurydzy przenoszą fuzariozę"),
    SimField("Przy Odrze", W, (17.701, 50.361), (0.0055, 0.0032), {2020: B, 2021: W, 2022: S, 2023: W, 2024: R},
             "dobre stanowisko po rzepaku"),
    SimField("Długie", W, (17.652, 50.343), (0.0110, 0.0016), {2020: W, 2021: R, 2022: W, 2023: B, 2024: W},
             "zboże po zbożu — łamliwość źdźbła, zgorzel podstawy źdźbła"),
    SimField("Kukurydza Krępna", M, (17.684, 50.338), (0.0070, 0.0035), {2020: M, 2021: W, 2022: M, 2023: M, 2024: M},
             "kukurydza trzeci rok z rzędu — omacnica, stonka, fuzariozy"),
    SimField("Pod Lasem", M, (17.640, 50.356), (0.0048, 0.0030), {2020: W, 2021: M, 2022: W, 2023: R, 2024: W},
             "kukurydza po pszenicy, przy lesie (dziki)"),
    SimField("Kukurydza przy Drodze", M, (17.712, 50.347), (0.0060, 0.0026), {2020: S, 2021: W, 2022: M, 2023: W, 2024: M},
             "kukurydza po kukurydzy"),
]

# Opole climatology: monthly mean temperature (°C) and precipitation (mm)
T_MONTH = [-0.8, 0.6, 4.3, 9.6, 14.4, 17.6, 19.6, 19.1, 14.6, 9.4, 4.4, 0.6]
P_MONTH = [33, 30, 38, 40, 66, 76, 92, 72, 54, 40, 40, 38]
P_WET = [0.40, 0.38, 0.40, 0.36, 0.42, 0.44, 0.42, 0.38, 0.36, 0.36, 0.42, 0.42]


def _clim_temp(d: date) -> float:
    """Daily climatological mean, interpolated between mid-month values."""
    m = d.month - 1
    mid = date(d.year, d.month, 15)
    if d >= mid:
        nxt = (m + 1) % 12
        span = 30.4
        frac = (d - mid).days / span
        return T_MONTH[m] + (T_MONTH[nxt] - T_MONTH[m]) * frac
    prv = (m - 1) % 12
    frac = (mid - d).days / 30.4
    return T_MONTH[m] + (T_MONTH[prv] - T_MONTH[m]) * frac


def _scenario(d: date) -> tuple[float, float, float]:
    """(temperature shift °C, wet-probability factor, amount factor) for the 2025 storyline."""
    if d.year == 2025 and d.month == 4:
        return 1.2, 0.30, 0.7            # dry, mild April
    if d.year == 2025 and d.month == 5 and d.day <= 20:
        return 0.0, 0.8, 0.9
    if d.year == 2025 and d.month == 6 and 3 <= d.day <= 12:
        return 0.8, 1.45, 1.1            # warm, showery spell around wheat flowering
    if d.year == 2025 and d.month == 7:
        return 1.0, 0.9, 1.0
    return 0.0, 1.0, 1.0


def _magnus_dew(t: float, rh: float) -> float:
    a, b = 17.62, 243.12
    g = math.log(max(rh, 1) / 100) + a * t / (b + t)
    return b * g / (a - g)


def simulate_daily(seed: int = 2025) -> list[dict]:
    rnd = random.Random(seed)
    days = []
    anom, wet_prev, sm, soil_t, snow = 0.0, False, 0.30, 5.0, 0.0
    d = WEATHER_START
    while d <= WEATHER_END:
        m = d.month - 1
        t_shift, wet_f, amt_f = _scenario(d)
        anom = 0.82 * anom + rnd.gauss(0, 1.5)
        t = _clim_temp(d) + anom + t_shift
        p_wet = min(0.9, P_WET[m] * wet_f * (1.35 if wet_prev else 0.8))
        wet = rnd.random() < p_wet
        mean_amt = P_MONTH[m] / (30.4 * P_WET[m])
        rain = round(rnd.gammavariate(0.75, mean_amt / 0.75) * amt_f, 1) if wet else 0.0
        if wet and rain < 0.2:
            rain = 0.2
        seasonal = math.sin(2 * math.pi * (d.timetuple().tm_yday - 105) / 365)
        dtr = (8.0 + 3.5 * seasonal) * (0.6 if rain > 2 else 1.0) + rnd.uniform(-1.2, 1.2)
        rh = 76 - 11 * seasonal + (8 if rain > 1 else 0) - 0.6 * anom + rnd.uniform(-6, 5)
        rh = max(45.0, min(98.0, rh))
        ra = 9.5 + 7.0 * math.sin(2 * math.pi * (d.timetuple().tm_yday - 80) / 365)   # mm/day, lat 50
        eto = max(0.0, 0.0023 * ra * (t + 17.8) * math.sqrt(max(dtr, 1))) * (0.7 if rain > 2 else 1.0)
        soil_t = 0.7 * soil_t + 0.3 * (t + 0.8)
        if t < 0 and rain:
            snow += rain
            rain_to_soil = 0.0
        else:
            melt = min(snow, max(0.0, t) * 2.5)
            snow -= melt
            rain_to_soil = rain + melt
        sm = max(0.12, min(0.42, sm + (rain_to_soil - 0.85 * eto) / 75))
        wind = max(2.0, rnd.gammavariate(4, 3.2) + (2.5 if d.month in (11, 12, 1, 2, 3) else 0))
        days.append({
            "date": d, "avg_temperature": round(t, 1), "min_temperature": round(t - dtr / 2, 1),
            "max_temperature": round(t + dtr / 2, 1), "midpoint_temperature": round(t, 1),
            "total_precipitation": rain, "avg_relative_humidity": round(rh, 1),
            "max_relative_humidity": round(min(100.0, rh + 13), 1), "min_relative_humidity": round(max(20.0, rh - 24), 1),
            "avg_dew_point_temperature": round(_magnus_dew(t, rh), 1), "avg_wind_speed": round(wind, 1),
            "max_wind_gust": round(wind * 2.1, 1), "eto": round(eto, 2),
            "avg_soil_temperature_level_1": round(soil_t, 1), "min_soil_temperature_level_1": round(soil_t - 1.8, 1),
            "max_soil_temperature_level_1": round(soil_t + 2.0, 1), "avg_soil_moisture_level_1": round(sm, 3),
            "avg_snow_depth": round(snow, 1), "avg_total_cloud_cover": round(min(1.0, 0.35 + (0.5 if wet else 0) + rnd.uniform(-0.15, 0.15)), 2),
            "total_downward_solar_radiation": round(ra * 2.45 * (0.45 if wet else 0.7), 1),
            "day_length": round(12.2 + 4.1 * math.sin(2 * math.pi * (d.timetuple().tm_yday - 80) / 365), 1),
        })
        wet_prev = wet
        d += timedelta(days=1)
    return days


def simulate_hourly(daily: list[dict], seed: int = 2025) -> list[dict]:
    rnd = random.Random(seed + 1)
    out = []
    for day in daily:
        t, dtr = day["avg_temperature"], day["max_temperature"] - day["min_temperature"]
        rh = day["avg_relative_humidity"]
        rain = day["total_precipitation"]
        rain_hours = set()
        if rain > 0:
            n = max(1, min(14, int(rain / 1.5) + rnd.randint(1, 4)))
            start = rnd.randint(0, 23)
            rain_hours = {(start + i) % 24 for i in range(n)}
        start_utc = datetime.combine(day["date"], time(0), tzinfo=TZ).astimezone(ZoneInfo("UTC"))
        end_utc = datetime.combine(day["date"] + timedelta(days=1), time(0), tzinfo=TZ).astimezone(ZoneInfo("UTC"))
        n_hours = int((end_utc - start_utc).total_seconds() // 3600)   # 23/24/25 around DST changes
        for i in range(n_hours):
            utc = start_utc + timedelta(hours=i)
            h = utc.astimezone(TZ).hour
            temp = t + dtr / 2 * math.cos(2 * math.pi * (h - 15) / 24)
            rel = rh - (temp - t) / max(dtr / 2, 0.5) * 11 + rnd.uniform(-2, 2)
            if h in rain_hours:
                rel = max(rel, 93 + rnd.uniform(0, 6))
            elif rel > 94:
                rel = 94 - rnd.uniform(0, 3) if rnd.random() < 0.7 else rel  # dew only on some nights
            rel = max(30.0, min(100.0, rel))
            out.append({"utc_time": utc, "date": day["date"],
                        "temperature": round(temp, 1), "relative_humidity": round(rel, 1),
                        "precipitation": round(rain / len(rain_hours), 2) if h in rain_hours else 0.0,
                        "dew_point_temperature": round(_magnus_dew(temp, rel), 1),
                        "wind_speed": day["avg_wind_speed"]})
    return out


def _polygon(f: SimField):
    from shapely.geometry import Polygon
    lon, lat = f.corner
    dx, dy = f.size
    # a slightly irregular quadrilateral, like a real parcel
    return Polygon([(lon, lat), (lon + dx, lat + dy * 0.08), (lon + dx * 0.97, lat + dy),
                    (lon + dx * 0.02, lat + dy * 0.94), (lon, lat)])


def _area_ha(poly) -> float:
    from pyproj import Transformer
    from shapely.ops import transform
    to_2180 = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True).transform
    return transform(to_2180, poly).area / 10_000


@transaction.atomic
def wipe() -> int:
    from core.models import Field, Risk, SoilCell, WeatherDaily, WeatherForecastDaily, WeatherGrid, WeatherHourly

    from core.models import Observation
    grids = WeatherGrid.objects.filter(grid_id=SIM_GRID)
    fields = Field.objects.filter(weather_grid__in=grids)
    cells = [c for f in fields for c in f.h3_cells]
    n = Observation.objects.filter(field__in=fields).delete()[0]
    n += Risk.objects.filter(field__in=fields).delete()[0]
    n += fields.delete()[0]
    n += SoilCell.objects.filter(h3_index_10__in=cells).delete()[0]
    for model in (WeatherHourly, WeatherForecastDaily, WeatherDaily):
        n += model.objects.filter(grid__in=grids).delete()[0]
    n += grids.delete()[0]
    return n


@transaction.atomic
def build(seed: int = 2025, today: date = TODAY, log=print) -> dict:
    import h3
    from shapely.geometry import mapping

    from core.models import (Clock, CropClass, Field, FieldCropYear, SoilCell, WeatherDaily, WeatherForecastDaily,
                             WeatherGrid, WeatherHourly)

    wipe()
    for code, name in LEGEND.items():
        CropClass.objects.get_or_create(code=code, defaults={"name": name})
    grid = WeatherGrid.objects.create(grid_id=SIM_GRID, lat=50.35, lon=17.68, geohash4="u3hq", time_zone="Europe/Warsaw")

    daily = simulate_daily(seed)
    WeatherDaily.objects.bulk_create([WeatherDaily(grid=grid, **d) for d in daily], batch_size=2000)
    hourly = simulate_hourly(daily, seed)
    WeatherHourly.objects.bulk_create([WeatherHourly(grid=grid, **h) for h in hourly], batch_size=5000)
    by_date = {d["date"]: d for d in daily}
    fc = []
    issued = FORECAST_FROM
    while issued <= WEATHER_END:
        for k in range(1, 8):
            d = issued + timedelta(days=k)
            if d in by_date:
                fc.append(WeatherForecastDaily(grid=grid, issued_on=issued,
                                               **{c: v for c, v in by_date[d].items()}))
        issued += timedelta(days=1)
    WeatherForecastDaily.objects.bulk_create(fc, batch_size=5000)
    log(f"weather: {len(daily)} days, {len(hourly)} hours, {len(fc)} forecast rows")

    rnd = random.Random(seed + 2)
    fields = []
    for sf in FIELDS:
        poly = _polygon(sf)
        cells = sorted(h3.geo_to_cells(mapping(poly), 10)) or [h3.latlng_to_cell(poly.centroid.y, poly.centroid.x, 10)]
        f = Field.objects.create(name=sf.name, geometry=mapping(poly), area_ha=round(_area_ha(poly), 2),
                                 centroid_lat=poly.centroid.y, centroid_lon=poly.centroid.x, weather_grid=grid,
                                 h3_cells=cells, crop_id=sf.crop)
        for year, crop in sf.history.items():
            edge = round(rnd.uniform(0.01, 0.05), 3)
            FieldCropYear.objects.create(field=f, year=year, crop_class_id=crop, share=round(1 - edge, 3))
            FieldCropYear.objects.create(field=f, year=year, crop_class_id=0, share=edge)
        for c in cells:
            # real-file formats (core.SoilCell): sand/silt/clay as fractions 0-1, BAND_* as text
            clay = rnd.uniform(0.14, 0.24)
            sand = rnd.uniform(0.15, 0.30)
            ph, om, cec = rnd.uniform(6.0, 7.1), rnd.uniform(1.6, 2.9), rnd.uniform(11, 19)
            SoilCell.objects.update_or_create(h3_index_10=c, defaults={
                "clay": round(clay, 3), "sand": round(sand, 3), "silt": round(1 - clay - sand, 3),
                "ph": round(ph, 1), "om": round(om, 2), "cec": round(cec, 1), "bulk_density": round(rnd.uniform(1.3, 1.5), 2),
                "band_om": "low" if om < 2 else "moderate", "band_cec": "moderate", "band_ph": "moderate",
                "soil_texture": "silt loam" if clay < 0.20 else "loam"})
        fields.append(f)
        log(f"field {f.id}: {f.name} ({LEGEND[f.crop_id]}, {f.area_ha} ha, {len(cells)} H3 cells) — {sf.story}")
    Clock.objects.update_or_create(pk=1, defaults={"today": today})
    return {"fields": fields, "today": today}


# farmer reports already given in the chat before the demo day (core.Observation, docs/database.md)
OBSERVATIONS = [
    # field, observed_on, kind, category, threat code, severity 0-1, distance_m, details, text
    ("Za Stodołą", date(2024, 10, 8), "field_fact", "other", None, None, None, {"sowing_date": "2024-10-08"},
     "Siałem 8 października, po kukurydzy na ziarno."),
    ("Długie", date(2025, 4, 2), "field_fact", "other", None, None, None, {"tillage": "reduced"},
     "Na Długim nie orałem, tylko talerzówka po pszenicy."),
    ("Przy Odrze", date(2025, 5, 28), "absence", "disease", None, None, None, {},
     "Przeszedłem całe pole przy Odrze, liście czyste, nie widzę ani rdzy, ani plam."),
    ("Długie", date(2025, 6, 2), "symptoms", "disease", "wheat.septoria_leaf_blotch", 0.6, None, {},
     "Na dolnych liściach brunatne plamy z czarnymi kropkami, na co trzeciej roślinie."),
    ("Kukurydza Krępna", date(2025, 6, 6), "neighbour", "pest", "maize.european_corn_borer", None, 600.0, {},
     "Sąsiad mówi, że u niego za drogą lata już omacnica."),
]


def add_observations(log=print, field_filter: dict | None = None) -> int:
    from core.models import Field, Observation, Threat
    n = 0
    for name, d, kind, cat, threat, sev, dist, details, text in OBSERVATIONS:
        f = Field.objects.filter(name=name, **(field_filter or {"weather_grid_id": SIM_GRID})).first()
        if f is None:
            continue
        Observation.objects.create(
            field=f, observed_on=d, kind=kind, category=cat,
            threat=Threat.objects.filter(code=threat).first() if threat else None, severity=sev, distance_m=dist,
            details=details | {"source": "sim_farm"}, text=text,
            idempotency_key=f"sim_farm:{name}:{d.isoformat()}:{kind}")
        n += 1
        log(f"report {d} {name}: {kind} — {text}")
    return n
