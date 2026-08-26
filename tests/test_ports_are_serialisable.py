"""Every port signature stays serialisable, so the extension model stays a decision (C-09).

`docs/core/07-extensibility.md` leaves one question deliberately open: whether a provider is an
in-process Python plugin or a separate process the Core talks to over a wire. The in-process
version is cheap and closes the door on a provider written in C# or plugged in without rebuilding
the worker. That door should be closed by a decision, never by a signature nobody noticed.

Out-of-process providers are possible only while what crosses a port can travel. Today every one
of the eight ports already qualifies — not by design, but as a consequence of ADR-0022 §3: *the
contract is derived from what the Core CALLS, never from what a provider OFFERS*. A channel
contract built from what Slack can do would have handles and callbacks in it. Built from three
calls, it is serialisable by happy accident.

This test makes the accident permanent. Closing the door now requires making a test go red, which
is a decision; without it, it happens by drift.

WHAT THIS GUARD IS NOT. `Path` passes here and is *semantically* machine-local: a filesystem path
means nothing to a provider on another host. `Workspace` already carries that lesson in its
`host_path` field. Serialisability is necessary for a remote transport and not sufficient for one,
and this test only claims the former.
"""

from __future__ import annotations

import enum
import importlib
import inspect
import types
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel

# The eight provider axes, plus the two observability sinks that ADR-0022's audit never covered.
PORT_MODULES = [
    "openfactory.adapters.agent.base",
    "openfactory.adapters.board.base",
    "openfactory.adapters.channel.base",
    "openfactory.adapters.environment.base",
    "openfactory.adapters.forge.base",
    "openfactory.adapters.notify.base",
    "openfactory.adapters.reviewer.base",
    "openfactory.adapters.sandbox.base",
    "openfactory.adapters.tracker.base",
    "openfactory.observability.events",
    "openfactory.observability.metrics",
]

#: Types that survive a wire. `Path` is here with the caveat in the module docstring.
_SCALARS = (str, int, float, bool, bytes, type(None), Path)

#: Unparameterised containers. `list[dict]` in this codebase means "JSON from a provider", and
#: demanding `dict[str, object]` everywhere would be churn for no safety — `object` is no more
#: transportable than `dict`. They are allowed because the guard's target is a LIVE OBJECT, and a
#: container is data by construction. `Any` stays refused: it is a claim about nothing.
_BARE_CONTAINERS = (list, dict, tuple, set, frozenset)

#: THE ONE EXCEPTION, and it is architecture rather than debt.
#:
#: The agent, reviewer and judgment ports take a live `SandboxAdapter`, because the harness runs
#: INSIDE the box: `execute` needs `sandbox.run(...)` to exec its CLI in the container. That pair
#: is physically co-located, so passing a handle instead would only move the callback somewhere
#: worse.
#:
#: The consequence is worth stating precisely, because it is the answer to a question
#: `docs/core/07-extensibility.md` leaves open: **the harness axis cannot go out of process
#: without a different contract; the other seven can.** An out-of-process harness would receive a
#: box IDENTIFIER and ask the Core to run things in it — a real design, not a signature tweak.
#:
#: Pinned by `test_the_exception_list_has_not_grown`, so this stays one reasoned hole rather than
#: an escape hatch.
_CO_LOCATED = {"SandboxAdapter"}


def _serialisable(tp: object) -> bool:
    """Can a value of this annotation be turned into data and back?

    Deliberately a WHITELIST. A denylist of the obvious offenders (`Callable`, `IO`) would pass
    anything nobody thought of — including `Any`, which is the widest hole of all and the one a
    hurried signature reaches for."""
    if tp is None or tp in _SCALARS:  # `-> None` annotates as the singleton, not NoneType
        return True
    if isinstance(tp, type):
        if tp in _BARE_CONTAINERS:
            return True
        if issubclass(tp, (BaseModel, enum.Enum)):
            return True
        if issubclass(tp, _SCALARS):
            return True
        return getattr(tp, "__name__", "") in _CO_LOCATED

    origin = typing.get_origin(tp)
    if origin is None:
        return False  # `Any`, a bare TypeVar, a forward ref that never resolved
    if origin is typing.Literal:
        return True
    if origin in (list, set, frozenset, tuple, dict, typing.Union, types.UnionType):
        return all(a is Ellipsis or _serialisable(a) for a in typing.get_args(tp))
    return False  # Callable, Iterator, Generator, Awaitable, IO, ...


def _protocols(module_name: str):
    mod = importlib.import_module(module_name)
    for name, obj in vars(mod).items():
        if (
            inspect.isclass(obj)
            and getattr(obj, "_is_protocol", False)
            and obj.__module__ == module_name
        ):
            yield name, obj


def _methods(proto: type):
    for name, fn in vars(proto).items():
        if name.startswith("_") or not inspect.isfunction(fn):
            continue
        yield name, fn


def _hints(proto: type, fn) -> dict:
    """Resolve the string annotations `from __future__ import annotations` leaves behind."""
    mod = importlib.import_module(proto.__module__)
    return typing.get_type_hints(fn, globalns=vars(mod))


PORTS = [(m, n, p) for m in PORT_MODULES for n, p in _protocols(m)]


def test_the_inventory_is_not_empty():
    """A guard that walks nothing passes for ever. This is the reachability check on the check —
    the defect this repository has recorded nine times."""
    assert len(PORTS) >= 9, [p[1] for p in PORTS]


