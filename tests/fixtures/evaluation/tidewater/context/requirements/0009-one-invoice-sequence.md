# REQ-0009 — Invoice numbers follow one continuous sequence

- **Status:** accepted
- **Asked by:** helena
- **Date:** 2023-03-12
- **Supersedes:** 0004

## Why

Restarting the numbers every January produced duplicate-looking numbers across years, and the new
tax authority rules ask for one unbroken sequence per issuer.

## What must be true

- [ ] invoice numbers never restart: each is the previous one plus one
- [ ] numbers carry no year prefix; the sequence continues from the last number of 2022

## Out of scope

- renumbering invoices already issued

## Affects

- `tidewater/numbering.py`

## Open questions

## Decisions taken during execution

| date | decision | who decided, and where |
|---|---|---|
| 2023-03-12 | the yearly restart is abandoned: numbering continues from the last 2022 number, with no year prefix | helena — billing review |
