"""The events a sailing emits, by name — what the booking service listens for."""

from __future__ import annotations

DEPARTED = "sailing.departed"
DELAYED = "sailing.delayed"
ARRIVED = "sailing.arrived"

ALL = (DEPARTED, DELAYED, ARRIVED)
