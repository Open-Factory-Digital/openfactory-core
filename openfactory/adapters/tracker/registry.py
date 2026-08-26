"""Which tracker a project uses — resolved from config, never from an import.

Same seam as the harness registry, for the same reason and after the same discovery: the platform
was agnostic in its protocols and hardcoded in its composition root. `TrackerAdapter` has always
been a Protocol, and `GitHubIssuesTracker` was still constructed by name in a dozen places, so a
Jira deployment meant editing a dozen files rather than changing one value.

The pilot is Python on GitHub. That is a PILOT, not the shape of the product: the same platform is
sold to clients whose tickets live in Jira, and "agnostic" has to be structurally true before the
first of them arrives, not promised for later.

AN UNKNOWN KIND RAISES. Falling back to GitHub would have a Jira deployment quietly writing its
tickets into a repository nobody reads — the one failure worse than an unsupported tracker is a
supported-LOOKING one pointed at the wrong system.
"""

from __future__ import annotations

from collections.abc import Callable

from openfactory import plugins

# No default. Removing the model default alone would not have removed the GitHub default:
# these resolvers ended in `or DEFAULT_KIND`, so `kind: ""` still landed on GitHub AFTER the
# contracts change — and the kernel AST guard stayed green, because a provider registry is
# correctly outside its scope. Both had to land together or C-08 would have shipped a
# checkable claim that was still false.


def _github(project, **kw):
    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    options = (getattr(project.tracker, "options", None) or {})
    return GitHubIssuesTracker(
        project.tracker.repo or "",
        board_owner=options.get("board_owner"),
        board_number=options.get("board_number"),
        token=kw.get("token"),
        token_provider=kw.get("token_provider"),
        # the client's own column names (C-14) — same registry row the Jira status_map uses
        board_columns=options.get("columns") or None,
    )


def _jira(project, **kw):
    import json
    import logging

    from openfactory.adapters.tracker.jira import JiraTracker

    log = logging.getLogger("openfactory.tracker")
    options = (getattr(project.tracker, "options", None) or {})
    # `options` is dict[str,str] by contract, so the status map travels as a JSON string:
    #   status_map: '{"in_progress": "Em andamento", "done": "Concluído"}'
    # Without it every set_state is a no-op-with-warning — an audit found the whole state-mapping
    # feature unreachable because nothing ever passed the map in.
    status_map: dict[str, str] = {}
    raw = options.get("status_map", "")
    if raw:
        try:
            status_map = {str(k): str(v) for k, v in json.loads(raw).items()}
        except (ValueError, AttributeError) as exc:
            log.error("jira status_map for %s is not valid JSON (%s) — issues will NOT be "
                      "transitioned until it is fixed", getattr(project, "name", "?"), exc)
    # THE VENDOR'S OWN CREDENTIAL, NEVER THE CALLER'S PROVIDER — the same refusal the forge
    # registry's Azure row makes, and it was missing here. `token_provider` on this axis is
    # ALWAYS `factory._bot_token_provider`, the GitHub App minter: every caller that has no
    # explicit token passes it. Honouring it meant the sweep that stopped handing this row a
    # GitHub token as `token=` simply changed which door the same token came in by — a fix that
    # only looks like one, which is worse than the gap. Found by adversarial review, 2026-08-20,
    # measured: a Jira project with no `JIRA_API_TOKEN` still built a `JiraTracker` whose token
    # was the minted `ghs_…`, before AND after the sweep.
    #
    # Jira's API token is static and named by `_VENDOR_DEFAULT_ENV`, so there is nothing a
    # provider would buy even if it were this vendor's: nothing configured → None → the adapter
    # fails saying which variable to set, which is an honest error rather than a mystery 401.
    from openfactory.credentials import vendor_default

    token = kw.get("token") or vendor_default(getattr(project, "tracker", None))
    return JiraTracker(
        site=options.get("site", ""),
        project_key=options.get("project_key") or project.tracker.repo or "",
        email=options.get("email", ""),
        token=token,
        status_map=status_map,
        issue_type=options.get("issue_type", "Task"),
    )


