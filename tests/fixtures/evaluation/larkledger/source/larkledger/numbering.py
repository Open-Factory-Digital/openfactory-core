"""The number an invoice gets when it is issued (REQ-0001)."""

from __future__ import annotations

from datetime import date

from larkledger.invoices import Invoice, InvoiceError


def invoice_number(year: int, sequence: int) -> str:
    """`2026-0001`: the year, then the place in that year's sequence."""
    return f"{year}-{sequence:04d}"


def next_number(issued: list[str], today: date) -> str:
    """The next number of this year's sequence. `issued` holds every number the business ever
    gave, cancelled invoices included, so a cancelled number is never handed out again."""
    prefix = f"{today.year}-"
    taken = [int(n.split("-", 1)[1]) for n in issued if n.startswith(prefix)]
    return invoice_number(today.year, max(taken, default=0) + 1)


def issue(invoice: Invoice, issued: list[str], today: date) -> Invoice:
    """A draft gets its number, and its issue date, at the moment it is issued."""
    if invoice.number is not None:
        raise InvoiceError(f"invoice {invoice.number} is already issued")
    invoice.number = next_number(issued, today)
    invoice.issued_on = today
    return invoice
