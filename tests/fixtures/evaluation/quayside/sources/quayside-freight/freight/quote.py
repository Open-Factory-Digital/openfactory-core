"""The freight calculation: weight times the rate of the port pair, with a minimum charge."""

from __future__ import annotations

#: Price per kilogram between two ports, in the invoice's currency.
RATES_PER_KG: dict[tuple[str, str], float] = {
    ("PTLIS", "NLRTM"): 0.42,
    ("PTLIS", "ESALG"): 0.18,
    ("NLRTM", "PTLIS"): 0.45,
}
#: No shipment is quoted below this, whatever it weighs.
MINIMUM_CHARGE = 35.0


def quote(origin_port: str, destination_port: str, weight_kg: float) -> float:
    """The freight for `weight_kg` from `origin_port` to `destination_port`.

    Raises `KeyError` for a port pair Quayside does not serve."""
    rate = RATES_PER_KG[(origin_port, destination_port)]
    return round(max(MINIMUM_CHARGE, weight_kg * rate), 2)