def _azure_devops(project, **kw):
    from openfactory.adapters.azure_devops import coordinates
    from openfactory.adapters.tracker.azure_devops import AzureBoardsTracker

    options = (getattr(project.tracker, "options", None) or {})
    # `state_map` travels as a JSON string for the same reason Jira's `status_map` does — options
    # is dict[str,str] by contract:
    #   state_map: '{"in_progress": "Doing", "needs_action": "Needs Action", "done": "Done"}'
    # Unlike Jira this is optional: Azure DevOps publishes each state's CATEGORY, so an
    # unconfigured deployment still moves cards correctly for every bucket the vendor classifies.
    state_map = _json_map(options.get("state_map", ""), project, "state_map")
    # THE VENDOR'S OWN CREDENTIAL, NEVER THE CALLER'S PROVIDER — the same refusal the forge
    # registry's Azure row makes, and it was missing here. `token_provider` on this axis is
    # ALWAYS `factory._bot_token_provider`, the GitHub App minter: every caller that has no
    # explicit token passes it. Honouring it meant the sweep that stopped handing this row a
    # GitHub token as `token=` simply changed which door the same token came in by — a fix that
    # only looks like one, which is worse than the gap. Found by adversarial review, 2026-08-20,
    # measured: a Jira project with no `JIRA_API_TOKEN` still built a `JiraTracker` whose token
    # was the minted `ghs_…`, before AND after the sweep.
    #
    # AND NOTHING ELSE IS NEEDED HERE. The shared `AzureDevOpsClient` below reads the variable this
    # project NAMES (`options.token_env`, default `AZURE_DEVOPS_PAT`) on its own — measured, both
    # the default and a named one. A `or token_for(options)` on this line would look like the fix
    # and change no answer, which is the shape this whole card is about; the caller's explicit
    # token is passed through because it is the one thing the client cannot know about.
    token = kw.get("token")
    organization, ado_project = coordinates(project, ref=getattr(project, "tracker", None))
    return AzureBoardsTracker(
        # ONE HOME FOR THIS SPELLING (`adapters/azure_devops.py::coordinates`). Four registries
        # each carried a copy promising the other three would move with it; two had already
        # drifted, and a drift here means the axes resolve to DIFFERENT ADO projects.
        organization=organization,
        project=ado_project,
        # `options` travels too: with no explicit token the shared client reads the variable this
        # project NAMES in `token_env`, so a credential never has to pass through the registry
        token=token,
        work_item_type=options.get("work_item_type", "Issue"),
        state_map=state_map,
        options=options,
    )


def _json_map(raw: str, project, field: str) -> dict[str, str]:
    """A JSON-encoded option, or {} — never a crash and never a silent empty.

    A malformed map is LOGGED AS AN ERROR rather than swallowed: it degrades a state change into a
    no-op, and a no-op nobody was told about is a card that stops moving for a reason no one can
    see."""
    import json
    import logging

    if not raw:
        return {}
    try:
        return {str(k): str(v) for k, v in json.loads(raw).items()}
    except (ValueError, AttributeError) as exc:
        logging.getLogger("openfactory.tracker").error(
            "%s for %s is not valid JSON (%s) — work items will NOT be transitioned by it until "
            "it is fixed", field, getattr(project, "name", "?"), exc)
        return {}


#: kind → builder. Adding a tracker is ONE entry here plus its module; a test asserts that no call
#: site anywhere goes back to naming a concrete class.
TRACKERS: dict[str, Callable[..., object]] = {
    "github": _github,
    "jira": _jira,
    # spelled like the shared client's module (`openfactory/adapters/azure_devops.py`) so one kind
    # names
    # this vendor on every axis it appears on
    "azure_devops": _azure_devops,
}


def tracker_kind(project) -> str:
    tracker = getattr(project, "tracker", None)
    return (getattr(tracker, "kind", "") or "").strip().lower()


def build_tracker(project, *, token=None, token_provider=None):
    """The project's tracker. Raises on an unknown kind — never guesses a provider."""
    kind = tracker_kind(project)
    builder = TRACKERS.get(kind) or plugins.builder('tracker', kind, builtin=TRACKERS)
    if builder is None:
        _known = ', '.join(plugins.known('tracker', TRACKERS))
        raise ValueError(
            f"unknown tracker {kind!r} — known: {_known}. Refusing to fall "
            f"back to a default: a deployment whose tickets live elsewhere would have this "
            f"one silently writing into a repository nobody reads."
        )
    return builder(project, token=token, token_provider=token_provider)
