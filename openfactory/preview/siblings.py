"""The pull requests a preview's unit is made of — and, by name, what is not in it (ADR-0050 D1,
D5; the design on #265, §6.1–§6.2).

A CARD is its own pull request. A REQUIREMENT is every card that executes it, and those live in
several repositories of one product, each with its own pull request — the front end's in `web`,
the back end's in `api`. Which cards those are is read where the product keeps them: its BOARD,
walked the way the orphan repair walks it (`product/module.py::_orphans`), each open card whose
citation names the requirement (`_cited_requirement`, the one reader of it).

TWO BOUNDS, BOTH ON THE SIBLING, NEVER ON THE READER'S TRUST:

- ITS REPOSITORY IS THE PRODUCT'S. A card on the board may live anywhere — transferred in, added to
  the board from any repository, an area path outside the product — and a body anybody can edit
  may cite REQ-0012. A sibling counts only when its repository is in `sources:`; any other is left
  out and said (`acme/tools#4 cites REQ-0012 but is not a repository of this product`), and nothing
  of it is ever checked out.
- ITS PULL REQUEST IS THE PLATFORM'S. The one the factory opened for that card, on
  `namespace.job_branch(n)` in that repository, and open by the forge's own answer — never a pull
  request somebody else pointed at the card, never a bare number the delivery loop reads
  (`ref_numbers`), which cannot say which repository it means.

A sibling with no such pull request is not an error: its repository is shown at its base, and
the card says so (`api runs its current version — api#13 has no pull request yet`).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from openfactory import namespace
from openfactory.contracts.refs import split_repo_ref
from openfactory.preview.demand import branches_of, open_changes, redact
from openfactory.preview.product import member, short

log = logging.getLogger("openfactory.preview.siblings")


class Change(BaseModel):
    """One open pull request of the unit: the repository it is in, where the forge holds it, and
    the branch a start fetches."""

    model_config = ConfigDict(frozen=True)

    repo: str
    url: str
    branch: str
    #: the card it is the pull request of, as the board names it (`acme/api#13`), when known
    card: str = ""


class Changes(BaseModel):
    """What the forge and the board said about a unit. `open` is None when the forge could not be
    read at all — which is never "nothing is open" — and `why` then says so."""

    model_config = ConfigDict(frozen=True)

    open: tuple[Change, ...] | None = ()
    #: a sentence for every card of the unit that is NOT in the preview, and why
    missing: tuple[str, ...] = ()
    why: str = ""


def cards_citing(requirement: int, tickets: Iterable, *, sources: Iterable[str],
                 default_repo: str) -> tuple[list[tuple[str, str]], list[str]]:
    """`([(repository, number)…], [missing…])` — the board's OPEN cards whose citation names
    `requirement`, each in its repository (a bare ref is the board's default repository), those
    in a repository outside `sources:` left out with a sentence naming them. Pure."""
    from openfactory.product.module import _cited_requirement

    members = [s for s in sources if s]
    found: list[tuple[str, str]] = []
    missing: list[str] = []
    for card in tickets:
        if getattr(card, "state", "open") != "open":
            continue
        if _cited_requirement(getattr(card, "body", "") or "") != requirement:
            continue
        repo, number = split_repo_ref(getattr(card, "number", ""), default_repo)
        number = number.lstrip("#")
        if not number.isdigit():
            continue
        home = member(repo, members)
        if not home:
            missing.append(f"{repo}#{number} cites REQ-{requirement:04d} but is not a repository "
                           f"of this product — not included.")
            continue
        if (home, number) not in found:
            found.append((home, number))
    return found, missing


def of_requirement(requirement: int, tickets: Iterable, *, sources: Iterable[str],
                   default_repo: str, forge) -> Changes:
    """The unit of a requirement: every sibling's pull request the platform opened and the forge
    reports open, each in its own repository — and a sentence for each sibling that has none, or
    that could not be asked about."""
    siblings, missing = cards_citing(requirement, tickets, sources=sources,
                                     default_repo=default_repo)
    out: list[Change] = []
    for repo, number in siblings:
        card = f"{short(repo)}#{number}"
        branch = namespace.job_branch(number)
        try:
            url = forge.pr_for_head(branch, repo=repo)
            state = forge.pr_status(pr=url, repo=repo) if url else ""
        except Exception as exc:  # noqa: BLE001 — unread is said, never judged open or absent
            log.info("could not ask about %s's pull request (%s)", card, redact(str(exc))[:160])
            url, state = None, ""
        if url is None:
            missing.append(f"whether {card} has a pull request could not be read — `{repo}` runs "
                           f"its current version in this preview.")
        elif not url:
            missing.append(f"`{repo}` runs its current version — {card} has no pull request "
                           f"yet.")
        elif state != "open":
            missing.append(f"`{repo}` runs its current version — {card}'s pull request is "
                           f"{state or 'not open'}.")
        else:
            out.append(Change(repo=repo, url=url, branch=branch, card=f"{repo}#{number}"))
    return Changes(open=tuple(out), missing=tuple(missing))


def of_record(token: str, was, forge, *, default_repo: str) -> Changes:
    """The unit as its record knows it — the pull requests its cards offered, each in the
    repository the job named — for a card, and for a requirement whose board could not be read."""
    found, why = branches_of(token, was, forge)
    if why:
        return Changes(open=(), why=why)
    repos = dict(getattr(was, "repos", {}) or {}) if was is not None else {}
    live, why = open_changes(found, forge, repos=repos)
    if live is None:
        return Changes(open=None, why=why)
    return Changes(open=tuple(Change(repo=repos.get(url) or default_repo, url=url, branch=branch)
                              for url, branch in live.items()))
