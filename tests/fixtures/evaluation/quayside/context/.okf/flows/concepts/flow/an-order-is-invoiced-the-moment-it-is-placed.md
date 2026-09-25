---
description: REQ-0001 across `quayside-orders`, `quayside-billing`, `quayside-freight`
generated:
  at: '2026-09-24T00:00:00Z'
  by: machine:knowledge-flows
sources:
- commit: fixture
  fingerprint: 02adbf6ca3f72602530f292cf3839a85d20a1e52e749f413a73a0442c45e3983
  lines: 33-39
  path: orders/placing.py
  repo: quayside-orders
- commit: fixture
  fingerprint: 02997758560bd3d643822fe72cdb5cfabf44f68bacfb5698e4a8e001247cb772
  lines: 24-33
  path: billing/invoicing.py
  repo: quayside-billing
- commit: fixture
  fingerprint: 6522f27e7bdcf21f5e588a1effdb5315b7f31935e4c81a83514811d08897359a
  lines: 15-20
  path: freight/quote.py
  repo: quayside-freight
status: draft
title: An order is invoiced the moment it is placed
type: flow
---

# An order is invoiced the moment it is placed

## What it does

The flow REQ-0001 names, as the code carries it across 3 repositories: billing, freight, orders. Open each part's concept for what it does, and its code to confirm.

## Behaviour

- billing → orders over http (env ORDERS_URL) — `quayside-platform` `docker-compose.yml:17`
- orders → billing over event (channel order.placed) — `quayside-orders` `api/asyncapi.yaml`; `quayside-billing` `asyncapi.yaml`
- orders → freight over grpc (env FREIGHT_ADDR) — `quayside-platform` `docker-compose.yml:4`; `quayside-platform` `k8s/orders.yaml:1`

## Depends on

- `quayside-billing` — Invoicing a placed order (`.okf/repos/quayside-billing/concepts/workflow/invoicing-a-placed-order.md`)
- `quayside-freight` — The freight calculation (`.okf/repos/quayside-freight/concepts/policy/the-freight-calculation.md`)
- `quayside-orders` — Placing an order (`.okf/repos/quayside-orders/concepts/workflow/placing-an-order.md`)
