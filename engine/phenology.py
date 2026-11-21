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
WHEAT_SPRING = [(0, 25), (420, 30), (560, 32), (700, 37), (820, 39), (930, 49), (970, 51), (1050, 59),
                (1100, 61), (1200, 69), (1400, 75), (1650, 85), (1900, 89), (2050, 92)]  # base 0, since 1 Jan
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


def stage_name(bbch: float) -> str:
    name = STAGE_NAMES[0][1]  # bbch < 0: not sown yet
    for b, n in STAGE_NAMES:
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
    return StageEstimate(bbch=float(row.bbch), name=stage_name(row.bbch), method="degree days (GDD), typical sowing date",
                         sowing=row.sowing, gdd=float(row.gdd), confidence=STAGE_CONFIDENCE_GDD)


def degree_days_base10(daily_temp: pd.Series, year: int) -> pd.Series:
    """Degree days base 10 °C since 1 January of `year` (for pest activity). Trailing sum."""
    t = daily_temp.sort_index().astype(float)
    t = t.reindex(pd.date_range(t.index.min(), t.index.max(), freq="D")).interpolate(limit_direction="both")
    return (t - 10).clip(lower=0).where(t.index >= pd.Timestamp(year, 1, 1), 0).cumsum()
