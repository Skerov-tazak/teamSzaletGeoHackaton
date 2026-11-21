"""
Scores one field's threats over a range of days, each with an explanation.

score = weather_or_activity (0-1) x stage_weight (0-1) x multipliers (crop history, soil), capped at 1.
Every factor becomes a "driver" in the explanation, with its value, unit, the rule's threshold and
its effect: how much the final score would change without it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from engine import features as F
from engine.catalog import CEREALS, MAIZE, WHEAT, Rule
from engine.phenology import STAGE_CONFIDENCE_GDD, stage_name

MODEL_VERSION = "0.1.0"
LEVELS = ((0.6, "high"), (0.3, "medium"), (0.0, "low"))  # team assumption, to agree with the map
NO_IN_SEASON_TREATMENT = {"wheat.take_all", "wheat.snow_mould", "maize.seedling_blight", "maize.crazy_top",
                          "maize.fusarium_stalk_rot", "maize.fusarium_ear_rot"}
# Spraying conditions, Metodyka kukurydzy Tabela 40 (p. 216): 1-25 °C, no rain, wind <= 4 m/s.
SPRAY = {"max_temperature": 25.0, "min_temperature": 1.0, "total_precipitation": 1.0, "avg_wind_speed": 14.4}
SPRAY_SOURCE = {"document": "Metodyka_integrowanej_ochrony_kukurydzy_dla_doradcow_2019.pdf", "page": 216,
                "note": "Tabela 40: warunki wykonywania zabiegów"}


def level_of(score: float) -> str:
    for cut, name in LEVELS:
        if score >= cut:
            return name
    return "low"


@dataclass
class FieldContext:
    crop: int
    crop_source: str                 # "field" (Field.crop) or "satellite" / "farmer" later
    previous_crop: int | None        # dominant class last season
    previous_crop_name: str | None
    maize_years_in_row: int          # consecutive maize seasons including this one
    soil: dict = field(default_factory=dict)  # averaged root-zone values: clay, sand, ph


def stage_weight(bbch: np.ndarray, rule: Rule) -> np.ndarray:
    lo, hi, ramp = rule.stage_min, rule.stage_max, max(rule.stage_ramp, 1)
    w = np.ones_like(bbch, dtype=float)
    w = np.where(bbch < lo, np.clip(1 - (lo - bbch) / ramp, 0, 1), w)
    w = np.where(bbch > hi, np.clip(1 - (bbch - hi) / ramp, 0, 1), w)
    return np.where(bbch < 0, 0.0, w)  # not sown yet


def ramp(x, low, high):
    return np.clip((np.asarray(x, dtype=float) - low) / max(high - low, 1e-9), 0, 1)


def multipliers(rule: Rule, ctx: FieldContext) -> list[dict]:
    out = []
    if rule.after_maize != 1.0 and ctx.previous_crop == MAIZE:
        out.append({"factor": "previous_crop", "label": "Previous crop was maize (residue carries the fungus)",
                    "value": ctx.previous_crop, "unit": "crop code", "display": ctx.previous_crop_name, "multiplier": rule.after_maize})
    if rule.cereal_after_cereal != 1.0 and ctx.previous_crop in CEREALS:
        out.append({"factor": "previous_crop", "label": f"Cereal after cereal (previous crop: {ctx.previous_crop_name})",
                    "value": ctx.previous_crop, "unit": "crop code", "display": ctx.previous_crop_name, "multiplier": rule.cereal_after_cereal})
    if rule.maize_monoculture != 1.0 and ctx.maize_years_in_row >= 2:
        out.append({"factor": "maize_monoculture", "label": f"Maize monoculture ({ctx.maize_years_in_row} seasons in a row)",
                    "value": ctx.maize_years_in_row, "unit": "seasons", "multiplier": rule.maize_monoculture})
    clay = ctx.soil.get("clay")
    if rule.heavy_soil != 1.0 and clay is not None and clay >= 30:
        out.append({"factor": "heavy_soil", "label": f"Heavy soil (clay {clay:.0f} %) holds water",
                    "value": round(clay, 1), "unit": "% clay", "multiplier": rule.heavy_soil})
    return out


@dataclass
class DayResult:
    day: date
    score: float
    explanation: dict


def score_rule(rule: Rule, ctx: FieldContext, daily: pd.DataFrame, hourly: pd.DataFrame,
               stages: pd.DataFrame, dd10: pd.Series, days: pd.DatetimeIndex) -> list[DayResult]:
    """Scores one rule for the given days (all inside one season)."""
    d = daily
    bbch = stages["bbch"].reindex(days).fillna(0).to_numpy()
    sw = stage_weight(bbch, rule)
    estimated = pd.Series(False, index=days)
    extra: dict[str, pd.Series] = {}

    if rule.kind == "infection_hours":
        hours, est = F.condition_hours(d, hourly, rule.temp_min, rule.temp_max, rule.moisture)
        win = F.trailing_sum(hours, rule.window_days).reindex(days).fillna(0)
        est_any = F.trailing_sum(est.astype(float), rule.window_days).reindex(days).fillna(0) > 0
        estimated = est_any
        base = ramp(win, rule.hours_low, rule.hours_high)
        main = {"factor": "condition_hours", "values": win,
                "label": f"Hours at {rule.temp_min:g}-{rule.temp_max:g} °C with {_moisture_text(rule.moisture)} in the last {rule.window_days} days",
                "unit": "h", "threshold": f"{rule.hours_low:g} h starts the risk, {rule.hours_high:g} h = full risk"}
        if rule.needs_rain_days:
            rain_days = F.trailing_sum((d["precip"].fillna(0) >= 1).astype(float), rule.window_days).reindex(days).fillna(0)
            rain_factor = np.clip(rain_days / rule.needs_rain_days, 0.0, 1.0)
            base = base * rain_factor
            extra["rain_days"] = rain_days
        if rule.crop == WHEAT:  # winter dormancy: leaf diseases do not develop in cold weather
            mean7 = F.trailing_mean(d["avg_temperature"], 7).reindex(days)
            active = ramp(mean7.to_numpy(), 3, 8)
            base = base * active
            extra["mean_temperature_7d"] = mean7
        if rule.code in ("maize.fusarium_ear_rot", "maize.fusarium_stalk_rot"):
            balance = F.trailing_sum(d["precip"].fillna(0) - d["eto"].fillna(0), 30).reindex(days).fillna(0)
            drought = ramp(-balance, 60, 150)  # water deficit 60-150 mm over 30 days
            base = np.maximum(base, 0.8 * drought)
            extra["water_balance_30d"] = balance
    elif rule.kind == "soil_days":
        cond = ((d["avg_soil_temperature_level_1"] < 12) & (d["avg_soil_moisture_level_1"] >= 0.30)).astype(float)
        win = F.trailing_sum(cond, rule.window_days).reindex(days).fillna(0)
        base = ramp(win, rule.hours_low, rule.hours_high)
        main = {"factor": "cold_wet_soil_days", "values": win, "unit": "days",
                "label": f"Days with cold (< 12 °C) and wet (>= 0.30 m³/m³) topsoil in the last {rule.window_days} days",
                "threshold": f"{rule.hours_low:g} days starts the risk, {rule.hours_high:g} days = full risk"}
    elif rule.kind == "snow_days":
        cond = (d["avg_temperature"].between(rule.temp_min - 2, rule.temp_max)
                & ((d["avg_snow_depth"].fillna(0) >= 5) | (d["avg_relative_humidity"] >= 90))
                & (d["min_soil_temperature_level_1"] > -0.5)).astype(float)
        win = F.trailing_sum(cond, rule.window_days).reindex(days).fillna(0)
        base = ramp(win, rule.hours_low, rule.hours_high)
        main = {"factor": "snow_mould_days", "values": win, "unit": "days",
                "label": f"Days at about 0-5 °C, wet or under snow, soil not frozen, in the last {rule.window_days} days",
                "threshold": f"{rule.hours_low:g} days starts the risk, {rule.hours_high:g} days = full risk"}
    elif rule.kind == "flood":
        cond = ((d["avg_soil_moisture_level_1"] >= 0.40) | (d["precip"].fillna(0) >= 30)).astype(float)
        win = F.trailing_sum(cond, rule.window_days).reindex(days).fillna(0)
        base = ramp(win, rule.hours_low, rule.hours_high)
        main = {"factor": "waterlogged_days", "values": win, "unit": "days",
                "label": f"Days with saturated topsoil or >= 30 mm rain in the last {rule.window_days} days",
                "threshold": f"{rule.hours_low:g} day starts the risk, {rule.hours_high:g} days = full risk"}
    elif rule.kind == "pest_activity":
        mean7 = F.trailing_mean(d["avg_temperature"], 7).reindex(days)
        if rule.code == "maize.frit_fly":
            base = ramp(-mean7.to_numpy(), -18, -12)  # cooler than 15 °C -> active
            main = {"factor": "mean_temperature_7d", "values": mean7, "unit": "°C",
                    "label": "Mean temperature of the last 7 days (cool springs favour frit fly)", "threshold": "< 15 °C favours it"}
        else:
            x = dd10.reindex(days).fillna(0).to_numpy()
            p0, p1 = rule.dd10_peak
            act = np.minimum(ramp(x, rule.dd10_start, p0), 1 - ramp(x, p1, rule.dd10_end))
            pressure = 0.6
            pressure_why = "typical for maize in the region (assumption)"
            if rule.code == "maize.western_corn_rootworm":
                pressure = 1.0 if ctx.maize_years_in_row >= 2 else 0.05
                pressure_why = (f"maize on this field {ctx.maize_years_in_row} seasons in a row: eggs overwinter in the soil"
                                if ctx.maize_years_in_row >= 2 else "first season of maize here: larvae have no eggs to hatch from")
            if rule.code == "maize.aphids":
                act = act * (0.5 + 0.5 * ramp(mean7.to_numpy(), 14, 20))
            base = act * pressure
            extra["local_pressure"] = pd.Series(pressure, index=days)
            extra["_pressure_reason"] = f"local pressure {pressure:.0%}: {pressure_why}"
            main = {"factor": "pest_activity", "values": pd.Series(np.round(act * 100), index=days), "unit": "% of peak activity",
                    "label": "Pest activity window from degree days (base 10 °C since 1 January)",
                    "threshold": f"starts at {rule.dd10_start:g}, peaks {p0:g}-{p1:g}, ends {rule.dd10_end:g} degree days"}
            extra["degree_days_10"] = dd10.reindex(days)
    else:
        raise ValueError(rule.kind)

    mults = multipliers(rule, ctx)
    m_total = float(np.prod([m["multiplier"] for m in mults])) if mults else 1.0
    base = np.asarray(base, dtype=float)
    final = np.clip(base * sw * m_total, 0, 1)

    results = []
    for i, day in enumerate(days):
        results.append(DayResult(day.date(), round(float(final[i]), 3), _explain(
            rule, ctx, day, float(final[i]), float(base[i]), float(sw[i]), float(bbch[i]), m_total, mults, main, i,
            stages, extra, bool(estimated.iloc[i]) if len(estimated) else False)))
    return results


def _moisture_text(kind: str) -> str:
    return {"wet": "wet leaves (RH >= 95 % or rain)", "humid": "humid air (RH >= 85 % or rain)",
            "mild": "humid but not rainy air (RH 50-95 %)"}[kind]


def _explain(rule, ctx, day, final, base, sw, bbch, m_total, mults, main, i, stages, extra, estimated) -> dict:
    level = level_of(final)
    value = main["values"].iloc[i] if hasattr(main["values"], "iloc") else main["values"][i]
    value = None if pd.isna(value) else round(float(value), 1)
    drivers = [{
        "factor": main["factor"], "label": main["label"], "value": value, "unit": main["unit"],
        "threshold": main["threshold"], "effect": round(final, 3),
        "note": "estimated from daily weather (no hourly data)" if estimated else None,
    }]
    st = stages.loc[day] if day in stages.index else None
    drivers.append({
        "factor": "growth_stage", "label": f"Growth stage BBCH {bbch:.0f} ({stage_name(bbch)}); susceptible BBCH {rule.stage_min}-{rule.stage_max}",
        "value": int(round(bbch)), "unit": "BBCH", "threshold": f"BBCH {rule.stage_min}-{rule.stage_max}",
        "effect": round(final - min(1.0, base * m_total), 3),
    })
    for m in mults:
        without = min(1.0, base * sw * m_total / m["multiplier"])
        drivers.append({**{k: v for k, v in m.items()}, "effect": round(final - without, 3)})
    pressure_reason = extra.get("_pressure_reason")
    for k, s in extra.items():
        if k.startswith("_"):
            continue
        v = s.iloc[i] if hasattr(s, "iloc") else s
        if pd.isna(v):
            continue
        drivers.append({"factor": k, "label": _EXTRA_LABELS.get(k, k), "value": round(float(v), 1),
                        "unit": _EXTRA_UNITS.get(k, ""), "effect": None})

    def lc(text: str) -> str:  # lower-case the first letter only (keeps °C, RH, BBCH)
        return text[:1].lower() + text[1:]

    reasons = []
    if bbch < 0:
        reasons.append("the crop is not sown yet")
    elif sw == 0:
        reasons.append(f"not in the susceptible stage (BBCH {rule.stage_min}-{rule.stage_max}; now BBCH {bbch:.0f}, {stage_name(bbch)})")
    else:
        reasons.append(f"{lc(main['label'])}: {value:g} {main['unit']}" if value is not None else lc(main["label"]))
        stage_txt = f"{stage_name(bbch)}, BBCH {bbch:.0f}"
        reasons.append(f"crop at {stage_txt}" + ("" if sw >= 1 else f" (only partly in the susceptible stage BBCH {rule.stage_min}-{rule.stage_max})"))
        reasons += [lc(m["label"]) for m in mults]
        if pressure_reason:
            reasons.append(pressure_reason)
    summary = f"{level.capitalize()} risk of {rule.name_en} ({rule.name_pl}): " + "; ".join(reasons) + "."

    confidence = STAGE_CONFIDENCE_GDD * (0.7 if estimated else 1.0)
    return {
        "version": 1,
        "summary": summary,
        "level": level,
        "score": round(final, 3),
        "threat": {"code": rule.code, "name_pl": rule.name_pl, "name_en": rule.name_en, "category": rule.category},
        "as_of": day.date().isoformat(),
        "crop": {"code": ctx.crop, "source": ctx.crop_source},
        "growth_stage": {"bbch": int(round(bbch)), "name": stage_name(bbch), "method": "degree days, typical sowing date",
                         "sowing_assumed": str(st["sowing"]) if st is not None else None, "confidence": STAGE_CONFIDENCE_GDD},
        "drivers": drivers,
        "action": _action(rule, level, sw),
        "severity": rule.severity,
        "expected_loss": round(final * rule.severity, 4),
        "confidence": round(confidence, 2),
        "sources": list(rule.sources),
        "notes": list(rule.notes),
        "assumptions": rule.assumptions,
        "model": "rules", "model_version": MODEL_VERSION,
    }


_EXTRA_LABELS = {"rain_days": "Days with >= 1 mm rain in the window (rain splash spreads spores)",
                 "mean_temperature_7d": "Mean temperature of the last 7 days (below ~3-8 °C the crop and the fungus are dormant)",
                 "water_balance_30d": "Water balance (rain - evapotranspiration), last 30 days; strongly negative = drought stress",
                 "local_pressure": "Local pest pressure from the field's history (0-1)",
                 "degree_days_10": "Degree days base 10 °C since 1 January"}
_EXTRA_UNITS = {"rain_days": "days", "mean_temperature_7d": "°C", "water_balance_30d": "mm", "local_pressure": "0-1", "degree_days_10": "°C·days"}


def _action(rule: Rule, level: str, sw: float) -> dict:
    if sw == 0 or level == "low":
        return {"type": "wait", "text": "No action needed now.", "threshold": rule.action_threshold or None, "spray_window": None}
    if level == "medium":
        return {"type": "monitor", "text": "Inspect the field in the coming days and compare with the threshold.",
                "threshold": rule.action_threshold or None, "spray_window": None}
    if rule.code in NO_IN_SEASON_TREATMENT:
        return {"type": "monitor", "text": "High risk, but there is no in-season treatment: inspect, record it, and plan prevention (rotation, residue, seed treatment).",
                "threshold": rule.action_threshold or None, "spray_window": None}
    return {"type": "treat", "text": "High risk: inspect the field now; if the threshold is exceeded, a treatment is justified.",
            "threshold": rule.action_threshold or None, "spray_window": None}


def spray_window(forecast: pd.DataFrame) -> dict | None:
    """First forecast day meeting the spraying conditions of Tabela 40 (daily approximation)."""
    if forecast is None or forecast.empty:
        return None
    for d, row in forecast.sort_index().iterrows():
        checks = {
            "max_temperature": row.get("max_temperature") is not None and row["max_temperature"] <= SPRAY["max_temperature"],
            "min_temperature": row.get("min_temperature") is not None and row["min_temperature"] >= SPRAY["min_temperature"],
            "total_precipitation": pd.isna(row.get("total_precipitation")) or row["total_precipitation"] < SPRAY["total_precipitation"],
            "avg_wind_speed": row.get("avg_wind_speed") is not None and row["avg_wind_speed"] <= SPRAY["avg_wind_speed"],
        }
        if all(checks.values()):
            rain = row.get("total_precipitation")
            rain = None if rain is None or pd.isna(rain) else round(float(rain), 1)
            return {"date": pd.Timestamp(d).date().isoformat(),
                    "conditions": {"max_temperature_c": round(float(row["max_temperature"]), 1),
                                   "min_temperature_c": round(float(row["min_temperature"]), 1),
                                   "precipitation_mm": rain, "avg_wind_kmh": round(float(row["avg_wind_speed"]), 1)},
                    "rule": "1-25 °C, no rain, wind <= 14.4 km/h (4 m/s)",
                    "note": None if rain is not None else "The forecast has no precipitation: check rain before spraying.",
                    "source": SPRAY_SOURCE}
    return None
