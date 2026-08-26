"""When the platform promises something and cannot deliver it, somebody is told — with a name.

THE CONVERSATION THAT CAUSED THIS. The product role spent a morning telling a client, in message
after message, that it could not open the documents or the code — and asking THE CLIENT to restore
its access. The product owner read it and named three things at once:

    *"a PO saying that to the client makes no sense… stuck in a loop with the client, nobody
    resolves anything, nobody knows what is going on… right here and now I am watching, but if this
    were a client, she should be asking the FACTORY for help."*

All three were right. The honesty was correct and the ADDRESSEE was wrong: the person who bought
"no dev needed" was handed a support ticket he could not work. And the degradation existed nowhere
else — no log a human reads, no owner, no state — so the only reason anybody noticed is that he
happened to be watching.

WHY A TICKET, AND NOT A LINE IN THE OPERATORS' CHANNEL. A chat message has no owner, no state and
no history; it scrolls away and the stall is silent again, which is the single failure this
platform exists to make impossible. A ticket closes.

WHY NOT THE CLIENT'S BOARD. A client's board carries the client's product (ADR-0027) — eleven
smoke-test tickets already shipped eleven dead endpoints into one, and a platform failure is not
product work. So: the factory's own board, declared per deployment.

WHAT CLOSES ONE. Observation, never self-report (ADR-0021), and the same rule the platform applies
to every other loop it keeps. Nobody marks an impediment resolved: the next time the capability
WORKS, the ticket closes itself, with the evidence in the comment. An operator who fixed it
silently and a fix that never happened must not look alike.
"""

from __future__ import annotations

import logging

from openfactory.util.bounded import BoundedDict

log = logging.getLogger("openfactory.ops")

#: What we last OBSERVED about each `(project, cause)` — True = working, False = broken.
#:
#: THIS RUNS ON THE PATH OF EVERY CLIENT MESSAGE, and both entry points below start with a
#: `find_ticket` lookup. Without this the healthy case — which is almost every case — would spend
#: one forge API call per capability per message, against the SAME App quota the poller and the
#: jobs draw on. A board read once cost 303 GraphQL points per call in this codebase and took the
#: whole factory over its hourly ceiling; the reflex to avoid is paying per message for a fact that
#: changes once a week.
#:
#: So the network is touched only on a TRANSITION. An unknown state (a fresh worker) counts as a
#: transition on purpose: an impediment opened before the restart still has to be able to close.
#:
#: AN ENTRY IS WRITTEN ONLY AFTER THE FORGE CALL IT STANDS FOR HAS RETURNED. This records what the
#: board was OBSERVED to hold, never what was attempted against it — the two look identical here and
#: the cost of confusing them is total. A create that raised and was remembered as "known broken"
#: suppresses that impediment for the LIFE of the worker: nothing is ever filed, nothing says so
#: again, and the client keeps being told the team was warned. A close that raised and was
#: remembered as "working" leaves the ticket open with nothing left to close it. A forge that keeps
#: refusing therefore costs one attempt per message until it lands, which is the price of the only
#: alternative on offer: an impediment nobody ever hears about.
_LAST: BoundedDict[str, bool] = BoundedDict(256)

#: Known causes. A CLOSED SET on purpose: the title is derived from the cause, dedup is by title,
#: and a free-form string would file a new ticket for every wording of the same trouble — the
#: opposite of a history somebody can count.
PRODUCT_NO_CODE = "product-no-code"
PRODUCT_MOUNT_EMPTY = "product-mount-empty"
PRODUCT_CORPUS_UNREADABLE = "product-corpus-unreadable"
PRODUCT_BOARD_UNREADABLE = "product-board-unreadable"
PRODUCT_CANNOT_WRITE = "product-cannot-write"

