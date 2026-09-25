# REQ-0001 — Invoice numbers never repeat and never skip

- **Status:** accepted
- **Asked by:** marta
- **Date:** 2026-03-02
- **Supersedes:** —

## Why

The business's accountant reconciles invoices by their number, and the tax office asks about any
gap in the sequence. A number that is reused, or one that is missing, costs the owner an afternoon
of explaining.

## What must be true

- [ ] every invoice a business issues gets the next number of that business's own sequence
- [ ] a number is never reused, not even when an invoice is cancelled
- [ ] a cancelled invoice stays in the list, marked as cancelled, with its number

## Out of scope

- importing invoice numbers from another invoicing system

## Affects

- `larkledger/numbering.py`

## Decisions taken during execution

| date | decision | who decided, and where |
|---|---|---|
| 2026-03-09 | the sequence starts again at 1 every calendar year, and the number carries the year: 2026-0001 | marta, with the accountant, in the kickoff call |
| 2026-03-16 | a draft invoice has no number; it gets one at the moment it is issued | marta, #12 |
