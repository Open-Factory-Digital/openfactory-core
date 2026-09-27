"""Which row makes the product's vectors — from configuration, never from an import (#269 slice 2).

ONE LINE OF CONFIGURATION. `OPENFACTORY_EMBED` names the row; unset, it is `local` — decision 14's
default, a model on this machine (`local.py`). `none` turns the semantic stage off on purpose. An
add-on's row joins through the `embed.<kind>` entry point (`plugins.py`) — an external embedding
API is such a row, and it is used only where a deployment names it.

AN UNKNOWN ROW RAISES, NAMING WHAT IS KNOWN — the house rule: falling back to another row would
embed a client's words with something nobody chose. A KNOWN ROW THAT CANNOT BE BUILT HERE raises
`EmbedderUnavailable` with why, and the index answers without the semantic stage and says so.

BUILT ONCE PER PROCESS AND CONFIGURATION (`for_the_index`). A local model is loaded into memory —
a second of work and up to a gigabyte for the multilingual one — so a turn must not load it again;
the refusal is remembered too, so a deployment without the extra does not retry an import on every
turn. A change of configuration is a new key, and is built afresh.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable

from openfactory import plugins
from openfactory.adapters.embed.base import Embedder, EmbedderUnavailable

log = logging.getLogger("openfactory.embed")

#: The entry-point axis: `embed.<kind>` — a builder `build(project=None) -> Embedder`.
AXIS = "embed"

#: The deployment's choice of row, and what it is when nobody chose.
KIND_ENV = "OPENFACTORY_EMBED"
DEFAULT_KIND = "local"
OFF = "none"


def _local(**_kw):
    from openfactory.adapters.embed.local import LocalRow

    return LocalRow.configured()


def _none(**_kw):
    raise EmbedderUnavailable(f"semantic search is turned off on this deployment "
                              f"({KIND_ENV}={OFF}) — the product's index answers by exact words, "
                              f"metadata and time only")


#: kind → builder, `build(project=None) -> Embedder`. Every row the platform ships; an add-on's
#: join through the entry point, and a built-in wins a collision (`plugins.builder`).
EMBEDDERS: dict[str, Callable[..., object]] = {
    "local": _local,
    OFF: _none,
}


def kind() -> str:
    return (os.environ.get(KIND_ENV) or "").strip().lower() or DEFAULT_KIND


def build_embedder(name: str | None = None, *, project=None) -> Embedder:
    """The row `name` (the configured one when None) — `ValueError` for a row nobody knows,
    `EmbedderUnavailable` for one that cannot be built here, with why."""
    chosen = name or kind()
    builder = EMBEDDERS.get(chosen) or plugins.builder(AXIS, chosen, builtin=EMBEDDERS)
    if builder is None:
        raise ValueError(f"unknown embed row {chosen!r} — known: "
                         f"{', '.join(plugins.known(AXIS, EMBEDDERS))}")
    row = builder(project=project)
    if not callable(getattr(row, "embed", None)) or not str(getattr(row, "id", "") or ""):
        raise ValueError(f"the embed row {chosen!r} built something with no `embed(texts)` or no "
                         f"`id` — its vectors could not be told from another model's")
    return row  # type: ignore[return-value]


_BUILT: dict[tuple[str, ...], tuple[Embedder | None, str]] = {}
_LOCK = threading.Lock()


def _key() -> tuple[str, ...]:
    from openfactory.adapters.embed.local import DIGEST_ENV, MODEL_ENV

    return (kind(), os.environ.get(MODEL_ENV) or "", os.environ.get(DIGEST_ENV) or "")


def for_the_index() -> tuple[Embedder | None, str]:
    """`(row, "")`, or `(None, why)` when there is none — never a raise: the index works without
    one, and says so with this sentence. Built once per process and configuration."""
    key = _key()
    with _LOCK:
        if key in _BUILT:
            return _BUILT[key]
    try:
        made: tuple[Embedder | None, str] = (build_embedder(), "")
    except (EmbedderUnavailable, ValueError) as exc:
        made = (None, str(exc))
        log.warning("OPENFACTORY_EMBED_UNAVAILABLE %s", exc)
    except Exception:  # noqa: BLE001 — an add-on's row that raised is a reason too
        # ITS WORDS GO TO THE LOG: the reason is rendered into what the role reads, and a
        # stranger's exception is not a sentence anybody wrote for a person
        made = (None, f"the {key[0]} embed row could not be built (the reason is in the "
                      f"platform's log)")
        log.warning("OPENFACTORY_EMBED_UNAVAILABLE %s", made[1], exc_info=True)
    with _LOCK:
        _BUILT[key] = made
    return made


def readiness() -> tuple[str, str]:
    """What the product's search runs as on THIS machine, without building anything (#337):
    `("semantic", which model)`, `("off", why)` when a deployment turned it off on purpose,
    `("words", why)` when it cannot run here, or `("add-on", which)` for a row an add-on ships —
    never built by a diagnostic, since an add-on's row may be an external API that spends."""
    chosen = kind()
    if chosen == OFF:
        return "off", f"turned off on purpose ({KIND_ENV}={OFF})"
    if chosen != DEFAULT_KIND:
        if EMBEDDERS.get(chosen) or plugins.builder(AXIS, chosen, builtin=EMBEDDERS):
            return "add-on", f"the `{chosen}` row, which an add-on ships — not built here"
        return "words", (f"{KIND_ENV}={chosen!r} names no row — known: "
                         f"{', '.join(plugins.known(AXIS, EMBEDDERS))}")
    from openfactory.adapters.embed.local import PINNED, LocalRow

    try:
        folder, digest = LocalRow.verified()
    except EmbedderUnavailable as exc:
        return "words", str(exc)
    which = PINNED.get(digest) or f"a model whose digest the deployment declared ({digest[:16]}…)"
    return "semantic", f"{which}, verified by its weights' SHA-256, in {folder}"


def _reset_for_tests() -> None:
    with _LOCK:
        _BUILT.clear()
