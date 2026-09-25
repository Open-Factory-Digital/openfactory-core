---
description: Freight is the weight times the port pair's rate per kilogram, never
  below the minimum charge.
generated:
  at: '2026-09-24T00:00:00Z'
  by: machine:fixture
sources:
- commit: fixture
  fingerprint: 6522f27e7bdcf21f5e588a1effdb5315b7f31935e4c81a83514811d08897359a
  lines: 15-20
  path: freight/quote.py
  repo: quayside-freight
status: draft
title: The freight calculation
type: policy
---

# The freight calculation

## What it does

`quote` multiplies the weight by the rate of the port pair and never quotes below the minimum charge.

## Business rules

- the rate is per kilogram, by port pair (`freight/quote.py:19`)
- no shipment is quoted below 35.0 (`freight/quote.py:12`)

## Consumed by

- quayside-orders — fixes the quote on an order when it is placed
