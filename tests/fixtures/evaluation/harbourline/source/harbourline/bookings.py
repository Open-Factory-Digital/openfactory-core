"""A booking, and the quote it must rest on (REQ-0001)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from harbourline.capacity import Sailing, reserve

#: How long a quote may be booked against, counted from the moment it was issued.
QUOTE_VALID_FOR = timedelta(hours=48)


class BookingRefused(Exception):
    """A booking the rules do not allow, with the sentence the shipper is shown."""


@dataclass
class Quote:
    id: str
    shipper: str
    issued_at: datetime
    accepted: bool
    kilograms: float


@dataclass
class Booking:
    quote_id: str
    shipper: str
    sailing: str
    kilograms: float


def book(quote: Quote, sailing: Sailing, now: datetime) -> Booking:
    """A booking against an accepted, unexpired quote, on a sailing with room for it."""
    if not quote.accepted:
        raise BookingRefused("accept the quote before booking")
    if now - quote.issued_at > QUOTE_VALID_FOR:
        raise BookingRefused("this quote has expired — ask for a new one")
    reserve(sailing, quote.kilograms)
    return Booking(quote_id=quote.id, shipper=quote.shipper, sailing=sailing.id,
                   kilograms=quote.kilograms)
