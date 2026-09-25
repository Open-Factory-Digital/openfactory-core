# REQ-0002 — Every customer has an account

- **Status:** accepted
- **Asked by:** helena
- **Date:** 2020-02-10
- **Supersedes:** —

## Why

Invoices, payments and reminders all hang off the customer they are for.

## What must be true

- [ ] a consignment is booked against a customer account
- [ ] an account holds the customer's billing address and payment term

## Out of scope

- customer self-service

## Affects

- `tidewater/accounts.py`

## Open questions

## Decisions taken during execution

| date | decision | who decided, and where |
|---|---|---|
| 2020-02-24 | an account is created by the billing team, never by the customer | helena — kickoff follow-up |
