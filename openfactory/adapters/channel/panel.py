"""The panel as a conversation channel — the second implementation of this axis (C-25).

WHY IT IS THE ONE WORTH BUILDING. `ChannelAdapter` has had exactly one implementation since it was
written, and a port with one implementation is a hypothesis, not a seam: nothing has ever forced
the contract to be honest about what a channel *is* as opposed to what Slack does. This provider
needs no third-party account, so it is also the only one whose behaviour can be proven in a test
suite rather than in somebody's workspace.

AND WITHOUT IT, A PROMISE THIS PLATFORM MAKES IS FALSE. "Never a silent wait — every stall either
self-heals or asks a human" was true only for deployments that bought Slack. Everyone else got the
question written, delivered to `say`, and dropped: not a quieter factory, a silent one.

PULL, NOT PUSH — and that is the whole shape of the difference. Slack owns a socket and delivers to
a reader; the panel is asked. So `say` records, `start_listeners` opens nothing, and a person is
"notified" by looking. That is a real limitation and it is stated rather than papered over: an
operator who never opens the panel is not reached, which is why a deployment that needs to reach
somebody who is not looking still wants a push channel.

THIS PROVIDER CAN CONFIRM. `ask_to_confirm` is the capability that made `ConfirmingChannel` a
separate protocol, and a browser button is exactly as unambiguous as a Slack one: it carries who
clicked, it names what was clicked, and it cannot be a sentence about something else.
"""

from __future__ import annotations

import logging

from openfactory.contracts.project import Project
from openfactory.memory import messages

log = logging.getLogger("openfactory.channel.panel")


class PanelChannel:
    """One deployment's conversations, carried by the panel that is already there.

    Implements `ChannelAdapter`, and `ConfirmingChannel` as well. No inheritance: the protocols are
    runtime-checkable and structural, and satisfying them by SHAPE is the point of the exercise —
    a base class would let this pass by ancestry rather than by contract.
    """

    def say(self, *, project: Project, channel: str, text: str) -> bool:
        """Record a message for this project's panel. Returns whether it landed, never raises.

        `channel` is carried verbatim rather than interpreted. The panel groups by project, but the
        core's callers pass whatever their own configuration names, and a provider that silently
        reinterprets that value is a provider that posts somewhere nobody expects."""
        name = _name(project)
        if not name:
            log.warning("OPENFACTORY_PANEL_SAY_NO_PROJECT a message was produced for a "
                        "project with "
                        ""
                        "no "
                        "name and could not be filed: %s", text[:120])
            return False
        try:
            return messages.say(name, text, channel=channel or name)
        except Exception as exc:  # noqa: BLE001 — see ChannelAdapter: `say` never raises
            log.error("could not record a message for %s (%s) — it was produced and nobody will "
                      "see it", name, exc)
            return False

    def mention(self, person: str, **_kw) -> str:
        """The person's plain name.

        THE CONTRACT'S OWN RULE, and the panel is the case that proves it is not a Slack detail: a
        browser page has no notification namespace at all, so there is nothing here that COULD be
        guessed. A wrong mention makes somebody read an irrelevant message and leaves the right
        person never asked, while the thread looks answered."""
        return str(person or "").strip()

    def start_listeners(self) -> None:
        """Nothing to open.

        NOT AN EMPTY IMPLEMENTATION — a stated one. Slack opens a socket per project and holds it;
        the panel is pull, so its "listener" is the browser asking `/api/messages/{project}`, and
        the answers arrive through the API's own routes. A provider that needed a background
        connection here would be one that could not run in a request/response deployment at all.
        """
        log.debug("the panel channel opens no connections — it is asked, it does not listen")

    def ask_to_confirm(self, *, project: Project, channel: str, thread: str, text: str, token: str,
                       approve: str, reject: str) -> bool:
        """Post a question with two unambiguous answers, and return whether it was posted.

        `thread` is accepted and unused: the panel has no threads, and refusing the parameter would
        make this provider unable to satisfy the protocol the core actually calls.

        Returns False WITHOUT RECORDING ANYTHING when it could not be filed, which is the contract's
        signal for "the caller owns the prose fallback" — so a question is never posted twice and
        never lost between the two paths."""
        name = _name(project)
        if not (name and token):
            log.warning("OPENFACTORY_PANEL_ASK_INCOMPLETE a confirmation needs a project and a "
                        "token; "
                        "got project=%r token=%r", name, token)
            return False
        try:
            return messages.ask(name, text, token=token, approve=approve, reject=reject,
                                channel=channel or name)
        except Exception as exc:  # noqa: BLE001 — the affordance is optional; the proposal is not
            log.warning("could not offer a confirmation on the panel for %s (%s)", name, exc)
            return False


def _name(project) -> str:
    return str(getattr(project, "name", "") or "").strip()
