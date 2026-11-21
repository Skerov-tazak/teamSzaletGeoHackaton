"""
Observation flow: message -> (1 LLM call, JSON) draft -> code fills/validates -> farmer confirms ->
record_observation (idempotent) -> engine reassessment -> answer from a template (no LLM).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from assistant import domain
from assistant.tools.registry import ToolError, call

from .flows import FlowResult
from .llm import LLM, complete_json, log_usage
from .router import Route

log = logging.getLogger("assistant.orchestrator")

CATEGORY_PL = {"choroba": "choroba", "szkodnik": "szkodnik", "chwasty": "chwasty", "uszkodzenie": "uszkodzenie",
               "inne": "inne"}


class DraftOut(BaseModel):
    field_id: int | None = None
    date: dt.date | None = None
    category: Literal["choroba", "szkodnik", "chwasty", "uszkodzenie", "inne"] | None = None
    threat: str | None = None
    severity: Literal["niskie", "srednie", "wysokie"] | None = None
    note: str = ""
    missing: list[str] = Field(default_factory=list)


EXTRACT_SYSTEM = ("Wyodrębniasz obserwację rolnika z pola do formularza. Zwracasz wyłącznie JSON z kluczami: "
                  "field_id (id z listy pól albo null), date (YYYY-MM-DD albo null), category (choroba|szkodnik|chwasty|"
                  "uszkodzenie|inne albo null), threat (nazwa z listy zagrożeń albo null — nie zgaduj), severity "
                  "(niskie|srednie|wysokie albo null), note (opis rolnika jego słowami, krótko), missing (lista "
                  "brakujących informacji). Nie wymyślaj pól ani zagrożeń spoza list.")


def _relative_date(message: str, today: dt.date) -> dt.date | None:
    t = domain.fold(message)
    if "przedwczoraj" in t:
        return today - dt.timedelta(days=2)
    if "wczoraj" in t:
        return today - dt.timedelta(days=1)
    m = re.search(r"(\d+)\s+dni\s+temu", t)
    if m:
        return today - dt.timedelta(days=int(m.group(1)))
    if "dzis" in t or "dzisiaj" in t or "rano" in t:
        return today
    return None


def symptom_snippet(text: str, threat_name: str, limit: int = 260) -> str:
    """For a Markdown table: the cells of the row about this threat; otherwise the start of the text."""
    key = domain.fold(threat_name).split()[:2]
    for line in text.splitlines():
        if line.startswith("|") and key and all(k[:5] in domain.fold(line) for k in key):
            cells = [c.strip() for c in line.strip("|").split("|") if c.strip()]
            text = " — ".join(cells[1:]) if len(cells) > 1 else cells[0]
            break
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def draft_text(d: dict) -> str:
    sev = {"niskie": "niskie", "srednie": "średnie", "wysokie": "wysokie"}.get(d.get("severity") or "", "nie podano")
    return (f"**Szkic obserwacji**\n- pole: {d['field']}\n- data: {d['date']}\n- kategoria: {d['category']}\n"
            f"- zagrożenie: {d.get('threat') or 'nie wskazano'}\n- nasilenie: {sev}\n- opis: {d['note']}")


def observation(route: Route, question: str, history, llm: LLM, state, selected_field, conv_id=None) -> FlowResult:
    today = dt.date.fromisoformat(call("get_season_date")["today"])
    fields = call("list_fields")["fields"]
    crop_code = route.crop and {"pszenica": 1110, "kukurydza": 1130}.get(route.crop)
    if route.field_id:
        crop_code = next((f["crop_code"] for f in fields if f["id"] == route.field_id), crop_code)
    from core.models import Threat
    threat_names = list(Threat.objects.filter(**({"crop_id": crop_code} if crop_code else {}))
                        .values_list("name", flat=True)[:40])
    user = (f"Data sezonu (dziś): {today}\nZaznaczone pole: "
            f"{(selected_field.name + ' (id ' + str(selected_field.id) + ')') if selected_field else 'brak'}\n"
            f"Pola: {[{'id': f['id'], 'nazwa': f['name'], 'uprawa': f['crop']} for f in fields]}\n"
            f"Zagrożenia uprawy: {threat_names}\nWiadomość rolnika: {question}")
    out, res = complete_json(llm, [{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": user}],
                             DraftOut, max_tokens=300)
    meta = {"llm_calls": [log_usage(res, kind="obserwacja", extra={"conversation_id": conv_id})], "extracted": out.model_dump(mode="json")}

    # code decides: field, date, threat
    valid_ids = {f["id"] for f in fields}
    field_id = out.field_id if out.field_id in valid_ids else None
    field_id = route.field_id or field_id or (selected_field.id if selected_field else None)
    date = _relative_date(question, today) or (out.date if out.date and out.date <= today else None) or today
    threat = None
    if field_id:
        fcrop = next(f["crop_code"] for f in fields if f["id"] == field_id)
        t = domain.threat_by_code_or_name(out.threat, fcrop) if out.threat else None
        if t is None and route.threats:
            t = Threat.objects.filter(code=route.threats[0], crop_id=fcrop).first()
        threat = t
    category = out.category or ("choroba" if threat and threat.category != "pest" else "szkodnik" if threat else None)

    missing = []
    if field_id is None:
        missing.append("pole")
    if category is None:
        missing.append("kategoria")
    if missing:
        names = ", ".join(f["name"] for f in fields)
        asks = []
        if "pole" in missing:
            asks.append(f"którego pola dotyczy (np. {names}) — możesz też zaznaczyć je na mapie")
        if "kategoria" in missing:
            asks.append("czy to choroba, szkodnik, chwasty czy uszkodzenie")
        return FlowResult("Chętnie zapiszę obserwację. Napisz proszę " + " oraz ".join(asks) + ".", meta=meta)

    fname = next(f["name"] for f in fields if f["id"] == field_id)
    draft = {"draft_id": uuid.uuid4().hex[:12], "field_id": field_id, "field": fname, "date": date.isoformat(),
             "category": category, "threat_code": threat.code if threat else None,
             "threat": threat.name if threat else None, "severity": out.severity,
             "note": (out.note or question).strip()[:500]}
    state.set_draft(draft)
    text = draft_text(draft) + "\n\nZapisać tę obserwację? (tak / nie)"
    sources = []
    if threat:  # one guide passage about symptoms, so the farmer can compare with what they see
        from .context import guide_sources
        crop = domain.crop_pl(next(f["crop_code"] for f in fields if f["id"] == field_id))
        sources, _ = guide_sources([(f"{threat.name} objawy", crop, 2)], budget=350, max_n=1)
        if sources:
            snippet = symptom_snippet(sources[0]["text"], threat.name)
            text += f"\n\nObjawy według metodyki, do porównania z tym, co widzisz: „{snippet}” [{sources[0]['chunk_id']}]"
    return FlowResult(text, sources=sources, focus_field_id=None if route.field_source == "selected" else field_id,
                      pending_action={"type": "confirm_observation", "draft": draft}, meta=meta)


def confirmation(route: Route, question: str, state, conv_id=None) -> FlowResult:
    draft = state.draft
    t = domain.fold(question)
    if draft is None:
        return FlowResult("Nie mam żadnej obserwacji do zapisania.")
    if t.split(" ")[0] in {"nie", "anuluj", "rezygnuje", "odrzuc", "stop"} or t in {"nie trzeba", "nie zapisuj"}:
        state.set_draft(None)
        return FlowResult("Dobrze, nie zapisuję tej obserwacji.")
    key = hashlib.sha256(f"{conv_id}:{draft['draft_id']}".encode()).hexdigest()[:64]
    try:
        res = call("record_observation", field_id=draft["field_id"], date=draft["date"], category=draft["category"],
                   threat=draft.get("threat_code"), severity=draft.get("severity"), note=draft["note"],
                   idempotency_key=key)
    except ToolError as e:
        return FlowResult(f"Nie udało się zapisać obserwacji: {e}")
    draft["saved_observation_id"] = res["observation_id"]
    state.set_draft(draft)  # kept, so a repeated "tak" is answered without a duplicate
    if not res["created"]:
        return FlowResult(f"Ta obserwacja jest już zapisana (nr {res['observation_id']}).",
                          meta={"observation_id": res["observation_id"]})
    r = res["reassessment"]
    text = f"Zapisałem obserwację nr {res['observation_id']} dla pola {draft['field']} ({draft['date']})."
    updated = []
    if r["status"] == "ok":
        updated = [draft["field_id"]]
        ch = r.get("changed", {})
        if ch:
            parts = [f"{(v['after'] or {}).get('threat', c)}: {(v['before'] or {}).get('level', '—')} → {v['after']['level']}"
                     for c, v in list(ch.items())[:3]]
            text += " Silnik przeliczył ryzyko pola: " + "; ".join(parts) + "."
        else:
            text += " Silnik przeliczył ryzyko pola — poziomy zagrożeń na dziś się nie zmieniły."
    elif r["status"] == "unavailable":
        text += " Silnik decyzyjny nie jest jeszcze podłączony, więc ryzyko pola nie zostało przeliczone."
    else:
        text += " Ponowna ocena ryzyka się nie udała; obserwacja jest zapisana, spróbuj przeliczyć później."
    return FlowResult(text, updated_field_ids=updated,
                      focus_field_id=None if route.field_source == "selected" else draft["field_id"],
                      meta={"observation_id": res["observation_id"], "reassessment_status": r["status"]})
