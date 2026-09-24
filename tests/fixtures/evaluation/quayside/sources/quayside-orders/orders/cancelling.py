"""Cancelling an order before it leaves the quay, and announcing it.

No concept of the knowledge bundle describes this file: the backfill's budget stopped at placing.
"""

from __future__ import annotations

#: The topic a cancellation is announced on.
ORDER_CANCELLED = "order.cancelled"
#: The states an order can still be cancelled from.
CANCELLABLE = frozenset({"placed"})


def cancel(order, publish):
    """Cancel `order` when it has not left the quay, and `publish` it on `ORDER_CANCELLED`.

    Returns the order; one that has already left is returned unchanged and nothing is announced."""
    if order.status not in CANCELLABLE:
        return order
    order.status = "cancelled"
    publish(ORDER_CANCELLED, {"orderId": order.id})
    return order
