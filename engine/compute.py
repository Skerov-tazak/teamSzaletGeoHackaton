"""
The engine's entry points, as agreed in docs/interfaces.md and docs/engine-predict-review.md:

    predict(field_ids=None, start=None, end=None) -> PredictResult   (an int: rows written, + .field_ids)
    clock_moved(old, new) -> PredictResult                            (the platform calls it when the demo date moves)
    precompute_season(season=None) -> PredictResult                   (the demo seed calls it once)

Computes the risk of every threat of each field's crop, for every day from `start` to `end`, and
overwrites them in Risk in one transaction. Which weather a day is assessed with:

    day <= today                 weather observed up to that day ("as of that day")
    today < day <= today + 7     weather observed up to today, then the forecast issued today (coming days)
    day > today + 7              weather observed up to that day; only the demo precompute writes these, and
                                 clock_moved() recomputes them as coming days once the date gets within 7 days

Features are trailing windows (engine/features.py), so a day never reads weather after itself.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from core import clock
from core.models import Field, Risk, Threat, WeatherDaily, WeatherForecastDaily
from engine import features as F
from engine import observations as OBS
from engine.catalog import CARRYOVER, MAIZE, RULES, rules_for_crop
from engine.phenology import bbch_series, calibrate, degree_days_base10, season_end
from engine.satellite.season import season_bounds, season_of
from engine.scoring import FieldContext, score_rule, spray_window

log = logging.getLogger(__name__)


SPREAD_RADIUS_M = 3000  # symptoms on one field raise the risk on fields of the same crop within this distance


class PredictResult(int):
    """
    The number of Risk rows written (an int, so callers that only count keep working), plus
    `.field_ids`: every field whose rows were rewritten, including nearby fields that a symptoms report
    spread to (the assistant returns them in updated_field_ids so the map reloads them).
    """

    def __new__(cls, rows: int = 0, field_ids=()):
        obj = super().__new__(cls, rows)
        obj.field_ids = sorted(set(field_ids))
        return obj

    def __add__(self, other):
        return PredictResult(int(self) + int(other), list(self.field_ids) + list(getattr(other, "field_ids", [])))

    def __repr__(self):
        return f"PredictResult({int(self)}, field_ids={self.field_ids})"


def last_computable_day(today: date | None = None) -> date | None:
    """The last day that has weather: observed (demo) or in the forecast issued today (live)."""
    today = today or clock.today()
    obs = WeatherDaily.objects.aggregate(m=Max("date"))["m"]
    fc = WeatherForecastDaily.objects.current(as_of=today).aggregate(m=Max("date"))["m"]
    days = [d for d in (obs, fc) if d is not None]
    return max(days) if days else None


def predict(field_ids: list[int] | None = None, start: date | None = None, end: date | None = None,
            observations: list | None = None) -> PredictResult:
    """
    start: default the season start (1 September).
    end:   default the later of today + 7 and the last day already stored for these fields, so a
           recompute after a farmer report or a crop change also replaces the precomputed days.
    `observations`: optional farmer reports (engine.observations.Report) to use instead of the
    Observation table, e.g. in tests or a scripted demo. Each report affects days >= its date only.
    Symptoms reported on a field also raise the risk on nearby fields of the same crop, so those
    fields are recomputed too (and listed in the result's .field_ids).
    """
    today = clock.today()
    start = start or season_bounds(season_of(today))[0]
    if end is None:
        stored = Risk.objects.filter(**({"field_id__in": field_ids} if field_ids is not None else {}))
        last = stored.aggregate(m=Max("date"))["m"]
        end = max(today + timedelta(days=clock.FORECAST_DAYS), last or today)
    last_day = last_computable_day(today)
    if last_day is None:
        log.warning("predict: no weather at all, nothing computed")
        return PredictResult(0)
    end = min(end, last_day)  # days without any weather can't be recomputed: leave their rows alone
    if start > end:
        return PredictResult(0)
    rows, n_fields, field_list = compute_rows(field_ids, start, end, observations, with_fields=True)
    with transaction.atomic():
        # replace the whole range for these fields: rows of threats that no longer apply (the crop changed,
        # a season not computable yet) must not linger
        Risk.objects.filter(field_id__in=[f.id for f in field_list], date__range=(start, end)).delete()
        Risk.objects.bulk_create(
            rows, batch_size=2000, update_conflicts=True,
            unique_fields=["field", "threat", "date"], update_fields=["score", "explanation", "computed_at"],
        )
    log.info("predict: %d risk rows for %d fields, %s..%s", len(rows), n_fields, start, end)
    return PredictResult(len(rows), [f.id for f in field_list])


def clock_moved(old: date, new: date | None = None) -> PredictResult:
    """
    The demo date moved from `old` to `new` (default: the Clock's current date). Recomputes exactly the
    days whose inputs changed, (min(old, new), max(old, new) + 7], for every field: days that were
    coming days and are now past go back to "as of that day", and the new coming days are computed
    from the forecast issued on `new`. Nothing else is rewritten.

    Called explicitly by the platform after saving the Clock (PUT /api/clock/, the admin's clock page);
    there is no signal. Use clock.save() or Clock.objects.update(); either way, call this afterwards.
    """
    new = new or clock.today()
    if old == new:
        return PredictResult(0)
    lo, hi = min(old, new), max(old, new)
    return predict(start=lo + timedelta(days=1), end=hi + timedelta(days=clock.FORECAST_DAYS))


def precompute_season(season: int | None = None) -> PredictResult:
    """
    For the demo seed: computes the previous season (this season's carry-over reads its peaks from
    Risk), then this season to its end (maize to 31 December), in that order. Days after today + 7
    are assessed as of that day and recomputed by clock_moved() when the date comes within 7 days.
    """
    season = season or season_of(clock.today())
    p0, p1 = season_bounds(season - 1)
    first = predict(start=p0, end=p1)
    s0, _ = season_bounds(season)
    return first + predict(start=s0, end=date(season, 12, 31))


def compute_rows(field_ids, start: date, end: date, observations=None, with_fields: bool = False):
    """Computes (does not save) the Risk rows. Shared by predict() and what_if()."""
    all_fields = list(Field.objects.select_related("crop", "weather_grid"))
    reports = list(observations) if observations is not None else OBS.load_all(start, end)
    reports += [r for f in all_fields for r in OBS.from_field(f)]  # facts stored on the field (if those columns exist)
    reports += farm_spread(reports, all_fields)
    if field_ids is not None:
        wanted = set(field_ids)
        # fields that get a derived "nearby symptoms" report from the requested fields are recomputed too
        wanted |= {r.field_id for r in reports if r.details.get("derived_from_field") in field_ids}
        fields = [f for f in all_fields if f.id in wanted]
    else:
        fields = all_fields
    threats = {t.code: t for t in Threat.objects.all()}
    now = timezone.now()
    rows: list[Risk] = []
    for field in fields:
        rows += _field_rows(field, threats, start, end, now, OBS.for_field(reports, field.id))
    if with_fields:
        return rows, len(fields), fields
    return rows, len(fields)


def farm_spread(reports, fields) -> list:
    """Symptoms on one field -> a 'neighbour' report for every other field of the same crop within 3 km."""
    import math

    by_id = {f.id: f for f in fields}
    out = []
    for r in reports:
        if r.kind != "symptoms" or r.field_id not in by_id or not r.threat_code:
            continue
        src = by_id[r.field_id]
        for f in fields:
            if f.id == src.id or f.crop_id != src.crop_id:
                continue
            dy = (f.centroid_lat - src.centroid_lat) * 111_320
            dx = (f.centroid_lon - src.centroid_lon) * 111_320 * math.cos(math.radians(src.centroid_lat))
            d = math.hypot(dx, dy)
            if d <= SPREAD_RADIUS_M:
                out.append(OBS.Report(observed_on=r.observed_on, kind="neighbour", threat_code=r.threat_code, distance_m=round(d),
                                      field_id=f.id, text=f"Symptoms reported on {src.name}",
                                      details={"derived_from_field": src.id, "derived_from_report": r.id}))
    return out


def what_if(field_id: int, day: date, hypothetical: list, start: date | None = None) -> list[dict]:
    """
    Dry run for the assistant: how would this field's risks on `day` change with these extra reports
    (e.g. "if I spray tomorrow", "if I sowed on 10 October")? Nothing is written.
    Returns one entry per threat: code, score now, score with the reports, level, summary.
    """
    start = start or day - timedelta(days=30)
    existing = OBS.load_all(start, day)
    base, _ = compute_rows([field_id], start, day, existing)
    alt, _ = compute_rows([field_id], start, day, existing + list(hypothetical))
    pick = lambda rows: {r.threat.code: r for r in rows if r.date == day and r.field_id == field_id}
    b, a = pick(base), pick(alt)
    out = []
    for code in sorted(a, key=lambda c: -a[c].score):
        out.append({"threat_code": code, "score_now": b[code].score if code in b else None, "score_if": a[code].score,
                    "change": round(a[code].score - (b[code].score if code in b else 0), 3),
                    "level_if": a[code].explanation["level"], "summary_if": a[code].explanation["summary"]})
    return out


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
                        previous_crop_name=names.get(season - 1), maize_years_in_row=in_row, soil=soil,
                        history={y: c for y, (c, _) in history.items()}, season=season)


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


def crop_season_segments(field: Field, start: date, end: date) -> list[tuple[int, date, date, int | None, str]]:
    """
    Splits [start, end] into (season, from, to, crop, crop source) pieces.

    Seasons are named by harvest year and run 1 Sep - 31 Aug (winter crops). Spring crops harvested
    after 1 September stay open longer (maize to 31 Dec, sugar beet to 30 Nov, potato to 31 Oct;
    engine.phenology.PROFILES). Seasons after the current one are skipped: their crop is not known yet.
    """
    current = season_of(clock.today())
    out = []
    s = start
    while s <= end:
        season = season_of(s)
        s_end = min(end, season_bounds(season)[1])
        if season > current:
            late = season_end(field.crop_id, current) if field.crop_id else None
            if late and late.month >= 9 and s.year == current and s <= late:  # spring crop harvested after 1 September
                s_end = min(end, late)
                out.append((current, s, s_end, field.crop_id, "field"))
            s = s_end + timedelta(days=1)
            continue
        crop, source = season_crop(field, season)
        out.append((season, s, s_end, crop, source))
        s = s_end + timedelta(days=1)
    return out


def _field_rows(field: Field, threats: dict, start: date, end: date, now, reports=()) -> list[Risk]:
    out: list[Risk] = []
    for season, s, s_end, crop, source in crop_season_segments(field, start, end):
        rules = [r for r in rules_for_crop(crop) if r.code in threats] if crop else []
        missing = [r.code for r in rules_for_crop(crop) if r.code not in threats] if crop else []
        if missing:
            log.warning("predict: %d engine threat codes have no Threat row and are skipped (run engine_load_threats): %s",
                        len(missing), ", ".join(missing[:5]))
        if rules:
            out += _season_rows(field, threats, rules, season, s, s_end, now, reports, crop, source)
    return out


def _season_rows(field, threats, rules, season, start, end, now, reports=(), crop=None, crop_source="field") -> list[Risk]:
    grid = field.weather_grid_id
    today = clock.today()
    horizon = today + timedelta(days=clock.FORECAST_DAYS)
    load_start = min(start, season_bounds(season)[0])
    ctx = field_context(field, season, crop_code=crop, crop_source=crop_source)
    ctx.last_season = last_season_peaks(field, season)
    from engine.satellite import fieldndvi
    anchors = fieldndvi.phenology_anchors(fieldndvi.load(field, season), ctx.crop, season)
    s0, s1 = season_bounds(season)
    sow = OBS.sowing_override([r for r in reports if r.observed_on <= end], window=(s0 - timedelta(days=60), s1))

    out: list[Risk] = []
    # 1. days assessed "as of that day": up to today, and (demo precompute only) after today + 7
    daily = F.load_daily(grid, load_start, end)
    if not daily.empty:
        hourly = F.load_hourly(grid, load_start, end)
        span = pd.date_range(max(pd.Timestamp(start), daily.index.min()), min(pd.Timestamp(end), daily.index.max()), freq="D")
        days = span[(span <= pd.Timestamp(today)) | (span > pd.Timestamp(horizon))]
        if len(days):
            stages = _stages(ctx, daily, season, anchors, sow)
            out += _score(field, threats, rules, ctx, daily, hourly, stages, season, days, reports, now, today, forecast_from=None)

    # 2. coming days: weather observed up to today, then the forecast issued today
    c0, c1 = max(start, today + timedelta(days=1)), min(end, horizon)
    if c0 <= c1:
        obs = F.load_daily(grid, load_start, today)
        fc = F.load_forecast(grid, today)
        fc = fc[fc.index > pd.Timestamp(today)] if not fc.empty else fc
        if fc.empty:
            log.warning("predict: no forecast issued on %s for grid %s: no coming-day risks", today, grid)
        elif not obs.empty:
            daily_c = pd.concat([obs, fc])
            hourly_c = F.load_hourly(grid, load_start, today)  # the forecast is daily only: infection hours fall back to daily estimates
            days = pd.date_range(pd.Timestamp(c0), min(pd.Timestamp(c1), daily_c.index.max()), freq="D")
            if len(days):
                known = [a for a in anchors if a.detected_on <= today]  # no satellite scene after today
                stages = _stages(ctx, daily_c, season, known, sow)
                out += _score(field, threats, rules, ctx, daily_c, hourly_c, stages, season, days, reports, now, today, forecast_from=today)
    if not out and daily.empty:
        log.warning("predict: no daily weather for grid %s, %s..%s", grid, load_start, end)
    return out


def _stages(ctx, daily, season, anchors, sow):
    stages = calibrate(bbch_series(ctx.crop, daily["avg_temperature"], season), ctx.crop, anchors)
    if sow:  # the farmer's sowing date replaces the assumed one from the day it was reported
        told = bbch_series(ctx.crop, daily["avg_temperature"], season, sowing=sow[0])
        use = told.index >= pd.Timestamp(sow[1])
        stages = stages.copy()
        stages.loc[use] = told.loc[use]
    return stages


def _score(field, threats, rules, ctx, daily, hourly, stages, season, days, reports, now, today, forecast_from) -> list[Risk]:
    """Scores the rules on `days`. forecast_from: the forecast's issue day when these are coming days."""
    dd10 = degree_days_base10(daily["avg_temperature"], season)
    grid = field.weather_grid_id
    out = []
    forecast_cache: dict[date, pd.DataFrame] = {}
    for rule in rules:
        for res in score_rule(rule, ctx, daily, hourly, stages, dd10, days, reports):
            lead = (res.day - today).days
            if forecast_from is not None:  # a coming day: its weather is the forecast, less certain the further ahead
                adjust_for_lead(res.explanation, lead, forecast_from)
            if res.explanation["action"]["type"] == "treat":
                fc = forecast_cache.get(res.day)
                if fc is None:
                    fc = _forecast(grid, res.day, today)
                    forecast_cache[res.day] = fc
                res.explanation["action"]["spray_window"] = spray_window(fc)
            out.append(Risk(field=field, threat=threats[rule.code], date=res.day, score=res.score,
                            explanation=res.explanation, computed_at=now))
    return out


FORECAST_CONFIDENCE_DROP = 0.06  # per day ahead (team assumption): day +7 keeps 58 % of the confidence


def adjust_for_lead(expl: dict, lead: int, issued_on: date | None = None) -> dict:
    """Confidence of a day `lead` days after today (weather from the forecast issued today). Idempotent."""
    base = expl.get("confidence_observed", expl["confidence"])
    expl["confidence_observed"] = base
    expl["forecast_lead_days"] = lead
    if issued_on is not None:
        expl["forecast_issued_on"] = issued_on.isoformat()
    expl["confidence"] = round(base * max(0.4, 1 - FORECAST_CONFIDENCE_DROP * lead), 2)
    note = (f"Day +{lead}: weather after today is the forecast issued today (daily values only), "
            "so the risk is a projection and less certain.")
    expl["notes"] = [n for n in expl.get("notes", []) if not n.startswith("Day +")] + [note]
    return expl


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


def _forecast(grid: str, day: date, today: date | None = None) -> pd.DataFrame:
    """
    The forecast for the days after `day`, as known on `day`; for a coming day (after today) that is the
    forecast issued today, never one issued in the future.
    """
    issued = min(day, today) if today else day
    cols = ["date", "max_temperature", "min_temperature", "total_precipitation", "avg_wind_speed", "avg_relative_humidity"]
    qs = (WeatherForecastDaily.objects.current(as_of=issued).filter(grid_id=grid, date__gt=day)
          .order_by("date").values(*cols))
    df = pd.DataFrame.from_records(qs, columns=cols)
    return df.set_index("date") if not df.empty else df


__all__ = ["predict", "clock_moved", "precompute_season", "PredictResult", "compute_rows", "what_if", "farm_spread", "adjust_for_lead", "field_context", "RULES"]
