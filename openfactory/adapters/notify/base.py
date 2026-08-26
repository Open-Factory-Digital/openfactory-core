"""Notifier — status + escalation channel (ADR-0001 D-12).

This is the "connect it to Telegram" seam: the platform tells the human what
shipped, what needs approval (e.g. a prod promotion), and what failed and needs a
decision. Kept behind a Protocol so Telegram/Slack/email are interchangeable.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

Level = Literal["info", "action_required", "warning", "error"]


@runtime_checkable
class Notifier(Protocol):
    def notify(self, *, message: str, level: Level = "info",
               about: str = "") -> str | None:
        """Send a status/escalation message to the human channel.

        `about` names the ticket this message is asking about, when it is asking about one. The
        PROVIDER decides what to do with it — Slack links the thread it opens to that ticket, so a
        reply there needs no number; a provider with no message identity ignores it. The core says
        WHAT the message is about and never HOW the link is made.

        RETURNS THE PROVIDER'S HANDLE FOR THE MESSAGE — Slack's `ts` — or None when there is none.

        It used to return None always, and that single discarded value is why every call-to-action
        this platform emits was a dead end: the message names a ticket in prose, asks for an answer,
        and destroys the only thing a reply could be resolved against. A person answering IN THE
        ALERT'S OWN THREAD, with the verb the alert asked for, reached nothing at all — because
        nothing knew which ticket that thread was about.

        None is a legitimate answer (a provider with no message identity, a drop); the caller
        degrades to requiring a fully-qualified command. It must never be an unexamined default.
        """
        ...


class NullNotifier(Notifier):
    """Default: drops notifications (used when no channel is configured)."""

    def notify(self, *, message: str, level: Level = "info",
               about: str = "") -> str | None:
        return None
