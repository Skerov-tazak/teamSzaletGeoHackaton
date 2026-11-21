"""
python manage.py engine_load_threats

Upserts the Threat rows the engine has rules for (engine/catalog.py), by code. Safe to run on top of
the platform's own Threat fixture: existing rows with the same code are updated, others are untouched.
Needs the CropClass rows 1110 (Wheat) and 1130 (Maize).
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import CropClass, Threat
from engine.catalog import RULES


class Command(BaseCommand):
    help = "Create / update the Threat rows for every rule in engine/catalog.py."

    @transaction.atomic
    def handle(self, *args, **opts):
        for code, name in ((1110, "Wheat"), (1130, "Maize")):
            CropClass.objects.get_or_create(code=code, defaults={"name": name})
        n = 0
        for rule in RULES.values():
            temp_text = f"{rule.temp_min:g}-{rule.temp_max:g}" if rule.temp_min is not None else ""
            Threat.objects.update_or_create(code=rule.code, defaults={
                "crop_id": rule.crop, "name": rule.name_pl, "category": rule.category,
                "temperature_text": temp_text, "temp_min_c": rule.temp_min, "temp_max_c": rule.temp_max,
                "humidity_text": "", "other_factors": " ".join(rule.notes),
                "growth_stage_text": f"BBCH {rule.stage_min}-{rule.stage_max}",
                "source": "engine rules",
            })
            n += 1
        self.stdout.write(self.style.SUCCESS(f"{n} threats upserted."))
