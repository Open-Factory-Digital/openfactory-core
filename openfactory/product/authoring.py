"""Writing: a requirement becomes a pull request; a requirement becomes issues.

TWO SURFACES, TWO AUTHORITIES (ADR-0019 §5).

    a requirement change   →  a PR in the documentation repo   →  a human merges it
    an issue               →  filed straight into Backlog      →  a human promotes it to TO-DO

The line is drawn at COST, not at content. Rewriting an ambiguous criterion is the role's job and
requiring a human for every wording decision would put a person back in the loop the factory exists
to remove. Starting work is not: TO-DO is what the poller pulls, so a promotion spends real money.

WHY A PULL REQUEST RATHER THAN A DIRECT COMMIT. It is the sign-off — auditable, versioned, familiar,
and no CI to pay for since a documentation repo has no gates to run. It also settles who wins when a
person and an agent edit the same paragraph: git does.

IDEMPOTENT BY CONSTRUCTION. Slack retries, a worker replaced mid-operation, a signal delivered
twice — each would otherwise leave a second PR proposing the same requirement, or a duplicate issue
on the board. Every write here derives a deterministic key and checks for its own prior result
first, the same discipline the Fargate launcher uses to re-attach to a job it already started.
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# the private regexes on purpose: reader and writers must share the ONE pattern object (see the
# note on `_STATUS_RE` in corpus.py) — a copy here is how the two drifted the first time
from openfactory.product.corpus import (
    _ASKED_RE,
    _DATE_RE,
    _STATUS_RE,
    ACCEPTED,
    DECISIONS_HEADING,
    DROPPED,
    OBSERVED,
    PROPOSED,
    SUPERSEDED,
    Corpus,
    find_decisions_table,
)
from openfactory.product.role import IssueDraft, RequirementDraft

log = logging.getLogger("openfactory.product")

_GIT_TIMEOUT = 120

#: The forge kind this module used to assume. KEPT AS A NAME AND NOT AS A BEHAVIOUR: nothing here
#: branches on a vendor any more (#95) — every pull-request operation goes through `ForgeAdapter`,
#: which is one interface over GitHub, Azure Repos and whatever comes next. It survives because it
#: is still the default of two parameters this module accepts and ignores, and those exist only
#: until their call sites drop them (see `propose_requirement`).
GITHUB = "github"

#: How long a merge may take to become VISIBLE before this module stops waiting for it, and why
#: waiting at all is not paranoia. MEASURED through the real adapters on 2026-08-06:
#:
#:     Azure Repos    `merge_pr` returned in 0.8s; the PR read `open`, and `merged` at +2.4s
#:     GitHub         `merged` on the first read back
#:
#: Completion is ASYNCHRONOUS on Azure DevOps by design — the arming PATCH answers `active` — so a
#: single read straight after the merge reports an honest merge as a failure, and this module's
#: answer to that is client-visible: `merged=False` is what makes the channel say the requirement
#: is not yet where the role can read it. One vendor's timing must not become another vendor's
#: wrong sentence. Six attempts two seconds apart is ~10s of patience for the case that is really
#: still open, and one round trip for the common case that is not.
_MERGE_ATTEMPTS = 6
_MERGE_DELAY = 2.0


@dataclass
class WriteResult:
    """What a write produced, or why it produced nothing. `ok=False` is always accompanied by a
    sentence a human can act on — a write that failed silently is how a requirement discussed at
    length turns out never to have been recorded."""

    ok: bool
    url: str = ""
    ref: str = ""
    detail: str = ""
    existed: bool = False
    #: whether the proposal reached the branch everyone reads. MERGING IS NOT ACCEPTING (ADR-0032):
    #: the requirement lands as `proposed`, and only a human's confirmation in the channel turns it
    #: into a promise the factory defends. Left unmerged it was invisible to the product role
    #: itself — it reads the docs branch, so its own requirement did not exist from where it stands.
    merged: bool = False

    #: The requirement number this write actually MINTED — 0 when the write minted none.
    #:
    #: The channel used to tell the client the number it had PREDICTED before the write, computed
    #: from the base corpus alone. `propose_requirement` mints against the base AND the unlanded
    #: `req/*` branches, so a pushed-but-unmerged proposal makes the two disagree — and the client
    #: was then told "o requisito 7 está registrado" about a file called `0008-…md`. Their next
    #: sentence is `aceita o requisito 7`, which finds nothing.
    #:
    #: So the act reports its own outcome, like every other write here. A prediction is a fine
    #: thing to compute and a terrible thing to state as fact.
    number: int = 0


def next_number(corpus: Corpus) -> int:
    """One past the highest number ever used — INCLUDING superseded ones.

    Reusing a retired number would silently re-point every citation of the old requirement at a new
    and unrelated one, which is the sort of corruption nobody notices until a decision is argued
    from the wrong document."""
    return max((r.number for r in corpus.requirements), default=0) + 1


def slugify(title: str, *, limit: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return (slug[:limit].rstrip("-") or "requirement")


def render_requirement(
    draft: RequirementDraft, *, number: int, asked_by: str = "", date: str = "",
    source: str = "",
) -> str:
    """The requirement as it will live in the repository — the same shape as the template, because
    a document a human cannot edit by hand is not a document, it is a database with extra steps."""
    status = "proposed"
    lines = [
        f"# REQ-{number:04d} — {draft.title}",
        "",
        f"- **Status:** {status}",
        f"- **Asked by:** {asked_by or 'unrecorded'}",
        f"- **Date:** {date or 'unrecorded'}",
        f"- **Supersedes:** {', '.join(f'REQ-{n:04d}' for n in draft.supersedes) or '—'}",
    ]
    if source:
        lines.append(f"- **Source:** {source}")
    lines += ["", "## Why", "", draft.why.strip() or "(not stated)", ""]

    lines += ["## What must be true", ""]
    lines += [f"- [ ] {c}" for c in draft.must_be_true] or ["- [ ] (nothing stated)"]
    lines += [""]

    lines += ["## Out of scope", ""]
    lines += [f"- {c}" for c in draft.out_of_scope] or ["- (nothing stated)"]
    lines += [""]

    lines += ["## Affects", ""]
    lines += [f"- `{c}`" for c in draft.affects] or ["- (not stated)"]
    lines += [""]

    if draft.conflicts:
        # Conflicts are recorded IN the document, not just reported in chat. A contradiction found
        # while drafting and then lost in a Slack scrollback is a contradiction that gets
        # rediscovered the expensive way.
        lines += ["## Conflicts raised while drafting", ""]
        for c in draft.conflicts:
            ref = f"REQ-{c.requirement:04d}" if c.requirement else "an existing requirement"
            lines.append(f"- **{c.kind}** {ref} — {c.explanation}")
        lines += [""]

    if draft.questions:
        lines += ["## Open questions", ""]
        lines += [f"- {q}" for q in draft.questions]
        lines += [""]

    lines += [
        f"## {DECISIONS_HEADING}",
        "",
        # THREE COLUMNS, and the person goes in the third with the channel. A fourth column would
        # have been cleaner to read and would have HIDDEN the answer: every requirement already
        # written for the live client has this three-column header, and GitHub's renderer silently
        # drops cells past the header's width. A row carrying the person as a fourth cell would
        # render without them — a provenance field that looks recorded and shows nothing.
        "| date | decision | who decided, and where |",
        "|---|---|---|",
        "",
    ]
    return "\n".join(lines)


def _git(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """One git call, AUTHORED AS THE BOT.

    THE IDENTITY IS CARRIED, NEVER ASSUMED. This module ran `git commit` on the ambient config,
    which is a bet that whoever built the worker image happened to run `git config --global
    user.email`. Where that bet loses, git refuses the commit with *"Please tell me who you
    are"* — and every requirement the product role writes fails, on a container that is
    otherwise perfectly healthy.

    Found by the platform's own CI (2026-08-05), which is a clean machine with no git identity —
    and a clean machine is exactly what a fresh deployment's container is. `machine.py::_commit`
    had carried the identity since the beginning; this file simply never learned the same lesson.

    `-c` rather than env vars: it applies to commits and leaves every other git call unchanged,
    and it cannot be lost by a subprocess that rebuilds its environment."""
    from openfactory.credentials import bot_identity

    bot = bot_identity()
    ident = ["-c", f"user.name={bot.name}", "-c", f"user.email={bot.email}"]
    p = subprocess.run(["git", *ident, *args], cwd=cwd, capture_output=True, text=True,
                       timeout=_GIT_TIMEOUT, check=False)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _scrub(text: str) -> str:
    return re.sub(r"(https://)[^@/\s]+@", r"\1***@", text or "")


def branch_for(number: int, title: str) -> str:
    """Deterministic, so a retry lands on the branch it already created instead of a second one."""
    return f"req/{number:04d}-{slugify(title, limit=32)}"


def _fold_replacement_conflicts(draft: RequirementDraft) -> RequirementDraft:
    """A `duplicates` conflict naming a requirement IS the replace instruction — fold it in.

    THE LIVE 0001/0002 CORRUPTION CAME THROUGH THIS GAP. The drafter returned `supersedes=[]` plus
    a machine-readable conflict `{kind: "duplicates", requirement: 1, "Ele deve substituir o texto
    do Requisito 1, não passar a existir ao lado dele"}` — and the propose acted only on
    `supersedes`, rendered the conflict to prose, and landed 0002 beside a still-live 0001: two
    `proposed` texts for one promise, the exact state the drafter had just said must not happen.
    The replace intent and the commit have to travel together; prose in the file is a record,
    never an act.

    Only `duplicates` folds. A `contradicts`/`narrows`/`depends_on` conflict is a tension for a
    person to resolve — retiring the old text on one of those would put a decision in their mouth.
    """
    dup = {c.requirement for c in draft.conflicts if c.kind == "duplicates" and c.requirement}
    if not dup.difference(draft.supersedes):
        return draft
    merged = sorted(set(draft.supersedes) | dup)
    log.warning("OPENFACTORY_PRODUCT_SUPERSEDE_FOLDED the draft's duplicates conflict(s) name %s — "
                "folded into supersedes=%s so the replacement is acted on, not narrated",
                sorted(dup), merged)
    return draft.model_copy(update={"supersedes": merged})


def _live_twins(root: Path, requirements_dir: str, *, slug: str,
                number: int) -> list[tuple[int, str]]:
    """`(number, status)` of every LIVE requirement already carrying the slug being written — one
    promise wearing two numbers, read off the clone before anything is committed.

    The STATUS travels because the two cases are not the same act. Retiring a text nobody agreed to
    loses no decision; retiring an ACCEPTED one revokes a promise, and that is a person's to make.

    THE THIRD DOOR ONTO THE TWO-LIVE-VERSIONS STATE, and the only one a drafter cannot be asked to
    close. The first two — a revision, and a `duplicates` conflict — are cases where the model
    KNOWS it is replacing something and says so. This one is the case where it does not: on
    2026-07-30 the conversation called the new text "the final version of requirement 2", the
    drafter therefore named only requirement 1 as replaced (which was true, and incomplete), and
    since this platform has no update-in-place the rewrite minted 0003 and left 0002 standing
    beside it. Two `proposed` texts for one promise, one turn after the second door was shut.

    Deterministic, because the tell is arithmetic and not judgment: the slug comes from the title,
    so an identical slug is an identical title. Read with the corpus's own parser rather than a
    private one — the pair that drifted apart is exactly how the status line was missed before.
    """
    from openfactory.product.corpus import load_corpus

    folder = root / requirements_dir.strip("/")
    if not folder.is_dir():
        return []
    return sorted((r.number, r.status) for r in load_corpus(folder).requirements
                  if r.slug == slug and r.number != number and r.is_live)


#: `req/0007-relatorio-mensal` → (7, "relatorio-mensal")
_REQ_BRANCH_RE = re.compile(r"^req/(?P<num>\d{4})-(?P<slug>.*)$")

#: The branch prefix every proposal lives under, and the filter the port narrows on SERVER-side.
#: A documentation repository with a thousand branches must not be paged through a client that
#: wants nine of them — and it is a string prefix, so the trailing slash is load-bearing: `req`
#: would also match `requirements-cleanup`.
REQ_PREFIX = "req/"


def _requirement_branches(forge, docs_repo: str) -> list[tuple[int, str]] | None:
    """`(number, slug)` for every `req/*` branch on the remote — the proposals pushed but not yet
    landed, which the base corpus cannot see. **`None` when they could not be listed at all.**

    THROUGH THE PORT (#97), which is what makes the number minting work off GitHub. This shelled
    out to `gh api repos/{docs_repo}/branches`, so on an Azure Repos deployment the runner refused
    (correctly — it would have exported that project's Microsoft credential to github.com) and the
    answer was an empty list. Empty is not a harmless degrade here: it is the input to the decision
    that mints a requirement's NUMBER, and minting from the base alone is how two files come to
    claim NNNN, which is the citation corruption `next_number`'s own docstring warns about.

    SO A FAILED READ IS `None` AND NOT `[]`, and the caller refuses instead of minting. The old
    docstring argued the opposite — "minting from the base alone is exactly what happened before,
    not something worse" — and that was true only while the two answers were indistinguishable. The
    port distinguishes them, so the caller can act on the difference, and this is the one place in
    this module where a wrong empty is not recoverable by a later sweep: a number, once written into
    a filename and cited by a card, is what the whole corpus keys on.

    `forge is None` is that same answer: a caller that offered no forge cannot have read anything.
    """
    if forge is None:
        return None
    names = forge.list_branches(docs_repo, prefix=REQ_PREFIX)
    if names is None:
        return None
    out: list[tuple[int, str]] = []
    for name in names:
        m = _REQ_BRANCH_RE.match(str(name).strip())
        if m:
            out.append((int(m.group("num")), m.group("slug")))
    return out


def _already_proposed(forge, docs_repo: str, branch: str) -> str | None:
    """The pull request this branch was already proposed as — `""` when there is none, `None` when
    the question could not be asked.

    ANY STATE, which is the question idempotency actually asks. A closed or merged pull request is
    still an answer of `yes, this was proposed`, and opening a second one for the same work is what
    this check exists to prevent. `pr_for_head` is deliberately wider than the `open_pr`
    implementations' own private lookup for exactly that reason.

    THE `None` ARM IS THE WHOLE POINT OF ASKING THROUGH THE PORT. `gh pr list … --jq .[0].url`
    answers "" both for a branch nobody ever proposed and for a repository it could not reach, and
    a caller writing `if not found: propose()` files the duplicate on the transient failure. The
    check is `is None`.
    """
    if forge is None:
        return None
    return forge.pr_for_head(branch, repo=docs_repo)


def propose_requirement(
    *,
    docs_repo: str,
    clone_url: str,
    draft: RequirementDraft,
    number: int,
    requirements_dir: str = "requirements",
    #: THE FORGE ADAPTER — every read and every pull-request act below goes through it, on every
    #: vendor. Not optional in production (`ProductModule.propose` builds it from the registry),
    #: and `None` here is not a default that quietly falls back to something else: it means the
    #: branch state could not be read, and this function refuses rather than minting a number
    #: against a board it never saw. A fallback would be a second path that only tests ever take,
    #: which is how this codebase's signature defect gets in.
    forge=None,
    asked_by: str = "",
    date: str = "",
    source: str = "",
    base: str = "main",
    #: ACCEPTED AND IGNORED, both of them, and named here rather than deleted. They fed the `gh`
    #: subprocess this module used to run; the forge adapter carries its own credential and its own
    #: vendor, so neither is read any more. They stay because
    #: `openfactory/product/module.py:1003,1006`
    #: still passes them and that file belongs to another pass: removing the parameters would raise
    #: TypeError inside the `except Exception` that wraps the call, and the client would be told
    #: "não consegui registrar esse requisito agora" for every requirement, on a path that works.
    #: Delete the argument and the parameter in the same commit, never one of the two.
    token: str = "",
    forge_kind: str = GITHUB,
) -> WriteResult:
    """Open (or find) the pull request that proposes one requirement, then land it.

    A fresh clone rather than the read cache: the cache is `reset --hard` on every use by design, so
    committing into it would race every reader. Writes are rare enough that a clone is the cheap
    option, and it keeps the read path exactly as it was.

    ONE MECHANISM NOW, AND IT IS THE PORT (#95). Listing the proposal branches, asking whether this
    one was ever proposed, opening the review request, merging it, reading the state back and
    deleting the landed branch are all `ForgeAdapter` calls — so this works on Azure Repos exactly
    as it works on GitHub, proven live on both (an Azure Repos `org/project/fx-dsk-context` and a
    GitHub `org/fx-dsk-context`, 2026-08-06). Until `open_pr`, `merge_pr` and `pr_status`
    took a repository, they could only speak about the repository the adapter was built for — the
    CODE — while every call here is about the DOCUMENTATION repository, so this half shelled out to
    `gh` and simply refused on any other vendor.

    WHAT SURVIVED FROM THAT REFUSAL IS ITS HONESTY. A pull request that does not open still returns
    `ok=False` with the branch and the number it minted, and says the text is safe and the review
    request is not open. Nothing here can answer "PR opened" without a URL the forge handed back."""
    # A "duplicates" conflict naming a requirement IS the replace instruction — folded into
    # `supersedes` BEFORE anything is rendered, so the file, the PR body and the retire stamp all
    # agree. The live corpus corruption came through this exact gap (see the helper).
    draft = _fold_replacement_conflicts(draft)
    # THE NUMBER IS MINTED AGAINST THE BASE *AND* THE UNLANDED BRANCHES. `number` arrives derived
    # from the base corpus, which cannot see a proposal pushed but never landed (a pr-create
    # failure leaves exactly that, until the weekly sweep rescues it). Re-minting such a number
    # files a SECOND requirement under one identity: two files claiming NNNN, `by_number` and the
    # supersede stamp then acting on whichever sorts first — the citation corruption
    # `next_number`'s own docstring warns about. A branch carrying THIS draft's slug is prior
    # work, and its number is adopted so a retry converges on itself instead of stepping past it.
    own_slug = slugify(draft.title, limit=32)
    branches = _requirement_branches(forge, docs_repo)
    if branches is None:
        # I COULD NOT READ, WHICH IS NOT THE SAME AS THERE IS NOTHING. Minting a number against a
        # board this call never saw is how two requirements come to share one identity — and unlike
        # an unopened pull request, that one is not repairable by a later sweep: the number is in
        # the filename, in the card that cites it and in the supersede stamp.
        log.error("OPENFACTORY_PRODUCT_BRANCHES_UNREADABLE repo=%s — the proposal branches could "
                  "not be "
                  "listed, so %04d was NOT minted and nothing was written", docs_repo, number)
        return WriteResult(ok=False,
                           detail="não consegui conferir o que já foi escrito antes, então não "
                                  "registrei nada. Sem essa conferência eu poderia gravar este "
                                  "texto com o número de outro requisito. Nada se perdeu — me "
                                  "peça de novo daqui a pouco.")
    own = [n for n, s in branches if s == own_slug]
    rivals = [n for n, s in branches if s != own_slug]
    if own:
        # OUR OWN PRIOR BRANCH WINS OVER EVERY RIVAL, AND THE `if` IS ON `own` ALONE. It used to be
        # `if own and max(own + [number]) != number`, which is only true when the prior attempt was
        # itself bumped — so in the ORDINARY retry, where nothing landed and the base still mints
        # the same number the prior attempt used, the adoption arm was a no-op and control fell
        # through to the rival bump below. FOUND LIVE on an Azure Repos `org/project/fx-ado`
        # (2026-08-06): with `req/0001-prova-viva…` (ours) and `req/0002-segunda-prova…` (a rival)
        # already pushed, re-proposing the FIRST draft minted `req/0003-prova-viva…` — a third
        # branch and a third number for a text that already had one.
        #
        # That is the corruption the whole paragraph above exists to prevent, produced by the
        # retry it exists to make idempotent, and it compounds: 0001, 0003, 0005… one per attempt,
        # each a live file with the same title. It was invisible on GitHub only because the
        # pull-request lookup a few lines down returns first — and the one state where it does not
        # is a branch pushed with NO pull request, which is exactly what a `pr create` failure
        # leaves behind (it left production in that state for weeks) and what a forge whose PR
        # ceremony the port cannot reach yet is in permanently.
        adopted = max(own + [number])
        if adopted != number:
            log.warning("OPENFACTORY_PRODUCT_NUMBER_ADOPTED repo=%s: a prior attempt "
                        "already pushed "
                        ""
                        "this "
                        "draft as %04d — adopting it instead of minting %04d",
                        docs_repo, max(own), number)
        number = adopted
    elif rivals and max(rivals) >= number:
        log.warning("OPENFACTORY_PRODUCT_NUMBER_BUMPED repo=%s: the base mints %04d but "
                    "an unlanded "
                    ""
                    ""
                    "req/* branch already claims up to %04d — minting %04d so two requirements "
                    "never share a number", docs_repo, number, max(rivals), max(rivals) + 1)
        number = max(rivals) + 1
    body_text = render_requirement(draft, number=number, asked_by=asked_by, date=date,
                                   source=source)
    branch = branch_for(number, draft.title)
    path = f"{requirements_dir.rstrip('/')}/{number:04d}-{slugify(draft.title)}.md"

    # already proposed? A retry must find its own PR, not open a second one.
    found = _already_proposed(forge, docs_repo, branch)
    if found is None:
        log.error("OPENFACTORY_PRODUCT_PRIOR_PROPOSAL_UNREADABLE repo=%s branch=%s — could not ask "
                  "whether this requirement was already proposed; nothing was written", docs_repo,
                  branch)
        return WriteResult(ok=False,
                           detail="não consegui verificar se esse requisito já tinha sido escrito "
                                  "antes, então não registrei nada — assim não fico com dois "
                                  "pedidos para a mesma coisa. Nada se perdeu; me peça de novo "
                                  "daqui a pouco.")
    if found.strip():
        return WriteResult(ok=True, url=found.strip(), ref=branch, existed=True, number=number,
                           detail="a pull request for this requirement already exists")
    if number in own:
        # THE TEXT IS ALREADY ON THE REMOTE AND THE REVIEW REQUEST IS WHAT IS MISSING. `number in
        # own` says our own branch for this exact draft exists (that is how `own` was built), and
        # the two answers above say no pull request was ever opened from it — the state a failed
        # `open_pr` leaves behind.
        #
        # Cloning on to fail is what happened before, and it failed in the worst possible place:
        # the push is rejected as a non-fast-forward, and the client's whole reply becomes
        # `could not push req/0003-…: ! [rejected]`. Measured on `fx-ado` (2026-08-06). Two things
        # are wrong with that and only one is cosmetic — the other is that `ref` and `number` come
        # back EMPTY, so the act that did write requirement 3 reports having minted nothing.
        #
        # Nothing is re-pushed on purpose: the branch already carries this draft, committed by the
        # attempt that created it with the same supersession and twin decisions this one would
        # take. A retry converges by recognising its own work, not by rewriting it.
        # AND IT MUST NOT CLAIM AN ALERT NOBODY SENDS. The sentence this returned was copied from
        # the `open_pr` failure below — *"o time foi avisado e conclui isso"* — and neither is
        # true from here. Nothing on this path opens an impediment:
        # `OPENFACTORY_PRODUCT_ALREADY_PUSHED`
        # is a log line, and `_could_not`/`_tell_the_factory`, the seams that DO reach a person,
        # are never on it. The completion half used to be worse still, because it was false exactly
        # where this branch was PERMANENT: `land_open_proposals` is the sweep that finishes a stuck
        # proposal, it ran on `gh`, and on any other forge it refused — so on those deployments the
        # promise that somebody was finishing it repeated forever. That half is fixed (#95): the
        # sweep now runs through the port on every vendor, so this state is a retry away from
        # resolving itself and no longer a dead end. The sentence still does not claim a person was
        # told, because none is. This module's own board reader carries the line about what the
        # other way costs: *"the client was told a colleague had been alerted who did not exist."*
        #
        # So it says what is true and leaves the person with something to do (the standing rule:
        # never a silent wait — self-heal, or offer a human an option). Retrying is real: the
        # branch is recognised rather than rewritten, so a later attempt converges on this same
        # number the moment the review request can be opened.
        log.warning("OPENFACTORY_PRODUCT_ALREADY_PUSHED repo=%s branch=%s — the requirement is on "
                    "the "
                    "remote with no pull request; not re-pushing it", docs_repo, branch)
        return WriteResult(ok=False, ref=branch, number=number,
                           detail="esse requisito já está escrito e guardado em segurança; o que "
                                  "falta é abrir o pedido de revisão, e isso eu não consigo fazer "
                                  "daqui. Nada se perdeu e nada precisa ser reescrito: me peça de "
                                  "novo mais tarde, ou peçam ao time para dar esse último passo.")

    tmp = Path(tempfile.mkdtemp(prefix="openfactory-req-"))
    try:
        rc, out = _git(["clone", "--depth", "1", "--branch", base, clone_url, str(tmp)])
        if rc != 0:
            return WriteResult(ok=False,
                               detail=f"could not clone {docs_repo}: {_scrub(out)[-200:]}")

        rc, out = _git(["checkout", "-b", branch], cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False, detail=f"could not create {branch}: {_scrub(out)[-200:]}")

        # READ THE BASE BEFORE WRITING INTO IT. A live requirement already carrying this slug is
        # the same promise under an older number, whether or not the drafter noticed — and it is
        # only visible here, in the clone. Folded now so the FILE, the pull request body and the
        # retire stamp are rendered from one list; discovering it after `render_requirement` and
        # patching only the stamp would ship a file whose own `Supersedes:` line disagrees with
        # what the commit did.
        # A DRAFTER MAY NAME SOMETHING ALREADY DEAD, and on 2026-07-31 one did: REQ-0005 had been
        # dropped hours earlier and the new text claimed to supersede it. Left in, the FILE would
        # claim a supersession the commit deliberately does not perform (`_mark_superseded` skips
        # a dropped requirement), and `_cross_check` would rightly call that an error. The claim
        # and the act travel together or neither goes.
        dead = _already_dead(tmp, requirements_dir, draft.supersedes)
        if dead:
            log.warning("OPENFACTORY_PRODUCT_SUPERSEDE_ALREADY_DEAD repo=%s: the draft names %s, "
                        "which "
                        "is already off the table — dropped from the claim so the file does not "
                        "assert a replacement nobody performed", docs_repo,
                        ", ".join(f"{n:04d}" for n in dead))
            draft = draft.model_copy(update={
                "supersedes": [n for n in draft.supersedes if n not in dead]})

        twins = [(n, st) for n, st in _live_twins(tmp, requirements_dir,
                                                  slug=slugify(draft.title), number=number)
                 if n not in draft.supersedes]
        # AN ACCEPTED TWIN IS A PROMISE, AND REVOKING ONE IS NOT A TIDY-UP. The unagreed twin is
        # folded because retiring a text nobody accepted loses no decision. An accepted one is a
        # commitment the factory currently defends, and replacing it silently — on nothing but a
        # matching title — would put a decision in somebody's mouth, the same reason a
        # `contradicts` conflict is never folded. So: refuse, and say what would make it legal.
        # The person makes it explicit, the drafter records it in `supersedes`, and this passes.
        promised = [n for n, st in twins if st == ACCEPTED]
        if promised:
            listed = ", ".join(str(n) for n in promised)
            log.error("OPENFACTORY_PRODUCT_TWIN_IS_A_PROMISE repo=%s: %s is accepted and carries "
                      "this "
                      "exact title; the draft does not say it replaces it — nothing committed",
                      docs_repo, listed)
            return WriteResult(
                ok=False,
                detail=f"já existe um requisito acordado com esse mesmo título (o {listed}), e "
                       f"este texto não diz que veio no lugar dele. Não registrei nada: deixar os "
                       f"dois valendo faria a fábrica defender um ou outro conforme lesse "
                       f"primeiro, e aposentar uma promessa sozinha não é minha decisão. Me diga "
                       f"que este texto substitui o {listed} e eu registro.")
        unagreed = sorted(n for n, _ in twins)
        if unagreed or dead:
            merged = sorted(set(draft.supersedes) | set(unagreed))
            log.warning("OPENFACTORY_PRODUCT_SUPERSEDE_TWIN repo=%s: %s already live under this "
                        "exact "
                        "title and never agreed — folded into supersedes=%s so one promise keeps "
                        "one number", docs_repo,
                        ", ".join(f"{n:04d}" for n in unagreed), merged)
            draft = draft.model_copy(update={"supersedes": merged})
            body_text = render_requirement(draft, number=number, asked_by=asked_by, date=date,
                                           source=source)

        target = tmp / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body_text, encoding="utf-8")
        # BOTH SIDES OF A SUPERSESSION, IN THE SAME COMMIT. The new file declaring "Supersedes:
        # REQ-0001" is only half of it — `corpus.live()` decides what is current by reading each
        # requirement's OWN status, so an old file that never learns it was replaced stays live.
        # The result is two `proposed` texts for one promise, and a factory that would defend
        # whichever it read first. Written together so the two can never disagree — and when the
        # old side CANNOT be stamped, nothing lands: half a supersession is exactly the two-live-
        # versions state, committed on purpose.
        retired, failed = _mark_superseded(tmp, requirements_dir, draft.supersedes, by=number)
        if failed:
            log.error("OPENFACTORY_PRODUCT_SUPERSEDE_FAILED repo=%s could not retire %s in favour "
                      "of "
                      "%04d — nothing was committed", docs_repo,
                      ", ".join(f"{n:04d}" for n in failed), number)
            return WriteResult(ok=False,
                               detail="esse texto substitui um requisito que já existe, mas não "
                                      "consegui marcar a versão antiga como substituída. Não "
                                      "registrei nada — assim não ficam duas versões valendo ao "
                                      "mesmo tempo. O time foi avisado e resolve.")
        for path_of_retired in retired:
            _git(["add", "--", path_of_retired], cwd=tmp)

        _git(["add", "--", path], cwd=tmp)
        message = (f"REQ-{number:04d}: {draft.title}\n\n"
                   f"Proposed from a product conversation"
                   + (f" with {asked_by}" if asked_by else "") + ".\n"
                   + (f"Source: {source}\n" if source else ""))
        rc, out = _git(["commit", "-m", message], cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False, detail=f"nothing to commit: {_scrub(out)[-200:]}")

        rc, out = _git(["push", "-u", clone_url, branch], cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False, detail=f"could not push {branch}: {_scrub(out)[-200:]}")

        pr_body = _pr_body(draft, number=number, asked_by=asked_by, source=source)
        url = _open_review_request(forge, docs_repo=docs_repo, head=branch, base=base,
                                   title=f"REQ-{number:04d}: {draft.title}", body=pr_body)
        if not url:
            # the branch is pushed, so the work is not lost — say exactly that
            # THE WORK IS SAFE AND THE CLIENT IS NOT ASKED TO DO GIT. The previous text named the
            # branch, was in English, and told the person to "open it by hand against main" — three
            # things ADR-0026 forbids in one sentence, to somebody who runs an accounting firm and
            # cannot open a pull request. What they need to know is that nothing was lost and that
            # it is the team's to finish.
            # THE NUMBER TRAVELS EVEN THOUGH THE WRITE FAILED, because this write DID mint one: the
            # file is committed and pushed under it, and `number`'s own contract is what this act
            # produced rather than whether it finished. It matters more now than when this branch
            # was only a `gh` outage — on a forge whose pull-request half the port cannot reach
            # yet, this WAS the ordinary outcome of a successful proposal — and reporting 0 would
            # have the channel tell a client about requirement zero. It is an exception again now
            # that the port opens the pull request on every vendor (#95), which is the whole point,
            # and the number still travels because that has never depended on the vendor.
            log.error("OPENFACTORY_PRODUCT_PR_FAILED branch=%s base=%s repo=%s — pushed, no PR",
                      branch, base, docs_repo)
            return WriteResult(ok=False, ref=branch, number=number,
                               detail="escrevi o requisito e guardei em segurança, mas não "
                                      "consegui abrir o pedido de revisão. Nada se perdeu — o time "
                                      "foi avisado e conclui isso.")
        # MERGE IT. The content was approved by an authorised person in the channel, in business
        # language; the pull request is mechanism. Leaving it open costs three things: a person must
        # perform a git operation on a business artefact, the client gets a GitHub link they cannot
        # act on, and THE ROLE CANNOT SEE ITS OWN WORK — it reads the docs branch, so an unmerged
        # requirement does not exist from where it stands. Asked about a requirement she had just
        # written, she answered "do meu lado ela está vazia", and she was right.
        #
        # Merging still does NOT accept: the file lands with `status: proposed`, and the promise the
        # factory defends is created by a separate human confirmation in the channel (ADR-0032).
        merged = _merge_and_confirm(forge, docs_repo=docs_repo, pr=url)
        if merged:
            _delete_landed_branch(forge, docs_repo, branch)
        elif merged is None:
            log.error("OPENFACTORY_PRODUCT_MERGE_UNCONFIRMED repo=%s pr=%s — the merge was "
                      "requested and "
                      "its outcome could not be read back. Reported as NOT landed: announcing a "
                      "merge on no evidence is the one thing this read-back exists to prevent, and "
                      "the hourly sweep converges on whichever it turns out to be", docs_repo, url)
        else:
            log.warning("OPENFACTORY_PRODUCT_PR_UNMERGED repo=%s branch=%s — the proposal stays "
                        "open and "
                        "the role cannot see it", docs_repo, branch)
        # THE NUMBER THIS WRITE MINTED, carried back so the client is told what happened rather
        # than what was predicted. `number` above may have been adopted from a prior attempt or
        # bumped past an unlanded rival; either way it is what the file is called.
        return WriteResult(ok=True, url=url, ref=branch, merged=merged is True, number=number)
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def _pr_body(draft: RequirementDraft, *, number: int, asked_by: str, source: str) -> str:
    parts = [f"Proposes **REQ-{number:04d} — {draft.title}**.", ""]
    if asked_by:
        parts += [f"Asked by {asked_by}.", ""]
    if draft.conflicts:
        # first, because it is the reason a reviewer might reject this outright
        parts += ["## ⚠ Conflicts with what the product already promises", ""]
        for c in draft.conflicts:
            ref = f"REQ-{c.requirement:04d}" if c.requirement else "an existing requirement"
            parts.append(f"- **{c.kind}** {ref} — {c.explanation}")
        parts += [""]
    if draft.questions:
        parts += ["## Open questions", ""] + [f"- {q}" for q in draft.questions] + [""]
    parts += ["## What must be true", ""] + [f"- {c}" for c in draft.must_be_true] + [""]
    parts += ["---", "",
              "Merging this is the sign-off on the requirement. It does **not** start any work: "
              "issues are filed into Backlog and a human promotes them to TO-DO."]
    if source:
        parts += ["", f"Source: {source}"]
    return "\n".join(parts)


def requirement_file(requirement, *, requirements_dir: str = "") -> str:
    """Where a requirement's file actually IS in the documentation repository — THE renderer.

    THE CORPUS STORES THE FILENAME. `parse_requirement` keeps `path.name`, because the corpus is
    loaded from the requirements folder and knows nothing above it; the file lives under the
    manifest's `requirements_dir`. So the raw field names no location, and every citation this
    platform writes is FOLLOWED — by a person opening it, and by the executor told not to go
    beyond it.

    ONE FUNCTION BECAUSE THE LESSON COST FOUR REPAIRS. `accept` learned it (every acceptance
    answered "não encontrei o requisito" about a requirement it had just listed), then the issue
    filer, then the alignment, then the orphan repair — and `defect_body` was still printing the
    bare field, so a defect card sent whoever picked it up to a path that does not exist. A fifth
    writer inherits the fix instead of rediscovering the trap.

    Callers pass the RESULT, never the requirement: `issue_body` and `defect_body` both take a
    resolved `requirement_path`, so there is nowhere left for a renderer to reach for `.path`.
    """
    directory = (requirements_dir or "").strip("/")
    name = getattr(requirement, "path", "") or ""
    return f"{directory}/{name}" if directory and name else name


def issue_body(draft: IssueDraft, *, requirement_path: str, docs_repo: str,
               commit: str = "", docs_url: str = "") -> str:
    """An issue that cites the requirement it executes — path, and the commit it was read from.

    The citation is what makes the issue a unit of EXECUTION rather than a second, drifting copy of
    the requirement. Same source-linking discipline the code map uses, for the same reason.

    `requirement_path` is the resolved location (`requirement_file`), never the corpus's bare
    filename.

    `docs_url` IS PASSED IN AND NOT COMPUTED, and "" renders the repository as plain text with no
    link at all. This function used to call a `_repo_url` helper that read `GH_HOST` and was
    therefore provider-aware in APPEARANCE and wrong in fact: on an Azure Repos deployment it
    produced `https://dev.azure.com/<repo>`, which addresses nothing, and with the variable unset a
    `github.com` link to a repository that may belong to somebody else. The provenance line is the
    one thing that makes an authored issue auditable, so a wrong link there is strictly worse than
    none — and only the caller, which can reach the project's forge, knows the right one
    (`ProductModule._docs_url`)."""
    parts = [f"## Objective\n\n{draft.objective.strip()}", ""]
    if draft.acceptance_criteria:
        parts += ["## Acceptance criteria", ""]
        parts += [f"- [ ] {c}" for c in draft.acceptance_criteria]
        parts += [""]
    if draft.out_of_scope:
        parts += ["## Out of scope", ""] + [f"- {c}" for c in draft.out_of_scope] + [""]
    cite = f"REQ-{draft.cites:04d}" if draft.cites else "a requirement"
    ref = f"`{requirement_path}`" + (f" @ `{commit[:12]}`" if commit else "")
    where = f"[{docs_repo}]({docs_url})" if docs_url else f"`{docs_repo}`"
    parts += [
        "## Source",
        "",
        f"Executes **{cite}** in {where} — {ref}.",
        "",
        "Nothing in this issue may go beyond that requirement. If the work needs a decision that "
        "is not written there, the decision belongs in the document first.",
    ]
    return "\n".join(parts)


def land_open_proposals(*, docs_repo: str, forge=None, base: str = "main",
                        token: str = "") -> list[str] | None:
    """Get every `req/*` branch INTO THE BASE — opening its review request if missing, then merging.

    `[]` = swept, nothing needed landing. `None` = THE SWEEP DID NOT RUN, which is a different fact
    and used to be spelled the same way. A caller that reads them alike reports "no proposals are
    stuck" about a repository it never managed to look at, which is this codebase's most expensive
    defect class wearing the sweep's clothes.

    THE RECOVERY USED TO STOP HALFWAY. Its first version opened the pull request and left it open,
    which recreates the very state it exists to clear: the requirement is on a branch, the base does
    not have it, and THE ROLE CANNOT READ ITS OWN WORK. Nina found that within one message —
    "Quantos requisitos existem: zero" — and reasoned to the cause herself: "ou o texto foi gravado
    num lugar que ainda não chegou até a versão que eu leio". She was right, and the half-recovery
    was mine.

    Merging is safe here for the same reason it is safe on the happy path (ADR-0032): the file lands
    as `proposed`, and only a person's confirmation in the channel makes it a promise. Landing it
    changes who can READ it, not what it means.

    Idempotent by construction: a merged branch is deleted, so the next sweep does not see it —
    and when that invariant breaks anyway (it did: `req/0002` outlived its squash-merged PR in the
    live client repo), the merged pull request is RECOGNISED and the leftover branch deleted,
    instead of re-proposing a requirement already in the base on every sweep forever.

    THIS WAS THE LAST FUNCTION HERE THE PORT COULD NOT CARRY, AND THE REASON WAS ITS SHAPE RATHER
    THAN ITS PLUMBING (#97, closed by #95). Every branch it looks at leads to exactly one of four
    acts, and three of them needed a method that could name a repository:

        no pull request ever          →  open one           `open_pr(…, repo=)`
        one exists, MERGED            →  delete the branch  `delete_branch(…, repo=)`
        one exists, CLOSED            →  leave it alone     (a person said no)
        one exists, still open        →  merge it           `merge_pr(…, repo=)`

    and telling those rows apart needs `pr_status(pr=…, repo=)`, because `pr_for_head` answers
    WHETHER a branch was ever proposed and deliberately not which state it is in. Porting the
    branch listing alone would have bought a sweep that can see every stuck proposal on an Azure
    deployment and do nothing about any of them. All four are here now, and `delete_branch` — built
    and, until this, consumed by nothing — finally has the caller its own docstring names.

    THE CLOSED ROW IS NEW AND IT IS A DELIBERATE CHANGE OF BEHAVIOUR. The `gh` version asked for
    MERGED pull requests, then for OPEN ones, and opened a fresh one when it saw neither — so a
    proposal a human had closed was re-proposed on the next pass, and the one after that, for ever.
    A closed pull request is somebody's answer of no; re-asking hourly is the loop this platform
    exists not to build. It is left alone, and said out loud in the log, because a `req/*` branch
    nobody wants is a person's to delete, not ours.

    `token` IS ACCEPTED AND IGNORED, exactly as in `propose_requirement`, and for the same reason:
    `runtime/temporal/activities.py::_land_product_proposals` still passes it. That call site is
    ALSO the one that does not pass a `forge` — so until it does, this sweep answers None on every
    hourly round and says so at ERROR. That is the honest shape of the gap and not a silent one,
    but it IS a gap: the fix is `forge=ProductModule(project)._forge()` at that call site, in a
    file this pass does not own.
    """
    if forge is None:
        # NOT `[]`. A sweep with no forge read nothing, decided nothing and landed nothing, and the
        # caller's `if rescued:` cannot tell that from a clean repository unless the two answers
        # differ. The ERROR is what a person greps for; the None is what a caller can branch on.
        log.error("OPENFACTORY_PRODUCT_SWEEP_NO_FORGE repo=%s — the proposal sweep was given no "
                  "forge "
                  "adapter, so it could not look at a single branch. Nothing is stuck BECAUSE OF "
                  "this, and nothing has been checked either: any requirement whose review request "
                  "failed stays out of the base, and the product role goes on denying it.",
                  docs_repo)
        return None
    names = forge.list_branches(docs_repo, prefix=REQ_PREFIX)
    if names is None:
        log.error("OPENFACTORY_PRODUCT_SWEEP_UNREADABLE repo=%s — the proposal branches could not "
                  "be "
                  "listed, so nothing was swept. Reported as 'could not', never as 'nothing to do'",
                  docs_repo)
        return None
    landed: list[str] = []
    for branch in sorted(names):
        # ANY STATE, and that is the fix that stopped the sweep re-proposing landed work. Asking
        # only for OPEN pull requests (while `propose_requirement`'s own idempotency check asks for
        # all of them) is what made this open a fresh client-visible "Requisito proposto" PR for a
        # branch whose content was already squash-merged — on every pass, forever.
        pr = _already_proposed(forge, docs_repo, branch)
        if pr is None:
            log.warning("OPENFACTORY_PRODUCT_SWEEP_BRANCH_UNREADABLE repo=%s branch=%s — could not "
                        "ask "
                        "whether it was ever proposed; left exactly as it is", docs_repo, branch)
            continue
        state = _pr_state(forge, docs_repo, pr) if pr else ""
        if state is None:
            log.warning("OPENFACTORY_PRODUCT_SWEEP_STATE_UNREADABLE repo=%s branch=%s pr=%s "
                        "— could "
                        ""
                        "not "
                        "read whether it is merged, closed or open; left alone rather than acted "
                        "on with a guess", docs_repo, branch, pr)
            continue
        if state == "merged":
            log.warning("OPENFACTORY_PRODUCT_PROPOSAL_ALREADY_LANDED repo=%s branch=%s — its pull "
                        "request is merged; deleting the leftover branch so the sweep converges",
                        docs_repo, branch)
            _delete_landed_branch(forge, docs_repo, branch)
            continue
        if state == "closed":
            log.warning("OPENFACTORY_PRODUCT_PROPOSAL_DISCARDED repo=%s branch=%s pr=%s — a person "
                        "closed "
                        "it without merging, so it is not stuck, it is refused. Not re-proposed "
                        "and not deleted: the text stays on the branch for whoever wants it back",
                        docs_repo, branch, pr)
            continue
        if not pr:
            pr = _open_review_request(
                forge, docs_repo=docs_repo, head=branch, base=base,
                title=f"Requisito proposto: {branch.split('/', 1)[-1]}",
                body="Aberto pela varredura de propostas que ficaram fora da base: o texto tinha "
                     "sido escrito e enviado, mas o pedido de revisão não chegou a abrir. Nada foi "
                     "reescrito — este pedido é sobre exatamente o que já estava salvo.")
            if not pr:
                log.warning("OPENFACTORY_PRODUCT_ORPHAN_STUCK repo=%s branch=%s — could not open a "
                            "review "
                            "request; the text is safe on the branch", docs_repo, branch)
                continue
        merged = _merge_and_confirm(forge, docs_repo=docs_repo, pr=pr)
        if merged:
            log.warning("OPENFACTORY_PRODUCT_PROPOSAL_LANDED repo=%s branch=%s", docs_repo, branch)
            _delete_landed_branch(forge, docs_repo, branch)
            landed.append(branch)
        elif merged is None:
            log.error("OPENFACTORY_PRODUCT_PROPOSAL_UNCONFIRMED repo=%s branch=%s pr=%s — "
                      "the merge "
                      ""
                      "was "
                      "requested and its outcome could not be read back; NOT counted as landed, "
                      "and the next pass settles it", docs_repo, branch, pr)
        else:
            log.warning("OPENFACTORY_PRODUCT_PROPOSAL_STILL_OPEN repo=%s branch=%s — the base does "
                        "not "
                        "have it and the product role cannot read it", docs_repo, branch)
    return landed


def _mark_superseded(root: Path, requirements_dir: str, numbers: list[int], *,
                     by: int) -> tuple[list[str], list[int]]:
    """Stamp `superseded-by` on each retired requirement — `(paths changed, numbers that FAILED)`.

    Finds the file by NUMBER PREFIX rather than by slug: the retired requirement's title is not
    knowable from here, and guessing it would silently retire nothing.

    THE STATUS LINE IS FOUND WITH THE READER'S OWN REGEX (`corpus._STATUS_RE`). This used to
    require exactly `- **status:**` while the parser deliberately tolerates hand-edited variants
    ("a human editing by hand should not lose a requirement's status to a missing asterisk") — so
    a parser-valid file silently kept both versions of one promise live, with only a log line to
    show for it. A number that cannot be retired (no file, no readable status line) comes back in
    `failed`, and the caller must refuse to land half a supersession.

    A requirement that already carries a `superseded-by` is left alone — the first supersession is
    the one that happened, and overwriting it would rewrite history to point at the newest text
    rather than the one that actually replaced it.
    """
    changed: list[str] = []
    failed: list[int] = []
    folder = root / requirements_dir.strip("/")
    for n in numbers or []:
        matches = sorted(folder.glob(f"{n:04d}-*.md")) if folder.is_dir() else []
        if not matches:
            log.warning("OPENFACTORY_PRODUCT_SUPERSEDE_MISSING requisito %04d não existe", n)
            failed.append(n)
            continue
        file = matches[0]
        text = file.read_text(encoding="utf-8")
        if re.search(r"superseded[-\s]?by", text, re.IGNORECASE):
            continue
        if _is_dropped(text):
            # ALREADY OFF THE TABLE, AND FOR A REASON SOMEBODY GAVE. Stamping `superseded-by` over
            # a `dropped` status replaces "we decided against this, here is who and why" with
            # "read that one instead" — and leaves the `Dropped by:` line underneath contradicting
            # the status above it. Exactly that happened to REQ-0005 on 2026-07-31, hours after
            # `dropped` was introduced: `is_live`, the status reader and the acceptance writer all
            # learned about the new dead state and this writer did not.
            log.warning("OPENFACTORY_PRODUCT_SUPERSEDE_SKIPPED_DROPPED requisito %04d já foi "
                        "abandonado "
                        "por decisão de alguém — o registro de quem decidiu e por quê vale mais "
                        "que um ponteiro para %04d", n, by)
            continue
        lines = text.splitlines()
        idx = next((i for i, line in enumerate(lines) if _STATUS_RE.match(line)), None)
        if idx is None:
            log.warning("OPENFACTORY_PRODUCT_SUPERSEDE_NO_STATUS %s tem formato "
                        "inesperado", file.name)
            failed.append(n)
            continue
        lines[idx] = f"- **Status:** superseded-by {by:04d}"
        file.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
        changed.append(f"{requirements_dir.strip('/')}/{file.name}")
    return changed, failed


def _already_dead(root: Path, requirements_dir: str, numbers: list[int]) -> list[int]:
    """Of `numbers`, those whose requirement is already superseded or dropped.

    Read from the clone with the corpus's own parser, because a claim about the base has to be
    checked against the base and not against what a model believed when it drafted."""
    from openfactory.product.corpus import load_corpus

    folder = root / requirements_dir.strip("/")
    if not folder.is_dir() or not numbers:
        return []
    corpus = load_corpus(folder)
    return sorted(n for n in numbers
                  if (req := corpus.by_number(n)) is not None and not req.is_live)


def _is_dropped(text: str) -> bool:
    """Whether this file records a decision AGAINST — read with the corpus's own status regex, so
    a hand-edited variant the parser tolerates is not silently overwritten by a writer that is
    stricter than the reader."""
    m = _STATUS_RE.search(text)
    value = re.sub(r"<!--.*?-->", "", m.group("value") if m else "").strip().lower()
    return value.split()[0] == DROPPED if value else False


def _open_review_request(forge, *, docs_repo: str, head: str, base: str, title: str,
                         body: str) -> str:
    """Open the pull request that proposes `head` in the DOCUMENTATION repository — the URL, or
    `""` when none was opened.

    THE PORT'S `open_pr` RAISES AND THIS ONE DOES NOT, and the reason is where each of them sits.
    The port is right to raise: for a job, a pull request that could not be opened must stop the
    job, and there is no return value that could mean "I could not tell" without a caller reading
    it as success. Here the requirement is ALREADY committed and pushed — the write that mattered
    happened — so throwing that away to report the ceremony's failure would lose the half that
    worked. Every caller in this module already treats `""` as "the review request did not open"
    and says so to the person, with the branch and the number the write minted.

    `""` IS NEVER "IT WORKED", which is the only property that has to survive whatever else changes
    here. This used to be a `gh` subprocess that returned "" on a non-GitHub deployment — an honest
    refusal, and the honesty is what had to be kept when the refusal stopped being necessary (#95).
    """
    try:
        return (forge.open_pr(head=head, base=base, title=title, body=body,
                              repo=docs_repo) or "").strip()
    except Exception as exc:  # noqa: BLE001 — every provider's failure means the same thing here
        log.error("OPENFACTORY_PRODUCT_PR_CREATE_FAILED repo=%s head=%s base=%s — the "
                  "forge refused "
                  ""
                  "to "
                  "open the review request (%s). The text is committed and pushed; only the pull "
                  "request is missing", docs_repo, head, base, _scrub(str(exc))[:300])
        return ""


def _pr_state(forge, docs_repo: str, pr: str) -> str | None:
    """`"merged"` | `"closed"` | `"open"` for a pull request in the docs repository — `None` when it
    could not be read.

    THE THIRD ANSWER IS THE POINT, as everywhere else on this seam. The port's `pr_status` raises
    rather than guessing, which is right for a durable merge-watch that will be retried; here the
    caller is an hourly sweep and a proposal it cannot classify must simply be left alone until the
    next pass. Turning the raise into `None` is what lets it skip ONE branch instead of abandoning
    the whole sweep — and `None` can never be mistaken for a state, which `"open"` could."""
    try:
        return forge.pr_status(pr=pr, repo=docs_repo)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not read the state of %s in %s (%s)", pr, docs_repo,
                    _scrub(str(exc))[:200])
        return None


def _merged_now(forge, docs_repo: str, pr: str, *, attempts: int | None = None,
                delay: float | None = None) -> bool | None:
    """Whether that pull request is actually merged — ASKED, never assumed, and WAITED FOR.

    `True` = merged. `False` = read, and not merged. `None` = could not be read at all, which the
    caller must not report as either.

    ASKED, because `merge_pr` returns None on success and on an armed-but-unfired auto-merge alike:
    its return is no evidence whatsoever. Reading the state back is the difference between "we
    merged it" and "we ran a command", and announcing a merge that did not happen is the same
    defect class as announcing a write that did not happen (ADR-0028) — ours, not the agent's.

    WAITED FOR, because on one vendor the merge is not instant and a single read would call an
    honest merge a failure. Azure DevOps completes asynchronously by design: measured live through
    the adapter, `merge_pr` returned in 0.8s and the pull request read `open` at +1.0s and `merged`
    at +2.4s. GitHub answered on the first read. The wait costs one round trip in the common case,
    because it stops the moment the answer is not `open`.

    A `closed` answer stops the wait immediately and is False: somebody abandoned the pull request
    while we were watching, and no amount of patience turns that into a merge.

    THE TWO BOUNDS ARE READ AT CALL TIME AND NOT TAKEN AS DEFAULT ARGUMENTS. A default is evaluated
    when the `def` runs, so `_MERGE_DELAY = 0` set by a test — or by anything else — would be bound
    to the module constant's ORIGINAL value and change nothing, which is the trap the `GITHUB`
    constant at the top of this file already carries a note about. Here it would cost ten real
    seconds per unmerged proposal in every suite run.
    """
    tries = max(1, _MERGE_ATTEMPTS if attempts is None else attempts)
    pause = _MERGE_DELAY if delay is None else delay
    unreadable = False
    for attempt in range(tries):
        state = _pr_state(forge, docs_repo, pr)
        if state == "merged":
            return True
        if state == "closed":
            return False
        if state is None:
            unreadable = True
        if attempt + 1 < tries:
            time.sleep(pause)
    # Every read said "open" → False, an answer. Any read failed and none said merged → None, the
    # absence of one. Collapsing these is how a merge that silently did not happen gets announced.
    return None if unreadable else False


def _merge_and_confirm(forge, *, docs_repo: str, pr: str, attempts: int | None = None,
                       delay: float | None = None) -> bool | None:
    """Merge, then read the outcome back. `True`/`False`/`None` — see `_merged_now`.

    A REFUSED MERGE IS STILL READ BACK, ON PURPOSE AND WITH ONE ATTEMPT. The commonest reason a
    merge is refused is that the pull request is already merged — a retried activity, a sweep
    passing over work the propose path just landed — and treating that as a failure would have the
    sweep re-open and re-merge for ever. But there is nothing in flight to wait for once the call
    was refused, so the read-back is a single question rather than ten seconds of patience."""
    try:
        forge.merge_pr(pr=pr, repo=docs_repo)
    except Exception as exc:  # noqa: BLE001
        log.warning("OPENFACTORY_PRODUCT_MERGE_REFUSED repo=%s pr=%s (%s) — asking once whether it "
                    "is "
                    "already merged, which is the commonest reason a merge is refused", docs_repo,
                    pr, _scrub(str(exc))[:200])
        return _merged_now(forge, docs_repo, pr, attempts=1, delay=delay)
    return _merged_now(forge, docs_repo, pr, attempts=attempts, delay=delay)


def _delete_landed_branch(forge, docs_repo: str, branch: str) -> None:
    """Remove a `req/*` branch whose pull request is IN THE BASE — the `--delete-branch` half of
    the `gh pr merge` this module used to run, through the port.

    NOT TIDINESS. `_requirement_branches` reads every surviving `req/*` branch as a proposal in
    flight, and that list is an input to the NUMBER the next requirement gets; `land_open_proposals`
    re-examines the branch on every hourly pass for ever. A leftover branch is therefore a permanent
    fact about a requirement that has already landed — the exact state `req/0002` was found in on
    the live client repository, outliving its squash-merged pull request.

    ONLY EVER CALLED ON A CONFIRMED MERGE. Deleting on an assumed one would delete work.

    `delete_branch` never raises and answers False when the branch may still be there, so a failure
    here is one log line and nothing more: the requirement landed, and the next sweep sees the
    branch again."""
    if not forge.delete_branch(branch, repo=docs_repo):
        log.warning("OPENFACTORY_PRODUCT_BRANCH_NOT_DELETED repo=%s branch=%s — it landed and the "
                    "branch "
                    "is still on the remote; the next sweep will recognise it as merged and try "
                    "again", docs_repo, branch)


def defect_body(*, restated: str, reported_by: str, severity: str, source: str,
                requirement, requirement_path: str, docs_repo: str, commit: str = "") -> str:
    """The issue body for a broken promise — classified, and citing what it breaks.

    The executor reads this cold, so everything it needs is HERE: what reality is doing, which
    promise says otherwise (verbatim quote, not just a number — the docs checkout may move), and
    how bad it is for the person who reported it. A defect that cites nothing is indistinguishable
    from a feature request wearing an angry tone, and it would be built as one.

    `requirement_path` is REQUIRED and comes from `requirement_file`, exactly like `issue_body`'s.
    This function used to render `requirement.path` itself — the corpus's bare filename — so the
    one card that names a promise pointed at a file nobody can open. Taking the resolved path is
    what makes the two bodies share one answer to "where does that requirement live"."""
    lines = ["**Tipo:** defeito — o produto está violando uma promessa já aceita"]
    if severity:
        # only when somebody actually judged one. The first version printed "Gravidade: média"
        # from a hardcoded default — a fabricated classification the fix queue would sort by.
        lines.append(f"**Gravidade:** {severity}")
    lines.append(f"**Reportado por:** {reported_by or 'não registrado'}")
    if source:
        lines.append(f"**Onde foi reportado:** {source}")
    lines += ["", "## O que está acontecendo", "", restated.strip(), ""]
    if requirement is not None:
        lines += [
            f"## A promessa violada — REQ-{requirement.number:04d}",
            "",
            f"`{requirement_path}` em `{docs_repo}`"
            + (f" (lido no commit `{commit[:12]}`)" if commit else ""),
            "",
            "O comportamento descrito acima contradiz o que este requisito promete. A correção "
            "deve restaurar a promessa — se a promessa é que está errada, isso é uma DECISÃO de "
            "produto e deve voltar como alteração do requisito, não como código.",
        ]
    else:
        lines += [
            "## A promessa violada",
            "",
            "Não foi possível apontar o requisito específico que este comportamento viola — o "
            "sintoma é claro, a promessa não. Quem pegar isto deve identificar a promessa "
            "quebrada ANTES de corrigir; se nenhuma existir, devolver ao produto: pode ser um "
            "pedido novo disfarçado de defeito.",
        ]
    return "\n".join(lines)


def record_fact(*, docs_repo: str, clone_url: str, term: str, body: str, said_by: str,
                where: str = "", base: str = "main", today: str | None = None) -> WriteResult:
    """Commit one `aprendido` fact straight to the docs branch — deliberately NOT a pull request.

    Requirements go through a PR because the factory DEFENDS them once accepted; a fact enters as
    `aprendido` — attributed, dated, and explicitly non-authoritative (domain.py's discipline) —
    so the review ceremony would add friction exactly where the goal is that people bother to say
    things out loud. The audit trail is the git history plus the attribution inside the file, and
    promotion to `confirmado` is a deliberate, human edit."""
    from datetime import UTC, datetime

    from openfactory.product.domain import Fact, render_file

    day = today or datetime.now(UTC).date().isoformat()
    fact = Fact(term=term.strip(), body=body.strip(), status="aprendido",
                source=said_by.strip(), where=where.strip(), learned_on=day)
    path = f"domain/{day}-{slugify(term, limit=40)}.md"

    tmp = Path(tempfile.mkdtemp(prefix="openfactory-fact-"))
    try:
        rc, out = _git(["clone", "--depth", "1", "--branch", base, clone_url, str(tmp)])
        if rc != 0:
            return WriteResult(ok=False,
                               detail=f"could not clone {docs_repo}: {_scrub(out)[-200:]}")
        target = tmp / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            render_file([fact], title=f"Fato: {fact.term}",
                        intro=f"Anotado numa conversa com {said_by}."),
            encoding="utf-8")
        _git(["add", "--", path], cwd=tmp)
        rc, out = _git(["commit", "-m",
                        f"fato: {fact.term}\n\nDito por {said_by}"
                        + (f" em {where}" if where else "") + "."], cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False, detail=f"nothing to commit: {_scrub(out)[-200:]}")
        rc, out = _git(["push", clone_url, f"HEAD:{base}"], cwd=tmp)
        if rc != 0:
            # a protected branch is the docs repo owner's right — say exactly what to do instead
            return WriteResult(ok=False,
                               detail=f"o repositório não aceita registro direto "
                                      f"({_scrub(out)[-120:]}); anote à mão em {path}")
        return WriteResult(ok=True, ref=path)
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


#: What a decision cell may never contain unescaped: a pipe would split one decision into two
#: cells and shift every later column, so the row renders as a different sentence than the person
#: approved. Escaped rather than rejected — refusing a decision because it contains a "|" would be
#: the platform's own table format leaking into what a client is allowed to decide.
_CELL_UNSAFE = str.maketrans({"|": "\\|", "\n": " ", "\r": " "})


def _cell(value: str, limit: int = 400) -> str:
    return (value or "").translate(_CELL_UNSAFE).strip()[:limit] or "(não declarado)"


def add_decision_row(text: str, *, day: str, decision: str, who: str,
                     where: str = "") -> tuple[str, str]:
    """`(updated_text, outcome)` — append one row to the decision register.

    `outcome` is "written", "no-section" (the file predates the template, or somebody removed it)
    or "duplicate" (this exact decision is already recorded on this day).

    APPENDED AT THE END OF THE SECTION, NEVER AFTER THE LAST `|` LINE IN THE FILE. The naive
    version finds the last table row and writes under it — and a requirement whose "Affects" or
    "Conflicts" section happens to hold a table gets the decision written into THAT one, where
    `has_decisions` will never see it and `no-write-back` goes on complaining about a decision the
    client watched being recorded.
    """
    span = find_decisions_table(text)
    if span is None:
        return text, "no-section"
    start, end = span
    body = text[start:end]
    row = f"| {day} | {_cell(decision)} | {_cell(who + (f' — {where}' if where else ''), 200)} |"
    if row.strip() in {line.strip() for line in body.splitlines()}:
        # the same decision, the same day, the same person: a retried confirmation, not a second
        # decision. Writing it twice would make one act look like two in the only record that
        # answers "how often did this change?"
        return text, "duplicate"
    lines = body.rstrip().splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    return text[:start] + "\n".join([*lines, row]) + "\n" + text[end:], "written"


def record_decision(*, docs_repo: str, clone_url: str, path: str, number: int,
                    decision: str, decided_by: str, where: str = "", base: str = "main",
                    today: str | None = None) -> WriteResult:
    """Write one decision into a requirement's register — THE WRITER THAT DID NOT EXIST.

    The register was rendered by `render_requirement`, read by `corpus._decision_rows`, and
    `_cross_check` even emitted `no-write-back` when an agreed requirement recorded no decision.
    Nothing anywhere wrote a row. So the role proposed recording a dated, attributed decision, a
    client would have confirmed it, and the answer would have been narration over an empty table —
    the third instance of that class in one day.

    IT MATTERS MORE THAN IT LOOKS. This is where the provenance of a decision taken AFTER the
    acceptance lives. Without it the decision exists on a card nobody opens in three months, or in
a conversation that scrolls. The role said it better than anybody: *"if this only goes on the
    card, in three months nobody knows where it came from or that you
    were the one who decided."*

    Committed straight to the docs branch, exactly like `accept_requirement` and for the same
    reason: an authorised person said so in the channel, and a pull request reviewing a sentence
    nobody is arguing about is the ceremony that teaches people to click through.
    """
    import datetime

    day = today or datetime.datetime.now(datetime.UTC).date().isoformat()
    if not (decision or "").strip():
        return WriteResult(ok=False, detail="não entendi qual foi a decisão para registrar")
    tmp = Path(tempfile.mkdtemp(prefix="openfactory-decision-"))
    try:
        rc, out = _git(["clone", "--depth", "1", "--branch", base, clone_url, str(tmp)])
        if rc != 0:
            return WriteResult(ok=False,
                               detail=f"could not clone {docs_repo}: {_scrub(out)[-200:]}")
        target = tmp / path
        if not target.is_file():
            return WriteResult(ok=False,
                               detail=f"não encontrei o requisito {number} para registrar a "
                                      f"decisão")
        text = target.read_text(encoding="utf-8")
        updated, outcome = add_decision_row(text, day=day, decision=decision,
                                            who=decided_by, where=where)
        if outcome == "duplicate":
            return WriteResult(ok=True, ref=path, existed=True,
                               detail="essa decisão já estava registrada hoje")
        if outcome == "no-section":
            # SAID, not silently appended. A requirement written before the template had this
            # section is a real state in the live client's base, and inventing the heading here
            # would put a table in a file whose shape nobody chose — the repair belongs to a
            # person who can look at the document.
            log.warning("OPENFACTORY_PRODUCT_NO_DECISION_SECTION repo=%s path=%s — the requirement "
                        "has "
                        "no '%s' section, so there is nowhere to record a decision",
                        docs_repo, path, DECISIONS_HEADING)
            return WriteResult(ok=False,
                               detail=f"o requisito {number} não tem a tabela de decisões no "
                                      f"documento, então não consegui gravar lá. Avisei o time.")
        target.write_text(updated, encoding="utf-8")
        _git(["add", "--", path], cwd=tmp)
        rc, out = _git(["commit", "-m",
                        f"requisito {number:04d}: decisão registrada por {decided_by}"], cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False, detail=f"nothing to commit: {_scrub(out)[-200:]}")
        rc, out = _git(["push", clone_url, f"HEAD:{base}"], cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False,
                               detail=f"o repositório não aceita registro direto "
                                      f"({_scrub(out)[-120:]})")
        return WriteResult(ok=True, ref=path)
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def accept_requirement(*, docs_repo: str, clone_url: str, path: str, number: int,
                       accepted_by: str, base: str = "main",
                       today: str | None = None) -> WriteResult:
    """Flip one requirement from `proposed` to `accepted` — THE ONLY ACT THAT CREATES A PROMISE.

    THIS STEP DID NOT EXIST. `accepted` was read in four places — it is what makes the factory
    DEFEND a statement — and written by nothing. A requirement was born `proposed` and stayed
    `proposed` unless somebody edited the markdown by hand. So a product sold as needing no
    developer required two developer operations per requirement: merge a pull request, then edit a
    field in a file.

    Committed straight to the docs branch rather than through a pull request, deliberately: the TEXT
    was already reviewed and merged; what changes here is one field, and it changes because an
    authorised person said so in the channel. A second review of a word nobody is arguing about is
    ceremony, and ceremony is what teaches people to click through.

    The date and the person are recorded in the same edit — `corpus.py` flags an accepted
    requirement missing either, and an acceptance nobody can attribute is not one.
    """
    import datetime

    day = today or datetime.datetime.now(datetime.UTC).date().isoformat()
    tmp = Path(tempfile.mkdtemp(prefix="openfactory-accept-"))
    try:
        rc, out = _git(["clone", "--depth", "1", "--branch", base, clone_url, str(tmp)])
        if rc != 0:
            return WriteResult(ok=False,
                               detail=f"could not clone {docs_repo}: {_scrub(out)[-200:]}")
        target = tmp / path
        if not target.is_file():
            return WriteResult(ok=False, detail=f"não encontrei o requisito {number} para aceitar")
        text = target.read_text(encoding="utf-8")
        updated, outcome = _set_status_accepted(text, accepted_by=accepted_by, day=day)
        if outcome == "already":
            return WriteResult(ok=True, ref=path, existed=True,
                               detail="esse requisito já estava acordado")
        if outcome != "flipped":
            # NEVER "already agreed", whatever the reason. Reporting a status that did not flip as
            # a prior agreement is exactly how the live client was told "já estava acordado" while
            # the file stayed `proposed`, no promise existed, and "quebra o requisito N" kept
            # answering "ainda não foi acordado" in the same channel. Which refusal this is —
            # theirs to act on, or ours to repair — belongs to `_accept_refusal`.
            _say_unflippable("OPENFACTORY_PRODUCT_ACCEPT_UNFLIPPABLE", docs_repo=docs_repo,
                             path=path,
                             outcome=outcome)
            return WriteResult(ok=False, ref=path, detail=_accept_refusal(number, outcome))
        target.write_text(updated, encoding="utf-8")
        _git(["add", "--", path], cwd=tmp)
        rc, out = _git(["commit", "-m", f"requisito {number:04d}: acordado por {accepted_by}"],
                       cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False, detail=f"nothing to commit: {_scrub(out)[-200:]}")
        rc, out = _git(["push", clone_url, f"HEAD:{base}"], cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False,
                               detail=f"o repositório não aceita registro direto "
                                      f"({_scrub(out)[-120:]})")
        return WriteResult(ok=True, ref=path)
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def drop_requirement(*, docs_repo: str, clone_url: str, path: str, number: int,
                     dropped_by: str, reason: str = "", base: str = "main",
                     today: str | None = None) -> WriteResult:
    """Mark one requirement as decided against — the act with no replacement.

    THE LIFECYCLE HAD NO WAY TO SAY "NOT THIS". A requirement could be written, agreed and replaced,
    and every one of those needs somebody to author a NEW text; there was no way to say a thing
    simply will not be done. The product owner named it in one line — *"something that will no
    longer be done — isn't that very common in a conversation with a PO?"* — and it is: it is the
    second most common thing that happens to a requirement after being written.

    Retiring by writing a replacement is what the platform could already do, and it is the wrong
    shape for this: it forces an invention (a text nobody wants) to record an absence.

    Committed straight to the docs branch, like the acceptance and for the same reason: one field
    changes, and it changes because an authorised person said so in the channel. A pull request
    reviewing the removal of something nobody is building is ceremony.

    WHO AND WHY ARE THE POINT. A requirement that quietly stops being current is indistinguishable
    from one that was lost; six months later "why aren't we doing this?" has to have an answer in
    the file rather than in somebody's memory of a chat.
    """
    import datetime

    day = today or datetime.datetime.now(datetime.UTC).date().isoformat()
    tmp = Path(tempfile.mkdtemp(prefix="openfactory-drop-"))
    try:
        rc, out = _git(["clone", "--depth", "1", "--branch", base, clone_url, str(tmp)])
        if rc != 0:
            return WriteResult(ok=False,
                               detail=f"could not clone {docs_repo}: {_scrub(out)[-200:]}")
        target = tmp / path
        if not target.is_file():
            return WriteResult(ok=False,
                               detail=f"não encontrei o requisito {number} para dar como "
                                      f"abandonado")
        text = target.read_text(encoding="utf-8")
        updated, outcome = _set_status_dropped(text, dropped_by=dropped_by, day=day, reason=reason)
        if outcome == "already":
            return WriteResult(ok=True, ref=path, existed=True,
                               detail=f"o requisito {number} já estava dado como abandonado")
        if outcome != "flipped":
            _say_unflippable("OPENFACTORY_PRODUCT_DROP_UNFLIPPABLE", docs_repo=docs_repo, path=path,
                             outcome=outcome)
            return WriteResult(ok=False, ref=path, detail=_drop_refusal(number, outcome))
        target.write_text(updated, encoding="utf-8")
        _git(["add", "--", path], cwd=tmp)
        message = f"requisito {number:04d}: abandonado por {dropped_by}"
        rc, out = _git(["commit", "-m", message + (f"\n\n{reason}" if reason else "")], cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False, detail=f"nothing to commit: {_scrub(out)[-200:]}")
        rc, out = _git(["push", clone_url, f"HEAD:{base}"], cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False,
                               detail=f"o repositório não aceita registro direto "
                                      f"({_scrub(out)[-120:]})")
        return WriteResult(ok=True, ref=path)
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


#: Refusals that are a STATE OF THE LIFECYCLE, not a damaged file. Both status writers refuse on
#: them and neither may report them as breakage: an `error` marker raised because somebody
#: deliberately retired a requirement is the noise that teaches a supervisor to skim the one that
#: means a file nobody can parse is sitting in the corpus.
_SETTLED = ("dropped", "superseded")


def _say_unflippable(marker: str, *, docs_repo: str, path: str, outcome: str) -> None:
    """The operator's half of a refused status change — one line, one severity rule, two writers."""
    log.log(logging.INFO if outcome in _SETTLED else logging.ERROR,
            "%s repo=%s path=%s — %s; nothing was changed", marker, docs_repo, path, outcome)


def _accept_refusal(number: int, outcome: str) -> str:
    """Why the acceptance did not happen, in words the person can act on — `_drop_refusal`'s
    sibling, drawing the same distinction on the other side of the lifecycle.

    A requirement the client THEMSELVES abandoned, and one that was written over, are business
    answers with a next step each; only the third is ours to fix. One sentence for all three tells
    somebody who dropped a requirement yesterday that their own decision is a text nobody can read
    and that a team is on its way to repair it — an apology for a file that is perfectly healthy,
    and an invented fix nobody will perform.
    """
    if outcome == "dropped":
        return (f"o requisito {number} tinha sido dado como abandonado, então não há promessa a "
                f"registrar — não mexi em nada. Se ele voltou a valer, me peça de novo e eu "
                f"escrevo o texto outra vez para vocês confirmarem.")
    if outcome == "superseded":
        return (f"o requisito {number} já tinha sido substituído por outro, então acordar com ele "
                f"seria assumir um texto que já não vale — não mexi em nada. Me diga o número do "
                f"que ficou no lugar dele e eu registro esse.")
    return (f"não consegui registrar o acordo do requisito {number}: o texto dele está num formato "
            f"que não reconheço com segurança. Não mudei nada — o time foi avisado e resolve.")


def _drop_refusal(number: int, outcome: str) -> str:
    """Why the drop did not happen, in words the person can act on.

    A requirement already REPLACED is a different answer from one whose file we cannot read: the
    first is "there is nothing to abandon, it is already off the table", the second is ours to fix.
    One sentence for both would send the reader hunting the wrong thing.
    """
    if outcome == "superseded":
        return (f"o requisito {number} já tinha sido substituído por outro, então ele já não "
                f"valia — não mexi em nada. Se o que você quer é abandonar o texto que ficou no "
                f"lugar dele, me diga o número dele.")
    return (f"não consegui dar o requisito {number} como abandonado: o texto dele está num "
            f"formato que não reconheço com segurança. Não mudei nada — o time foi avisado e "
            f"resolve.")


def _set_status_dropped(text: str, *, dropped_by: str, day: str,
                        reason: str = "") -> tuple[str, str]:
    """`(new text, outcome)` — `"flipped"`, `"already"`, or what is wrong.

    Shares `corpus._STATUS_RE` with the reader and with every other writer here, which is the
    discipline that stopped the acceptance silently flipping nothing for weeks.

    ANY LIVE STATE CAN BE ABANDONED, including `accepted`. That is deliberate and it is the whole
    point: deciding not to do something you had promised is a normal business event, and a
    lifecycle that only lets you drop things nobody agreed to would force the one case that most
    needs a record to happen by hand. What it must never be is quiet — the caller gates it behind
    an explicit confirmation, and the file keeps who and why.
    """
    lines = text.splitlines()
    idx = next((i for i, line in enumerate(lines) if _STATUS_RE.match(line)), None)
    if idx is None:
        return text, "no status line the corpus parser could read either"
    raw = _STATUS_RE.match(lines[idx]).group("value")
    value = re.sub(r"<!--.*?-->", "", raw).strip().lower()
    word = value.split()[0] if value else ""
    if word == DROPPED:
        return text, "already"
    if word.startswith(SUPERSEDED):
        # already off the table, and pointing at a replacement. Overwriting that would erase the
        # pointer a reader follows to find what took its place.
        return text, "superseded"
    if word not in (PROPOSED, OBSERVED, ACCEPTED):
        return text, f"status is {value!r}, which is not a state anything can be dropped from"

    lines[idx] = f"- **Status:** {DROPPED}"
    stamp = f"- **Dropped by:** {dropped_by} on {day}"
    if reason:
        stamp += f" — {reason.strip()}"
    lines.insert(idx + 1, stamp)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), "flipped"


def _set_status_accepted(text: str, *, accepted_by: str, day: str) -> tuple[str, str]:
    """`(new text, outcome)` — `"flipped"`, `"already"`, or what is wrong (operator English).

    THE STATUS LINE IS FOUND WITH THE READER'S OWN REGEX (`corpus._STATUS_RE`), never a private
    pattern. This function used to match only a bare `status:` — a shape no producer of
    requirement files has ever written (`render_requirement`, the brownfield writer and the
    template all emit `- **Status:** …`), so on every real file it changed nothing and the caller
    announced "já estava acordado" over a requirement still `proposed`. One pattern shared with
    the parser is what makes that drift structurally impossible; `_mark_superseded` follows the
    same discipline.

    Only the two pre-promise states flip: `proposed`, and `observed` — a reverse-engineered
    reading whose confirmation by a person is, by brownfield.py's own contract, the one event that
    turns it into a commitment. Everything else is a problem for the caller to REFUSE on, never an
    "already agreed". A requirement already `accepted` returns `"already"` unchanged, so a second
    confirmation cannot quietly rewrite who agreed to it — and `unrecorded`, render's placeholder
    for provenance nobody supplied, is treated as absence and filled; a real name never is.
    """
    lines = text.splitlines()
    idx = next((i for i, line in enumerate(lines) if _STATUS_RE.match(line)), None)
    if idx is None:
        return text, "no status line the corpus parser could read either"
    raw = _STATUS_RE.match(lines[idx]).group("value")
    value = re.sub(r"<!--.*?-->", "", raw).strip().lower()
    word = value.split()[0] if value else ""
    if word.startswith("accepted"):
        return text, "already"
    if word == DROPPED:
        # named apart from the generic refusal: "we decided against this" is a thing the person
        # can act on (ask for it again, and it is drafted fresh), while "unrecognised format" is
        # a thing only the team can
        return text, "dropped"
    if word.startswith(SUPERSEDED):
        # and so is this one, for the same reason and with a different next step: a replacement
        # exists, so the person has a number to accept instead. `_set_status_dropped` names it
        # apart already; a bare "not a pre-promise state" here is the caller's only input.
        return text, "superseded"
    if word not in ("proposed", "observed"):
        return text, f"status is {value!r}, which is not a pre-promise state"
    lines[idx] = re.sub(word, "accepted", lines[idx], count=1, flags=re.IGNORECASE)

    # who and when, IN THE BULLET SHAPE THE PARSER READS BACK. The bare `asked_by:` lines the old
    # version inserted were invisible to corpus._field_re, so even a successful accept would have
    # tripped the no-asker/no-date warnings it exists to satisfy.
    extra: list[str] = []
    for pattern, label, fresh in ((_ASKED_RE, "Asked by", accepted_by), (_DATE_RE, "Date", day)):
        j = next((i for i, line in enumerate(lines) if pattern.match(line)), None)
        if j is None:
            extra.append(f"- **{label}:** {fresh}")
            continue
        existing = re.sub(r"<!--.*?-->", "", pattern.match(lines[j]).group("value")).strip()
        if not existing or existing.lower() == "unrecorded":
            lines[j] = f"- **{label}:** {fresh}"
    if extra:
        lines[idx + 1:idx + 1] = extra
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), "flipped"


def propose_baseline(*, docs_repo: str, clone_url: str, files: dict[str, str],
                     product: str, observations: int, covered: list[str],
                     base: str = "main", forge=None,
                     #: accepted and ignored — see `propose_requirement`. `module.py:1371,1372`
                     #: still passes both.
                     token: str = "", forge_kind: str = GITHUB) -> WriteResult:
    """The brownfield first pass as ONE pull request — inventory plus every candidate.

    One PR, not forty: a team asked to review forty requirement PRs reviews none, and the exercise
    dies in its first week (brownfield.py's opening argument). The branch is deterministic, so a
    retry finds its own PR instead of opening a second.

    Everything inside lands as `observed` — a reading of the code, never a promise. The PR body
    says so in the first line, because this is the one moment where somebody could mistake a
    reverse-engineered description for something the product agreed to.

    `forge` is the same contract as `propose_requirement`'s: the idempotency question goes through
    the port, and a caller that hands no forge could not have asked it. Getting that arm wrong here
    is the most expensive duplicate this module can file — a second baseline is forty candidate
    requirements proposed twice, at a moment whose whole design argument is that a team asked to
    review forty pull requests reviews none.

    NOT MERGED, unlike a requirement proposal, and that difference is the point of the whole
    exercise: everything inside is `observed`, and a human reading it and deciding what is really a
    promise IS the deliverable. Landing it unread would turn a reverse-engineered description into
    the base the factory answers from."""
    branch = "product/baseline"

    found = _already_proposed(forge, docs_repo, branch)
    if found is None:
        log.error("OPENFACTORY_PRODUCT_PRIOR_PROPOSAL_UNREADABLE repo=%s branch=%s — could not ask "
                  "whether the baseline was already proposed; nothing was written",
                  docs_repo, branch)
        return WriteResult(ok=False,
                           detail="não consegui verificar se esse levantamento já tinha sido "
                                  "feito antes, então não escrevi nada — assim não fico com dois "
                                  "levantamentos iguais para vocês revisarem. Me peça de novo "
                                  "daqui a pouco.")
    if found.strip():
        return WriteResult(ok=True, url=found.strip(), ref=branch, existed=True,
                           detail="o levantamento já tinha sido proposto")

    # OUR OWN BRANCH, PUSHED, WITH NO PULL REQUEST ON IT — the window between the push below and
    # `_open_review_request`, which a rate limit, an expired token or a worker dying lands in.
    # Without this arm the verb WEDGES PERMANENTLY: the next run finds no pull request, clones
    # fresh, commits, and its `push -u` is rejected as non-fast-forward against the branch the
    # first attempt left behind. Every subsequent first pass fails the same way, on a repository
    # where nothing is wrong except that a PR was never opened.
    #
    # This is also why the workflow no longer retries. The docstring there argued the verb was
    # idempotent — true of the happy path, asserted of all of them, and this is the path it
    # skipped.
    try:
        pushed = branch in {str(b) for b in (forge.list_branches() or ())}
    except Exception:  # noqa: BLE001 — an unreadable branch list is not a reason to write twice
        log.info("could not list %s's branches before proposing a baseline", docs_repo,
                 exc_info=True)
        pushed = False
    if pushed:
        url = _open_review_request(
            forge, docs_repo=docs_repo, head=branch, base=base,
            title=f"Levantamento inicial sobre {product}",
            body="A branch deste levantamento já tinha sido enviada numa tentativa anterior que "
                 "não chegou a abrir o pull request. Este PR abre o que ficou faltando — o "
                 "conteúdo é o daquela passagem, e continua tudo como `observed`.")
        if url:
            return WriteResult(ok=True, url=url, ref=branch, existed=True,
                               detail="o levantamento já estava enviado; só faltava abrir o "
                                      "pedido de revisão, e abri agora")
        return WriteResult(ok=False, ref=branch,
                           detail=f"a branch {branch} já está enviada de uma tentativa anterior e "
                                  f"o pull request não abriu; abra à mão contra {base}")

    tmp = Path(tempfile.mkdtemp(prefix="openfactory-baseline-"))
    try:
        rc, out = _git(["clone", "--depth", "1", "--branch", base, clone_url, str(tmp)])
        if rc != 0:
            return WriteResult(ok=False,
                               detail=f"could not clone {docs_repo}: {_scrub(out)[-200:]}")
        rc, out = _git(["checkout", "-b", branch], cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False, detail=f"could not create {branch}: {_scrub(out)[-200:]}")

        for path, body in sorted(files.items()):
            target = tmp / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
            _git(["add", "--", path], cwd=tmp)

        rc, out = _git(["commit", "-m",
                        f"baseline: {observations} observações sobre {product}\n\n"
                        f"Leitura do código como ele está hoje. Tudo entra como `observed` — "
                        f"nada aqui é promessa até alguém confirmar."], cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False, detail=f"nothing to commit: {_scrub(out)[-200:]}")
        rc, out = _git(["push", "-u", clone_url, branch], cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False, detail=f"could not push {branch}: {_scrub(out)[-200:]}")

        body = "\n".join([
            f"**Isto é uma LEITURA do código, não um conjunto de requisitos.** {observations} "
            f"observações sobre o que o sistema parece fazer hoje — cada uma entra como "
            f"`observed`, com a evidência que a sustenta.",
            "",
            "Uma observação vira promessa quando uma pessoa a confirma e muda o status para "
            "`accepted`. Até lá a fábrica NÃO defende nada disto: um bug lido do código é "
            "indistinguível de uma funcionalidade.",
            "",
            "Áreas cobertas nesta passagem: "
            + (", ".join(covered) if covered else "(o repositório)"),
            "",
            "O que este PR **não** garante: que a cobertura seja completa, nem que cada "
            "comportamento observado seja intencional. As duas coisas são decisão de quem revisa.",
        ])
        url = _open_review_request(
            forge, docs_repo=docs_repo, head=branch, base=base,
            title=f"Levantamento inicial: {observations} observações sobre {product}", body=body)
        if not url:
            return WriteResult(ok=False, ref=branch,
                               detail=f"a branch {branch} foi enviada mas o pull request não "
                                      f"abriu; abra à mão contra {base}")
        return WriteResult(ok=True, url=url, ref=branch)
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)

