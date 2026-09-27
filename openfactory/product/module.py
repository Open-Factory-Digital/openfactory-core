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

WHAT WRITES WITHOUT ASKING `may_act`, AND ON WHOSE AUTHORITY. Seven methods here change a client's
board or their documentation without calling the gate themselves. They are LISTED, rather than left
to be found by reading all of them, because a deliberate exception nobody wrote down is
indistinguishable from a forgotten one — the reason the tracker contract declares `link_child` and
`children_of` in the same breath as the rule they are exempt from.

    file_defect · file_ticket ·           THE YES IS ONE LAYER UP. The channel stages the act,
    note_fact · baseline
                                          checks `may_act`, and only then calls these; the
                                          conversation holds the confirmation and is the record of
                                          it. They are the pen, never the judgement.

    record_answer                         THE PERSON ALREADY SPOKE, ON THE FACTORY'S OWN CARD.
                                          The sweep records what the requester answered to a
                                          question the factory asked them there (ADR-0048 §6):
                                          provenance, not authorisation — `said_by` is the card's
                                          author, verbatim, and the requester of a card is on no
                                          product allowlist. It writes nothing the person did not
                                          write, and only where the factory said it would.

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

    record_distillate                     NOBODY IS ASKED, AND NOTHING IS DECIDED (#269 slice 3,
                                          ADR-0053 D4). What a conversation that went quiet agreed,
                                          asked and decided, as a model read it, written once per
                                          span under `conversations/` in the context repository,
                                          naming nobody. It is evidence the role cites with its
                                          date, never a requirement, a decision or a fact — those
                                          stay a person's confirmation (D14) — and it writes only
                                          a file of its own, never one a person wrote.

Adding another is not forbidden. Leaving it off this list is.

