---
description: The freight of an order is quoted by the freight service and fixed on
  it, then the order is announced on `order.placed`.
generated:
  at: '2026-09-24T00:00:00Z'
  by: machine:fixture
sources:
- commit: fixture
  fingerprint: 02adbf6ca3f72602530f292cf3839a85d20a1e52e749f413a73a0442c45e3983
  lines: 33-39
  path: orders/placing.py
  repo: quayside-orders
status: draft
title: Placing an order
type: workflow
---

# Placing an order

## What it does

`place` asks the freight service for a quote, fixes the quote's id and amount on the order, and publishes the order's id and quote id on `order.placed`.

## Business rules

- the freight quoted is fixed on the order before it is announced (`orders/placing.py:37`)
- the announcement carries the order's id and its freight quote's id (`orders/placing.py:38`)

## Depends on

- quayside-freight — the quote, `FreightQuotes.QuoteShipment` over gRPC

## Consumed by

- quayside-billing — invoices the order `order.placed` announces
