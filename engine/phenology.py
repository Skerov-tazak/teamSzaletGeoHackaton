"""
Growth stage (BBCH) per day from growing degree days (GDD).

No sowing dates exist in the data, so the model uses typical regional dates (team assumption) and
reports a stage_confidence below 1. Each estimate says how it was made, for the explanation.

- Winter wheat: sown ~1 October. Autumn development from GDD base 0 °C since sowing (to BBCH 25,
  tillering, by winter). From 1 January the spring development follows GDD base 0 °C since 1 January.
- Maize: sown ~25 April. GDD base 6 °C since sowing.
- Winter barley and other winter cereals: like wheat, sown a little earlier, heading and harvest earlier.
- Winter rapeseed: sown ~25 August (before the season starts on 1 September). Autumn and spring
  development from GDD base 5 °C (since sowing / since 1 January).
- Sugar beet: sown ~5 April, GDD base 3 °C since sowing. Potato: planted ~20 April, GDD base 6 °C.

The GDD -> BBCH tables are calibrated to typical dates in Opolskie (heading end of May, wheat
harvest mid-July; maize tasseling mid/late July, maturity end of September).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from engine.catalog import BARLEY, MAIZE, OTHER_CEREALS, POTATO, RAPESEED, SUGAR_BEET, WHEAT

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


def _scaled(table, k):
    """The same stage curve reached with k x the degree days (k < 1 = an earlier crop)."""
    return [(g * k if b > 25 else g, b) for g, b in table]


# Other crops: typical dates in Opolskie (team assumption, not calibrated to the satellite yet).
BARLEY_SPRING = _scaled(WHEAT_SPRING, 0.82)         # heading ~ mid May, harvest early July
OTHER_CEREALS_SPRING = _scaled(WHEAT_SPRING, 0.95)
RAPESEED_AUTUMN = [(0, 0), (70, 9), (120, 10), (200, 12), (300, 14), (400, 16), (500, 18), (650, 19)]   # base 5, since sowing
RAPESEED_SPRING = [(0, 19), (30, 30), (80, 50), (130, 60), (200, 65), (300, 69), (500, 75), (700, 79),
                   (850, 83), (1000, 89), (1100, 92)]  # base 5, since 1 Jan: flowering late April - mid May, harvest mid July
SUGAR_BEET_TABLE = [(0, 0), (110, 10), (200, 12), (300, 14), (500, 19), (700, 31), (900, 39), (1600, 45), (2200, 49)]  # base 3
POTATO_TABLE = [(0, 0), (130, 9), (200, 15), (300, 21), (450, 35), (550, 51), (650, 61), (750, 65), (850, 69),
                (1000, 75), (1300, 91), (1500, 97)]  # base 6, since planting


@dataclass(frozen=True)
class Profile:
    winter: bool              # sown in autumn of the previous year
    sowing: tuple             # (month, day), team assumption
    base: float               # GDD base temperature (°C)
    table: list               # spring crops: since sowing; winter crops: spring curve since 1 January
    autumn: list | None = None
    spring_base: float | None = None  # winter crops: base of the spring curve (default: base)
    season_end: tuple = (8, 31)       # last day of the crop's season (harvest), (month, day) of the season year


PROFILES = {
    WHEAT: Profile(True, (10, 1), 0.0, WHEAT_SPRING, WHEAT_AUTUMN),
    BARLEY: Profile(True, (9, 20), 0.0, BARLEY_SPRING, WHEAT_AUTUMN),
    OTHER_CEREALS: Profile(True, (9, 25), 0.0, OTHER_CEREALS_SPRING, WHEAT_AUTUMN),
    RAPESEED: Profile(True, (8, 25), 5.0, RAPESEED_SPRING, RAPESEED_AUTUMN),
    MAIZE: Profile(False, (4, 25), 6.0, MAIZE_TABLE, season_end=(12, 31)),
    SUGAR_BEET: Profile(False, (4, 5), 3.0, SUGAR_BEET_TABLE, season_end=(11, 30)),
    POTATO: Profile(False, (4, 20), 6.0, POTATO_TABLE, season_end=(10, 31)),
}
DEFAULT_SOWING = {c: p.sowing for c, p in PROFILES.items()}  # (month, day), team assumption
GDD_BASE = {c: p.base for c, p in PROFILES.items()}


def season_end(crop: int, season: int) -> date:
    """Last day a crop of `season` is in the field (spring crops harvested after 31 August stay open)."""
    m, d = PROFILES[crop].season_end if crop in PROFILES else (8, 31)
    return date(season, m, d)


def crop_season(crop: int, day: date) -> int:
    """The season a day belongs to for this crop (a beet field in October still belongs to that year)."""
    s = day.year + 1 if day.month >= 9 else day.year
    if crop in PROFILES and not PROFILES[crop].winter and day.month >= 9 and day <= season_end(crop, day.year):
        return day.year
    return s
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


RAPESEED_STAGE_NAMES = [
    (-1, "not sown yet"), (0, "sown, germinating"), (9, "emergence"), (10, "leaf development (rosette)"),
    (30, "stem elongation"), (50, "flower buds"), (60, "flowering"), (70, "pod development"), (80, "ripening"),
    (89, "fully ripe"), (92, "harvest / over-ripe"),
]
SUGAR_BEET_STAGE_NAMES = [
    (-1, "not sown yet"), (0, "sown, germinating"), (10, "emergence, cotyledons"), (11, "leaf development"),
    (31, "canopy closing"), (39, "canopy closed"), (40, "root growth"), (49, "root harvestable"),
]
POTATO_STAGE_NAMES = [
    (-1, "not planted yet"), (0, "planted, sprouting"), (9, "emergence"), (10, "leaf development"),
    (21, "side shoots"), (31, "rows closing"), (40, "tuber formation"), (51, "flower buds"), (60, "flowering"),
    (70, "berries, tuber bulking"), (91, "haulm senescence"), (97, "haulm dead"),
]
CROP_STAGE_NAMES = {MAIZE: MAIZE_STAGE_NAMES, RAPESEED: RAPESEED_STAGE_NAMES, SUGAR_BEET: SUGAR_BEET_STAGE_NAMES,
                    POTATO: POTATO_STAGE_NAMES}


def stage_name(bbch: float, crop: int | None = None) -> str:
    names = CROP_STAGE_NAMES.get(crop, STAGE_NAMES)
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
    prof = PROFILES.get(crop, PROFILES[MAIZE])
    base = prof.base
    month, day = prof.sowing
    out = pd.DataFrame(index=t.index)
    given = sowing is not None
    if prof.winter:
        sowing = pd.Timestamp(sowing) if given else pd.Timestamp(season - 1, month, day)
        gdd_day = (t - base).clip(lower=0)
        spring_day = (t - (prof.spring_base if prof.spring_base is not None else base)).clip(lower=0)
        autumn = gdd_day.where((t.index >= sowing) & (t.index < pd.Timestamp(season, 1, 1)), 0).cumsum()
        spring = spring_day.where(t.index >= pd.Timestamp(season, 1, 1), 0).cumsum()
        bbch_aut = _interp(prof.autumn, autumn.values)
        bbch_spr = _interp(prof.table, spring.values)
        in_spring = t.index >= pd.Timestamp(season, 1, 1)
        out["bbch"] = np.where(in_spring, np.maximum(bbch_spr, bbch_aut), bbch_aut)
        out.loc[t.index < sowing, "bbch"] = -1
        out["gdd"] = np.where(in_spring, spring.values, autumn.values)
    else:
        sowing = pd.Timestamp(sowing) if given else pd.Timestamp(season, month, day)
        gdd = (t - base).clip(lower=0).where(t.index >= sowing, 0).cumsum()
        out["bbch"] = _interp(prof.table, gdd.values)
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
    if not anchors or crop not in (WHEAT, MAIZE):  # satellite anchors exist for wheat and maize only
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
