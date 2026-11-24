"""Backend-neutral availability math shared by MongoDB and PostgreSQL."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RecipeLine:
    ingredient_id: str
    ingredient_name: str
    qty_per_portion: float
    available: float | None


def compute_min_portions(
    lines: list[RecipeLine],
) -> tuple[int, str | None, str | None]:
    """Return (max_portions, limiting_ingredient_id, limiting_ingredient_name).

    Lines are processed in ingredient_id order so ties resolve identically on
    both backends. Negative stock is clamped to zero before flooring.
    """
    if not lines:
        return 0, None, None

    min_portions: int | None = None
    limit_id: str | None = None
    limit_name: str | None = None

    for line in sorted(lines, key=lambda item: item.ingredient_id):
        if line.qty_per_portion <= 0:
            return 0, line.ingredient_id, line.ingredient_name
        available = max(0.0, line.available if line.available is not None else 0.0)
        portions = math.floor(available / line.qty_per_portion)
        if min_portions is None or portions < min_portions:
            min_portions = portions
            limit_id = line.ingredient_id
            limit_name = line.ingredient_name

    return min_portions if min_portions is not None else 0, limit_id, limit_name


__all__ = ["RecipeLine", "compute_min_portions"]