WHERE IT RUNS. The agent works inside the DOCUMENTATION checkout, because that is what almost every
product question is about. It is given the path of the source checkout when one is available, but
whether it can read outside its working directory depends on the harness (`-s read-only` confines
Codex; Claude's tool allowlist does not). So code reading is stated as a bonus rather than promised
— an honest limitation is worth more than a capability that works on one engine and silently does
not on another.
"""

from __future__ import annotations

import functools
import logging
import os
import re
import threading
from pathlib import Path

from openfactory.adapters.board.columns import CANONICAL_COLUMNS
from openfactory.contracts.document import CLIENT
from openfactory.contracts.refs import canonical_ref, ref_sort_key
from openfactory.ops.impediment import PRODUCT_BOARD_UNREADABLE as _IMP_BOARD
from openfactory.ops.impediment import PRODUCT_CANNOT_WRITE as _IMP_WRITE
from openfactory.ops.impediment import PRODUCT_CORPUS_UNREADABLE as _IMP_CORPUS
from openfactory.ops.impediment import PRODUCT_MOUNT_EMPTY as _IMP_MOUNT_EMPTY
from openfactory.ops.impediment import PRODUCT_NO_CODE as _IMP_NO_CODE
from openfactory.product.authoring import (
    WriteResult,
    filed_by_the_product_role,
    issue_body,
    next_number,
    propose_requirement,
    requirement_file,
)
from openfactory.product.corpus import requester_identity
from openfactory.product.loader import ProductContext, load_product_context
from openfactory.product.requester import forge_identity_for
from openfactory.product.role import ProductAnswer, ProductRole

log = logging.getLogger("openfactory.product")

#: The two mount names USED TO LIVE HERE, as `DOCS_DIRNAME`/`CODE_DIRNAME`, with a note saying the
#: prompt is told these paths and a rename that did not reach it would send the role looking in a
#: directory that does not exist. The note was right about the danger and wrong about the remedy:
#: two constants kept in step by hand are the danger, not the cure. `mounted()` now DERIVES the
#: names from where `compose()` actually put things, so there is nothing left to keep in step.

#: One lock per composed root — a project's cached view — so two turns never compose it at once,
#: and a turn's own view is never linked from a root another turn is rebuilding (#266 slice 2).
_VIEW_LOCKS: dict[str, threading.Lock] = {}
_VIEW_LOCKS_GUARD = threading.Lock()


def _view_lock(root: str) -> threading.Lock:
    with _VIEW_LOCKS_GUARD:
        return _VIEW_LOCKS.setdefault(root, threading.Lock())


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


def _docs_root(module, *, default: str) -> Path | None:
    """Where the documentation is in `module`'s view: at its root, or under `docs/` beside the
    sources — as `_workspace` built it (`_docs_at`), or `default` for a view somebody else built.

    A FUNCTION OF THE MODULE'S STATE, NOT A METHOD, because `mounted` is asked of stand-ins that
    carry the state and none of the methods."""
    root = getattr(module, "_combined", None)
    if not root:
        return None
    at = getattr(module, "_docs_at", None) or default
    return Path(root) if at == "." else Path(root) / at


def _with_facts(out: dict[str, str], facts, root) -> dict[str, str]:
    """`mounted` plus the `facts` door — ONLY when its manifest is on disk (#33). The same rule
    the `okf` key follows one line up: the prompt is built in a process that does not stand in
    the workspace, so the existence question is answered here, where the absolute path is."""
    if facts and root and (Path(facts) / "README.md").is_file():
        out["facts"] = os.path.relpath(str(facts), str(root))
    return out


def _the_read_model(module, root) -> dict:
    """What the facts pack is handed of the product's read model (#267): `{"model", "speaker"}`,
    or `{}` when this pass is not answering somebody's question.

    ONLY FOR AN ANSWER. `answer()` marks the module (`_facts_for`); a draft, a judgement or a
    survey writes the pack it always wrote. The model reads the floor, the jobs, the threads and
    the forge — worth it for "why did #42 stop?", not for "is this a yes?".

    ONCE PER MODULE, which is once per turn: the module is built fresh for every message, and the
    role is built more than once inside one.

    THE SPEAKER ONLY IN A VIEW OF THE TURN'S OWN. The files may call the person asking "you" only
    when no other conversation's turn can read them; a turn that fell back to the shared directory
    (`_own_view`'s degrade) gets files that name nobody at all."""
    if not hasattr(module, "_facts_for"):
        return {}
    if "_product_model" not in vars(module):
        try:
            from openfactory.product import model as read_model

            ctx = module.context()
            # THE LOOPS ARE THE AGENDA THIS CONVERSATION MAY READ (#267 slice 3), in the model as
            # in `loops.md`: its now.md and the briefing are read by this turn, and a decision
            # asked in somebody's private conversation is not this room's to see, named or not
            conversation = str(getattr(module, "_conversation", "") or "")
            module._product_model = read_model.build(
                module.project, corpus=ctx.corpus if ctx.available else None,
                loops_seen=lambda member: _loops_seen_in(member, conversation, member.name))
        except Exception as exc:  # noqa: BLE001 — the pack it always wrote still goes out
            log.warning("[%s] the product's read model could not be built (%s) — the facts "
                        "pack goes without it", getattr(module.project, "name", "?"), exc,
                        exc_info=True)
            module._product_model = None
    model = module._product_model
    if model is None:
        return {}
    own = bool(root) and getattr(module, "_turn_view", None) == str(root)
    # AND THE DOCUMENTS THIS TURN MAY BE SHOWN BY NAME (#269): an internal one only in a view of
    # the turn's own — a pack another conversation's turn may read is written for a client
    audience = getattr(module, "_documents_audience", CLIENT) if own else CLIENT
    return {"model": model, "speaker": module._facts_for if own else "", "audience": audience}


def _the_sight(module):
    """The turn's sight (`ProductModule.sight`), or None for a stand-in that carries the module's
    state and none of its methods — the prompt then says nothing it did not check."""
    look = getattr(module, "sight", None)
    return look() if callable(look) else None


def _the_chain(module, read_model: dict) -> str:
    """The traceability chain for this turn's facts pack (#268 slice 3, `product/chain.py`) — only
    for an answer to somebody, like the read model it walks; "" otherwise, or when it could not be
    walked (said in the log, and the pack goes out without it).

    A FUNCTION OF THE MODULE'S STATE, like `_the_read_model`: it is asked of stand-ins too."""
    if not hasattr(module, "_facts_for"):
        return ""
    from openfactory.product import chain
    from openfactory.product.sources import declared

    try:
        docs = _docs_root(module, default="docs")
        made = chain.build(read_model.get("model"), _the_sight(module),
                           declared=declared(docs).repos if docs is not None else [],
                           docs_root=docs)
        mounted = getattr(module, "mounted", None)
        where = (mounted() if callable(mounted) else {}).get("docs") or "docs"
        return made.render(docs=where)
    except Exception as exc:  # noqa: BLE001 — the pack it always wrote still goes out
        log.warning("[%s] the chain could not be walked (%s) — the facts pack goes without it",
                    getattr(getattr(module, "project", None), "name", "?"), exc, exc_info=True)
        return ""


def _the_briefing(module):
    """The briefing this turn's answer carries (#267 slice 2, `product/briefing.py`), rendered for
    the person it answers and in their register — or None: the switch is off, the pass answers
    nobody, or there is no read model.

    ALWAYS "YOU" FOR THE SPEAKER, unlike the files. The files may be read by another
    conversation's turn when the view degrades to the shared directory (`_the_read_model`); the
    prompt is this turn's alone.

    ONCE PER MODULE, like the model it is rendered from — the role is built more than once in a
    turn — and ONE LOG LINE, which is what #266's battery (#281) reads to tell its two arms apart
    and to size the one that carries it."""
    if not hasattr(module, "_facts_for"):
        return None
    if "_briefing" in vars(module):
        return module._briefing
    from openfactory.product import briefing as situation

    name = getattr(module.project, "name", "?")
    made = None
    model = vars(module).get("_product_model")
    if not situation.enabled():
        log.info("OPENFACTORY_PRODUCT_BRIEFING project=%s state=off (%s) — the answer carries the "
                 "board section instead", name, situation.SWITCH_ENV)
    elif model is None:
        log.info("OPENFACTORY_PRODUCT_BRIEFING project=%s state=no-model — the answer carries the "
                 "board section instead", name)
    else:
        try:
            made = situation.render(model, speaker=module._facts_for,
                                    raw=bool(getattr(module, "_raw_diagnosis", False)),
                                    audience=getattr(module, "_documents_audience", CLIENT))
            log.info("OPENFACTORY_PRODUCT_BRIEFING project=%s state=on lines=%d chars=%d "
                     "left_out=%d raw=%s", name, len(made.lines), len(made.text), made.left_out,
                     "yes" if made.raw else "no")
        except Exception as exc:  # noqa: BLE001 — the board section still goes out
            log.warning("[%s] the briefing could not be rendered (%s) — the answer carries the "
                        "board section instead", name, exc, exc_info=True)
    module._briefing = made
    return made


def _the_search_scope(module, root) -> tuple[str, str, bool]:
    """`(audience, conversation, own)` a turn's searches of the product's memory run with (#269
    slice 2): the documents the turn may be shown, the conversation it answers in, and whether
    the facts pack is this turn's alone. A pack another conversation's turn may read — the shared
    view's degrade — is searched as a room: the client's audience, and no private line at all."""
    own = bool(root) and getattr(module, "_turn_view", None) == str(root)
    audience = getattr(module, "_documents_audience", CLIENT) if own else CLIENT
    return audience, str(getattr(module, "_conversation", "") or ""), own


def _the_attachments(module) -> tuple[dict[str, str], list[tuple[str, bytes]]]:
    """The files the message being answered carries (#336), for the pack: `({found name: text},
    [(found name, image bytes)])` — and, on the module, the line per file the role is told.
    Read once per module, which is once per turn; `({}, [])` for a message without files."""
    if "_attached_read" in vars(module):
        return module._attached_read
    files = list(getattr(module, "_attachments", ()) or ())
    module._attached_listed = []
    module._attached_read = ({}, [])
    if not files:
        return module._attached_read
    from openfactory.product.attachments import Attachment, for_the_turn

    try:
        wanted = [Attachment(id=str(f.get("id", "")), name=str(f.get("name", "")),
                             type=str(f.get("type", "")), size=int(f.get("size") or 0))
                  for f in files if isinstance(f, dict)]
        texts, images, listed = for_the_turn(
            module.project, wanted, conversation=str(getattr(module, "_conversation", "") or ""))
    except Exception:  # noqa: BLE001 — the answer goes out, and the role is told the files failed
        log.warning("[%s] the message's files could not be read",
                    getattr(module.project, "name", "?"), exc_info=True)
        texts, images = {}, []
        listed = [{"n": n, "name": str(f.get("name", "a file")), "file": "",
                   "said": "could not be read just now"}
                  for n, f in enumerate(files, start=1) if isinstance(f, dict)]
    module._attached_listed = listed
    module._attached_read = (texts, images)
    return module._attached_read


def _the_search_before_the_turn(module, root) -> tuple[dict[str, str], list[str]]:
    """THE ENGINE RETRIEVES BEFORE THE TURN (#269 slice 2, ADR-0053 D8): the product's index
    brought up to what this turn read — its corpus, its board, its conversations — then searched
    from the message, and the hits written as `found/before-the-turn.md` in the facts pack.
    `({}, [])` when this pass answers nobody or the switch is off; `({}, [gap])` when the memory
    could not be searched — a gap in the manifest, never "nothing was found".

    ONCE PER MODULE, which is once per turn: the role is built again for a draft or a judgement
    after the answer, and that pack carries the same file — the search is not run, nor recorded,
    a second time.

    NEVER UNDER THE SEMAPHORE, and nowhere near it: this runs while the pack is written, before the
    model is asked, and the search itself refuses to run under the lock (`index/search.py`)."""
    from openfactory.product import semaphore
    from openfactory.product.index import retrieval

    question = str(getattr(module, "_question", "") or "")
    if not hasattr(module, "_facts_for") or not question.strip() or not retrieval.enabled():
        return {}, []
    if "_found_before" in vars(module):
        return module._found_before
    project = module.project
    if semaphore.held_here(project):
        return {}, []
    audience, conversation, own = _the_search_scope(module, root)
    try:
        ctx = module.context()
        cards = module._board_cards()
        retrieval.refresh(project, corpus=ctx.corpus if ctx.available else None,
                          requirements_dir=getattr(ctx, "requirements_dir", "requirements"),
                          cards=cards, said=retrieval.said_of(project))
        _found, text = retrieval.before_the_turn(
            project, question=question, said=str(getattr(module, "_said_before", "") or ""),
            audience=audience, conversation=conversation, own=own)
    except Exception as exc:  # noqa: BLE001 — the answer goes out without it, and says so
        # THE WORDS OF WHAT FAILED GO TO THE LOG, never into the manifest the role reads and a
        # client may be answered from (`_could_not`'s rule, for this branch too)
        log.warning("[%s] the product's memory could not be searched before the turn (%s)",
                    getattr(project, "name", "?"), exc, exc_info=True)
        module._found_before = ({}, [
            "the product's memory could not be searched before this message (the reason is in "
            "the platform's log) — what it holds about this is unknown, not absent: say you could "
            "not look, never that nothing was found"])
        return module._found_before
    module._found_before = ({f"{retrieval.FOUND_DIR}/{retrieval.BEFORE}": text}, [])
    return module._found_before


def _takes(fn, name: str) -> bool:
    """Whether `fn` declares the keyword `name`, by name or through `**kwargs` — read from the
    signature, so a double written before the keyword is called exactly as before."""
    import inspect

    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD
                                 for p in params.values())


def _the_view_s_gap(module) -> list[str]:
    """The manifest's word on what this turn's view leaves out (#269 slice 3): a count, never a
    name — "could not be shown" never becomes "is not there" (ADR-0041)."""
    held = int(getattr(module, "_view_withheld", 0) or 0)
    if not held:
        return []
    if held < 0:
        return ["the documents of the context repository could not be judged for this "
                "conversation, so none are in your workspace — what they say is unknown, not "
                "absent"]
    return [f"{held} document(s) of the context repository are not in your workspace: they may "
            f"not be shown to this conversation. Never say they do not exist, and never guess "
            f"what they say"]


def _done_before(module, text: str) -> list:
    """THE WHOLE MEMORY, FOR "WAS THIS DONE BEFORE?" (#269 slice 3, ADR-0053 D7): what the
    product's index holds that may be the thing asked for — requirements whatever became of them,
    closed cards of any age, documents, distilled conversations — searched in THIS turn's scope
    (`_the_search_scope`: the audience it may be shown, its own conversation) and recorded.

    OUTSIDE THE SEMAPHORE, ALWAYS: this runs while the turn is answered or drafted, before anything
    is staged, and the search itself refuses to run under the lock (`index/search.py`). `[]` when
    retrieval is off, when the calling thread holds the semaphore, or when the index could not be
    searched — a lead lost, said in the log, never an answer lost."""
    from openfactory.product import semaphore
    from openfactory.product.index import retrieval

    project = getattr(module, "project", None)
    if not str(text or "").strip() or not retrieval.enabled():
        return []
    try:
        if semaphore.held_here(project):
            return []
        audience, conversation, own = _the_search_scope(module, getattr(module, "_combined", None))
        return list(retrieval.done_before(project, text, audience=audience,
                                          conversation=conversation, own=own).hits)
    except Exception as exc:  # noqa: BLE001 — the board, the corpus and the loops still answer
        log.warning("[%s] the product's memory could not be searched for what was already asked "
                    "(%s)", getattr(project, "name", "?"), exc)
        return []


def _may_search(module) -> bool:
    """Whether this pass may offer the role `[[BUSCA: …]]` (#269 slice 2): an answer to somebody,
    with its facts pack written — where the hits go — and retrieval on."""
    from openfactory.product.index.retrieval import enabled

    return (hasattr(module, "_facts_for") and bool(getattr(module, "_facts_dir", None))
            and bool(str(getattr(module, "_question", "") or "").strip()) and enabled())


def _log_mount(project, root, *, docs, code, mounted=(), missing=None) -> None:
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

    EVERY SOURCE OF THE PRODUCT, AND ONE VERDICT (#268). `mounted` names the repositories placed and
    `missing` the ones that could not be, with the sentence the prompt carries. The prompt tells
    the role the team already knows when code is missing, so the impediment is opened for ANY
    declared source missing — not only the project's own — and closed only when none is. One
    verdict per turn: two calls with two verdicts would open and close the ticket in one message.
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
    missing = dict(missing or {})
    said = "; ".join(f"{repo}: {why}" for repo, why in missing.items())
    (log.warning if missing else log.info)(
        "OPENFACTORY_PRODUCT_SOURCES project=%s mounted=%s missing=%s", name,
        ",".join(mounted) or "(none)", said or "(none)")
    # the factory hears about it too, and keeps hearing until it works again
    if not isinstance(project, str):
        _tell_the_factory(project, _IMP_MOUNT_EMPTY, line, ok=not empty)
        _tell_the_factory(project, _IMP_NO_CODE,
                          f"{line}{f' missing={said}' if said else ''} — a agente respondeu sem "
                          f"poder abrir o código",
                          ok=bool(code) and n_code > 0 and not missing)


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


def _asked_of(person: str, conversation: str) -> dict[str, str]:
    """Whom a decision is asked of, and where, as a loop's `context` holds it — `{}` for nobody.

    SEALED, NEVER NAMED (`speaker.sealed`). The ledger is read into every conversation's prompt —
    the decisions register the role opens, the "possibly already asked" section — and the chase
    reads `context["person"]` to address a reminder in the product's room. What scoping needs is
    to COMPARE a speaker with the person asked, so a digest is all that is kept: nobody's name
    reaches another conversation from here, and no reminder starts naming people it did not."""
    from openfactory.product.conversation import owner_of
    from openfactory.product.speaker import sealed

    who = sealed(person)
    if not who:
        return {}
    # A PRIVATE ONE BY ITS OWNER (#335): asked in one of a person's sessions, it is on their agenda
    # and answered from any of them — the reading it had when a person had one conversation
    return {"asked_of": who, "asked_in": sealed(owner_of(conversation))}


def _scope_of(loop) -> dict[str, str]:
    ctx = loop.context or {}
    who = str(ctx.get("asked_of") or "")
    return {"asked_of": who, "asked_in": str(ctx.get("asked_in") or "")} if who else {}


def _answered_by(loop, *, person: str, where: tuple[str, ...], room: str) -> bool:
    """Whether `person`, speaking in `where` (the conversation, and the room it lives in), is who
    this decision was asked of, there. A loop that records nobody — opened before #266 slice 4 —
    is answered by a message in its own room, which is the narrowest the old rows allow."""
    from openfactory.product.conversation import owner_of
    from openfactory.product.speaker import sealed

    scope = _scope_of(loop)
    if not scope:
        return loop.about == room
    return (scope["asked_of"] == sealed(person)
            and scope["asked_in"] in {sealed(owner_of(w)) for w in where if w})


def _acceptances_here(project, ledger, conversation: str | None) -> list:
    """The open acceptances a message in `conversation` may answer (#267 slice 3).

    AN ACCEPTANCE ASKED IN A PRIVATE CONVERSATION IS ANSWERED THERE, AND NOWHERE ELSE: the delivery
    was announced to the person who asked, where they asked (`events.deliver`), and somebody else's
    "funcionou" in the room must neither close it nor be told which delivery it closed. One asked
    in the room is answered from anywhere, as every acceptance was before. `None` — a caller that
    names no conversation — reads them all, as before; "" is a conversation nobody could name,
    which answers the room's alone. The one rule the agenda and the chat use (`agenda.sees`)."""
    from openfactory.memory.ledger import ACCEPTANCE, waiting
    from openfactory.product.followup import OWNER

    open_acc = [x for x in waiting(ledger, owner=OWNER) if x.kind == ACCEPTANCE]
    if conversation is None:
        return open_acc
    from openfactory.product import agenda, events

    here = agenda.Viewer(own=conversation)
    room = events.room_of(project)
    return [x for x in open_acc if agenda.sees(here, agenda.audience(x, room=room))]


def _loops_seen_in(project, conversation: str, name: str) -> list:
    """THE ROLE'S AGENDA, AS THE CONVERSATION IT IS ANSWERING MAY READ IT (#267 slice 3) — the
    ledger the facts pack renders (`loops.md`, `decisions.md`), filtered by the one rule the
    panel's agenda and the chat use (`agenda.visible`): the room's items, and `conversation`'s own.
    A room's turn is read by everyone in the room, so it never carries a delivery owed to somebody
    in their private conversation; a turn nobody's conversation is known for (the factory's own)
    reads the room's alone."""
    from openfactory.memory import store as loop_store
    from openfactory.product import agenda, events

    return agenda.visible(loop_store.read(name), agenda.Viewer(own=conversation),
                          room=events.room_of(project))


def may_act(project, user_id: str, *, via: str = "api") -> bool:
    """Whether this PERSON may make the product role WRITE (a requirement PR, an issue).

    Empty allowlist = nobody. Reading is not gated: what the product promises is not a secret from
    the channel it is discussed in.

    BY PERSON, NEVER BY A VENDOR'S USER ID (#266 slice 6, ADR-0051 D16). `user_id` is a person of
    the platform — the id the identity provider knows them by, which is what `product.admins`
    lists. A chat add-on maps its own users to those people before a message reaches the door
    (`adapters/channel/base.py::PeopleOfAChannel`); a user it could not map is a GUEST
    (`speaker.GUEST`), and a guest is refused here whatever the list says — so no spelling an
    add-on invents for somebody it does not know can ever match an admin by accident. That rule
    only ever narrows: a person who could write before still can, by the same id.

    THE RULE ITSELF LIVES IN `policy.authz` NOW (C-26) — this is its PRODUCT scope, deliberately
    separate from the factory floor's, because the client who may approve a requirement and the
    operator who may skip a job are different trusts and always were. What moved is the answering,
    not the difference.

    `via` IS PROVENANCE, NOT PERMISSION — `authz.may` compares the id against the allowlist and
    never reads the channel. It is a parameter because it was once hardcoded to one vendor's name,
    and once the role gained a second transport (#98) that constant became a false statement
    inside the one record that says who authorised a change to a client's requirements. `api` when
    a caller does not say: the core's own name for a caller of its interface."""
    from openfactory.identity.base import Subject
    from openfactory.policy import authz
    from openfactory.product.speaker import is_guest

    if not user_id or is_guest(user_id):
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
    _WRITES = frozenset({"create_ticket", "comment", "close_ticket", "update_body", "update_title",
                         "add_label",
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

        # `*args, **kwargs` HIDES WHAT THE ROW TAKES, and `tracker.base.says_delivered` reads a
        # row's `close_ticket` to know whether it can be told a close was NOT a delivery (#203).
        # `inspect.signature` follows `__wrapped__`, so the question reaches the row through this.
        watched.__wrapped__ = attr
        return watched


def _bound_answer(module, answer: ProductAnswer) -> ProductAnswer:
    """The reading's confidence, set by what its evidence checks out against (#33 slice 7): the
    bundle mounted for the role and the corpus — never the model's own certainty. A "works like
    this" the bundle cannot back carries the caveat in the client's voice, because the person
    decides on it. A module-level function, and defensive about `module`: the bound is a
    measurement about the reply and must never cost it — a double standing in for the module in
    a test, or a bundle that will not read, leaves the answer as it was."""
    reading = getattr(answer, "reading", None)
    if not getattr(answer, "ok", False) or reading is None:
        return answer
    from openfactory.product.reading import BAIXA, bound
    from openfactory.product.voice import reading_caveat, stale_caveat
    try:
        # every source's bundle (#268); a double that only knows the one folder still bounds by it
        okf = getattr(module, "_okf_dirs", None) or getattr(module, "_okf_dir", None)
        bundle_dir = okf() if callable(okf) else None
        corpus = getattr(module.context(), "corpus", None)
        # AND THE TURN'S CHECK (#268 slice 3, ADR-0052 D20): a concept whose code moved since it
        # was published is stale, whatever the manifest says; a reading that stands on code it
        # opened, and cites no concept, is medium — both from what this turn mounted
        look = getattr(module, "sight", None)
        sight = look() if callable(look) else None
        broken = sight.broken_titles if sight is not None else ()
        code = _code_read(module, reading, sight)
        bounded = bound(reading, bundle_dir=bundle_dir, corpus=corpus, broken=broken,
                        code_read=len(code))
    except Exception:  # noqa: BLE001 — the bound is a measurement about the reply, never the reply
        log.warning("could not bound the reading", exc_info=True)
        return answer
    text = answer.text
    language = getattr(getattr(module, "project", None), "language", None)
    if getattr(answer, "is_misuse", False) and bounded.confidence == BAIXA:
        text = (text.rstrip() + "\n\n" + reading_caveat(language=language)).strip()
    # A STALE DESCRIPTION IS NAMED IN THE ANSWER, never used as current (D20): whatever the reply
    # made of it, the person reads that the description it rested on is out of date
    stale = [c for c, verdict in (bounded.verified.get("concepts") or {}).items()
             if verdict == "stale"]
    if stale:
        text = (text.rstrip() + "\n\n" + stale_caveat(stale, language=language)).strip()
    return answer.model_copy(update={"reading": bounded, "text": text})


def _code_read(module, reading, sight) -> list[tuple[str, str]]:
    """The code files a reading says it opened that lie in a source this turn mounted —
    `(repo, path)` — and nothing else (`sight.where_read`)."""
    if sight is None or not getattr(reading, "code", None):
        return []
    from openfactory.product.sight import where_read

    root = getattr(module, "_combined", None)
    return where_read(reading.code, root=Path(root) if root else None, mounts=sight.mounts)


#: The stream reader cuts a pulse's target at this many characters (`stream._target_of`). A path
#: that long may have been cut, and a cut path names another file or none, so it is not read as one.
_STREAM_TARGET_CAP = 200


def _opened_in_stream(harness: str, raw: str) -> list[str]:
    """The files a harness's own stream says the turn READ — by intent, on the harnesses whose
    stream is read (`stream.pulses_of`; `trajectory.intent_of`), `[]` on the others. What a harness
    reads through its shell is not seen here, nor a path the reader cut; the reply's evidence names
    those."""
    if not raw or not harness:
        return []
    from openfactory.adapters.agent.stream import TOOL, pulses_of
    from openfactory.observability.trajectory import READ, intent_of

    try:
        pulses = pulses_of(harness, raw) or []
    except Exception:  # noqa: BLE001 — a stream that will not read costs this list only
        log.info("could not read the %s stream for the files it opened", harness, exc_info=True)
        return []
    return [p.target for p in pulses if p.kind == TOOL and p.target
            and len(p.target) < _STREAM_TARGET_CAP and intent_of(p.name) == READ]


def _signal_gaps(module, answer) -> list[tuple[str, str]]:
    """Code this turn read that no concept covers, asked of the knowledge pipeline — the
    `no-concept` signal (ADR-0052 D22, #268 slice 3). Returns the requests that were NEW.

    WHAT THE TURN READ is what the reply's evidence says it opened and what the harness's own
    stream says it read, mapped to a source this turn mounted (`sight.where_read`) — nothing outside
    `sources:`. WHAT NO CONCEPT COVERS is the knowledge gate's own verdict against that source's
    bundle (`sight.uncovered`): a test or a config file its kind excuses, a file the inventory never
    saw and a source with no bundle at all are not signalled.

    THE ROLE NEVER WRITES THE BUNDLE. The request goes to the pipeline's inbox
    (`knowledge/requests.py`) — the repository, the path and a fixed sentence, never the question or
    who asked — deduplicated by the gap's own key, and the pipeline takes it at its next refresh.

    A module-level function, and defensive about `module`, for `_bound_answer`'s reason: a stand-in
    that carries no sight signals nothing. Never raises: a signal is a measurement about the
    answer, and it must never cost it."""
    if not getattr(answer, "ok", False):
        return []
    from datetime import UTC, datetime

    from openfactory.knowledge import requests as asked
    from openfactory.product import sight as seen

    try:
        sight = _the_sight(module)
        if sight is None:
            return []
        root = getattr(module, "_combined", None)
        reading = getattr(answer, "reading", None)
        said = list(getattr(reading, "code", None) or [])
        opened = _opened_in_stream(getattr(answer, "harness", "") or "",
                                   getattr(answer, "raw", "") or "")
        read = seen.where_read([*said, *opened], root=Path(root) if root else None,
                               mounts=sight.mounts)
        dark = seen.uncovered(read, sight)
        if not dark:
            return []
        project = getattr(module, "project", None)
        inbox = asked.inbox_for(project)
        at = datetime.now(UTC).isoformat()
        new = [(repo, path) for repo, path in dark
               if asked.request(inbox, repo=repo, path=path, at=at)]
        log.info("OPENFACTORY_KNOWLEDGE_GAP_SIGNALLED project=%s read=%d uncovered=%d new=%d %s",
                 getattr(project, "name", "?"), len(read), len(dark), len(new),
                 ", ".join(f"{r}:{p}" for r, p in dark)[:400])
        return new
    except Exception:  # noqa: BLE001 — a signal is a measurement, never the answer
        log.warning("could not signal what the turn read that no concept covers", exc_info=True)
        return []


def _not_the_requester(cfg, *, actor: str, requester: str, language=None) -> str:
    """The sentence refusing a second yes given by somebody other than the requester — or "" when
    the yes may proceed (ADR-0047 §4).

    THE REQUESTER OWNS THE SECOND YES. `may_act` says who may WRITE at all; this says whose
    promise it is. An admin who did not ask is let through only when the deployment's
    configuration says so (`product.accept_on_behalf`), and a requirement nobody is recorded as
    having asked for has nobody to defer to — where "nobody" is `corpus.requester_identity`'s
    reading of the field, by shape, and NOT a list of phrases. The first version of this gate
    kept such a list, five phrases long, and `brownfield.py` wrote a sixth: every `observed`
    requirement became one no actor could ever accept, and the only way out was switching §4 off
    for the whole product (#70, found in review)."""
    from openfactory.product.voice import only_the_requester_accepts

    who = requester_identity(requester)
    if not who:
        return ""
    if (actor or "").strip().strip("<@>") == who:
        return ""
    if getattr(cfg, "accept_on_behalf", False):
        return ""
    return only_the_requester_accepts(requester=who, language=language)


def awaiting_of(requirement) -> str:
    """Whose acceptance a card opened from this requirement awaits — "" once it is a promise.
    The requester's own name when the requirement recorded one, else the role's word for them —
    and a placeholder or a sentence in that field is not a name (`requester_identity`), or the
    card would read "awaiting unrecorded's acceptance"."""
    if getattr(requirement, "is_promise", False):
        return ""
    asked_by = getattr(requirement, "asked_by", "")
    return asked_by if requester_identity(asked_by) else "the requester"


class ProductModule:
    """One project's product module: the corpus it reasons over, and the actions it may take."""

    def __init__(self, project, *, token: str | None = None, context: ProductContext | None = None,
                 agent=None, tracker=None, board=None, via: str = "api") -> None:
        self.project = project
        #: WHERE the actor of every write below is speaking from. Provenance, never permission —
        #: `authz.may` compares the id against the allowlist and never reads this. It exists
        #: because it used to be one vendor's name as a constant inside `may_act`, and the moment
        #: the role gained a second transport (#98) that constant became a false statement in the
        #: one record that says who authorised a change to a client's requirements. Defaulted to
        #: `api`, the core's own name for a caller of its interface (#266 slice 6): the vendor it
        #: used to default to is an add-on, which says its own name.
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

    def _role(self, *, pending: str = "", intake: str = "") -> ProductRole:
        agent = self._agent
        if agent is None:
            from openfactory.adapters.agent import build_product

            agent = build_product(self.project)
        note = self._corpus_note()
        if note:
            # corpus health travels with EVERY operation, not just answer() — see _CorpusNoted
            agent = _CorpusNoted(agent, note)
        cfg = getattr(self.project, "product", None)
        # THE FACTS, AS FILES, BEFORE THE PROMPT DESCRIBES THE WORKSPACE (#33): written here so
        # `mounted()` below can report the door only when it is really on disk.
        self._facts_dir = self._write_facts()
        return ProductRole(agent, corpus=self.context().corpus,
                           project_name=getattr(self.project, "name", "") or "",
                           language=getattr(self.project, "language", "") or "",
                           pending_proposal=pending,
                           intake=intake,
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
                           mounted=self.mounted(),
                           # the situation now, from the model the pack above was written from
                           # (#267 slice 2) — None for anything but an answer to somebody
                           briefing=_the_briefing(self),
                           # every source of the product, the missing ones with why, and each
                           # one's checked module map; the documents the onboarding wrote (#268)
                           mounts=self.mounts(),
                           onboarding=self.onboarding(),
                           # the map checked against the code this turn mounted, what is stale and
                           # blind, and the capabilities (#268 slice 3)
                           sight=_the_sight(self),
                           # THE ROLE'S OWN SEARCH, `[[BUSCA: …]]` (#269 slice 2) — offered only to
                           # an answer whose facts pack is on disk, where its hits are written
                           search=(getattr(self, "_search_for_the_role", None)
                                   if _may_search(self) else None))

    def _search_for_the_role(self, queries: list[str], round_: int) -> str:
        """The role's `[[BUSCA: …]]` searches of one round (#269 slice 2): run with the turn's
        scope, written as `found/search-<round>.md` in the pack the role reads — through the
        pack's withholdings — and the note the next round's prompt carries."""
        from openfactory.product import facts
        from openfactory.product.index import retrieval
        from openfactory.product.model import Names, finish

        into = getattr(self, "_facts_dir", None)
        audience, conversation, own = _the_search_scope(self, getattr(self, "_combined", None))
        founds, text = retrieval.for_the_role(self.project, queries, round_=round_,
                                              audience=audience, conversation=conversation,
                                              own=own)
        model = vars(self).get("_product_model")
        names = Names(getattr(model, "people", ()) or (),
                      speaker=str(getattr(self, "_facts_for", "") or "") if own else "")
        name = f"{retrieval.FOUND_DIR}/search-{round_}.md"
        if not into or not facts.add_file(Path(into), name, finish(text, names)):
            return ("The search you asked for ran, and its hits could not be written as a file "
                    "for you — answer from what you have, and say what you could not look up.")
        counts = "; ".join(f"`{' '.join(q.split())[:80]}` — {len(f.hits)} hit(s)"
                           + (" (by exact words, metadata and date only)" if f.degraded else "")
                           for q, f in zip(queries, founds, strict=True))
        return (f"Round {round_}: the engine searched the product's memory for {counts}. The hits, "
                f"each with where it is, its date and how it was read, are in "
                f"`{Path(into).name}/{name}` — open it.")

    def _write_facts(self):
        """The board whole, the open loops and the decisions register, as files in the
        workspace root (`product/facts.py`, #33) — or None, honestly, when they could not be.

        ONE LOG LINE PER PASS WITH THE COUNTS. The manifest's gaps are the measurement #33 asks
        for — how often the role needs a fact nobody gathered — and a number that lives only in
        a file inside a worktree is a number nobody can add up."""
        from openfactory.product import facts

        self._workspace()
        root = getattr(self, "_combined", None)
        if not root:
            return None
        name = getattr(self.project, "name", "") or ""
        seen_here = functools.partial(_loops_seen_in, self.project,
                                      str(getattr(self, "_conversation", "") or ""))
        read_model = _the_read_model(self, root)
        # THE CHAIN WALKS THE MODEL (#268 slice 3): handed in only when there is one to hand in,
        # so a pass that answers nobody writes the pack it always wrote
        chain = _the_chain(self, read_model)
        # WHAT THE ENGINE FOUND IN THE PRODUCT'S MEMORY FOR THIS MESSAGE (#269 slice 2), written
        # with the rest of the pack and through the same withholdings
        found, found_gaps = _the_search_before_the_turn(self, root)
        # WHAT THE MESSAGE CARRIED (#336): each file's reading beside what the search found, and
        # through the same withholdings; an image is written as itself once the pack stands
        attached, images = _the_attachments(self)
        found = {**found, **attached}
        files, gaps = facts.gather(name, self._board_cards(), read=seen_here,
                                   **({"chain": chain} if chain else {}),
                                   **({"found": found} if found else {}), **read_model)
        into = facts.write_facts(Path(root), files=files,
                                 gaps=[*gaps, *found_gaps, *_the_view_s_gap(self)])
        for image, data in images if into else ():
            if not facts.add_image(into, image, data):
                self._attached_listed = [
                    {**line, "file": "", "said": "could not be put in front of you"}
                    if line.get("file") == image else line
                    for line in getattr(self, "_attached_listed", [])]
        log.info("OPENFACTORY_PRODUCT_FACTS project=%s files=%d gaps=%d written=%s",
                 name, len(files), len(gaps), "yes" if into else "no")
        return into

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
        `_mounted()` reports it, so the prompt stops claiming access that does not exist.

        A VIEW PER TURN (#266 slice 2, ADR-0051 D11). The composed root below is the CACHE, rebuilt
        in place; what the agent reads is a view of this module's own, made from it
        (`workspace.turn_view`) and removed by `release()` when the turn ends. With conversations
        in parallel, one turn recomposing the shared root reset what another turn's agent was
        reading — so no two turns share one, and the degraded shapes get their own copy too.

        EVERY SOURCE OF THE PRODUCT, NOT THE PROJECT'S ONE (#268, ADR-0052 D14, D16). This mounted
        `forge.repo` alone, so in a product of several repositories the role could read the other
        services' concepts and not open their code. Now every repository `sources:` declares is
        brought up — sparse, partial, side by side (`product/sources.py`) — and placed under
        `src/`; one that could not be is kept with why, for the prompt to name. A product of one
        source is the same shape with one source, on this same path."""

        from openfactory.adapters.sandbox.base import Workspace
        from openfactory.adapters.sandbox.registry import judging_worktree
        from openfactory.product.sources import NOT_CHECKED_OUT
        from openfactory.product.workspace import compose

        docs = self.context().docs_path
        branch = getattr(getattr(self.project, "product", None), "docs_branch", "main")
        if hasattr(self, "_combined"):
            return (judging_worktree(self.project, root=self._combined),
                    Workspace(path=self._combined, branch=branch, base_branch=branch))

        # where the turn views of this project live: beside the cache they are made from
        turns = os.path.join(os.path.dirname(str(docs)), f"{self.project.name}-turns")
        checkouts = self._source_checkouts(docs)
        self._own_source, self._left_out = checkouts.own, checkouts.left_out
        self._mounted_sources, self._missing_sources = {}, dict(checkouts.missing)
        if not checkouts.placed:
            self._combined, self._mounted_code = self._own_view(turns, docs=docs), None
            self._docs_at = "."
            _log_mount(self.project, self._combined, docs=self._combined, code=None,
                       missing=self._missing_sources)
            return (judging_worktree(self.project, root=self._combined),
                    Workspace(path=self._combined, branch=branch, base_branch=branch))

        # A STABLE path, rebuilt in place — not a temp directory per message. The module is
        # constructed fresh for every message (deliberately: one conversation must not carry
        # another's state), so `mkdtemp` here meant one directory nobody ever removed, per message.
        # `compose` is idempotent at a fixed root, so the ordinary turn — the cache has not moved —
        # costs a `rev-parse` and no checkout at all.
        # Beside the checkouts it is built from, derived from the cache's own location, so it
        # follows the cache wherever it lives instead of assuming a path a deploy can move.
        root = os.path.join(os.path.dirname(str(docs)), f"{self.project.name}-view")
        try:
            # ONE COMPOSE AT A TIME PER ROOT, and the turn's view is taken under the same lock: a
            # view linked while another turn's compose was replacing a worktree would hold half of
            # each. The lock covers a `rev-parse` and a link per file — never a model call, and
            # never a fetch: every source was brought up before it.
            with _view_lock(root):
                ws = compose(docs_checkout=docs, sources=checkouts.placed, root=root)
                mine = self._own_view(turns, docs=ws.docs, sources=dict(ws.sources),
                                      shared=str(ws.path))
        except Exception as exc:  # noqa: BLE001 — a workspace problem degrades, never raises
            # Documentation-only rather than nothing: a question about requirements is still
            # answerable, and `mounted()` will tell the prompt the code is not there.
            log.warning("product: could not compose the workspace for %s (%s) — answering from "
                        "the documentation alone", getattr(self.project, "name", "?"), exc)
            self._combined, self._mounted_code = self._own_view(turns, docs=docs), None
            self._docs_at = "."
            self._missing_sources.update({r: NOT_CHECKED_OUT for r in checkouts.placed})
            _log_mount(self.project, self._combined, docs=self._combined, code=None,
                       missing=self._missing_sources)
            return (judging_worktree(self.project, root=self._combined),
                    Workspace(path=self._combined, branch=branch, base_branch=branch))
        for repo in checkouts.placed:
            if repo not in ws.sources:
                # THE HONEST HALF of the same degrade: `compose` records why in `missing` rather
                # than dropping the repo silently, and that reason is worth a log line — a role told
                # it has no code when the checkout was fine is the exact confusion this board item
                # is about. The prompt gets the plain sentence; git's words stay in the log.
                log.warning("product: the source %s of %s was not placed in the workspace (%s) — "
                            "the role will be told it cannot open it", repo,
                            getattr(self.project, "name", "?"),
                            ws.missing.get(repo, "no reason given"))
                self._missing_sources[repo] = NOT_CHECKED_OUT
        self._combined, self._docs_at = mine, "docs"
        own = getattr(self, "_turn_view", None) == mine
        self._mounted_sources = {repo: (os.path.join(mine, "src", placed.name) if own
                                        else str(placed))
                                 for repo, placed in ws.sources.items()}
        self._mounted_code = self._mounted_sources.get(checkouts.own)
        _log_mount(self.project, self._combined, docs=os.path.join(mine, "docs"),
                   code=self._mounted_code, mounted=tuple(self._mounted_sources),
                   missing=self._missing_sources)
        return (judging_worktree(self.project, root=self._combined),
                Workspace(path=self._combined, branch=branch, base_branch=branch))

    def _source_checkouts(self, docs):
        """Every source the product declares in the documentation checkout at `docs`, brought up
        for this turn side by side — and nothing it does not declare (#268)."""
        from openfactory.product.sources import check_out, declared

        found = declared(docs)
        if found.sources:
            # resolved once, here, rather than raced for by one thread per source
            _ = self.token
        return check_out(self._source_repo(), found,
                         lambda repo, spelling, own: self._source_checkout(repo, spelling,
                                                                           own=own))

    def _own_view(self, turns: str, *, docs, sources=None, shared: str | None = None) -> str:
        """This module's own view, made under `turns` — or, when one cannot be made, the SHARED
        directory it would have been made from, said out loud.

        Falling back to the shared directory is the degrade the workspace already had (answering
        from something rather than nothing); the marker is what keeps it from passing for a turn
        with a view of its own.

        MADE TO THE TURN'S AUDIENCE (#269 slice 3, ADR-0053 D10). The role reads this directory
        with its harness's tools, so it is a path into the prompt like the pack and the searches:
        a document this turn may not be shown, and a private conversation's distillate that is not
        this one's, are never copied into it (`_withheld_from_view`). And WHEN SOMETHING IS
        WITHHELD THERE IS NO SHARED FALLBACK: the shared directory holds every document, so a view
        that could not be made is an empty one — an answer from the prompt alone, said in the log —
        never the whole repository."""
        from openfactory.product.workspace import turn_view

        withheld = self._withheld_from_view(docs)
        if withheld is None:
            return self._an_empty_view(turns, "its documents could not be judged", 0)
        try:
            made = turn_view(turns, docs=docs, sources=sources, withheld=withheld)
        except Exception as exc:  # noqa: BLE001 — a view problem degrades, never raises
            if withheld:
                log.warning("the view of %s could not be made (%s)",
                            getattr(self.project, "name", "?"), exc)
                return self._an_empty_view(turns, "the view could not be made", len(withheld))
            fallback = shared if shared is not None else str(docs)
            log.warning("OPENFACTORY_PRODUCT_SHARED_VIEW project=%s — could not make this turn a "
                        "view of its own (%s); it reads the shared %s, which another turn may "
                        "rebuild under it", getattr(self.project, "name", "?"), exc, fallback)
            return fallback
        self._turn_view = str(made)
        return str(made)

    def _withheld_from_view(self, docs) -> list[str] | None:
        """The documentation's files this turn's view may not hold — its audience's reading
        (`documents/record.py::withheld`): the client's unless `answer` was told the turn answers
        one of the product's own people in private, and the conversation it answers in, for the
        distillates. The curated truth — the requirements and the glossary, which every prompt
        carries — is every reader's.

        None when the repository could not be walked: nothing is decided about a file that was
        never looked at, so the view is made empty (`_own_view`)."""
        from openfactory.product.documents.record import withheld
        from openfactory.product.index.sync import is_requirement_file
        from openfactory.product.loader import DOMAIN_DIRNAME

        audience = str(getattr(self, "_documents_audience", "") or CLIENT)
        conversation = str(getattr(self, "_conversation", "") or "")
        try:
            requirements_dir = self.context().requirements_dir
        except Exception as exc:  # noqa: BLE001 — the default folder, the corpus's own default
            log.info("the requirements folder of %s could not be read (%s) — the view keeps "
                     "`requirements/` as the curated truth", getattr(self.project, "name", "?"),
                     exc)
            requirements_dir = "requirements"

        def curated(path: str) -> bool:
            return (is_requirement_file(path, requirements_dir)
                    or path.startswith(f"{DOMAIN_DIRNAME}/"))

        try:
            held = withheld(Path(docs), audience, own=conversation, curated=curated)
        except Exception as exc:  # noqa: BLE001 — what could not be judged is not handed over
            log.error("OPENFACTORY_PRODUCT_VIEW_UNJUDGED project=%s (%s) — the documents of this "
                      "turn's view could not be judged, so none are handed over",
                      getattr(self.project, "name", "?"), exc)
            self._view_withheld = -1
            return None
        self._view_withheld = len(held)
        if held:
            log.info("OPENFACTORY_PRODUCT_VIEW_WITHHELD project=%s audience=%s withheld=%d — "
                     "documents this turn may not be shown are not in its view",
                     getattr(self.project, "name", "?"), audience, len(held))
        return held

    def _an_empty_view(self, turns: str, why: str, withheld: int) -> str:
        """The degrade of a view that had to leave documents out and could not be made: an empty
        view of the turn's own, removed with the turn — never the shared one, which holds them all.
        When not even that can be made, a path that holds nothing: the harness then cannot stand
        in it and the answer fails, which is a failure said out loud and never a disclosure."""
        from openfactory.product.workspace import empty_turn_view

        log.error("OPENFACTORY_PRODUCT_EMPTY_VIEW project=%s — could not make this turn a view "
                  "of its own (%s), and %d document(s) may not be shown to it, so it reads none "
                  "rather than the shared directory", getattr(self.project, "name", "?"), why,
                  withheld)
        try:
            made = empty_turn_view(turns)
        except OSError as exc:
            log.error("OPENFACTORY_PRODUCT_NO_VIEW project=%s (%s) — not even an empty view could "
                      "be made", getattr(self.project, "name", "?"), exc)
            return os.path.join(turns, "no-view")
        self._turn_view = str(made)
        return str(made)

    def release(self) -> None:
        """The view this module made for its turn, removed — and forgotten, so a later read makes
        a fresh one rather than reading a directory that is gone.

        ONLY WHAT `_workspace` MADE ITSELF. A view somebody handed this module (a test's fixture, a
        caller that set `_combined`) is not its to delete, and is left exactly as it was."""
        from openfactory.product.workspace import release_turn_view

        made = getattr(self, "_turn_view", None)
        if not made:
            return
        for attr in ("_turn_view", "_combined", "_mounted_code", "_facts_dir", "_docs_at",
                     "_mounted_sources", "_missing_sources", "_mount_list", "_own_source",
                     "_left_out", "_sight"):
            self.__dict__.pop(attr, None)
        release_turn_view(made)

    def _source_checkout(self, repo: str, spelling: str = "", *, own: bool = False):
        """One SOURCE of the product, brought up for a turn: a sparse, partial checkout cached
        between messages (`SparseRepoCache`, #268) — a `sources.Checkout` holding where it is, or
        why it is not. Never raises: it runs on a thread per source, and one source's trouble is a
        sentence in the prompt, never the turn.

        `own` is the registry project's own repository: addressed by the registry's spelling and
        read on the registry's declared base. Every other source is addressed as `sources:` spells
        it and read on its own default branch, since the registry declares no branch for it."""
        from openfactory.product.sources import NOT_ADDRESSABLE, NOT_CHECKED_OUT, Checkout, why_not

        try:
            from openfactory.loader import load_manifest_base_branch
            from openfactory.runtime.repo_cache import SparseRepoCache

            try:
                url = self._clone_url((self._source_repo() if own else "") or spelling or repo)
            except Exception as exc:  # noqa: BLE001 — a forge this deployment cannot address
                log.warning("product: the forge of %s cannot address the source %s (%s)",
                            getattr(self.project, "name", "?"), repo, type(exc).__name__)
                return Checkout(why=NOT_ADDRESSABLE)
            cache = SparseRepoCache()
            # THE REGISTRY'S DECLARED BASE, OR THE REPOSITORY'S OWN (#162). `"main"` here was not a
            # harmless default: `git clone --branch main` against a `master` or `develop`
            # repository names nothing and fails, and this function's failure is silent by
            # contract — the role is told it cannot open the code and answers documentation-only
            # for ever. `""` lets the clone land where the repository points.
            path = cache.sync(self._source_key(repo), url,
                              load_manifest_base_branch(self.project, default="") if own else "")
            if path is None:
                return Checkout(why=why_not(cache.failure))
            if not cache.partial:
                log.info("product: the source %s of %s was cloned WHOLE — its forge does not "
                         "serve partial clones", repo, getattr(self.project, "name", "?"))
            return Checkout(path=path, left_out=tuple(cache.left_out))
        except Exception as exc:  # noqa: BLE001 — no code is survivable; a silent promise is not
            log.warning("product: could not check out the source %s of %s (%s) — the role will be "
                        "told it cannot open it, instead of guessing about it", repo,
                        getattr(self.project, "name", "?"), type(exc).__name__)
            return Checkout(why=NOT_CHECKED_OUT)

    def _source_key(self, repo: str) -> str:
        """The cache key of one source: this project's, and the source's coordinate flattened — a
        name `RepoCache`'s other keys (`<project>-source`, `<project>--docs`) cannot take, whatever
        the source is called."""
        return f"{self.project.name}--source--{repo.strip('/').replace('/', '--')}"

    def mounts(self):
        """Every source the product declares, as this turn's view holds it — where each is, why each
        missing one is not, what the sparse checkout left out, and its module map CHECKED against
        the code mounted for it (#268, ADR-0052 D16, D18). None for a view somebody handed this
        module: nothing is known about its sources, and the prompt says only what `mounted` does.

        Once per module, which is once per turn: the map's check reads every file it was drawn
        from, and the role is built more than once inside one turn."""
        from openfactory.product.sources import Mount, module_map

        self._workspace()
        if "_mount_list" in vars(self):
            return self._mount_list
        root = getattr(self, "_combined", None)
        where = getattr(self, "_mounted_sources", None)
        if not root or where is None:
            return None
        docs = _docs_root(self, default="docs")
        own = getattr(self, "_own_source", "")
        left = getattr(self, "_left_out", {}) or {}
        out = []
        for repo, path in where.items():
            mapped, why = module_map(docs, repo, Path(path))
            out.append(Mount(repo=repo, path=os.path.relpath(path, root), own=repo == own,
                             left_out=tuple(left.get(repo, ())),
                             map=os.path.relpath(mapped, root) if mapped else "", map_why=why))
        out += [Mount(repo=repo, why=why, own=repo == own)
                for repo, why in (getattr(self, "_missing_sources", {}) or {}).items()]
        out.sort(key=lambda m: not m.own)       # stable: the project's own first, then as declared
        self._mount_list = out
        return out

    def onboarding(self) -> list[tuple[str, str]]:
        """The onboarding's documents in this product's context repository, as `(path, what)`
        relative to the root the role stands in — only those on disk (#268, ADR-0052 D18)."""
        from openfactory.onboarding.context import written_documents

        self._workspace()
        root = getattr(self, "_combined", None)
        docs = _docs_root(self, default="docs")
        if not root or docs is None:
            return []
        return [(os.path.relpath(docs / rel, root) + ("/" if rel.endswith("/") else ""), what)
                for rel, what in written_documents(docs)]

    def sight(self):
        """The turn's reading of the map (#268 slice 3, `product/sight.py`): every concept of every
        source's bundle checked against the code mounted for that source, the flows across them
        checked source by source, what is stale, what is blind, and the capabilities with every
        link that no longer holds. An empty one for a view somebody handed this module.

        Once per module, which is once per turn: the check reads every file a concept cites, and
        the role is built more than once inside one. One log line, with the counts."""
        from openfactory.product import sight as seen

        self._workspace()
        if "_sight" in vars(self):
            return self._sight
        root = getattr(self, "_combined", None)
        try:
            made = seen.look(docs_root=_docs_root(self, default="docs"),
                             root=Path(root) if root else None, mounts=self.mounts(),
                             docs_rel=self.mounted().get("docs") or "docs")
        except Exception as exc:  # noqa: BLE001 — the sight is a reading, never the answer
            log.warning("[%s] the map could not be checked against the code this turn (%s)",
                        getattr(self.project, "name", "?"), exc, exc_info=True)
            made = seen.Sight()
        log.info("OPENFACTORY_PRODUCT_SIGHT project=%s bundles=%d mounted=%d stale=%d blind=%d "
                 "left_out=%d dangling=%d", getattr(self.project, "name", "?"),
                 sum(1 for b in made.bundles.values() if b is not None), len(made.mounts),
                 len(made.stale), len(made.blind), made.left_out, len(made.dangling))
        self._sight = made
        return made

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
        facts = getattr(self, "_facts_dir", None)
        # WHERE THE DOCUMENTATION IS, AS THE VIEW WAS BUILT: under `docs/` whenever any source was
        # placed beside it — the project's own or another of the product's (#268) — and at the root
        # of a documentation-only view
        docs = _docs_root(self, default="docs" if code else ".")
        if not root or docs is None:
            return _with_facts({"docs": ".", "code": ""}, facts, root)
        out = {"docs": os.path.relpath(str(docs), root),
               "code": os.path.relpath(str(code), str(root)) if code else ""}
        # THE KNOWLEDGE BUNDLE, AND ONLY WHEN IT IS REALLY THERE — the rule `code` above already
        # follows, for a second reason that is specific to this key: the role composes its prompt
        # in THIS process, where every name in this dict is relative to a workspace root the
        # process is not standing in. A role that asked `Path("docs/.okf")` whether it exists
        # would be answered by the worker's own cwd — False on every project that has one, and
        # the section would be dead on all of them while looking wired. The existence question is
        # answerable here, where the absolute path is, and nowhere the prompt is built.
        door = docs / OKF_DIRNAME / OKF_INDEX_FILE
        if door.is_file():
            out["okf"] = os.path.relpath(str(door.parent), root)
        # THE SYSTEM LAYER (#268 slice 2), by the same rule: its door, only when it is on disk —
        # wherever the documentation is, a documentation-only view included.
        from openfactory.knowledge.system.render import INDEX_FILE, SYSTEM_DIRNAME

        system = docs / OKF_DIRNAME / SYSTEM_DIRNAME / INDEX_FILE
        if system.is_file():
            out["system"] = os.path.relpath(str(system.parent), root)
        # THE FLOWS ACROSS SERVICES (#268 slice 3), by the same rule
        from openfactory.knowledge.flows import FLOWS_DIRNAME

        flows = docs / OKF_DIRNAME / FLOWS_DIRNAME / OKF_INDEX_FILE
        if flows.is_file():
            out["flows"] = os.path.relpath(str(flows.parent), root)
        return _with_facts(out, facts, root)

    # ---- reading ----------------------------------------------------------------------------

    def answering_in(self, conversation: str) -> None:
        """The KEY of the conversation this module's turn answers in (#267 slice 3) — so the
        agenda the role reads is the one that conversation may see (`_loops_seen_in`). Told by
        the engine before the answer; a module is built per turn, so it holds one conversation's.
        Never told, it is nobody's: the room's items alone."""
        self._conversation = str(conversation or "")

    def answer(self, question: str, *, context: str = "", conversation: str = "",
               pending: str = "", intake: str = "", speaker=None,
               private: bool = False, now: str = "", attachments=()) -> ProductAnswer:
        """Anyone in the channel may ask. Returns an unavailable-with-reason answer rather than
        raising, because this is called straight from a chat listener.

        `speaker` is who asked, as a person of this product with their role in it
        (`product/speaker.py`, #266 slice 4) — handed to the role's prompt, so it knows who it is
        answering and in which role. None for a question nobody in a conversation asked (the
        factory's own, `engine.consult`).

        `private` is whether the conversation is the role and that person alone (`door.is_direct`)
        — with an engineer, the one place the briefing quotes the tech-lead's diagnosis as it
        wrote it (#267 slice 2, ADR-0052 D10). False, the room's reading, when a caller does not
        say.

        `now` is when the turn is (`product/clock.py::now_block`): today's date and how long ago
        the conversation's previous message was — "" from a caller that does not say.

        `attachments` are the files the message carries (#336): read into the facts pack before
        the role is asked (`_the_attachments`), and listed for it beside the question."""
        ctx = self.context()
        if not ctx.available:
            return ProductAnswer(ok=False, error=ctx.reason)
        # THE DOCUMENTS THEY MAY BE SHOWN, by who asks and where (#269): an internal one only to an
        # engineer or a product admin in private — a name is content. DECIDED BEFORE THE VIEW IS
        # MADE (#269 slice 3): the view is a path into the prompt too, and it is made to this
        # audience (`_own_view`); a view an earlier stage of the turn made is the client's reading
        from openfactory.product.documents.record import turn_audience

        self._documents_audience = turn_audience(speaker, private=private)
        sandbox, ws = self._workspace()
        # THE PRODUCT AS THE PANEL SHOWS IT, for a question somebody asked (#267): the pack this
        # answer's role reads carries the read model, and names only the person asking.
        self._facts_for = str(getattr(speaker, "id", "") or "")
        # AND THE BRIEFING IN THEIR REGISTER: the raw diagnosis only to an engineer in private
        from openfactory.product.briefing import raw_for

        self._raw_diagnosis = raw_for(speaker, private=private)
        # AND WHAT THE ENGINE SEARCHES THE PRODUCT'S MEMORY FOR BEFORE THE TURN (#269 slice 2): the
        # message, and the lines before it when it is too short to carry its subject
        self._question = question
        self._said_before = conversation
        self._attachments = list(attachments or ())
        # the corpus note is NOT defaulted into `context` here any more: _role() carries it on
        # every prompt (the one seam), and doubling it up would say the same warning twice
        answer = self._role(pending=pending, **({"intake": intake} if intake else {})).answer(
            sandbox=sandbox, workspace=ws, question=question,
            context=context, conversation=conversation,
            **({"speaker": speaker} if speaker is not None else {}),
            **({"now": now} if now else {}),
            **({"attached": self._attached_listed}
               if getattr(self, "_attached_listed", None) else {}),
            asked=self.already_asked(question))
        answer = _bound_answer(self, answer)
        _signal_gaps(self, answer)
        return answer

    def _okf_dir(self) -> Path | None:
        """The bundle this role's reading is BOUND against, as an absolute path — the one folder
        per source repository (D-2, `.okf/repos/<owner--name>/`) when the context repository holds
        it; the root only when a bundle actually sits there; None when neither does.

        THE ROOT DOOR IS A LIST, NOT A BUNDLE. `_front_door` writes `.okf/index.md` at the root to
        link the per-source folders, and since D-2 no concept lives beside it — so a bound that
        read the root found `concepts/` empty and graded every citation `baixa`, on every project,
        while the prompt told the role to open that same door and follow its links. The third
        reading (#59) could therefore never reach `alta` against a bundle the platform itself had
        published. Found by review, 2026-09-06, while designing the plan that would have trusted
        that grade. `mounted()` keeps pointing the ROLE at the front door — it reads and follows
        links; the bound reads files, and needs the folder they are in."""
        from openfactory.knowledge.okf import OKF_DIRNAME, OKF_INDEX_FILE
        root = getattr(self, "_combined", None)
        if not root:
            return None
        docs = _docs_root(self, default="docs")
        try:
            from openfactory.adapters.forge.registry import repo_of
            from openfactory.knowledge.pipeline import okf_subpath

            source = docs / okf_subpath(repo_of(self.project))
        except Exception:  # noqa: BLE001 — a project shape with no repo has no per-source folder
            log.debug("no per-source bundle path for this project", exc_info=True)
            source = None
        if source is not None and (source / OKF_INDEX_FILE).is_file():
            return source
        door = docs / OKF_DIRNAME
        # a bundle written at the root — one written before D-2, or one a test planted — is read
        # as before; a bare front door with nothing beside it is reported as the door it is.
        # THOSE TWO ARE THE ONLY WAYS HERE (a question raised in the review of #71): the
        # project's own repository is always among the product's `sources` —
        # `config.resolve_product_link` step 4 refuses the link otherwise — so a backfill
        # since #76 has written the per-source folder above for it, however many sources the
        # product declares.
        return door if (door / OKF_INDEX_FILE).is_file() else None

    def _okf_dirs(self) -> list[Path]:
        """EVERY bundle this role's reading is bound against: the project's own, as `_okf_dir`
        finds it, and then the folder of every other source the product declares (#268, ADR-0052
        D20).

        ONE SOURCE'S BUNDLE BOUNDED A PRODUCT'S ANSWER. A reading that cited the payments service's
        concept, in a product whose registry project is the web front end, was graded "not in the
        bundle" — `baixa`, and the caveat said to the client — about a concept the platform itself
        had published one folder along. The declaration is read from the view's own copy of the
        context repository, so the bound reads exactly what the role could open."""
        from openfactory.knowledge.okf import OKF_INDEX_FILE
        from openfactory.product.sources import bundle_home, declared

        dirs: list[Path] = []
        own = self._okf_dir()
        if own is not None:
            dirs.append(own)
        docs = _docs_root(self, default="docs")
        if docs is None:
            return dirs
        for repo in declared(docs).repos:
            home = bundle_home(docs, repo)
            if home is not None and (home / OKF_INDEX_FILE).is_file() and home not in dirs:
                dirs.append(home)
        # AND THE FLOWS ACROSS THEM (#268 slice 3): a flow's concept is cited like any other, and
        # a bound that could not find it would grade the answer that spans services the lowest
        from openfactory.knowledge.flows import FLOWS_DIRNAME
        from openfactory.knowledge.okf import OKF_DIRNAME

        flows = docs / OKF_DIRNAME / FLOWS_DIRNAME
        if (flows / OKF_INDEX_FILE).is_file():
            dirs.append(flows)
        return dirs

    def already_asked(self, text: str) -> str:
        """Was this asked before — by whom, and where it lives — as a prompt section, or "".

        FROM THE BOARD, THE CORPUS AND THE OPEN DECISIONS, NEVER THE TRANSCRIPT (#33): a repeat
        must be caught across people and channels, and the transcript knows one conversation.
        The three reads are the ones this module already makes for the prompt; an unreadable
        ledger costs the decisions half and nothing else, because a lead the role could have had
        is cheaper to lose than the answer.

        AND THE WHOLE MEMORY (#269 slice 3, ADR-0053 D7): what the product's index finds for it —
        a card closed years ago, a dropped or superseded requirement, a document, a distilled
        conversation (`_done_before`) — outside the semaphore, in this turn's scope. ONCE PER TEXT
        PER MODULE: the answer and the draft of the same message read the same section."""
        from openfactory.product import asked

        said = vars(self).get("_already_asked") or {}
        if text in said:
            return said[text]
        loops: list = []
        try:
            from openfactory.memory import store as loop_store

            loops = loop_store.read(self.project.name)
        except Exception:  # noqa: BLE001 — a lead lost, never an answer
            log.warning("could not read the ledger to check what was already asked",
                        exc_info=True)
        matches = asked.already_asked(text, cards=self._board_cards(),
                                      corpus=self.context().corpus, loops=loops,
                                      found=_done_before(self, text))
        # NOBODY NAMED (ADR-0051 D9): the section informs the answer, and the model is never
        # handed the name of whoever asked before — it could repeat it to someone else
        section = asked.render(matches, name_people=False)
        self.__dict__.setdefault("_already_asked", {})[text] = section
        return section

    def settle_acceptance(self, text: str, *,
                          conversation: str | None = None) -> tuple[str, object, bool] | None:
        """A reply that answers "did it work?" — closes the loop with the CLIENT's verdict.

        Returns `(verdict, loop)` when one was settled, else None (the message was not an answer,
        and belongs to the normal conversation). Never closes on silence and never on a guess:
        `acceptance_verdict` returns "" for anything ambiguous, and this returns None for it.

        When several deliveries are awaiting an answer, a REF NAMED IN THE TEXT settles that one —
        never a guess. Failing that, the NEWEST is settled and the caller names it in the reply, so
        a wrong guess is at least visible and correctable.

        A RELEASE LOOP COMES BACK OPEN, whatever the verdict (#273): this reads what was said and
        cannot know who said it, and a release's verdict counts only from somebody who may act on
        it. The release gate closes it (`engine._maybe_release`).

        ONLY WHAT WAS ASKED WHERE THE REPLY IS WRITTEN (#267 slice 3): `conversation` is the
        conversation the reply was written in, and an acceptance asked in somebody's private
        conversation is not one it may answer (`_acceptances_here`). A caller that names none
        reads every acceptance, as before.
        """
        from openfactory.memory import store as loop_store
        from openfactory.memory.ledger import ACCEPTANCE, close_by_observation
        from openfactory.product.followup import acceptance_verdict

        verdict = acceptance_verdict(text)
        if not verdict:
            # AMBIGUOUS IS NOT "NO ANSWER". "ok", "beleza", "conferi", "testei" all used to close a
            # delivery as accepted; they now reach here, and a model decides whether the person
            # actually said it works (ADR-0029). No open acceptance → no call, so this costs nothing
            # on an ordinary message.
            verdict = (self._judge_acceptance(text, conversation=conversation)
                       if conversation is not None else self._judge_acceptance(text))
            if not verdict:
                return None
        try:
            ledger = loop_store.read(self.project.name)
        except Exception:  # noqa: BLE001 — an unreadable ledger must not eat the message
            log.warning("could not read the ledger to settle an acceptance", exc_info=True)
            return None
        open_acc = _acceptances_here(self.project, ledger, conversation)
        if not open_acc:
            return None
        # A NAMED RELEASE WINS OVER "NEWEST" (found verifying #24 item 2, 2026-08-04): the ambiguous
        # branch used to tell the client "diga o número" while nothing anywhere read one back — the
        # loop was already closed as the newest guess before the client could even answer. Resolved
        # here, BEFORE anything closes, so a correct reply never gets overruled by a guess.
        named = _named_release(text, open_acc)
        loop = named or max(open_acc, key=lambda x: x.ts)
        ambiguous = named is None and len(open_acc) > 1

        # A RELEASE LOOP IS NEVER CLOSED HERE, and two defects taught it. The first was an
        # AMBIGUOUS "funcionou": the guess was recorded as `worked` first and the "which one?"
        # question went out second — so the client's later, correct answer found its loop already
        # closed, and the ledger said a release was accepted that nobody had confirmed. The second
        # was a REFUSED one (#273): a "funcionou" from somebody off the admin list closed the loop
        # as `worked` here, before the release gate asked who was speaking. The gate refused them
        # and released nothing, and the question an admin should still have been asked was gone,
        # with the ledger saying the release was accepted. Whether a release's verdict counts
        # depends on who gave it, which this method cannot see; the gate can, so the gate closes
        # the loop — on a "não funcionou", and on a "funcionou" once `may_act` has passed.
        #
        # An ordinary delivery keeps the close-newest-and-name-it behaviour: a wrong guess there
        # costs one visible correction, and nothing it closes spends anything.
        from openfactory.product.followup import is_release

        if is_release(loop):
            return verdict, loop, ambiguous

        rows = close_by_observation(ledger, {(ACCEPTANCE, loop.subject, loop.about): verdict})
        if rows:
            loop_store.write(self.project.name, rows)
        return verdict, loop, ambiguous

    def record_decisions(self, labels: list[str], *, channel: str = "", conversation: str = "",
                         person: str = "") -> int:
        """Open one loop per decision she just asked for. Returns how many were new.

        Deduplicated by label: re-asking the same thing in a later message must not stack a second
        reminder — the person would be chased twice about one decision and read it as a machine
        that is not listening.

        ASKED OF A PERSON, IN A CONVERSATION (#266 slice 4, ADR-0051 D11). The decisions are the
        ones she asked in her answer to `person`, in `conversation`, and the loop records both —
        as digests (`speaker.sealed`): the ledger is read into every conversation's prompt (the
        decisions register, "possibly already asked"), and what it needs is to compare, never to
        name. Only that person, there, closes it (`close_decisions_answered`). The same label
        asked of somebody else is their decision, with a loop of its own. A caller that names
        nobody opens loops the old way, which any message in their room closes."""
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
        scope = _asked_of(person, conversation or channel)
        already = {x.subject for x in waiting(ledger, owner=OWNER)
                   if x.kind == DECISION and (not scope or _scope_of(x) == scope)}
        from datetime import UTC, datetime

        ts = datetime.now(UTC).isoformat()
        fresh = [open_loop(DECISION, _decision_key(lab), owner=OWNER, ts=ts, about=channel,
                           context={"asked": lab[:400], **scope})
                 for lab in labels if _decision_key(lab) not in already]
        if fresh:
            loop_store.write(self.project.name, fresh)
        return len(fresh)

    def close_decisions_answered(self, *, channel: str = "", conversation: str = "",
                                 person: str = "") -> int:
        """A person replied in this conversation — that IS the answer to what she asked them.

        The observation here is the human speaking, which is the same standard `acceptance_verdict`
        uses (ADR-0021: closed by observation, never self-report). Partial answers are safe: she
        has the conversation in memory now, so if something is still undecided her next reply
        re-asks it and a new loop opens. The alternative — keeping them open — chases a person
        about things they just discussed, which is how a channel gets muted.

        ONLY WHAT WAS ASKED OF THIS PERSON, HERE (#266 slice 4, ADR-0051 D11). This closed every
        open decision of the project on any message from anyone, so a decision asked of one person
        in one conversation was closed as `answered` by somebody else's "bom dia" in another, and
        nobody was ever chased about it: the observation has to be the right person's. `person`
        speaking in `conversation` (or at `channel`, the room it lives in) closes the loops opened
        for them there. A loop opened before this, which records nobody, closes as it always did
        — on a message in its own room. A caller that names nobody closes the old way, too.
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
        if person or conversation:
            live = [x for x in live if _answered_by(x, person=person,
                                                    where=(conversation, channel),
                                                    room=channel)]
        if not live:
            return 0
        # ONLY THESE LOOPS ARE HANDED TO THE CLOSE, never the ledger whole: two people asked the
        # same decision in one room hold loops that share `(kind, subject, about)`, and a close
        # keyed by that triple over the whole ledger would answer both
        rows = close_by_observation(
            live, {(DECISION, x.subject, x.about): "answered" for x in live})
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

    def _judge_acceptance(self, text: str, *, conversation: str | None = None) -> str:
        """`worked` | `did-not-work` | "" for a reply the lexical gate could not classify.

        Reads the ledger FIRST: with nothing awaiting acceptance there is nothing to judge, so an
        ordinary message never pays for a model call — and with nothing awaiting it HERE
        (`_acceptances_here`), neither does a message in another conversation."""
        from openfactory.memory import store as loop_store

        try:
            open_acc = _acceptances_here(self.project, loop_store.read(self.project.name),
                                         conversation)
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
        role = self._role()
        # THE DUPLICATE CHECK BEFORE ANYTHING IS STAGED READS THE WHOLE MEMORY (#269 slice 3,
        # ADR-0053 D7): what the draft's conflicts are checked against is what the answer was
        # shown — a request dropped years ago is a `duplicates` conflict the person reads before
        # the yes. Handed only to a role whose `draft` takes it, like every keyword grown here.
        section = self.already_asked(request) if _takes(role.draft, "asked") else ""
        return role.draft(sandbox=sandbox, workspace=ws, request=request, asked_by=asked_by,
                          **({"asked": section} if section else {}))

    # ---- the semaphore on what becomes work ---------------------------------------------------

    def _checked_write(self, *, act: str, kind: str, text: str, seen: int | None, write,
                       saved=None, judge=None, against=None, found) -> WriteResult:
        """One write of the product's record, through the product's semaphore (ADR-0051 D7).

        THE ONE DOOR every writer below goes through, for the reason `_tell_the_factory` gives for
        itself: eight writers wiring the lock each would become seven, and the one nobody wires
        mints a duplicate number. `write` runs inside the semaphore — mint, commit, push, file —
        and never a model; `judge` runs outside it. `found(item)` is this writer's own answer when
        what it was asked to write was saved moments ago in another conversation; `seen` is the
        sequence the staged proposal's check saw (None: a caller that ran no check — its check is
        now).

        A semaphore that could not be had in time, and a sequence that kept moving past every
        round, are both said to the person in a sentence, and neither writes anything."""
        from openfactory.product import semaphore
        from openfactory.product.voice import semaphore_busy, too_much_at_once

        # `getattr`, like the writers that call this: a module built without a project (a test's
        # `__new__`) is a product of one — no name — and its write still goes through the lock
        project = getattr(self, "project", None)
        lang = getattr(project, "language", None)
        # WHAT BECAME OF EACH WRITE, in order, on this module — a module is one turn's — so the
        # confirmation that asked for it can tell a write the semaphore refused from one that
        # happened, and keep a refused yes staged (`confirm._refused_for_contention`)
        outcomes = self.__dict__.setdefault("_write_outcomes", [])
        try:
            checked = semaphore.check_and_write(project, seen=seen, kind=kind, text=text,
                                                write=write, saved=saved, judge=judge,
                                                against=against)
        except semaphore.Busy as exc:
            outcomes.append("refused")
            return _could_not(semaphore_busy(language=lang), act=act, cause=exc)
        if checked.found is not None:
            outcomes.append("found")
            log.info("OPENFACTORY_PRODUCT_JUST_ASKED act=%s ref=%s — saved moments ago in another "
                     "conversation; nothing written, the person is linked to it", act,
                     checked.found.ref or "-")
            return found(checked.found)
        if checked.crowded:
            outcomes.append("refused")
            return _could_not(too_much_at_once(language=lang), act=act,
                              cause="the product's write sequence moved on every round")
        outcomes.append("written")
        return checked.result

    def _same_as(self, text: str, items: list):
        """Of what was SAVED after a proposal's check, the item that IS it — or None.

        CALLED OUTSIDE THE SEMAPHORE, ALWAYS (`semaphore.check_and_write`), because it may ask the
        model: a judgement held under the lock would hold every other write of the product for as
        long as the model takes. Only the items that share enough words to be the same request
        reach the model at all; none does, and nothing is asked.

        When the model cannot say, the closest is taken as the match: the person is then linked to
        a card or a requirement close to what they asked for, and told so — a visible correction
        away — rather than a second copy of it written unchecked (ADR-0051: nothing is written
        unchecked)."""
        from openfactory.product import semaphore

        close = semaphore.closest(text, items)
        if not close:
            return None
        verdict = ""
        try:
            sandbox, ws = self._workspace()
            verdict = self._role().judge_same(sandbox=sandbox, workspace=ws, request=text,
                                              candidates=[i.text for i in close])
        except Exception:  # noqa: BLE001 — an unjudged match falls back to the words, said below
            log.warning("could not judge whether a request is the same as one just saved",
                        exc_info=True)
        if verdict == "none":
            return None
        if verdict.isdigit() and 1 <= int(verdict) <= len(close):
            return close[int(verdict) - 1]
        log.warning("OPENFACTORY_PRODUCT_SAME_UNJUDGED ref=%s — the model gave no verdict; the "
                    "closest saved item is taken as the match rather than write a second copy",
                    close[0].ref or "-")
        return close[0]

    def propose(self, answer: ProductAnswer, *, actor: str, asked_by: str = "",
                date: str = "", source: str = "", seen: int | None = None) -> WriteResult:
        """Record a drafted requirement as a pull request — the sign-off surface.

        Takes the ProductAnswer from `draft` rather than re-deriving one, so what a human saw in
        the conversation is exactly what gets committed.

        MINTED, COMMITTED AND PUSHED UNDER THE PRODUCT'S SEMAPHORE (ADR-0051 D7). Two proposals at
        once used to mint one number — the second push was refused and landed on a `req/N-…`
        branch under the same N. `seen` is the sequence the staged draft's check saw: a
        requirement saved since, by another conversation, that is the same request is linked
        instead of written again."""
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

        from openfactory.product.voice import just_asked_for_a_requirement

        cfg = self.project.product
        docs = ctx.link.docs_repo
        title = answer.draft.title
        try:
            return self._checked_write(
                act="propose a requirement", kind="requirement", text=title, seen=seen,
                write=lambda: propose_requirement(
                    docs_repo=docs, clone_url=self._clone_url(docs), draft=answer.draft,
                    token=self.token or "",   # `gh` has no ambient login in the worker
                    # …and on a non-GitHub forge that token must not reach `gh` AT ALL: it is this
                    # project's Azure/GitLab credential, and `gh` would export it to github.com.
                    forge_kind=self._forge_kind(),
                    # the two READS that used to be `gh` and now work on every vendor: which
                    # proposal branches exist (the number is minted against them) and whether this
                    # one was ever proposed. Not optional — a missing forge means "could not
                    # read", and the writer refuses rather than minting against a board it never
                    # saw.
                    forge=self._forge(),
                    # a floor, not the mint: the writer mints from the base its own clone holds,
                    # under the semaphore (`propose_requirement`)
                    number=next_number(ctx.corpus),
                    requirements_dir=ctx.requirements_dir, asked_by=asked_by, date=date,
                    source=source, base=cfg.docs_branch),
                # a number minted is a number saved, landed or not: the next writer must see it
                saved=lambda r: ((f"REQ-{r.number:04d}", r.url)
                                 if r.number and not r.existed else None),
                judge=self._same_as,
                found=lambda item: WriteResult(
                    ok=False, existed=True, just_asked=True, ref=item.ref,
                    number=_req_number(item.ref),
                    detail=just_asked_for_a_requirement(
                        number=_req_number(item.ref), title=item.text,
                        language=getattr(self.project, "language", None))))
        except Exception as exc:  # noqa: BLE001 — a chat listener must not see a traceback
            return _could_not("não consegui registrar esse requisito agora. Nada foi escrito — o "
                              "time foi avisado e resolve.",
                              act="propose a requirement", cause=exc)

    # ---- filing work ---------------------------------------------------------------------------

    #: Where a filed issue lands. A CONSTANT, never a parameter: TO-DO is what the poller pulls, so
    #: a column name the caller could choose would be a money gate one argument wide. The product
    #: role writes work down; a human decides when it starts (ADR-0019 §5).
    #:
    #: The NAME comes from the platform's vocabulary (`adapters/board/columns.py`); what stays
    #: closed here is the CHOICE OF KEY, which is the half the money gate turns on.
    FILING_COLUMN = CANONICAL_COLUMNS["backlog"]

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

        `actor` is the PERSON's id — exactly what `may_act` checks against the allowlist, exactly
        what every sibling write branch passes. It used to be decorated with one chat vendor's
        mention syntax where the record was written, and the one call site that pre-decorated it
        made every channel acceptance fail this method's own re-gate; since #266 slice 6 nothing
        decorates it at all — the file names the person as the platform knows them.
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
            # `nothing_to_build` HERE TOO: a second acceptance is the catalog's retry door — it
            # runs the breakdown again — so a reading of the code has to answer the same the
            # second time, or the second click files what the first one rightly did not (#182).
            return WriteResult(ok=True, existed=True, ref=req.path,
                               detail="esse já estava acordado",
                               nothing_to_build=req.came_from_the_code)
        cfg = getattr(self.project, "product", None)
        refused = _not_the_requester(cfg, actor=actor, requester=getattr(req, "asked_by", ""),
                                     language=getattr(self.project, "language", None))
        if refused:
            return WriteResult(ok=False, detail=refused)
        try:
            # UNDER THE SEMAPHORE FOR ITS WRITE ALONE (ADR-0051 D7): an acceptance has nothing to
            # duplicate — the clone says "already" — but its push to the context repository
            # collides with every other one, and the second of two used to be told it failed
            result = self._corpus_changed(self._checked_write(
                act=f"accept requirement {number}", kind="acceptance", text=f"REQ-{number:04d}",
                seen=None, against=(), found=lambda item: WriteResult(ok=True, existed=True),
                write=lambda: accept_requirement(
                    docs_repo=ctx.link.docs_repo,
                    clone_url=self._clone_url(ctx.link.docs_repo),
                    path=self._requirement_path(req),
                    number=number,
                    # decorated HERE, for the record alone — the raw id was what authorised the act
                    accepted_by=actor,
                    base=getattr(cfg, "docs_branch", "main")),
                saved=_saved_in_the_repository))
            # WHAT WAS JUST AGREED TO IS ALREADY BUILT, and the act says so itself (#182). Decided
            # on the requirement's own data — the evidence a baseline pass wrote into the file —
            # never on which surface the yes came from: both doors into an acceptance read this
            # field and neither asks the role to break built behaviour into issues.
            if result.ok:
                result.nothing_to_build = req.came_from_the_code
            return result
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
            return self._corpus_changed(self._checked_write(
                act=f"drop requirement {number}", kind="drop", text=f"REQ-{number:04d}",
                seen=None, against=(), found=lambda item: WriteResult(ok=True, existed=True),
                write=lambda: drop_requirement(
                    docs_repo=ctx.link.docs_repo, clone_url=self._clone_url(ctx.link.docs_repo),
                    path=self._requirement_path(req),
                    number=number, dropped_by=actor, reason=reason,
                    base=getattr(cfg, "docs_branch", "main")),
                saved=_saved_in_the_repository))
        except Exception as exc:  # noqa: BLE001 — a chat listener must not see a traceback
            return _could_not(f"não consegui registrar o abandono do requisito {number} agora. "
                              f"Nada mudou — o time foi avisado e resolve.",
                              act=f"drop requirement {number}", cause=exc)

    def confirm_capability(self, slug: str, *, actor: str) -> WriteResult:
        """A person of the product confirms a business capability — the ONLY act that makes one
        curated truth (ADR-0052 D19, #268 slice 3, `product/capabilities.py`).

        What is confirmed is either a flow the knowledge pipeline observed (`.okf/flows/`), written
        as the capability with its links as they were seen, or a capability file somebody wrote
        without a confirmation, flipped with who and when. Gated like every write that changes what
        the factory argues from: an authorised person (`may_act`), through the product's semaphore
        for its push. `actor` is the person's id, recorded in the file for whoever maintains it and
        never rendered into a conversation.

        NEVER FROM A TURN BY ITSELF. Nothing in a reply confirms a capability; this is reached by a
        person's own act (`product_confirm_capability` in the action catalogue), with their yes."""
        from openfactory.knowledge.flows import FLOWS_DIRNAME, read_flows
        from openfactory.knowledge.okf import OKF_DIRNAME
        from openfactory.product.capabilities import (
            CAPABILITIES_DIR,
            confirm_in_repository,
            is_slug,
        )

        ctx = self.context()
        if not ctx.available:
            return self._cannot_see_the_product()
        if not may_act(self.project, actor, via=self._via):
            return WriteResult(ok=False, detail=unauthorized_message(self.project))
        wanted = (slug or "").strip().lower()
        if not is_slug(wanted):
            # A NAME, NEVER A PATH: the slug is typed by a person and names the file written
            return WriteResult(ok=False, detail="esse nome não é o de uma capacidade")
        docs = Path(ctx.docs_path)
        flows = read_flows(docs / OKF_DIRNAME / FLOWS_DIRNAME)
        flow = flows.by_slug(wanted) if flows is not None else None
        written = (docs / CAPABILITIES_DIR / f"{wanted}.md").is_file()
        if flow is None and not written:
            return WriteResult(ok=False,
                               detail="não encontrei essa capacidade entre as observadas nem entre "
                                      "as escritas")
        cfg = getattr(self.project, "product", None)
        try:
            return self._corpus_changed(self._checked_write(
                act=f"confirm capability {wanted}", kind="capability", text=wanted, seen=None,
                against=(), found=lambda item: WriteResult(ok=True, existed=True),
                write=lambda: confirm_in_repository(
                    docs_repo=ctx.link.docs_repo, clone_url=self._clone_url(ctx.link.docs_repo),
                    slug=wanted, flow=flow, confirmed_by=actor,
                    base=getattr(cfg, "docs_branch", "main")),
                saved=_saved_in_the_repository))
        except Exception as exc:  # noqa: BLE001 — a chat listener must not see a traceback
            return _could_not(f"não consegui registrar a confirmação da capacidade {wanted} "
                              f"agora. Nada mudou — o time foi avisado e resolve.",
                              act=f"confirm capability {wanted}", cause=exc)

    def record_decision(self, number: int, *, decision: str, actor: str,
                        where: str = "", seen: int | None = None) -> WriteResult:
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
            # SAVED AT CONFIRMATION, UNDER THE SEMAPHORE (ADR-0051 D7, D10): two decisions saved at
            # once both land — the second clones after the first pushed — and the same decision
            # recorded moments ago from another conversation is said to exist, not written twice
            return self._corpus_changed(self._checked_write(
                act=f"record a decision on requirement {number}", kind="decision",
                text=f"REQ-{number:04d}: {decision}", seen=seen,
                found=lambda item: WriteResult(ok=True, existed=True, just_asked=True,
                                               ref=self._requirement_path(req),
                                               detail="essa decisão acabou de ser registrada"),
                write=lambda: record_decision(
                    docs_repo=ctx.link.docs_repo, clone_url=self._clone_url(ctx.link.docs_repo),
                    path=self._requirement_path(req), number=number,
                    decision=decision, decided_by=actor, where=where,
                    base=getattr(cfg, "docs_branch", "main")),
                saved=_saved_in_the_repository))
        except Exception as exc:  # noqa: BLE001 — a chat listener must not see a traceback
            return _could_not(f"não consegui registrar essa decisão no requisito {number} agora. "
                              f"Nada mudou — o time foi avisado e resolve.",
                              act=f"record a decision on requirement {number}", cause=exc)

    def record_answer(self, *, about: str, question: str, answer: str, said_by: str,
                      where: str, requirement: int | None = None) -> WriteResult:
        """A person answered, on the factory's own card, a question the factory asked there
        (ADR-0048 §6) — write it into the product's context in THEIR name.

        NOT GATED BY `may_act`, AND THE REASON IS WHAT THE WRITE IS. `record_decision` asks
        whether the ACTOR may change the document, because the actor is a person acting through
        the channel. Here the actor is the factory recording what a person wrote where the factory
        asked them to write it — provenance, not authorisation; the requester of a card is not on
        the product allowlist on any deployment, and gating on it would have refused every answer
        (ADR-0048, refutation 1). `said_by` is stored verbatim: it is a tracker identity, and the
        `<@…>` a chat mention wears would render as a broken tag in the client's own document.

        When the card cites a live requirement the answer is a decision on it; otherwise it is a
        fact about `about` (the file the question was about), `aprendido`, attributed. A term the
        context already holds is answered with `existed=True` — the caller reads that as recorded,
        which it is."""
        from openfactory.product.authoring import record_decision, record_fact

        ctx = self.context()
        if not ctx.available:
            return self._cannot_see_the_product()
        who = (said_by or "").strip() or "unknown"
        text = " ".join((answer or "").split())
        cfg = getattr(self.project, "product", None)
        base = getattr(cfg, "docs_branch", "main")
        try:
            if requirement is not None:
                req = ctx.corpus.by_number(requirement)
                if req is not None and req.is_live:
                    said = f"{' '.join(question.split())} — {text}"
                    return self._corpus_changed(self._checked_write(
                        act="record an answer given on the card", kind="decision",
                        text=f"REQ-{requirement:04d}: {said}", seen=None,
                        found=lambda item: WriteResult(ok=True, existed=True),
                        write=lambda: record_decision(
                            docs_repo=ctx.link.docs_repo,
                            clone_url=self._clone_url(ctx.link.docs_repo),
                            path=self._requirement_path(req), number=requirement,
                            decision=said, decided_by=who, where=where, base=base),
                        saved=_saved_in_the_repository))
            term = (about or "").strip()[:120] or " ".join(question.split())[:120]
            existing = ctx.domain.get(term)
            if existing is not None:
                # WHAT IS WRITTEN, NEVER WHO SAID IT (#266 slice 4, ADR-0051 D9) — `note_fact`'s
                # rule, which this sentence missed: it is posted on the card, to its requester,
                # and whoever told the context this term is not theirs to learn from it
                return WriteResult(ok=False, existed=True,
                                   detail=f"já tenho isto anotado sobre {term!r}: "
                                          f"{existing.body[:160]}")
            return self._checked_write(
                act="record an answer given on the card", kind="fact", text=term, seen=None,
                found=lambda item: WriteResult(ok=False, existed=True,
                                               detail=f"isto acabou de ser anotado sobre {term!r}"),
                write=lambda: record_fact(
                    docs_repo=ctx.link.docs_repo, clone_url=self._clone_url(ctx.link.docs_repo),
                    term=term, body=text, said_by=who, where=where, base=base),
                saved=_saved_in_the_repository)
        except Exception as exc:  # noqa: BLE001 — the sweep reads the result; never a traceback
            return _could_not(f"não consegui registrar a resposta sobre {about!r} agora. Nada foi "
                              f"escrito — o time foi avisado e resolve.",
                              act="record an answer given on the card", cause=exc)

    def file_issues(self, requirement, *, actor: str, tracker=None, board=_UNSET,
                    conversation: str = "", requester: str = "") -> list[WriteResult]:
        """Break a requirement into issues and file them into Backlog, each citing its source.

        One result per issue, in order, so a partial failure is visible per item rather than
        collapsing into "something went wrong" — the caller reports exactly which ones landed.

        `conversation` and `requester` are where, and by whom, the requirement was asked for — read
        off what they staged (`confirm._whose`) — so its delivery is announced there (#267 slice
        3). A filing that knows neither — a panel button, a CLI verb — is announced to the room."""
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
        self._open_delivery(requirement, results, conversation=conversation,
                            requester=requester)
        return results

    def file_ticket(self, *, title: str, described: str, reported_by: str, source: str = "",
                    tracker=None, board=_UNSET, seen: int | None = None) -> WriteResult:
        """Open the card a person asked for, as described — the first of the three verbs at the
        frontier (#33: create, reorder, move to `To Do`), and until now the one that did not exist:
        `file_defect` filed a broken promise and `breakdown` filed work from a matched gesture, and
        there was no "describe it to me and I will open it".

        SAME PEN AS A DEFECT, SAME GATE. It lands in Backlog, never `To Do` — starting the work
        spends money and that stays a person's call (ADR-0019 §5). The confirmation happened in the
        conversation; this method writes. Deduplicated by exact title like a defect, because a
        person who asks twice wants one card, and the reply says so. Answers with the URL, which is
        what #33 asks of every one of the three verbs.

        CHECKED AND FILED AS ONE STEP, UNDER THE PRODUCT'S SEMAPHORE (ADR-0051 D7). Two
        conversations asking for the same card at once both found nothing and both filed it. The
        title lookup and the create now happen inside the semaphore, and a card saved by another
        conversation after this one's check (`seen`) that is the same request comes back as it —
        linked, with nobody's name. The placement is after: the card exists, and where it sits
        is repairable."""
        from openfactory.product.authoring import ticket_body
        ctx = self.context()
        name = title.strip().rstrip(".")[:80]
        if not name:
            return _could_not("preciso de um título para abrir o cartão.", act="file a ticket")
        tracker = tracker or self._tracker()

        def _open() -> WriteResult:
            existing = tracker.find_ticket(title=name)
            if existing:
                return WriteResult(ok=True, ref=str(existing), existed=True,
                                   url=self._issue_url(tracker, str(existing)),
                                   detail="já existe um cartão com esse título")
            made = tracker.create_ticket(
                title=name,
                body=ticket_body(described=described, reported_by=reported_by, source=source,
                                 docs_repo=ctx.link.docs_repo,
                                 requester_forge=forge_identity_for(
                                     getattr(self, "project", None), reported_by, tracker)))
            return WriteResult(ok=True, ref=str(made), url=self._issue_url(tracker, made))

        try:
            opened = self._checked_write(
                act="file a ticket", kind="ticket", text=name, seen=seen, against=_CARD_KINDS,
                write=_open, saved=_saved_on_the_board, judge=self._same_as,
                found=_the_card_just_asked_for)
        except Exception as exc:  # noqa: BLE001 — a chat listener must never see a traceback
            return _could_not("não consegui abrir o cartão agora. Nada foi escrito — o time foi "
                              "avisado e resolve.", act="file a ticket", cause=exc)
        if not opened.ok or opened.existed:
            return opened
        ref, url = opened.ref, opened.url
        number = _as_ticket_number(ref)
        board = self._board_or_default(board)
        detail = ""
        if board is not None and number:
            placed = False
            try:
                board.add_item(issue_url=url)
                placed = bool(board.set_column(issue=str(number), issue_url=url,
                                               name=self.FILING_COLUMN))
            except Exception as exc:  # noqa: BLE001 — the card exists; placement is repairable
                log.info("card %s opened but not placed on the board (%s)", ref, exc)
            if not placed:
                log.warning("OPENFACTORY_PRODUCT_TICKET_NOT_PLACED ref=%s column=%s — the card "
                            "exists but has no column, so the queue cannot see it until a person "
                            "places it", ref, self.FILING_COLUMN)
                detail = ("abri o cartão, mas ainda não consegui posicioná-lo no quadro — o time "
                          "foi avisado e posiciona.")
        return WriteResult(ok=True, ref=str(ref), url=url, detail=detail)

    def file_defect(self, *, restated: str, reported_by: str, violates: int | None,
                    severity: str = "", source: str = "", tracker=None,
                    board=_UNSET, seen: int | None = None, conversation: str = "",
                    requester: str = "") -> WriteResult:
        """Register a broken promise as work — classified, citing the requirement it violates.

        A defect skips the requirement-drafting ceremony ON PURPOSE: the promise already exists;
        what is being recorded is that reality disagrees with it. It still lands in Backlog, never
        TO-DO — starting the fix spends money, and that stays a person's call (ADR-0019 §5). The
        confirmation happened in the conversation (the channel holds the one yes, exactly like a
        requirement's); this method is the pen, not the judgement.

        And it is FOLLOWED UP: a delivery loop opens on the filed issue, so the person who reported
        it is told — unprompted — that the fix shipped, when it ships and in the conversation they
        reported it in (`conversation`, `requester`: #267 slice 3). A bug report that vanishes into
        a board the client cannot see is indistinguishable from being ignored."""
        from openfactory.product.authoring import defect_body

        ctx = self.context()
        title = restated.strip().rstrip(".")[:80]
        tracker = tracker or self._tracker()

        def _open() -> WriteResult:
            # `by_number`, and INSIDE the guard. The first version called a `.get` the corpus
            # never had, so any defect that actually CITED a requirement — the case the answer
            # prompt explicitly asks her for — crashed before the try, reached the channel's
            # catch-all as a generic "broke" message, and the consumed confirmation was gone.
            cited = ctx.corpus.by_number(violates) if violates else None
            existing = tracker.find_ticket(title=title)
            if existing:
                return WriteResult(ok=True, ref=str(existing), existed=True,
                                   detail="já registrei esse problema antes")
            made = tracker.create_ticket(
                title=title,
                body=defect_body(restated=restated, reported_by=reported_by,
                                 severity=severity, source=source,
                                 requester_forge=forge_identity_for(
                                     getattr(self, "project", None), reported_by, tracker),
                                 requirement=cited,
                                 # resolved, like every other citation this module writes: the
                                 # corpus's own field is a bare filename (`requirement_file`)
                                 requirement_path=(self._requirement_path(cited) if cited else ""),
                                 docs_repo=ctx.link.docs_repo,
                                 commit=ctx.docs_commit))
            return WriteResult(ok=True, ref=str(made), url=self._issue_url(tracker, made))

        try:
            # CHECKED AND FILED AS ONE STEP, like `file_ticket` and for its reason (ADR-0051 D7)
            filed = self._checked_write(
                act="file a defect", kind="defect", text=title, seen=seen, against=_CARD_KINDS,
                write=_open, saved=_saved_on_the_board, judge=self._same_as,
                found=_the_card_just_asked_for)
        except Exception as exc:  # noqa: BLE001 — a chat listener must never see a traceback
            return _could_not("não consegui registrar esse problema agora. Nada foi escrito — o "
                              "time foi avisado e resolve.",
                              act="file a defect", cause=exc)
        if not filed.ok or filed.existed:
            return filed
        ref = filed.ref

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
            self._track_defect(number, conversation=conversation, requester=requester)
        return WriteResult(ok=True, ref=str(ref), detail=detail)

    def _track_defect(self, number: str, *, conversation: str = "",
                      requester: str = "") -> None:
        """A delivery loop on the fix, so 'consertamos o que você reportou' gets said unprompted —
        in the conversation it was reported in, when there is one (#267 slice 3).

        Subject `defeito-N` rather than a requirement number: the loop closes when THIS issue
        closes, and the sweep's delivered() pass already knows how to watch a set of issues."""
        try:
            from datetime import UTC, datetime

            from openfactory.memory import store as loop_store
            from openfactory.memory.ledger import DELIVERY, open_loop, waiting
            from openfactory.product.followup import delivered_to

            ledger = loop_store.read(self.project.name)
            already = {x.subject for x in waiting(ledger) if x.kind == DELIVERY}
            subject = f"defeito-{number}"
            if subject in already:
                return
            loop_store.write(self.project.name, [open_loop(
                DELIVERY, subject, owner="product", ts=datetime.now(UTC).isoformat(),
                context={"issues": str(number), "defect": "1",
                         **delivered_to(conversation, requester)})])
        except Exception as exc:  # noqa: BLE001 — the defect was filed; only the courtesy is lost
            log.warning("could not start tracking defect #%s (%s) — the fix will ship without "
                        "anyone announcing it to the reporter", number, exc)

    def note_fact(self, *, term: str, body: str, said_by: str, where: str = "",
                  seen: int | None = None) -> WriteResult:
        """Write down one thing somebody said about the business — as `aprendido`, attributed.

        Refuses to silently overwrite: a term that already exists is answered with what is written,
        because two versions of the same fact is worse than either. Status stays `aprendido`
        (never `confirmado` from a chat message — domain.py's discipline), so recording this hands
        nothing new to the factory to defend."""
        from openfactory.product.authoring import record_fact
        from openfactory.product.voice import just_noted

        ctx = self.context()
        if not ctx.available:
            return self._cannot_see_the_product()
        existing = ctx.domain.get(term)
        if existing is not None:
            # WHAT IS WRITTEN, NEVER WHO SAID IT (ADR-0051 D9): the fact may have been told in
            # another conversation, and its teller is not this person's to learn from a refusal
            return WriteResult(
                ok=False, existed=True,
                detail=f"já tenho isto anotado sobre {term!r}: {existing.body[:160]}")
        try:
            return self._checked_write(
                act="record a fact", kind="fact", text=term, seen=seen,
                found=lambda item: WriteResult(
                    ok=False, existed=True, just_asked=True,
                    detail=just_noted(term=term,
                                      language=getattr(self.project, "language", None))),
                write=lambda: record_fact(
                    docs_repo=ctx.link.docs_repo,
                    clone_url=self._clone_url(ctx.link.docs_repo),
                    term=term, body=body, said_by=said_by, where=where,
                    base=getattr(self.project.product, "docs_branch", "main")),
                saved=_saved_in_the_repository)
        except Exception as exc:  # noqa: BLE001
            return _could_not(f"não consegui anotar o que você me disse sobre {term!r} agora. Nada "
                              f"foi escrito — o time foi avisado e resolve.",
                              act="record a fact", cause=exc)

    def record_distillate(self, *, path: str, text: str, after: str) -> WriteResult:
        """Write one conversation's distillate into the context repository (#269 slice 3, ADR-0053
        D4) — THROUGH THE PRODUCT'S SEMAPHORE, like every write of its record: the clone, the
        once-per-span check and the push are one step (`authoring.record_distillate`), and the
        model that distilled it ran before, outside the lock (`product/distil.py`).

        Nobody confirmed it and nobody is asked: it is a reading, cited as evidence and never made
        a decision or a requirement except by a person's confirmation (ADR-0053 D14) — which is
        why it is declared among the writes that do not ask `may_act` (the module's docstring)."""
        from openfactory.product.authoring import record_distillate

        ctx = self.context()
        if not ctx.available:
            return self._cannot_see_the_product()
        cfg = getattr(self.project, "product", None)
        try:
            return self._checked_write(
                act="distil a conversation", kind="distillate", text=path, seen=None, against=(),
                found=lambda item: WriteResult(ok=True, existed=True, ref=path),
                write=lambda: record_distillate(
                    docs_repo=ctx.link.docs_repo, clone_url=self._clone_url(ctx.link.docs_repo),
                    path=path, text=text, after=after,
                    base=getattr(cfg, "docs_branch", "main")),
                saved=_saved_in_the_repository)
        except Exception as exc:  # noqa: BLE001 — the pass reads it again at the next tick
            return _could_not("não consegui guardar o resumo da conversa agora.",
                              act="distil a conversation", cause=exc)

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

    def _open_delivery(self, requirement, results: list[WriteResult], *, conversation: str = "",
                       requester: str = "") -> None:
        """The moment a requirement becomes filed work is the moment she starts WAITING on it
        (ADR-0021): a `delivery` loop opens here, and it closes when every one of these issues is
        delivered — observed the moment a job finishes one (`events.card_finished`), or by the
        weekly sweep as the catch-all — and only then does she say "está pronto", in the
        conversation it was asked in (`conversation`), else the room (#267 slice 3).

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
                                       ts=datetime.now(UTC).isoformat(),
                                       conversation=conversation, requester=requester)
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
        where, elsewhere = self._filing_repo(draft, tracker)
        try:
            # An existing issue with this title is this operation's own prior result far more often
            # than it is a coincidence: a retried conversation must not file the work twice.
            existing = tracker.find_ticket(title=title) or self._titled_in(where, title)
            if existing:
                return WriteResult(ok=True, ref=str(existing), existed=True,
                                   detail="já existe um cartão com esse título")
            ref = tracker.create_ticket(
                title=title,
                body=issue_body(draft, requirement_path=self._requirement_path(requirement),
                                docs_repo=self.context().link.docs_repo,
                                docs_url=self._docs_url(),
                                commit=self.context().docs_commit,
                                awaiting=awaiting_of(requirement),
                                # THE ONE HOP nothing made: a card born from a requirement is
                                # asked for by whoever asked for the requirement
                                requester=getattr(requirement, "asked_by", "") or "",
                                requester_forge=forge_identity_for(
                                    getattr(self, "project", None),
                                    getattr(requirement, "asked_by", "") or "", tracker)),
                **({"repo": where} if where else {}))
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
            from openfactory.contracts.refs import ref_number, split_repo_ref

            placed = False
            # a card filed in another repository of the product comes back QUALIFIED (C-18); its
            # number is the part after the repository
            number = ref_number(split_repo_ref(ref)[1])
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
        return WriteResult(ok=True, ref=str(ref), detail=elsewhere)

    def _filing_repo(self, draft, tracker) -> tuple[str, str]:
        """`(repository, said)` — where a card of this draft is filed: the repository the role
        named for it (`target_repo`) ONLY when that is one of the product's `sources:` and not the
        tracker's own, and the tracker can file there (`files_elsewhere`); `""` otherwise, with a
        sentence when a named repository was not honoured (#265 §6.2).

        THE MEMBERSHIP SET BOUNDS IT, NEVER THE MODEL. `target_repo` is a model's answer, and an
        issue filed in a repository outside the product is a card of another client's code on
        this product's board — so a name outside `sources:` is filed where every card was filed
        before this existed, and said."""
        from openfactory.adapters.tracker.base import files_elsewhere
        from openfactory.product.config import repo_match

        target = str(getattr(draft, "target_repo", "") or "").strip().strip("/")
        default = self._source_repo()
        if not target or (default and repo_match(target, default)):
            return "", ""
        home = next((s for s in self._sources() if s and repo_match(target, s)), "")
        if not home:
            log.warning("OPENFACTORY_PRODUCT_TARGET_OUTSIDE_SOURCES project=%s target=%s — not a "
                        "repository of this product; the card is filed in %s",
                        getattr(self.project, "name", "?"), target, default or "its default")
            return "", (f"o cartão foi aberto em `{default or 'o repositório padrão'}`: "
                        f"`{target}` não está entre os repositórios deste produto.")
        if not files_elsewhere(tracker):
            return "", (f"o cartão foi aberto em `{default or 'o repositório padrão'}`: este "
                        f"quadro registra todo cartão num lugar só, e ele é de `{home}`.")
        return home, ""

    def _titled_in(self, repo: str, title: str) -> str | None:
        """An OPEN card titled `title` in `repo`, from the board this pass already read — the
        idempotency `find_ticket` gives the tracker's own repository, for a card filed in another
        one: a retried conversation must not file it twice there either."""
        if not repo:
            return None
        from openfactory.contracts.refs import split_repo_ref
        from openfactory.product.config import repo_match

        for card in self._board_tickets or ():
            where, number = split_repo_ref(card.number, self._source_repo())
            if card.state != "closed" and card.title.strip() == title and \
                    repo_match(where, repo):
                return str(card.number)
        return None

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

    def open_cards_for(self, number: int, *, actor: str, tracker=None, board=_UNSET,
                       conversation: str = "", requester: str = ""):
        """The official card(s) for a requirement the conversation has just written — BEFORE the
        promise (ADR-0047 §2). Gated: this writes.

        `break_down` refuses a proposal, and rightly: filing work from one used to commit the
        factory to a decision nobody had made. Here the card IS what the requester is about to
        decide on — it lands in Backlog, inert, saying on its face whose acceptance it awaits, and
        the second yes is given on it. A requirement that is off the table gets nothing.

        `conversation` and `requester` are handed to the filing (`file_issues`)."""
        ctx = self.context()
        if not ctx.available:
            return [self._cannot_see_the_product()]
        requirement = ctx.corpus.by_number(number)
        if requirement is None:
            return [WriteResult(ok=False, detail=f"não encontrei o requisito {number}")]
        if not requirement.is_live:
            return [WriteResult(ok=False, detail=f"o requisito {number} já não vale — não abri "
                                                 f"nenhum cartão para ele")]
        return self.file_issues(requirement, actor=actor, tracker=tracker, board=board,
                                conversation=conversation, requester=requester)

    def stamp_acceptance(self, number: int, cards: list[str], *, actor: str, requester: str = "",
                         where: str = "", tracker=None, today: str | None = None):
        """The acceptance, written where the work lives: one comment per card, in the requester's
        name (ADR-0047 §3). Gated like the acceptance it records.

        The requirement already carries who agreed and when — that is the record. This is the
        VISIBLE copy: whoever picks the card up reads that it is a promise, and whose, without
        opening the context repository. A comment that cannot be posted is said, per card, and the
        agreement stands; the copy is a courtesy, never the act."""
        from datetime import UTC, datetime

        from openfactory.product.voice import acceptance_stamp

        if not may_act(self.project, actor, via=self._via):
            return [WriteResult(ok=False, detail=unauthorized_message(self.project))]
        refused = _not_the_requester(getattr(self.project, "product", None), actor=actor,
                                     requester=requester,
                                     language=getattr(self.project, "language", None))
        if refused:
            return [WriteResult(ok=False, detail=refused)]
        tracker = tracker or self._tracker()
        day = today or datetime.now(UTC).date().isoformat()
        text = acceptance_stamp(number=number, actor=actor, requester=requester, day=day,
                                where=where, language=getattr(self.project, "language", None),
                                agent_name=self._name())
        results: list[WriteResult] = []
        for ref in cards:
            try:
                tracker.comment(str(ref), text)
                results.append(WriteResult(ok=True, ref=str(ref)))
            except Exception as exc:  # noqa: BLE001 — one card's comment must not lose the others
                # the agreement stands in the requirement; only this card does not show it
                results.append(_could_not(f"não consegui registrar o aceite no {ref}",
                                          act=f"stamp the acceptance on {ref}", cause=exc,
                                          ref=str(ref)))
        return results

    def break_down(self, number: int, *, actor: str, asked_for: bool, board=_UNSET,
                   conversation: str = "", requester: str = ""):
        """Turn one requirement into units of work, filed into Backlog. Gated: this writes.

        `conversation` and `requester` are where the requirement was asked for, when the caller
        knows (the acceptance's second act, `confirm._also_broke_it_down`) — its delivery is
        announced there (#267 slice 3).

        `asked_for` HAS NO DEFAULT, ON PURPOSE (#182). It says whether a PERSON asked for this
        breakdown — "quebra o requisito 7", the `product_break_down` row — or whether it is the
        automatic second act of an acceptance. The difference decides one case: a requirement
        that came from the code describes behaviour that is already built, so the automatic chain
        files nothing for it, while a person who asks is telling us something the file cannot —
        that the text now says more than the code does. A default would let the next call site
        stay silent on the question, and silence is how the automatic chain reached a 65-entry
        baseline with *"Break the requirement below into issues"*: a caller that does not say
        fails on its first run instead.

        THE SINK ASKS AS WELL AS THE DOORS. Both acceptance doors already read the acceptance's
        own `nothing_to_build` and never get here. This is what stops the door nobody has written
        yet, and an older panel starting the workflow against a newer worker."""
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
        if requirement.came_from_the_code and not asked_for:
            from openfactory.product.voice import nothing_to_build

            # NOT `ok`, AND NOT A FAILURE EITHER — so it carries both. A caller that knows the
            # field reads it and says the right thing. One that does not (an older panel reading
            # this worker's answer) treats it as "nothing was filed" and prints the detail, which
            # is this sentence: why, and how to ask. `ok=True` with no ref would have been counted
            # as a card — "Work filed: ?" — about work that does not exist.
            return [WriteResult(ok=False, nothing_to_build=True,
                                detail=nothing_to_build(
                                    number=number,
                                    language=getattr(self.project, "language", None)))]
        return self.file_issues(requirement, actor=actor, board=board,
                                conversation=conversation, requester=requester)

    def _name(self) -> str:
        return getattr(getattr(self.project, "product", None), "agent_name", "") or ""

    # ---- keeping the factory busy --------------------------------------------------------------

    #: Where approved work lands. A constant, as in `FILING_COLUMN`: this is the column the poller
    #: pulls from, so a caller able to name it is a money gate one argument wide. The name is the
    #: platform's own (`adapters/board/columns.py`); the key is what stays closed.
    QUEUE_COLUMN = CANONICAL_COLUMNS["todo"]

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

    def reorder(self, numbers: list[str], *, actor: str, board=None) -> list[WriteResult]:
        """Write the backlog order — the product owner's second verb at the frontier (#33), and
        until now the one that only ever PROPOSED: `propose_queue` said what should start next and
        wrote nothing, so a reprioritisation lived in a chat message until somebody dragged cards.

        THE ORDER IS THE SEQUENCE GIVEN, top first, and it is written as a chain of "after the
        previous one" placements — the primitive every board can honour (`Rankable.place_after`)
        rather than a renumbering none of them wants. Cards not named keep their places below.
        Gated on the allowlist like `promote`, because the next `promote` follows board order and
        an order anybody could write is an order anybody could spend against. Spends nothing itself.

        A BOARD THAT CANNOT RANK SAYS SO. `Rankable` is a capability, not a promise every board
        makes; the refusal names the board rather than raising in a listener."""
        if not may_act(self.project, actor, via=self._via):
            return [WriteResult(ok=False, detail=unauthorized_message(self.project))]
        board = board or self._board()
        if board is None:
            return [WriteResult(ok=False, detail="não consegui acessar o quadro")]
        from openfactory.adapters.board.base import Rankable
        if not isinstance(board, Rankable):
            return [WriteResult(ok=False, detail="este quadro ainda não aceita reordenação por "
                                                 "aqui — a ordem precisa ser mudada no próprio "
                                                 "quadro")]
        from openfactory.product.board import forget_board
        forget_board(getattr(self.project, "name", ""))
        tracker = self._tracker()
        out: list[WriteResult] = []
        previous: str | None = None
        for number in numbers:
            try:
                url = self._issue_url(tracker, number)
                placed = bool(board.place_after(issue=str(number), issue_url=url, after=previous,
                                                column=self.FILING_COLUMN))
                out.append(WriteResult(ok=placed, ref=f"#{number}",
                                       detail="" if placed else "o quadro recusou a reordenação"))
                if placed:
                    previous = str(number)
            except Exception as exc:  # noqa: BLE001 — one failure must not lose the rest
                out.append(_could_not(f"não consegui reposicionar o #{number} agora. O time foi "
                                      f"avisado e resolve.",
                                      act="reorder the backlog", cause=exc, ref=f"#{number}"))
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
        from openfactory.adapters.tracker.parse import criteria_heading

        if criteria_heading(ticket.body or "") is not None:
            # see `voice._REFINE_WOULD_BE_IGNORED`: an appended set under the first section is a
            # set the parser never reads, and the next refine would append another
            from openfactory.product.voice import refine_would_be_ignored

            return WriteResult(ok=False, ref=f"#{number}", detail=refine_would_be_ignored(
                number=number, language=getattr(self.project, "language", None)))

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

        `actor` is the person's id, the thing `may_act` checks, and it is written as it is — no
        vendor's mention syntax around it (#266 slice 6).

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
            #
            # THROUGH THE PORT'S SEAM (#203): a row written before `delivered` existed is refused
            # this close by name, instead of raising a `TypeError` this `except` would report as
            # "I could not close it" with nothing a person could act on.
            from openfactory.adapters.tracker.base import close_ticket

            close_ticket(tracker, f"#{number}",
                         _closing_note(in_favour_of=in_favour_of, actor=actor,
                                       reason=reason, agent=self._name()),
                         delivered=False)
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

    def correct_card(self, number: str, *, actor: str, text: str = "",
                     title: str = "") -> WriteResult:
        """Correct what a card this role opened from a request or a defect says (#156).

        THE ONE WAY SUCH A CARD CHANGES. #150 decided that a card this role opened is the product
        owner's: the board refuses to edit, close or reopen it, and the change is asked for here.
        A requirement card already had that path (change the requirement, then `align_card`); a
        request or a defect had none, so a request written down wrong could only be closed and
        asked for again, losing its number and its thread.

        WHAT IS REPLACED, AND WHAT GOES WITH IT. `text` replaces the section that holds what was
        asked (`O que foi pedido`) or what is happening (`O que está acontecendo`); `title` renames.
        The criteria `refine` wrote were derived from the old text, so they are removed with it and
        the reply offers to write new ones: criteria describing a request that no longer exists are
        what an agent would build. The card keeps the old text, in a comment.

        NOT ONCE THE FACTORY HAS IT, for the reason `card_edit` refuses: an agent works from the
        text it read at pickup. A column this platform does not map refuses too: it cannot say.

        TWO WRITES, TWO OUTCOMES (`close_card`): the correction, then the note. A note that failed
        is reported on a SUCCESS, never as a failure of the correction that landed.
        """
        from openfactory.adapters.board.base import stage_key
        from openfactory.adapters.board.columns import has_started
        from openfactory.product.voice import correction_note, correction_refused

        number = canonical_ref(number)
        text, title = (text or "").strip(), (title or "").strip()
        lang = getattr(self.project, "language", None)
        if not may_act(self.project, actor, via=self._via):
            return WriteResult(ok=False, detail=unauthorized_message(self.project))

        tickets, error = self._read_board()
        if error:
            return _could_not(_BOARD_UNREADABLE, act=f"correct #{number}", cause=error)
        card = next((t for t in tickets if t.number == number), None)
        if card is None:
            return WriteResult(ok=False, detail=correction_refused("not_found", number=number,
                                                                   language=lang))
        if card.state != "open":
            return WriteResult(ok=False, existed=True, ref=f"#{number}",
                               detail=correction_refused("closed", number=number, language=lang))
        kind = filed_by_the_product_role(card.body or "")
        if kind not in _WHAT_WAS_ASKED:
            return WriteResult(ok=False, ref=f"#{number}", detail=correction_refused(
                "requirement" if kind == "requirement" else "board", number=number, language=lang))
        column = (card.column or "").strip()
        if column:
            # THE SAME SEAM THE BOARD'S OWN GATE USES (#231). This asked `key_for` for the key with
            # `options.get("columns")` as the map, and `ProviderRef.options` is `dict[str, str]`:
            # on a Jira deployment that refused every correction as "a column this platform does
            # not map", and on one that HAD typed the option it raised `TypeError` into a chat.
            # The row holds the deployment's names (`adapters/board/base.py::Staged`).
            key = stage_key(self._board(), column)
            if not key or has_started(key):
                return WriteResult(ok=False, ref=f"#{number}", detail=correction_refused(
                    "started" if key else "unmapped", number=number, column=column,
                    language=lang))

        tracker = self._tracker()
        rename = getattr(tracker, "update_title", None) if title else None
        if title and rename is None:
            return WriteResult(ok=False, ref=f"#{number}",
                               detail=correction_refused("rename", number=number, language=lang))

        before = card.body or ""
        after, old_text, removed = _corrected(before, kind, text) if text else (before, "", None)
        text_changed = bool(text) and _as_said(old_text) != _as_said(text)
        title_changed = bool(title) and title != (card.title or "").strip()
        if not text_changed and not title_changed:
            return WriteResult(ok=True, existed=True, ref=f"#{number}")
        if not text_changed:
            removed = None

        from openfactory.product.board import forget_board

        failed = correction_refused("failed", number=number, language=lang)
        if text_changed:
            try:
                tracker.update_body(f"#{number}", after)
            except Exception as exc:  # noqa: BLE001 — a chat listener must not see a traceback
                return _could_not(failed, act=f"correct #{number}", cause=exc, ref=f"#{number}")
            forget_board(getattr(self.project, "name", ""))   # what we cached is now wrong

        residue = ""
        if title_changed:
            try:
                rename(f"#{number}", title)
            except Exception as exc:  # noqa: BLE001 — the text may have landed; the title did not
                if not text_changed:
                    return _could_not(failed, act=f"rename #{number}", cause=exc,
                                      ref=f"#{number}")
                log.warning("OPENFACTORY_PRODUCT_CORRECT_UNRENAMED card=#%s (%s) — the text was "
                            "corrected and the title was not", number, exc)
                residue = correction_refused("unrenamed", number=number, language=lang)
                title_changed = False
            else:
                forget_board(getattr(self.project, "name", ""))

        try:
            tracker.comment(f"#{number}", correction_note(
                kind=kind, actor=actor, old_text=old_text, old_title=card.title or "",
                text_changed=text_changed, title_changed=title_changed,
                criteria_removed=removed is not None, language=lang, agent_name=self._name()))
        except Exception as exc:  # noqa: BLE001 — the correction landed; only its record is lost
            log.warning("OPENFACTORY_PRODUCT_CORRECT_UNNOTED card=#%s (%s) — the card was "
                        "corrected and does not say what it said before", number, exc)
            residue = " ".join(filter(None, [
                residue, correction_refused("unnoted", number=number, language=lang)]))
        if residue:
            return WriteResult(ok=True, ref=f"#{number}", detail=residue)
        # A MEASURE, NOT A RESIDUE (`confirm._unfinished`): how many criteria went with the old
        # text, which the reply turns into the offer to write new ones.
        return WriteResult(ok=True, ref=f"#{number}",
                           detail=f"{removed} critérios" if removed is not None else "")

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
            if filed_by_the_product_role(card.body) == "defect":
                # A DEFECT RESTORES A PROMISE; IT DOES NOT EXECUTE ONE. Its citation is read now
                # (#265: a defect is a card of its requirement's preview), and the repair below
                # writes a REQUIREMENT card's Source over whatever it rewrites — so a defect is left
                # exactly as the repair has always left it: untouched.
                continue
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


#: The section that holds what a request asked for, or what a defect reports — the part of the card
#: `correct_card` replaces. The headings `authoring.ticket_body` and `defect_body` write.
_WHAT_WAS_ASKED = {"request": "O que foi pedido", "defect": "O que está acontecendo"}

#: The sections `_with_criteria` appends when `refine` writes criteria from a card's own text.
_REFINED_FROM_THE_TEXT = ("Acceptance criteria", "Out of scope", "Open questions")


def _as_said(text: str) -> str:
    return " ".join((text or "").split())


def _corrected(body: str, kind: str, text: str) -> tuple[str, str, int | None]:
    """`(new body, the text it replaced, criteria removed)` — `None` when there were none to remove.

    SURGERY (`_with_section`): only the section that holds what was asked is replaced, and the
    sections a refine derived from it are removed. Everything else on the card stays as it was."""
    from openfactory.adapters.tracker.parse import parse_ticket_body

    heading = _WHAT_WAS_ASKED[kind]
    old = _section_of(body, heading)
    old_text = old.split("\n", 1)[1].strip() if "\n" in old else ""
    after = _with_section(body, heading, f"## {heading}\n\n{text.strip()}")
    removed: int | None = None
    if any(_section_of(after, section) for section in _REFINED_FROM_THE_TEXT):
        removed = len(parse_ticket_body(id="", title="", body=body, repo="").acceptance_criteria)
        for section in _REFINED_FROM_THE_TEXT:
            after = _without_section(after, section)
    return after, old_text, removed


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


#: The heading `authoring.defect_body` writes over the promise a defect breaks. A HEADING, matched
#: as a whole line: a defect filed before its `## Source` existed cites its requirement here and
#: nowhere else, and it is as much a card of that requirement as one filed from it (#265 §6.1).
_DEFECT_CITES_RE = re.compile(r"^## A promessa violada — REQ-(\d{4})\s*$", re.MULTILINE)


def _cited_requirement(body: str) -> int | None:
    """The requirement a card says it EXECUTES, read from its own `## Source` section — or, for a
    defect, from the heading naming the promise it breaks.

    Only from there. A number in the objective is prose — somebody explaining themselves — while
    the Source line is the one an executor is told not to go beyond, and repointing on a mention
    would rewrite cards nobody claimed were derived from anything. The defect's heading is the
    same kind of line: the platform wrote it, over the one requirement the fix must restore."""
    m = _CITES_RE.search(_section_of(body or "", "Source"))
    if m:
        return int(m.group(1))
    m = _DEFECT_CITES_RE.search(body or "")
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

    who = actor or "o time"
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

    who = actor or "o time"
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

    who = f", a pedido de {actor}" if actor else ""
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


#: A card is a card: a request and a defect asked for the same thing are one piece of work, and
#: the second of them is linked to the first rather than filed beside it.
_CARD_KINDS = ("ticket", "defect")


def _saved_in_the_repository(result: WriteResult) -> tuple[str, str] | None:
    """What a write to the context repository saved, for the product's write sequence — or None
    when it saved nothing new (refused, or already there)."""
    return (result.ref, result.url) if result.ok and not result.existed else None


def _saved_on_the_board(result: WriteResult) -> tuple[str, str] | None:
    """The card a filing opened — its ref and where a person follows it — or None."""
    return (result.ref, result.url) if result.ok and not result.existed else None


def _the_card_just_asked_for(item) -> WriteResult:
    """A card saved moments ago in another conversation, answered AS this filing: nothing new is
    opened, the person is linked to it, and nothing about who asked travels (ADR-0051 D9)."""
    return WriteResult(ok=True, existed=True, just_asked=True, ref=item.ref, url=item.url)


def _req_number(ref: str) -> int:
    """`REQ-0041` → 41; 0 when the ref carries no number."""
    digits = re.sub(r"[^0-9]", "", str(ref or ""))
    return int(digits) if digits else 0


def _as_ticket_number(ref) -> int:
    """A ref as a number, or 0 when it carries none.

    Kept returning 0 for its existing callers, which compare against it. `ref_number` is the
    honest primitive — it returns None, because 0 reads as a real issue number all the way down —
    and this is the thin shim for the call sites that still expect the old contract (C-05)."""
    from openfactory.contracts.refs import ref_number

    return ref_number(ref) or 0
