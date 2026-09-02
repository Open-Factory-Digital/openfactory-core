"""Which identity provider a deployment trusts — from config, never from an import (C-26, #55).

TWO BUILT-IN ROWS, and the rows are what matter: `local` (tokens the deployment configured for
itself) and `oidc` (#33 — any OpenID Connect provider, configured, because OIDC is a standard and
not a vendor). Anything else — SAML, a proprietary assertion — is one module each, joining through
the `openfactory.adapters` entry-point group as `identity.<kind>`, never a second identity
implementation inside whichever front end needed it first. That was the whole argument for
building the axis before the provider — adding SSO first means implementing identity twice, in the
layer where it is most expensive to undo. Until 2026-08-26 this module said the rows were added
HERE, which contradicted the doctrine one directory up; until 2026-09-02 it said OIDC was an
add-on, and no add-on existed anywhere — "ready for SSO" meant a socket, not a plug.

RAISES ON AN UNKNOWN KIND. The failure mode of this axis is letting the wrong person in, so a
deployment that names a provider this build does not have must fail loudly at startup rather than
fall back to something more permissive. THE SAME RULE HOLDS FOR WHAT AN ADD-ON HANDS BACK: an
object that is not an `IdentityProvider` is refused by name, not used — the panel gate would call
`identify` on it and an AttributeError there is a door that failed open or closed by accident.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from openfactory import plugins

DEFAULT_KIND = "local"

#: The entry-point axis name: `identity.<kind>`.
AXIS = "identity"

#: Where a deployment names its provider. An env var rather than a per-project field on purpose:
#: identity is a property of the DEPLOYMENT, and one project trusting a different provider from
#: its neighbour is a configuration nobody could reason about.
KIND_ENV = "OPENFACTORY_IDENTITY"


def _local(**_kw):
    from openfactory.identity.local import LocalIdentity

    return LocalIdentity()


def _oidc(**_kw):
    from openfactory.identity.oidc import OidcIdentity

    provider = OidcIdentity()
    # REFUSED AT STARTUP, BY NAME. A row that names a provider and not its issuer is a door that
    # would answer "nobody" to every credential — closed, but closed for a reason nothing said.
    # The registry's contract is that a kind this build cannot run raises here, and a kind it
    # cannot CONFIGURE is the same fact one variable later.
    why = provider.misconfiguration()
    if why:
        raise ValueError(why)
    return provider


#: kind → builder. SAML and the like plug in through the entry-point group; a built-in row wins a
#: collision.
IDENTITIES: dict[str, Callable[..., object]] = {
    "local": _local,
    "oidc": _oidc,
}


def identity_kind(env: dict[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    return (str(source.get(KIND_ENV, "") or "").strip().lower() or DEFAULT_KIND)


def build_identity(env: dict[str, str] | None = None):
    """The deployment's identity provider. Raises on an unknown kind — see the module docstring.
    A built-in row wins; an add-on's row (`identity.<kind>` entry point) fills the rest."""
    kind = identity_kind(env)
    builder = IDENTITIES.get(kind) or plugins.builder(AXIS, kind, builtin=IDENTITIES)
    if builder is None:
        known = ", ".join(plugins.known(AXIS, IDENTITIES))
        raise ValueError(
            f"unknown identity provider {kind!r} — known: {known}. "
            f"Refusing to fall back: the failure mode of this axis is letting the wrong person in."
        )
    provider = builder()
    from openfactory.identity.base import IdentityProvider

    if not isinstance(provider, IdentityProvider):
        raise TypeError(
            f"the {kind!r} identity provider does not satisfy IdentityProvider (no `identify`): "
            f"got {type(provider).__name__}. Refusing to use it: the panel gate dispatches through "
            f"`identify`, and a provider without one fails at the door instead of at startup."
        )
    return provider
