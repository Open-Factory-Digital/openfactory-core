# REQ-0001 — One freight invoice per consignment

- **Status:** accepted
- **Asked by:** helena
- **Date:** 2020-02-10
- **Supersedes:** —

## Why

Every consignment is billed on its own, so a customer can match each invoice to the shipment it
paid for.

## What must be true

- [ ] a delivered consignment produces exactly one freight invoice
- [ ] the invoice names the consignment it bills

## Out of scope

- grouping several consignments into one invoice

## Affects

- `tidewater/invoices.py`

## Open questions

## Decisions taken during execution

| date | decision | who decided, and where |
|---|---|---|
| 2020-03-02 | an invoice is issued when the consignment is delivered, not when it is picked up | helena — kickoff follow-up |
