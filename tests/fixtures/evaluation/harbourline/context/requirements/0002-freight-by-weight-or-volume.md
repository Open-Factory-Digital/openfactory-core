# REQ-0002 — Freight is charged on the greater of weight and volume

- **Status:** accepted
- **Asked by:** ines
- **Date:** 2026-04-06
- **Supersedes:** —

## Why

A pallet of foam weighs little and fills a container. Charging on weight alone lets light, bulky
cargo sail almost free, and the line pays for the space it takes.

## What must be true

- [ ] the chargeable weight is the greater of the actual weight and the volumetric weight
- [ ] the volumetric weight is the volume in cubic metres times 333 kg
- [ ] the price is the chargeable weight times the lane's rate per kilogram, plus the surcharges

## Out of scope

- dangerous goods, which are priced by hand

## Affects

- `harbourline-pricing/pricing/freight.py`
- `harbourline-pricing/pricing/surcharges.py`

## Decisions taken during execution

| date | decision | who decided, and where |
|---|---|---|
| 2026-04-14 | the fuel surcharge is 12% of the freight, and it is shown on its own line | ines, with finance, #9 |
