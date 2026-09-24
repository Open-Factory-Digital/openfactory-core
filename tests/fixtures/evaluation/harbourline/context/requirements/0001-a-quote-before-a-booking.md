# REQ-0001 — A shipper books only against a quote they accepted

- **Status:** accepted
- **Asked by:** ines
- **Date:** 2026-04-06
- **Supersedes:** —

## Why

A shipper who books without a quote is surprised by the invoice, and the line's agents spend the
week after a sailing explaining prices. A booking has to rest on a price the shipper saw and said
yes to.

## What must be true

- [ ] a booking is refused unless it names a quote the shipper accepted
- [ ] a quote is valid for 48 hours from the moment it was issued
- [ ] a booking against an expired quote is refused, and the shipper is asked to quote again

## Out of scope

- negotiated contract rates for the line's largest shippers

## Affects

- `harbourline/bookings.py`
- `harbourline-web/src/booking.ts`

## Decisions taken during execution

| date | decision | who decided, and where |
|---|---|---|
| 2026-04-10 | the 48 hours count from the quote's issue, not from the shipper's acceptance | ines, #7 |
