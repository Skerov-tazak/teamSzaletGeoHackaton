# Decision engine

**Owner:** Bartek

Turns each field's data into risk assessments per threat and day, each with an explanation of why. It may combine rules from the guides, ML models and agents.

## Talking to the rest of the system

- Reads and writes the database only through the Django ORM, using the models in [`core/models.py`](../core/models.py). This app has no models or migrations of its own; ask Jan or Szymek for schema changes.
- *To be defined in the interfaces step:* which tables the engine reads and writes, the risk scale and explanation format, and how the engine is triggered (season backfill, and reassessment after a farmer's observation).
