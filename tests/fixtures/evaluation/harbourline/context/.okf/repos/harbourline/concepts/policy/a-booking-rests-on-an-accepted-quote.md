---
description: A booking is made only against a quote the shipper accepted, within 48
  hours of its issue, on a sailing with room left.
generated:
  at: '2026-09-24T00:00:00Z'
  by: machine:fixture
sources:
- commit: fixture
  fingerprint: 4b561c0c7392fa836372f9cb1006ca826cddb51ed878a9c4c9862d475e948e31
  lines: 35-43
  path: harbourline/bookings.py
  repo: harbourline
status: draft
title: A booking rests on an accepted quote
type: policy
---

# A booking rests on an accepted quote

## What it does

`book` refuses an unaccepted quote and one issued more than 48 hours ago, then reserves the kilograms on the sailing.

## Business rules

- a quote is valid for 48 hours from its issue (`harbourline/bookings.py:11`)

## Consumed by

- harbourline-web
