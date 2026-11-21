import logging

from django.apps import AppConfig
from django.db.models.signals import post_save

log = logging.getLogger(__name__)


def _clock_moved(sender, instance, **kwargs):
    """When the demo date moves, the "days ahead" of rows already written follow it (scores unchanged)."""
    try:
        from engine.compute import refresh_forecast_confidence
        refresh_forecast_confidence(instance.today)
    except Exception:  # never block saving the clock
        log.exception("engine: refreshing forecast confidence after a clock change failed")


class EngineConfig(AppConfig):
    name = "engine"
    verbose_name = "Decision engine"

    def ready(self):
        post_save.connect(_clock_moved, sender="core.Clock", dispatch_uid="engine_clock_moved")
