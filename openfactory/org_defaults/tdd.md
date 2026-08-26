# Org default: test-driven development

This is an **organization-level** default (ADR-0001 D-2, layer 3): it applies to
every project unless a project tightens it further. It is *content* (a guideline
the worker wears), never framework machinery.

- Write the test before the implementation.
- A change without a corresponding test is incomplete, not "done".
- Prefer the smallest test that pins the behavior described by the acceptance
  criterion it maps to.
