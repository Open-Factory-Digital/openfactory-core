"""Which credential a vendor's axis takes — declared per KIND, resolvable from outside.

THE FACT THIS REGISTRY EXISTS TO HOLD. `credentials.forge_token_for(project)` resolved a credential
as: the registry's `token_env` → the vendor's default variable → the deployment's generic pair.
The middle step read a dict literal in core (`_VENDOR_DEFAULT_ENV = {"azure_devops": …, "jira":
…}`), and the last resort everywhere else was one vendor's mint (`github_app_token_from_env`).
Measured 2026-08-24 with a `forge.gitlab` add-on installed the way a stranger installs one: its
projects were handed `OPENFACTORY_BOT_TOKEN` — the deployment's GITHUB credential — because the
dict had no row for it and nothing let the add-on add one; and through `factory.build_runner`'s
exact spelling (`token_provider=None if forge_token_for(p) else prov`) the same add-on received
the GitHub App minter as `token_provider`.

So the per-kind facts move here, into rows the same loader a stranger already uses can extend
(`credential.gitlab = pkg:row` in the `openfactory.adapters` group). A row declares three things,
each optional:

    env       the variable this vendor's credential lives in BY DEFAULT — the registry's
              `token_env` always wins, this answers for a deployment that named nothing
    mint      what THIS DEPLOYMENT can mint for the vendor when a project names nothing —
              a token now, or None when the deployment holds nothing of that vendor's
    provider  the same as a re-minting PROVIDER for a job that outlives one token
    discover  a PERSON's own login on this machine (`gh auth token`) — onboarding's convenience,
              never a job's credential

GITHUB'S ROW IS THE APP MINT. It stays the reference vendor's capability and it stays reachable
through `factory.py` — the composition root, the one core module allowed to know a concrete
adapter — so the seams tests already drive (`factory.github_app_token_from_env`) keep meaning
what they mean. What changes is WHO asks for it: the axis resolves its kind's row, and a kind
with no `mint` gets `None` — "a token from the wrong system is worse than none".

A KIND WITH NO ROW IS NOT AN ERROR HERE, unlike every dispatching registry. A missing row means
"this vendor declares nothing", and the generic pair is what an undeclared vendor has always
had; refusing would turn every pre-seam registry row into a dead deployment.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from openfactory import plugins

log = logging.getLogger("openfactory.credential")


@dataclass(frozen=True)
class CredentialRow:
    """What one vendor declares about its credential. Every field optional — see the module."""

    env: str = ""
    mint: Callable[[], str | None] | None = None
    provider: Callable[[], Callable[[], str] | None] | None = None
    discover: Callable[[], str | None] | None = None


def _github() -> CredentialRow:
    """`env=""` on purpose: GitHub's default IS the generic pair (`OPENFACTORY_FORGE_TOKEN` /
    `OPENFACTORY_TRACKER_TOKEN` / `OPENFACTORY_BOT_TOKEN`), and naming a variable here would say
    otherwise. The mint and the provider are the App trio, reached through the composition root."""

    def mint() -> str | None:
        from openfactory.factory import github_app_token_from_env

        return github_app_token_from_env()

    def provider():
        from openfactory.factory import _bot_token_provider

        return _bot_token_provider()

    def discover() -> str | None:
        from openfactory.adapters.forge.github import discover_token

        return discover_token()

    return CredentialRow(env="", mint=mint, provider=provider, discover=discover)


#: kind → the variable the shipped vendor's credential lives in BY DEFAULT. A names TABLE on
#: purpose — the shape `environ.names_read` recognises — so these two stay RESERVED against an
#: add-on role claiming them as a model variable (`environ.reserved`); a keyword argument to a
#: dataclass is a read the scan cannot see, and a name it cannot see is a secret it can hand out.
#: The rows below are built from this table; an add-on's row names its own variable in its own
#: package, which is that package's to reserve.
SHIPPED_ENV: dict[str, str] = {
    "jira": "JIRA_API_TOKEN",
    "azure_devops": "AZURE_DEVOPS_PAT",
}


def _jira() -> CredentialRow:
    """A static API token; nothing a deployment could mint, nobody's login to discover."""
    return CredentialRow(env=SHIPPED_ENV["jira"])


def _azure_devops() -> CredentialRow:
    """The PAT the shared client reads on its own; no mint (an `az` JWT is the adapter's own
    provider, resolved in the forge registry row) and no login to discover."""
    return CredentialRow(env=SHIPPED_ENV["azure_devops"])


#: kind → the row's builder. A builder rather than a row so a vendor's callables stay lazy: this
#: table is consulted on every credential resolution and must import nothing until asked.
CREDENTIALS: dict[str, Callable[[], CredentialRow]] = {
    "github": _github,
    "jira": _jira,
    "azure_devops": _azure_devops,
}


def credential_row(kind: str) -> CredentialRow | None:
    """The row for `kind` — shipped, else an installed add-on's, else None (declares nothing).

    An add-on's builder must return a `CredentialRow`; anything else is logged and read as no
    declaration, so a broken add-on degrades to the generic pair rather than to a traceback in a
    credential path."""
    key = (kind or "").strip().lower()
    if not key:
        return None
    builder = CREDENTIALS.get(key) or plugins.builder("credential", key, builtin=CREDENTIALS)
    if builder is None:
        return None
    try:
        row = builder()
    except Exception:  # noqa: BLE001 — a row that cannot be built declares nothing
        log.warning("the %s credential row could not be built; treating it as undeclared", key,
                    exc_info=True)
        return None
    if not isinstance(row, CredentialRow):
        log.warning("the %s credential add-on returned %r, not a CredentialRow — ignored", key,
                    type(row).__name__)
        return None
    return row


def known() -> list[str]:
    """Every kind that declares a credential row — shipped plus installed."""
    return plugins.known("credential", CREDENTIALS)
