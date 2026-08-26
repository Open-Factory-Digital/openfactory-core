## What this changes

One or two sentences about the BEHAVIOUR that is different afterwards, not the files touched.

## Why

The situation that produced it. If it is a defect, what it did before.

## How it is proven

This project's bar, from [CONTRIBUTING.md](../CONTRIBUTING.md):

- [ ] a guard that fails without this change and passes with it
- [ ] the guard is proven by mutation — break the thing it protects and watch it go red
      (`tools/mutate.py`, with the plan committed under `tools/mutations/`)
- [ ] `ruff check` clean, and the suite green in both orders
      (`python -m pytest -q -n auto`)

If any box is unchecked, say why here — a stated exception is fine, a silent one is not.

## Anything a reviewer should look at first
