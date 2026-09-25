---
description: An order announced on `order.placed` is invoiced with its lines and the
  freight fixed on it, unless it was cancelled first.
generated:
  at: '2026-09-24T00:00:00Z'
  by: machine:fixture
sources:
- commit: fixture
  fingerprint: 02997758560bd3d643822fe72cdb5cfabf44f68bacfb5698e4a8e001247cb772
  lines: 24-33
  path: billing/invoicing.py
  repo: quayside-billing
status: draft
title: Invoicing a placed order
type: workflow
---

# Invoicing a placed order

## What it does

`on_order_placed` reads the order from the orders service's HTTP API and issues an invoice of its lines' total and the freight amount on the order.

## Business rules

- an order cancelled before it is invoiced is never invoiced (`billing/invoicing.py:29`)
- the invoice carries the freight amount fixed on the order (`billing/invoicing.py:33`)
- an invoice's total is its lines' total plus its freight, rounded to cents (`billing/invoicing.py:21`)

## Depends on

- quayside-orders — `GET /orders/{orderId}` for the order's lines, and the `order.placed` event
