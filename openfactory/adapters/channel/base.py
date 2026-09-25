"""What a CONVERSATION CHANNEL is, independently of who carries it.

The product owner's call, 2026-07-28: Telegram comes later because Slack is what a professional
client expects — but the seam has to exist now, or "later" means rewriting the worker.

THE SURFACE IS DELIBERATELY THREE METHODS. Not because a channel does only three things, but
because that is all the CORE ever asked of one: five call sites across the worker, needing "post
this", "how do I address this person", and "start listening". Everything else Slack does — threads,
Socket Mode, mrkdwn conversion, pending confirmations, the whole 1,500-line conversational layer —
is that provider's business and stays inside it.

A protocol built from what a provider CAN do would be a Slack API in disguise, and Telegram would
have to fake half of it. Built from what the core NEEDS, Telegram implements three methods.

WHAT EVERY IMPLEMENTATION OWES:

**`say` returns whether it landed, and never raises.** Its callers are scheduled rounds and
activities; an exception there turns one undelivered message into a retry storm, and a silent
failure turns it into an agent that looks like it has nothing to say.

**`mention` degrades to a plain name rather than guessing.** A wrong mention is worse than none: it
makes somebody read an irrelevant message AND leaves the right person never asked, while the thread
looks answered. Providers differ here — Slack needs a workspace lookup, Telegram has @usernames —
so the rule lives in the contract, not in one adapter.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from openfactory.contracts.project import Project


@runtime_checkable
class ChannelAdapter(Protocol):
    """One provider carrying one deployment's conversations."""

    def say(self, *, project: Project, channel: str, text: str) -> bool:
        """Post a message outside any conversation (a scheduled round, an activity).

        Returns whether it was delivered. NEVER raises — see the module docstring."""
        ...

    def mention(self, person: str, **kw) -> str:
        """How to address `person` (a forge login) so they are actually notified.

        Falls back to the plain name when the person cannot be identified with confidence."""
        ...

    def start_listeners(self) -> None:
        """Begin receiving messages for every project this provider serves.

        THE PROVIDER OWNS WHAT IT OPENS. An earlier signature returned "whatever must be held to
        keep the connections alive" and the worker parked it in a `# noqa: F841` variable — live
        socket objects crossing a port, which quietly rules out ever running this provider out of
        process (`docs/core/07-extensibility.md`). Nothing is gained by it either: the caller has
        to keep the ADAPTER alive regardless, and an adapter that holds its own connections is the
        same lifetime with one fewer thing to remember.

        No parameters: the first draft advertised a `registry` argument the only implementation's
        underlying function does not accept, a TypeError armed to fire the day somebody used the
        documented surface. Providers read their configuration the same way everything else does —
        from the deployment registry themselves."""
        ...


@runtime_checkable
class PeopleOfAChannel(Protocol):
    """WHO A CHANNEL'S USER IS, as a person of the platform — the add-on's answer, and the one place
    it gives it (#266 slice 6, ADR-0051 D1 and D16).

    THE CORE AUTHORISES PEOPLE, NEVER A VENDOR'S USER IDS. `product.admins` and `admins` list the
    ids the platform's identity provider knows people by — a panel credential, an invitation, an
    SSO login — and every gate compares a speaker with them (`product/module.py::may_act`). A chat
    vendor identifies the same people by ids of its own, which the core never sees and must never
    compare: mapping one to the other is the add-on's job, because only the add-on can read its
    vendor's directory — a verified email, a profile field, its own configuration.

    A PORT RATHER THAN A REGISTRY SECTION, on purpose. A table of vendor ids in the registry would
    put the vendor's shape back into the core's configuration, and would fix one way of mapping for
    every vendor; the port leaves the vendor's ids entirely inside the add-on and lets it answer
    however its vendor can. The core calls it at the chat adapter's door (`product/channel.py::
    handle` and `confirm_by_click`), so a vendor's id is turned into a person before anything is
    recorded, staged or authorised.

    A SEPARATE PROTOCOL, like `ConfirmingChannel`: most channels (the panel) identify people
    through the platform already and need none of it. The object that implements it is usually the
    add-on's channel adapter, but anything with the method will do.
    """

    def person_of(self, user: str, *, project: Project) -> str:
        """The platform's id for the person `user` is on this channel, for `project` — or "" when
        the add-on cannot say WITH CONFIDENCE.

        "" is safe and exact: the user is spoken to as a guest, told apart from every other guest,
        who may write nothing (`product/speaker.py::GUEST`). A wrong person is not: it would let one
        vendor user confirm with another person's authority. Never raises — a lookup that fails is
        "" (the core also treats a raise as "", and logs it)."""
        ...


@runtime_checkable
class ConfirmingChannel(Protocol):
    """A channel that can ask for approval in a way that CANNOT be misread.

    A SEPARATE PROTOCOL, ON PURPOSE. The core surface above is three methods because that is what
    the core needs of every provider; this is a capability only some providers have, and folding it
    into `ChannelAdapter` would make every existing adapter and every test double fail an
    `isinstance` check for something they legitimately cannot do. Callers ask
    `isinstance(channel, ConfirmingChannel)` and degrade when the answer is no.

    WHY THE CORE NEEDS IT AT ALL — the justification the three-method rule demands. On 2026-07-30 an
    owner approved a staged requirement with "Sim — registre." The gate matched words, did not
    recognise it, wrote nothing, and the agent then said it had been registered. Reading the reply
    with a model fixed the recognition, but reading is still INTERPRETATION standing between a
    person and an irreversible act taken in their name. A click is not interpreted: it carries the
    clicker's identity, it names exactly what was clicked, and it cannot be a sentence about
    something else. For the one decision in this platform that spends money and writes in somebody's
    name, that difference is the requirement — not a Slack feature.
    """

    def ask_to_confirm(self, *, project: Project, channel: str, thread: str, text: str, token: str,
                       approve: str, reject: str) -> bool:
        """Post `text` together with an unambiguous way to approve or reject it.

        `token` identifies WHAT is being confirmed and comes back with the click, so the caller can
        verify the person approved the thing they were shown rather than whatever is staged now.
        `approve` / `reject` are the button labels, already in the reader's language.

        Returns True when an interactive request was posted and the caller may rely on a click
        arriving. Returns False WITHOUT POSTING ANYTHING when the provider has no interactive
        surface — the caller owns the prose fallback, so nothing is ever posted twice. Never raises:
        a provider hiccup must degrade to the fallback, not lose the proposal.
        """
        ...
