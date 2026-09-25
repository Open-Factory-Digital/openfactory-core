# REQ-0004 — Invoice numbers restart every year

- **Status:** superseded-by 0009
- **Asked by:** helena
- **Date:** 2021-03-15
- **Supersedes:** —

## Why

The accountant wanted one invoice sequence per fiscal year, with the year readable in the number.

## What must be true

- [ ] invoice numbers restart at 1 on the first of January
- [ ] every number carries the year as a prefix: TW-2021-0001

## Out of scope

- a sequence per customer

## Affects

- `tidewater/numbering.py`

## Open questions

## Decisions taken during execution

| date | decision | who decided, and where |
|---|---|---|
| 2021-03-15 | invoice numbers restart on the first of January, with the year as a prefix | helena — operations call |
