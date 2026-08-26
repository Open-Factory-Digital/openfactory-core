"""Which board implementation a project gets — decided from its tracker kind.

UNKNOWN KINDS RAISE, they never degrade to a default. The same rule the harness registry follows
(ADR-0018): a typo that silently produced a GitHub board on a Jira deployment would fail later,
somewhere else, as a confusing permission error — and the ONE thing worse than an unsupported
tracker is a supported-looking one that writes to the wrong system.

THE THIRD COMES FROM OUTSIDE (2026-08-26). This was an if-chain over three vendor names with the
GitHub coordinates gate ABOVE it, so a stranger's `board.<kind>` entry point was loaded and never
asked: with board_owner/board_number set the chain raised "no board provider", without them it
answered None — tickets only — and a Jira-shaped add-on (whose project IS its board) could never
have one. The chain is a table now, the lookup comes first, and each row decides for itself
whether this project has a board.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from openfactory import plugins
from openfactory.adapters.board.base import BoardAdapter

log = logging.getLogger("openfactory.board")

#: The entry-point axis name: `board.<kind>`, keyed — like the table below — by TRACKER kind,
#: because a board is what a tracker's cards are arranged on and no project declares one apart.
AXIS = "board"


def _json_map(raw, project, option: str, consequence: str) -> dict[str, str] | None:
    """A registry option that travels as a JSON object. `None` when absent or unparseable.

    `ProviderRef.options` is `dict[str, str]` by contract, so a map has to arrive as a string —
    exactly as the Jira `status_map` does:

        columns: '{"todo": "A Fazer", "done": "Concluído"}'
        areas:   '{"Portal": "dsk-ui"}'

    A map that will not parse is an ERROR and then `None`, never a half-applied dict: the adapter
    falls back to its default and the mismatch surfaces loudly at the first use rather than as a
    card that quietly never travels. `consequence` is what the operator loses by the fallback, and
    it is a parameter because the two maps lose different things — saying "falling back to the
    defaults" for both would make one of the two messages useless."""
    if not raw:
        return None
    if isinstance(raw, dict):  # a loose registry (or a test) that already holds the map
        return {str(k): str(v) for k, v in raw.items()}
    import json

    try:
        parsed = json.loads(raw)
        return {str(k): str(v) for k, v in parsed.items()}
    except (ValueError, AttributeError) as exc:
        log.error("the board `%s` map for %s is not a JSON object (%s) — %s",
                  option, getattr(project, "name", "?"), exc, consequence)
        return None


def _column_names(project, options: dict) -> dict[str, str] | None:
    """The client's own column names, keyed by the neutral lifecycle keys (C-14)."""
    return _json_map(
        options.get("columns"), project, "columns",
        "falling back to the platform's default column names, which will NOT match a board that "
        "renamed them")


def _jira(project, *, token, token_provider, options):
    # NO board_owner/board_number, and that absence is the design rather than an omission.
    # A Jira project's workflow STATUS is its column, so the project itself is the board —
    # there is no second object to point at, and demanding coordinates for one would be
    # inventing configuration a Jira deployment cannot supply. The pickup queue is a JQL
    # query over the project the tracker already names.
    from openfactory.adapters.board.jira import JiraProjectBoard
    from openfactory.adapters.tracker.registry import build_tracker

    return JiraProjectBoard(build_tracker(project, token=token, token_provider=token_provider))


def _azure_devops(project, *, token, token_provider, options):
    # SAME ABSENCE OF board_owner/board_number AS JIRA, for the same reason: an Azure Boards
    # column IS a work item state, so the project's own board is the board and there is no
    # second object to point at. What Azure DevOps needs instead is one level MORE nesting
    # than GitHub — organization / project / team — and the team is the part a deployment
    # cannot be asked to guess, so it is optional here and discovered from the project itself.
    #
    # The board is built from the SHARED client rather than through `build_tracker`, which is
    # where this differs from Jira: there, auth, the site URL and the status map all lived
    # inside the tracker, so a board with its own REST client would have drifted from it. Here
    # the credential already lives one level up, in `adapters/azure_devops.py` (C-20 — one
    # HTTP client for every Azure DevOps axis), so the board holds no vendor knowledge the
    # tracker also holds, and a deployment can run Azure Boards with a GitHub forge.
    from openfactory.adapters.azure_devops import coordinates
    from openfactory.adapters.board.azure_devops import AzureBoardsBoard
    from openfactory.adapters.forge.registry import repo_of

    tracker = project.tracker
    # THE SAME COORDINATES THE TRACKER REGISTRY READS, spelling for spelling. Not a courtesy:
    # `tracker/registry.py:_azure_devops` accepts `org` as an alias for `organization` and
    # falls back to `tracker.repo` for the ADO project, so a row written the way IT documents
    # built a working tracker and a board whose constructor raised ValueError — and
    # `scan_todo` does not catch it, so that is a poller tick with a stack trace where the
    # pickup queue should be. Reading them differently is the worse bug of the two: the axes
    # would then resolve to DIFFERENT projects and the board would report on work items the
    # tracker never writes to. If either registry's spelling moves, both move together.
    organization, ado_project = coordinates(project, ref=tracker)
    return AzureBoardsBoard(
        organization=organization,
        project=ado_project,
        team=options.get("team", ""),
        board=options.get("board", ""),
        # the client's own column names (C-14) — the same registry row the Jira status_map and
        # the GitHub board columns use.
        columns=_column_names(project, options),
        order_by=options.get("order_by", ""),
        # C-18: the repository a bare card belongs to, and the area→repo map for the ones that
        # do not. Absent → refs stay bare and nothing moves, which is every single-repo project.
        # PROJECT-QUALIFIED to match what `_repo_for_area` mints, so a card sitting in the
        # default repository's own area comes back BARE rather than needlessly qualified.
        default_repo=(f"{ado_project}/{repo_of(project)}" if repo_of(project) else ""),
        areas=_json_map(
            options.get("areas"), project, "areas",
            "falling back to the convention that an area's leaf name IS the repository name. "
            "On a product whose areas are named differently, every card then routes to the "
            "default repository"),
        token=token,
        token_provider=token_provider,
        options=options,
    )


