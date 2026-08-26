"""Identity as an axis (ADR-0002's shape, applied to *who is asking*) — C-26, #55."""

from openfactory.identity.base import ANONYMOUS, UNKNOWN, IdentityProvider, Subject
from openfactory.identity.registry import IDENTITIES, build_identity, identity_kind

__all__ = [
    "ANONYMOUS",
    "IDENTITIES",
    "UNKNOWN",
    "IdentityProvider",
    "Subject",
    "build_identity",
    "identity_kind",
]
