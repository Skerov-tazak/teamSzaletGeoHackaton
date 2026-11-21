"""python manage.py sim_farm [--wipe] [--no-engine]

Realistic SIMULATED farm for demos and chat testing (assistant/simfarm.py): 6 fields near
Krapkowice, simulated weather 2023-07 … 2025-10, crop history, soil, farmer observations, Clock =
2025-06-10. Then the real decision engine computes the risks (engine_load_threats + predict,
previous season first). Replaces the assistant's toy dev seed and is replaced by the platform import.
"""
from datetime import date
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand

from assistant import devdata, simfarm


class Command(BaseCommand):
    help = "Build the simulated demo farm and run the decision engine on it."

    def add_arguments(self, parser):
        parser.add_argument("--wipe", action="store_true", help="only delete the simulated farm")
        parser.add_argument("--no-engine", action="store_true", help="do not run engine_load_threats/predict")

    def handle(self, *args, **o):
        t0 = time.time()
        if o["wipe"]:
            self.stdout.write(f"Deleted {simfarm.wipe()} simulated rows.")
            return
        n = devdata.wipe()
        if n:
            self.stdout.write(f"Removed the old toy dev seed ({n} rows).")
        simfarm.build(log=self.stdout.write)
        if o["no_engine"]:
            return
        call_command("engine_load_threats")
        simfarm.add_observations(log=self.stdout.write)
        from engine import predict
        n1 = predict(start=date(2024, 1, 15), end=date(2024, 8, 31))
        n2 = predict(start=date(2024, 9, 1), end=date(2025, 10, 31))
        self.stdout.write(self.style.SUCCESS(
            f"Engine wrote {n1} risks (season 2024) + {n2} (season 2025). Today = {simfarm.TODAY}. "
            f"Done in {time.time() - t0:.0f}s."))
