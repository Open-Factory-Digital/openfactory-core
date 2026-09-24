"""What is added to the freight, each on its own line."""

from __future__ import annotations

#: The fuel surcharge, as a share of the freight.
FUEL = 0.12


def surcharges(freight: float) -> dict[str, float]:
    """Every surcharge on `freight`, named."""
    return {"fuel": round(freight * FUEL, 2)}
