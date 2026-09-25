# REQ-0003 — An invoice is due thirty days after it is issued

- **Status:** accepted
- **Asked by:** helena
- **Date:** 2020-06-01
- **Supersedes:** —

## Why

Customers asked for one rule they could plan their payments by.

## What must be true

- [ ] the due date is the issue date plus the account's payment term
- [ ] the payment term is thirty days unless the account says otherwise

## Out of scope

- early-payment discounts

## Affects

- `tidewater/invoices.py`

## Open questions

## Decisions taken during execution

| date | decision | who decided, and where |
|---|---|---|
