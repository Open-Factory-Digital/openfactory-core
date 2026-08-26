"""Which notifier a project's unprompted speech goes through — from config, never from an import.

THE PUSH HALF OF A CHANNEL. `build_channel` answers "where do conversations happen" (say, mention,
listen); this answers "where does the tech-lead speak when nobody asked" — the diagnosis voice,
the park alerts, the deploy outcomes, the pull request that is ready. Same kind, two adapters:
a chat channel's notifier posts with a bot token where its channel adapter opens a socket, and
the panel's writes into the message store its channel adapter reads back.

WHAT THIS REPLACES, measured 2026-08-26: `factory.notifier_for_project` was an if-chain — explicit
panel, then Slack when a token and a channel id resolve, then Telegram from two env vars, then the
panel — with no table and no plugin lookup. A stranger who installed `channel.matrix` AND
`notifier.matrix` got their channel built and their notifier silently replaced by the panel's:
eight call sites of unprompted speech landed in a store their users never open, with no line in
any log. The kind is resolved the same way the channel registry resolves it (`channel_kind`), a
built-in row wins, an add-on's `notifier.<kind>` row fills the rest.

THE TABLE HOLDS THE PANEL AND NOTHING ELSE. The chat rows — `slack`, and `telegram` as the
deployment-wide fallback — were built-in rows importing their module lazily until 2026-08-26, so
with the chat modules absent the Slack row raised a `ModuleNotFoundError` and the Telegram row
did the same the moment a deployment set its two variables. Both ship in `openfactory-slack` now
and arrive through the `notifier.<kind>` entry point; a kind the platform's own packages ship is
refused (here: warned about) naming the package to install (`plugins.install_hint`).

THE DEPLOYMENT-WIDE FALLBACK IS DECLARED, NEVER INFERRED. The Telegram row used to switch itself
on whenever `OPENFACTORY_TELEGRAM_BOT_TOKEN` and `OPENFACTORY_TELEGRAM_CHAT_ID` were set — the
core reading a vendor's variables to decide a vendor was wanted, the same inference the cloud cut
removed from the box axis (`fargate` from a cluster variable). Now `OPENFACTORY_NOTIFIER_FALLBACK`
names a KIND on this axis (`telegram`, or a stranger's), the row it names is built the way every
row is, and a deployment that names nothing has the panel as its last resort — the reference
surface (ADR-0038). A declared fallback that cannot be built, or cannot post, is a WARNING naming
what it lacked; it is never silently the panel.

TWO RULES THE TABLE KEEPS, and both are ordering:

- An INFERRED panel does not step in front of the declared fallback. `channel_kind` infers
  `panel` for a project with neither a declaration nor chat coordinates; a deployment that
  declared a fallback on purpose must still be spoken to there. So an inferred default consults
  the fallback first, and a DECLARED kind never does — `channel: panel` is a choice, not an
  absence.
- AN ADD-ON CHANNEL WITH NO NOTIFIER OF ITS OWN IS NOT A FAILURE. `ChannelAdapter.say` is a
  legitimate way to build a channel and stop; refusing here would fail `build_runner` at job
  start and the `notify_deploy` activity mid-flight — absence read as failure. The notifications
  fall back to the declared fallback (or the panel), and the fallback is LOGGED BY NAME so the
  silence the operator would otherwise be diagnosing has a sentence in the worker's log.

Never raises. Every caller is a scheduled round or an activity that would turn one unresolvable
notifier into a retry storm; an unknown kind is a warning naming the kind, and the message still
lands somewhere a person can find it.

NEVER SILENT, THE ROWS INCLUDED. A row answers a Notifier, or `CannotPost(missing=…)` naming
what it lacked, or `None` (an add-on following the shorter contract). The first version of this
module let a `None` fall through to the fallback with no line at all — measured 2026-08-26: a
Slack row with no bot token became the panel and nothing said so, the very silence the docstring
above promised was gone. Every fallback taken here is one WARNING naming the project, the kind,
what was missing and where the speech went instead.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass

from openfactory import plugins
from openfactory.adapters.channel.registry import CHANNELS, DEFAULT_KIND, channel_kind

log = logging.getLogger("openfactory.notify")

#: The entry-point axis name: `notifier.<kind>` — a builder
#: `build(project) -> Notifier | CannotPost | None`. The project may be `None` when the row is
#: asked for as the deployment-wide fallback by a caller with no project in hand.
AXIS = "notifier"

#: The variable that names the deployment-wide fallback KIND — a row on this axis, built with the
#: project (or `None`) like any other. Unset means: the panel is the last resort.
FALLBACK_ENV = "OPENFACTORY_NOTIFIER_FALLBACK"


@dataclass(frozen=True)
class CannotPost:
    """A row's answer when it cannot post for this project: WHAT it lacked, by name — the env
    var it reads, the registry field it needs — so the warning that takes the fallback can say
    which line in which file would have made the row speak."""

    missing: tuple[str, ...]


def _panel(project):
    from openfactory.adapters.notify.panel import PanelNotifier

    return PanelNotifier(project_name=str(getattr(project, "name", "") or ""))


#: kind → builder, `build(project) -> Notifier | CannotPost | None`. Keyed by CHANNEL kind on
#: purpose: a project declares one channel and gets both halves of it. `CannotPost` (or a bare
#: `None`) means "this row cannot post for this project" and the fallback below decides, never
#: the caller — and never silently. A chat notifier joins through the entry point, never here.
NOTIFIERS: dict[str, Callable[..., object]] = {
    "panel": _panel,
}


def fallback_kind() -> str:
    """The deployment-wide fallback kind, as declared — `""` when the deployment declared none."""
    return (os.environ.get(FALLBACK_ENV) or "").strip().lower()


@dataclass(frozen=True)
class FallbackState:
    """What the deployment declared as its fallback and what stands behind it — read by
    `openfactory doctor`, so the state has ONE printed line. Measured 2026-08-26: a deployment
    with a fallback row's two variables set and no declaration built `NullNotifier` for every
    project-less caller and this logger emitted nothing — two variables present and unread, and
    no sentence anywhere saying so."""

    #: the kind `FALLBACK_ENV` names; `""` when the deployment declared none
    declared: str
    #: a row answers for the declared kind (built-in or installed)
    implemented: bool
    #: what the declared row said it lacked; `""` when it can post, or when there is no row
    cannot_post: str
    #: the candidates a deployment could declare, in the registry's order: every installed
    #: (non-built-in) kind whose PROJECT-LESS answer is a Notifier, or a `CannotPost` lacking
    #: only variables the row declares it reads (`plugins.environment`) — what a deployment sets
    installed: tuple[str, ...]
    #: installed kinds a project-less caller can never use, each with what the row would still
    #: need once its variables are set. The reviewer's probe (2026-08-26): with the chat package
    #: installed and nothing declared, the doctor offered `<one of slack, telegram>` — and the
    #: per-project row answers "the project's channel_id" to a project-less caller, so declaring
    #: it can never post. Every offered option must be executable; this row is held back, said.
    unserviceable: tuple[tuple[str, str], ...] = ()


def fallback_state(project=None) -> FallbackState:
    """The fallback as this deployment stands: declared or not, implemented or not, able to post
    or not, which installed kinds a deployment could declare and which it never usefully can.
    Never raises (`_row_answer`)."""
    kind = fallback_kind()
    installed, unserviceable = _candidates()
    if not kind:
        return FallbackState("", False, "", installed, unserviceable)
    builder = NOTIFIERS.get(kind) or plugins.builder(AXIS, kind, builtin=NOTIFIERS)
    if builder is None:
        return FallbackState(kind, False, "", installed, unserviceable)
    answer = _row_answer(kind, project, builder)
    lacked = _lacked(answer) if isinstance(answer, CannotPost) else ""
    return FallbackState(kind, True, lacked, installed, unserviceable)


_ENV_SHAPED = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")


def _candidates() -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """The installed (non-built-in) kinds, split: offered when a project-less caller could use
    the row once its variables are set; held back, with what it would still need, otherwise."""
    offered: list[str] = []
    held: list[tuple[str, str]] = []
    for kind in plugins.known(AXIS, NOTIFIERS):
        if kind in NOTIFIERS:
            continue
        need = _still_needed(kind, plugins.builder(AXIS, kind, builtin=NOTIFIERS))
        if need:
            held.append((kind, need))
        else:
            offered.append(kind)
    return tuple(offered), tuple(held)


def _still_needed(kind: str, builder) -> str:
    """`""` when `kind` could serve project-less callers once its declared variables are filled
    — its answer for no project is a Notifier, or a `CannotPost` whose every item names one of
    the variables the row declares it reads. Otherwise what the row would still need: a project
    field, an undeclared variable, a builder that loads or does not raise."""
    if builder is None:
        return "a row that loads"
    answer = _row_answer(kind, None, builder)
    if not isinstance(answer, CannotPost):
        return ""
    if not answer.missing:
        return _lacked(answer)
    declared = set(plugins.environment(builder))
    unmet = [what for what in answer.missing if not (set(_ENV_SHAPED.findall(what)) & declared)]
    return ", ".join(unmet)


def _row_answer(kind: str, project, builder: Callable[..., object]):
    """A row's answer for `project`, normalised: a `Notifier`, or `CannotPost` naming what it
    lacked — a row that raises is a row that cannot post (its error is what it lacked), and a
    row that hands back a non-notifier is refused by name rather than used."""
    from openfactory.adapters.notify.base import Notifier

    try:
        built = builder(project)
    except Exception as exc:  # noqa: BLE001 — the contract is "never raises", and a row is code we did not write
        # A ROW THAT RAISES IS A ROW THAT CANNOT POST, said the same way. Every caller here is a
        # scheduled round or an activity; an exception out of a builder would turn one add-on's
        # bug into a retry storm on the floor (the reviewer's cut, 2026-08-26). The row's error is
        # what it lacked, so the add-on's author finds it by name.
        return CannotPost(missing=(f"a builder that does not raise ({type(exc).__name__}: "
                                   f"{str(exc)[:120]})",))
    if built is None:
        return CannotPost(missing=())
    if isinstance(built, CannotPost):
        return built
    if not isinstance(built, Notifier):
        # REFUSED, NOT USED, and said out loud: a notifier without `notify` would fail the first
        # scheduled round that speaks, hours after the misconfiguration, as an AttributeError.
        return CannotPost(missing=(f"a builder whose result satisfies Notifier — got "
                                   f"{type(built).__name__}, which does not satisfy Notifier "
                                   f"(no `notify`)",))
    return built


def _lacked(answer: CannotPost) -> str:
    return (", ".join(answer.missing) if answer.missing
            else "something it did not name (the row answered None)")


def _declared_fallback(project):
    """The notifier `OPENFACTORY_NOTIFIER_FALLBACK` names, or None — with one WARNING when the
    declaration cannot be honoured: the kind nobody installed (naming the package when it is one
    of ours), or a row that cannot post (naming what it lacked)."""
    kind = fallback_kind()
    if not kind:
        return None
    builder = NOTIFIERS.get(kind) or plugins.builder(AXIS, kind, builtin=NOTIFIERS)
    if builder is None:
        log.warning("%s names %r, which no notifier row implements (known: %s)%s; the "
                    "deployment-wide fallback is the panel until that is installed",
                    FALLBACK_ENV, kind, ", ".join(plugins.known(AXIS, NOTIFIERS)),
                    plugins.install_hint(AXIS, kind))
        return None
    answer = _row_answer(kind, project, builder)
    if isinstance(answer, CannotPost):
        log.warning("%s names %r, but that notifier cannot post — missing %s; the "
                    "deployment-wide fallback is the panel until that is filled in",
                    FALLBACK_ENV, kind, _lacked(answer))
        return None
    return answer


def _last_resort(project):
    """THE PANEL, NOT SILENCE (ADR-0038: the panel is the reference surface; channels are
    add-ons). A project with no channel configured used to fall through to NullNotifier — so a
    fresh no-Slack deployment had a mute tech-lead standing next to the panel's own message store.
    `NullNotifier` remains only for the project-less caller, which has no store row to write to."""
    if project is not None and str(getattr(project, "name", "") or ""):
        return _panel(project)
    from openfactory.adapters.notify.base import NullNotifier

    return NullNotifier()


def _fallback(project):
    """Where speech goes when the project's own row cannot carry it: the declared deployment-wide
    fallback, else the panel (or, with no project at all, nothing)."""
    return _declared_fallback(project) or _last_resort(project)


def _channel_knows(kind: str) -> bool:
    return kind in CHANNELS or plugins.builder("channel", kind, builtin=CHANNELS) is not None


def build_notifier(project=None):
    """The notifier a project's unprompted speech goes through. Never raises — see the module
    docstring for the two ordering rules and the add-on fallback."""
    if project is None:
        return _fallback(None)

    name = str(getattr(project, "name", "") or "")
    kind = channel_kind(project)
    declared = bool(str(getattr(project, "channel", "") or "").strip())

    builder = NOTIFIERS.get(kind) or plugins.builder(AXIS, kind, builtin=NOTIFIERS)
    if builder is None:
        fallback = _fallback(project)
        reason = ("has a channel adapter but no notifier of its own"
                  if _channel_knows(kind) else
                  "is known to neither the channel nor the notifier registry — `build_channel` "
                  "refuses it by name")
        log.warning("project %s speaks through %r, which %s%s; its notifications go to %s "
                    "(install a `%s.%s` entry point to change that)",
                    name or "?", kind, reason, plugins.install_hint(AXIS, kind),
                    type(fallback).__name__, AXIS, kind)
        return fallback

    built = _row_answer(kind, project, builder)
    if isinstance(built, CannotPost):
        # THE ROW CANNOT POST, AND SAYS SO. What it lacked comes from the row (`CannotPost`) or
        # is admitted to be unknown (a bare `None`); the fallback taken is named by type.
        fallback = _fallback(project)
        log.warning("project %s speaks through %r, but that notifier cannot post — missing %s; "
                    "its notifications go to %s until that is filled in",
                    name or "?", kind, _lacked(built), type(fallback).__name__)
        return fallback
    if declared or kind != DEFAULT_KIND:
        return built
    # An inferred default: the declared fallback first, then what the row built (the panel).
    return _declared_fallback(project) or built
