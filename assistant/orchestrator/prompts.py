"""System prompt, message template and the token budget (sources trimmed first, then history)."""
from __future__ import annotations

from .llm import estimate_tokens, input_budget

SYSTEM = """Jesteś doradcą agronomicznym w aplikacji Field Under Pressure. Pomagasz rolnikowi uprawiającemu pszenicę ozimą i kukurydzę.

Zasady:
- Piszesz po polsku, krótko i konkretnie: 4–8 zdań, chyba że instrukcja mówi inaczej. Bez wstępów i powtarzania pytania.
- „Dziś” to data sezonu z bloku <kontekst>, nie data z zegara.
- Dane pola, ryzyka i pogody bierzesz WYŁĄCZNIE z bloku <kontekst>. Jeśli czegoś tam nie ma, napisz, że tego nie wiesz.
- Powody ryzyka podajesz tylko z wyjaśnienia silnika (pole „powody (silnik)”). Nie wymyślaj własnych przyczyn. Jeśli wyjaśnienie silnika nie zgadza się z metodyką, powiedz to wprost.
- Każde zdanie oparte na metodyce kończysz identyfikatorem źródła w nawiasie kwadratowym, dokładnie tak jak w bloku <zrodla>, np. [pszenica_doradcy:5.1:0007]. Nie używaj identyfikatorów spoza bloku <zrodla>. Nie podawaj numerów stron ani tytułów — dodamy je sami.
- NIGDY nie podawaj nazw handlowych środków ochrony roślin, substancji czynnych do zastosowania ani dawek (l/ha, g/ha itp.). Zamiast tego napisz: „dobór środka i dawki według aktualnej etykiety, skonsultuj z doradcą”. Wolno opisywać progi szkodliwości, terminy lustracji i metody niechemiczne.
- Nie stawiaj pewnej diagnozy z opisu rolnika: zaproponuj lustrację i opisz objawy z metodyki, żeby mógł je porównać.
- Poziomy ryzyka (niskie/średnie/wysokie) są wyliczone z wyniku silnika 0–1; nie przeliczaj ich.
- Opisy silnika bywają po angielsku — przekazuj ich treść po polsku, bez dopisywania nowych faktów.
- Zalecenie silnika „zabieg” znaczy: lustracja i decyzja z doradcą po przekroczeniu progu — nigdy nie podawaj środka ani dawki."""


def _source_block(s: dict) -> str:
    head = f"[{s['chunk_id']}] {s.get('citation_text', '')}"
    if s.get("section"):
        head += f" — {s['section']}"
    return f"{head}\n{s['text']}"


def render(context_lines: list[str], sources: list[dict], history: list[dict], question: str,
           instructions: str = "") -> str:
    parts = ["<kontekst>", *context_lines, "</kontekst>"]
    parts += ["<zrodla>", *([_source_block(s) for s in sources] or ["(brak fragmentów metodyk)"]), "</zrodla>"]
    if history:
        parts += ["<historia>", *[f"{'Rolnik' if h['role'] == 'user' else 'Asystent'}: {h['text']}" for h in history],
                  "</historia>"]
    if instructions:
        parts += ["<instrukcja>", instructions, "</instrukcja>"]
    parts += ["<pytanie>", question, "</pytanie>"]
    return "\n".join(parts)


def build_messages(context_lines: list[str], sources: list[dict], history: list[dict], question: str,
                   instructions: str = "", system: str = SYSTEM, budget: int | None = None) -> tuple[list[dict], dict]:
    """Messages within the input budget. Trims the weakest (last) sources, then the oldest history,
    then long context lines. Returns (messages, info about what was trimmed)."""
    budget = budget or input_budget()
    sources, history = list(sources), list(history)
    info = {"dropped_sources": [], "dropped_history": 0}

    def msgs():
        return [{"role": "system", "content": system},
                {"role": "user", "content": render(context_lines, sources, history, question, instructions)}]

    while estimate_tokens(msgs()) > budget and sources:
        info["dropped_sources"].append(sources.pop()["chunk_id"])
    while estimate_tokens(msgs()) > budget and history:
        history.pop(0)
        info["dropped_history"] += 1
    if estimate_tokens(msgs()) > budget:
        context_lines = [line[:300] for line in context_lines]
    m = msgs()
    info["estimated_input_tokens"] = estimate_tokens(m)
    info["sources"] = [s["chunk_id"] for s in sources]
    return m, info
