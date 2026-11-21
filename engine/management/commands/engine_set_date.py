"""python manage.py engine_set_date 2025-06-20

Moves the demo date and recomputes the days that change (engine.clock_moved). For scripts and the
terminal; the platform's PUT /api/clock/ and the admin's clock page call engine.clock_moved themselves.
"""

from datetime import date

from django.core.management.base import BaseCommand

from core.models import Clock
from engine import clock_moved


class Command(BaseCommand):
    help = "Set the demo date (Clock) and recompute the risks of the days that change."

    def add_arguments(self, parser):
        parser.add_argument("date", type=date.fromisoformat)

    def handle(self, *args, date=None, **opts):
        c = Clock.objects.get(pk=1)
        old = c.today
        c.today = date
        c.save()
        n = clock_moved(old, date)
        self.stdout.write(self.style.SUCCESS(f"Clock {old} -> {date}: {int(n)} risk rows recomputed."))
