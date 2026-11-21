"""
Flows per question type. Code decides and fetches; the model writes. At most ONE LLM call per flow
(the observation extraction is its own single call).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from assistant import domain
from assistant.tools.registry import ToolError, call

from . import context as ctx
from . import guard
from .llm import LLM, LLMResult, log_usage, strip_think
from .prompts import build_messages
from .router import Route

log = logging.getLogger("assistant.orchestrator")


@dataclass
class FlowResult:
    text: str
    sources: list[dict] = field(default_factory=list)        # passages given to the model (citable)
    risk_citations: list[dict] = field(default_factory=list)
    focus_field_id: int | None = None
    updated_field_ids: list[int] = field(default_factory=list)
    chart: dict | None = None
    pending_action: dict | None = None
    meta: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- the one LLM call
def ask_llm(llm: LLM, kind: str, context_lines, sources, question, history, instructions="",
            max_tokens: int | None = None, conversation_id=None) -> tuple[str, dict]:
    messages, info = build_messages(context_lines, sources, history, question, instructions)
    res: LLMResult = llm.complete(messages, max_tokens=max_tokens)
    calls = [log_usage(res, kind=kind, extra={"conversation_id": conversation_id})]
    text = strip_think(res.text)
    doses = guard.find_doses(text)
    if doses:
        log.warning("dose in answer (%s): %s — regenerating once", kind, doses)
        retry = messages + [{"role": "assistant", "content": text}, {"role": "user", "content": guard.REGENERATE_NOTE}]
        res2 = llm.complete(retry, max_tokens=max_tokens)
        calls.append(log_usage(res2, kind=kind + ":regenerate", extra={"conversation_id": conversation_id}))
        text = strip_think(res2.text)
        if guard.find_doses(text):
            log.warning("dose again after regeneration — safe message")
            text = guard.SAFE_MESSAGE
    meta = {"llm_calls": calls, "prompt_info": info, "guard_triggered": bool(doses),
            "prompt": messages}  # the prompt is kept for `manage.py chat --show-prompt`, not stored in Message.meta
    return text, meta


# ----------------------------------------------------------------------------- dose requests
DOSE_INTENT = re.compile(r"\bdawk|ile (litr|ml|mililitr|gram|kilogram|kg)|\b(l|ml|g|kg)\s*/\s*ha|jaki(m|ego)? (srod|preparat|fungicyd|herbicyd|insektycyd)|"
                         r"czym (opryskac|pryskac|zwalczyc)|nazw\w* (srod|preparat)|jaki fungicyd|jaki herbicyd|jaki insektycyd")
DOSE_INSTRUCTION = ("Rolnik pyta o środek ochrony roślin lub dawkę. NIE podawaj nazw środków ani dawek. Napisz wprost, "
                    "że dobór środka i dawki jest według aktualnej etykiety i w porozumieniu z doradcą. Możesz opisać "
                    "progi szkodliwości, termin lustracji i metody niechemiczne z cytatami.")
LABEL_REFERRAL = "Dobór środka i dawki — zawsze według aktualnej etykiety środka; w razie wątpliwości skonsultuj się z doradcą."


def asks_for_dose(question: str) -> bool:
    return bool(DOSE_INTENT.search(domain.fold(question)))


def ensure_referral(text: str, question: str) -> str:
    if asks_for_dose(question) and "etykiet" not in text.lower():
        text = text.rstrip() + "\n\n" + LABEL_REFERRAL
    return text


# ----------------------------------------------------------------------------- general question
def general(route: Route, question: str, history, llm: LLM, conv_id=None) -> FlowResult:
    crop = route.crop
    sources, err = ctx.guide_sources([(question, crop, 4)], budget=1800, max_n=4)
    if route.threats and crop in ("pszenica", "kukurydza"):
        from core.models import Threat
        names = list(Threat.objects.filter(code__in=route.threats).values_list("name", flat=True))
        sources = ctx.risk_condition_sources(crop, names)[:1] + sources
    lines = ctx.season_lines() + ([f"Uprawa z pytania: {crop}"] if crop else []) + ([err] if err else [])
    instructions = "Odpowiedz na pytanie na podstawie źródeł, z cytatami."
    if asks_for_dose(question):
        instructions += " " + DOSE_INSTRUCTION
    text, meta = ask_llm(llm, route.type, lines, sources, question, history, instructions, conversation_id=conv_id)
    return FlowResult(ensure_referral(text, question), sources=sources, meta=meta | {"dose_request": asks_for_dose(question)})


# ----------------------------------------------------------------------------- question about a field
def _pick_field(route: Route) -> tuple[int | None, str]:
    if route.field_id:
        return route.field_id, route.field_source
    s = call("get_farm_risk_summary")
    if s["fields"]:
        return s["fields"][0]["id"], "highest_risk"
    return None, ""


def field_question(route: Route, question: str, history, llm: LLM, conv_id=None) -> FlowResult:
    field_id, how = _pick_field(route)
    if field_id is None:
        return FlowResult("Nie mam jeszcze danych o polach gospodarstwa, więc nie mogę ocenić ryzyka.")
    lines = ctx.season_lines()
    risk_lines, focus, risk_cits = ctx.field_risk_context(field_id, route.threats or None)
    lines += risk_lines
    if how == "highest_risk":
        lines.append("Uwaga: rolnik nie wskazał pola — wybrano pole o najwyższym ryzyku dziś; powiedz na początku, "
                     "którego pola dotyczy odpowiedź.")
    crop = route.crop or ctx.crop_of_code(call("get_field", field_id=field_id)["crop_code"])
    top = [t for t in focus][:2]
    queries = [(ctx.threat_query(t["threat"], crop), crop, 3) for t in top]
    if route.threats or len(question.split()) > 6:  # a specific question adds its own search
        queries.append((question, crop, 3))
    sources, err = ctx.guide_sources(queries, budget=ctx.SOURCES_TOKEN_BUDGET, max_n=ctx.MAX_SOURCES)
    sources = ctx.risk_condition_sources(crop, [t["threat"] for t in top]) + sources
    sources = sources[:ctx.MAX_SOURCES + 1]
    if err:
        lines.append(err)
    instructions = ("Struktura odpowiedzi (bez nagłówków, 4–8 zdań): (a) dlaczego pole jest zagrożone — tylko powody "
                    "z silnika; (b) co mówi metodyka o tym zagrożeniu — z cytatem; (c) co zrobić teraz — lustracja, "
                    "metody niechemiczne, kiedy skontaktować się z doradcą; (d) jeśli dane silnika i metodyka się "
                    "rozjeżdżają, powiedz to.")
    if asks_for_dose(question):
        instructions += " " + DOSE_INSTRUCTION
    text, meta = ask_llm(llm, route.type, lines, sources, question, history, instructions, conversation_id=conv_id)
    meta["field_id"], meta["field_choice"] = field_id, how
    return FlowResult(ensure_referral(text, question), sources=sources, risk_citations=risk_cits,
                      focus_field_id=field_id if how not in ("selected", "conversation") else None, meta=meta)


# ----------------------------------------------------------------------------- farm overview
def farm_summary(route: Route, question: str, history, llm: LLM, conv_id=None) -> FlowResult:
    s = call("get_farm_risk_summary")
    lines = ctx.season_lines() + ["Najpilniejsze pary pole × zagrożenie (silnik; poziomy tymczasowe):"]
    picked, used_fields = [], set()
    for p in s["most_urgent"]:  # prefer one pair per field
        if p["field_id"] not in used_fields:
            picked.append(p)
            used_fields.add(p["field_id"])
        if len(picked) == 3:
            break
    for p in picked:
        lines.append(f"- {p['field']} (id {p['field_id']}): {p['threat']} — {ctx._fmt(p['score'])} ({p['level']}), "
                     f"trend {p['trend']}; powody (silnik): {p['explanation']}")
    lines.append("Wszystkie pola (maks. ryzyko dziś): " + "; ".join(
        f"{f['name']} {ctx._fmt(f['max_score']) if f['max_score'] is not None else '—'} ({f['max_level']})" for f in s["fields"]))
    crops = {}
    for p in picked:
        crop = ctx.crop_of_code(next(f["crop_code"] for f in s["fields"] if f["id"] == p["field_id"]))
        crops.setdefault(p["threat"], crop)
    threats = list(crops.items())[:2]
    sources, err = ctx.guide_sources([(ctx.threat_query(t, c), c, 2) for t, c in threats], budget=1600, max_n=4)
    if err:
        lines.append(err)
    instructions = ("Omów TYLKO pola z listy „Najpilniejsze pary”, od najpilniejszego. Przy każdym: zagrożenie, powód "
                    "z silnika i JEDNO konkretne działanie (np. lustracja, metoda niechemiczna), z cytatem metodyki, jeśli "
                    "pasuje. Pozostałe pola wspomnij jednym zdaniem na końcu (bez wymyślania powodów).")
    text, meta = ask_llm(llm, route.type, lines, sources, question, history, instructions, conversation_id=conv_id)
    if picked:  # a follow-up ("co mam zrobić?") continues with the most urgent field
        meta["field_id"] = picked[0]["field_id"]
    return FlowResult(text, sources=sources, risk_citations=[p["citation"] for p in picked], meta=meta)


# ----------------------------------------------------------------------------- charts
WEATHER_WORDS = {"opad": "total_precipitation", "deszcz": "total_precipitation",
                 "wilgot": "avg_relative_humidity", "temperatur": "avg_temperature", "cieplo": "avg_temperature"}


def chart(route: Route, question: str, history, llm: LLM, conv_id=None) -> FlowResult:
    q = domain.fold(question)
    fields = route.field_ids or ([route.field_id] if route.field_id else [])
    if not fields:
        fid, _ = _pick_field(route)
        fields = [fid] if fid else []
    if not fields:
        return FlowResult("Nie mam danych o polach, więc nie mogę narysować wykresu.")
    threat = route.threats[0] if route.threats else None
    if threat is None:
        r = call("get_field_risks", field_id=fields[0])
        if not r["threats"]:
            return FlowResult("Na tym polu nie ma teraz istotnych zagrożeń do pokazania na wykresie.")
        threat = r["threats"][0]["threat_code"]
    variable = next((v for k, v in WEATHER_WORDS.items() if k in q), None)
    try:
        if variable:
            res = call("chart_weather_vs_risk", field_id=fields[0], variable=variable, threat=threat)
        else:
            res = call("chart_risk_timeline", field_ids=fields[:6], threat=threat)
    except ToolError as e:
        return FlowResult(f"Nie mogę przygotować wykresu: {e}")
    import json
    summary = json.dumps(res["summary"], ensure_ascii=False, default=str)
    lines = ctx.season_lines() + [f"Podsumowanie wykresu (liczby policzone przez aplikację): {summary}"]
    text, meta = ask_llm(llm, route.type, lines, [], question, [],
                         "Napisz 1–2 zdania komentarza do wykresu, używając WYŁĄCZNIE liczb z podsumowania. "
                         "Nie cytuj metodyk.", max_tokens=200, conversation_id=conv_id)
    return FlowResult(text, risk_citations=res.get("citations", []), chart=res["chart"],
                      meta=meta | {"chart_summary": res["summary"]})


# ----------------------------------------------------------------------------- out of scope
CAPABILITIES = ("Jestem asystentem agronomicznym dla pszenicy i kukurydzy w tym gospodarstwie. Mogę: wyjaśnić, "
                "dlaczego pole jest zagrożone (na podstawie oceny ryzyka), podać warunki rozwoju chorób i szkodników "
                "z oficjalnych metodyk integrowanej ochrony roślin (z cytatami), pokazać wykres ryzyka lub pogody, "
                "podsumować najpilniejsze pola i zapisać Twoją obserwację z pola. Nie doradzam środków ochrony "
                "roślin ani dawek.")


def out_of_scope(route: Route, question: str, history, llm: LLM, conv_id=None) -> FlowResult:
    return FlowResult(CAPABILITIES, meta={"llm_calls": []})


def complex_question(route: Route, question: str, history, llm: LLM, conv_id=None) -> FlowResult:
    """Agent mode is optional (step G); without it complex questions use the single-call flows."""
    if route.field_id or route.field_ids:
        return field_question(route, question, history, llm, conv_id)
    return farm_summary(route, question, history, llm, conv_id)


def strip_markdown_noise(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()
