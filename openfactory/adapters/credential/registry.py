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
    source    THE VENDOR'S OWN RESOLUTION, for a vendor whose adapters resolve their credential
              themselves: which source answers for an axis with these options, and a provider
              read at each use — the stored secret, a person's CLI login, or the workload's own
              identity (#373). Everything that asks "does this deployment hold a credential" asks
              it, so the doctor and the adapter answer from ONE function

and what to SAY when the credential is the problem — `when_missing`, `when_refused` — because a
remedy is the vendor's own words (its variable, its login, its console, its recipe) and the
doctor that spelled them carried a branch per vendor and GitHub's for everybody else.

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

#: What an axis declares, in its `options`, to take the credential the WORKLOAD already has — the
#: identity the platform issued to the machine or pod it runs on (a cloud VM's managed identity),
#: with nothing stored and nothing to rotate (#373). A declaration and never a guess: nothing asks
#: a metadata endpoint because one happens to answer, and an axis that declares nothing resolves
#: exactly as it did before this existed.
IDENTITY_OPTION = "identity"
#: The one value `identity` may take.
WORKLOAD = "workload"
#: Which identity, when the machine holds more than one — a user-assigned identity's client id.
#: Empty means the one the platform assigned to the machine itself.
IDENTITY_CLIENT_ID_OPTION = "identity_client_id"

#: The `source` identity of each kind of credential (`CredentialRow.source`), as the doctor names
#: them. A stored secret is `env:<NAME>`; a person's CLI login `login:<cli>`; the workload's own
#: identity `identity:workload`.
WORKLOAD_SOURCE = f"identity:{WORKLOAD}"


def declared_identity(options) -> tuple[bool, str]:
    """`(declared, problem)` for an axis's `options`: whether it declares the workload's own
    identity, and — when it declares something no resolution can use — why, in one sentence.

    `(False, "")` is the axis that declares nothing, which is every axis written before #373.
    A PROBLEM IS NEVER A FALLBACK: an axis that declared an identity and cannot have it resolves
    no credential at all, rather than quietly taking a stored secret or a login nobody chose."""
    options = options or {}
    raw = str(options.get(IDENTITY_OPTION) or "").strip()
    if not raw:
        if str(options.get(IDENTITY_CLIENT_ID_OPTION) or "").strip():
            return False, (f"`{IDENTITY_CLIENT_ID_OPTION}` is set with no `{IDENTITY_OPTION}: "
                           f"{WORKLOAD}` beside it — say which identity to use, or remove it")
        return False, ""
    if raw.lower() != WORKLOAD:
        return False, (f"`{IDENTITY_OPTION}: {raw}` names no credential this deployment can use "
                       f"— the one that can be declared is `{IDENTITY_OPTION}: {WORKLOAD}`, the "
                       f"identity the platform gave the machine the worker runs on")
    if str(options.get("token_env") or "").strip():
        return False, (f"it declares both `token_env` and `{IDENTITY_OPTION}: {WORKLOAD}` — an "
                       f"axis has one credential; remove the one it should not use")
    return True, ""


@dataclass(frozen=True)
class CredentialRow:
    """What one vendor declares about its credential. Every field optional — see the module."""

    env: str = ""
    mint: Callable[[], str | None] | None = None
    provider: Callable[[], Callable[[], str] | None] | None = None
    discover: Callable[[], str | None] | None = None

    #: `source(options) -> (identity, provider)` — see the module. `identity` is `env:<NAME>`,
    #: `login:<cli>` or `identity:workload`; `provider` answers the token at each use, or None
    #: when that source holds nothing right now. `("", None)` when no source can answer.
    #:
    #: A VENDOR THAT DECLARES THIS IS ANSWERED BY IT ALONE. `forge_token_for` used to walk the
    #: registry's variable, the vendor's variable, then the deployment's generic pair — and the
    #: Azure adapters, which resolve their own credential and never take a caller's, walked the
    #: first two and then the `az` login. Measured 2026-09-28: on a worker holding only
    #: `OPENFACTORY_BOT_TOKEN`, the doctor counted that GitHub token as an Azure project's forge
    #: credential and reported the forge reachable, while the adapter had none. One function, asked
    #: by both, is what makes that disagreement impossible rather than fixed once more.
    source: Callable[[dict], tuple[str, Callable[[], str | None] | None]] | None = None

    #: Whether this vendor needs a credential AT ALL (ADR-0049 D1).
    #:
    #: THE MODEL COULD NOT SAY "NONE" AND THE SILENCE MEANT SOMETHING ELSE. Every other field is
    #: optional and `env=""` already carries a meaning — GitHub declares it because GitHub's
    #: default IS the generic pair — so a row that simply named no variable was indistinguishable
    #: from GitHub's, and a project on a vendor that needs nothing would be handed this
    #: deployment's `OPENFACTORY_BOT_TOKEN` on a machine that also runs a GitHub project. A
    #: credential that looks configured and belongs to somebody else is the most expensive shape
    #: a configuration error takes.
    #:
    #: `True` by default, so no existing row changes meaning and no add-on has to be edited.
    needs: bool = True

    #: WHAT TO DO when this vendor's credential is MISSING, and when the vendor REFUSED it — the
    #: remedy `openfactory doctor` prints, read through `plugins.sentence`.
    #:
    #: ON THE ROW BECAUSE THE DOCTOR CHOSE THEM BY KIND, and chose wrong for everyone it had no
    #: branch for. Measured 2026-09-19 with a stranger's row declaring `env="ACME_TOKEN"`: its
    #: operator was told to set `OPENFACTORY_BOT_TOKEN` or create a GitHub App; and the remedy for
    #: a REFUSED credential was GitHub's for every vendor, so an Azure DevOps PAT that had expired
    #: read "a GitHub App: grant it access to this repository". #170 moved the presence question
    #: here and left the words behind.
    #:
    #: Empty by default, and an empty one is honest: the doctor then says a sentence that names no
    #: vendor, built from what the row does declare (`env`), so an add-on that never heard of
    #: these fields is no longer told somebody else's remedy.
    when_missing: str = ""
    when_refused: str = ""


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

    return CredentialRow(
        env="", mint=mint, provider=provider, discover=discover,
        when_missing=("set OPENFACTORY_BOT_TOKEN (a PAT, to try things out) or the GitHub App "
                      "trio (OPENFACTORY_GH_APP_ID / _KEY or _KEY_CONTENT / _INSTALLATION_ID) "
                      "in the environment the worker reads — docs/setup/github.md is the "
                      "whole recipe"),
        when_refused=("a GitHub App: grant it access to this repository (Contents / Issues / "
                      "Pull requests / Projects). A PAT: check its scopes and that it has not "
                      "expired"))


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
    """The PAT the shared client reads on its own — and, when no PAT is set, this machine's `az`
    login, which the adapter mints a JWT from at each use (`azure_devops.token_for`); or, when the
    axis DECLARES it, the identity the platform gave the machine the worker runs on (#373). No
    login to discover.

    `source` IS THE ADAPTER'S OWN RESOLUTION (`azure_devops.credential_source`), the function
    `token_for` answers from — so what the doctor reports and what the adapter uses cannot part.

    THE PROVIDER IS DECLARED HERE BECAUSE NOTHING COULD SEE IT WHERE IT LIVED (#170). The `az`
    path was resolved only inside the forge registry's builder, so everything that asks "does this
    deployment hold a credential for this vendor" asked this row, found `env` alone, and answered
    no. Reproduced on a deployment with the variable unset on purpose: the adapter cloned, read a
    declared context repository and opened pull requests on its minted token, while the doctor
    said `no forge credential is configured`, ended `NOT ready`, and sent the operator to create
    the static token this path exists to avoid.

    The provider answers None when `az` does not — no CLI, no login — so a row with no credential
    still says so. Asking it spawns `az` once; the minted token is cached process-wide by the
    adapter, so the use that follows reuses it rather than spawning again.

    NO `mint`, ON PURPOSE. A `mint` answers `deployment_*_token`, whose VALUE callers pass on as a
    static `token=`, and the tracker row hands that straight to the shared client, which keeps it
    for the whole job — an hour-long JWT frozen at the start of a longer one, the defect
    `AzureDevOpsClient.token` exists to prevent. A provider is only ever a callable read at each
    use, and both Azure rows resolve their own credential rather than take a caller's provider,
    so declaring it changes what is ASKED and nothing that is used."""

    def provider():
        from openfactory.adapters.azure_devops import az_token

        return az_token if az_token() else None

    def source(options):
        from openfactory.adapters.azure_devops import credential_source

        return credential_source(options)

    return CredentialRow(
        env=SHIPPED_ENV["azure_devops"], provider=provider, source=source,
        # ALL THREE OF THIS VENDOR'S SOURCES (#170, #373). It said only "set AZURE_DEVOPS_PAT", so
        # a person inside a tenant where a PAT cannot be created — the case the `az` path was
        # built for — was sent to do the one thing they cannot; and a hosted worker whose
        # organisation forbids long-lived tokens was never told its machine's own identity counts.
        when_missing=("on a machine whose platform gave it an identity the organisation has "
                      "added as a user, declare `identity: workload` in the axis's options and "
                      "the adapter mints its own token from it; on a machine where a person runs "
                      "`az login`, that login — the adapter mints from it at each use; otherwise "
                      "set AZURE_DEVOPS_PAT (or the variable this project names in "
                      "`forge.options.token_env`) in the environment the worker reads, a PAT from "
                      "dev.azure.com → User settings → Personal access tokens. "
                      "docs/setup/azure-devops.md §1 is the whole recipe"),
        # THE SCOPE IS THE ONE docs/setup/azure-devops.md §1 TABULATES for what a forge does:
        # fetching, pushing branches, opening and completing pull requests.
        when_refused=("a PAT: check that it has not expired, that it belongs to this "
                      "organisation and that it carries Code (Read & write) — "
                      "docs/setup/azure-devops.md §1 lists each scope and what breaks without "
                      "it. An `az login`, or the machine's own identity: check that the account "
                      "or identity is a user of this organisation and can contribute to this "
                      "repository"))


def _local() -> CredentialRow:
    """This vendor needs nothing: the board is a file this deployment already owns and the forge
    is the person's own repository (ADR-0049 D1, D3).

    `needs=False` RATHER THAN `env=""`, which is GitHub's row and means the opposite — see the
    field. `discover=None` for the same reason one turn later: `init` calls `discover_forge_token`
    with the chosen kind, and a discovery that went looking for a token on a machine that needs
    none would report its absence as a problem to fix."""
    return CredentialRow(needs=False)


#: kind → the row's builder. A builder rather than a row so a vendor's callables stay lazy: this
#: table is consulted on every credential resolution and must import nothing until asked.
CREDENTIALS: dict[str, Callable[[], CredentialRow]] = {
    "local": _local,
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