#: cause → what the ticket is called. Written for a person opening a board, not for a grep: the
#: title is what a supervisor scans, and "product-mount-empty" tells them nothing they can act on.
#:
#: AND IT IS AN IDENTITY, WHICH IS WHY IT IS NOT TRANSLATED (#124). `title_for` is the DEDUP KEY —
#: `find_ticket(title=…)` matches EXACTLY, by contract, and that exactness is the whole mechanism:
#: the platform derives the string from a closed set of causes so the second occurrence finds the
#: first. Put this table in a phrasebook and a deployment that changes its language stops
#: recognising its own open tickets and files a fresh duplicate on every occurrence, for ever —
#: silently, because a create that succeeds looks exactly like a create that was needed.
#:
#: So the split is deliberate: the TITLE is identity and stays in one language, and the BODY —
#: `_body` below — is where the explanation lives and where a language may be chosen. A supervisor
#: still reads a sentence rather than a slug; they just read it in the identity's language.
#:
#: These were Portuguese until 2026-08-16 and are English now, which re-files any impediment
#: ticket open at that moment ONCE. Measured before changing: no deployment has a factory board
#: configured today, so the cost is zero and would not have stayed that way.
_TITLES = {
    PRODUCT_NO_CODE: "the product agent cannot open the product's code",
    PRODUCT_MOUNT_EMPTY: "what is mounted for the product agent is empty",
    PRODUCT_CORPUS_UNREADABLE: "the product's requirements cannot be read",
    PRODUCT_BOARD_UNREADABLE: "the work board cannot be read",
    PRODUCT_CANNOT_WRITE: "a write by the product agent failed",
}

#: What every impediment says about itself, so a supervisor opening it cold knows what it costs and
#: how it ends without reading this module — IN THE DEPLOYMENT'S OWN LANGUAGE (#160). The split
#: this module argues for above is exactly this: the title is identity and never moves, the body is
#: the explanation and follows the language. It was welded Portuguese until this card.
def _preamble(language: str | None) -> str:
    from openfactory.techlead import voice as tl_voice

    return tl_voice.say(tl_voice.NARRATION, "ops.impediment.preamble", language)


def title_for(project: str, cause: str) -> str:
    """The ticket's title — DETERMINISTIC, because it is also the dedup key.

    Exact-title matching is the wrong tool when a model writes the title (two wordings of one idea
    become two cards, which is how #511 duplicated #288). It is exactly the right tool here: the
    platform derives this from a closed set of causes, so the same trouble always produces the same
    string and the second occurrence finds the first.

    WHICH ALSO MEANS IT IS NOT PROSE (#124). Nothing in this string may follow a project's
    configured language — see `_TITLES`. The human explanation belongs in `_body`."""
    return f"[openfactory] {project}: {_TITLES.get(cause, cause)}"


def _board(project):
    return getattr(project, "factory_board", None)


def _tracker_for(project, tracker):
    """The factory's tracker, or None when this deployment has not declared a board.

    None is a configuration, not a failure — but it is SAID, once per cause, because a deployment
    silently discarding its own impediments is the state this module exists to end."""
    if tracker is not None:
        return tracker
    board = _board(project)
    if board is None or board.tracker is None:
        return None
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.credentials import tracker_token
    from openfactory.factory import _bot_token_provider

    # THE SAME SEAM, POINTED SOMEWHERE ELSE — a project whose `tracker` is the factory's board.
    # Building it this way rather than by hand is what keeps the vendor-agnosticism literal: a
    # deployment that keeps its tickets in Jira files its impediments in Jira, through the
    # dispatch that already exists, without a line of code here knowing that.
    return build_tracker(project.model_copy(update={"tracker": board.tracker}),
                         token=tracker_token(), token_provider=_bot_token_provider())


