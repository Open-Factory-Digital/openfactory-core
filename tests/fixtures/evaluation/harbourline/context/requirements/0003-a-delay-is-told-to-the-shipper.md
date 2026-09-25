# REQ-0003 — A shipper is told when their cargo will arrive late

- **Status:** accepted
- **Asked by:** tomas
- **Date:** 2026-05-02
- **Supersedes:** —

## Why

Shippers plan trucks and warehouse staff around the arrival. Finding out at the port that a
sailing is a day late costs them a wasted trip.

## What must be true

- [ ] when a sailing's expected arrival moves later by more than 6 hours, every shipper booked on
      it is told
- [ ] the message says the new expected arrival
- [ ] a shipper is not told twice about the same delay

## Out of scope

- telling the consignee, who is the shipper's own customer

## Affects

- `harbourline-tracking/tracking/eta.py`
- `harbourline-tracking/tracking/events.py`
