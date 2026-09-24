"""Which runtime runs a preview — resolved from the deployment, never from a file the agent can
write (ADR-0050 D11; the design on #265, §5.1).

THE KIND IS DEPLOYMENT-SHAPED, LIKE THE BOX. `OPENFACTORY_PREVIEW_RUNTIME` names it
(`runtime/temporal/io.py::default_preview_runtime`, default `none`), and nothing a repository
declares can move it: the runtime decides which daemon agent-written code runs on, and that is the
operator's decision.

BORN WITH TWO ROWS, AND OPEN. `compose` runs the plan on the deployment's own Docker daemon;
`none` refuses by name. A third — a Kubernetes namespace, a vendor's ephemeral environments — is a
`preview.<kind>` entry point in the `openfactory.adapters` group, whose builder returns a row in
the same shape as ours: `(PreviewTraits, factory)`. An add-on's row is checked by `_check_row`,
the check ours pass at import, so a stranger's mistake is refused in the same words; and what its
factory builds must satisfy `PreviewRuntime`, or it is REFUSED rather than used — a runtime
missing `down` would leave every preview it started running for ever.

RESOLVED ON THE ACTIVITY SIDE. `plugins._load()` scans site-packages; a workflow body must never
ask this module anything. The workflow reads the kind as data and an activity builds the row
(the two-lookup rule `adapters/sandbox/registry.py` states).
"""

from __future__ import annotations

from collections.abc import Callable

from openfactory import plugins
from openfactory.adapters.preview.base import PreviewRuntime, PreviewTraits

#: The entry-point axis a runtime registers under (`preview.<kind>` → a row).
AXIS = "preview"


def _compose(**kw):
    """EVERY knob by name, so an unknown one is a TypeError here, naming itself, rather than a
    setting silently ignored (the box registry's rule, ADR-0018)."""
    from openfactory.adapters.preview.compose import ComposeRuntime

    known = ("reach", "panel_container", "start_timeout", "settle_seconds", "poll_seconds",
             "log_root", "clock", "sleep")
    unknown = sorted(set(kw) - set(known))
    if unknown:
        raise TypeError(f"the compose preview runtime takes no {unknown} — it takes {known}")
    return ComposeRuntime(**{k: kw[k] for k in known if kw.get(k) is not None})


def _none(**_kw):
    from openfactory.adapters.preview.none import NoRuntime

    return NoRuntime()


def _checked(rows: dict[str, tuple]) -> dict[str, tuple]:
    """Every row answers for itself, AT IMPORT — and the same check admits an add-on's row."""
    for kind, row in rows.items():
        _check_row(kind, row)
    return rows


def _check_row(kind: str, row: object) -> tuple:
    if not isinstance(row, tuple) or len(row) != 2:
        raise TypeError(f"the {kind!r} preview runtime row must be (PreviewTraits, factory); got "
                        f"{type(row).__name__}")
    traits, build = row
    if not isinstance(traits, PreviewTraits):
        raise TypeError(f"the {kind!r} preview runtime row does not start with PreviewTraits; got "
                        f"{type(traits).__name__}")
    if traits.name != kind:
        raise TypeError(f"the preview runtime row filed under {kind!r} describes {traits.name!r}")
    if not callable(build):
        raise TypeError(f"the {kind!r} preview runtime row's factory is not callable")
    unknown = set(traits.reaches) - {"network", "loopback"}
    if unknown:
        raise TypeError(f"the {kind!r} preview runtime claims reaches the panel cannot route: "
                        f"{sorted(unknown)}")
    return row


#: kind → (traits, factory). A new runtime joins as one row — here, or through the
#: `preview.<kind>` entry point without editing this file.
RUNTIMES: dict[str, tuple[PreviewTraits, Callable]] = _checked({
    # The deployment's own Docker daemon, through the compose CLI the worker carries. It builds
    # (a service the change touched is built from the change's tree) and both reaches exist:
    # `network` on the compose stack, `loopback` on one machine.
    "compose": (PreviewTraits(name="compose", builds=True, reaches=("network", "loopback")),
                _compose),
    # Nothing runs, and every door says so by name (`none.REFUSAL`).
    "none": (PreviewTraits(name="none", builds=False, reaches=()), _none),
})


def _key(kind: str) -> str:
    return (kind or "").strip().lower()


def _row(kind: str) -> tuple:
    key = _key(kind)
    row = RUNTIMES.get(key)
    if row is not None:
        return row
    make = plugins.builder(AXIS, key, builtin=RUNTIMES)
    if make is None:
        raise ValueError(f"unknown preview runtime {kind!r} — known: "
                         f"{', '.join(plugins.known(AXIS, RUNTIMES))}"
                         f"{plugins.install_hint(AXIS, key)}. Set OPENFACTORY_PREVIEW_RUNTIME to "
                         f"one of them, or install the add-on that declares `{AXIS}.{key}`.")
    return _check_row(key, make())


def runtime_traits(kind: str) -> PreviewTraits:
    """What a runtime is, built-in or installed — asked without building it."""
    return _row(kind)[0]


def build_runtime(kind: str, **kw) -> PreviewRuntime:
    """The runtime for this kind. Raises on an unknown kind, naming what IS installed — a
    deployment whose previews silently ran nowhere would show a start button that does nothing —
    and on a factory that builds something that is not a `PreviewRuntime`."""
    built = _row(kind)[1](**kw)
    if not isinstance(built, PreviewRuntime):
        missing = [m for m in ("prerequisites", "up", "watch", "logs", "down", "running", "prove")
                   if not hasattr(built, m)]
        raise TypeError(f"the {kind!r} preview runtime does not satisfy PreviewRuntime (missing: "
                        f"{missing}) — refused rather than used: a runtime that cannot `down` "
                        f"leaves every preview it starts running")
    return built
