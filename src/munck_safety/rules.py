from __future__ import annotations


def should_alert(*, person_in_zone: bool, operation_active: bool, was_in_zone: bool) -> bool:
    """Alert only on zone entry while the operation is active."""
    return person_in_zone and operation_active and not was_in_zone