def report(project, cause: str, detail: str = "", *, tracker=None) -> str:
    """Open (or leave open) the impediment for `cause`. Returns its ref, or "".

    NEVER RAISES AND NEVER BLOCKS THE REPLY. This runs on the path of a client's message: an
    impediment that cost somebody their answer would be a worse bug than the one it reports.

    Idempotent by title, so a capability broken for an hour produces ONE ticket and not one per
    message — the difference between a history and a flood. A second occurrence adds nothing: the
    ticket is already open and already says the same thing.
    """
    name = getattr(project, "name", "?")
    if _LAST.get(f"{name}|{cause}") is False:
        return ""          # already known broken; the ticket is open and already says this
    try:
        trk = _tracker_for(project, tracker)
        if trk is None:
            log.warning("OPENFACTORY_OPS_NO_BOARD project=%s cause=%s — this deployment "
                        "declares no "
                        ""
                        ""
                        "factory board, so the impediment has nowhere to go and only this line "
                        "records it: %s", name, cause, detail[:200])
            return ""
        title = title_for(name, cause)
        existing = trk.find_ticket(title=title)
        if existing:
            _LAST[f"{name}|{cause}"] = False      # the board HAS it; a repeat adds nothing
            log.info("OPENFACTORY_OPS_STILL_OPEN project=%s cause=%s ref=%s", name, cause, existing)
            return str(existing)
        board = _board(project)
        ref = trk.create_ticket(
            title=title,
            body=_body(name, cause, detail, board, getattr(project, "language", None)))
        _LAST[f"{name}|{cause}"] = False          # after the create, so a refused one is retried
        _label_and_assign(trk, ref, board, project)
        log.error("OPENFACTORY_OPS_IMPEDIMENT_FILED project=%s cause=%s ref=%s — %s",
                  name, cause, ref, detail[:200])
        return str(ref)
    except Exception as exc:  # noqa: BLE001 — reporting trouble must never become trouble
        log.warning("OPENFACTORY_OPS_REPORT_FAILED project=%s cause=%s (%s) — the impediment is in "
                    "this "
                    "log line and nowhere else", name, cause, str(exc)[:160])
        return ""


def resolved(project, cause: str, evidence: str = "", *, tracker=None) -> bool:
    """Close the impediment for `cause` because the capability WORKED. True when one was closed.

    The evidence goes in as a comment before the close, so the record says what made it better
    rather than only that somebody thought it was.

    Costs NOTHING on the ordinary path: a capability already observed working is skipped without
    touching the network. Only the first observation after a restart, and every real transition,
    reaches the forge.
    """
    name = getattr(project, "name", "?")
    if _LAST.get(f"{name}|{cause}") is True:
        return False       # already observed working; nothing is open, so nothing to close
    try:
        trk = _tracker_for(project, tracker)
        if trk is None:
            return False
        existing = trk.find_ticket(title=title_for(name, cause))
        if not existing:
            _LAST[f"{name}|{cause}"] = True       # nothing open — the ordinary path, and it is free
            return False
        if evidence:
            from openfactory.techlead import voice as tl_voice

            trk.comment(str(existing),
                        tl_voice.say(tl_voice.NARRATION, "ops.impediment.closed",
                                     getattr(project, "language", None),
                                     evidence=evidence[:400]))
        trk.close_ticket(str(existing), "completed")
        _LAST[f"{name}|{cause}"] = True           # after the close, so a refused one is retried
        log.warning("OPENFACTORY_OPS_IMPEDIMENT_CLOSED project=%s cause=%s ref=%s — the capability "
                    "worked again", name, cause, existing)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("OPENFACTORY_OPS_CLOSE_FAILED project=%s cause=%s "
                    "(%s)", name, cause, str(exc)[:160])
        return False


def _body(project: str, cause: str, detail: str, board, language: str | None = None) -> str:
    from openfactory.techlead import voice as tl_voice

    supervisor = getattr(board, "supervisor", "") if board else ""
    owner = (f"@{supervisor}" if supervisor
             else tl_voice.say(tl_voice.NARRATION, "ops.impediment.no-owner", language))
    return tl_voice.say(
        tl_voice.NARRATION, "ops.impediment.body", language,
        preamble=_preamble(language), project=project, cause=cause, owner=owner,
        detail=detail or tl_voice.say(tl_voice.NARRATION, "ops.impediment.no-detail", language))


def _label_and_assign(trk, ref: str, board, project) -> None:
    """Best-effort decoration. A ticket that exists without its label is findable and useful; one
    that failed to be created is not — so neither of these may undo the filing."""
    label = getattr(board, "label", "") if board else ""
    if label:
        try:
            trk.add_label(str(ref), label)
        except Exception as exc:  # noqa: BLE001
            log.info("could not label the impediment %s (%s)", ref, exc)
    supervisor = getattr(board, "supervisor", "") if board else ""
    if supervisor:
        try:
            trk.set_assignees(str(ref), [supervisor])
        except Exception as exc:  # noqa: BLE001
            # SAID, not swallowed: an unassigned impediment is one nobody is accountable for, and
            # that is the exact state this module was written to end.
            log.warning("OPENFACTORY_OPS_UNASSIGNED ref=%s supervisor=%s (%s) — nobody is named on "
                        "it",
                        ref, supervisor, exc)
