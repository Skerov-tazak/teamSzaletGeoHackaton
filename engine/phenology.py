"""
Growth stage (BBCH) per day from growing degree days (GDD).

No sowing dates exist in the data, so the model uses typical regional dates (team assumption) and
reports a stage_confidence below 1. Each estimate says how it was made, for the explanation.

- Winter wheat: sown ~1 October. Autumn development from GDD base 0 °C since sowing (to BBCH 25,
  tillering, by winter). From 1 January the spring development follows GDD base 0 °C since 1 January.
- Maize: sown ~25 April. GDD base 6 °C since sowing (guide range for maize: 6-10 °C).

The GDD -> BBCH tables are calibrated to typical dates in Opolskie (heading end of May, wheat
harvest mid-July; maize tasseling mid/late July, maturity end of September).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from engine.catalog import MAIZE, WHEAT

STAGE_NAMES = [
    (-1, "not sown yet"), (0, "sown, germinating"), (9, "emergence"), (10, "leaf development"), (20, "tillering"),
    (30, "stem elongation"), (51, "heading / tasseling"), (61, "flowering"), (71, "grain development"),
    (83, "ripening"), (89, "fully ripe"), (92, "harvest / over-ripe"),
]

# (GDD, BBCH) breakpoints, linear in between.
WHEAT_AUTUMN = [(0, 0), (120, 10), (250, 13), (420, 21), (600, 25)]  # base 0, since sowing
# Heading and ripening re-calibrated to Sentinel-2 on 7 wheat field-seasons near Krapkowice (2024-25):
# NDVI peak (heading, ~BBCH 55) at a median 1060 GDD, NDVI < 0.5 (ripening, ~BBCH 83) at a median 2135 GDD.
WHEAT_SPRING = [(0, 25), (420, 30), (560, 32), (700, 37), (820, 39), (950, 49), (1010, 55), (1080, 59),
                (1130, 61), (1250, 69), (1600, 75), (2000, 83), (2200, 85), (2400, 89), (2550, 92)]  # base 0, since 1 Jan
MAIZE_TABLE = [(0, 0), (80, 9), (110, 10), (200, 13), (350, 16), (450, 30), (820, 51), (900, 59),
               (950, 63), (1050, 69), (1200, 75), (1400, 85), (1600, 87), (1750, 89)]  # base 6, since sowing

DEFAULT_SOWING = {WHEAT: (10, 1), MAIZE: (4, 25)}  # (month, day), team assumption
GDD_BASE = {WHEAT: 0.0, MAIZE: 6.0}
STAGE_CONFIDENCE_GDD = 0.6


@dataclass
class StageEstimate:
    bbch: float
    name: str
    method: str
    sowing: date
    gdd: float
    confidence: float

    def as_dict(self) -> dict:
        return {"bbch": int(round(self.bbch)), "name": self.name, "method": self.method,
                "sowing_assumed": self.sowing.isoformat(), "gdd": round(self.gdd), "confidence": self.confidence}


MAIZE_STAGE_NAMES = [
    (-1, "not sown yet"), (0, "sown, germinating"), (9, "emergence"), (10, "leaf development"),
    (30, "stem elongation"), (51, "tasseling"), (63, "flowering (silking)"), (71, "grain filling"),
    (83, "ripening"), (87, "physiological maturity"), (89, "fully ripe"),
]


def stage_name(bbch: float, crop: int | None = None) -> str:
    names = MAIZE_STAGE_NAMES if crop == MAIZE else STAGE_NAMES
    name = names[0][1]  # bbch < 0: not sown yet
    for b, n in names:
        if bbch >= b:
            name = n
    return name


def _interp(table, x):
    xs, ys = zip(*table)
    return np.interp(x, xs, ys)


def bbch_series(crop: int, daily_temp: pd.Series, season: int, sowing: date | None = None) -> pd.DataFrame:
    """
    daily_temp: avg temperature (°C) indexed by date, covering the season (gaps are filled).
    Returns a frame indexed by date with columns bbch, gdd, sowing (trailing sums only: no look-ahead).
    """
    t = daily_temp.sort_index().astype(float)
    t = t.reindex(pd.date_range(t.index.min(), t.index.max(), freq="D")).interpolate(limit_direction="both")
    base = GDD_BASE.get(crop, 0.0)
    month, day = DEFAULT_SOWING.get(crop, (4, 25))
    out = pd.DataFrame(index=t.index)
    given = sowing is not None
    if crop == WHEAT:
        sowing = pd.Timestamp(sowing) if given else pd.Timestamp(season - 1, month, day)
        gdd_day = (t - base).clip(lower=0)
        autumn = gdd_day.where((t.index >= sowing) & (t.index < pd.Timestamp(season, 1, 1)), 0).cumsum()
        spring = gdd_day.where(t.index >= pd.Timestamp(season, 1, 1), 0).cumsum()
        bbch_aut = _interp(WHEAT_AUTUMN, autumn.values)
        bbch_spr = _interp(WHEAT_SPRING, spring.values)
        in_spring = t.index >= pd.Timestamp(season, 1, 1)
        out["bbch"] = np.where(in_spring, np.maximum(bbch_spr, bbch_aut), bbch_aut)
        out.loc[t.index < sowing, "bbch"] = -1
        out["gdd"] = np.where(in_spring, spring.values, autumn.values)
    else:
        sowing = pd.Timestamp(sowing) if given else pd.Timestamp(season, month, day)
        gdd = (t - base).clip(lower=0).where(t.index >= sowing, 0).cumsum()
        out["bbch"] = _interp(MAIZE_TABLE, gdd.values)
        out.loc[t.index < sowing, "bbch"] = -1
        out["gdd"] = gdd.values
    out["sowing"] = sowing.date()
    out["method"] = "degree days, sowing date from the farmer" if given else "degree days, typical sowing date"
    out["confidence"] = 0.85 if given else STAGE_CONFIDENCE_GDD
    return out


def estimate(crop: int, stages: pd.DataFrame, day: date) -> StageEstimate:
    row = stages.loc[pd.Timestamp(day)]
    return StageEstimate(bbch=float(row.bbch), name=stage_name(row.bbch, crop), method="degree days (GDD), typical sowing date",
                         sowing=row.sowing, gdd=float(row.gdd), confidence=STAGE_CONFIDENCE_GDD)


def degree_days_base10(daily_temp: pd.Series, year: int) -> pd.Series:
    """Degree days base 10 °C since 1 January of `year` (for pest activity). Trailing sum."""
    t = daily_temp.sort_index().astype(float)
    t = t.reindex(pd.date_range(t.index.min(), t.index.max(), freq="D")).interpolate(limit_direction="both")
    return (t - 10).clip(lower=0).where(t.index >= pd.Timestamp(year, 1, 1), 0).cumsum()


STAGE_CONFIDENCE_SATELLITE = 0.8


def calibrate(stages: pd.DataFrame, crop: int, anchors) -> pd.DataFrame:
    """
    Shift the degree-day stage curve so it passes through satellite anchors (engine.satellite.fieldndvi).
    An anchor is applied only from the day it could be known (`detected_on`), so earlier days keep the
    uncalibrated estimate: no look-ahead.
    """
    if not anchors:
        return stages
    table = WHEAT_SPRING if crop == WHEAT else MAIZE_TABLE
    gdds, bbchs = zip(*table)
    out = stages.copy()
    for a in sorted(anchors, key=lambda x: x.detected_on):
        on = pd.Timestamp(a.on)
        if on not in out.index:
            continue
        if crop == WHEAT and on < pd.Timestamp(on.year, 1, 1):
            continue
        need = float(np.interp(a.bbch, bbchs, gdds))
        delta = float(stages.loc[on, "gdd"]) - need
        use = out.index >= pd.Timestamp(a.detected_on)
        if crop == WHEAT:
            use &= out.index >= pd.Timestamp(on.year, 1, 1)
        shifted = np.interp(stages.loc[use, "gdd"].to_numpy() - delta, gdds, bbchs)
        out.loc[use, "bbch"] = np.maximum(shifted, 0)
        out.loc[use, "method"] = f"degree days calibrated to the satellite: {a.what}"
        out.loc[use, "confidence"] = STAGE_CONFIDENCE_SATELLITE
    return out
