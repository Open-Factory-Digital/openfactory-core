"""The identity provider a deployment has before it buys one (C-26, #55).

PER-PERSON TOKENS, FROM THE DEPLOYMENT'S OWN CONFIGURATION. `OPENFACTORY_PANEL_TOKENS` names
one secret
per person:

    OPENFACTORY_PANEL_TOKENS="s3cret-a:alice:Alice Ferreira,s3cret-b:bob:Bob Nakamura"

That is not SSO and does not pretend to be. What it does is make the panel able to answer *who
approved that production release* using the machinery a deployment already has — an environment
variable delivered from SSM — instead of waiting for an identity provider to be procured.

THE LEGACY SHARED TOKEN STILL WORKS, AND IS REPORTED AS WHAT IT IS. `OPENFACTORY_PANEL_TOKEN`
remains
valid, because breaking every existing deployment's panel to close an audit gap would close it by
locking everyone out. But a caller who presents it resolves to `UNKNOWN` rather than to a person,
so the gap appears in the audit line as the word `anonymous` instead of being invisible. A hole
you can grep for is a different thing from a hole nobody can see.

NO ORDERING AMBIGUITY: the per-person map is consulted first. A deployment that sets both is one
mid-migration, and during that window a person with their own token must be recognised as
themselves rather than as whoever also knows the shared one.
"""

from __future__ import annotations

import hmac
import logging
import os

from openfactory.identity.base import UNKNOWN, Subject

log = logging.getLogger("openfactory.identity")

#: `token:id:display` rows, comma-separated. The display name is optional.
PEOPLE_ENV = "OPENFACTORY_PANEL_TOKENS"

#: The one shared password this replaces. Still honoured; see the module docstring.
SHARED_ENV = "OPENFACTORY_PANEL_TOKEN"

#: THE SAME TWO SHAPES, FOR A CREDENTIAL THAT IS NOT AN OPERATOR'S (#98). A business analyst who
#: writes requirements is not running the floor, and until these existed the only way to let them
#: near the product role was to hand over the panel token — which also hands over merge and skip.
#: A subject resolved from one of these carries the `product` group, and the action layer turns
#: that into `Actor.scopes`; every row outside that area is then refused by name.
PRODUCT_PEOPLE_ENV = "OPENFACTORY_PRODUCT_TOKENS"
PRODUCT_SHARED_ENV = "OPENFACTORY_PRODUCT_TOKEN"

#: The group name a product credential asserts. One string, defined once, because the identity
#: provider and the action layer have to agree on it and a typo would silently scope somebody to
#: an area that does not exist.
PRODUCT_GROUP = "product"


class LocalIdentity:
    """Credentials this deployment configured for itself, with no provider anywhere."""

    def __init__(self, *, env: dict[str, str] | None = None) -> None:
        #: Read at construction, not per call: a provider whose answers change between two
        #: requests of the same session is a provider that can grant and revoke silently.
        self._env = dict(env if env is not None else os.environ)

    def identify(self, *, credential: str, via: str = "") -> Subject | None:
        """Who holds this token, and what they are scoped to. None when nobody does.

        NARROW BEFORE BROAD, WITHIN EACH TIER. The per-person maps are still consulted before the
        shared ones, for the reason the module docstring gives. What is new is the order inside a
        tier: the product map is read first, so a token that a mistake put in BOTH resolves to the
        SMALLER authority. Getting this backwards would mean a copy-paste could silently widen a
        business analyst's credential into an operator's, and the direction a configuration error
        fails in is the only thing that makes it survivable."""
        try:
            token = str(credential or "").strip()
            if not token:
                return None
            for person in _people(self._env.get(PRODUCT_PEOPLE_ENV, "")):
                if hmac.compare_digest(token, person.token):
                    return Subject(id=person.id, display=person.display or person.id,
                                   via="local", groups=(PRODUCT_GROUP,))
            for person in _people(self._env.get(PEOPLE_ENV, "")):
                # CONSTANT TIME, because this compares a secret. `==` on a token leaks its prefix
                # to anyone who can measure, and the panel is reachable from a browser.
                if hmac.compare_digest(token, person.token):
                    return Subject(id=person.id, display=person.display or person.id, via="local")
            product_shared = str(self._env.get(PRODUCT_SHARED_ENV, "") or "")
            if product_shared and hmac.compare_digest(token, product_shared):
                log.info("OPENFACTORY_IDENTITY_ANONYMOUS a caller presented the shared PRODUCT "
                         "token; "
                         "set %s to record who is acting", PRODUCT_PEOPLE_ENV)
                # Anonymous in the audit line, like its floor equivalent — but still SCOPED, which
                # is a different question from being named. Returning `UNKNOWN` here would hand a
                # product credential the floor.
                return Subject(id="", display="somebody with the product token",
                               via=UNKNOWN.via, groups=(PRODUCT_GROUP,))
            shared = str(self._env.get(SHARED_ENV, "") or "")
            if shared and hmac.compare_digest(token, shared):
                # THE AUDIT GAP, SAID OUT LOUD ONCE PER USE. This is the state the card calls "a
                # shared password, not an identity", and it stays reachable on purpose — the fix
                # for it is configuration, and locking a deployment out is not a fix.
                log.info("OPENFACTORY_IDENTITY_ANONYMOUS a caller presented the shared "
                         "panel token; "
                         ""
                         ""
                         "set %s to record who is acting", PEOPLE_ENV)
                return UNKNOWN
            return None
        except Exception as exc:  # noqa: BLE001 — an identity provider never takes the door down
            log.warning("the local identity provider could not read a credential (%s)", exc)
            return None

    def open_to_everyone(self) -> bool:
        """Whether this deployment configured NO credential at all.

        A SEPARATE QUESTION FROM `identify`, and it has to be, because the two answers point
        opposite ways: with nothing configured every request is unauthenticated *and permitted*
        (the local-development default this platform has always had), while with something
        configured an unresolvable credential must be refused. Folding them together is how "unset
        means open" becomes "unknown means open".

        THE PRODUCT VARIABLES COUNT AS CONFIGURATION. They have to: a deployment that issued only
        product credentials — the exact shape of "a BA needs to write requirements and nobody else
        needs the panel yet" — would otherwise answer "nothing is configured" and serve every read
        endpoint to the internet unauthenticated, which is the one direction this gate must never
        fail in and the direction it already failed in once (C-26)."""
        return not any(self._env.get(name, "").strip() for name in
                       (PEOPLE_ENV, SHARED_ENV, PRODUCT_PEOPLE_ENV, PRODUCT_SHARED_ENV))


class _Person:
    __slots__ = ("token", "id", "display")

    def __init__(self, token: str, ident: str, display: str) -> None:
        self.token, self.id, self.display = token, ident, display


def _people(raw: str) -> list[_Person]:
    """`token:id:display` rows → people. A malformed row is SKIPPED AND LOGGED, never guessed at:
    a half-parsed row would hand somebody an identity that is not theirs."""
    out: list[_Person] = []
    for row in str(raw or "").split(","):
        row = row.strip()
        if not row:
            continue
        parts = [p.strip() for p in row.split(":")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            log.warning("OPENFACTORY_IDENTITY_BAD_ROW ignoring a %s entry that is not "
                        "'token:id[:display]' — that person cannot be identified", PEOPLE_ENV)
            continue
        out.append(_Person(parts[0], parts[1], ":".join(parts[2:]).strip()))
    return out