def _github(project, *, token, token_provider, options):
    # THE COORDINATES GATE IS THIS ROW'S, not the registry's. GitHub Projects v2 is a second
    # object beside the repository, so a project points at it with board_owner/board_number and
    # their absence means "tickets only". Jira and Azure Boards have no such object, and a
    # stranger's board may be shaped either way — which is why the gate sat in the wrong place
    # while it was above the dispatch: a Jira-shaped add-on without coordinates read as "no board"
    # before its builder was ever asked (measured 2026-08-26).
    owner, number = options.get("board_owner"), options.get("board_number")
    if not (owner and number):
        return None  # tickets only — a legitimate configuration

    from openfactory.adapters.tracker.github_project import GitHubProjectBoard

    return GitHubProjectBoard(str(owner), str(number), token=token,
                              token_provider=token_provider,
                              columns=options.get("columns") or None,
                              # C-18: what a BARE ref on this board means. Cards from any other
                              # repo leave (and are matched) as `owner/name#n`.
                              default_repo=getattr(project.tracker, "repo", "") or "")


#: tracker kind → the board it implies. Each row answers `None` for "this project has no board",
#: which is a first-class answer on this axis (a deployment can run on tickets alone). A stranger's
#: row joins through the `board.<kind>` entry point with the same signature:
#: `build(project, *, token, token_provider, options) -> BoardAdapter | None`.
BOARDS: dict[str, Callable[..., BoardAdapter | None]] = {
    "github": _github,
    "jira": _jira,
    "azure_devops": _azure_devops,
}

#: The public spelling of the built-in kinds — kept as a tuple because the tests and the docs
#: read it as one; the table above is the source, this is its projection.
BOARD_KINDS = tuple(BOARDS)


def build_board(project, *, token: str | None = None, token_provider=None) -> BoardAdapter | None:
    """The project's board, or `None` when it has no board configured.

    `None` is a first-class answer, not a failure: a board is OPTIONAL (a deployment can run
    perfectly on tickets alone), and every caller already handles its absence. What is not
    acceptable is guessing a provider.

    THE LOOKUP COMES BEFORE ANY GATE. The tracker kind picks the row — built-in or the add-on's
    `board.<kind>` entry point — and the ROW decides whether this project has a board. The
    registry only refuses when no row exists AND the project points at a board anyway
    (board_owner/board_number set): that is a project configured for a provider this deployment
    cannot build, and leaving it pointing at nothing is the confusing-permission-error shape the
    module docstring refuses. Without those options an unknown kind is tickets-only, as before.

    `token_provider` is a callable resolved at each USE rather than here — the same idiom the forge
    and tracker already take. Two reasons it belongs on the board too: an App installation token
    lasts about an hour and a job can outlive one, and a caller that only *might* read the board
    (the doctor, on a project that may have none) must not pay a token mint to find out it has
    nothing to authenticate for."""
    tracker = getattr(project, "tracker", None)
    if tracker is None:
        return None
    options = getattr(tracker, "options", None) or {}
    kind = (getattr(tracker, "kind", "") or "").strip().lower()

    builder = BOARDS.get(kind) or plugins.builder(AXIS, kind, builtin=BOARDS)
    if builder is not None:
        return builder(project, token=token, token_provider=token_provider, options=options)

    owner, number = options.get("board_owner"), options.get("board_number")
    if not (owner and number):
        return None  # tickets only — a legitimate configuration

    known = ", ".join(plugins.known(AXIS, BOARDS))
    raise ValueError(
        f"no board provider for tracker kind {kind!r} (known: {known}). "
        f"A project configures a board with board_owner/board_number; if this tracker has no "
        f"board, remove those options rather than leaving them pointing at nothing."
    )
