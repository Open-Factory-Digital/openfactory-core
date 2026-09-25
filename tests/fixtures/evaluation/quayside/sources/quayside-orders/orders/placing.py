"""Placing an order: its freight is quoted, fixed on it, and the order is announced (REQ-0001)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

#: Where the freight service answers — `FreightQuotes.QuoteShipment` over gRPC.
FREIGHT_ADDR = os.environ.get("FREIGHT_ADDR", "freight:50051")
#: The topic an order is announced on.
ORDER_PLACED = "order.placed"


@dataclass
class Line:
    sku: str
    quantity: int
    weight_kg: float


@dataclass
class Order:
    id: str
    customer_id: str
    origin_port: str
    destination_port: str
    lines: list[Line] = field(default_factory=list)
    freight_quote_id: str = ""
    freight_amount: float = 0.0
    status: str = "placed"


def place(order: Order, quote, publish) -> Order:
    """Fix the freight `quote(order)` returns on the order, then `publish` it on `ORDER_PLACED`.

    `quote` returns `(quote id, amount)`; the amount is what the invoice will carry."""
    order.freight_quote_id, order.freight_amount = quote(order)
    publish(ORDER_PLACED, {"orderId": order.id, "freightQuoteId": order.freight_quote_id})
    return order
