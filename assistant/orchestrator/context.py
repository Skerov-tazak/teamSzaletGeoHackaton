"""Context for the prompt, built by code from the tools (no LLM): field, engine risks, guide sources."""
from __future__ import annotations

import logging

from assistant import domain
from assistant.tools.guides import fit_passages
from assistant.tools.registry import ToolError, call

log = logging.getLogger("assistant.orchestrator")

SOURCES_TOKEN_BUDGET = 2000
MAX_SOURCES = 5
FACTOR_LABELS = {"avg_temperature": "średnia temp.", "avg_relative_humidity": "wilgotność wzgl.",
                 "total_precipitation": "opady", "min_temperature": "temp. min.", "max_temperature": "temp. maks."}


def _fmt(x, nd=2) -> str:
    return f"{x:.{nd}f}".replace(".", ",") if isinstance(x, (int, float)) else str(x)


def season_lines() -> list[str]:
    d = call("get_season_date")
    return [f"Data sezonu (dziś): {d['today']}; prognoza do {d['forecast_until']}."]


def field_line(field: dict) -> str:
    return f"Pole: {field['name']} (id {field['id']}; {field['crop']}, {_fmt(field['area_ha'], 1)} ha)"


ACTION_PL = {"wait": "czekać (ryzyko niskie albo poza wrażliwą fazą)",
             "monitor": "obserwować pole (lustracja)",
             "treat": "lustracja teraz; zabieg uzasadniony dopiero po przekroczeniu progu szkodliwości"}


def _driver(d: dict) -> str:
    s = d.get("label", "")
    if d.get("value") is not None and str(d.get("value")) not in s:
        s += f" = {d['value']} {d.get('unit', '')}".rstrip()
    if d.get("text"):
        s += f" (rolnik: „{d['text']}”)"
    return s


def growth_stage_line(threats: list[dict]) -> str | None:
    for t in threats:
        gs = (t.get("explanation") or {}).get("growth_stage")
        if gs:
            line = f"Faza rozwojowa (silnik): BBCH {gs.get('bbch')} — {gs.get('name', '')}"
            if gs.get("sowing_assumed"):
                line += f"; data siewu przyjęta: {gs['sowing_assumed']}"
            return line
    return None


def threat_lines(t: dict, with_factors: bool = True) -> list[str]:
    today = t["today"]
    rising = f", rośnie od {t['rising_days']} dni" if t.get("rising_days", 0) >= 2 else ""
    line = (f"- {t['threat']}: dziś {_fmt(today['score'])} ({today['level']}), trend {t['trend']}{rising}; "
            f"maks. w okresie {_fmt(t['max']['score'])} ({t['max']['level']}) dnia {t['max']['date']}")
    out = [line]
    expl = t.get("explanation") or {}
    if expl.get("summary"):
        out.append(f"  powody (silnik): {expl['summary']}")
    if with_factors and expl.get("drivers"):
        ds = "; ".join(_driver(d) for d in expl["drivers"][:4])
        out.append(f"  czynniki (silnik, od najważniejszego): {ds}")
    act = expl.get("action") or {}
    if act.get("type"):
        a = f"  zalecenie silnika: {ACTION_PL.get(act['type'], act['type'])}"
        if act.get("threshold"):
            a += f"; próg dla tej fazy: {act['threshold']}"
        if act.get("weather_window"):
            a += f"; najbliższe okno pogodowe na zabieg: {act['weather_window']}"
        out.append(a)
    if with_factors and expl.get("factors"):
        fs = "; ".join(f"{FACTOR_LABELS.get(f.get('variable'), f.get('variable'))} {f.get('value')} {f.get('unit', '')}"
                       f" (próg: {f.get('threshold', '?')})" for f in expl["factors"][:4])
        out.append(f"  czynniki: {fs}")
    return out


