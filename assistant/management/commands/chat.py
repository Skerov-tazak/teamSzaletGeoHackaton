"""python manage.py chat "pytanie" [--field ID|nazwa] [--conversation ID] [--live] [--show-prompt] [--chart-out plik.json]

Talk to the assistant from the terminal. Default: FakeLLM (no API calls); --live uses the LLM
configured in .env. Messages are saved like the chat endpoint does, so a follow-up ("tak") can
continue with --conversation <id>.
"""
import json
import logging

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Ask the assistant a question (FakeLLM by default, --live for the real model)."

    def add_arguments(self, parser):
        parser.add_argument("message")
        parser.add_argument("--field", help="selected field: id or name")
        parser.add_argument("--conversation", type=int, help="continue this conversation id")
        parser.add_argument("--live", action="store_true", help="use the real LLM from .env")
        parser.add_argument("--show-prompt", action="store_true")
        parser.add_argument("--chart-out", help="write the chart spec (Vega-Lite) to this file")

    def handle(self, *args, **o):
        logging.basicConfig(level=logging.WARNING)
        logging.getLogger("assistant").setLevel(logging.INFO)
        from core.models import Field

        from assistant.answer import answer
        from assistant.models import Conversation, Message
        from assistant.orchestrator.fake import demo_llm
        from assistant.orchestrator.llm import get_llm

        field = None
        if o["field"]:
            field = (Field.objects.filter(pk=int(o["field"])).first() if o["field"].isdigit()
                     else Field.objects.filter(name__iexact=o["field"]).first())
            if field is None:
                raise CommandError(f"Nie ma pola „{o['field']}”. Pola: {list(Field.objects.values_list('id', 'name'))}")
        if o["conversation"]:
            conv = Conversation.objects.filter(pk=o["conversation"]).first()
            if conv is None:
                raise CommandError(f"Nie ma rozmowy {o['conversation']}")
        else:
            conv = Conversation.objects.create(title=Conversation.title_from(o["message"]))
        Message.objects.create(conversation=conv, role=Message.Role.USER, text=o["message"], field=field)
        llm = get_llm() if o["live"] else demo_llm()

        reply = answer(conv, o["message"], field, llm=llm)

        Message.objects.create(conversation=conv, role=Message.Role.ASSISTANT, text=reply.text,
                               citations=reply.citations, meta=reply.meta,
                               focus_field_id=reply.focus_field_id)
        w = self.stdout.write
        if o["show_prompt"] and getattr(reply, "_prompt", None):
            for m in reply._prompt:
                w(self.style.MIGRATE_HEADING(f"--- {m['role']} ---"))
                w(m["content"])
        meta = reply.meta
        w(self.style.MIGRATE_HEADING(f"\n=== route: {meta.get('route')} ({meta.get('route_reason')}) · rozmowa {conv.pk}"))
        for c in meta.get("llm_calls", []):
            w(f"LLM: {c['provider']}/{c['model']} in={c['prompt_tokens']} out={c['completion_tokens']} "
              f"{'(szac.)' if c.get('estimated') else ''} {c['duration_ms']} ms [{c['kind']}]")
        if "prompt_info" in meta:
            pi = meta["prompt_info"]
            w(f"prompt ≈ {pi['estimated_input_tokens']} tok.; źródła: {pi['sources']}; pominięte: {pi['dropped_sources']}")
        if meta.get("removed_citations"):
            w(self.style.WARNING(f"usunięte nieznane cytaty: {meta['removed_citations']}"))
        w(self.style.SUCCESS("\n" + reply.text + "\n"))
        for c in reply.citations:
            w(f"  cytat: {json.dumps(c, ensure_ascii=False)}")
        if reply.focus_field_id or reply.updated_field_ids:
            w(f"  focus_field_id={reply.focus_field_id} updated_field_ids={reply.updated_field_ids}")
        if reply.chart is not None:
            w(f"  wykres: {reply.chart.get('title', {}).get('text')} ({len(reply.chart.get('data', {}).get('values', []))} punktów)")
            if o["chart_out"]:
                with open(o["chart_out"], "w") as f:
                    json.dump(reply.chart, f, ensure_ascii=False, indent=1)
                w(f"  zapisano: {o['chart_out']}")
        if reply.pending_action:
            w(f"  oczekuje: {reply.pending_action['type']} → odpowiedz: manage.py chat \"tak\" --conversation {conv.pk}")
