# REQ-0002 — An unpaid invoice is chased twice, then handed to the owner

- **Status:** accepted
- **Asked by:** marta
- **Date:** 2026-04-06
- **Supersedes:** —

## Why

Customers forget to pay. The owner does not want to write reminder emails by hand, and does not
want a customer chased by a machine for ever either: after two reminders it is a conversation
between people.

## What must be true

- [ ] a customer whose invoice is still unpaid 7 days after its due date receives a first reminder
  by email
- [ ] if the invoice is still unpaid 21 days after its due date, a second and last reminder is sent
- [ ] after the second reminder the owner of the business is told, and no further reminder is sent
  automatically
- [ ] an invoice paid in full, or cancelled, receives no reminder

## Out of scope

- charging late fees
- reminders by text message

## Affects

- `larkledger/reminders.py`

## Decisions taken during execution

| date | decision | who decided, and where |
|---|---|---|
| 2026-04-20 | reminders go out at 09:00 in the business's own time zone, never at night | marta, #27 |
