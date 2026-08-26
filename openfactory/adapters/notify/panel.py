"""The panel as a PUSH target — the notifier row the registry did not have (C-25 review).

THE HOLE THIS CLOSES. `notifier_for_project` dispatched Slack → Telegram → Null, so on a
`channel: panel` deployment every notification — the tech-lead's diagnosis voice, the park
alerts, the deploy outcomes, the split announcements — resolved to the NullNotifier and
vanished. The panel channel shipped with a message store and a Conversation section, and the
paths that actually SPEAK never wrote into it: built, tested, reached by nothing.

"Push" here means what the panel can honestly offer: the message is DURABLE and visible the
moment anybody looks. Nobody's phone buzzes — that limitation is the provider's, stated on
`PanelChannel` — but a notification that lands in the store is a fact an operator can find,
where a NullNotifier made it a fact nobody could.
"""

from __future__ import annotations

import logging

from openfactory.adapters.notify.base import Level

log = logging.getLogger("openfactory.notify.panel")


class PanelNotifier:
    """Satisfies the Notifier protocol by writing into the panel's message store."""

    def __init__(self, *, project_name: str) -> None:
        self.project_name = project_name

    def notify(self, *, message: str, level: Level = "info",
               about: str = "") -> str | None:
        from openfactory.memory import messages

        # The level travels as a prefix, same vocabulary the Slack notifier renders as an icon —
        # the store keeps one text field and an operator reads urgency off the first character.
        icon = {"info": "•", "action_required": "!", "warning": "!", "error": "✗"}
        landed = messages.say(self.project_name, f"{icon.get(level, '•')} {message}",
                              channel=self.project_name)
        if not landed:
            # the caller treats a notifier as best-effort; the trace is the only evidence left
            log.warning("a %s notification for %s could not be recorded: %s",
                        level, self.project_name, message[:120])
        return None
