"""A preview on demand — what the job offers, and what a card may say about it (ADR-0050 D6; the
design on #265, §4.3 and §5.5).

TWO READERS, NEITHER OF WHICH MAY RUN ANYTHING. The job, at the moment its pull request is handed
to a person, OFFERS a preview (`offer`): it writes a record and asks no daemon, no runtime and no
compose file anything — a preview is built from commits (D4), so the box the job ran in does not
matter, and a job must never wait on, or fail over, a preview. The panel, when a card is opened,
JUDGES what can be done (`judge`): whether a preview can start is asked of the deployment (a
runtime named) and of the forge (an open pull request of the unit), never read off the record the
job wrote — the moment a person merges a preview proposal, the pull request they were waiting on
can be started, whatever the job wrote days ago.

THE OFFER NEVER OVERWRITES A LIVE PREVIEW. A requirement is previewed as one unit with every card
that executes it (D1); a sibling card reaching its gate while the unit is up does not take it down
or relabel it `offered` — it joins the unit's cards, and the record says the preview is `stale`:
the change it adds is not in what a person is looking at until somebody rebuilds.

`stale`, at read time: a preview is of the head it was built from, and a branch that moved since
is a preview of a commit nobody is merging any more. The forge's answer is asked once a minute per
unit at most (`forge_state`), because the panel asks on every open of a card.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from collections.abc import Callable
from typing import NamedTuple

from openfactory import namespace, preview
from openfactory.preview.plan import CardRef, Unit
from openfactory.util.bounded import BoundedDict

log = logging.getLogger("openfactory.preview.demand")

#: How many previews one deployment runs at once when `OPENFACTORY_PREVIEW_MAX` says nothing. Each
#: unit may reserve the operator's `memory_total` (8g by default), so four is a laptop's worth.
DEFAULT_MAX = 4

#: How long the forge's answer about a unit is reused at read time.
FORGE_TTL_SECONDS = 60


def max_previews() -> int:
    """`OPENFACTORY_PREVIEW_MAX`, else `DEFAULT_MAX`. A value that is not a positive number is the
    default, said once in the log — a cap nobody can read must not become no cap."""
    raw = (os.environ.get("OPENFACTORY_PREVIEW_MAX") or "").strip()
    if not raw:
        return DEFAULT_MAX
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        log.warning("OPENFACTORY_PREVIEW_MAX=%r is not a positive number — %d previews at once",
                    raw, DEFAULT_MAX)
        return DEFAULT_MAX
    return value


def over_cap(running, *, mine: str, cap: int) -> str:
    """Why another preview may not start while `running` are up, or "" when it may (D6). The
    refusal NAMES the units holding the deployment, because "the limit is reached" sends a person
    looking for something they cannot see; "acme 12 and acme req0012 are up" tells them which to
    stop."""
    others = sorted({(rp.project, rp.unit) for rp in running if rp.compose_project != mine})
    if len(others) < cap:
        return ""
    names = ", ".join(f"{p} {u}" for p, u in others)
    return (f"this deployment runs at most {cap} preview{'s' if cap != 1 else ''} at once "
            f"(OPENFACTORY_PREVIEW_MAX) and {len(others)} {'are' if len(others) != 1 else 'is'} "
            f"up: {names} — stop one from its card, or raise the cap.")


def unit_for(project: str, token: str, was: preview.Preview | None) -> Unit:
    """The unit a token names, with the cards its record knows of."""
    requirement = token.startswith("req")
    cards = tuple(CardRef(ref=c) for c in (was.cards if was else ()))
    if not cards and not requirement:
        cards = (CardRef(ref=token),)
    return Unit(project=project, kind="requirement" if requirement else "card",
                id=f"REQ-{token[3:]}" if requirement else token, cards=cards, token=token)


# ── the offer ────────────────────────────────────────────────────────────────────────────────────


def why_not_here(kind: str, *, required: bool) -> str:
    """What a card says when THIS deployment can run no preview, or "" when it can."""
    if kind and kind != "none":
        return ""
    from openfactory.adapters.preview import none

    reason = none.said()
    said = (f"{reason}." if reason == none.ONE_MACHINE
            else f"no preview can run on this deployment: {reason}.")
    if required:
        said += (" This project's pull requests wait for a person: previews are required and none "
                 "can run here — set OPENFACTORY_PREVIEW_RUNTIME, or `openfactory project "
                 "set-preview <project> --no-required`.")
    return said


def product_context(project):
    """The project's product context — the one reader of it (`load_product_context`), or an
    inactive one carrying why when it could not be read at all. Never raises: a preview never
    fails a job, and a product module that cannot be read is a product module that is off."""
    from openfactory.product.config import ProductLink
    from openfactory.product.loader import ProductContext, load_product_context

    try:
        return load_product_context(project)
    except Exception as exc:  # noqa: BLE001 — unreadable is off, said, never on
        return ProductContext(link=ProductLink(
            active=False, kind="config",
            reason=f"the product context could not be read ({redact(str(exc))[:160]})"))


def offer(*, project, manifest, ticket, pr_url: str, branch: str,
          latest: Callable[[str, str], preview.Preview | None] = preview.latest,
          record: Callable[[preview.Preview], object] = preview.record,
          runtime_kind: str | None = None, shape_root=None,
          base: str = "main", product: Callable | None = None) -> preview.Preview | None:
    """Record that this card's change can be previewed — or, when its unit is already up, that
    the preview no longer shows everything. None when nothing was written: the project declares no
    `preview:` on its base (declare nothing, and nothing changes — D3), or the card carries no
    number, or the unit already knows this card and its pull request.

    Asks nothing of a daemon or a runtime, and reads the runtime's KIND only to say why a preview
    cannot start here: `can_start` is judged at read time, never from what this writes.

    A BASE THAT DECLARES NO `preview:` IS STILL OFFERED SOMETHING (#265 slice 4, §4.3): the card
    says what would give this change a preview. `shape_root` is the job's own checkout; what it
    says a draft could be read from is written on the record as `shape`, and the sentence naming
    the open proposal is computed when the card is READ, because a person opens and merges the
    proposal after this. Pure: `offer_facts` reads files inside that tree and runs nothing. With
    no tree to read, nothing is written — declare nothing, and nothing changes (D3).

    A CARD OF A REQUIREMENT IS OFFERED AS THE REQUIREMENT ONLY WHEN THE PRODUCT CAN BE READ
    (§6.1): `product(project)` — the product context, `product_context` by default — must be
    available, because a requirement's siblings are the product's board's cards within its
    `sources:`. Off, the card is its own unit and its record says why (`alone`)."""
    if not preview.card_of(ticket.id):
        return None
    shape: dict[str, str] = {}
    if getattr(manifest, "preview", None) is None:
        if shape_root is None:
            return None
        from openfactory.adapters.forge.registry import repo_of
        from openfactory.onboarding.preview_propose import offer_facts

        facts = offer_facts(shape_root, repo=repo_of(project), base=base)
        if not facts.case:
            return None  # the change itself declares one: it is offered once that lands
        shape = facts.model_dump()
    from openfactory.preview.unit import unit_of
    from openfactory.product.module import _cited_requirement

    name = project.name
    body = str(getattr(ticket, "raw", "") or "")
    repo = str(getattr(ticket, "repo", "") or "")
    # the product is asked only of a card that cites a requirement: every other card is its own
    # unit whatever the product module says, and asking would cost a checkout for nothing
    ctx = (product or product_context)(project) if _cited_requirement(body) is not None else None
    unit = unit_of(name, CardRef(ref=str(ticket.id), repo=repo), body, ctx=ctx)
    if unit is None:
        return None
    card = preview.card_of(ticket.id)
    was = latest(name, unit.token)
    cards = tuple(dict.fromkeys([*(was.cards if was else ()), card]))
    urls = tuple(dict.fromkeys([*(was.pr_urls if was else ()), pr_url]))
    branches = {**(was.branches if was else {}), pr_url: branch}
    repos = {**(was.repos if was else {}), **({pr_url: repo} if repo else {})}
    known = was is not None and card in was.cards and was.branches.get(pr_url) == branch
    if was is not None and was.state in (preview.STARTING, preview.LIVE):
        if known:
            return None
        said = (f"{ticket.id} opened its pull request after this preview started — rebuild it to "
                f"include that change.")
        joined = was.model_copy(update={"cards": cards, "pr_urls": urls, "branches": branches,
                                        "repos": repos,
                                        "stale": tuple(dict.fromkeys([*was.stale, said]))})
        record(joined)
        return joined
    if runtime_kind is None:
        from openfactory.runtime.temporal.io import default_preview_runtime

        runtime_kind = default_preview_runtime()
    required = bool(getattr(getattr(project, "preview", None), "required", False))
    offered = preview.Preview(project=name, unit=unit.token, kind=unit.kind, cards=cards,
                              state=preview.OFFERED, pr_urls=urls, branches=branches, shape=shape,
                              repos=repos, alone=unit.alone,
                              missing=(unit.alone,) if unit.alone else (),
                              why="" if shape else why_not_here(runtime_kind, required=required))
    if known and was.state == preview.OFFERED and was.why == offered.why and \
            was.shape == offered.shape and was.alone == offered.alone:
        return None  # offered already, in these words — a second row would say nothing new
    record(offered)
    return offered


# ── what the forge says, at read time ────────────────────────────────────────────────────────────


class ForgeState(NamedTuple):
    """What the forge answered about one unit. `open` is None when it could not be read — which
    is not "no open pull request", and is never judged as one."""

    open: tuple[str, ...] | None
    heads: dict[str, str]
    #: pull request → branch, for the ones the forge found by branch name
    branches: dict[str, str]


def redact(text: str) -> str:
    return re.sub(r"(https?://)[^@/\s]+@", r"\1***@", text or "")


def ls_remote(remote: str, branch: str) -> str | None:
    """The sha `branch` points at on `remote` — which, for a branch a job pushed, IS the head of
    the pull request the forge holds. None when it could not be read. The remote may carry a
    credential; it is an argument here and never reaches a sentence."""
    if not remote or not branch:
        return None
    try:
        done = subprocess.run(["git", "ls-remote", "--heads", remote, f"refs/heads/{branch}"],
                              capture_output=True, text=True, timeout=20, check=False,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("could not read the head of %s (%s)", branch, redact(str(exc)))
        return None
    if done.returncode:
        log.info("could not read the head of %s (%s)", branch, redact(done.stderr.strip()[:160]))
        return None
    first = (done.stdout or "").split()
    return first[0] if first else ""


def branches_of(token: str, was: preview.Preview | None, forge) -> tuple[dict[str, str], str]:
    """Every pull request the unit is known to have, with its branch — `(url → branch, why)`.

    From the record when the job offered it; for a CARD nobody offered (a job older than this
    build, a card whose job ended before its gate) from the branch every job for that card works
    on, asked of the forge. A requirement's cards are known here only from their offers — what a
    card can say about itself at read time; a START finds every sibling on the board
    (`preview/siblings.py`)."""
    found = dict(was.branches) if was else {}
    for url in (was.pr_urls if was else ()):
        found.setdefault(url, "")
    if token.startswith("req"):
        return found, ("" if found else f"no card of REQ-{token[3:]} has reached its pull request "
                                        f"yet — a preview shows a change, and there is none yet.")
    branch = namespace.job_branch(token)
    for url, known in list(found.items()):
        if not known:
            found[url] = branch
    if found:
        return found, ""
    url = forge.pr_for_head(branch)
    if url is None:
        return {}, f"the forge could not say whether `{branch}` has a pull request."
    if not url:
        return {}, (f"card {token} has no pull request yet — a preview shows a change, and there "
                    f"is none to show yet.")
    return {url: branch}, ""


def open_changes(found: dict[str, str], forge, *, repos: dict[str, str] | None = None
                 ) -> tuple[dict[str, str] | None, str]:
    """The pull requests among `found` the forge reports OPEN — or None, with why, when not one
    could be read. One that could not be read is left out rather than assumed open. `repos` says
    which repository each is in, when the record knows (a bare ref is ambiguous across them)."""
    out: dict[str, str] = {}
    unread: list[str] = []
    for url, branch in found.items():
        try:
            repo = (repos or {}).get(url, "")
            status = forge.pr_status(pr=url, repo=repo) if repo else forge.pr_status(pr=url)
        except Exception as exc:  # noqa: BLE001 — unread is said, never judged open or closed
            log.info("could not read %s (%s)", url, redact(str(exc)[:160]))
            unread.append(url)
            continue
        if status == "open":
            out[url] = branch
    if not out and unread:
        return None, f"the forge could not say whether {', '.join(unread)} is still open."
    return out, ""


#: (project, unit, what the record knows) → (when asked, what the forge said). Bounded: one entry
#: per unit somebody opened, and the oldest answer is the least worth keeping.
_CACHE: BoundedDict[tuple, tuple[float, ForgeState]] = BoundedDict(512)


def forge_state(project, token: str, was: preview.Preview | None, *,
                forge_of: Callable | None = None, heads_of: Callable | None = None,
                now: float | None = None) -> ForgeState:
    """What the forge says about one unit now: which of its pull requests are open, and the head
    each points at. Reused for `FORGE_TTL_SECONDS` — the panel asks on every open of a card."""
    now = time.time() if now is None else now
    key = (project.name, token, tuple(was.pr_urls) if was else (),
           tuple(sorted((was.heads or {}).items())) if was else ())
    hit = _CACHE.get(key)
    if hit and now - hit[0] < FORGE_TTL_SECONDS:
        return hit[1]
    state = _forge_state(project, token, was, forge_of=forge_of, heads_of=heads_of)
    _CACHE[key] = (now, state)
    return state


def _forge_state(project, token, was, *, forge_of, heads_of) -> ForgeState:
    try:
        forge = (forge_of or _forge_of)(project)
        found, _why = branches_of(token, was, forge)
        live, _why = open_changes(found, forge)
    except Exception as exc:  # noqa: BLE001 — a card that cannot ask the forge still renders
        log.info("could not ask the forge about %s %s (%s)", project.name, token,
                 redact(str(exc)[:160]))
        return ForgeState(open=None, heads={}, branches={})
    if live is None:
        return ForgeState(open=None, heads={}, branches=found)
    repos = dict(getattr(was, "repos", {}) or {}) if was is not None else {}
    heads = {}
    for url, branch in live.items():
        # IN THE PULL REQUEST'S OWN REPOSITORY: a requirement's siblings live in several, and a
        # branch is a name inside one — `openfactory/13` read in the wrong one is another card's
        sha = (heads_of or ls_remote)(remote_for(project, forge, repos.get(url, "")), branch)
        if sha:
            heads[url] = sha
    return ForgeState(open=tuple(live), heads=heads, branches=found)


def _forge_of(project):
    from openfactory.adapters.forge.registry import build_forge
    from openfactory.credentials import deployment_forge_token, forge_token_for

    return build_forge(project, token=forge_token_for(project) or deployment_forge_token(project))


def _remote(project, forge) -> str:
    """Where a job's branch is read from: the forge's own remote (authenticated when hosted, the
    repository path on the local forge), else the project's repository as registered."""
    try:
        remote = forge.push_remote()
    except Exception as exc:  # noqa: BLE001 — no remote is an unread head, not a failed card
        log.info("the forge named no remote for %s (%s) — its heads are read from the registered "
                 "repository", getattr(project, "name", "?"), redact(str(exc)[:160]))
        remote = None
    return remote or str(getattr(project, "repo_path", "") or "")


def remote_for(project, forge, repo: str = "") -> str:
    """Where a branch of `repo` is read and fetched from: the project's own remote for its own
    repository (`""`, or the repository the forge was built for), else that repository's clone
    URL on the same forge, carrying the forge's own credential only when it owns the host
    (`authenticated_url`). An argument of whoever runs git — never stored, never said."""
    from openfactory.adapters.forge.registry import repo_of
    from openfactory.product.config import repo_match

    if not repo or repo_match(repo, repo_of(project) or ""):
        return _remote(project, forge)
    try:
        return forge.authenticated_url(forge.clone_url(repo, token=None))
    except Exception as exc:  # noqa: BLE001 — an unaddressable repository is an unread head
        log.info("the forge could not address %s (%s)", repo, redact(str(exc)[:160]))
        return ""


def stale_of(was: preview.Preview, heads_now: dict[str, str]) -> list[str]:
    """One sentence per pull request whose branch moved past the head the preview was built from.
    A head the forge did not answer for is not a move."""
    out = []
    for url, built in sorted((was.heads or {}).items()):
        now = heads_now.get(url, "")
        if built and now and now != built:
            out.append(f"built from {built[:7]}; the pull request is now at {now[:7]} — rebuild.")
    return out


class Judged(NamedTuple):
    can_start: bool
    why: str
    stale: list[str]


def judge(was: preview.Preview | None, *, kind: str, forge: ForgeState, required: bool = False
          ) -> Judged:
    """What a card may offer: whether a preview can start now and, when it cannot, why — from the
    DEPLOYMENT (a runtime named) and the FORGE (an open pull request of the unit), never from what
    the offer wrote — and which of what is up no longer shows the pull request's head."""
    stale = list(was.stale) if was else []
    if was is not None and was.live:
        stale += [s for s in stale_of(was, forge.heads) if s not in stale]
    running = was is not None and (was.state == preview.STARTING
                                   or (was.live and not was.expired()))
    refusal = why_not_here(kind, required=required)
    if refusal:
        return Judged(False, refusal, stale)
    if running:
        return Judged(False, "", stale)
    if forge.open is None:
        # the forge did not answer: an offered unit may still be started — the plan activity is
        # the judge, and it asks the forge again
        offered = bool(was and was.pr_urls)
        return Judged(offered, "" if offered else "the forge could not be asked whether this card "
                                                  "has an open pull request.", stale)
    if not forge.open:
        return Judged(False, "there is no open pull request of this card — a preview shows a "
                             "change, and there is none to show.", stale)
    return Judged(True, "", stale)
