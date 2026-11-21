"""
record_observation: write a farmer's observation, then ask the engine to reassess the field.

Only after the user confirmed a draft (orchestrator flow / MCP `confirm=true`). Idempotent by
`idempotency_key`. Stored in the interim assistant.Observation table until core.Observation exists.
An engine failure does not undo the observation (reassessment.status = "failed"/"unavailable").
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Literal

from pydantic import BaseModel, Field

from assistant import domain
from .platform import _field, season_today
from .registry import ToolError, register

log = logging.getLogger("assistant.tools")

Category = Literal["choroba", "szkodnik", "chwasty", "uszkodzenie", "inne"]
Severity = Literal["niskie", "srednie", "wysokie"]
Kind = Literal["symptoms", "absence", "neighbour", "treatment", "field_fact", "event"]
ENGINE_FACT_KEYS = ("sowing_date", "tillage", "resistant_to", "distance_m", "type", "scope")


def engine_predict():
    """engine.predict(field_ids=..., start=...) if the engine exists, else None."""
    for mod, attr in (("engine", "predict"), ("engine.predict", "predict"), ("engine.engine", "predict")):
        try:
            m = __import__(mod, fromlist=[attr])
            fn = getattr(m, attr, None)
            if callable(fn):
                return fn
        except ImportError:
            continue
    return None


def field_levels(field, day: dt.date) -> dict[str, dict]:
    from core.models import Risk
    return {r.threat.code: {"threat": r.threat.name, "score": round(r.score, 2), "level": domain.level(r.score)[1]}
            for r in Risk.objects.filter(field=field, date=day).select_related("threat")}


class ObservationIn(BaseModel):
    field_id: int
    date: dt.date | None = Field(None, description="Dzień obserwacji; domyślnie dziś (data sezonu).")
    category: Category
    threat: str | None = Field(None, description="Kod lub nazwa zagrożenia (opcjonalnie).")
    severity: Severity | None = None
    note: str = Field(description="Opis rolnika jego słowami.")
    idempotency_key: str = Field(min_length=8, max_length=64)
    kind: Kind | None = Field(None, description="symptoms (widzę objawy; domyślnie) | absence (sprawdziłem, czysto) | "
                                                "neighbour (u sąsiada) | treatment (wykonałem zabieg) | field_fact (fakt o polu: "
                                                "data siewu, uprawa) | event (grad, wyleganie, zalanie)")
    facts: dict | None = Field(None, description="Dla silnika: sowing_date (YYYY-MM-DD), tillage (reduced|plough), "
                                                 "distance_m (sąsiad), type (hail|lodging|flood), scope (farm)")


def resolve_draft(field_id, date, category, threat, severity, note) -> dict:
    """Validate an observation draft without saving (also the MCP dry run)."""
    f = _field(field_id)
    today = season_today()
    d = date or today
    if d > today:
        raise ToolError(f"Data obserwacji {d} jest w przyszłości (dziś w sezonie: {today}).")
    t = domain.threat_by_code_or_name(threat, f.crop_id) if threat else None
    return {"field_id": f.id, "field": f.name, "crop": domain.crop_pl(f.crop_id), "date": d, "category": category,
            "threat_code": t.code if t else None, "threat": t.name if t else None,
            "threat_unrecognized": bool(threat and not t), "severity": severity, "note": note}


@register("record_observation", """
Zapisuje obserwację rolnika z pola (choroba, szkodnik, chwasty, uszkodzenie, inne) i uruchamia
ponowną ocenę ryzyka pola przez silnik. ZAPIS: wolno wywołać tylko po tym, jak użytkownik
zobaczył szkic i potwierdził. Ten sam idempotency_key nie tworzy duplikatu. Zwraca id obserwacji
i zmianę ryzyka (przed/po) dla pola na dziś.
""", ObservationIn, writes=True, agent_visible=False)
def record_observation(field_id, date, category, threat, severity, note, idempotency_key, kind=None, facts=None) -> dict:
    from django.db import transaction

    from assistant.models import Observation

    existing = Observation.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return {"observation_id": existing.id, "created": False, "draft": None,
                "reassessment": existing.details.get("reassessment", {"status": "skipped"})}
    draft = resolve_draft(field_id, date, category, threat, severity, note)
    f = _field(field_id)
    today = season_today()
    before = field_levels(f, today)
    with transaction.atomic():
        obs, created = Observation.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={"field": f, "date": draft["date"], "category": category,
                      "threat_id": None, "severity": severity or "", "note": note,
                      # engine format (engine/README.md "Observation rows"): kind + known fact keys at top level
                      "details": {"draft": {k: str(v) if isinstance(v, dt.date) else v for k, v in draft.items()},
                                  **({"kind": kind} if kind else {}),
                                  **{k: v for k, v in (facts or {}).items() if k in ENGINE_FACT_KEYS and v not in (None, "")}}})
        if created and draft["threat_code"]:
            from core.models import Threat
            obs.threat = Threat.objects.get(code=draft["threat_code"])
            obs.save(update_fields=["threat"])
    if not created:
        return {"observation_id": obs.id, "created": False, "draft": draft,
                "reassessment": obs.details.get("reassessment", {"status": "skipped"})}

    predict = engine_predict()
    if predict is None:
        reassessment = {"status": "unavailable", "message": "Silnik decyzyjny nie jest jeszcze dostępny.",
                        "before": before, "after": before}
    else:
        try:
            from django.utils import timezone

            from core.models import Risk
            t0 = timezone.now()
            rows = predict(field_ids=[f.id], start=draft["date"])
            after = field_levels(f, today)
            changed = {c: {"before": before.get(c), "after": a} for c, a in after.items()
                       if before.get(c, {}).get("score") != a["score"]}
            # the engine also recomputes nearby fields of the same crop when symptoms spread
            recomputed = sorted(set(Risk.objects.filter(computed_at__gte=t0).values_list("field_id", flat=True))) or [f.id]
            reassessment = {"status": "ok", "rows_written": rows, "before": before, "after": after, "changed": changed,
                            "recomputed_field_ids": recomputed}
        except Exception as e:  # noqa: BLE001 - the observation stays saved
            log.exception("engine.predict failed after observation %s", obs.id)
            reassessment = {"status": "failed", "message": f"Ponowna ocena ryzyka nie powiodła się: {e}",
                            "before": before, "after": before}
    obs.details = obs.details | {"reassessment": {k: v for k, v in reassessment.items() if k in ("status", "message", "rows_written")}}
    obs.save(update_fields=["details"])
    return {"observation_id": obs.id, "created": True, "draft": draft, "reassessment": reassessment}