def field_risk_context(field_id: int, threat_codes: list[str] | None = None, max_threats: int = 3):
    """(context lines, focus threats [dicts], risk citations) for a field, today-3 … today+7."""
    lines, focus = [], []
    if threat_codes:
        for code in threat_codes[:2]:
            try:
                r = call("get_field_risks", field_id=field_id, threat=code)
                focus += r["threats"]
            except ToolError as e:
                log.info("threat %s: %s", code, e)
        field = call("get_field", field_id=field_id)
        rest = []
    else:
        r = call("get_field_risks", field_id=field_id)
        field = r["field"]
        focus = r["threats"][:max_threats]
        rest = [t["threat"] for t in r["threats"][max_threats:]] + r.get("other_threats_low", [])
    lines.append(field_line(field))
    gs = growth_stage_line(focus)
    if gs:
        lines.append(gs)
    lines.append("Ryzyko według silnika decyzyjnego (poziomy silnika: <0,3 niskie, <0,6 średnie, wyżej wysokie):")
    if not focus:
        lines.append("- brak danych o ryzyku dla tego pola w okresie dziś−3 … dziś+7")
    for t in focus:
        lines += threat_lines(t)
    if rest:
        lines.append(f"Pozostałe zagrożenia (niższe ryzyko): {', '.join(rest[:8])}{'…' if len(rest) > 8 else ''}")
    return lines, focus, [t["citation"] for t in focus]


def risk_condition_sources(crop: str | None, threat_names: list[str]) -> list[dict]:
    """Rows of the risk spreadsheet as citable sources (chunk ids ryzyka_zebrane:{crop}.r{row})."""
    if crop not in ("pszenica", "kukurydza"):
        return []
    out = []
    for name in threat_names[:2]:
        rows = call("get_risk_conditions", crop=crop, threat=name)["rows"][:1]
        for r in rows:
            parts = [f"temperatura: {r['temperature_raw']}" if r.get("temperature_raw") else "",
                     f"wilgotność: {r['humidity_raw']}" if r.get("humidity_raw") else "",
                     f"inne: {r['other_factors']}" if r.get("other_factors") else ""]
            out.append({"chunk_id": r["chunk_id"], "citation_text": f"Zestawienie warunków ryzyka, arkusz „{r['sheet']}”, wiersz {r['row']}",
                        "section": "", "kind": "excel_row",
                        "text": f"Warunki sprzyjające ({r['threat']}): " + "; ".join(p for p in parts if p),
                        "citation": {"type": "guide", "document": "ryzyka_zebrane.xlsx", "sheet": r["sheet"], "row": r["row"]}})
    return out


def guide_sources(queries: list[tuple[str, str | None, int]], budget: int = SOURCES_TOKEN_BUDGET,
                  max_n: int = MAX_SOURCES, exclude: set[str] | None = None) -> tuple[list[dict], str | None]:
    """Run several searches, interleave by rank, dedupe, fit the token budget.
    Returns (sources, error message or None)."""
    from assistant.rag.search import search
    from assistant.rag.store import QdrantUnavailable
    results = []
    try:
        for q, crop, k in queries:  # no crop -> only the farm's crops' guides (not oats, rye, potatoes…)
            results.append(search(q, crop=crop or "farm", k=k, include_pesticide_doses=False))
    except QdrantUnavailable:
        return [], "Wyszukiwarka metodyk jest niedostępna — odpowiadaj bez cytatów z metodyk i powiedz o tym."
    seen = set(exclude or ())
    merged = []
    for i in range(max((len(r) for r in results), default=0)):
        for r in results:
            if i < len(r) and r[i].chunk_id not in seen:
                seen.add(r[i].chunk_id)
                merged.append(r[i])
    return fit_passages(merged[:max_n * 2], budget)[:max_n], None


def threat_query(name: str, crop: str | None) -> str:
    return f"{name} {crop or ''} warunki rozwoju objawy ograniczanie niechemiczne lustracja".strip()


def crop_of_code(code: int | None) -> str | None:
    return domain.CROP_PL.get(code or -1)
