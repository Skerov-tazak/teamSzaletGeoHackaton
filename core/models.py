"""
Every table of the platform lives here: farms, fields, weather, soil, threats, risks, observations.

Owned by Szymek + Janek. Other components (engine, assistant) import these models and own no
migrations of their own; if you need a new table or column, ask us.
"""

from django.db import models  # noqa: F401  (models are added once the database doc is agreed)
