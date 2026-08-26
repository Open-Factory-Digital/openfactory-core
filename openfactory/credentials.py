"""Credentials, read from the process environment — the composition root's job, not the kernel's.

These lived in `openfactory/contracts/bot.py` until C-08. A domain model that reads `os.environ` is
not
vendor-named, so no guard catches it, but it is the same mistake: the kernel stops being a set of
values you can construct and becomes something that behaves differently depending on the machine.

Each token is per-AXIS on purpose (ADR-0022). A Jira-tracker plus GitLab-forge project needs a Jira
API token AND a GitLab access token; a single-vendor GitHub project can reuse one for both, which
is what `OPENFACTORY_BOT_TOKEN` is for.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from openfactory.contracts.bot import BotIdentity

log = logging.getLogger("openfactory.credentials")


def app_private_key() -> str | None:
    """The GitHub App's PEM, however this process was handed it — or None if it has no App.

    TWO DELIVERY SHAPES, ONE ANSWER. A file path (`OPENFACTORY_GH_APP_KEY`) is how a laptop and the
    terraform-mounted task get it; raw content (`OPENFACTORY_GH_APP_KEY_CONTENT`) is how Secrets
    Manager,
    an env var and a compose file get it. Every reader used to want the path, so two entry points
    bridged the gap by writing a temp file at import time — the Fargate entrypoint and the panel —
    and everything else silently had no credential. `openfactory doctor` inside the compose worker
    reported `gh auth login` on a container holding a perfectly good private key.

    NO TEMP FILE. `mint_installation_token` takes the PEM as content and always did; the file only
    existed because callers read a path before calling it. Removing that step removes a 0600
    creation race, an import-order dependency and a private key on disk.

    CONTENT FIRST. A stale `OPENFACTORY_GH_APP_KEY` inherited from an outer environment must not
    shadow
    the key this process was actually given — the path is the fallback, not the authority.
    """
    content = os.environ.get("OPENFACTORY_GH_APP_KEY_CONTENT")
    if content:
        return content
    path = os.environ.get("OPENFACTORY_GH_APP_KEY")
    if not path:
        return None
    try:
        return Path(path).expanduser().read_text()
    except OSError as exc:
        # Silence would present three layers away as an unauthenticated forge, which reads as a
        # permissions problem on GitHub's side rather than a missing file on ours.
        log.warning("the App key at %s could not be read (%s) — this process has no App "
                    "credential", path, exc)
        return None


def app_id() -> str | None:
    """The GitHub App's id, or None when this process has no App.

    HERE RATHER THAN AT EACH READER (#64, C-28). This and `app_installation_id` were read inline
    with `os.environ.get` in four places — `factory.py` twice, `adapters/github_app.py`, and as a
    typer `envvar=` in `cli.py` — while `app_private_key` above was already centralised. A
    credential with four readers has four places to disagree about precedence and four places a
    future per-project override would have to be threaded through.

    Collapsing them is the enabling refactor for C-28 UNDER EITHER OPTION the card offers (refuse
    a registry that spans installations, or make the installation per-project): both need exactly
    one place that answers "which installation is this?". It changes no behaviour today."""
    return os.environ.get("OPENFACTORY_GH_APP_ID") or None


def app_installation_id() -> str | None:
    """Which installation of the App this process acts as, or None.

    ONE PROCESS, ONE INSTALLATION — and that is a real, undocumented limit rather than a design
    (#64). The CHANNEL credential is per-project (`factory.notifier_for_project` reads the env var
    the registry names), so one deployment hosts N projects across N Slack workspaces; the FORGE
    credential is process-wide, so the same deployment authenticates against exactly one GitHub
    App installation. Two orgs need two processes today, and nothing states that anywhere a person
    onboarding a project would look."""
    return os.environ.get("OPENFACTORY_GH_APP_INSTALLATION_ID") or None


def bot_identity() -> BotIdentity:
    """Who the factory acts as, from the environment the deployment set."""
    return BotIdentity(
        name=os.environ.get("OPENFACTORY_BOT_NAME", "OpenFactory Bot"),
        email=os.environ.get("OPENFACTORY_BOT_EMAIL", "openfactory-bot@localhost"),
        login=os.environ.get("OPENFACTORY_BOT_LOGIN") or None,
    )


def _row(kind: str):
    """The vendor's credential row — shipped or installed — or None when it declares nothing.

    THE TABLE THIS REPLACES WAS CLOSED. `_VENDOR_DEFAULT_ENV` was a dict literal in this module
    naming two vendors' variables; a stranger's `forge.gitlab` add-on had no way to add a row, so
    its projects fell through to the generic pair — the deployment's GITHUB credential — and were
    handed it as if it were their own (measured 2026-08-24). The rows live in
    `adapters/credential/registry.py` and an add-on declares one exactly as it declares a forge."""
    from openfactory.adapters.credential.registry import credential_row

    return credential_row(kind)


def vendor_default_env(ref) -> str:
    """The variable the axis vendor's credential lives in BY DEFAULT, or `""` — the registry's
    `token_env` always wins; this answers for a deployment that named nothing. GitHub answers
    `""` on purpose: its default IS the generic pair, and a row naming a variable would say
    otherwise. Derived from the vendor's own row, never from a table here."""
    kind = (getattr(ref, "kind", "") or "").strip().lower()
    row = _row(kind)
    return (row.env or "") if row is not None else ""


def vendor_default(ref) -> str | None:
    """The axis vendor's own default credential, or None.

    BEFORE the generic fallback, never after — that order is the fix. `forge_token()` falls back
    to `OPENFACTORY_BOT_TOKEN`, which on a mixed deployment is a GITHUB credential: an Azure
    DevOps project that reached it would present a GitHub PAT as HTTP Basic and read back a 401 —
    a credential that LOOKS configured failing as if it were revoked. The shared ADO client
    already read `AZURE_DEVOPS_PAT` on its own, so the adapters worked while everything that asks
    "does this project HAVE a forge credential" — the doctor's presence probe, the repo-cache
    fetch — answered no. Found by the pre-pilot funnel review (2026-08-09): an ADO-only
    deployment was told "no forge credential is configured" with a GitHub remedy, over a
    perfectly good PAT."""
    named = vendor_default_env(ref)
    return (os.environ.get(named) or "").strip() or None if named else None


def tracker_token() -> str | None:
    return (os.environ.get("OPENFACTORY_TRACKER_TOKEN")
            or os.environ.get("OPENFACTORY_BOT_TOKEN") or None)


def _axis_credential(project, axis: str, generic, *,
                     announce: bool = True) -> tuple[str, str | None]:
    """`(source, value)` of `project`'s credential on `axis` — ONE resolution for both axes.

    `source` is the credential's IDENTITY, never its value: `env:<NAME>` for a variable the
    project or its vendor named, `generic:<axis>` for the deployment-wide pair (one value per
    process, whichever of the two variables holds it), `""` when nothing answered. It exists so
    a reader that must ask a credential ONCE can tell two credentials apart without comparing
    their values — `floor.reading.budgets` keyed its rows by the token itself, and the App mint
    renews the token on every call, so N projects on one installation cost N mints and N probes
    (measured 2026-08-26). The identity is the thing that answered, which survives a renewal.

    Resolution: `token_env` if named → the axis vendor's own default variable (its credential
    row's `env`) → `generic()`, the axis's process-wide reader (`tracker_token` / `forge_token`,
    passed as the function so the seam the harnesses patch stays the seam). `announce=False`
    keeps the named-but-empty warning from being said twice when a caller asks for the source
    and then the value."""
    ref = getattr(project, axis, None)
    options = getattr(ref, "options", None) or {}
    named = str(options.get("token_env") or "").strip()
    if named:
        value = os.environ.get(named)
        if value:
            return f"env:{named}", value
        if announce:
            log.warning("%s names %s as its %s credential and that variable is empty — falling "
                        "back to this deployment's own, which is very likely the wrong system",
                        getattr(project, "name", "?"), named, axis)
    default = vendor_default_env(ref)
    if default:
        value = (os.environ.get(default) or "").strip() or None
        if value:
            return f"env:{default}", value
    value = generic() or None
    return (f"generic:{axis}", value) if value else ("", None)


def tracker_token_for(project) -> str | None:
    """This PROJECT's tracker credential, falling back to the deployment's.

    ONE DEPLOYMENT HOSTS N PROJECTS AND THEY DO NOT SHARE A TRACKER. `tracker_token()` is a single
    process-wide value, so a worker serving a GitHub project and a Jira project authenticated both
    with whichever one the environment happened to carry — and the Jira one simply came back with
    an empty queue. Found live on fx-jira (F-02, 2026-08-05): the board resolved, the search ran,
    the backlog had a ticket in TO-DO, and the pickup queue was `[]`.

    THE REGISTRY NAMES THE VARIABLE, IT NEVER HOLDS THE SECRET — exactly the shape ADR-0015 uses
    for the per-workspace Slack token (`channel_options.bot_token_env`). `deploy/registry.yaml` is
    baked into the worker image; a token written there is a token in an image layer.

    Resolution: `token_env` if named → the axis vendor's own default variable (its credential
    row's `env`) → the deployment-wide generic pair. A GitHub axis is unchanged."""
    return _axis_credential(project, "tracker", tracker_token)[1]


def forge_token() -> str | None:
    return (os.environ.get("OPENFACTORY_FORGE_TOKEN")
            or os.environ.get("OPENFACTORY_BOT_TOKEN") or None)


def forge_token_for(project) -> str | None:
    """This PROJECT's forge credential, falling back to the deployment's.

    THE SAME DEFECT AS `tracker_token_for`, ON THE OTHER AXIS, AND IT HAS BEEN LATENT ALL ALONG.
    That one was found live on fx-jira: a worker serving a GitHub project and a Jira project
    authenticated both with whichever process-wide token the environment carried, and the Jira
    board came back with an empty queue. The forge axis had the identical hole and nothing had
    stepped in it, for one reason only — until today `FORGES` had a single row, so every project's
    forge really was the same vendor.

    The Azure Repos row ends that. Worse than a bare failure: `forge_token()` falls back to
    `OPENFACTORY_BOT_TOKEN`, so an Azure project would be handed a GitHub PAT, present it as HTTP
    Basic,
    and read back a 401 — a credential that LOOKS configured failing as if it were revoked, which
    is the most expensive shape a configuration error takes because it looks like something else.

    A DEFAULT THAT IS ONLY SAFE WHILE ONE VENDOR EXISTS IS A DEFECT WAITING FOR THE SECOND. Written
    with the ADO pack rather than after it, because after it means finding it in a client's logs.

    Resolution: `token_env` if named → the axis vendor's own default variable (its credential
    row's `env`) → the deployment-wide generic pair. A GitHub axis is unchanged."""
    return _axis_credential(project, "forge", forge_token)[1]


def deployment_tracker_token(project) -> str | None:
    """The credential this DEPLOYMENT can mint for `project`'s TRACKER, when the project names none.

    THE MIRROR OF `deployment_forge_token`, ON THE AXIS WHERE THE FAILURE IS WORSE. A forge handed
    the wrong system's token answers 401 — wrong, but legible. Azure DevOps answers a GitHub token
    with **HTTP 200 and a sign-in page**, so the board reads as configured-but-unreadable, and Jira
    answers an empty search — a board with work in TO-DO produces a pickup queue of `[]` and
    nothing anywhere says the credential was for another system.

    Both of those were found by running against a real deployment rather than by reading, which is
    why the resolution now lives in one place instead of at each call site: `… or
    github_app_token_from_env()` was spelled at eighteen of them, inside modules that name no
    vendor anywhere else.

    THE VENDOR'S OWN ROW ANSWERS. The reference vendor's row carries the App mint; a vendor whose
    row has no `mint` — and a stranger's add-on that declares none — gets None, because this
    deployment has nothing of that vendor's to offer and a token from the wrong system is worse
    than none. A project that names NO kind predates the seam and keeps the reference mint.
    """
    return _deployment_mint(getattr(project, "tracker", None))


def deployment_forge_token(project) -> str | None:
    """The credential this DEPLOYMENT can mint for `project`'s forge, when the project names none.

    THE VENDOR DECIDES, and that is the whole point of this function existing. Twenty-three
    call sites across the package spell the last resort as `… or github_app_token_from_env()`,
    inside modules that are otherwise vendor-neutral. It is not wrong today — `build_forge` and
    `clone_url_for`'s Azure row refuse a caller's ambient GitHub token outright — but it is
    correct by the defence of the layer below rather than by what the caller asked for, and it
    puts one vendor's name in code that claims to know none. Raised by the operator while
    reviewing exactly these changes (2026-08-14): *"it matters that any change be aimed at
    the PRODUCT and not at my specific case"*.

    So: the vendor's OWN ROW answers (`adapters/credential/registry.py`). The reference vendor's
    row carries the App mint; a vendor whose row declares no `mint` — and a stranger's add-on
    that declares none — gets None, because this deployment has nothing of that vendor's to offer
    and a token from the wrong system is worse than none. Behaviour is identical for GitHub and
    strictly honest elsewhere."""
    return _deployment_mint(getattr(project, "forge", None))


#: The kind a registry row that predates the seam has: none. It keeps the reference vendor's
#: capabilities, because refusing it would turn a legacy row into a dead deployment.
_REFERENCE_KIND = "github"


def _kind_of(ref) -> str:
    return str(getattr(ref, "kind", "") or "").strip().lower() or _REFERENCE_KIND


def _deployment_mint(ref) -> str | None:
    """One token this deployment can mint for `ref`'s vendor, or None — the row decides."""
    row = _row(_kind_of(ref))
    return row.mint() if row is not None and row.mint is not None else None


def tracker_credential_source(project) -> str:
    """WHERE `tracker_token_for(project) or deployment_tracker_token(project)` comes from — the
    credential's IDENTITY, never its value, and never a mint.

    `env:<NAME>` when a variable the project or its vendor named answers; `generic:tracker` when
    the deployment-wide pair does (one value per process, so one identity); `deployment:<kind>`
    when nothing is set and the vendor's row can mint one; `""` when this process has no
    credential for it. Non-empty exactly when `tracker_token_for(p) or deployment_tracker_token(p)`
    is.

    ONE PROCESS HOLDS ONE DEPLOYMENT CREDENTIAL PER VENDOR — the App trio is read from the
    process environment (`app_id`, `app_installation_id`), so `deployment:<kind>` IS the App's
    identity within this process. That is what makes it a key: `floor.reading.budgets` asks a
    budget once per credential, and the mint renews the VALUE on every call, so keying by value
    asked N times for N projects on one installation (measured 2026-08-26). A mint that would
    fail still has an identity — the budget row for it reads as unread once, not N times."""
    source, value = _axis_credential(project, "tracker", tracker_token, announce=False)
    if value:
        return source
    kind = _kind_of(getattr(project, "tracker", None))
    row = _row(kind)
    return f"deployment:{kind}" if row is not None and row.mint is not None else ""


def _deployment_provider(ref):
    """A re-minting PROVIDER for `ref`'s vendor, or None — for a job that outlives one token.

    THE DOOR THE MINT CAME IN BY AFTER THE TOKEN DOOR WAS CLOSED. `factory.build_runner` spelled
    `token_provider=None if forge_token_for(p) else prov` with `prov` the GitHub App minter for
    EVERY kind, so an add-on forge with no credential of its own received a callable that mints
    GitHub tokens, and nothing told the add-on to refuse it (measured 2026-08-24). The provider
    is now the row's, so a vendor that declares none gets None through this door too."""
    row = _row(_kind_of(ref))
    return row.provider() if row is not None and row.provider is not None else None


def deployment_tracker_provider(project):
    """The re-minting provider this deployment holds for `project`'s TRACKER vendor, or None."""
    return _deployment_provider(getattr(project, "tracker", None))


def deployment_forge_provider(project):
    """The re-minting provider this deployment holds for `project`'s FORGE vendor, or None."""
    return _deployment_provider(getattr(project, "forge", None))


def discover_forge_token(kind: str) -> str | None:
    """A PERSON's own login on this machine for the forge `kind`, or None — onboarding's
    convenience, consulted through the vendor's row (`discover`), absent on vendors with none.

    It was `cli.py::_gh_token_if_logged_in`, a `gh auth token` subprocess in core on a path that
    had just asked which forge the deployment uses. Never raises: an unavailable helper (no CLI,
    not logged in, a vendor with no such thing) is an ordinary state."""
    row = _row((kind or "").strip().lower())
    if row is None or row.discover is None:
        return None
    try:
        return row.discover()
    except Exception:  # noqa: BLE001 — a convenience may not break onboarding
        log.debug("the %s login could not be discovered", kind, exc_info=True)
        return None
