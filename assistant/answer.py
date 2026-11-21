"""
The assistant's single entry point, called by the chat endpoint (docs/interfaces.md -> Chat).

    answer(conversation, message, selected_field) -> Reply

The platform saves the user's message before calling and the reply afterwards. Nothing raises
out of here: any error becomes a Polish message in Reply.text (stack trace in the log).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field as dataclass_field

from assistant.models import Conversation

log = logging.getLogger("assistant.answer")


@dataclass
class Reply:
    # --- the agreed contract (docs/interfaces.md) ---
    text: str                                                    # markdown
    citations: list[dict] = dataclass_field(default_factory=list)
    focus_field_id: int | None = None
    updated_field_ids: list[int] = dataclass_field(default_factory=list)
    # --- proposed extensions (assistant/INTERFACE_PROPOSALS.md #6); defaults keep old callers working ---
    chart: dict | None = None             # Vega-Lite v5 spec
    pending_action: dict | None = None    # e.g. {"type": "confirm_observation", "draft": {...}}
    meta: dict = dataclass_field(default_factory=dict)  # route, LLM usage (stored in Message.meta)


_LLM = None


def default_llm():
    """The configured real LLM (cached per process)."""
    global _LLM
    if _LLM is None:
        import os
        if os.getenv("ASSISTANT_LLM", "").lower() == "fake":  # frontend work without API keys
            from assistant.orchestrator.fake import demo_llm
            _LLM = demo_llm()
        else:
            from assistant.orchestrator.llm import get_llm
            _LLM = get_llm()
    return _LLM


def answer(conversation: Conversation, message: str, selected_field=None, llm=None) -> Reply:
    from assistant.orchestrator import citations, flows, observations, router
    from assistant.orchestrator.llm import LLMError
    from assistant.orchestrator.state import State, history

    state = State(conversation)
    try:
        route = router.route(message, selected_field, state)
        log.info("route=%s reason=%s field=%s threats=%s", route.type, route.reason, route.field_id, route.threats)
        if route.type != "potwierdzenie" and state.draft:
            state.set_draft(None)  # the farmer moved on; an unconfirmed draft is dropped
        conv_id = conversation.pk if conversation is not None else None
        if route.type == "poza_zakresem":
            result = flows.out_of_scope(route, message, [], None)
        elif route.type == "potwierdzenie":
            result = observations.confirmation(route, message, state, conv_id)
        else:
            llm = llm or default_llm()
            hist = history(conversation)
            if route.type == "obserwacja":
                result = observations.observation(route, message, hist, llm, state, selected_field, conv_id)
            else:
                flow = {"pytanie_ogolne": flows.general, "pytanie_o_pole": flows.field_question,
                        "podsumowanie_farmy": flows.farm_summary, "wykres": flows.chart,
                        "zlozone": flows.complex_question}[route.type]
                result = flow(route, message, hist, llm, conv_id)

        allowed = dict(state.seen) | {s["chunk_id"]: s["citation"] for s in result.sources}
        text, guide_cits, unknown = citations.finalize(result.text, allowed)
        state.remember({s["chunk_id"]: s["citation"] for s in result.sources})
        state.save()
        meta = {k: v for k, v in result.meta.items() if k != "prompt"}
        meta |= {"route": route.type, "route_reason": route.reason, "removed_citations": unknown,
                 "sources": [s["chunk_id"] for s in result.sources]}
        if result.chart is not None:
            meta["chart"] = result.chart
        if result.pending_action is not None:
            meta["pending_action"] = result.pending_action
        reply = Reply(text=text, citations=guide_cits + result.risk_citations, focus_field_id=result.focus_field_id,
                      updated_field_ids=result.updated_field_ids, chart=result.chart,
                      pending_action=result.pending_action, meta=meta)
        reply._prompt = result.meta.get("prompt")  # for the CLI only
        return reply
    except LLMError as e:
        log.warning("LLM unavailable: %s", e)
        return Reply(text=f"Nie mogę teraz odpowiedzieć, bo model językowy jest niedostępny. {e}",
                     meta={"error": "llm", "detail": str(e)})
    except Exception as e:  # noqa: BLE001 - never raise into the chat view
        log.exception("answer() failed")
        return Reply(text="Nie mogę teraz odpowiedzieć, bo wystąpił błąd po stronie asystenta. Spróbuj ponownie "
                          "za chwilę albo zadaj pytanie inaczej.", meta={"error": type(e).__name__, "detail": str(e)})
