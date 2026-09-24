# 2. Order events go over Kafka

- **Status:** Accepted
- **Date:** 2026-03-09

## Context

Billing must invoice an order the moment it is placed (REQ-0001), without orders knowing billing
exists.

## Decision

Orders sends `order.placed` and `order.cancelled` to Kafka. Whoever needs them subscribes.
