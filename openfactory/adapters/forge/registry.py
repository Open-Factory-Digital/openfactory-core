"""Which forge a project uses — resolved from config, never from an import.

Same seam as the harness and tracker registries. GitLab is not implemented yet, deliberately:
the product owner's call on 2026-07-28 was to leave GitLab and Telegram for later but to **leave
everything prepared to plug in**, and a stub adapter that nothing exercises would be the twelfth
instance of this codebase's signature defect — built, tested, reached by nothing.

So what "prepared" means here is precise, and it is the part that actually costs:

    the seam dispatches            one row in FORGES, not a sweep through the composition root
    nothing outside names a class  eleven direct constructions routed through here
    the contract is runtime-checked `isinstance` against the Protocol, so a new adapter cannot
                                    ship half-implemented and be discovered in production
    an unknown kind RAISES          `gitlab` today gives "known: azure_devops, github" — an honest
                                    error at startup, not a GitHub call against a GitLab URL

Adding GitLab later is then one module plus one row, with the test suite already asserting it
satisfies the same seventeen-method contract GitHub does.

Azure Repos was the first row to prove that sentence, and it cost exactly what the seam promised:
one module plus the builder below. It also made a latent defect real — while `FORGES` had a single
row, every project's forge was the same vendor, so `forge_token()` being process-wide was harmless.
It is not harmless now, which is why the builder resolves the credential per project.
"""

from __future__ import annotations

from collections.abc import Callable

from openfactory import plugins

# No default. Removing the model default alone would not have removed the GitHub default:
# these resolvers ended in `or DEFAULT_KIND`, so `kind: ""` still landed on GitHub AFTER the
# contracts change — and the kernel AST guard stayed green, because a provider registry is
# correctly outside its scope. Both had to land together or C-08 would have shipped a
# checkable claim that was still false.


def repo_of(project) -> str:
    """The repository the forge acts on, falling back to the tracker's.

    The fallback is not tidiness: six call sites carried it independently, because a project may
    name its repo on either axis and the forge is useless without one. Centralising it here means
    a new provider inherits the same rule instead of rediscovering it.

    PUBLIC BECAUSE THE SENTENCE ABOVE WAS NOT TRUE YET. Two more copies had grown since it was
    written — one in `product/board.py`, one in the Slack bot — each with the same rule spelled a
    different way. A docstring claiming to be the single home is worth exactly as much as the
    number of callers that can reach it."""
    forge = getattr(project, "forge", None)
    tracker = getattr(project, "tracker", None)
    return (getattr(forge, "repo", None) or getattr(tracker, "repo", None) or "")


def _github(project, **kw):
    from openfactory.adapters.forge.github import GitHubForge

    return GitHubForge(repo_of(project), token=kw.get("token"),
                       token_provider=kw.get("token_provider"))


def _azure_devops(project, **kw):
    from openfactory.adapters.azure_devops import coordinates, token_for
    from openfactory.adapters.forge.azure_devops import AzureReposForge

    forge = getattr(project, "forge", None)
    options = dict(getattr(forge, "options", None) or {})
    organization, ado_project = coordinates(project, ref=forge)
    return AzureReposForge(
        repo_of(project),
        # ONE HOME FOR THIS SPELLING (`adapters/azure_devops.py::coordinates`). Four registries
        # each carried a copy promising the other three would move with it; two had already
        # drifted, and a drift here means the axes resolve to DIFFERENT ADO projects.
        organization=organization,
        project=ado_project,
        # THE AZURE CREDENTIAL, NEVER THE AMBIENT ONE — and `kw` is where the ambient one arrives.
        # Every call site that builds a forge hands this axis a GITHUB credential: the worker's
        # `_forge_for` and the panel's `_pr_checks` pass `forge_token()` (OPENFACTORY_FORGE_TOKEN /
        # OPENFACTORY_BOT_TOKEN), the box passes a GitHub App token, and `token_provider` is that
        # App's
        # own minter. `forge_token_for` does not close this: a project that names no `token_env`
        # is DELIBERATELY given the deployment's own token, which is right for the six GitHub
        # projects that exist and wrong for this one. Reproduced before this line changed — with
        # both variables set, this row handed the adapter the GitHub PAT and `push_remote()`
        # emitted it into a dev.azure.com URL: a github.com secret sent to Microsoft, and a 401
        # that reads like a revoked credential rather than like the configuration mistake it is.
        # Same call, same reason, as `environment/registry.py`'s Azure row refusing `kw["token"]`.
        #
        # A PROVIDER rather than a value, so it is read at each USE: the variable is named by the
        # project (`options.token_env`, default AZURE_DEVOPS_PAT) and an `az account
        # get-access-token` JWT lasts about an hour, so a job that outlives one still pushes.
        # Nothing configured → None → the shared client raises the sentence that names the
        # variable to set, which is an honest error rather than a mystery 401.
        token_provider=lambda: token_for(options),
        options=options,
    )




