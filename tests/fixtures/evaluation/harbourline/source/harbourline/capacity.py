"""How many kilograms a sailing has left."""

from __future__ import annotations

from dataclasses import dataclass


class SailingFull(Exception):
    """The sailing has no room for this cargo."""


@dataclass
class Sailing:
    id: str
    capacity_kg: float
    booked_kg: float = 0.0

    @property
    def left_kg(self) -> float:
        return self.capacity_kg - self.booked_kg


def reserve(sailing: Sailing, kilograms: float) -> None:
    """Take `kilograms` of the sailing's capacity, or refuse when it would overflow."""
    if kilograms > sailing.left_kg:
        raise SailingFull(f"{sailing.id} has {sailing.left_kg:.0f} kg left")
    sailing.booked_kg += kilograms
