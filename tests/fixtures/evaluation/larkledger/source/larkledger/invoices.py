"""An invoice, its lines, its total and its due date."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

#: The payment term a customer gets when the business chose none for them.
DEFAULT_PAYMENT_TERM_DAYS = 30

#: The only terms a business can choose for a customer.
PAYMENT_TERMS_DAYS = (15, 30, 60)

#: One invoice holds at most this many lines; a longer order is split into two invoices.
MAX_LINES = 50


class InvoiceError(ValueError):
    """An invoice that cannot be built as asked."""


@dataclass(frozen=True)
class Line:
    description: str
    quantity: Decimal
    unit_price: Decimal

    def amount(self) -> Decimal:
        """Each line is rounded to the cent on its own, before the lines are added up."""
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"), ROUND_HALF_UP)


@dataclass
class Invoice:
    customer: str
    currency: str
    issued_on: date | None = None
    number: str | None = None
    term_days: int = DEFAULT_PAYMENT_TERM_DAYS
    lines: list[Line] = field(default_factory=list)
    paid: Decimal = Decimal("0")
    cancelled: bool = False

    def add(self, line: Line) -> None:
        if len(self.lines) >= MAX_LINES:
            raise InvoiceError(f"an invoice holds at most {MAX_LINES} lines")
        self.lines.append(line)

    def total(self) -> Decimal:
        return sum((line.amount() for line in self.lines), Decimal("0"))

    def due_on(self) -> date | None:
        """The issue date plus the customer's payment term; a draft has no due date."""
        if self.issued_on is None:
            return None
        return self.issued_on + timedelta(days=self.term_days)

    def outstanding(self) -> Decimal:
        return max(self.total() - self.paid, Decimal("0"))


def set_term(invoice: Invoice, days: int) -> None:
    if days not in PAYMENT_TERMS_DAYS:
        raise InvoiceError(f"a payment term is one of {PAYMENT_TERMS_DAYS} days")
    invoice.term_days = days
