---
status: accepted
date: 2026-03-10
---

# Invoice when the order is placed, from the event

## Context

REQ-0001 asks for the invoice the moment the order is placed. Polling orders would invoice late
and load it for nothing.

## Decision

Billing listens to `order.placed`, then asks orders for the order's lines over its HTTP API
(`GET /orders/{orderId}`), and issues the invoice with the freight fixed on the order.
