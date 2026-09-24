# REQ-0003 — A customer can pay part of an invoice

- **Status:** proposed
- **Asked by:** marta
- **Date:** 2026-05-11
- **Supersedes:** —

## Why

Larger customers pay in instalments. Today the owner marks such an invoice as paid when the first
instalment arrives, and loses track of what is still owed.

## What must be true

- [ ] a payment smaller than the amount due is recorded against the invoice
- [ ] the invoice shows the balance still due
- [ ] a reminder about a partly paid invoice asks for the balance, not the original amount

## Out of scope

- payment plans agreed in advance

## Affects

- `larkledger/invoices.py`
- `larkledger/reminders.py`

## Open questions

- does a partial payment start the reminder schedule again?

## Decisions taken during execution

| date | decision | who decided, and where |
|---|---|---|
