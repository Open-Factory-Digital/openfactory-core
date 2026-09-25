"""Issuing an invoice for a placed order (REQ-0001)."""

from __future__ import annotations

import os
from dataclasses import dataclass

#: Where the orders service answers; billing reads an order's lines from `GET /orders/{orderId}`.
ORDERS_URL = os.environ.get("ORDERS_URL", "http://orders:8080")


@dataclass
class Invoice:
    order_id: str
    customer_id: str
    lines_total: float
    freight_amount: float

    @property
    def total(self) -> float:
        return round(self.lines_total + self.freight_amount, 2)


def on_order_placed(event: dict, fetch_order) -> Invoice | None:
    """The invoice for the order `event` announces — None when the order was cancelled first.

    `fetch_order(order_id)` is the call to the orders service's HTTP API."""
    order = fetch_order(event["orderId"])
    if order.get("status") == "cancelled":
        return None
    lines_total = sum(line["amount"] for line in order.get("lines", []))
    return Invoice(order_id=order["id"], customer_id=order["customerId"],
                   lines_total=lines_total, freight_amount=order.get("freightAmount", 0.0))
