"""python manage.py sim_farm [--simulated] [--wipe] [--no-engine]

Demo farm for demos and chat testing: 6 fields near Krapkowice (Opolskie), farmer reports in
core.Observation, Clock = 2025-06-10, then the real decision engine computes the risks
(engine_load_threats + predict, previous season first).

Default: the organisers' REAL data (assistant/realfarm.py): real parcels and crop history from the
crop maps, real weather 2023-2025 with IMERG rain, real soil. Needs the files in DATA_DIR.
--simulated: the old simulated weather/soil/history (assistant/simfarm.py), no data files needed.
"""
from datetime import date
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from assistant import devdata, realfarm, simfarm


def devdata_names() -> list[str]:
    """Fields of the toy dev seed (assistant_dev_seed), which this command replaces."""
    return [f[0] for f in devdata.DEV_FIELDS]


class Command(BaseCommand):
    help = "Build the demo farm (real data by default) and run the decision engine on it."

    def add_arguments(self, parser):
        parser.add_argument("--simulated", action="store_true", help="simulated weather/soil/history instead of real data")
        parser.add_argument("--wipe", action="store_true", help="only delete the demo farm")
        parser.add_argument("--no-engine", action="store_true", help="do not run engine_load_threats/predict")
        parser.add_argument("--force", action="store_true",
                            help="run even if the database holds other fields (e.g. a scenario): their same-named fields go")

    def handle(self, *args, **o):
        t0 = time.time()
        from core.models import Field
        own = set(realfarm.NAMES) | {f.name for f in simfarm.FIELDS} | set(devdata_names())
        others = list(Field.objects.exclude(name__in=own).values_list("name", flat=True)[:5])
        if others and not o["force"]:
            # the sim farm deletes fields by name ("Długie", "Pod Lasem", "Za Stodołą" are demo_2024 fields too),
            # recomputes every field and moves the Clock: never on top of a scenario by accident
            raise CommandError(f"The database holds other fields ({', '.join(others)}, …), probably a scenario. "
                               "sim_farm would delete same-named fields and move the date. Switch scenarios with "
                               "`python manage.py scenario switch <slug>`, or pass --force.")
        if o["wipe"]:
            self.stdout.write(f"Deleted {realfarm.wipe()} demo-farm rows.")
            return
        n = devdata.wipe()
        if n:
            self.stdout.write(f"Removed the old toy dev seed ({n} rows).")
        farm = simfarm if o["simulated"] else realfarm
        if farm is realfarm:
            missing = realfarm.check_files()
            if missing:
                raise CommandError("Brak plików z danymi (DATA_DIR):\n  " + "\n  ".join(missing)
                                   + "\nPobierz je albo uruchom: python manage.py sim_farm --simulated")
        else:
            realfarm.wipe()
        farm.build(log=self.stdout.write)
        if o["no_engine"]:
            return
        call_command("engine_load_threats")
        farm.add_observations(log=self.stdout.write)
        from engine import predict
        n1 = predict(start=date(2024, 1, 15), end=date(2024, 8, 31))
        n2 = predict(start=date(2024, 9, 1), end=date(2025, 10, 31))
        self.stdout.write(self.style.SUCCESS(
            f"Engine wrote {int(n1)} risks (season 2024) + {int(n2)} (season 2025). Today = {farm.TODAY}. "
            f"Data: {'simulated' if farm is simfarm else 'real (organisers)'}. Done in {time.time() - t0:.0f}s."))
