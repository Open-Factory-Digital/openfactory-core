from openfactory.adapters.preview.base import PreviewRuntime, PreviewTraits, PrunesCaches

__all__ = ["ComposeRuntime", "NoRuntime", "PreviewRuntime", "PreviewTraits", "PrunesCaches"]

_LAZY = {
    "ComposeRuntime": "openfactory.adapters.preview.compose",
    "NoRuntime": "openfactory.adapters.preview.none",
}


# LAZY, like every other port package: importing the PORT must not load a row — see
# `openfactory/adapters/sandbox/__init__.py` for why that is a contract and not an optimisation.
def __getattr__(name: str):
    import importlib

    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)


def __dir__():
    return sorted(__all__)
