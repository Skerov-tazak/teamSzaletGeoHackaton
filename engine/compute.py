"""
The engine's entry point, as agreed in docs/interfaces.md:

    predict(field_ids=None, start=None, end=None) -> int

Computes the risk of every threat of each field's crop, for every day from `start` to `end`
(default: the current season, 1 September .. today + 7), and overwrites them in Risk in one bulk
write. Each day is assessed as of that day: features are trailing windows over weather observed up
to that day (see engine/features.py), and the spraying window comes from the forecast issued that day.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
from django.db import transaction
from django.utils import timezone

from core import clock
from core.models import Field, Risk, Threat, WeatherForecastDaily
from engine import features as F
from engine import observations as OBS
from engine.catalog import CARRYOVER, MAIZE, RULES, rules_for_crop
from engine.phenology import bbch_series, degree_days_base10
from engine.satellite.season import season_bounds, season_of
from engine.scoring import FieldContext, score_rule, spray_window

log = logging.getLogger(__name__)


def predict(field_ids: list[int] | None = None, start: date | None = None, end: date | None = None,
            observations: list | None = None) -> int:
    """
    `observations`: optional farmer reports (engine.observations.Report) to use instead of the
    Observation table, e.g. in tests or a scripted demo. Each report affects days >= its date only.
    """
    today = clock.today()
    end = end or today + timedelta(days=clock.FORECAST_DAYS)
    start = start or season_bounds(season_of(today))[0]
    if start > end:
        return 0
    fields = Field.objects.select_related("crop", "weather_grid")
    if field_ids is not None:
        fields = fields.filter(id__in=field_ids)
    threats = {t.code: t for t in Threat.objects.all()}
    rows: list[Risk] = []
    now = timezone.now()
    for field in fields:
        reports = OBS.for_field(observations, field.id) if observations is not None else OBS.load(field.id, start, end)
        rows += _field_rows(field, threats, start, end, now, reports)
    with transaction.atomic():
        Risk.objects.bulk_create(
            rows, batch_size=2000, update_conflicts=True,
            unique_fields=["field", "threat", "date"], update_fields=["score", "explanation", "computed_at"],
        )
    log.info("predict: %d risk rows for %d fields, %s..%s", len(rows), len(fields), start, end)
    return len(rows)


def field_context(field: Field, season: int, crop_code: int | None = None, crop_source: str = "field") -> FieldContext:
    crop = crop_code or field.crop_id
    history = {}
    names = {}
    for fcy in field.crop_years.select_related("crop_class").all():
        best = history.get(fcy.year)
        if best is None or fcy.share > best[1]:
            history[fcy.year] = (fcy.crop_class_id, fcy.share)
            names[fcy.year] = fcy.crop_class.name
    prev = history.get(season - 1)
    in_row = 1 if crop == MAIZE else 0
    if crop == MAIZE:
        y = season - 1
        while history.get(y, (None,))[0] == MAIZE:
            in_row += 1
            y -= 1
    soil = {}
    cells = list(field.soil_cells().values("clay", "sand", "ph"))
    for key in ("clay", "sand", "ph"):
        vals = [c[key] for c in cells if c[key] is not None]
        if vals:
            soil[key] = sum(vals) / len(vals)
    for key in ("clay", "sand"):  # the soil package stores fractions (0.18), the doc says % (18): accept both
        if key in soil and soil[key] <= 1.0:
            soil[key] *= 100
    return FieldContext(crop=crop, crop_source=crop_source, previous_crop=prev[0] if prev else None,
                        previous_crop_name=names.get(season - 1), maize_years_in_row=in_row, soil=soil)


def season_crop(field: Field, season: int) -> tuple[int | None, str]:
    """
    The crop of a field in a season. Field.crop is the crop of the current season (the clock's); for
    earlier seasons the crop map says what grew there (largest share), so last season is scored with
    last season's crop.
    """
    if season >= season_of(clock.today()):
        return field.crop_id, "field"
    best = field.crop_years.filter(year=season).order_by("-share").values_list("crop_class_id", flat=True).first()
    return best, "crop map"


def _field_rows(field: Field, threats: dict, start: date, end: date, now, reports=()) -> list[Risk]:
    out: list[Risk] = []
    s = start
    while s <= end:  # a range may cross 1 September: score each season separately
        season = season_of(s)
        s_end = min(end, season_bounds(season)[1])
        crop, source = season_crop(field, season)
        rules = [r for r in rules_for_crop(crop) if r.code in threats] if crop else []
        if rules:
            out += _season_rows(field, threats, rules, season, s, s_end, now, reports, crop, source)
        s = s_end + timedelta(days=1)
    return out


def _season_rows(field, threats, rules, season, start, end, now, reports=(), crop=None, crop_source="field") -> list[Risk]:
    grid = field.weather_grid_id
    load_start = min(start, season_bounds(season)[0])
    daily = F.load_daily(grid, load_start, end)
    if daily.empty:
        log.warning("predict: no daily weather for grid %s, %s..%s", grid, load_start, end)
        return []
    hourly = F.load_hourly(grid, load_start, end)
    days = pd.date_range(max(pd.Timestamp(start), daily.index.min()), min(pd.Timestamp(end), daily.index.max()), freq="D")
    if len(days) == 0:
        return []
    ctx = field_context(field, season, crop_code=crop, crop_source=crop_source)
    ctx.last_season = last_season_peaks(field, season)
    stages = bbch_series(ctx.crop, daily["avg_temperature"], season)
    sow = OBS.sowing_override([r for r in reports if r.observed_on <= end])
    if sow:  # the farmer's sowing date replaces the assumed one from the day it was reported
        told = bbch_series(ctx.crop, daily["avg_temperature"], season, sowing=sow[0])
        use = told.index >= pd.Timestamp(sow[1])
        stages = stages.copy()
        stages.loc[use] = told.loc[use]
    dd10 = degree_days_base10(daily["avg_temperature"], season)
    out = []
    forecast_cache: dict[date, pd.DataFrame] = {}
    for rule in rules:
        for res in score_rule(rule, ctx, daily, hourly, stages, dd10, days, reports):
            if res.explanation["action"]["type"] == "treat":
                fc = forecast_cache.get(res.day)
                if fc is None:
                    fc = _forecast(grid, res.day)
                    forecast_cache[res.day] = fc
                res.explanation["action"]["spray_window"] = spray_window(fc)
            out.append(Risk(field=field, threat=threats[rule.code], date=res.day, score=res.score,
                            explanation=res.explanation, computed_at=now))
    return out


def last_season_peaks(field: Field, season: int) -> dict:
    """Peak risk per threat on this field in the previous season (from earlier predict() runs)."""
    from django.db.models import Max

    s0, s1 = season_bounds(season - 1)
    peaks = {}
    rows = (Risk.objects.filter(field=field, date__range=(s0, s1)).values("threat__code", "threat__name")
            .annotate(peak=Max("score")))
    by_code = {r["threat__code"]: r for r in rows}
    for code, sources in CARRYOVER.items():
        best = max((by_code[c] for c in sources if c in by_code), key=lambda r: r["peak"], default=None)
        if best:
            day = Risk.objects.filter(field=field, threat__code=best["threat__code"], date__range=(s0, s1),
                                      score=best["peak"]).values_list("date", flat=True).first()
            peaks[code] = {"peak": best["peak"], "date": day.isoformat() if day else None, "threat": best["threat__name"]}
    return peaks


def _forecast(grid: str, day: date) -> pd.DataFrame:
    cols = ["date", "max_temperature", "min_temperature", "total_precipitation", "avg_wind_speed"]
    qs = WeatherForecastDaily.objects.current(as_of=day).filter(grid_id=grid).order_by("date").values(*cols)
    df = pd.DataFrame.from_records(qs, columns=cols)
    return df.set_index("date") if not df.empty else df


__all__ = ["predict", "field_context", "RULES"]
