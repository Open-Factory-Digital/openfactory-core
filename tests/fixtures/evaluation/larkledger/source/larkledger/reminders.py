"""Which reminder, if any, an unpaid invoice is due today (REQ-0002)."""

from __future__ import annotations

from datetime import date

from larkledger.invoices import Invoice

FIRST_REMINDER_DAYS = 7
SECOND_REMINDER_DAYS = 21

#: The hour, in the business's own time zone, at which reminders are sent.
SEND_AT_HOUR = 9


def reminder_due(invoice: Invoice, today: date) -> str | None:
    """`first`, `second` or `owner` — or None when nothing is due today.

    `owner` means the business owner is told; the customer hears nothing more from the product."""
    due = invoice.due_on()
    if due is None or invoice.cancelled or invoice.outstanding() == 0:
        return None
    late = (today - due).days
    if late == FIRST_REMINDER_DAYS:
        return "first"
    if late == SECOND_REMINDER_DAYS:
        return "second"
    if late == SECOND_REMINDER_DAYS + 1:
        return "owner"
    return None
