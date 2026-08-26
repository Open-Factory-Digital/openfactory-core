"""Where a stranger's adapter registers itself — without editing a file of ours (#106).

`docs/core/07-extensibility.md` states the rule the platform is measured against:

    an axis is agnostic when it is BORN WITH TWO; a platform is extensible when a stranger can
    add the third WITHOUT EDITING OUR FILES.

By the first half the axes pass — every one ships two or more implementations, dispatched by a
registry that refuses an unknown kind. By the second half the platform failed, and the same
document admitted it in as many words: *"`openfactory install <addon>` is impossible today — an
add-on would have nowhere to register itself."* Every registry a dict literal, all inside this
repository (seven of them when the sentence was written; `AXES` below is the count today).
Adding a row meant opening a pull request against us.

This is that nowhere, filled in. A package declares entry points in the group below and its rows
join the tables at lookup time:

    [project.entry-points."openfactory.adapters"]
    "forge.gitlab" = "openfactory_gitlab:build_forge"

WHAT DOES NOT CHANGE, and it is the part worth protecting. An unknown kind still RAISES, naming
what IS supported — the house rule, and the reason is in `observability/registry.py`: falling back
to a null implementation would run the factory with no journal and look exactly like a job that
has not started. What changes is only that the list it names can grow from outside.

BUILT-INS WIN A COLLISION. A plugin declaring `forge.github` does not silently replace the one the
platform ships: the shipped row answers, and the collision is logged. An add-on that could shadow
a core adapter is an add-on that can change what "github" means for every project on the
deployment, which is not an extension point — it is a supply chain.

LOADED LAZILY AND CACHED. Import time is where a broken third-party package would take the whole
CLI down, and a stranger's code must never be a reason `openfactory --help` fails.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger("openfactory.plugins")

#: The entry-point group an add-on declares. One group for every axis, with the axis in the NAME
#: (`forge.gitlab`), because a group per axis would mean a stranger has to know which of the
#: axes below to use before they know whether we support their kind at all.
#:
#: ONE AXIS RETURNS A VALUE RATHER THAN AN ADAPTER: `role.<name>` (2026-08-24). Its builder takes
#: no arguments and returns an `adapters.agent.roles.RoleSpec` — the role's prompt, env names and
#: default harness — because a role is configuration the harness registry resolves, not a client
#: it constructs. Same group, same `builder()`/`known()`/`shadowed()`, same built-ins-win rule; the
#: harness registry (`adapters/agent/registry.py`) is the one that validates what came back.
GROUP = "openfactory.adapters"

#: EVERY axis an entry point may name — the published list, and the one the extensibility guard
#: derives from the registries and compares with (`tests/test_a_stranger_can_add_an_adapter.py`):
#: an axis here that no registry asks for is a door painted on a wall, and a registry that asks
#: for an axis not listed here is one a stranger cannot find. The provider axes published in
#: `docs/architecture.md` §6's seam table are here by their entry-point names (`harness` for the
#: coding agent, `box` for the sandbox, `ci` for the CI observer, `event`/`metrics` for
#: observability), plus the ones the platform grew on the way: the notifier (the push half of a
#: channel), identity, the agent role, the session store, the token-pool source, and the runner
#: of a remote box.
AXES: tuple[str, ...] = (
    "tracker", "board", "forge", "ci", "harness", "box", "event", "metrics", "channel",
    "notifier", "identity", "role", "session_store", "token_pool", "box_runner",
    # The two the forge cut added on 2026-08-26, when the credential and the board setup stopped
    # being GitHub's by name: a vendor's credential resolver and its board creator are rows too.
    "credential", "board_setup",
)

#: WHERE THE PLATFORM'S OWN ROWS SHIP, by entry-point name, so a refusal can say which package to
#: install rather than only that the kind is unknown. Measured before this table existed
#: (2026-08-26): with the chat modules absent, `channel: slack` raised a `ModuleNotFoundError`
#: out of a built-in row; with the row gone it was refused by name, correctly, and the sentence
#: listed `panel` — leaving the operator to guess that a package exists. A PACKAGE NAME IS NOT A
#: VENDOR'S PRODUCT: the value names the distribution that carries the row, and the key is the
#: kind the deployment already declared. `tests/test_the_chat_is_a_directory_delete.py` holds
#: every key to a row one of the packages under `addons/` declares, and every declared row to a
#: key here.
SHIPS_IN: dict[str, str] = {
    "channel.slack": "openfactory-slack",
    "notifier.slack": "openfactory-slack",
    "notifier.telegram": "openfactory-slack",
    "box_runner.fargate": "openfactory-aws",
    "metrics.dynamodb": "openfactory-aws",
    "session_store.s3": "openfactory-aws",
    "token_pool.ssm": "openfactory-aws",
}


def install_hint(axis: str, kind: str) -> str:
    """The clause a refusal appends for a kind the platform's own packages ship: which package
    carries the row, and a remedy that can be followed. Empty for a kind nobody publishes — the
    refusal then says only what IS installed, which is all it knows.

    IT NO LONGER SAYS `pip install <name>`, AND THAT WAS THE ONLY REMEDY A STUCK OPERATOR HAD
    (2026-08-26). Nothing in this repository publishes a distribution to an index, so the bare
    name resolved nowhere: the one command the platform handed a person at the moment it refused
    to run was a command that fails, while the page repeating it called the packages private
    twenty lines later. What is TRUE is where the row comes from — a wheel the deployment
    carries — and what the kind is called on the entry-point group, which is also the whole
    contract a stranger needs to satisfy it with a package of their own
    (`docs/core/07-extensibility.md`).
    """
    package = SHIPS_IN.get(f"{axis}.{kind}")
    if package is None:
        return ""
    return (f" — {kind!r} ships in the add-on package {package}, which is on no public index: "
            f"install the wheel your deployment carries, or any package declaring `{axis}.{kind}`")


_cache: dict[str, dict[str, Callable[..., Any]]] | None = None


def _load() -> dict[str, dict[str, Callable[..., Any]]]:
    global _cache
    if _cache is not None:
        return _cache
    found: dict[str, dict[str, Callable[..., Any]]] = {}
    try:
        from importlib.metadata import entry_points

        points = entry_points(group=GROUP)
    except Exception:  # noqa: BLE001 — a broken metadata store must not take the CLI down
        log.warning("could not read the %s entry points", GROUP, exc_info=True)
        _cache = {}
        return _cache
    for point in points:
        axis, _, kind = point.name.partition(".")
        if not axis or not kind:
            log.warning("ignoring add-on entry point %r — the name must be `<axis>.<kind>`, e.g. "
                        "`forge.gitlab`", point.name)
            continue
        try:
            builder = point.load()
        except Exception:  # noqa: BLE001 — one bad add-on may not disable the others
            log.warning("add-on %r could not be loaded and is ignored; every other axis is "
                        "unaffected", point.name, exc_info=True)
            continue
        if not callable(builder):
            log.warning("add-on %r does not point at a callable and is ignored", point.name)
            continue
        found.setdefault(axis, {})[kind] = builder
    _cache = found
    return _cache


def reset_cache() -> None:
    """Forget what was loaded. For tests that install an entry point mid-run — production loads
    once and never changes, which is the whole reason the cache exists."""
    global _cache
    _cache = None


def builder(axis: str, kind: str, *, builtin: dict) -> Callable[..., Any] | None:
    """An add-on's builder for `axis`/`kind`, or None — never one that shadows a built-in.

    `builtin` is passed rather than imported so this module stays ignorant of the tables:
    the registry that owns the axis is the one that knows its own rows, and a second copy of that
    knowledge here would be a second place to keep in step.
    """
    if kind in builtin:
        return None
    return _load().get(axis, {}).get(kind)


def known(axis: str, builtin: dict) -> list[str]:
    """Every kind this deployment can build for `axis` — shipped plus installed, sorted.

    Used by the refusal message. A stranger who installed an add-on and typo'd the kind has to see
    their own row in the list, or the error tells them the platform does not support what they
    just installed.
    """
    added = [k for k in _load().get(axis, {}) if k not in builtin]
    if added:
        log.debug("%s add-ons: %s", axis, ", ".join(sorted(added)))
    return sorted({*builtin, *added})


def environment(builder: Callable[..., Any] | None) -> tuple[str, ...]:
    """The environment variables a row DECLARES it reads — `builder.environment`, a zero-argument
    callable answering names or a tuple of them; `()` for a row that declares nothing, and for
    no row at all.

    WHY A ROW SAYS IT. `openfactory init` writes the deployment's environment with a row for every
    variable the chosen kinds read; for a kind the core does not ship, the only party that knows
    the names is the package that ships it. The core carried the chat package's two variables
    by name until 2026-08-26 — the one place it still spelled a vendor's variable after the chat
    cut. A row derives its answer the way the core derives its own reservations
    (`environ.names_read`, by AST) rather than keeping a table; `how_to` beside it is the
    package's own comment for the block."""
    declared = getattr(builder, "environment", None)
    if declared is None:
        return ()
    names = declared() if callable(declared) else declared
    return tuple(str(n) for n in names)


def how_to(builder: Callable[..., Any] | None) -> str:
    """The row's own comment for the rows it declares (`builder.how_to`), or `""`."""
    return str(getattr(builder, "how_to", "") or "")


def shadowed(axis: str, builtin: dict) -> list[str]:
    """Kinds an add-on declared that a built-in already owns. Reported rather than honoured — see
    the module docstring: an add-on that can redefine `github` is a supply chain, not an
    extension."""
    return sorted(k for k in _load().get(axis, {}) if k in builtin)
