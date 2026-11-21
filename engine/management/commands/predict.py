"""python manage.py predict [--fields 1 2] [--start 2025-03-01] [--end 2025-06-30]"""

from datetime import date

from django.core.management.base import BaseCommand

from engine import predict


class Command(BaseCommand):
    help = "Compute risks (default: all fields, the current season up to today + 7) and overwrite them in Risk."

    def add_arguments(self, parser):
        parser.add_argument("--fields", type=int, nargs="*", help="Field ids (default: all).")
        parser.add_argument("--start", type=date.fromisoformat, help="First day (default: 1 September of the season).")
        parser.add_argument("--end", type=date.fromisoformat, help="Last day (default: today + 7).")

    def handle(self, *args, fields=None, start=None, end=None, **opts):
        n = predict(field_ids=fields, start=start, end=end)
        self.stdout.write(self.style.SUCCESS(f"{n} risk rows written."))
