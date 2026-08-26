"""Which CI a project's deployments are observed through — from config, never from an import.

Paired with the forge registry on purpose: a client is not "on GitLab for code and GitHub for CI",
so the CI kind DEFAULTS TO THE FORGE'S. One value configures both, and a deployment that genuinely
splits them can still say so explicitly.

GitLab CI is not implemented yet (the product owner's call: later, but prepared). The seam is being
delivered here — see `forge/registry.py` for why a stub would be worse than an honest error.

Azure Pipelines is the second vendor on this axis, and it cost one module plus the row below. What
it did NOT cost is the interesting part: the port stayed three methods, because a CI observer is
asked what the platform needs to know (is this ref green, did it reach that environment, is it
alive) rather than what a vendor happens to expose.

THE THIRD COMES FROM OUTSIDE (2026-08-26). An add-on registers `ci.<kind>` in the
`openfactory.adapters` entry-point group and its row joins the table at lookup time, the shape
every other registry has. It matters twice on this axis: the CI kind DEFAULTS TO THE FORGE'S, so a
stranger's `forge.gitea` was built and then refused one call later — `build_promotion_runner`
asked this registry for `gitea` and it knew only the built-ins (measured: "unknown CI 'gitea'"
with the add-on's `ci.gitea` loaded and never consulted). And the refusal now says which of the
two ways out applies: install the `ci.<kind>` add-on, or name a different CI in `forge.options.ci`.

AN ADD-ON RESOLVES ITS OWN CREDENTIAL. Both call sites hand this axis the deployment's FORGE
credential (`build_observer(project, token=forge_token_for(project) or app_tok)`), which is a
GitHub token on a GitHub deployment. The two built-in Azure rows already refuse it (`token=None`
below, with the measurement); an add-on's builder is handed `token=None` for the same reason — a
credential only goes to the host that issued it (#162), and the platform cannot know which host a
stranger's CI is. The add-on reads the variable its project's `options.token_env` names.
"""

from __future__ import annotations

from collections.abc import Callable

from openfactory import plugins

#: The entry-point axis name: `ci.<kind>`.
AXIS = "ci"


#: forge/CI kind → the observer it implies.
def _github_actions(project, **kw):
    from openfactory.adapters.environment.github_actions import GitHubActionsObserver

    return GitHubActionsObserver(
        (project.forge.repo if getattr(project, "forge", None) else None) or "",
        token=kw.get("token"),
    )




def _azure_pipelines(project, **kw):
    from openfactory.adapters.azure_devops import coordinates
    from openfactory.adapters.environment.azure_pipelines import AzurePipelinesObserver

    forge = getattr(project, "forge", None)
    options = dict(getattr(forge, "options", None) or {})
    organization, ado_project = coordinates(project, ref=forge)
    return AzurePipelinesObserver(
        # ONE HOME FOR THIS SPELLING (`adapters/azure_devops.py::coordinates`). Four registries
        # each carried a copy promising the other three would move with it; two had already
        # drifted, and a drift here means the axes resolve to DIFFERENT ADO projects.
        # It is not a startup nicety: `factory.py` builds this observer for every PromotionRunner,
        # so a disagreement here killed the promotion at construction, before a pipeline was read.
        organization=organization,
        project=ado_project,
        # NOT `repo_of(project)` — the forge's fallback — on purpose. That falls back to the
        # tracker's `repo`, which here names the ADO PROJECT rather than a git repository, and this
        # project really does contain a repo whose name equals the project's: the observer would
        # have quietly reported another repository's builds. A missing repo raises in the
        # constructor instead.
        repo=(getattr(forge, "repo", None) or ""),
        # NOT `kw["token"]`. Both call sites hand this axis a GITHUB credential — `build_observer(
        # project, token=forge_token() or app_tok)` in the factory, a GitHub App token in the
        # action catalog — because until now every observer was GitHub's. Passing it on would
        # authenticate against dev.azure.com with a github.com token and surface as 401 on a
        # perfectly good configuration. The Azure credential is read from the environment variable
        # this project's options name, which is where it has always lived.
        token=None,
        options=options,
    )


OBSERVERS: dict[str, Callable[..., object]] = {
    "github": _github_actions,
    # `github_actions` accepted as an alias so a deployment can be explicit about the CI when it
    # differs from the forge — the two names mean the same observer today.
    "github_actions": _github_actions,
    # Azure Repos ⇒ Azure Pipelines, by the same "one value configures both" rule: `azure_devops`
    # is the kind the forge and tracker rows use, so a project that names it once is observed by
    # the right CI without saying so twice.
    "azure_devops": _azure_pipelines,
    "azure_pipelines": _azure_pipelines,
}


def declared_ci(project) -> str:
    """The `ci` option a project names explicitly, lower-cased, or "" when it inherits."""
    forge = getattr(project, "forge", None)
    options = (getattr(forge, "options", None) or {})
    return str(options.get("ci", "")).strip().lower()


def observer_kind(project) -> str:
    """The CI kind: an explicit `ci` option, else the forge's kind.

    Defaulting to the forge is the honest reading of how these deployments are actually shaped —
    and it means adding GitLab CI arrives automatically for a project that moved its forge, rather
    than silently observing the wrong system until somebody notices deployments never confirm."""
    explicit = declared_ci(project)
    if explicit:
        return explicit
    from openfactory.adapters.forge.registry import forge_kind

    return forge_kind(project)


def build_observer(project, *, token=None):
    """The project's CI observer. Raises on an unknown kind — a deployment whose pipelines are
    never observed would report every release as "still verifying", for ever.

    A built-in row wins; an add-on's row (`ci.<kind>` entry point) fills the rest and is built
    WITHOUT the caller's credential — see the module docstring."""
    kind = observer_kind(project)
    builder = OBSERVERS.get(kind)
    if builder is not None:
        return builder(project, token=token)
    added = plugins.builder(AXIS, kind, builtin=OBSERVERS)
    if added is not None:
        return added(project, token=None)
    known = ", ".join(plugins.known(AXIS, OBSERVERS))
    # WHICH DOOR. The kind was either named in `forge.options.ci` or inherited from the forge, and
    # the operator's remedy differs: a forge add-on with no CI of its own needs `forge.options.ci`
    # to name one this deployment implements, and a typo'd explicit `ci` needs the option fixed.
    # Saying "unknown CI" alone sent an operator to the forge registry, where everything was fine.
    origin = ("named by `forge.options.ci`" if declared_ci(project)
              else "inherited from the forge kind, because the project names no `forge.options.ci`")
    raise ValueError(
        f"unknown CI {kind!r} ({origin}) — known: {known}. Either install the add-on that "
        f"declares the `{AXIS}.{kind}` entry point, or set `forge.options.ci` to one of the known "
        f"kinds. Refusing to fall back: an observer pointed at the wrong system never confirms a "
        f"deployment, and the symptom is a release that hangs in 'verifying' rather than an error "
        f"anybody can act on."
    )
