---
description: Freight is priced on the greater of the actual weight and the volumetric
  weight, 333 kg per cubic metre.
generated:
  at: '2026-09-24T00:00:00Z'
  by: machine:fixture
sources:
- commit: fixture
  fingerprint: 46b9bb57d4156abcd1f9eb4f44f96fbf1a4bd042f11834564377457f23c2e0be
  lines: 17-19
  path: pricing/freight.py
  repo: harbourline-pricing
status: draft
title: Chargeable weight
type: policy
---

# Chargeable weight

## What it does

`chargeable_weight` returns max(actual kg, m3 x 333); `freight` multiplies it by the lane's rate and adds the surcharges.

## Business rules

- the volumetric weight is 333 kg per cubic metre (`pricing/freight.py:8`)

## Consumed by

- harbourline
- harbourline-web
