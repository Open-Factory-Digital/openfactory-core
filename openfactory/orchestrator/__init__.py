"""The orchestrator: the deterministic maestro, plus the pure decisions it makes.

LAZY on purpose. `JobRunner` reaches for adapters, subprocesses and timeouts; `merge_policy` and
`validation` are pure functions over domain types and are part of the Core (`docs/core/02` §1).
Importing one used to load the other, so a Core module could not be imported without the whole
runner and, through it, every vendor library behind it (C-21).
"""

from __future__ import annotations

_LAZY = {"JobRunner": "openfactory.orchestrator.machine"}

__all__ = ["JobRunner"]


def __getattr__(name: str):
    import importlib

    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)


def __dir__():
    return sorted(__all__)
