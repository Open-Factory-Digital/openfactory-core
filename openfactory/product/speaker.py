"""Who is speaking to the product role, and in which role — a person, per product (#266 slice 4).

THE ROLE ANSWERED EVERYONE AS NOBODY. `ProductModule.answer` took no speaker; the only trace of
one was the transcript's `"{actor}: text"`, a raw id, and the role's prompt had no notion of who it
was talking to. In a group room ten people are ten different conversations with one product, and a
client asking what a requirement promises, an admin whose yes records it and an engineer asking how
the code does it today are three different audiences for the same sentence (ADR-0051 decision 8).

THREE ROLES, ONE PER PERSON PER PRODUCT, AND CLIENT IS THE DEFAULT. Resolved from the registry's
`product:` section and nothing else — the operator's declaration, never what a message claims:

    engineer        `product.engineers` lists them: the people who build the product
    admin           `product.admins` lets them confirm what is recorded (`may_act`, the product's
                    allowlist — groups included)
    client          everybody else, and anybody the deployment could not identify

An engineer who is also on the admin list is an engineer who may confirm: the role says how the
role speaks to them, `approver` says whether their yes records anything. The two are kept apart on
purpose — the prompt is shaped by the first, and every write is still gated by `may_act` alone.

NOTHING HERE IS PERMISSION. `approver` is `may_act`'s answer carried to the prompt, so the role
knows whose confirmation can count; the gates that decide it ask `may_act` themselves.

`sealed` is how a person is carried where it must be compared and never read back: a staged
proposal's key, a decision's scope. A digest names nobody, so a key that travels to another
conversation, a panel list or a button carries no name.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

CLIENT, ADMIN, ENGINEER = "client", "admin", "engineer"
ROLES = (CLIENT, ADMIN, ENGINEER)


@dataclass(frozen=True)
class Person:
    """One person speaking to the product role: who, their role in this product, and whether their
    confirmation can record anything here."""

    id: str
    role: str = CLIENT
    approver: bool = False


def person(project, speaker: str, *, via: str = "api") -> Person:
    """`speaker` as a person of this product. Never raises: a registry section that cannot be read
    makes a client, which is the role with the fewest assumptions in it."""
    who = str(speaker or "").strip()
    if not who:
        return Person(id="")
    from openfactory.product.module import may_act

    try:
        approver = bool(may_act(project, who, via=via))
    except Exception:  # noqa: BLE001 — a client is the safe reading of an unreadable allowlist
        approver = False
    cfg = getattr(project, "product", None)
    engineers = {str(e).strip() for e in (getattr(cfg, "engineers", None) or ())}
    if who in engineers:
        return Person(id=who, role=ENGINEER, approver=approver)
    return Person(id=who, role=ADMIN if approver else CLIENT, approver=approver)


def sealed(value: str) -> str:
    """`value` as something that can be compared and never read — "" for nothing."""
    value = str(value or "").strip()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else ""


#: What each role means to the role's answer, in the prompt's own language (the instructions are
#: English; the client's language rules are the voice's, and still hold for every role).
_SAID = {
    CLIENT: ("a client of this product — someone it is built for, or who asked for part of it. "
             "Speak in the business's terms, as the rules above say."),
    ADMIN: ("a product admin — one of the people this product's configuration lets confirm what "
            "is recorded. What they ask for, they can confirm themselves; speak in the business's "
            "terms, as the rules above say."),
    ENGINEER: ("an engineer who builds this product. They can take how it works today in more "
               "technical depth — which part of the product does it, and why — but the rules "
               "above on what reaches the conversation still hold: others may read it too."),
}


def render(speaker: Person | None) -> str:
    """The prompt block that says who wrote the message being answered — or "" for nobody known.

    VOLATILE, so the caller puts it after everything a cache can keep. It names the speaker, who is
    in the conversation already; it names nobody else, and it grants nothing."""
    if speaker is None or not speaker.id:
        return ""
    said = _SAID.get(speaker.role, _SAID[CLIENT])
    if speaker.approver and speaker.role != ADMIN:
        said += " Their confirmation can record what is staged."
    elif not speaker.approver:
        said += (" Their confirmation alone does not record anything here; say so rather than "
                 "promising a write.")
    return f"## Who is speaking\n{speaker.id} — {said}"


__all__ = ["ADMIN", "CLIENT", "ENGINEER", "ROLES", "Person", "person", "render", "sealed"]
