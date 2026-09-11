"""Who is asking — as an axis, so SSO becomes a row rather than a rewrite (C-26, #55).

THE DEEPEST PROBLEM WAS NEVER THE ABSENCE OF SSO, IT WAS THE ABSENCE OF A SUBJECT. There were two
authorization models and they did not know about each other:

    panel   `OPENFACTORY_PANEL_TOKEN`     a shared password. Everyone holding it is the same person,
    so
                                   *who approved that production release* had no answer at all.
                                   Unset meant fully open.
    Slack   `project.admins`       an allowlist of user ids per project; empty = read-only.

For an enterprise buyer that unanswerable question is audit, and it is the first one their security
review asks. Adding OIDC to the panel first would have implemented identity a second time, in the
one layer where it is most expensive to undo — E6 repeated one floor down. So the axis comes first
and a provider is a row in a registry.

A SUBJECT IS NOT AN ACTOR. `actions.Actor` is what an action runs on behalf of and carries a
DECISION (`admin`); a `Subject` is who a credential turned out to belong to, and carries no
decision at all. Keeping them apart is what stops a provider from being able to grant itself
permission: identity answers *who*, policy answers *may they*, and only the second one is allowed
to say yes.

WHAT EVERY IMPLEMENTATION OWES:

**`identify` returns None rather than guessing.** A credential that cannot be resolved is an
unknown caller, and an unknown caller who gets a plausible identity is worse than one who is
refused: the refusal is visible and the wrong identity is written into an audit line as fact.

**It never raises.** Its callers are request handlers and a chat listener. An identity provider
that throws takes down the door rather than closing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

#: `via` for a caller nobody could identify. NOT an empty string: "" reads as a missing field and
#: gets logged, filtered and compared as one, while this is a positive fact about the request —
#: somebody acted and the deployment cannot say who.
ANONYMOUS = "anonymous"


@dataclass(frozen=True)
class Subject:
    """Who a credential belongs to. Says nothing about what they may do."""

    #: Stable id in the provider's own namespace: a Slack user id, an email, an OIDC `sub`.
    id: str
    #: What to write where a human reads it. Falls back to `id` when the provider has no name.
    display: str = ""
    #: Which provider resolved this — `local`, `slack`, `oidc`. `ANONYMOUS` when none could.
    via: str = ""
    #: Group or role names the provider asserts. Empty for providers that carry no groups; policy
    #: must work without them, because the first provider has none and the buyer's has dozens.
    groups: tuple[str, ...] = field(default_factory=tuple)

    @property
    def known(self) -> bool:
        """Whether anybody was actually identified.

        A named property rather than `bool(subject.id)` at each call site: "an anonymous caller"
        is the single most important condition in this module and it must be spelled the same way
        everywhere, or one door checks it and another does not."""
        return bool(self.id) and self.via != ANONYMOUS


#: The three doors the panel mounts for a provider that has a login (#33) — the OIDC row's
#: redirect, the local row's form — and the cookie the panel already reads. Named HERE, once,
#: because the page, the gate's 401 and the routes must agree on the spelling, and because
#: `local` and `oidc` both need them and neither may import the other.
LOGIN_PATH = "/auth/login"
CALLBACK_PATH = "/auth/callback"
LOGOUT_PATH = "/auth/logout"
REGISTER_PATH = "/auth/register"
TOKEN_COOKIE = "openfactory_token"

#: What a request carries when the deployment let it through without knowing who it was — the
#: legacy shared-token panel, and a local `openfactory` invocation. Deliberately a real value
#: rather than None, so the audit line says "anonymous" instead of having no field.
UNKNOWN = Subject(id="", display="somebody with the panel token", via=ANONYMOUS)


@runtime_checkable
class IdentityProvider(Protocol):
    """One way of turning a credential into a person."""

    def identify(self, *, credential: str, via: str = "") -> Subject | None:
        """Who this credential belongs to, or None when it belongs to nobody this can name.

        `credential` is whatever the transport carries: a bearer token, a signed assertion, a chat
        user id. `via` is the transport's own hint and providers may ignore it.

        NEVER RAISES — see the module docstring."""
        ...
