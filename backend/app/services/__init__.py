"""Service layer.

Deliberately empty of eager imports. The previous version pulled sync -> yclients
-> cache -> services/__init__ back into itself, so importing anything from
app.services dragged in SQLAlchemy, the AI client and a circular reference.
Import the concrete module you need instead:

    from app.services.slots import compute_free_slots
    from app.services.sync import sync_all
"""
