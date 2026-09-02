"""The product module's front door — what a Slack listener, an activity or the panel calls.

Everything below it is testable in isolation (the reconciliation is pure, the corpus is files, the
role is one `ask()`); this is the layer that says WHO may do WHAT, and turns "unavailable" into a
sentence rather than an exception.

AUTHORITY (ADR-0019 §5). Two questions, and only the second is about a person:

    is the module available for this project?      the reconciliation in config.py
    may THIS person make it act?                   `may_act`, over the project's allowlist

Reading is open to the channel, as it is for the tech-lead (ADR-0016): asking what the product
already promises is not a privileged operation. Writing is not. An empty allowlist means nobody can
act — the safe default, so enabling the module never silently hands out authoring rights.

WHAT WRITES WITHOUT ASKING `may_act`, AND ON WHOSE AUTHORITY. Four methods here change a client's
board or their documentation without calling the gate themselves. They are LISTED, rather than left
to be found by reading all of them, because a deliberate exception nobody wrote down is
indistinguishable from a forgotten one — the reason the tracker contract declares `link_child` and
`children_of` in the same breath as the rule they are exempt from.

    file_defect · note_fact · baseline    THE YES IS ONE LAYER UP. The channel stages the act,
                                          checks `may_act`, and only then calls these; the
                                          conversation holds the confirmation and is the record of
                                          it. They are the pen, never the judgement.

    repoint_orphans                       NOBODY IS ASKED AT ALL — hourly, `actor=""`, no staged
                                          proposal, no person in the loop. It is safe only inside a
                                          boundary that must never widen: it changes nothing a card
                                          says must be TRUE, only which requirement the card CITES,
                                          and only onto the successor the corpus itself names. That
                                          repairs a pointer this platform wrote and can prove is
                                          stale. Re-deriving criteria from the new text decides
                                          what gets BUILT, so it goes through `align_card` behind a
                                          confirmation. The boundary is held by a test, not by this
                                          paragraph (tests/test_card_maintenance.py).

Adding a fifth is not forbidden. Leaving it off this list is.

WHERE IT RUNS. The agent works inside the DOCUMENTATION checkout, because that is what almost every
product question is about. It is given the path of the source checkout when one is available, but
whether it can read outside its working directory depends on the harness (`-s read-only` confines
Codex; Claude's tool allowlist does not). So code reading is stated as a bonus rather than promised
— an honest limitation is worth more than a capability that works on one engine and silently does
not on another.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from openfactory.contracts.refs import canonical_ref, ref_sort_key
from openfactory.ops.impediment import PRODUCT_BOARD_UNREADABLE as _IMP_BOARD
from openfactory.ops.impediment import PRODUCT_CANNOT_WRITE as _IMP_WRITE
from openfactory.ops.impediment import PRODUCT_CORPUS_UNREADABLE as _IMP_CORPUS
from openfactory.ops.impediment import PRODUCT_MOUNT_EMPTY as _IMP_MOUNT_EMPTY
from openfactory.ops.impediment import PRODUCT_NO_CODE as _IMP_NO_CODE
from openfactory.product.authoring import (
    WriteResult,
    issue_body,
    next_number,
    propose_requirement,
    requirement_file,
)
from openfactory.product.loader import ProductContext, load_product_context
from openfactory.product.role import ProductAnswer, ProductRole

log = logging.getLogger("openfactory.product")

#: The two mount names USED TO LIVE HERE, as `DOCS_DIRNAME`/`CODE_DIRNAME`, with a note saying the
#: prompt is told these paths and a rename that did not reach it would send the role looking in a
#: directory that does not exist. The note was right about the danger and wrong about the remedy:
#: two constants kept in step by hand are the danger, not the cure. `mounted()` now DERIVES the
#: names from where `compose()` actually put things, so there is nothing left to keep in step.


def _visible(path) -> int:
    """How many entries an agent standing in `path` would actually see. -1 when the path is not
    there at all — a directory that exists and is empty and one that does not exist are different
    failures, and telling them apart is the whole point of counting."""
    from pathlib import Path as _P

    try:
        p = _P(str(path))
        if not p.is_dir():
            return -1
        return sum(1 for x in p.iterdir() if not x.name.startswith("."))
    except OSError:
        return -1


def _tell_the_factory(project, cause: str, detail: str, *, ok: bool) -> None:
    """One capability, one impediment — opened when it breaks, closed when it works.

    THE SEAM, and there is exactly one on purpose. Wiring this per symptom is how the mount would
    get a ticket and the unreadable corpus would not, which is the "lesson learned in one file and
    not copied" this codebase has paid for six times. Every place the platform promises something
    and cannot deliver comes through here.

    Closing on success is what makes the board converge instead of accumulating: nobody marks an
    impediment resolved, the next working mount does it, and the evidence goes in the comment
    (ADR-0021 — a loop closes by observation, never by self-report).
    """
    from openfactory.ops import impediment

    try:
        if ok:
            impediment.resolved(project, cause, evidence=detail)
        else:
            impediment.report(project, cause, detail)
    except Exception:  # noqa: BLE001 — reporting trouble must never become trouble
        log.warning("could not report the factory impediment %s", cause, exc_info=True)


def _log_mount(project, root, *, docs, code) -> None:
    """State, every time, what the role was actually handed.

    WRITTEN AFTER AN HOUR OF GUESSING. Nina reported "o que está montado para mim veio vazio" and
    there was no way to tell whether the checkout was missing, the symlinks were broken, the
    registry named no source repo, or she was simply mistaken — because the one thing that decides
    what her prompt CLAIMS she can open was never recorded anywhere. Three silent exits led here
    and none of them left a trace.

    Counted, not just named: a path that exists and holds nothing is the exact state being
    reported, and a log line that prints the path without the count cannot distinguish it from a
    healthy mount. An empty mount is an ERROR — the prompt is about to promise files that are not
    there, which is the one thing this whole layer exists to prevent.
    """
    name = getattr(project, "name", project)
    n_root, n_docs = _visible(root), _visible(docs)
    n_code = _visible(code) if code else 0
    line = (f"project={name} root={root} entries={n_root} docs={docs} docs_entries={n_docs} "
            f"code={code or '(none)'} code_entries={n_code}")
    empty = n_root <= 0 or n_docs <= 0
    if empty:
        log.error("OPENFACTORY_PRODUCT_MOUNT_EMPTY %s — the role is about to be told it can open "
                  "files "
                  "that are not there", line)
    else:
        log.info("OPENFACTORY_PRODUCT_MOUNT %s", line)
    # the factory hears about it too, and keeps hearing until it works again
    if not isinstance(project, str):
        _tell_the_factory(project, _IMP_MOUNT_EMPTY, line, ok=not empty)
        _tell_the_factory(project, _IMP_NO_CODE,
                          f"{line} — a agente respondeu sem poder abrir o código",
                          ok=bool(code) and n_code > 0)


def _decision_key(label: str) -> str:
    """A stable, short identity for a decision, so re-asking it is recognised as the same one.

    Words rather than a hash: the key shows up in the ledger and in the panel, and `fechar-11-cards`
    is something a human can recognise while `a3f9c1` is a row nobody can act on."""
    import re as _re
    import unicodedata

    flat = unicodedata.normalize("NFKD", label.lower())
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    words = [w for w in _re.findall(r"[a-z0-9#]+", flat) if len(w) > 2][:6]
    return "-".join(words)[:60] or "decisao"


def may_act(project, user_id: str, *, via: str = "slack") -> bool:
    """Whether this person may make the product role WRITE (a requirement PR, an issue).

    Empty allowlist = nobody. Reading is not gated: what the product promises is not a secret from
    the channel it is discussed in.

    THE RULE ITSELF LIVES IN `policy.authz` NOW (C-26) — this is its PRODUCT scope, deliberately
    separate from the factory floor's, because the client who may approve a requirement and the
    operator who may skip a job are different trusts and always were. What moved is the answering,
    not the difference.

    `via` IS PROVENANCE, NOT PERMISSION — `authz.may` compares the id against the allowlist and
    never reads the channel. It is a parameter because it was HARDCODED to `"slack"`, and once the
    role gained a second transport (#98) that constant became a false statement inside the one
    record that says who authorised a change to a client's requirements. Defaulted so every
    existing caller keeps saying exactly what it said before."""
    from openfactory.identity.base import Subject
    from openfactory.policy import authz

    if not user_id:
        return False
    return authz.is_admin(Subject(id=user_id, via=via), project, scope=authz.PRODUCT)


def unauthorized_message(project) -> str:
    """Said out loud, never silently ignored — a request that vanishes is indistinguishable from a
    broken bot, and the person tries again.

    In the CLIENT's terms (voice.py): naming a configuration file would be both useless and
    slightly insulting to someone who was never meant to edit one."""
    from openfactory.product.voice import cannot_write

    cfg = getattr(project, "product", None)
    return cannot_write(has_approvers=bool(cfg is not None and (cfg.admins or [])),
                        language=getattr(project, "language", None))


#: A ticket ref as a person types it back: `412`, `#412`, or a Jira-style `CONT-412`. Bounded so
#: ordinary conversation ("às 15h", a year, a phone number) cannot be swallowed whole — a stray
#: match only matters if it coincides with an OPEN release ref, which is the actual filter.
_REF_IN_TEXT = re.compile(r"#?\b([A-Za-z][A-Za-z0-9]{0,9}-\d{1,6}|\d{1,6})\b")


def _named_release(text: str, loops: list) -> object | None:
    """The one open loop among `loops` whose release ref is named in `text`, or None.

    THE FIX FOR #24 ITEM 2 (2026-08-04): the ambiguous-release reply used to say "diga o número"
    while no code anywhere read one back — the loop was already closed as a guess before the
    client could even answer. This is what makes that instruction true.

    ONLY RELEASE LOOPS ARE CANDIDATES. A delivery-acceptance loop's subject is a requirement, not
    a ticket somebody would type back — matching against it would resolve the wrong kind of
    ambiguity by coincidence.

    TWO DIFFERENT RELEASE REFS NAMED RESOLVES NOTHING, same as none: "o 412 e o 430 funcionaram"
    is still a guess about which ONE this reply settles, and a guess is exactly what this function
    exists to refuse. Case-insensitive on purpose — Jira mints `CONT-412` and people type
    `cont-412`, and those must not read as two tickets.
    """
    from openfactory.product.followup import is_release

    mentioned = {canonical_ref(m).upper() for m in _REF_IN_TEXT.findall(text or "")}
    if not mentioned:
        return None
    candidates = [x for x in loops
                  if is_release(x) and canonical_ref(is_release(x)).upper() in mentioned]
    return candidates[0] if len(candidates) == 1 else None


#: How the fact that nobody passed a board is told apart from a caller saying "do not place this".
#: `None` cannot express both, and conflating them is what left every filed card column-less.
_UNSET = object()


def _could_not(sentence: str, *, act: str, cause: object = "", ref: str = "") -> WriteResult:
    """The one way this module reports a write that did not happen.

    TWO AUDIENCES, TWO ARGUMENTS, AND NO WAY TO CONFUSE THEM. `sentence` is composed for the client
    and `cause` is for whoever fixes it; `cause` is never rendered into the result, and there is no
    argument that would put it there. `promote` used to answer `detail=str(exc)[:160]`, so a `gh`
    that timed out made the client's entire reply a shell argv carrying a GraphQL mutation and the
    board's own field ids — and the partial-failure line said the same thing under a pt-BR headline.

    WHY COMPOSITION RATHER THAN A FILTER. The channel does sanitise (`voice.client_safe_detail`),
    by recognising machinery SHAPES: `fatal:`, an HTTP code, a path, a `*Error` name, the delivery
    vocabulary. A shape list can only catch what it has already been shown — an argv, a JSON parse
    message, and a perfectly calm English sentence naming the repository all walk straight past it.
    It is the second line of defence, and it only gets to be the second line if a caught exception,
    or prose written for an operator, never becomes a `detail` in the first place.

    Every `except` branch in this file goes through here, and a test asserts that none builds a
    `WriteResult` of its own — the guard is structural because the next writer of a failure branch
    will not have read this docstring.
    """
    log.warning("OPENFACTORY_PRODUCT_WRITE_FAILED act=%s ref=%s — %s", act, ref or "-", cause)
    return WriteResult(ok=False, ref=ref, detail=sentence)


#: What the client is told when the board cannot be read for an act about ONE card. The three that
#: need to find the card first (`refine`, `close_card`, `align_card`) say it with one voice: a third
#: hand-written copy is where wording drifts, and the one that never had a sentence at all returned
#: `read_board`'s operator prose — English, naming the repository — into the channel verbatim.
_BOARD_UNREADABLE = ("não consegui abrir o quadro agora para ler esse cartão, então não mexi nele. "
                     "O time foi avisado.")


class _CorpusNoted:
    """The corpus-health note, carried on EVERY prompt this module sends — one seam, all consumers.

    `_corpus_note()` used to reach exactly one consumer: `answer()`'s `context` default. Drafting,
    the issue breakdown, both judges, refine and the queue all reasoned over the same broken
    corpus with no warning — so a draft touching a promise that exists in two live versions argued
    its conflicts from whichever file the model opened first. Every role operation already passes
    through `agent.ask` (role._ask), so the note is attached HERE rather than at N call sites a
    future consumer could forget."""

    def __init__(self, agent, note: str) -> None:
        self._agent = agent
        self._note = note

    def ask(self, *, sandbox, workspace, prompt, phase):
        return self._agent.ask(sandbox=sandbox, workspace=workspace,
                               prompt=f"{self._note}\n\n{prompt}", phase=phase)

    def __getattr__(self, name):
        return getattr(self._agent, name)


class _WatchedWrites:
    """Every write this module makes, watched — a MACHINE failure reaches the factory's board.

    A WRAPPER, NOT A REPORT AT EACH CALL SITE. Filing, refining, closing, repointing and placing a
    card each end in their own `except` branch with their own sentence for the client, and wiring
    the impediment into all of them is the "lesson learned in one file and not copied" this
    codebase has paid for repeatedly: five wirings become four, and the one nobody remembers is the
    one that fails silently. Anything written through the adapter is covered here, including a
    write somebody adds next month.

    A BUSINESS REFUSAL NEVER COMES THROUGH HERE, and that distinction is the whole worth of the
    ticket. "That card is already closed" is an answer somebody can act on in the conversation; a
    forge that raised, or that answered `False` to a placement, is the platform failing to do what
    it said it would — the only one of the two that is an operator's to fix. A board carrying both
    is a board nobody triages.

    The exception is re-raised: every caller already turns one into a sentence the client can act
    on, and reporting trouble must never change what the client hears.

    WHAT THIS GUARD RESTS ON, and it is a contract rather than a hope: an adapter write that failed
    RAISES, or answers `False` (`adapters/tracker/base.py`). It cannot detect a write that returned
    quietly having done nothing — the production tracker did exactly that for close, comment and
    body edits, so a failed close read as a clean write here, the client was told the card was
    closed, and the impediment a real failure had opened was closed by the write that never
    happened. A guard sharing the failure mode of the thing it guards is worth less than none.
    """

    #: What actually changes something — and the only evidence that CLOSES the impediment. A read
    #: coming back is the forge answering; a write landing is the capability the ticket names.
    _WRITES = frozenset({"create_ticket", "comment", "close_ticket", "update_body", "add_label",
                         "remove_label", "set_assignees", "set_state", "link_child",
                         "add_item", "set_column"})

    #: What can FAIL a write. The lookup that gates one belongs here even though it changes
    #: nothing: `_file_one` and `file_defect` both ask "does this already exist?" first, so a
    #: `find_ticket` that raises means the create never ran — a write that did not happen for a
    #: machine reason, which is exactly what the ticket is for. The client is told the same thing
    #: either way, and an operator who only hears about half of them triages a board that lies.
    _WATCHED = _WRITES | frozenset({"find_ticket", "get_ticket"})

    def __init__(self, inner, tell) -> None:
        self._inner = inner
        self._tell = tell

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name not in self._WATCHED or not callable(attr):
            return attr

        def watched(*args, **kwargs):
            try:
                out = attr(*args, **kwargs)
            except Exception as exc:
                self._tell(False, f"{name}: {str(exc)[:200]}")
                raise
            if name in self._WRITES:
                # A WRITE THAT ANSWERED `False` DID NOT HAPPEN. That is how a board refuses a
                # placement, and reading a falsy answer as success is what left filed cards with
                # no column while the client was told they were queued. `is False` exactly —
                # `None` is what a comment returns, and it means nothing went wrong.
                self._tell(out is not False,
                           f"{name} recusou a escrita" if out is False else name)
            return out

        return watched


class ProductModule:
    """One project's product module: the corpus it reasons over, and the actions it may take."""

    def __init__(self, project, *, token: str | None = None, context: ProductContext | None = None,
                 agent=None, tracker=None, board=None, via: str = "slack") -> None:
        self.project = project
        #: WHERE the actor of every write below is speaking from. Provenance, never permission —
        #: `authz.may` compares the id against the allowlist and never reads this. It exists
        #: because it used to be the constant `"slack"` inside `may_act`, and the moment the role
        #: gained a second transport (#98) that constant became a false statement in the one
        #: record that says who authorised a change to a client's requirements. Defaulted to
        #: `"slack"` so the channel, which is every existing caller, is unchanged.
        self._via = via
        self._token = token
        self._context = context
        self._agent = agent
        #: adapters supplied at CONSTRUCTION, for the same reason `context` and `agent` can be:
        #: the operations that write must be drivable without a forge behind them. These are the
        #: module's own — `_tracker`/`_board` watch them — unlike one handed in at a call site.
        self._given_tracker = tracker
        self._given_board = board
        self._board_tickets: list = []

    @property
    def token(self) -> str | None:
        """The forge credential, resolved the same way every other worker-side path resolves it.

        Defaulted HERE rather than at each call site because both real entry points — the Slack
        handler and the scheduled sweep — construct this with no token, and a documentation repo is
        private. Without a credential the clone fails, the module reports itself unavailable, and
        the role answers "I can't see the requirements" to every single message while every test
        passes: the tests hand it a checkout directly."""
        if self._token is None:
            from openfactory.credentials import deployment_forge_token, forge_token_for

            self._token = (forge_token_for(self.project)
                           or deployment_forge_token(self.project) or "")
        return self._token or None

    def _clone_url(self, repo: str) -> str:
        """The URL that clones `repo` for THIS project — asked of the forge, never spelled here.

        EIGHT CALL SITES IMPORTED `runtime.fargate.entrypoint.clone_url`, which says `github.com`
        as a literal: the documentation checkout, the source checkout behind every conversation,
        and the six writers (propose, accept, drop, record a decision, record a fact, baseline).
        On an Azure Repos deployment every one of them addressed a host the client does not use.
        The documentation one is the expensive half — with no corpus the module reports itself
        unavailable, so a client whose product IS on Azure gets "não consigo ver os requisitos" to
        every message, for ever, with the wrong host named nowhere in the answer.

        ONE HOME rather than eight edits, for the reason this file states about impediments and
        placements: eight wirings become seven, and the one nobody remembers is the one that fails.

        `clone_url_for` also decides the CREDENTIAL, and that is not a detail on this path.
        `self.token` resolves through `forge_token_for`, so on an Azure project it is the Azure
        PAT and on a GitHub project the GitHub one — and the forge registry's Azure row refuses an
        ambient token outright, minting its own. Passing `self.token` here is therefore an offer,
        not an instruction, which is exactly what that row was built for.

        RAISES on an unknown forge, deliberately, like `build_forge`: a clone aimed at the wrong
        host fails as a 404 about a missing repository, which sends somebody hunting a permissions
        problem. Every caller below is already inside the `try` that turns trouble into a sentence
        for the client."""
        from openfactory.adapters.forge.registry import clone_url_for

        return clone_url_for(self.project, repo, token=self.token)

    def _forge_kind(self) -> str:
        """Which forge this deployment runs — read from the registry, through the seam.

        The product module's pull-request path is `gh`, and `gh` is one vendor's command line. The
        callers below hand it this so it can REFUSE on any other vendor instead of exporting this
        project's credential to github.com (`authoring.gh_runner`)."""
        from openfactory.adapters.forge.registry import forge_kind

        return forge_kind(self.project)

    def _forge(self):
        """The project's forge adapter — what the authoring writers read the DOCS repository with.

        THE PORT GREW A READ SIDE AND THIS IS WHERE IT ARRIVES (#97). `authoring.py` asked
        github.com two questions on every proposal — which `req/*` branches exist, and whether this
        one was ever proposed — by shelling out to `gh`, so on an Azure Repos deployment both were
        refused (correctly: the alternative was exporting that project's Microsoft credential to
        GitHub) and both answered "". An empty answer to the first mints a requirement number
        against a board nobody read; an empty answer to the second opens a second pull request for
        work already proposed. `list_branches` and `pr_for_head` take a REPOSITORY, which is the
        whole reason they can serve here at all — `push_remote()` and its siblings are bound to
        `self.repo`, the source code, and the documentation is a different repository.

        `token=self.token` is an OFFER, exactly as it is at `_clone_url`: `forge_token_for` resolves
        this project's own credential, and the registry's Azure row refuses an ambient token
        outright and mints its own from the variable the project names. Passing it is right for the
        GitHub rows and harmless for the others by construction.

        RAISES on an unknown forge, like `build_forge` and `_clone_url`: every caller below is
        inside the `try` that turns trouble into a sentence for the client, and a forge that cannot
        be built must not degrade into "there are no branches"."""
        from openfactory.adapters.forge.registry import build_forge

        return build_forge(self.project, token=self.token)

    def _docs_url(self) -> str:
        """Where a HUMAN opens the documentation repository — "" when the forge cannot say.

        `authoring._repo_url` used to answer this, and it was provider-aware in APPEARANCE only: it
        read `GH_HOST`, so an Azure deployment that set that variable produced
        `https://dev.azure.com/<repo>`, which addresses nothing at all, and one that did not
        produced a github.com link to a repository that may belong to somebody else. It is printed
        into the `## Source` block of every card the product role files — the one line that makes
        an authored issue auditable — so a wrong link there is worse than no link.

        DERIVED FROM THE FORGE'S OWN CLONE URL rather than from a new adapter method, because a
        clone URL already carries the three things that differ per provider: the host, the path
        shape, and Azure Repos' extra `/{project}/_git/` segment that GitHub has no equivalent of.
        Asked WITHOUT a credential (`token=None`) — this string is published on a client's board.

        `build_forge` rather than `clone_url_for`: that wrapper deliberately lets the ADAPTER's own
        credential win over the caller's, which is right for a clone and exactly wrong here. The
        `@` check below is the guard that makes that sentence checkable rather than merely stated —
        a userinfo section in a published URL is a secret on a board, and nothing downstream would
        ever notice it."""
        import re as _re

        repo = self.context().link.docs_repo
        if not repo:
            return ""
        try:
            from openfactory.adapters.forge.registry import build_forge

            url = build_forge(self.project).clone_url(repo, token=None)
        except Exception as exc:  # noqa: BLE001 — no link is survivable; a wrong one is not
            log.warning("product: cannot build a documentation URL for %s (%s) — the cards it "
                        "files will name the repository without linking to it",
                        getattr(self.project, "name", "?"), exc)
            return ""
        authority = url.split("://", 1)[-1].split("/", 1)[0]
        if "@" in authority:
            log.error("OPENFACTORY_PRODUCT_DOCS_URL_HAS_A_CREDENTIAL project=%s — the forge "
                      "answered a "
                      "URL carrying userinfo and this is written onto a client's board; dropping "
                      "the link rather than publishing it",
                      getattr(self.project, "name", "?"))
            return ""
        return _re.sub(r"\.git$", "", url)

    # ---- state ------------------------------------------------------------------------------

    def context(self, *, refresh: bool = False) -> ProductContext:
        """The loaded corpus, or the reason there isn't one. Cached per instance: one Slack message
        should not re-sync the documentation repo three times."""
        if self._context is None or refresh:
            self._context = load_product_context(self.project, token=self.token)
            # THE SEAM FOR "SHE CANNOT SEE THE PRODUCT", and it is here rather than at the eight
            # `if not ctx.available` branches for the reason this codebase keeps relearning: eight
            # wirings become seven, and the one nobody remembers is the one that fails. This is the
            # single place the answer is produced.
            #
            # It also makes an existing sentence TRUE. `voice._UNAVAILABLE` has always ended with
            # "Já avisei o time." — and until this line nothing told anybody: the corpus failed, a
            # warning went to a log nobody reads, and the client was told a colleague had been
            # alerted who did not exist.
            _tell_the_factory(self.project, _IMP_CORPUS,
                              (self._context.reason or "")[:400] or "sem motivo declarado",
                              ok=bool(self._context.available))
        return self._context

    def _corpus_changed(self, result: WriteResult) -> WriteResult:
        """Forget what was read BEFORE this module's own write — and hand the result straight back.

        A module answers from a context loaded once per Slack message, which is right: one message
        must not re-sync the documentation repo three times. It stops being right the moment the
        module WRITES to that repo, because everything after the write is then answered from the
        version before it.

        THIS IS WHAT WOULD HAVE MADE THE AUTOMATIC BREAKDOWN A NO-OP IN PRODUCTION WHILE PASSING
        EVERY TEST. `break_down` refuses anything that is not yet a promise, and it asks the cached
        corpus — where the requirement the client had just agreed to was still `proposed`. Every
        acceptance would have answered "this is not a promise yet" about the promise it had
        made one line earlier, and no unit test with a stubbed module would ever have seen it.

        Wrapped around the write rather than written after it, so the invalidation cannot be left
        out of the next act that changes the corpus: the value has to pass through here to be
        returned at all. Only a successful write invalidates — a refused one changed nothing, and
        throwing the context away would buy a repo sync for nothing.
        """
        if result.ok and not result.existed:
            self._context = None
        return result

    @property
    def available(self) -> bool:
        return self.context().available

    def health(self) -> str:
        return self.context().health()

    def _cannot_see_the_product(self) -> WriteResult:
        """Every write's first refusal: the corpus could not be loaded, so nothing may be written
        against it.

        `ProductLink.reason` IS NOT THAT SENTENCE, and nine branches returned it as one. It is an
        operator's paragraph — "the source repo claims its documentation lives in 'x/y', but this
        deployment authorizes 'a/b'… Fix `docs_repo` in the source repo's
        `.openfactory/project.yaml`" —
        addressed to somebody with a checkout, and it went to a client who has neither. `voice`
        already holds the client's half of this exact fact and takes the diagnosis as a separate
        argument, which is the same split `_could_not` makes one layer down.
        """
        from openfactory.product.voice import unavailable

        reason = self.context().reason
        return _could_not(unavailable(reason_for_team=reason,
                                      language=getattr(self.project, "language", None)),
                          act="read the requirements", cause=reason)

    def _role(self, *, pending: str = "") -> ProductRole:
        agent = self._agent
        if agent is None:
            from openfactory.adapters.agent import build_product

            agent = build_product(self.project)
        note = self._corpus_note()
        if note:
            # corpus health travels with EVERY operation, not just answer() — see _CorpusNoted
            agent = _CorpusNoted(agent, note)
        cfg = getattr(self.project, "product", None)
        return ProductRole(agent, corpus=self.context().corpus,
                           project_name=getattr(self.project, "name", "") or "",
                           language=getattr(self.project, "language", "") or "",
                           pending_proposal=pending,
                           agent_name=getattr(cfg, "agent_name", "") or "",
                           domain=self.context().domain,
                           # the board this module ALREADY read, handed over rather than fetched
                           # again from inside the box (ADR-0017's shape: inject, don't explore)
                           # ONE RECORD PER CARD, not two parallel dicts. It used to be
                           # `board=self._board_columns()` plus `titles={...self._board_tickets}`,
                           # which worked only because Python evaluates keyword arguments left to
                           # right: the first call is what POPULATES `_board_tickets` for the
                           # second. Reorder the two lines and every title silently disappears.
                           #
                           # And the split is what let a card reach the prompt as an IDENTITY with
                           # no QUALIFIER: neither dict carries `state` or `state_reason`, so the
                           # rule that closed-is-not-delivered had nothing to read on this surface.
                           cards=self._board_cards(),
                           # what is REALLY readable — the prompt describes it instead of
                           # asserting access the runtime may not have provided
                           mounted=self.mounted())

    def _read_board(self, *, token: str | None = None, fresh: bool = False):
        """`(tickets, error)` — THE board read of this module, and the one place a failed one
        becomes an impediment.

        Every operation here that looks at the board comes through this: the column lookup behind
        every conversational answer, the queue proposal, the triage, a refinement, an alignment,
        the orphan sweep. Reporting the failure at each of them is the shape that has already cost
        this codebase six repairs — so the report lives at the read, not at its callers.

        `voice._UNAVAILABLE` and the queue's own refusals end with "Já avisei o time." Until this
        line nothing told anybody: the board failed, a log line nobody reads recorded it, and the
        client was told a colleague had been alerted who did not exist."""
        from openfactory.product.board import read_board

        tickets, error = read_board(self.project, token=token or self.token, fresh=fresh)
        self._board_was_read(error)
        return tickets, error

    def _board_was_read(self, error: str) -> None:
        """Opened when the board cannot be read, closed by the next read that works (ADR-0021).

        Called directly by the one reader that does not come through `_read_board` —
        `parked_with_diagnosis` reads inside board.py and returns the same `error` string."""
        _tell_the_factory(self.project, _IMP_BOARD,
                          (error or "")[:400] or "sem motivo declarado", ok=not error)

    def _write_outcome(self, ok: bool, detail: str) -> None:
        """A write that failed for a MACHINE reason — never for a business rule (`_WatchedWrites`).

        Closed by the next write that works, so an operator who fixed it silently and a fix that
        never happened do not look alike."""
        _tell_the_factory(self.project, _IMP_WRITE, detail, ok=ok)

    def _board_cards(self) -> list | None:
        """The board as the role sees it — WHOLE TICKETS, read lazily when the sweep has not run.

        `None` means the read FAILED, and that distinction is load-bearing: an earlier version
        returned None whenever `_board_tickets` was empty — which is EVERY conversational message,
        since the channel builds a fresh module per message. The prompt then said "the board could
        not be read just now", so Nina told clients she could not see a perfectly readable board:
        "não olhei" and "não consegui" colliding, this time in her own mouth. The read is one
        paginated query (1 GraphQL point) behind the snapshot cache, so a conversation affords it.

        TICKETS AND NOT TWO DICTS. This used to hand over `{number: column}` and, separately,
        `{number: title}`. Both of those are IDENTITY WITHOUT QUALIFIER: neither carries `state`
        or `state_reason`, so the surface that talks to the client had no way to tell a card closed
        as delivered from one closed as `not_planned` — while the sweep, reading these very same
        objects, has had that rule since eleven cards were closed as `not_planned` in one sitting.
        Handing the whole ticket over is what lets `Ticket.delivered` govern both surfaces instead
        of one.
        """
        if self._board_tickets:
            return list(self._board_tickets)
        tickets, error = self._read_board()
        if error:
            log.info("[%s] the role answers without the board (%s)",
                     getattr(self.project, "name", "?"), error)
            return None
        self._board_tickets = tickets
        return list(tickets)

    def _workspace(self):
        """What the role can READ during a conversation: the documentation repo AND the code.

        THE PROMPT PROMISED THE CODE AND THE RUNTIME DID NOT DELIVER IT. `product.md` says "You
        also have read access to the source code, and you should use it: a claim about what the
        product does today is worth far more when you have opened the file than when you have
        inferred it from a document" — and every conversational operation handed over the docs
        checkout alone. Asked to write the requirements of an existing product, the role answered
        that it could not: "não tenho o código do produto acessível, só a pasta de requisitos. Sem
        ele, qualquer coisa que eu escreva sobre o comportamento actual é adivinhação." Refusing to
        guess is the behaviour we want — against a promise the system itself had broken.

        Both are mounted under one directory because the agent runs with `cwd` at the workspace
        root, and everything it may open should live inside it. Writing still goes through
        `propose_requirement`'s own clone — nothing here is ever committed.

        REAL CONTENT, NOT TWO POINTERS OUT OF THE TREE (board #1). This used to be a root holding
        two symlinks to checkouts elsewhere, chosen because two copies are hundreds of megabytes
        and this runs on every message. The cost argument was right and the conclusion was not:
        `product/workspace.py` had already solved exactly this with git worktrees — real files whose
        objects are shared, so it costs a file write rather than a clone — and said, in its own
        docstring, why the symlink shape must be avoided: *"a confined sandbox will not follow a
        link that leaves its root, so a symlinked layout would reproduce exactly the failure this
        exists to avoid."*

        That is not hypothetical and it is not cosmetic: it is the AGNOSTICISM claim. Codex's
        `-s read-only` is a sandbox policy that confines the process; Claude's tool allowlist is
        not. The same layout therefore reads everything on one engine and NOTHING on another, with
        answers still arriving either way — and "vendor-agnostic" is one of the three sentences this
        product is sold on. `compose()` existed, was tested, and was called by nothing: the
        fifteenth time in this codebase that the right mechanism was built and then not reached.

        Degrades honestly: if the source cannot be fetched, the docs checkout is returned alone and
        `_mounted()` reports it, so the prompt stops claiming access that does not exist."""

        from openfactory.adapters.sandbox.base import Workspace
        from openfactory.adapters.sandbox.registry import judging_worktree
        from openfactory.product.workspace import compose

        docs = self.context().docs_path
        branch = getattr(getattr(self.project, "product", None), "docs_branch", "main")
        if hasattr(self, "_combined"):
            return (judging_worktree(self.project, root=self._combined),
                    Workspace(path=self._combined, branch=branch, base_branch=branch))

        source = self._source_checkout()
        if source is None:
            self._combined, self._mounted_code = docs, None
            _log_mount(self.project, docs, docs=docs, code=None)
            return (judging_worktree(self.project, root=docs),
                    Workspace(path=docs, branch=branch, base_branch=branch))

        # A STABLE path, rebuilt in place — not a temp directory per message. The module is
        # constructed fresh for every message (deliberately: one conversation must not carry
        # another's state), so `mkdtemp` here meant one directory nobody ever removed, per message.
        # `compose` is idempotent at a fixed root, so the ordinary turn — the cache has not moved —
        # costs a `rev-parse` and no checkout at all.
        # Beside the checkouts it is built from, derived from the cache's own location, so it
        # follows the cache wherever it lives instead of assuming a path a deploy can move.
        root = os.path.join(os.path.dirname(str(docs)), f"{self.project.name}-view")
        repo = self._source_repo() or self.project.name
        try:
            ws = compose(docs_checkout=docs, sources={repo: source}, root=root)
        except Exception as exc:  # noqa: BLE001 — a workspace problem degrades, never raises
            # Documentation-only rather than nothing: a question about requirements is still
            # answerable, and `mounted()` will tell the prompt the code is not there.
            log.warning("product: could not compose the workspace for %s (%s) — answering from "
                        "the documentation alone", getattr(self.project, "name", "?"), exc)
            self._combined, self._mounted_code = docs, None
            _log_mount(self.project, docs, docs=docs, code=None)
            return (judging_worktree(self.project, root=docs),
                    Workspace(path=docs, branch=branch, base_branch=branch))
        placed = ws.sources.get(repo)
        if placed is None:
            # THE HONEST HALF of the same degrade: `compose` records why in `missing` rather than
            # dropping the repo silently, and that reason is worth a log line — a role told it has
            # no code when the checkout was fine is the exact confusion this board item is about.
            log.warning("product: the source of %s was not placed in the workspace (%s) — the role "
                        "will be told it cannot open the code",
                        getattr(self.project, "name", "?"), ws.missing.get(repo, "no reason given"))
        self._combined = str(ws.path)
        self._mounted_code = str(placed) if placed is not None else None
        _log_mount(self.project, self._combined, docs=str(ws.docs),
                   code=str(placed) if placed is not None else None)
        return (judging_worktree(self.project, root=self._combined),
                Workspace(path=self._combined, branch=branch, base_branch=branch))

    def _source_checkout(self):
        """A read-only checkout of the SOURCE repo, cached between messages. None on any trouble —
        the caller degrades to documentation only and says so."""
        try:
            from openfactory.loader import load_manifest_base_branch
            from openfactory.runtime.repo_cache import RepoCache

            repo = self._source_repo()
            if not repo:
                return None
            # THE REGISTRY'S DECLARED BASE, OR THE REPOSITORY'S OWN (#162). `"main"` here was not a
            # harmless default: `git clone --branch main` against a `master` or `develop`
            # repository names nothing and fails, and this function's failure is silent by
            # contract — the role is told it cannot open the code and answers documentation-only
            # for ever. `""` lets the clone land where the repository points.
            return RepoCache().sync(f"{self.project.name}-source", self._clone_url(repo),
                                    load_manifest_base_branch(self.project, default=""))
        except Exception as exc:  # noqa: BLE001 — no code is survivable; a silent promise is not
            log.warning("product: could not check out the source of %s (%s) — the role will be "
                        "told it cannot open the code, instead of guessing about it",
                        getattr(self.project, "name", "?"), exc)
            return None

    def mounted(self) -> dict[str, str]:
        """What is actually readable right now, for the prompt to describe REALITY.

        A fixed sentence claiming code access is exactly how the role came to tell a client it had
        verified something it could not open.

        DERIVED FROM THE PATHS THAT WERE BUILT, never from a constant. The names used to be two
        literals here and two symlinks over there, agreeing because somebody kept them in step —
        and what the prompt tells the role to open is the one string that must not be a guess. Now
        the workspace answers where it put things and this reports it relative to the root the
        agent stands in.
        """
        from openfactory.knowledge.okf import OKF_DIRNAME, OKF_INDEX_FILE

        self._workspace()
        code = getattr(self, "_mounted_code", None)
        root = getattr(self, "_combined", None)
        if not code or not root:
            return {"docs": ".", "code": ""}
        out = {"docs": os.path.relpath(os.path.join(root, "docs"), root),
               "code": os.path.relpath(str(code), str(root))}
        # THE KNOWLEDGE BUNDLE, AND ONLY WHEN IT IS REALLY THERE — the rule `code` above already
        # follows, for a second reason that is specific to this key: the role composes its prompt
        # in THIS process, where every name in this dict is relative to a workspace root the
        # process is not standing in. A role that asked `Path("docs/.okf")` whether it exists
        # would be answered by the worker's own cwd — False on every project that has one, and
        # the section would be dead on all of them while looking wired. The existence question is
        # answerable here, where the absolute path is, and nowhere the prompt is built.
        door = Path(root) / "docs" / OKF_DIRNAME / OKF_INDEX_FILE
        if door.is_file():
            out["okf"] = os.path.relpath(str(door.parent), root)
        return out

    # ---- reading ----------------------------------------------------------------------------

    def answer(self, question: str, *, context: str = "", conversation: str = "",
               pending: str = "") -> ProductAnswer:
        """Anyone in the channel may ask. Returns an unavailable-with-reason answer rather than
        raising, because this is called straight from a chat listener."""
        ctx = self.context()
        if not ctx.available:
            return ProductAnswer(ok=False, error=ctx.reason)
        sandbox, ws = self._workspace()
        # the corpus note is NOT defaulted into `context` here any more: _role() carries it on
        # every prompt (the one seam), and doubling it up would say the same warning twice
        return self._role(pending=pending).answer(
            sandbox=sandbox, workspace=ws, question=question,
            context=context, conversation=conversation)

    def settle_acceptance(self, text: str) -> tuple[str, object, bool] | None:
        """A reply that answers "did it work?" — closes the loop with the CLIENT's verdict.

        Returns `(verdict, loop)` when one was settled, else None (the message was not an answer,
        and belongs to the normal conversation). Never closes on silence and never on a guess:
        `acceptance_verdict` returns "" for anything ambiguous, and this returns None for it.

        When several deliveries are awaiting an answer, a REF NAMED IN THE TEXT settles that one —
        never a guess. Failing that, the NEWEST is settled and the caller names it in the reply, so
        a wrong guess is at least visible and correctable.
        """
        from openfactory.memory import store as loop_store
        from openfactory.memory.ledger import ACCEPTANCE, close_by_observation, waiting
        from openfactory.product.followup import OWNER, acceptance_verdict

        verdict = acceptance_verdict(text)
        if not verdict:
            # AMBIGUOUS IS NOT "NO ANSWER". "ok", "beleza", "conferi", "testei" all used to close a
            # delivery as accepted; they now reach here, and a model decides whether the person
            # actually said it works (ADR-0029). No open acceptance → no call, so this costs nothing
            # on an ordinary message.
            verdict = self._judge_acceptance(text)
            if not verdict:
                return None
        try:
            ledger = loop_store.read(self.project.name)
        except Exception:  # noqa: BLE001 — an unreadable ledger must not eat the message
            log.warning("could not read the ledger to settle an acceptance", exc_info=True)
            return None
        open_acc = [x for x in waiting(ledger, owner=OWNER) if x.kind == ACCEPTANCE]
        if not open_acc:
            return None
        # A NAMED RELEASE WINS OVER "NEWEST" (found verifying #24 item 2, 2026-08-04): the ambiguous
        # branch used to tell the client "diga o número" while nothing anywhere read one back — the
        # loop was already closed as the newest guess before the client could even answer. Resolved
        # here, BEFORE anything closes, so a correct reply never gets overruled by a guess.
        named = _named_release(text, open_acc)
        loop = named or max(open_acc, key=lambda x: x.ts)
        ambiguous = named is None and len(open_acc) > 1

        # AN AMBIGUOUS "FUNCIONOU" ON A RELEASE CLOSES NOTHING. The other half of the same defect:
        # the guess was recorded as `worked` first and the "which one?" question went out second —
        # so the client's later, correct answer found its loop already closed, and the ledger said
        # a release was accepted that nobody had confirmed. An ordinary delivery keeps the
        # close-newest-and-name-it behaviour (a wrong guess there costs one visible correction);
        # a release guess puts software in front of the client's users, so the loop stays OPEN and
        # the caller asks — the reply that names the ref lands right here and settles it.
        from openfactory.product.followup import is_release

        if ambiguous and verdict == "worked" and is_release(loop):
            return verdict, loop, True

        rows = close_by_observation(ledger, {(ACCEPTANCE, loop.subject, loop.about): verdict})
        if rows:
            loop_store.write(self.project.name, rows)
        return verdict, loop, ambiguous

    def record_decisions(self, labels: list[str], *, channel: str = "") -> int:
        """Open one loop per decision she just asked for. Returns how many were new.

        Deduplicated by label: re-asking the same thing in a later message must not stack a second
        reminder — the person would be chased twice about one decision and read it as a machine
        that is not listening."""
        if not labels:
            return 0
        from openfactory.memory import store as loop_store
        from openfactory.memory.ledger import DECISION, open_loop, waiting
        from openfactory.product.followup import OWNER

        try:
            ledger = loop_store.read(self.project.name)
        except Exception:  # noqa: BLE001 — never lose the reply because the ledger is unreadable
            log.warning("could not read the ledger to record decisions", exc_info=True)
            return 0
        already = {x.subject for x in waiting(ledger, owner=OWNER) if x.kind == DECISION}
        from datetime import UTC, datetime

        ts = datetime.now(UTC).isoformat()
        fresh = [open_loop(DECISION, _decision_key(lab), owner=OWNER, ts=ts, about=channel,
                           context={"asked": lab[:400]})
                 for lab in labels if _decision_key(lab) not in already]
        if fresh:
            loop_store.write(self.project.name, fresh)
        return len(fresh)

    def close_decisions_answered(self, *, channel: str = "") -> int:
        """A person replied in this conversation — that IS the answer to what she asked them.

        The observation here is the human speaking, which is the same standard `acceptance_verdict`
        uses (ADR-0021: closed by observation, never self-report). Partial answers are safe: she
        has the conversation in memory now, so if something is still undecided her next reply
        re-asks it and a new loop opens. The alternative — keeping them open — chases a person
        about things they just discussed, which is how a channel gets muted.
        """
        from openfactory.memory import store as loop_store
        from openfactory.memory.ledger import DECISION, close_by_observation, waiting
        from openfactory.product.followup import OWNER

        try:
            ledger = loop_store.read(self.project.name)
        except Exception:  # noqa: BLE001
            log.warning("could not read the ledger to close decisions", exc_info=True)
            return 0
        live = [x for x in waiting(ledger, owner=OWNER) if x.kind == DECISION]
        if not live:
            return 0
        rows = close_by_observation(
            ledger, {(DECISION, x.subject, x.about): "answered" for x in live})
        if rows:
            loop_store.write(self.project.name, rows)
        return len(rows)

    def _corpus_note(self) -> str:
        """Problems with the corpus travel WITH every operation (via `_role()`'s wrapper — the one
        seam every prompt passes through). A role reasoning over a corpus with dangling references
        or two live versions of one promise should say so rather than draft, judge or queue
        confidently from a broken map."""
        errors = self.context().corpus.errors
        if not errors:
            return ""
        listed = "; ".join(f"{f.path}: {f.message}" for f in errors[:5])
        return (f"NOTE — the requirements corpus has {len(errors)} unresolved problem(s), so parts "
                f"of it may be untrustworthy: {listed}")

    # ---- writing ----------------------------------------------------------------------------

    def _judge_acceptance(self, text: str) -> str:
        """`worked` | `did-not-work` | "" for a reply the lexical gate could not classify.

        Reads the ledger FIRST: with nothing awaiting acceptance there is nothing to judge, so an
        ordinary message never pays for a model call."""
        from openfactory.memory import store as loop_store
        from openfactory.memory.ledger import ACCEPTANCE, waiting
        from openfactory.product.followup import OWNER

        try:
            open_acc = [x for x in waiting(loop_store.read(self.project.name), owner=OWNER)
                        if x.kind == ACCEPTANCE]
        except Exception:  # noqa: BLE001
            log.warning("could not read the ledger to judge an acceptance", exc_info=True)
            return ""
        if not open_acc:
            return ""
        loop = max(open_acc, key=lambda x: x.ts)
        ctx = self.context()
        if not ctx.available:
            return ""
        try:
            sandbox, ws = self._workspace()
            verdict = self._role().judge_acceptance(
                sandbox=sandbox, workspace=ws, reply=text,
                delivered=f"requisito {loop.subject}" + (
                    " (um defeito reportado)" if (loop.context or {}).get("defect") else ""))
        except Exception:  # noqa: BLE001
            log.warning("could not judge an acceptance", exc_info=True)
            return ""
        return "" if verdict == "neither" else verdict

    def confirmed(self, reply: str, *, proposal: str) -> str:
        """`approve` | `reject` | `neither` for a reply the lexical gate could not classify.

        Degrades to `neither` on any trouble: a proposal that stays pending costs one message, and
        an approval invented by a failure costs a requirement nobody agreed to."""
        ctx = self.context()
        if not ctx.available:
            return "neither"
        try:
            sandbox, ws = self._workspace()
            return self._role().judge_confirmation(sandbox=sandbox, workspace=ws,
                                                   reply=reply, proposal=proposal)
        except Exception:  # noqa: BLE001
            log.warning("could not judge a confirmation", exc_info=True)
            return "neither"

    def draft(self, request: str, *, asked_by: str = "") -> ProductAnswer:
        """Drafting is READ-ONLY: it produces a proposal and the conflicts it found, and writes
        nothing. Anyone may ask for one — the gate is on recording it, not on thinking about it."""
        ctx = self.context()
        if not ctx.available:
            return ProductAnswer(ok=False, error=ctx.reason)
        sandbox, ws = self._workspace()
        return self._role().draft(sandbox=sandbox, workspace=ws,
                                  request=request, asked_by=asked_by)

    def propose(self, answer: ProductAnswer, *, actor: str, asked_by: str = "",
                date: str = "", source: str = "") -> WriteResult:
        """Record a drafted requirement as a pull request — the sign-off surface.

        Takes the ProductAnswer from `draft` rather than re-deriving one, so what a human saw in
        the conversation is exactly what gets committed."""
        ctx = self.context()
        if not ctx.available:
            return self._cannot_see_the_product()
        if not may_act(self.project, actor, via=self._via):
            return WriteResult(ok=False, detail=unauthorized_message(self.project))
        if not answer.ok or answer.draft is None:
            # `answer.error` is the ROLE's diagnosis — "the codex harness's draft could not be read
            # (JSONDecodeError)" — and it used to be handed over as the client's sentence.
            return _could_not("não consegui transformar isso num texto de requisito que se "
                              "sustentasse, então não registrei nada. Me diga de outro jeito e eu "
                              "tento de novo.",
                              act="draft a requirement", cause=answer.error)

        cfg = self.project.product
        docs = ctx.link.docs_repo
        try:
            return propose_requirement(
                docs_repo=docs, clone_url=self._clone_url(docs), draft=answer.draft,
                token=self.token or "",   # `gh` has no ambient login in the worker
                # …and on a non-GitHub forge that token must not reach `gh` AT ALL: it is this
                # project's Azure/GitLab credential, and `gh` would export it to github.com.
                forge_kind=self._forge_kind(),
                # the two READS that used to be `gh` and now work on every vendor: which proposal
                # branches exist (the number is minted against them) and whether this one was ever
                # proposed. Not optional — a missing forge means "could not read", and the writer
                # refuses rather than minting against a board it never saw.
                forge=self._forge(),
                number=next_number(ctx.corpus),
                requirements_dir=ctx.requirements_dir, asked_by=asked_by, date=date,
                source=source, base=cfg.docs_branch)
        except Exception as exc:  # noqa: BLE001 — a chat listener must not see a traceback
            return _could_not("não consegui registrar esse requisito agora. Nada foi escrito — o "
                              "time foi avisado e resolve.",
                              act="propose a requirement", cause=exc)

    # ---- filing work ---------------------------------------------------------------------------

    #: Where a filed issue lands. A LITERAL, never a parameter: TO-DO is what the poller pulls, so
    #: a column name the caller could choose would be a money gate one argument wide. The product
    #: role writes work down; a human decides when it starts (ADR-0019 §5).
    FILING_COLUMN = "Backlog"

    def _requirement_path(self, requirement) -> str:
        """This module's binding of `authoring.requirement_file`: the ONE renderer of a
        requirement's location, given this project's requirements directory.

        A method rather than five inline joins, and a shared function rather than a method, for the
        same reason at two altitudes: the writers that print a citation — the acceptance, the
        abandonment, the issue filer, the alignment, the orphan repair and the defect card — must
        all get the same answer, and the one that did not was found by rendering a path nobody
        could open (see `requirement_file`)."""
        return requirement_file(requirement,
                                requirements_dir=self.context().requirements_dir)

    def accept(self, number: int, *, actor: str) -> WriteResult:
        """Turn a written requirement into a PROMISE the factory defends (ADR-0032).

        The step that did not exist. `accepted` was read in four places and written by nothing, so
        every requirement stayed `proposed` unless a person edited the markdown by hand — two
        developer operations per requirement, in a product sold as needing no developer.

        Gated like every other write: an authorised person, one confirmation. It is the single most
        consequential act on this surface, because after it the factory ARGUES FROM this statement.

        `actor` is the RAW Slack id — exactly what `may_act` checks against the allowlist, exactly
        what every sibling write branch passes. The `<@…>` mention is DECORATION and belongs only
        to the human-readable record written into the file; the one call site that pre-decorated
        it made every channel acceptance fail this method's own re-gate, so callers must never
        decorate and this method does it itself where the record is written.
        """
        from openfactory.product.authoring import accept_requirement

        ctx = self.context()
        if not ctx.available:
            return self._cannot_see_the_product()
        if not may_act(self.project, actor, via=self._via):
            return WriteResult(ok=False, detail=unauthorized_message(self.project))
        req = ctx.corpus.by_number(number)
        if req is None:
            return WriteResult(ok=False,
                               detail=f"não encontrei o requisito {number} escrito na base")
        if req.status == "accepted":
            return WriteResult(ok=True, existed=True, ref=req.path,
                               detail="esse já estava acordado")
        cfg = getattr(self.project, "product", None)
        try:
            return self._corpus_changed(accept_requirement(
                docs_repo=ctx.link.docs_repo, clone_url=self._clone_url(ctx.link.docs_repo),
                path=self._requirement_path(req),
                number=number,
                # decorated HERE, for the record alone — the raw id was what authorised the act
                accepted_by=f"<@{actor}>",
                base=getattr(cfg, "docs_branch", "main")))
        except Exception as exc:  # noqa: BLE001 — a chat listener must not see a traceback
            return _could_not(f"não consegui registrar o acordo do requisito {number} agora. Nada "
                              f"mudou — o time foi avisado e resolve.",
                              act=f"accept requirement {number}", cause=exc)

    def drop(self, number: int, *, actor: str, reason: str = "") -> WriteResult:
        """Record that a requirement will NOT be done — the act with no replacement.

        The lifecycle could write, agree and replace, and every one of those needs somebody to
        author a new text. It could not say "not this", which is the second most common thing that
        happens to a requirement in a real product conversation. Retiring by writing a replacement
        forces an invention to record an absence.

        Gated exactly like `accept`, and for a stronger reason on the accepted case: this is the
        only act that takes a promise BACK. `actor` is the RAW Slack id, decorated only where the
        human-readable record is written.
        """
        from openfactory.product.authoring import drop_requirement

        ctx = self.context()
        if not ctx.available:
            return self._cannot_see_the_product()
        if not may_act(self.project, actor, via=self._via):
            return WriteResult(ok=False, detail=unauthorized_message(self.project))
        req = ctx.corpus.by_number(number)
        if req is None:
            return WriteResult(ok=False,
                               detail=f"não encontrei o requisito {number} escrito na base")
        cfg = getattr(self.project, "product", None)
        try:
            return self._corpus_changed(drop_requirement(
                docs_repo=ctx.link.docs_repo, clone_url=self._clone_url(ctx.link.docs_repo),
                path=self._requirement_path(req),
                number=number, dropped_by=f"<@{actor}>", reason=reason,
                base=getattr(cfg, "docs_branch", "main")))
        except Exception as exc:  # noqa: BLE001 — a chat listener must not see a traceback
            return _could_not(f"não consegui registrar o abandono do requisito {number} agora. "
                              f"Nada mudou — o time foi avisado e resolve.",
                              act=f"drop requirement {number}", cause=exc)

    def record_decision(self, number: int, *, decision: str, actor: str,
                        where: str = "") -> WriteResult:
        """Write a decision taken AFTER the acceptance into the requirement's own register.

        Gated like every act that changes the document. Unlike `accept` and `drop` this adds to a
        requirement rather than changing what it promises — so it is allowed on any requirement
        that is still LIVE, agreed or not: decisions get taken while a text is still a proposal,
        and refusing to record those would push them back into the chat scrollback this exists to
        replace. A dropped or superseded requirement is refused, because writing into a document
        nobody is executing records a decision where nobody will look for it.
        """
        from openfactory.product.authoring import record_decision

        ctx = self.context()
        if not ctx.available:
            return self._cannot_see_the_product()
        if not may_act(self.project, actor, via=self._via):
            return WriteResult(ok=False, detail=unauthorized_message(self.project))
        req = ctx.corpus.by_number(number)
        if req is None:
            return WriteResult(ok=False,
                               detail=f"não encontrei o requisito {number} escrito na base")
        if not req.is_live:
            return WriteResult(ok=False,
                               detail=f"o requisito {number} já não vale, então registrar uma "
                                      f"decisão nele guardaria isso onde ninguém vai procurar. "
                                      f"Me diga em qual requisito isso deve entrar.")
        cfg = getattr(self.project, "product", None)
        try:
            return self._corpus_changed(record_decision(
                docs_repo=ctx.link.docs_repo, clone_url=self._clone_url(ctx.link.docs_repo),
                path=self._requirement_path(req), number=number,
                decision=decision, decided_by=f"<@{actor}>", where=where,
                base=getattr(cfg, "docs_branch", "main")))
        except Exception as exc:  # noqa: BLE001 — a chat listener must not see a traceback
            return _could_not(f"não consegui registrar essa decisão no requisito {number} agora. "
                              f"Nada mudou — o time foi avisado e resolve.",
                              act=f"record a decision on requirement {number}", cause=exc)

    def file_issues(self, requirement, *, actor: str,
                    tracker=None, board=_UNSET) -> list[WriteResult]:
        """Break a requirement into issues and file them into Backlog, each citing its source.

        One result per issue, in order, so a partial failure is visible per item rather than
        collapsing into "something went wrong" — the caller reports exactly which ones landed."""
        ctx = self.context()
        if not ctx.available:
            return [self._cannot_see_the_product()]
        if not may_act(self.project, actor, via=self._via):
            return [WriteResult(ok=False, detail=unauthorized_message(self.project))]

        # THE BOARD, READ ONCE AND USED TWICE. `_role()` puts it in the decomposition's prompt and
        # this set verifies every `already_on_board` the decomposition answers with. Priming
        # `_board_tickets` here is what keeps it ONE read: `_board_columns()` finds it loaded and
        # does not go back to the forge.
        #
        # VERIFIED AGAINST EXACTLY WHAT THE ROLE WAS SHOWN. `_board_columns()` prefers the tickets
        # already in hand over a fresh read, so deriving this from anything else would let the
        # prompt and the check disagree — the role would name a card the prompt listed and the
        # filing would call it unknown and duplicate it, which is the very defect being closed.
        #
        # `None` means the board could not be read AT ALL, the same vocabulary `_board_columns`
        # uses. An EMPTY board is a board we can vouch for; one we could not read lets us vouch
        # for nothing, and those two must never collapse into one value.
        tickets, board_error = self._read_board()
        if not board_error:
            self._board_tickets = tickets
        shown = self._board_tickets or (None if board_error else tickets)
        known_open: set[str] | None = (
            None if shown is None else {t.number for t in shown if t.state != "closed"})

        sandbox, ws = self._workspace()
        drafts = self._role().issues_for(
            sandbox=sandbox, workspace=ws, requirement=requirement,
            sources=self._sources())
        if not drafts.ok:
            # the ROLE's own words about its harness, and they used to be the client's sentence
            return [_could_not("não consegui quebrar esse requisito em frentes de trabalho que se "
                               "sustentassem, então não registrei nada.",
                               act="break a requirement into work", cause=drafts.error)]

        tracker = tracker or self._tracker()
        board = self._board_or_default(board)   # ADR-0030: production never used to pass one
        results: list[WriteResult] = []
        for draft in drafts.issues:
            results.append(self._file_one(draft, requirement, tracker, board,
                                          known_open=known_open))
        self._open_delivery(requirement, results)
        return results

    def file_defect(self, *, restated: str, reported_by: str, violates: int | None,
                    severity: str = "", source: str = "", tracker=None,
                    board=_UNSET) -> WriteResult:
        """Register a broken promise as work — classified, citing the requirement it violates.

        A defect skips the requirement-drafting ceremony ON PURPOSE: the promise already exists;
        what is being recorded is that reality disagrees with it. It still lands in Backlog, never
        TO-DO — starting the fix spends money, and that stays a person's call (ADR-0019 §5). The
        confirmation happened in the conversation (the channel holds the one yes, exactly like a
        requirement's); this method is the pen, not the judgement.

        And it is FOLLOWED UP: a delivery loop opens on the filed issue, so the weekly sweep can
        tell the person who reported it — unprompted — that the fix shipped. A bug report that
        vanishes into a board the client cannot see is indistinguishable from being ignored."""
        from openfactory.product.authoring import defect_body

        ctx = self.context()
        title = restated.strip().rstrip(".")[:80]
        tracker = tracker or self._tracker()
        try:
            # `by_number`, and INSIDE the guard. The first version called a `.get` the corpus
            # never had, so any defect that actually CITED a requirement — the case the answer
            # prompt explicitly asks her for — crashed before the try, reached the channel's
            # catch-all as a generic "broke" message, and the consumed confirmation was gone.
            cited = ctx.corpus.by_number(violates) if violates else None
            existing = tracker.find_ticket(title=title)
            if existing:
                return WriteResult(ok=True, ref=str(existing), existed=True,
                                   detail="já registrei esse problema antes")
            ref = tracker.create_ticket(
                title=title,
                body=defect_body(restated=restated, reported_by=reported_by,
                                 severity=severity, source=source,
                                 requirement=cited,
                                 # resolved, like every other citation this module writes: the
                                 # corpus's own field is a bare filename (`requirement_file`)
                                 requirement_path=(self._requirement_path(cited) if cited else ""),
                                 docs_repo=ctx.link.docs_repo,
                                 commit=ctx.docs_commit))
        except Exception as exc:  # noqa: BLE001 — a chat listener must never see a traceback
            return _could_not("não consegui registrar esse problema agora. Nada foi escrito — o "
                              "time foi avisado e resolve.",
                              act="file a defect", cause=exc)

        number = _as_ticket_number(ref)
        board = self._board_or_default(board)
        detail = ""
        if board is not None and number:
            placed = False
            try:
                url = self._issue_url(tracker, ref)
                board.add_item(issue_url=url)
                placed = bool(board.set_column(issue=str(number), issue_url=url,
                                               name=self.FILING_COLUMN))
            except Exception as exc:  # noqa: BLE001 — the issue exists; placement is repairable
                log.info("defect %s filed but not placed on the board (%s)", ref, exc)
            if not placed:
                # A `False` FROM THE BOARD IS THE INVISIBLE-CARD STATE, NOT A QUIETER SUCCESS.
                # `promote` checks this same bool; discarding it here meant a column-less card
                # that `readiness`/`propose_queue` (exact column match, no else-branch) can never
                # surface again — while the reply promised the client it was queued.
                log.warning("OPENFACTORY_PRODUCT_DEFECT_NOT_PLACED ref=%s column=%s — the card "
                            "exists "
                            "but has no column, so the queue cannot see it until a person places "
                            "it", ref, self.FILING_COLUMN)
                detail = ("registrei o problema, mas ainda não consegui posicionar o cartão no "
                          "quadro — o time foi avisado e posiciona.")
        if number:
            self._track_defect(number)
        return WriteResult(ok=True, ref=str(ref), detail=detail)

    def _track_defect(self, number: str) -> None:
        """A delivery loop on the fix, so 'consertamos o que você reportou' gets said unprompted.

        Subject `defeito-N` rather than a requirement number: the loop closes when THIS issue
        closes, and the sweep's delivered() pass already knows how to watch a set of issues."""
        try:
            from datetime import UTC, datetime

            from openfactory.memory import store as loop_store
            from openfactory.memory.ledger import DELIVERY, open_loop, waiting

            ledger = loop_store.read(self.project.name)
            already = {x.subject for x in waiting(ledger) if x.kind == DELIVERY}
            subject = f"defeito-{number}"
            if subject in already:
                return
            loop_store.write(self.project.name, [open_loop(
                DELIVERY, subject, owner="product", ts=datetime.now(UTC).isoformat(),
                context={"issues": str(number), "defect": "1"})])
        except Exception as exc:  # noqa: BLE001 — the defect was filed; only the courtesy is lost
            log.warning("could not start tracking defect #%s (%s) — the fix will ship without "
                        "anyone announcing it to the reporter", number, exc)

    def note_fact(self, *, term: str, body: str, said_by: str, where: str = "") -> WriteResult:
        """Write down one thing somebody said about the business — as `aprendido`, attributed.

        Refuses to silently overwrite: a term that already exists is answered with what is written,
        because two versions of the same fact is worse than either. Status stays `aprendido`
        (never `confirmado` from a chat message — domain.py's discipline), so recording this hands
        nothing new to the factory to defend."""
        from openfactory.product.authoring import record_fact

        ctx = self.context()
        if not ctx.available:
            return self._cannot_see_the_product()
        existing = ctx.domain.get(term)
        if existing is not None:
            return WriteResult(
                ok=False, existed=True,
                detail=f"já tenho isto anotado sobre {term!r} (por {existing.source or '?'}): "
                       f"{existing.body[:160]}")
        try:
            return record_fact(
                docs_repo=ctx.link.docs_repo,
                clone_url=self._clone_url(ctx.link.docs_repo),
                term=term, body=body, said_by=said_by, where=where,
                base=getattr(self.project.product, "docs_branch", "main"))
        except Exception as exc:  # noqa: BLE001
            return _could_not(f"não consegui anotar o que você me disse sobre {term!r} agora. Nada "
                              f"foi escrito — o time foi avisado e resolve.",
                              act="record a fact", cause=exc)

    def baseline(self, *, areas: list[str] | None = None) -> WriteResult:
        """The brownfield first pass: READ the source repository, write what it appears to do.

        Reverse engineering, with the one rule that makes it safe (brownfield.py): the output is
        OBSERVATIONS, never requirements. A requirement says what MUST be true; code says what IS
        true, bugs included. Turning the second into the first freezes bugs into promises the
        factory would then defend, and the provenance would be a lie — "asked by: the code" is
        not a person. So everything lands as `observed`, in ONE pull request, and a human turning
        an entry into `accepted` is the only event that creates a promise.

        Reads the CODE repo, writes to the DOCS repo — the two are different by design (ADR-0019)
        and this method is the only place they meet."""
        from openfactory.product.authoring import propose_baseline
        from openfactory.product.brownfield import milestone_files

        ctx = self.context()
        if not ctx.available:
            return self._cannot_see_the_product()

        sandbox, workspace = self._source_workspace()
        if workspace is None:
            return WriteResult(ok=False, detail="não consegui obter uma cópia do código para ler")

        answer = self._role().survey(sandbox=sandbox, workspace=workspace,
                                     areas=areas or [], layout=self._layout_hint(workspace))
        if not answer.ok or answer.baseline is None:
            return _could_not("li o produto e não consegui escrever um levantamento que se "
                              "sustentasse, então não registrei nada.",
                              act="survey the product", cause=answer.error)

        baseline = answer.baseline
        from datetime import UTC, datetime

        files = milestone_files(
            baseline, product=self.project.name,
            first_number=next_number(ctx.corpus),
            requirements_dir=ctx.requirements_dir,
            date=datetime.now(UTC).date().isoformat())
        try:
            return propose_baseline(
                docs_repo=ctx.link.docs_repo,
                token=self.token or "",   # `gh` has no ambient login in the worker
                forge_kind=self._forge_kind(),
                # "was this baseline already proposed?", through the port — the duplicate this
                # prevents is forty candidate requirements proposed twice
                forge=self._forge(),
                clone_url=self._clone_url(ctx.link.docs_repo),
                files=files, product=self.project.name,
                observations=len(baseline.observations), covered=baseline.covered,
                base=getattr(self.project.product, "docs_branch", "main"))
        except Exception as exc:  # noqa: BLE001 — a chat listener must not see a traceback
            return _could_not("não consegui escrever o levantamento agora. Nada foi registrado — o "
                              "time foi avisado e resolve.",
                              act="write the baseline", cause=exc)

    def _source_workspace(self):
        """A checkout of the SOURCE repository — what the survey reads.

        Every other operation here works on the DOCS checkout; this is the one that needs the
        code. Separate method so the difference is impossible to miss at a call site."""
        from openfactory.adapters.sandbox.base import Workspace
        from openfactory.adapters.sandbox.registry import judging_worktree
        from openfactory.runtime.repo_cache import RepoCache

        repo = self._source_repo()
        if not repo:
            return None, None
        try:
            url = self._clone_url(repo)
        except Exception as exc:  # noqa: BLE001 — `baseline()` calls this outside a try
            # `_clone_url` raises on a forge this deployment does not implement, which is the
            # honest error `build_forge` promises. It must not become a traceback in a chat
            # listener: the caller already answers "não consegui obter uma cópia do código".
            log.warning("product: cannot address the source repository of %s (%s) — the baseline "
                        "has nothing to read", getattr(self.project, "name", "?"), exc)
            return None, None
        from openfactory.loader import load_manifest_base_branch
        from openfactory.runtime.repo_cache import current_branch

        path = RepoCache().sync(f"{self.project.name}-source", url,
                                load_manifest_base_branch(self.project, default=""))
        if path is None:
            return None, None
        # THE WORKSPACE IS TOLD WHAT THE CHECKOUT ACTUALLY IS, not what this line hoped. Both
        # fields said `main` regardless, so on a `master` client every judgement the baseline
        # produced described its branch by a name that does not exist there.
        landed = current_branch(path) or "main"
        return judging_worktree(self.project, root=path), Workspace(path=str(path), branch=landed,
                                                                    base_branch=landed)

    @staticmethod
    def _layout_hint(workspace) -> str:
        """The top-level shape of the repo, so the survey starts from what exists rather than
        guessing directory names. Cheap: one listing, no reads."""
        from pathlib import Path as _P

        try:
            entries = sorted(p.name for p in _P(workspace.path).iterdir()
                             if not p.name.startswith("."))[:40]
            return "## Repository layout\n" + "\n".join(f"- {e}" for e in entries)
        except OSError:
            return ""

    def _open_delivery(self, requirement, results: list[WriteResult]) -> None:
        """The moment a requirement becomes filed work is the moment she starts WAITING on it
        (ADR-0021): a `delivery` loop opens here, and the weekly sweep closes it — by observing
        that every one of these issues is closed — and only then says "está pronto".

        Filing is the ONLY place this can open. `followup.deliveries_to_open` existed, was tested,
        and was called by nothing — the twelfth instance of this repo's signature defect, caught
        the same hour it was written. Closing worked; nothing ever opened, so "it's done" was a
        sentence she could still never say. Best-effort: the issues were filed either way, and a
        delivery she fails to track is a missing courtesy, not lost work — but it says so."""
        import logging

        log = logging.getLogger("openfactory.product")
        try:
            from openfactory.contracts.refs import ref_numbers

            landed = [r.ref for r in results if r.ok and r.ref]
            numbers = ref_numbers(landed)
            if not numbers:
                # No numeric ref among them. On a numeric tracker that means nothing landed; on a
                # provider whose refs are not numbers it means the ledger cannot key this delivery
                # yet (C-05). Either way the work IS filed — say which, rather than returning as if
                # nothing had happened.
                if landed:
                    log.info("delivery not tracked for %s: none of %s is a numeric ref — the "
                             "issues exist and the open-loop ledger is keyed by number",
                             self.project.name, landed)
                return
            from datetime import UTC, datetime

            from openfactory.memory import store as loop_store
            from openfactory.memory.ledger import waiting
            from openfactory.product.followup import OWNER, deliveries_to_open

            ledger = loop_store.read(self.project.name)
            fresh = deliveries_to_open({requirement.number: numbers},
                                       waiting(ledger, owner=OWNER),
                                       ts=datetime.now(UTC).isoformat())
            if fresh:
                loop_store.write(self.project.name, fresh)
        except Exception as exc:  # noqa: BLE001 — the work was filed; only the follow-up is lost
            log.warning("could not start tracking the delivery of REQ-%s (%s) — the work exists, "
                        "but nobody will announce when it is done", 
                        getattr(requirement, "number", "?"), exc)

    def _reused_card(self, draft, requirement, tracker,
                     known_open: set[str] | None) -> str | None:
        """The open card this front already lives on — VERIFIED — or None to file it normally.

        The verification is the whole point. `already_on_board` is a model's claim about a board,
        and honouring it unchecked would let one hallucinated number delete a front of work with
        nothing anywhere saying so. So an unconfirmable claim files the issue: a duplicate is
        visible on the board and a person can close it in one click, while work dropped on a claim
        nobody checked is invisible for ever and nobody ever learns it was owed. When the two
        failures are not symmetric, the guard must not be either.
        """
        claimed = draft.already_on_board
        if not claimed:
            return None
        if known_open is None:
            log.warning("OPENFACTORY_PRODUCT_REUSE_UNVERIFIED ref=#%s — the breakdown says this "
                        "front is "
                        "already carded, but the board could not be read, so the claim cannot be "
                        "checked. Filing it: a duplicate beats work silently dropped.", claimed)
            return None
        if claimed not in known_open:
            log.warning("OPENFACTORY_PRODUCT_REUSE_UNKNOWN ref=#%s — the breakdown named a card "
                        "that is "
                        "not open on the board we just read. Filing “%s” instead of trusting it.",
                        claimed, draft.title.strip()[:60])
            return None
        # The reuse is only half of it: a card serving a requirement that does not SAY so has the
        # same problem the duplicate had — the link exists in one chat message and nowhere a person
        # will ever look. Best-effort on purpose (the tracker contract in adapters/tracker/base.py:
        # best-effort is the caller's decision), because a refused comment must not turn a correct
        # reuse into a duplicate.
        try:
            from openfactory.product.voice import _pick

            tracker.comment(
                f"#{claimed}",
                _pick(_ALSO_SERVES, getattr(self.project, "language", None)).format(
                    number=f"REQ-{requirement.number:04d}", title=requirement.title))
        except Exception as exc:  # noqa: BLE001
            log.info("OPENFACTORY_PRODUCT_REUSE_UNANNOTATED ref=#%s req=%s (%s) — the card is "
                     "reused and "
                     "the citation is only in this line", claimed, requirement.number, exc)
        return claimed

    def _file_one(self, draft, requirement, tracker, board,
                  *, known_open: set[str] | None = None) -> WriteResult:
        title = draft.title.strip()
        reused = self._reused_card(draft, requirement, tracker, known_open)
        if reused:
            return WriteResult(ok=True, ref=f"#{reused}", existed=True,
                               detail=f"essa frente já está no #{reused} — apontei o requisito "
                                      f"para lá em vez de abrir um cartão novo")
        try:
            # An existing issue with this title is this operation's own prior result far more often
            # than it is a coincidence: a retried conversation must not file the work twice.
            existing = tracker.find_ticket(title=title)
            if existing:
                return WriteResult(ok=True, ref=str(existing), existed=True,
                                   detail="já existe um cartão com esse título")
            ref = tracker.create_ticket(
                title=title,
                body=issue_body(draft, requirement_path=self._requirement_path(requirement),
                                docs_repo=self.context().link.docs_repo,
                                docs_url=self._docs_url(),
                                commit=self.context().docs_commit))
        except Exception as exc:  # noqa: BLE001 — one bad issue must not lose the others
            return _could_not(f"não consegui registrar “{title}” agora. O time foi avisado e "
                              f"resolve — as outras frentes seguiram.",
                              act=f"file work: {title[:60]}", cause=exc)

        if board is not None:
            # A PLACEMENT THAT RAISED AND ONE THAT ANSWERED `False` ARE ONE STATE — a card with no
            # column, invisible to `readiness`/`propose_queue` for ever, while the reply says it is
            # in the Backlog. `file_defect` already reports them through a single flag; the branch
            # here was written twice and the raising half answered in English with the exception
            # inside it. One state, one sentence, one place to change it.
            from openfactory.contracts.refs import ref_number

            placed = False
            number = ref_number(ref)
            if number is None:
                # `BoardAdapter` is typed with an integer issue id (C-05). Until that changes, a
                # non-numeric ref cannot be placed — but the issue EXISTS, so this reports the same
                # way a board refusal does rather than raising over a courtesy.
                log.warning("OPENFACTORY_PRODUCT_CARD_NOT_PLACED ref=%s reason=non-numeric — the "
                            "board "
                            "port takes an integer issue id", ref)
                return WriteResult(ok=True, ref=str(ref),
                                   detail="criado, mas o quadro não aceitou a colocação — o "
                                          "cartão está sem coluna e o time foi avisado.")
            try:
                url = self._issue_url(tracker, ref)
                board.add_item(issue_url=url)
                placed = bool(board.set_column(issue=str(number), issue_url=url,
                                               name=self.FILING_COLUMN))
            except Exception as exc:  # noqa: BLE001 — the issue exists; placement is repairable
                log.info("work %s filed but not placed on the board (%s)", ref, exc)
            if not placed:
                log.warning("OPENFACTORY_PRODUCT_CARD_NOT_PLACED ref=%s column=%s — the "
                            "card exists "
                            ""
                            "but "
                            "has no column, so the queue cannot see it until a person places it",
                            ref, self.FILING_COLUMN)
                return WriteResult(ok=True, ref=str(ref),
                                   detail="criado, mas o quadro recusou a colocação — o cartão "
                                          "está sem coluna e o time foi avisado.")
        return WriteResult(ok=True, ref=str(ref))

    def _issue_url(self, tracker, ref: str) -> str:
        """Where a HUMAN opens the card just filed — ASKED of the tracker, never spelled here.

        This built `https://github.com/{repo}/issues/{n}` by hand, which is the exact call site
        `TrackerAdapter.ticket_url` was put on the port for: *"the platform sends people to
        tickets… and those call sites were building `https://github.com/{repo}/issues/{n}` by
        hand"*. On Azure Boards a work item lives at `/_workitems/edit/{id}` and on Jira at
        `/browse/KEY-1`, so the hand-built string is not merely a dead link — on GitHub Enterprise
        it points at public github.com, where a same-named repository may belong to somebody else.

        THE TRACKER IN HAND, NOT A FRESH ONE. `_file_one` calls this twice per card and already
        holds the adapter it created the ticket with; building another here would authenticate a
        second time per placement and, worse, could resolve a different one than the write used.

        "" when the provider cannot say — which is what the contract allows and what `add_item`
        and `set_column` already tolerate. A placement is repairable; an invented URL is not."""
        try:
            return str(tracker.ticket_url(str(ref)) or "")
        except Exception as exc:  # noqa: BLE001 — the ticket exists; a link is a courtesy
            log.warning("product: the tracker could not name a URL for %s (%s) — placing the card "
                        "without one", ref, exc)
            return ""

    def _source_repo(self) -> str:
        for axis in ("forge", "tracker"):
            ref = getattr(self.project, axis, None)
            if ref is not None and getattr(ref, "repo", None):
                return str(ref.repo)
        # SILENT UNTIL NOW, and it is the first rung of the ladder that decides whether the role
        # is told it can read the product's code. A deployment whose registry names no forge and
        # no tracker degrades every conversation to documentation-only, for ever, with nothing in
        # any log saying why — which is exactly the state that cost an hour of guessing when Nina
        # reported "o que está montado para mim veio vazio".
        log.warning("OPENFACTORY_PRODUCT_NO_SOURCE_REPO project=%s — neither `forge.repo` nor "
                    "`tracker.repo` is configured, so the code cannot be mounted and every answer "
                    "about current behaviour will be documentation-only",
                    getattr(self.project, "name", "?"))
        return ""

    def _sources(self) -> list[str]:
        """Every source repo of this product — a product spans N, and an issue must name which one
        it lands in."""
        from openfactory.product.loader import _read_docs_manifest

        docs, _ = _read_docs_manifest(Path(self.context().docs_path))
        return list(docs.sources) if docs else [self._source_repo()]

    def _tracker(self):
        """The project's tracker, built the same way the job runner builds it — same repo, same
        board coordinates, same App-token provider — and WATCHED.

        THE MODULE WATCHES WHAT THE MODULE PRODUCES, which is one rule and one place. An adapter
        handed in at a CALL SITE (`file_issues`, `file_defect`, `refine`) is the caller's own and
        is used as it came: every one of those callers is a test, because production reaches the
        forge through this default — the same thing placement had to learn (ADR-0030). Wrapping
        here rather than at each write is what makes the write somebody adds next month covered
        without anybody remembering to wire it."""
        inner = self._given_tracker
        if inner is None:
            from openfactory.credentials import tracker_token_for
            from openfactory.factory import _bot_token_provider

            # THIS PROJECT'S CREDENTIAL, NOT THE PROCESS'S. `tracker_token()` is one value for the
            # whole worker (`OPENFACTORY_TRACKER_TOKEN` / `OPENFACTORY_BOT_TOKEN`), and one
            # deployment now hosts
            # projects on different vendors. Handing an Azure Boards adapter the deployment's
            # GitHub PAT is not a failure that announces itself: the adapter presents it as HTTP
            # Basic to dev.azure.com and reads back a 401, so a credential that LOOKS configured
            # fails as if it had been revoked — and a github.com secret has been sent to Microsoft
            # on the way. `forge_token_for` already closed the same hole on the other axis (see
            # `ProductModule.token`); this module was the last reader of the process-wide one, and
            # every other build site in the codebase — the factory, the activities, the CLI, the
            # tech-lead — had already moved.
            #
            # It also matters for the SILENT half: a token that authenticates against the wrong
            # system does not raise, it answers an empty search — F-02 on fx-jira, where a board
            # with a ticket in TO-DO produced a pickup queue of `[]`.
            #
            # Unset `token_env` → `tracker_token()`, byte for byte, for every project that exists.
            tok = tracker_token_for(self.project)
            # Through the REGISTRY: whether this client keeps tickets in GitHub or Jira is the
            # deployment's business, not the product role's.
            from openfactory.adapters.tracker.registry import build_tracker

            inner = build_tracker(self.project, token=tok,
                                  token_provider=None if tok else _bot_token_provider())
        return _WatchedWrites(inner, self._write_outcome)

    # ---- what a person can ASK it to do --------------------------------------------------------

    def triage_board(self, *, token: str | None = None):
        """Read the board and report. Writes NOTHING (ADR-0019 / triage.py): asked or scheduled,
        this role has the least context exactly when it is told to look at everything at once."""
        from openfactory.product.triage import triage

        tickets, error = self._read_board(token=token)
        if error:
            return None, error
        # Kept for whoever holds this module next: the follow-up pass needs assignees (who to ask)
        # and closed states (what got delivered), and reading the board again to learn what this
        # call already knew would spend the shared GitHub quota twice for one answer. Before this
        # line, `_board_tickets` was only ever set by propose_queue — so on the sweep path it was
        # permanently empty, every question went unowned, and the delivery loop could NEVER close.
        self._board_tickets = tickets
        return triage(tickets), ""

    def introduce(self, *, areas: list[str] | None = None, with_situation: bool = True,
                  previous_backlog: int | None = None) -> str:
        """Arrive, and say where things stand.

        The situation is part of the introduction rather than a separate message: an agent that
        says hello and nothing else has to be asked a question before it is worth anything, and the
        first thing anybody wants to know is whether the factory is doing something."""
        from openfactory.product.queue import readiness
        from openfactory.product.voice import announcement

        cfg = getattr(self.project, "product", None)
        lang = getattr(self.project, "language", None)
        name = getattr(cfg, "agent_name", "") or ""
        requirements = len(self.context().corpus.requirements)
        state = None
        if with_situation:
            tickets, error = self._read_board()
            if not error:
                state = readiness(tickets)
        # arriving still works when the board does not: without a state it introduces itself and
        # says what it would do, which is more use than saying nothing
        return announcement(product=self.project.name, areas=areas, language=lang,
                            agent_name=name, readiness=state, requirements=requirements)

    def status_line(self) -> str:
        """Where things stand: the corpus, and whether this role can see it at all."""
        return self.health()

    def review_needs_action(self, *, token: str | None = None, limit: int = 10):
        """Classify what is parked, using the diagnosis the tech-lead already left on each ticket.

        Reads rather than asks: the diagnosis is a comment on the issue, and two agents conversing
        with no human in the loop is where two mistakes compound with nobody owning the result
        (ADR-0019 §6). Capped, because this costs one model call per parked ticket and a column
        with forty is a column that needs a person, not forty classifications."""
        from openfactory.product.board import parked_with_diagnosis
        from openfactory.product.needs_action import Verdict, classify_prompt, review

        ctx = self.context()
        if not ctx.available:
            return None, ctx.reason

        items, error = parked_with_diagnosis(self.project, token=token or self.token, limit=limit)
        # the one board read that does not come through `_read_board` — it happens inside board.py,
        # and it degrades the same way, so it reports through the same seam
        self._board_was_read(error)
        if error:
            return None, error
        if not items:
            return review([], may_act=False, agent_name=self._name(),
                          language=getattr(self.project, "language", None)), ""

        sandbox, ws = self._workspace()
        role = self._role()
        verdicts = []
        for item in items:
            answer = role.ask_json(
                sandbox=sandbox, workspace=ws,
                prompt=classify_prompt(ticket_number=item.number, title=item.title,
                                       body=item.body, diagnosis=item.diagnosis),
                phase="product_triage")
            # an unreadable classification is `unclear`, never a cause that would make it ACT
            verdicts.append(
                Verdict(ticket=item.number, **answer) if isinstance(answer, dict)
                else Verdict(ticket=item.number))
        return review(verdicts, may_act=False, agent_name=self._name(),
                      language=getattr(self.project, "language", None)), ""

    def break_down(self, number: int, *, actor: str, board=_UNSET):
        """Turn one requirement into units of work, filed into Backlog. Gated: this writes."""
        ctx = self.context()
        if not ctx.available:
            return [self._cannot_see_the_product()]
        requirement = ctx.corpus.by_number(number)
        if requirement is None:
            return [WriteResult(ok=False, detail=f"não encontrei o requisito {number}")]
        if not requirement.is_promise:
            # A proposal or a reading of the code is not something to build. Filing work from one
            # would commit the factory to a decision nobody has made.
            return [WriteResult(ok=False, detail=_not_a_promise(number, requirement))]
        return self.file_issues(requirement, actor=actor, board=board)

    def _name(self) -> str:
        return getattr(getattr(self.project, "product", None), "agent_name", "") or ""

    # ---- keeping the factory busy --------------------------------------------------------------

    #: Where approved work lands. A literal, as in `FILING_COLUMN`: this is the column the poller
    #: pulls from, so a caller able to name it is a money gate one argument wide.
    QUEUE_COLUMN = "TO-DO"

    def propose_queue(self, *, limit: int = 5, token: str | None = None):
        """What should start next, in order — and why each one, and why not the others.

        Returns `(readiness, proposal, error)`. The readiness is arithmetic over the board and is
        true whatever the model says; the ordering is the judgement. Keeping them separate is what
        makes "nothing is ready, these eleven need criteria first" an answer the role can give
        instead of a confident list it invented."""
        from openfactory.product.queue import (
            QueueProposal,
            proposal_prompt,
            readiness,
            whole_batches,
        )

        ctx = self.context()
        if not ctx.available:
            return None, None, ctx.reason

        tickets, error = self._read_board(token=token)
        if error:
            return None, None, error

        state = readiness(tickets)
        self._board_tickets = tickets   # kept so the reply can show titles without reading again
        by_number = {t.number: t for t in tickets}
        # TO-DO is included in the ordering, not just the backlog: the poller pulls in board order,
        # so an unordered queue is the factory doing the right work at the wrong time.
        candidates = [by_number[n] for n in (state.todo + state.ready) if n in by_number]
        if not candidates:
            return state, QueueProposal(), ""

        sandbox, ws = self._workspace()
        answer = self._role().ask_json(
            sandbox=sandbox, workspace=ws, phase="product_queue",
            # TITLES AND THE TOTAL. The prompt asks the role to judge whether a non-candidate looks
            # more valuable than what it proposed — over what used to be a list of bare integers,
            # which is a judgement the data cannot support. And the slice below is the caller's,
            # so the renderer could not say it had happened: `candidates[:40]` under a heading
            # reading "Candidates" says "this is everything ready", and 20 tickets could never be
            # proposed while the reply called the list complete.
            prompt=proposal_prompt(
                readiness=state, candidates=candidates[:40], limit=limit,
                titles={t.number: t.title for t in tickets},
                total_candidates=len(candidates)))
        if not isinstance(answer, dict):
            return state, None, "não consegui montar a proposta"

        proposal = QueueProposal(**answer)
        # never propose something that is not a candidate: a model naming a ticket that is parked,
        # unrefined or imaginary would have a person approving work that cannot start
        allowed = {t.number for t in candidates}
        proposal.items = [i for i in proposal.items if i.ticket in allowed]
        # THE LIMIT CUTS AT A BATCH BOUNDARY, NEVER INSIDE ONE. `[:limit]` was applied straight
        # after the ordering, so a group of three straddling position five was silently split: two
        # queued, one left behind, and staging carrying a change the client cannot exercise —
        # which is the sign-off that releases it to production.
        proposal.items, cut = whole_batches(proposal.items, limit)
        if cut:
            # NAMED, never a silent truncation. "What happened to the rest?" is the first question
            # a proposed queue gets, and an omission with no sentence reads as an oversight.
            left = ", ".join(f"#{i.ticket}" for i in cut)
            trailer = (f"Deixei para a próxima rodada o que não cabia inteiro agora: {left}.")
            proposal.note = f"{proposal.note} {trailer}".strip() if proposal.note else trailer
        return state, proposal, ""

    def promote(self, numbers: list[str], *, actor: str, board=None) -> list[WriteResult]:
        """Move approved tickets into the queue — the ONE action here that spends money.

        Gated on the allowlist, and ordered: they are moved in the sequence given, because the
        poller pulls in board order and an approved sequence that arrives shuffled is not the
        sequence anybody approved."""
        if not may_act(self.project, actor, via=self._via):
            return [WriteResult(ok=False, detail=unauthorized_message(self.project))]
        board = board or self._board()
        if board is None:
            return [WriteResult(ok=False, detail="não consegui acessar o quadro")]

        from openfactory.product.board import forget_board

        # what we cached describes a board we are about to change
        forget_board(getattr(self.project, "name", ""))
        # ONE tracker for the whole batch: it is only consulted for the card's URL, and building
        # one per number would authenticate once per card moved.
        tracker = self._tracker()
        out: list[WriteResult] = []
        for number in numbers:
            try:
                url = self._issue_url(tracker, number)
                board.add_item(issue_url=url)
                moved = board.set_column(issue=str(number), issue_url=url,
                                         name=self.QUEUE_COLUMN)
                out.append(WriteResult(ok=bool(moved), ref=f"#{number}",
                                       detail="" if moved else "o quadro recusou a movimentação"))
            except Exception as exc:  # noqa: BLE001 — one failure must not lose the rest
                # A CLIENT READS THIS ONE. Both branches of the reply speak it — the whole-failure
                # branch as the entire message, the partial one under a pt-BR headline — so
                # `str(exc)` here made "1 não entraram:" continue into a `gh api graphql` argv
                # carrying the mutation and the board's field ids.
                out.append(_could_not(f"não consegui mover o #{number} para a fila agora. O time "
                                      f"foi avisado e resolve.",
                                      act="queue approved work", cause=exc, ref=f"#{number}"))
        return out

    def _board_or_default(self, board):
        """The board a filed card is placed on — the real one unless a caller injected something.

        `board=None` WAS THE DEFAULT AND PRODUCTION NEVER OVERRODE IT. Every placement sat behind
        `if board is not None`, supplied only from tests, so `FILING_COLUMN = "Backlog"` was reached
        by nothing and filed work landed on the board with NO column. It is then invisible to
        `readiness` and `propose_queue`, which match column names exactly — the role could never
        surface it again, while the reply told the client "Estão no Backlog" and the defect reply
        promised "entra na fila de correção quando o time aprovar a próxima leva". Both false, and
        unfalsifiable from inside the conversation.

        An optional argument that only tests supply is the definition of unreachable code. The
        default is now the real board; `None` still means "deliberately do not place", which the
        `_UNSET` sentinel keeps distinguishable — `None` alone could not express both.
        """
        return self._board() if board is _UNSET else board

    def _board(self):
        """The board this module places cards on — watched, like the tracker and for the same
        reason: a placement that raised, or that answered `False`, leaves a card with no column,
        invisible to the queue for ever, while the reply told the client it was filed."""
        inner = self._given_board
        if inner is None:
            # Through the FACTORY, never by naming a vendor: whether this deployment keeps its
            # board in GitHub Projects or somewhere else is the registry's business, not the
            # product role's.
            from openfactory.adapters.board import build_board
            from openfactory.credentials import tracker_token_for

            # Per project, for the reason spelled out at `_tracker`: the board axis reads the
            # tracker's credential, and a deployment's GitHub PAT offered to an Azure Boards board
            # is the same wrong-system 401 wearing a different call site.
            inner = build_board(self.project, token=tracker_token_for(self.project) or self.token)
        return None if inner is None else _WatchedWrites(inner, self._write_outcome)

    # ---- refining what is not ready ------------------------------------------------------------

    _REFINE_SCHEMA = (
        'Return ONLY a JSON object (no prose, no code fences):\n'
        '{"criteria": [str], "out_of_scope": [str], "questions": [str], "cites": int|null}\n'
        '`criteria` are observable statements: someone reading them can say whether the change is '
        'done, without opening the code. Never write HOW to build it — that is not yours, and a '
        'criterion phrased as an implementation is one the reviewer cannot check.\n'
        '`questions` is for what you could not determine. An empty list on a vague ticket is a '
        'warning sign, not a success: say what a person still has to answer.'
    )

    def refine(self, number: str, *, actor: str, tracker=None):
        """Give a backlog ticket something testable to be judged against.

        The most common reason a job parks is a ticket nobody can evaluate, and rewriting one is
        exactly this role's layer: WHAT must be true, never how. A ticket that already states
        something testable is left alone — improving prose nobody complained about is how an agent
        churns a board and teaches people to stop reading its comments."""
        # THE REF IS THE PROVIDER'S OPAQUE STRING (C-05). Normalised here rather than
        # trusted, because the callers are a chat entry and a board read: `#412`, `412`
        # and a stray space are the same card, and `t.number == number` is an identity
        # test that fails silently on the difference.
        number = canonical_ref(number)
        from openfactory.product.queue import has_criteria

        ctx = self.context()
        if not ctx.available:
            return self._cannot_see_the_product()
        if not may_act(self.project, actor, via=self._via):
            return WriteResult(ok=False, detail=unauthorized_message(self.project))

        tickets, error = self._read_board()
        if error:
            # `read_board`'s error is written for an operator and NAMES THE REPOSITORY — "could not
            # list the issues of ClientOrg/client-repo". Returned as the detail, it was the
            # client's whole reply on the ordinary transient this deployment lives with, a
            # throttled quota. The two siblings below already said this in pt-BR; refine is the one
            # that had never been given a sentence.
            return _could_not(_BOARD_UNREADABLE, act=f"refine #{number}", cause=error)
        ticket = next((t for t in tickets if t.number == number), None)
        if ticket is None:
            return WriteResult(ok=False, detail=f"não encontrei o #{number}")
        if has_criteria(ticket):
            return WriteResult(ok=True, ref=f"#{number}", existed=True,
                               detail="esse já diz quando estaria pronto — não mexi")

        sandbox, ws = self._workspace()
        answer = self._role().ask_json(
            sandbox=sandbox, workspace=ws, phase="product_refine",
            prompt=("Este item não diz quando estaria pronto, então seria recusado na entrada. "
                    "Escreva o que precisa ser verdade para considerá-lo feito, no nível do "
                    "PRODUTO.\n\n"
                    f"## Item #{ticket.number} — {ticket.title}\n\n{ticket.body}\n\n"
                    + self._REFINE_SCHEMA))
        criteria = (answer or {}).get("criteria") or []
        if not isinstance(answer, dict) or not criteria:
            return WriteResult(ok=False, ref=f"#{number}",
                               detail="não consegui escrever critérios que se sustentassem")

        body = _with_criteria(ticket.body, answer, agent=self._name(),
                              language=getattr(self.project, "language", None))
        tracker = tracker or self._tracker()
        # TWO WRITES, TWO OUTCOMES — the rule `close_card` states, and the third card writer to
        # need it. One `try` around both makes a note that failed report the REWRITE as a failure,
        # and here that answer is not merely wrong, it is self-repairing in the worst direction:
        # the criteria are on the card, the client is told they are not, and the next attempt —
        # theirs or the sweep's — reads a card it believes still has none and appends a SECOND set
        # under its own heading. That is the two-sets-on-one-card state `_ALSO_CALLED` exists to
        # repair, manufactured by the repair.
        try:
            tracker.update_body(f"#{number}", body)
        except Exception as exc:  # noqa: BLE001 — a chat listener must not see a traceback
            return _could_not(f"não consegui escrever os critérios no #{number} agora. Nada mudou "
                              f"no cartão — o time foi avisado e resolve.",
                              act=f"refine #{number}", cause=exc, ref=f"#{number}")
        from openfactory.product.board import forget_board

        # BEFORE the second write, not after it: what we cached describes a card that no longer
        # exists, and `has_criteria` is read from that snapshot. Leaving the invalidation behind a
        # write that can fail is what turns a lost note into a duplicated set of criteria.
        forget_board(getattr(self.project, "name", ""))
        detail = f"{len(criteria)} critérios"
        try:
            tracker.comment(f"#{number}", _refine_note(answer, agent=self._name()))
        except Exception as exc:  # noqa: BLE001 — the criteria landed; the note only repeats them
            # `detail` ON AN OK RESULT MEANS WHAT THE WRITE DID NOT DO — the reading `close_card`
            # and `align_card` share, and the reason the reply that speaks it must not ALSO claim
            # the note (their headlines take that as a flag). Announcing a comment that does not
            # exist is the same act as announcing a card that was never closed.
            log.warning("OPENFACTORY_PRODUCT_REFINE_UNEXPLAINED card=#%s (%s) — the criteria were "
                        "written "
                        "and the comment attributing them was not", number, exc)
            detail = (f"escrevi os critérios no #{number}, mas não consegui deixar o comentário "
                      f"dizendo que fui eu — isso está escrito no próprio item. O time foi "
                      f"avisado.")
        return WriteResult(ok=True, ref=f"#{number}", detail=detail)

    # ---- maintaining the cards themselves --------------------------------------------------------

    def close_card(self, number: str, *, actor: str, in_favour_of: str | None = None,
                   reason: str = "") -> WriteResult:
        """Close one card, naming the one that stays — the hand behind a decision already taken.

        THIS DID NOT EXIST, AND A DECISION WAS LOST TO ITS ABSENCE. On 2026-07-31 she proposed
        closing #511 in favour of #288, an authorised person confirmed, she answered "Registrado o
        pedido junto ao time" — and nothing happened. #511 stayed open, the next queue proposal put
        it first, and the client had been invited to check a board for a request nobody had made.
        The same class as "aposentar" before `drop` existed: an everyday product act with no
        operation behind it, so the agent describes instead of acting.

        ONE ACT, LINKED BOTH WAYS. The closing comment names the survivor and travels with the
        close itself; the survivor is told what was folded into it. A close with no pointer leaves
        the next reader asking why work disappeared, and a pointer with no close leaves the
        duplicate on the board — which is precisely the state this repairs.

        `actor` is the RAW Slack id, the thing `may_act` checks; the `<@…>` mention is decoration
        and appears only in what gets written.

        Deliberately does NOT require the requirements corpus: this is bookkeeping on the board,
        and making it wait on a documentation checkout would leave a duplicate open because a
        different repository was unreachable.
        """
        # THE REF IS THE PROVIDER'S OPAQUE STRING (C-05). Normalised here rather than
        # trusted, because the callers are a chat entry and a board read: `#412`, `412`
        # and a stray space are the same card, and `t.number == number` is an identity
        # test that fails silently on the difference.
        number = canonical_ref(number)
        in_favour_of = canonical_ref(in_favour_of) or None
        if not may_act(self.project, actor, via=self._via):
            return WriteResult(ok=False, detail=unauthorized_message(self.project))

        tickets, error = self._read_board()
        if error:
            return _could_not(_BOARD_UNREADABLE, act=f"close #{number}", cause=error)
        card = next((t for t in tickets if t.number == number), None)
        if card is None:
            return WriteResult(ok=False, detail=f"não encontrei o cartão #{number} no quadro")
        if card.state != "open":
            # A BUSINESS ANSWER, NOT A BREAKAGE. Somebody got there first — say so and stop; the
            # confirmation that authorised this was about a card that no longer needs it.
            return WriteResult(ok=False, existed=True, ref=f"#{number}",
                               detail=f"o #{number} já estava fechado — não mexi nele")

        survivor = None
        if in_favour_of is not None:
            survivor = next((t for t in tickets if t.number == in_favour_of), None)
            if survivor is None:
                return WriteResult(
                    ok=False,
                    detail=f"não encontrei o #{in_favour_of} no quadro, então não fechei o "
                           f"#{number}: mandar quem ler procurar um cartão que não existe é pior "
                           f"do que deixar os dois abertos.")
            if survivor.state != "open":
                # THE BOARD IS READ WITH `--state all`, so a card closed last month is on this list
                # and passes the check above. Folding work into it closes both and the work is
                # tracked nowhere — worse than the dangling pointer refused just above, because
                # this one reads as correct on the way past. `_orphans` applies the same rule.
                return WriteResult(
                    ok=False,
                    detail=f"o #{in_favour_of} também já está fechado, então não fechei o "
                           f"#{number}: os dois fechados quer dizer que ninguém está olhando esse "
                           f"trabalho. Me digam qual cartão fica com ele.")

        tracker = self._tracker()
        try:
            # NOT A DELIVERY. This act takes an item off the list of work — "deixa de ser algo a
            # fazer", in the words the client confirms — which is the opposite of shipping it.
            # Left as the default, `#511` (closed as a duplicate of `#288` at a client's request)
            # came back marked completed and read as delivered work everywhere downstream.
            tracker.close_ticket(
                f"#{number}", delivered=False,
                reason=_closing_note(in_favour_of=in_favour_of, actor=actor,
                                     reason=reason, agent=self._name()))
        except Exception as exc:  # noqa: BLE001 — a chat listener must not see a traceback
            return _could_not(f"não consegui fechar o #{number} agora. Nada mudou — o time foi "
                              f"avisado e resolve.",
                              act=f"close #{number}", cause=exc, ref=f"#{number}")

        from openfactory.product.board import forget_board

        forget_board(getattr(self.project, "name", ""))   # what we cached is now wrong

        detail = ""
        if survivor is not None:
            try:
                tracker.comment(f"#{in_favour_of}",
                                _survivor_note(closed=number, actor=actor, agent=self._name()))
            except Exception as exc:  # noqa: BLE001 — the close happened; only the pointer is lost
                log.warning("OPENFACTORY_PRODUCT_CLOSE_UNLINKED closed=#%s survivor=#%s (%s) — the "
                            "surviving card does not say what was folded into it", number,
                            in_favour_of, exc)
                detail = (f"fechei o #{number}, mas não consegui deixar o registro disso no "
                          f"#{in_favour_of}. O time foi avisado.")
        return WriteResult(ok=True, ref=f"#{number}", detail=detail)

    def align_card(self, number: str, *, requirement: int, actor: str) -> WriteResult:
        """Make a card execute the requirement it should — citation AND what it must satisfy.

        THE HALF `refine` CANNOT DO. `refine` exists to unblock a card with nothing testable on it,
        and it correctly refuses one that already says when it would be done ("o #516 já dizia
        quando estaria pronto — não mexi"). So a change carried by a NEW requirement had no way of
        reaching cards written against the old text.

        THIS COSTS A MODEL CALL AND CHANGES WHAT GETS BUILT, which is why it is separated from
        `repoint_orphans` and why the channel stages a confirmation before calling it. Re-deriving
        criteria is a judgement; re-pointing a citation is not.

        The body is edited SECTION BY SECTION rather than re-rendered: a card is not only what this
        platform wrote into it — #288 predates every requirement and was typed by a person, and
        others carry a refinement or an argument in the description.
        """
        # THE REF IS THE PROVIDER'S OPAQUE STRING (C-05). Normalised here rather than
        # trusted, because the callers are a chat entry and a board read: `#412`, `412`
        # and a stray space are the same card, and `t.number == number` is an identity
        # test that fails silently on the difference.
        number = canonical_ref(number)
        from openfactory.product.role import IssueDraft

        ctx = self.context()
        if not ctx.available:
            return self._cannot_see_the_product()
        if not may_act(self.project, actor, via=self._via):
            return WriteResult(ok=False, detail=unauthorized_message(self.project))
        req = ctx.corpus.by_number(requirement)
        if req is None:
            return WriteResult(ok=False,
                               detail=f"não encontrei o requisito {requirement} escrito na base")
        if not req.is_promise:
            # Aligning onto a retired text is the very defect this method repairs, performed on
            # purpose — and the printed rule on the card would then order the old promise built.
            # Aligning onto a text nobody has agreed to is the same act one step earlier: the card
            # would carry criteria derived from a proposal, under a rule saying nothing may go
            # beyond it, while the client may still say no. `break_down` refuses both.
            return WriteResult(ok=False, detail=_not_a_promise(requirement, req))

        tickets, error = self._read_board()
        if error:
            return _could_not(_BOARD_UNREADABLE, act=f"align #{number}", cause=error)
        card = next((t for t in tickets if t.number == number), None)
        if card is None:
            return WriteResult(ok=False, detail=f"não encontrei o cartão #{number} no quadro")

        sandbox, ws = self._workspace()
        answer = self._role().ask_json(
            sandbox=sandbox, workspace=ws, phase="product_align",
            # the SAME schema `refine` writes criteria against — one shape for "what must be true
            # about a card", so the two cannot drift into producing different-looking cards
            prompt=(f"Este cartão foi escrito a partir de outro texto e precisa passar a executar "
                    f"o requisito abaixo. Reescreva o que precisa ser verdade para considerá-lo "
                    f"feito, no nível do PRODUTO e SOMENTE a partir deste requisito: nada pode "
                    f"entrar que o requisito não peça, e o que ele mudou em relação ao texto "
                    f"anterior tem de aparecer.\n\n"
                    f"## Requisito REQ-{req.number:04d} — {req.title}\n\n{req.body}\n\n"
                    f"## Cartão #{card.number} — {card.title}\n\n{card.body}\n\n"
                    + self._REFINE_SCHEMA))
        criteria = (answer or {}).get("criteria") or []
        if not isinstance(answer, dict) or not criteria:
            return WriteResult(ok=False, ref=f"#{number}",
                               detail=f"não consegui escrever critérios que se sustentassem a "
                                      f"partir do requisito {requirement} — não mexi no cartão")

        # `issue_body` renders it, as it rendered the card in the first place. The draft carries
        # only what the rewritten sections need: everything else in the card — its objective,
        # what somebody added by hand — is left exactly where it is.
        #
        # THE EXCLUSIONS TRAVEL WITH THE CRITERIA. The model is asked for `out_of_scope` by the
        # same schema (`_REFINE_SCHEMA`) and the answer used to be dropped, so an aligned card came
        # out carrying the RETIRED requirement's exclusions under a Source line ordering the
        # executor not to go beyond the new one — one new set and one stale one, which is the
        # defect this method exists to repair.
        #
        # EVERY SECTION THE PLATFORM WRITES ONTO A CARD IS NAMED HERE, and one left off the list is
        # one the alignment keeps from the retired text. `refine` writes a third — the open
        # questions, closing with the line attributing the criteria to what the card already
        # described — and `issue_body` renders no such section, so both go: what was
        # unresolved about the OLD text is not unresolved about this one, and the attribution stops
        # being true the moment the criteria are re-derived. The questions THIS pass could not
        # answer go in the comment (`_align_note`), where nothing orders an executor to meet them.
        canonical = issue_body(IssueDraft(acceptance_criteria=criteria,
                                          out_of_scope=answer.get("out_of_scope") or [],
                                          cites=requirement),
                               requirement_path=self._requirement_path(req),
                               docs_repo=ctx.link.docs_repo, docs_url=self._docs_url(),
                               commit=ctx.docs_commit)
        # BY THE CANONICAL NAME, which is what reaches the second name too: `_section_re` expands
        # every heading through `_ALSO_CALLED`, and that expansion is one-way. Named as "Em
        # aberto" — as this was until #160 — the strip matched only the Portuguese spelling, so a
        # card refined AFTER the headings were canonicalised kept the retired text's open
        # questions under a Source line ordering the executor to meet the new requirement.
        body = _rewritten(card.body, canonical,
                          ("Acceptance criteria", "Out of scope", "Open questions", "Source"))

        # TWO WRITES, TWO OUTCOMES — the discipline `close_card` states and these two siblings did
        # not copy. Sharing one `try` reports a landed rewrite as a total failure whenever the note
        # that explains it fails afterwards, and the admin is told the card still executes the old
        # text while its criteria have in fact already been replaced.
        tracker = self._tracker()
        try:
            tracker.update_body(f"#{number}", body)
        except Exception as exc:  # noqa: BLE001
            return _could_not(f"não consegui reescrever o #{number} agora. O time foi avisado e "
                              f"resolve.",
                              act=f"align #{number} to REQ-{requirement:04d}", cause=exc,
                              ref=f"#{number}")
        from openfactory.product.board import forget_board

        forget_board(getattr(self.project, "name", ""))
        detail = f"{len(criteria)} critérios"
        try:
            tracker.comment(f"#{number}", _align_note(requirement, answer, agent=self._name()))
        except Exception as exc:  # noqa: BLE001 — the card was rewritten; the note explains it
            log.warning("OPENFACTORY_PRODUCT_ALIGN_UNEXPLAINED card=#%s requirement=%s (%s) — the "
                        "criteria were replaced and nothing on the card says so", number,
                        requirement, exc)
            detail = (f"alinhei o #{number}, mas não consegui deixar escrito nele que o texto "
                      f"anterior foi substituído. O time foi avisado.")
        return WriteResult(ok=True, ref=f"#{number}", detail=detail)

    def orphaned_cards(self) -> list[tuple[str, int, int]]:
        """`(card, the requirement it cites, the promise it should cite)` — read-only, no model.

        WHAT A REPLACEMENT LEAVES BEHIND. REQ-0004 was agreed, became fourteen cards, and was then
        replaced by REQ-0006; the cards kept citing the retired text, pinned to its file and its
        commit, under the printed rule that nothing in them may go beyond that requirement. Follow
        the rule and you build the old promise.

        Deterministic on purpose: the successor is written in the corpus, so naming it needs no
        judgement and costs nothing — which is what makes the repair something the platform may
        perform on its own."""
        return [(card.number, cited, successor) for card, cited, successor in self._orphans()]

    def repoint_orphans(self, *, actor: str = "") -> list[WriteResult]:
        """Re-point every orphan's citation at the promise that replaced it. One result per card.

        WHAT IT DELIBERATELY DOES NOT DO IS THE POINT: the criteria are left exactly as they are.
        Re-deriving them spends money and changes what gets BUILT, and that is a decision somebody
        makes (`align_card`, staged behind a confirmation). Re-pointing a citation is bookkeeping
        the platform owes for a supersession it performed itself — so the comment says plainly that
        the criteria below it were written against the older text and nobody has revisited them.

        NOT GATED, AND `actor` DEFAULTS TO NOBODY, because this must be able to run unattended: an
        orphan discovered on a Sunday is a card somebody may pick up on Monday and build wrong. It
        is safe to leave ungated precisely because it decides nothing — it repairs a pointer the
        platform wrote and that the platform can prove is stale.

        THE EXCEPTION IS DECLARED, NOT ASSUMED. This is the only write in this module with no human
        anywhere — not in the module, not one layer up in the channel — so it is named in the
        AUTHORITY block at the top of this file, beside the three whose yes lives in the
        conversation. An exemption argued only in the method that takes it reads exactly like an
        omission nobody noticed, which is the mistake the tracker contract avoids by declaring
        `link_child` and `children_of` where the rule itself is written.

        THE BOUNDARY, and it is the whole of the argument above:

            it may change WHICH REQUIREMENT A CARD CITES — and nothing else on the card
            it may aim only at the successor THE CORPUS NAMES — never at a text it chose
            it takes NO card and NO requirement from its caller — `actor` is all it accepts

        Widen any of the three and this stops being bookkeeping and becomes a decision taken in a
        client's name with nobody asked. `tests/test_card_maintenance.py` fails if it does.

        IDEMPOTENT BY CONSTRUCTION rather than by a guard: a card citing a live requirement is not
        an orphan, so the second run has nothing to find.
        """
        ctx = self.context()
        tracker = None            # built only if there is something to write
        results: list[WriteResult] = []
        for card, cited, successor in self._orphans():
            req = ctx.corpus.by_number(successor)
            body = _with_section(card.body, "Source", self._source_section(req))
            if body == card.body:
                continue
            tracker = tracker or self._tracker()
            try:
                tracker.update_body(f"#{card.number}", body)
            except Exception as exc:  # noqa: BLE001 — one card must not lose the others
                results.append(_could_not(
                    f"não consegui atualizar o #{card.number} — ele continua apontando para o "
                    f"texto antigo, e o time foi avisado.",
                    act=f"repoint #{card.number} to REQ-{successor:04d}", cause=exc,
                    ref=f"#{card.number}"))
                continue
            try:
                tracker.comment(f"#{card.number}",
                                _repoint_note(cited=cited, successor=successor, actor=actor,
                                              agent=self._name()))
            except Exception as exc:  # noqa: BLE001 — the citation moved; the warning did not
                # SEPARATE FROM THE BODY WRITE, and here the cost of conflating them is permanent:
                # the card has stopped being an orphan, so no later sweep comes back for the
                # sentence saying its criteria were written against the older text. Reporting the
                # whole card as failed on top of that would hide the one repair that DID land.
                log.warning("OPENFACTORY_PRODUCT_REPOINT_UNEXPLAINED card=#%s requirement=%s "
                            "(%s) — "
                            ""
                            "the "
                            "citation moved and nothing on the card warns that what it asks for "
                            "was written against the replaced text", card.number, successor, exc)
            results.append(WriteResult(ok=True, ref=f"#{card.number}",
                                       detail=f"passou a executar o requisito {successor}"))
        if results:
            from openfactory.product.board import forget_board

            forget_board(getattr(self.project, "name", ""))
        return results

    def _orphans(self) -> list[tuple[object, int, int]]:
        """`(ticket, cited, successor)` — the ONE reading both public operations stand on.

        Kept together so the list a person is shown and the repair that runs can never disagree
        about what an orphan is. An unreadable corpus or board yields nothing rather than a guess:
        both already report themselves through their own seam."""
        ctx = self.context()
        if not ctx.available:
            return []
        tickets, error = self._read_board()
        if error:
            return []
        out: list[tuple[object, int, int]] = []
        for card in sorted(tickets, key=lambda t: ref_sort_key(t.number)):
            if card.state != "open":
                continue          # a closed card executes nothing; rewriting it is noise
            cited = _cited_requirement(card.body)
            if cited is None:
                continue
            req = ctx.corpus.by_number(cited)
            if req is None or req.is_live:
                continue
            successor = _successor(ctx.corpus, cited)
            if successor is None or successor == cited:
                # abandoned, a chain that leads nowhere, or a replacement still waiting for a yes —
                # in all three there is nothing anybody has agreed to point this card at
                continue
            out.append((card, cited, successor))
        return out

    def _source_section(self, requirement) -> str:
        """The `## Source` block citing `requirement`, rendered by the SAME function that writes a
        card in the first place.

        `issue_body` is handed a draft with nothing else in it because nothing else is taken from
        the render. A private copy of this wording would be the second renderer of one artefact,
        which is how this repo's formats drift apart."""
        from openfactory.product.role import IssueDraft

        ctx = self.context()
        return _section_of(issue_body(IssueDraft(cites=requirement.number),
                                      requirement_path=self._requirement_path(requirement),
                                      docs_repo=ctx.link.docs_repo, docs_url=self._docs_url(),
                                      commit=ctx.docs_commit),
                           "Source")


#: `REQ-0004` — the citation, read only from where a citation MEANS something (see below).
_CITES_RE = re.compile(r"REQ-(\d{4})")


#: Every heading THIS PLATFORM has written over one section of a card. `issue_body` names the
#: criteria in English — the executor reads that body — and `refine` names them in pt-BR
#: (`_with_criteria`, written for the client who reads the same card), so a card that has been
#: through both carries whichever came last.
#:
#: Surgery that recognises one name does not replace the other: it ADDS a second, contradictory set
#: of criteria under a comment saying the previous text was substituted, and whoever picks the card
#: up builds the older promise — the exact defect `align_card` exists to repair, performed by
#: `align_card`. One section, one identity, whatever it was called on the day it was written.
#:
#: EVERY SECTION WRITTEN UNDER TWO NAMES BELONGS HERE, not the one the defect was found on. The
#: exclusions are the same trap one section down — `issue_body` calls them "Out of scope" and
#: `_with_criteria` calls them "Fora de escopo" — and they are read by the same executor, under the
#: same rule that nothing may go beyond the requirement.
#: EVERY NAME EVER MINTED STAYS READABLE. `_with_criteria` stopped writing the Portuguese three
#: (#160) — one section, one identity — but cards written before that are on real boards now, and
#: a reader that stops recognising them silently reads an empty section and re-adds one.
_ALSO_CALLED: dict[str, tuple[str, ...]] = {
    "acceptance criteria": ("Critérios de aceite", "Criterios de aceite"),
    "out of scope": ("Fora de escopo",),
    "open questions": ("Em aberto",),
}


def _section_re(heading: str) -> re.Pattern[str]:
    """One `## Heading` block, heading included, up to the next heading or the end.

    Case-insensitive because a card is a document people edit; the same tolerance `corpus._field_re`
    extends to a hand-written status line, and for the same reason. Every name the platform has
    used for that section matches (`_ALSO_CALLED`)."""
    names = "|".join(re.escape(name) for name
                     in (heading, *_ALSO_CALLED.get(heading.strip().lower(), ())))
    return re.compile(rf"^##\s+(?:{names})\s*$.*?(?=^##\s|\Z)",
                      re.MULTILINE | re.DOTALL | re.IGNORECASE)


def _section_of(text: str, heading: str) -> str:
    """That section verbatim, or "" when the document has none."""
    m = _section_re(heading).search(text or "")
    return m.group(0).rstrip() if m else ""


def _with_section(body: str, heading: str, section: str) -> str:
    """`body` with its `## heading` replaced by `section`, added when it has none.

    SURGERY, NEVER A RE-RENDER. A card carries more than this platform put in it: somebody refined
    it, somebody argued in the description, and the oldest ones were typed by a person before any
    requirement existed. Rebuilding the whole body from a template to change one section would take
    all of that away — and an agent that silently replaces what people wrote teaches them to
    distrust everything it touches (`_with_criteria` states the same rule for the same reason)."""
    if not section:
        return body
    text = body or ""
    pattern = _section_re(heading)
    if pattern.search(text):
        # A function rather than a replacement string, so a `\g` or a backslash inside the rendered
        # section is not read as a backreference by `re.sub` — the citation carries a path and a
        # repository name. EVERY block of this section is consumed and only the first is written
        # back: a card that already carries two (one under each name the platform has used for it)
        # must not come out of a replacement still carrying a stale one.
        written = []

        def _replace(_match: re.Match[str]) -> str:
            written.append(True)
            return section + "\n\n" if len(written) == 1 else ""

        return pattern.sub(_replace, text).rstrip() + "\n"
    # SOURCE IS THE LAST SECTION A CARD CARRIES — `issue_body` puts it there, and it ends with the
    # rule about not going beyond the requirement. Anything else being ADDED goes above it, so the
    # criteria never land underneath the sentence that closes the card.
    anchor = _section_re("Source").search(text) if heading.lower() != "source" else None
    if anchor:
        return (text[:anchor.start()].rstrip() + "\n\n" + section + "\n\n"
                + text[anchor.start():].strip() + "\n")
    return text.rstrip() + "\n\n" + section + "\n"


def _without_section(body: str, heading: str) -> str:
    """`body` with every `## heading` block taken out, under any name the platform gave it.

    EVERY block, not the first: a card that has been through both writers carries the section twice
    (`_ALSO_CALLED`), and removing one of the two leaves the reader the older half."""
    pattern = _section_re(heading)
    if not pattern.search(body or ""):
        return body
    return re.sub(r"\n{3,}", "\n\n", pattern.sub("", body or "")).rstrip() + "\n"


def _rewritten(body: str, canonical: str, headings: tuple[str, ...]) -> str:
    """`body` with each of `headings` taken from `canonical` — INCLUDING the ones `canonical` does
    not have, which are REMOVED.

    THE ABSENT SECTION IS THE DANGEROUS ONE. These are the parts of a card this platform writes,
    re-derived here from a different requirement; one the new render is silent about is not one to
    keep, it is the retired text's — and it stays under a Source line telling whoever works the
    card not to go beyond the new requirement. A card carrying one fresh set and one stale one is
    the exact state the alignment exists to repair.

    `_with_section` leaves an empty section alone on purpose — `repoint_orphans` moves a citation
    and must not delete criteria it deliberately did not revise — so the removal is stated here,
    where the caller is replacing the whole set at once."""
    for heading in headings:
        section = _section_of(canonical, heading)
        body = _with_section(body, heading, section) if section \
            else _without_section(body, heading)
    return body


def _cited_requirement(body: str) -> int | None:
    """The requirement a card says it EXECUTES, read from its own `## Source` section.

    Only from there. A number in the objective is prose — somebody explaining themselves — while
    the Source line is the one an executor is told not to go beyond, and repointing on a mention
    would rewrite cards nobody claimed were derived from anything."""
    m = _CITES_RE.search(_section_of(body or "", "Source"))
    return int(m.group(1)) if m else None


def _successor(corpus, number: int) -> int | None:
    """The PROMISE at the end of a supersession chain, or None.

    FOLLOWED TO THE END, NOT ONE HOP: 0002 → 0004 → 0006 has to land on 0006, and a card repointed
    at 0004 would be an orphan again the moment anybody looked at it.

    A PROMISE, NOT MERELY A TEXT THAT IS STILL LIVE. `proposed` and `observed` are live — neither
    is superseded nor dropped — and neither is something the factory may be pointed at.
    `propose_requirement` stamps `superseded-by` on the predecessors in the SAME commit that writes
    the replacement as `proposed`, and the recovery sweep merges it into the branch everyone reads
    before anybody has said yes. Landing on `is_live` therefore retargeted thirteen cards onto a
    text the client had not agreed to, unattended, within the hour — and announced it to them. This
    is `break_down`'s rule, which was stated one method away and not copied.

    None for an abandoned requirement, and None while the replacement is only proposed: nothing has
    taken its place YET, the cards stay where they are, and the next sweep after the confirmation
    repairs them. None for a chain that loops or dangles, for the same reason `corpus._cross_check`
    calls a dangling pointer worse than no pointer at all.

    "NOTHING TO AIM AT" IS NOT "NOTHING THERE", and a caller must not read it as one. Whether a
    replacement EXISTS is a different question with a different answer — REQ-0008 `superseded-by
    0009` with 0009 still `proposed` is the ordinary healthy shape — and answering it from this
    None told a client a readable text could not be found. Anything that has to NAME the
    replacement rather than act on it walks the chain for that question, never this one."""
    seen: set[int] = set()
    current = corpus.by_number(number)
    while current is not None and not current.is_promise:
        if current.superseded_by is None or current.number in seen:
            return None
        seen.add(current.number)
        current = corpus.by_number(current.superseded_by)
    return current.number if current is not None else None


def _not_a_promise(number: int, requirement) -> str:
    """Why the factory may not be aimed at this text, in the client's terms — ONE sentence for the
    two acts that aim it (`break_down` files work from a requirement, `align_card` rewrites a card
    against one), because a person told two different things about one rule learns the rule is
    arbitrary.

    Three answers, not one, and the difference is what the person can do next: a retired text has a
    replacement to ask about, a proposal needs a yes, and a reading of the code was never a promise
    at all — telling somebody "it is not agreed" about a brownfield observation invites them to
    agree to a description of the bugs the product already has."""
    from openfactory.product.corpus import OBSERVED

    if not requirement.is_live:
        return (f"o requisito {number} já não vale, então mandar construir a partir dele seria "
                f"pedir um texto aposentado. Me diga qual requisito vale hoje e eu sigo com esse.")
    if requirement.status == OBSERVED:
        return (f"o {number} é o que eu li que o sistema já faz hoje, não algo que vocês pediram — "
                f"construir a partir dele seria transformar o comportamento actual em promessa, "
                f"defeitos inclusive. Se é isso que tem de valer, me digam e eu registro primeiro.")
    return (f"o requisito {number} ainda não foi acordado, então não dá para virar trabalho: "
            f"enquanto ele for só uma proposta, construir a partir dele seria decidir por vocês. "
            f"Me confirmem esse requisito e eu sigo.")


def _closing_note(*, in_favour_of: str | None, actor: str, reason: str,
                  agent: str = "") -> str:
    """What the closed card is left saying. Written for whoever opens it in six months and asks
    why the work disappeared — so it names the decision, the person, and where the work went."""
    from openfactory.product.voice import signature

    who = f"<@{actor}>" if actor else "o time"
    note = f"{signature(agent)} fechado a pedido de {who}"
    note += (f", em favor do #{in_favour_of}: o trabalho passa a ser acompanhado lá."
             if in_favour_of else ".")
    if reason:
        note += f"\n\n{reason.strip()}"
    return note


def _survivor_note(*, closed: str, actor: str, agent: str = "") -> str:
    """The other half of the link. Without it the surviving card never learns it absorbed
    something, and whoever picks it up works from half the conversation."""
    from openfactory.product.voice import signature

    who = f"<@{actor}>" if actor else "o time"
    return (f"{signature(agent)} o #{closed} foi fechado em favor deste, a pedido de {who}. Se "
            f"havia algo escrito lá que não está aqui, vale trazer antes de começar.")


def _align_note(requirement: int, answer: dict, *, agent: str = "") -> str:
    from openfactory.product.voice import signature

    note = (f"{signature(agent)} este cartão passou a executar o requisito {requirement}, e "
            f"reescrevi o que precisa ser verdade para dá-lo por pronto a partir dele — o texto "
            f"que ele seguia antes foi substituído. Corrijam se eu entendi errado.")
    if answer.get("questions"):
        note += "\n\nO que eu não consegui determinar:\n" + "\n".join(
            f"- {q}" for q in answer["questions"])
    return note


def _repoint_note(*, cited: int, successor: int, actor: str = "", agent: str = "") -> str:
    """Says what changed AND what deliberately did not.

    The second half is the one that matters: whoever picks this card up has to know that what it
    asks for was written against the older text, or they will read the new citation and assume
    somebody checked."""
    from openfactory.product.voice import signature

    who = f", a pedido de <@{actor}>" if actor else ""
    return (f"{signature(agent)} este cartão passou a executar o requisito {successor}{who}: o "
            f"requisito {cited}, que ele citava, foi substituído por aquele.\n\n"
            f"**O que está escrito aqui como \"pronto\" continua igual, e foi escrito a partir do "
            f"texto antigo.** Não revisei nada disso: rever pode mudar o que vai ser construído, "
            f"e essa é uma decisão de vocês, não uma arrumação minha.")


#: What an EXISTING card is told when the breakdown reuses it for a new requirement (#160). It
#: lands on the client's own card, unprompted — the link would otherwise live in one chat message
#: and nowhere anybody will look.
_ALSO_SERVES = {
    "pt-BR": ("Este cartão também atende o requisito {number} — {title}. Nenhum cartão novo foi "
              "criado para essa frente."),
    "en": ("This card also serves requirement {number} — {title}. No new card was created for "
           "that strand."),
}

#: The one PROSE line `_with_criteria` writes under the headings (#160).
_CRITERIA_FROM_WHAT_WAS_THERE = {
    "pt-BR": "critérios escritos a partir do que já estava descrito.",
    "en": "criteria written from what was already described.",
}


def _with_criteria(body: str, answer: dict, *, agent: str = "",
                   language: str | None = None) -> str:
    """The original text plus what must be true. APPENDED, never replaced: somebody wrote that
    description, and an agent that silently rewrites it teaches people to distrust everything it
    touches.

    THE HEADINGS ARE THE PLATFORM'S, THE SENTENCE IS THE CLIENT'S (#160). This wrote three
    Portuguese headings — "Critérios de aceite", "Fora de escopo", "Em aberto" — into cards that
    `authoring.py` writes in English, on any project, in any language. That is not a translation
    bug, it is the SECOND NAME that `_ALSO_CALLED` exists to survive, minted by us: a card through
    both writers carries two contradictory acceptance sections and whoever picks it up builds the
    older promise.

    A heading here is read back — `_section_re` matches it, and the executor's "nothing beyond the
    requirement" rule stands on it — so it is an identity, not prose, and identities do not get
    translated (`techlead/voice.py` states the rule for the other phrasebook). The signature line
    under it IS prose, and that is what follows the project's language.
    """
    from openfactory.product.voice import _pick, signature

    parts = [(body or "").rstrip(), "", "## Acceptance criteria", ""]
    parts += [f"- [ ] {c}" for c in answer.get("criteria") or []]
    if answer.get("out_of_scope"):
        parts += ["", "## Out of scope", ""] + [f"- {c}" for c in answer["out_of_scope"]]
    if answer.get("questions"):
        parts += ["", "## Open questions", ""] + [f"- {q}" for q in answer["questions"]]
    parts += ["", f"_{signature(agent)} {_pick(_CRITERIA_FROM_WHAT_WAS_THERE, language)}_"]
    return "\n".join(parts)


def _refine_note(answer: dict, *, agent: str = "") -> str:
    from openfactory.product.voice import signature

    note = (f"{signature(agent)} este item não dizia quando estaria pronto, então seria recusado "
            f"na entrada. Escrevi {len(answer.get('criteria') or [])} critérios a partir do que já "
            f"estava descrito — corrijam se eu entendi errado.")
    if answer.get("questions"):
        note += "\n\nO que eu não consegui determinar:\n" + "\n".join(
            f"- {q}" for q in answer["questions"])
    return note


def _as_ticket_number(ref) -> int:
    """A ref as a number, or 0 when it carries none.

    Kept returning 0 for its existing callers, which compare against it. `ref_number` is the
    honest primitive — it returns None, because 0 reads as a real issue number all the way down —
    and this is the thin shim for the call sites that still expect the old contract (C-05)."""
    from openfactory.contracts.refs import ref_number

    return ref_number(ref) or 0
