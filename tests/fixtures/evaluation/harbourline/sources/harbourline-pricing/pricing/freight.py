"""The chargeable weight, and the freight on a lane (REQ-0002)."""

from __future__ import annotations

from pricing.surcharges import surcharges

#: Kilograms charged per cubic metre of cargo: a light, bulky pallet pays for the space it takes.
VOLUMETRIC_KG_PER_M3 = 333

#: The rate per chargeable kilogram, per lane.
RATES = {
    ("PTLIS", "BRSSZ"): 0.42,
    ("PTLIS", "NLRTM"): 0.18,
}


def chargeable_weight(actual_kg: float, volume_m3: float) -> float:
    """The greater of the actual weight and the volumetric weight."""
    return max(actual_kg, volume_m3 * VOLUMETRIC_KG_PER_M3)


def freight(lane: tuple[str, str], actual_kg: float, volume_m3: float) -> dict[str, float]:
    """The price of one quote, line by line: the freight, then every surcharge on it."""
    base = round(chargeable_weight(actual_kg, volume_m3) * RATES[lane], 2)
    return {"freight": base, **surcharges(base)}