@pytest.mark.parametrize("module,proto_name,proto", PORTS, ids=lambda v: getattr(v, "__name__", v))
def test_every_port_method_signature_is_serialisable(module, proto_name, proto):
    offenders: list[str] = []
    for meth_name, fn in _methods(proto):
        try:
            hints = _hints(proto, fn)
        except Exception as exc:  # an annotation that cannot even be resolved is its own failure
            offenders.append(f"{proto_name}.{meth_name}: unresolvable annotations ({exc})")
            continue
        for arg, tp in hints.items():
            if not _serialisable(tp):
                offenders.append(f"{proto_name}.{meth_name}({arg}: {tp!r})")
    assert not offenders, (
        "a port signature stopped being serialisable, which closes the door on an "
        "out-of-process provider by accident rather than by decision "
        "(docs/core/07-extensibility.md §5–7):\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("module,proto_name,proto", PORTS, ids=lambda v: getattr(v, "__name__", v))
def test_every_port_method_annotates_everything(module, proto_name, proto):
    """An unannotated parameter is not "no type" — it is `Any`, which this guard cannot inspect.
    Left alone, it is the easiest way to smuggle a live object across a port."""
    missing: list[str] = []
    for meth_name, fn in _methods(proto):
        sig = inspect.signature(fn)
        for pname, param in sig.parameters.items():
            if pname in ("self", "cls") or param.kind in (
                param.VAR_POSITIONAL, param.VAR_KEYWORD
            ):
                continue
            if param.annotation is inspect.Parameter.empty:
                missing.append(f"{proto_name}.{meth_name}({pname})")
        if sig.return_annotation is inspect.Signature.empty:
            missing.append(f"{proto_name}.{meth_name} -> ?")
    assert not missing, "unannotated port signatures are un-guardable:\n  " + "\n  ".join(missing)


# ── the guard is itself guarded: it must reject what it claims to reject ────────────────────────
#
# A test that passes because its check is broken is worse than no test. Each of these is a
# signature somebody could plausibly write, and each must be refused.

class _Live:
    """A vendor client — the thing an in-process-only port would hand around."""


@pytest.mark.parametrize("annotation", [
    typing.Callable[[int], None],          # a callback: needs a live process on the other side
    typing.Iterator[str],                  # a stream: cannot be a value
    typing.Generator[str, None, None],
    typing.Awaitable[int],
    typing.IO[bytes],                      # an open handle
    typing.Any,                            # the widest hole, and the easiest to write
    _Live,                                 # an arbitrary object
    list[_Live],                           # ... hidden one level down
    dict[str, typing.Callable[[], None]],  # ... and two
    tuple[int, typing.Any],
    typing.Optional[_Live],                # noqa: UP045 — the union form is tested separately
])
def test_the_guard_rejects_what_it_must(annotation):
    assert not _serialisable(annotation)


@pytest.mark.parametrize("annotation", [
    str, int, float, bool, bytes, None, Path,
    list[str], dict[str, int], tuple[int, str], set[str],
    typing.Optional[str],  # noqa: UP045
    str | None,
    list[dict[str, int]],
    typing.Literal["a", "b"],
])
def test_the_guard_accepts_plain_data(annotation):
    assert _serialisable(annotation)


def test_the_exception_list_has_not_grown():
    """One reasoned hole, not an escape hatch. Adding a name here means claiming another pair is
    physically co-located — which is an architectural claim and should cost a conversation."""
    assert _CO_LOCATED == {"SandboxAdapter"}


def test_the_co_located_exception_only_applies_where_it_was_argued():
    """`SandboxAdapter` is allowed because the harness runs inside the box. It must not become a
    way to pass a box into, say, the tracker or the forge."""
    allowed = {"CodingAgentAdapter", "JudgmentAgentAdapter", "ReviewerAdapter"}
    for _mod, proto_name, proto in PORTS:
        if proto_name in allowed:
            continue
        for meth_name, fn in _methods(proto):
            try:
                hints = _hints(proto, fn)
            except Exception:
                continue
            for arg, tp in hints.items():
                assert getattr(tp, "__name__", "") not in _CO_LOCATED, (
                    f"{proto_name}.{meth_name}({arg}) takes a live {tp} — the co-location "
                    "argument was made for the harness/box pair only"
                )


def test_the_guard_accepts_a_pydantic_model_and_an_enum():
    from openfactory.contracts.state import JobState
    from openfactory.observability.events import JobEvent

    assert _serialisable(JobEvent)
    assert _serialisable(JobState)
    assert _serialisable(list[JobEvent])


# ── every port must be checkable, not merely declared ───────────────────────────────────────────

@pytest.mark.parametrize("module,proto_name,proto", PORTS, ids=lambda v: getattr(v, "__name__", v))
def test_every_port_protocol_is_runtime_checkable(module, proto_name, proto):
    """ADR-0022 §2: *a protocol nobody checks is documentation.* Its audit applied this to the
    axes it covered and five were left behind — agent, environment, notify, reviewer and sandbox —
    so `isinstance(x, SandboxAdapter)` raised a TypeError rather than answering. A contract that
    cannot be checked cannot catch an adapter that ships half-implemented, which is the exact
    failure the rule was written after: `BoardAdapter`'s own first implementation had no
    `columns()` and the check caught it within the hour."""
    assert getattr(proto, "_is_runtime_protocol", False), (
        f"{proto_name} cannot be isinstance-checked — add @runtime_checkable"
    )
