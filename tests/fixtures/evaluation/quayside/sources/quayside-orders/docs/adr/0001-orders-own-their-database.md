# 1. The orders service owns its database

- **Status:** Accepted
- **Date:** 2026-03-02

## Context

Billing needs an order's lines to invoice it. Reading them straight from the orders database
would tie billing to the orders schema.

## Decision

Only the orders service reads and writes the orders database. Anybody else asks it, over its HTTP
API, or listens to the events it sends.

## Consequences

A change to the orders schema is a change to one service.
