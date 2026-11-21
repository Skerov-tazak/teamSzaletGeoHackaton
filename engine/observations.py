"""
Farmer reports (from the chat) and how they change a field's risks.

Reports are read from the database: `core.Observation` (the agreed home, columns in engine/README.md)
and, until that exists, the chat's interim `assistant.Observation` (mapped in `_from_assistant`). Tests
and demos can pass reports to predict(observations=[...]) directly.

Every report only affects days on or after the day it was observed (the "as of that day" rule), and
every applied report becomes a driver in the explanation, with its effect on the score.

Kinds:
- symptoms   the farmer sees the threat on this field -> score floor (0.6 + 0.3 x severity), fading after 10 days;
             without a threat code: x(1 + 0.3 x severity) for every threat of that group (disease / pest)
- absence    inspected, nothing found -> x0.5, back to normal over 10 days (threat_code empty = all threats)
- neighbour  a neighbour / the area has it -> x(1 + 0.5 x closeness), fading over 21 days and 3 km
- treatment  sprayed against it -> x0.3 for 14 days, back to normal by day 21 (threat_code empty = all fungal)
- field_fact details: sowing_date (replaces the assumed one), tillage ("plough" / "reduced"),
             resistant_to ([threat codes] -> x0.6)
- event      details.type (or details.event): hail (fungal x1.3, 14 days), lodging (fungal x1.2, 21 days), flood (crazy top floor 0.7)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

KINDS = ("symptoms", "absence", "neighbour", "treatment", "field_fact", "event")


@dataclass
class Report:
    observed_on: date
    kind: str
    threat_code: str | None = None
    severity: float | None = None     # 0-1
    distance_m: float | None = None   # neighbour reports
    details: dict = field(default_factory=dict)
    text: str = ""
    field_id: int | None = None       # None = whole farm / the area
    id: int | None = None
    group: str | None = None          # "disease" / "pest": threat group of a report without a threat code

    def label(self) -> str:
        from engine.catalog import RULES
        when = self.observed_on.isoformat()
        rule = RULES.get(self.threat_code or "")
        what = f"{rule.name_en} ({rule.name_pl})" if rule else (self.threat_code or "all threats")
        if self.kind == "symptoms" and not rule and self.group:
            return f"Farmer reported {'a pest' if self.group == 'pest' else 'a disease'} on this field on {when}" + (f": \"{self.text}\"" if self.text else "")
        if self.kind == "symptoms":
            return f"Farmer reported {what} on this field on {when}" + (f" (severity {self.severity:.0%})" if self.severity is not None else "")
        if self.kind == "absence":
            return f"Farmer inspected the field on {when} and found no {what if self.threat_code else 'symptoms'}"
        if self.kind == "neighbour":
            where = f" about {self.distance_m:.0f} m away" if self.distance_m else " nearby"
            return f"Reported {what}{where} on {when} (spores can spread to this field)"
        if self.kind == "treatment":
            return f"Treatment against {what} on {when}"
        if self.kind == "event":
            return f"{str(self.details.get('type') or self.details.get('event') or 'event').capitalize()} reported on {when}"
        return f"Field information from the farmer on {when}: " + ", ".join(f"{k}={v}" for k, v in self.details.items())


def _from_core(r) -> Report:
    return Report(
        observed_on=r.observed_on, kind=getattr(r, "kind", "symptoms"), threat_code=getattr(r, "threat_code", None) or None,
        severity=getattr(r, "severity", None), distance_m=getattr(r, "distance_m", None),
        details=getattr(r, "details", None) or {}, text=getattr(r, "text", "") or "", field_id=r.field_id, id=r.pk,
    )


ASSISTANT_SEVERITY = {"niskie": 0.3, "srednie": 0.6, "średnie": 0.6, "wysokie": 0.9}
ASSISTANT_GROUP = {"choroba": "disease", "szkodnik": "pest"}
DISEASE_CATEGORIES = ("fungal", "bacterial", "viral")


def _from_assistant(r) -> Report | None:
    """
    The chat's interim assistant.Observation -> Report. The kind comes from details.kind (or
    details.draft.kind); without it: choroba / szkodnik -> symptoms, uszkodzenie -> event, others ignored.
    """
    raw = r.details or {}
    d = {**(raw.get("draft") or {}), **{k: v for k, v in raw.items() if k not in ("draft", "reassessment")}}
    kind = d.get("kind") or {"choroba": "symptoms", "szkodnik": "symptoms", "uszkodzenie": "event"}.get(r.category)
    if kind not in KINDS:
        return None
    sev = ASSISTANT_SEVERITY.get((r.severity or "").lower())
    if kind == "symptoms" and sev is None:
        sev = 0.5
    details = {k: v for k, v in d.items() if k in ("sowing_date", "tillage", "resistant_to", "type", "event", "scope")}
    if kind == "event" and not (details.get("type") or details.get("event")):
        note = (r.note or "").lower()
        details["type"] = next((t for t, words in (("hail", ("grad",)), ("lodging", ("wylegl", "wyległ", "polegl", "położ")),
                                                    ("flood", ("zalan", "zalał", "powód", "podtop"))) if any(w in note for w in words)), None)
    dist = d.get("distance_m")
    return Report(
        observed_on=r.date, kind=kind, threat_code=r.threat.code if r.threat_id else None, severity=sev,
        distance_m=float(dist) if dist not in (None, "") else (1000.0 if kind == "neighbour" else None),
        details=details, text=r.note or "", field_id=None if d.get("scope") == "farm" else r.field_id, id=r.pk,
        group=ASSISTANT_GROUP.get(r.category),
    )


def _query(end: date, field_id: int | None = None) -> list[Report]:
    from django.apps import apps
    from django.db.models import Q

    out: list[Report] = []
    try:
        core = apps.get_model("core", "Observation")
    except LookupError:
        core = None
    if core is not None:
        q = core.objects.filter(observed_on__lte=end)
        if field_id is not None:
            q = q.filter(Q(field_id=field_id) | Q(field__isnull=True))
        out += [_from_core(r) for r in q]
    try:
        interim = apps.get_model("assistant", "Observation")
    except LookupError:
        interim = None
    if interim is not None:
        q = interim.objects.filter(date__lte=end).select_related("threat")
        rows = [x for x in (_from_assistant(r) for r in q) if x is not None]
        if field_id is not None:
            rows = for_field(rows, field_id)
        out += rows
    return out


def load(field_id: int, start: date, end: date) -> list[Report]:
    """Reports for a field (and farm-wide ones) observed up to `end`."""
    return _query(end, field_id)


def load_all(start: date, end: date) -> list[Report]:
    """All reports of the farm observed up to `end`."""
    return _query(end)


def for_field(reports: list[Report] | None, field_id: int) -> list[Report]:
    return [r for r in (reports or []) if r.field_id in (None, field_id)]


def sowing_override(reports: list[Report]) -> tuple[date, date] | None:
    """(sowing_date, reported_on) from the latest field_fact with a sowing date."""
    facts = [r for r in reports if r.kind == "field_fact" and r.details.get("sowing_date")]
    if not facts:
        return None
    r = max(facts, key=lambda x: x.observed_on)
    sd = r.details["sowing_date"]
    return (sd if isinstance(sd, date) else date.fromisoformat(str(sd))), r.observed_on


def _age(days: pd.DatetimeIndex, on: date) -> np.ndarray:
    """Days since the report (NaN before it: the report is not known yet)."""
    a = (days - pd.Timestamp(on)).days.to_numpy().astype(float)
    a[a < 0] = np.nan
    return a


def _fade(age: np.ndarray, full: float, gone: float) -> np.ndarray:
    """1 for age <= full, linear to 0 at age = gone, 0 before the report (NaN)."""
    w = np.clip(1 - (age - full) / max(gone - full, 1e-9), 0, 1)
    return np.nan_to_num(w, nan=0.0)


@dataclass
class Effect:
    report: Report
    mult: np.ndarray        # multiplier per day (1 = no effect)
    floor: np.ndarray       # minimum score per day (0 = no effect)
    after: np.ndarray       # multiplier applied after the floor (treatments)


def effects(rule, reports: list[Report], days: pd.DatetimeIndex) -> list[Effect]:
    """The effects of the reports on one threat rule, per day."""
    n = len(days)
    one, zero = np.ones(n), np.zeros(n)
    out = []
    for r in reports:
        age = _age(days, r.observed_on)
        known = ~np.isnan(age)
        if not known.any():
            continue
        same = r.threat_code == rule.code
        mult, floor, after = one.copy(), zero.copy(), one.copy()
        if r.kind == "symptoms" and r.threat_code is None and r.group:
            hit = (rule.category == "pest") if r.group == "pest" else (rule.category in DISEASE_CATEGORIES)
            if not hit:
                continue
            sev = 0.5 if r.severity is None else float(r.severity)
            mult = 1 + 0.3 * sev * _fade(age, 10, 21)
        elif r.kind == "symptoms" and same:
            sev = 0.6 if r.severity is None else float(r.severity)
            floor = (0.6 + 0.3 * sev) * _fade(age, 10, 21)
        elif r.kind == "absence" and (same or r.threat_code is None):
            mult = 1 - 0.5 * _fade(age, 0, 10)
        elif r.kind == "neighbour" and same:
            close = 1.0 if not r.distance_m else float(np.clip(1 - (r.distance_m - 500) / 2500, 0, 1))
            mult = 1 + 0.5 * close * _fade(age, 7, 21)
        elif r.kind == "treatment" and (same or (r.threat_code is None and rule.category == "fungal")):
            after = 1 - 0.7 * _fade(age, 14, 21)
        elif r.kind == "field_fact":
            if r.details.get("tillage") == "reduced" and rule.code in ("wheat.fusarium_head_blight", "maize.fusarium_ear_rot",
                                                                      "maize.european_corn_borer", "wheat.tan_spot"):
                mult = np.where(known, 1.3, 1.0)
            if rule.code in (r.details.get("resistant_to") or []):
                mult = mult * np.where(known, 0.6, 1.0)
        elif r.kind == "event":
            t = r.details.get("type") or r.details.get("event")
            if t == "hail" and rule.category in ("fungal", "bacterial"):
                mult = 1 + 0.3 * _fade(age, 7, 14)
            elif t == "lodging" and rule.category == "fungal":
                mult = 1 + 0.2 * _fade(age, 14, 21)
            elif t == "flood" and rule.code == "maize.crazy_top":
                floor = 0.7 * _fade(age, 14, 28)
        if np.allclose(mult, 1) and not floor.any() and np.allclose(after, 1):
            continue
        out.append(Effect(r, mult, floor, after))
    return out


def combine(base: np.ndarray, effs: list[Effect], skip: int | None = None) -> np.ndarray:
    """score = (min(1, base x multipliers) floored by symptom reports) x treatments; `skip` leaves one out."""
    s = np.asarray(base, dtype=float).copy()
    floor = np.zeros_like(s)
    after = np.ones_like(s)
    for i, e in enumerate(effs):
        if i == skip:
            continue
        s = s * e.mult
        floor = np.maximum(floor, e.floor)
        after = after * e.after
    return np.clip(np.maximum(np.minimum(s, 1.0), floor) * after, 0, 1)
