"""May this person do this — decided once, in the Core (C-26, #55).

AUTHORIZATION LIVING IN THE TRANSPORT PRODUCES ONE AUTHORIZATION MODEL PER TRANSPORT. There were
three, and they did not know about each other:

    Slack   `project.admins`          an allowlist per project; empty = read-only for everyone
    product `project.product.admins`  a second allowlist, for the gestures that WRITE
    panel   `OPENFACTORY_PANEL_TOKEN`        a shared password — everyone holding it was the same
    person

The failure is not that the three rules differ; two of them differing is legitimate, because the
tech-lead's floor and the client's requirements are different things to be trusted with. The
failure is that the rules lived where the requests arrive, so answering "who may do this" meant
reading three front ends, and adding a fourth surface meant inventing a fourth answer.

WHAT MOVED AND WHAT DID NOT. The DECISION moved here. The DATA did not: the allowlists still live
on the project, because who may act on a project is that project's business and always was. This
module is where the two allowlists are read and the same question is answered the same way for
every door.

IDENTITY ANSWERS *WHO*, THIS ANSWERS *MAY THEY*, and the split is load-bearing. An identity
provider that could also grant permission would be a provider that can promote its own callers —
which is exactly what "the panel token means admin" was.

EMPTY MEANS NOBODY, everywhere. It is the safe default and it is also the honest one: a deployment
that has not said who may act has not said it, and guessing "then everyone" is how a factory ends
up acting on the word of whoever found the URL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from openfactory.identity.base import Subject

log = logging.getLogger("openfactory.policy")

#: The floor: resume, skip, ack, enable, the release gate — everything the tech-lead does.
FACTORY = "factory"

#: The requirements: accept, drop, close, align, break down — everything the product role writes.
PRODUCT = "product"

SCOPES = (FACTORY, PRODUCT)


@dataclass(frozen=True)
class Decision:
    """Whether they may, and why — because a refusal a person cannot act on is a dead end.

    The reason is for a LOG and for a sentence, never for a client to branch on: the front ends
    map `allowed`, and prose that becomes a protocol is prose nobody can improve."""

    allowed: bool
    why: str = ""

    def __bool__(self) -> bool:
        return self.allowed


def may(subject: Subject, *, project, scope: str = FACTORY) -> Decision:
    """Whether `subject` may act on `project` within `scope`.

    An unknown scope is REFUSED rather than treated as the default. A typo would otherwise widen
    permission silently, which is the one direction this module must never fail in."""
    if scope not in SCOPES:
        log.error("OPENFACTORY_AUTHZ_UNKNOWN_SCOPE %r — refusing; known scopes are "
                  "%s", scope, SCOPES)
        return Decision(False, f"unknown authorization scope {scope!r}")

    if subject is None or not subject.known:
        return Decision(False, "the deployment could not tell who is asking")

    allowed, why_not = _allowlist(project, scope)
    if why_not:
        return Decision(False, why_not)
    if subject.id in allowed:
        return Decision(True)
    # GROUPS ARE CHECKED TOO, and they cost nothing today: the local provider asserts none, so this
    # is dead for it. It is here because the moment an OIDC provider exists the allowlist stops
    # being a list of people and becomes a list of groups, and a policy that could only compare
    # ids would have to be rewritten at exactly the point somebody is depending on it.
    if any(g in allowed for g in subject.groups):
        return Decision(True)
    return Decision(False, f"{subject.id} is not on this project's {scope} allowlist")


def is_admin(subject: Subject, project, *, scope: str = FACTORY) -> bool:
    """`may(...)` as a plain bool, for the callers that only render a yes or a no."""
    return bool(may(subject, project=project, scope=scope))


def _allowlist(project, scope: str) -> tuple[frozenset[str], str]:
    """`(who may act, "")` or `(∅, why nobody can)`.

    The two are separated because they are different answers to a person: "you are not on the
    list" is actionable by an admin, and "this project has no product role enabled" is actionable
    by whoever configured it. Collapsing both into False is how a support conversation starts."""
    if scope == PRODUCT:
        cfg = getattr(project, "product", None)
        if cfg is None or not getattr(cfg, "enabled", True):
            return frozenset(), "the product role is not enabled on this project"
        return frozenset(getattr(cfg, "admins", None) or ()), ""
    return frozenset(getattr(project, "admins", None) or ()), ""