#: kind → builder. GitLab joins as one row here plus `forge/gitlab.py`; nothing else changes.
FORGES: dict[str, Callable[..., object]] = {
    "github": _github,
    # spelled like the shared client's module (`openfactory/adapters/azure_devops.py`) and like the
    # tracker's row, so ONE kind names this vendor on every axis it appears on
    "azure_devops": _azure_devops,
}


def forge_kind(project) -> str:
    """Which forge this project uses, falling back to the tracker's — the single-vendor case.

    THE CONTRACT ALREADY PROMISED THIS AND THIS FUNCTION DID NOT KEEP IT. `contracts/project.py`
    says, above the three axes: *"If only some are given, missing ones fall back to `tracker` (the
    common single-vendor case), so callers can set one and get all."* `repo_of` implements exactly
    that for the repository half, ten lines up. The KIND half never did, so a registry row that
    declared only `tracker:` — the shape the contract invites — resolved to `""` and raised
    *"unknown forge ''"* at `build_forge`, which is on the job path.

    Latent rather than live only because every registered project happens to spell both out. It
    surfaced when the clone URL moved behind this registry: three test fixtures written the
    documented way stopped working, which is the contract's own promise failing in miniature.

    THIS IS NOT A DEFAULT AND ADR-0018 STILL HOLDS. An unset tracker kind is still unset, and a
    Jira-tracker project with no forge now resolves to `jira` and raises *"unknown forge 'jira' —
    known: azure_devops, github"*, naming the real problem. What is refused is GUESSING a vendor;
    inheriting the one the deployment actually declared is the opposite of a guess."""
    forge = getattr(project, "forge", None)
    kind = (getattr(forge, "kind", "") or "").strip().lower()
    if kind:
        return kind
    tracker = getattr(project, "tracker", None)
    return (getattr(tracker, "kind", "") or "").strip().lower()


def clone_url_for(project, repo: str = "", *, token: str | None = None) -> str:
    """The URL that clones `repo` for THIS project — through the registry, never a literal.

    `repo` empty means the project's own. Anything else is C-18 in action: the preflight sizes the
    card's repository, the knowledge pipeline reads the merged one, and the product module clones
    a docs repository that is not the code at all.

    RAISES on an unknown forge, exactly as `build_forge` does, and for the same reason: a clone
    aimed at the wrong host fails as a 404 about a missing repository, which sends somebody to look
    for a permissions problem instead of a configuration one.

    THE ADAPTER'S OWN CREDENTIAL WINS OVER THE CALLER'S, and that is the whole reason this is a
    function rather than two lines at each call site. `build_forge` already REFUSES an ambient
    token on the Azure row (`_azure_devops` takes a `token_provider` and ignores `kw["token"]`),
    because every caller in this codebase hands the forge axis a GitHub credential — the worker's
    `_forge_for`, the panel's `_pr_checks`, the box's App token. Passing the caller's token
    straight through to `clone_url` would have walked around that refusal and put a github.com
    secret into a `dev.azure.com` URL: the exact defect the refusal exists to prevent, reintroduced
    one layer up by the convenience wrapper.

    AND `or token` WOULD HAVE PUT IT BACK, WHICH IS HOW THIS WAS WRITTEN THE FIRST TIME. The
    adapter's `token` is None whenever its own credential is unset — an Azure project on a
    deployment that has not provisioned `AZURE_DEVOPS_PAT` yet, which is precisely the state during
    onboarding. The fallback then handed the caller's GitHub secret straight to dev.azure.com.
    Reproduced verbatim before removing it:

        https://openfactory:ghp_…@dev.azure.com/{org}/{project}/_git/fx-ado

    The guard that was supposed to prevent this only ever ran with the ADO variable SET, so it
    asserted the happy path and called it proof. A missing credential now yields a TOKENLESS URL —
    the clone fails saying so, which is the honest outcome, instead of failing with someone else's
    secret in the request. `GitHubForge.token` already returns whatever it was built with, so this
    costs the GitHub path nothing."""
    forge = build_forge(project, token=token)
    return forge.clone_url(repo, token=getattr(forge, "token", None))


def build_forge(project, *, token=None, token_provider=None):
    """The project's forge. Raises on an unknown kind — never guesses a provider.

    A GitLab deployment falling back to GitHub would authenticate against the wrong host with the
    wrong token and report the failure as a permissions problem, which is the most expensive shape
    a configuration error can take: it looks like something else."""
    kind = forge_kind(project)
    builder = FORGES.get(kind) or plugins.builder('forge', kind, builtin=FORGES)
    if builder is None:
        _known = ', '.join(plugins.known('forge', FORGES))
        raise ValueError(
            f"unknown forge {kind!r} — known: {_known}. Refusing to fall back "
            f"to a default: pointing a {kind} deployment at the wrong client would surface "
            f"as a confusing auth error rather than as the configuration mistake it is."
        )
    return builder(project, token=token, token_provider=token_provider)
