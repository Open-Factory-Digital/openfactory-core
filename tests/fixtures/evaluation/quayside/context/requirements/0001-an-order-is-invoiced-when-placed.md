# REQ-0001 — An order is invoiced the moment it is placed

- **Status:** accepted
- **Asked by:** ines
- **Date:** 2026-05-04
- **Supersedes:** —

## Why

Quayside's customers pay before a shipment leaves the quay. An order that waits for somebody to
invoice it by hand waits on the quay too.

## What must be true

- [ ] placing an order produces its invoice without anybody acting on it
- [ ] the invoice carries every line of the order, and the freight quoted for it
- [ ] an order cancelled before it is invoiced is never invoiced

## Out of scope

- partial invoices
- invoicing in more than one currency

## Affects

- `quayside-orders`, `quayside-billing`, `quayside-freight`
