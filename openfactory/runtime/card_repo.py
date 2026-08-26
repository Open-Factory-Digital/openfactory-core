"""C-18 — the product owns the board; the repository travels ON the ticket.

MOVED OUT OF `runtime/temporal/activities.py`, and the reason is a defect this cost. The view lived
beside the Temporal activities, so only the durable path applied it: `openfactory run` called
`build_runner(project, issue)` with the raw registry entry and edited the DEFAULT repository
whatever the card said.

Found on the first real multi-repo ticket. `Deskline/fx-dsk-ui#15` — a card about the
TypeScript UI — produced a PR against `fx-dsk-flows` editing `src/Admissao.cs`, the .NET backend.
The independent review rejected it (score 10, *"the diff only modifies the .NET backend but the
ticket's entire premise is the UI"*), which is the guard working; the routing that put it there is
what this move fixes.

The CLI is what an operator uses to try the platform, and what an onboarding session would use in
front of a client's developers. A capability that works on the poller and not there is a capability
that is missing exactly when somebody is watching.
"""

from __future__ import annotations

import logging

log = logging.getLogger("openfactory.c18")


def _ref_repo(project, ref) -> tuple[str, str]:
    """(the repository this ref lives in, the bare ref) — C-18.

    A ref may carry its own repository (`owner/name#3`): one board routes cards to several source
    repos, so the repo every downstream act needs — the clone, the PR, the issue URL — comes from
    the REF first and the project's default only when the ref carries none. The default keeps the
    forge-over-tracker precedence every site used before this existed."""
    from openfactory.contracts.refs import split_repo_ref

    default = (project.forge.repo if project.forge else None) or project.tracker.repo or ""
    return split_repo_ref(ref, default)

def _runner_view(project, ref) -> tuple[object, str]:
    """`(the project as THIS CARD'S repository sees it, the checkout key)` — C-18.

    FOUND LIVE (fx-multirepo web#1, 2026-08-04). C-18 routed the board, the tracker, the Fargate
    box and the preflight clone through the ref — and left the LOCAL runner reading
    `project.repo_path`. So a qualified card cloned the project's DEFAULT repository, the agent
    edited files that belonged to another product, and `gh pr create` refused with "No commits
    between main and sdlc/1" — the only reason nothing worse happened is that the default repo had
    just merged a branch of that name.

    A VIEW, not a mutation: the registry entry is shared, and rewriting it would leak this card's
    repository into every later job. `name` deliberately does NOT change — journals, the log dir,
    the channel and the board all belong to the PRODUCT, and only the checkout and the container
    need to tell two repositories apart."""
    card_repo, _ = _ref_repo(project, ref)
    default = (project.forge.repo if project.forge else None) or project.tracker.repo or ""
    if _is_default_repo(project, card_repo):
        return project, project.name

    def _at(axis):
        return axis.model_copy(update={"repo": card_repo}) if axis is not None else None

    from openfactory.adapters.forge.registry import clone_url_for

    raw = (project.repo_path or "").strip()
    # THE SLUG SWAP STAYS, because it is the only thing that preserves a host nobody declared: a
    # GitHub Enterprise deployment registers `https://ghe.acme.com/...`, and composing a URL from
    # the forge would send that clone to the public internet. What was wrong underneath it was the
    # FALLBACK — a bare `github.com` literal for any registered path the slug did not appear in.
    #
    # AND THE SWAP HAD AN ASYMMETRY THAT ONLY A SECOND PROVIDER COULD SHOW. `default` comes from
    # the registry (`fx-ado`), while C-18 mints the card's repo already qualified
    # (`{project}/fx-dsk-ui`), because a bare one does not survive `split_repo_ref`. Substituting
    # the second for the first inside `…/{project}/_git/fx-ado` produced
    # `…/_git/{project}/fx-dsk-ui` — a doubled segment, and a 404 that reads like a repository
    # somebody forgot to create. So the replacement is taken at the SAME qualification level as the
    # coordinate the URL already carries: GitHub's `owner/name` swaps whole, Azure's swaps its leaf.
    replacement = card_repo
    if default.count("/") < card_repo.count("/"):
        replacement = card_repo.rsplit("/", 1)[-1]
    if default and default in raw:
        repo_path = raw.replace(default, replacement)
    else:
        # No slug to swap: ASK THE FORGE rather than composing a vendor's URL by hand.
        try:
            repo_path = clone_url_for(project, card_repo, token=None)
        except Exception as exc:  # noqa: BLE001 — an unresolvable forge must not kill the view
            log.warning(
                "could not compose a checkout URL for %s on %s (%s) — keeping the project's own, "
                "so this card would run against the DEFAULT repository",
                card_repo, getattr(project, "name", "?"), str(exc)[:140])
            repo_path = raw
    view = project.model_copy(update={
        "repo_path": repo_path,
        # THE TRACKER DOES NOT MOVE, AND THAT IS C-18'S OWN SENTENCE: the board belongs to the
        # PRODUCT; only the checkout and the container need to tell two repositories apart.
        #
        # It was moved anyway, and GitHub hid it. There a card's repository IS the repository its
        # issue lives in, so rewriting `tracker.repo` was merely redundant — every method already
        # resolves the card's repo per operation through `_locate` → `split_repo_ref`.
        #
        # On Azure DevOps the two are different LEVELS. `tracker.repo` names the ADO PROJECT that
        # holds the work items (`Deskline`); the card's repository is one of the N git repos
        # inside it. Rewriting the first with the second produced
        # `/Deskline/fx-dsk-ui/_apis/wit/workitems/15` and a 404 about a missing CONTROLLER —
        # an error that reads like a platform routing bug rather than a coordinate mistake.
        # Found on the first real multi-repo card, which is the first time the two levels differed.
        "tracker": project.tracker,
        "forge": _at(project.forge),
        "ci": _at(project.ci),
    })
    return view, _checkout_key(project, card_repo)



def _is_default_repo(project, repo: str) -> bool:
    """Whether `repo` names the project's DEFAULT repository, at either qualification level.

    Azure's registry rows carry the BARE repository name (`fx-ado`) while C-18 mints every
    card's repo already qualified (`Deskline/fx-ado`) — the same level asymmetry the URL
    swap in `_runner_view` handles. Comparing the two spellings by equality filed the default
    repo under a FOREIGN key: its own checkout duplicated, its box proof recorded away from
    the project name, and every default card held by a gate looking at the wrong proof
    (adversarial review, 2026-08-13). The qualifier must still MATCH — a same-named repository
    in another ADO project is genuinely foreign."""
    default = (project.forge.repo if project.forge else None) or project.tracker.repo or ""
    if not repo or repo == default:
        return True
    if default and default.count("/") < repo.count("/") \
            and repo.rsplit("/", 1)[-1] == default:
        qualifier = repo.rsplit("/", 1)[0]
        tracker_repo = (project.tracker.repo or "") if getattr(project, "tracker", None) else ""
        forge_project = ""
        forge = getattr(project, "forge", None)
        if forge is not None:
            forge_project = str((getattr(forge, "options", None) or {}).get("project", ""))
        return qualifier in {q for q in (tracker_repo, forge_project) if q}
    return False


def _checkout_key(project, repo: str) -> str:
    """The RepoCache key for a checkout of `repo` under this project.

    The project NAME for its default repo — byte-for-byte today's key, so no cache re-clones.
    A suffixed key for a card's foreign repo: two repositories must never share one checkout,
    or a preflight against `…-api` reads `…-web`'s manifest and sizes the wrong world."""
    if _is_default_repo(project, repo):
        return project.name
    return f"{project.name}--{repo.replace('/', '--')}"