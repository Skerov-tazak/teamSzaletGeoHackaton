"""
The demo's current date. The demo replays a past season, so never use date.today():

    from core import clock
    today = clock.today()
"""

from datetime import date

# How many days ahead the forecast (and the "coming days" risks) reach.
FORECAST_DAYS = 7


class ClockNotSetError(RuntimeError):
    """The Clock row is missing: set the demo date in /admin/ or run the seed."""


def today() -> date:
    """The demo's current date, from the single Clock row. Raises ClockNotSetError if it is missing."""
    from core.models import Clock  # imported here: core.models imports this module

    try:
        return Clock.objects.values_list("today", flat=True).get(pk=1)
    except Clock.DoesNotExist:
        raise ClockNotSetError(
            "The Clock row is missing. Set the demo date in /admin/ (Platform > Clock) or run the seed."
        ) from None
