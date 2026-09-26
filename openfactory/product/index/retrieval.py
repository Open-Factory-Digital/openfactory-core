"""The engine retrieves; the role reads files; `[[BUSCA: …]]` asks for more (#269 slice 2, ADR-0053
D8, D12).

BEFORE THE TURN, the engine searches the product's memory from the message — and, when the message
is too short to search on ("e o segundo?"), from the lines before it — and writes the hits, each
with its citation, as a file in the role's facts pack: `found/before-the-turn.md`, listed by the
manifest beside `board.md` and `decisions.md` (ADR-0041: facts are files). THAT SEARCH NEVER
INCLUDES A LINE SAID IN A GROUP TO SOMEBODY ELSE (D12): what was not addressed to the role is
searchable, and is never put in front of it by a search nobody asked for.

WHEN THE ROLE NEEDS MORE, it writes `[[BUSCA: <what to look for>]]` and nothing else; the engine
searches, writes `found/search-<round>.md`, and asks again with the prompt it asked the first time
and a note naming the file (`role.py::ProductRole._searched`). Text the model writes, on every
harness — no tool protocol. An explicit search MAY return unaddressed group lines, as cited hits
marked as such: somebody asked for it. Bounded: `role.SEARCH_ROUNDS` rounds a turn, a few
searches a round.

EVERY SEARCH IS RECORDED (D8): who formulated it — the engine or the role — the query, the hits
(their ids, sources, dates and standing, never their text) and the conversation, as a digest, in
`<product_state_dir>/searches.jsonl`. A wrong answer is then traceable to what was found. The query
is a person's words, so the record keeps the transcript's retention (`RETENTION_DAYS`) and forgets
past it. A log line per search carries the counts and never the words.

A PRIVATE CONVERSATION'S LINES COME BACK ONLY TO IT, and a room is searched for everybody in it: the
audience is the turn's (`documents/record.py::turn_audience`), and a pack another conversation's
turn may read — the degraded shared view — is searched as a room, with no private lines at all.

A SWITCH FOR THE BATTERY'S TWO ARMS (ADR-0053, *What would make it wrong*): retrieval's cost per
turn is measured with it and without it, so `OPENFACTORY_PRODUCT_RETRIEVAL=off` turns the step off
— no search before the turn, no marker offered — and the answer is the prompt as it was.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openfactory.contracts.document import INTERNAL
from openfactory.product.index.items import (
    CARD,
    CLOSED,
    DECISION,
    DISTILLATE,
    DOCUMENT,
    DROPPED,
    REQUIREMENT,
    TURN,
    UNREADABLE,
    conversation_digest,
)
from openfactory.product.index.search import Found, Hit, Query, search
from openfactory.product.index.store import Index
from openfactory.product.index.sync import EMBED_PER_TURN, Synced, sync

log = logging.getLogger("openfactory.product.index")

SWITCH_ENV = "OPENFACTORY_PRODUCT_RETRIEVAL"

#: The files a turn's searches are written as, under the facts pack's `found/`.
FOUND_DIR = "found"
BEFORE = "before-the-turn.md"

#: Who formulated a search, as the record says it: the engine before a turn, the role through
#: its marker, and the "done before?" check (#269 slice 3, ADR-0053 D7) — the engine's too, for
#: the check before anything is drafted or written.
ENGINE, ROLE, DONE_BEFORE = "engine", "role", "done-before"

#: A message with fewer words worth searching than this is searched with the lines before it.
MIN_WORDS = 3
#: How much of the query the rendered file repeats, and how much of a history item it quotes.
QUERY_CHARS = 300
HISTORY_EXCERPT = 300

SEARCHES_FILE = "searches.jsonl"
#: How long a search record waits for the file's lock before it appends without it.
RECORD_WAIT_SECONDS = 10.0


def enabled() -> bool:
    return (os.environ.get(SWITCH_ENV) or "").strip().lower() not in ("off", "0", "false", "no")


def embedder():
    """`(row, "")` or `(None, why)` — the deployment's embedder, built once per process."""
    from openfactory.adapters.embed.registry import for_the_index

    return for_the_index()


# ── the index, brought up to date ───────────────────────────────────────────────────────────────

def said_of(project) -> list:
    """The product's conversation lines as its recall index holds them — refreshed by this very
    turn a moment earlier (`engine._with_elsewhere`), read here as it stands."""
    from openfactory.memory.recall import CONVERSATION, INDEX_FILE, MemoryIndex, Said
    from openfactory.paths import project_memory_dir

    held = MemoryIndex.load(Path(project_memory_dir(project)) / INDEX_FILE,
                            str(getattr(project, "name", "") or ""))
    out = []
    for row in held.rows.values():
        if row.get("store") != CONVERSATION:
            continue
        try:
            out.append(Said(**row))
        except TypeError:
            continue
    return out


def refresh(project, *, corpus=None, requirements_dir: str = "requirements", cards=None,
            said=None, embed_limit: int | None = EMBED_PER_TURN) -> Synced:
    """The product's index brought up to what this caller has read: its document records always,
    and the corpus, the board and the conversations when handed."""
    from openfactory.product.documents.store import Store
    from openfactory.product.key import product_key

    key = product_key(project)
    row, why = embedder()
    return sync(Index(key), records=Store(key), corpus=corpus, requirements_dir=requirements_dir,
                cards=cards, member=str(getattr(project, "name", "") or ""), said=said,
                embedder=row, degraded=why, embed_limit=embed_limit)


# ── the searches ────────────────────────────────────────────────────────────────────────────────

def _said_before(conversation: str) -> str:
    """The last two lines of the conversation block the turn was handed — `who: text` lines under
    its first heading, the recall block after it left out."""
    lines: list[str] = []
    for line in str(conversation or "").splitlines()[1:]:
        if line.startswith("## "):
            break
        if line.strip():
            lines.append(line.split(": ", 1)[-1].strip())
    return "\n".join(lines[-2:])


def query_of(question: str, conversation: str = "") -> str:
    """What the engine searches for before a turn: the message, and when the message is too short
    to carry its subject, the lines before it."""
    from openfactory.memory.recall import tokens

    if len(tokens(question)) >= MIN_WORDS:
        return question
    return f"{question}\n{_said_before(conversation)}".strip()


def run(project, query: Query, *, by: str, conversation: str, round_: int = 0) -> Found:
    """One search of `project`'s product, recorded."""
    from openfactory.product.key import product_key

    key = product_key(project)
    row, why = embedder()
    found = search(Index(key), query, embedder=row, degraded=why)
    record(key, by=by, found=found, conversation=conversation, round_=round_)
    return found


def before_the_turn(project, *, question: str, said: str = "", audience: str = INTERNAL,
                    conversation: str = "", own: bool = True) -> tuple[Found, str]:
    """The engine's search before a turn, and the file it becomes. `own` is whether the pack is
    this turn's alone: when it is not, the search is a room's — no private line at all."""
    # A PACK OTHERS MAY READ keeps every document — the product's, everybody's (the product
    # owner's decision of 2026-09-25) — and no private line: those stay their person's
    query = Query(text=query_of(question, said), audience=audience,
                  own=conversation if own else "", exclude=conversation, overheard=False)
    found = run(project, query, by=ENGINE, conversation=conversation)
    text = render(found, heading="before this turn", by=ENGINE)
    _measured(project, ENGINE, [found], text)
    return found, text


#: What "was this done before?" reads (ADR-0053 D7): the requirements whatever became of them, the
#: decisions of their registers and the ones a model read in a document, the closed cards of any
#: age, the documents, and the distilled conversations. Never a raw line of a conversation — the
#: recall block already brings those, and a line is not a request.
DONE_BEFORE_KINDS = (REQUIREMENT, DECISION, CARD, DOCUMENT, DISTILLATE)


def done_before(project, text: str, *, audience: str = INTERNAL, conversation: str = "",
                own: bool = True) -> Found:
    """THE "DONE BEFORE?" SEARCH (#269 slice 3, ADR-0053 D7): what the product's whole memory holds
    that may be the thing asked for now — searched from the request itself, with the turn's scope,
    and recorded like every search. Before any lock: the search refuses to run under the product's
    semaphore (`search.py`), and what it finds is weighed by the role before anything is staged."""
    query = Query(text=text, audience=audience,
                  own=conversation if own else "", overheard=False, kinds=DONE_BEFORE_KINDS)
    return run(project, query, by=DONE_BEFORE, conversation=conversation)


def _measured(project, by: str, founds: list[Found], text: str) -> None:
    """ONE LINE PER FILE WITH ITS SIZE — what retrieval costs a turn, which ADR-0053 says must be
    measured, not assumed; the battery reads it beside the briefing's, as its two arms differ."""
    log.info("OPENFACTORY_PRODUCT_FOUND project=%s by=%s searches=%d hits=%d history=%d chars=%d",
             getattr(project, "name", "?"), by, len(founds), sum(len(f.hits) for f in founds),
             sum(len(h.history) for f in founds for h in f.hits), len(text))


def for_the_role(project, queries: list[str], *, round_: int, audience: str = INTERNAL,
                 conversation: str = "", own: bool = True) -> tuple[list[Found], str]:
    """The role's `[[BUSCA: …]]` searches of one round, and the file they become. Asked for, so a
    line said in a group to somebody else may be a hit (D12) — cited, and marked."""
    founds = [run(project, Query(text=q, audience=audience,
                                 own=conversation if own else "", overheard=True),
                  by=ROLE, conversation=conversation, round_=round_) for q in queries]
    parts = [render(found, heading=f"your search {round_}.{n}", by=ROLE)
             for n, found in enumerate(founds, start=1)]
    text = "\n\n".join(parts)
    _measured(project, ROLE, founds, text)
    return founds, text


# ── what the role reads ─────────────────────────────────────────────────────────────────────────

_STANDING = {
    CLOSED: "a closed card",
    DROPPED: "DROPPED — decided against, and nothing replaced it: history, not what holds today",
    UNREADABLE: "EXISTS AND COULD NOT BE READ — say that it exists and could not be read; never "
                "that it is absent or says nothing",
}


def _label(hit: Hit) -> str:
    if hit.kind == REQUIREMENT:
        return hit.title
    if hit.kind == DECISION:
        return (f"{hit.title} — a decision in its register" if hit.number is not None
                else f"a decision read in \"{hit.title}\"")
    if hit.kind == CARD:
        return f"card {hit.title}"
    if hit.kind == TURN:
        return f"said in {hit.source}"
    if hit.kind == DISTILLATE:
        return hit.title or "a conversation, distilled"
    return hit.title or hit.source


def _where(hit: Hit) -> str:
    where = (f"`{hit.source}`" if hit.kind in (DOCUMENT, DECISION, REQUIREMENT, DISTILLATE)
             else hit.source)
    return f"{where}, {hit.locator}" if hit.locator else where


def _dated(hit: Hit) -> str:
    if not hit.date:
        return "undated"
    return f"{hit.date}" + (f" ({hit.date_from})" if hit.date_from else "")


def _quote(text: str, limit: int) -> list[str]:
    body = " ".join(str(text or "").split())
    if len(body) > limit:
        body = body[:limit].rsplit(" ", 1)[0] + " …"
    return [f"> {body}"] if body else []


def _name(hit: Hit) -> str:
    """A hit named in one breath — `REQ-0009`, `card #731`, the document's title and kind."""
    if hit.number is not None:
        return f"REQ-{hit.number:04d}"
    if hit.kind == CARD:
        return f"card {hit.title.split(' — ')[0]}"
    if hit.kind == TURN:
        return "a line of a conversation"
    if hit.kind == DISTILLATE:
        return f"a conversation distilled on {hit.date or 'an unknown date'}"
    return f"\"{hit.title}\" ({hit.origin.split(',')[0].split(' — ')[0]})"


def _timeline(hit: Hit) -> str:
    """ADR-0053 D3's answer, in order: what was decided when, what replaced it, what holds."""
    steps = [f"{h.date or 'undated'} {_name(h)}" for h in hit.history]
    steps.append(f"{hit.date or 'undated'} {_name(hit)}")
    return " → ".join(steps) + f". What holds today: {_name(hit)}."


def _hit_lines(n: int, hit: Hit) -> list[str]:
    lines = [f"## {n}. {_label(hit)}", "", f"- where: {_where(hit)}", f"- dated: {_dated(hit)}",
             f"- read from: {hit.origin}"]
    if hit.status in _STANDING:
        lines.append(f"- status: {_STANDING[hit.status]}")
    elif hit.kind == TURN:
        lines.append("- status: evidence of what was said — never name who said it")
    elif hit.kind == DISTILLATE:
        lines.append("- status: a model's reading of a conversation — evidence of what was said, "
                     "agreed or asked, with its date; never a requirement or a decision of the "
                     "product, and never name who said it")
    elif hit.number is not None:
        lines.append("- status: holds today" if hit.kind == REQUIREMENT else
                     f"- status: holds today — a decision in the register of "
                     f"REQ-{hit.number:04d}")
    else:
        lines.append("- status: current evidence — nothing it cites was superseded")
    if hit.kind == TURN and not hit.addressed:
        lines.append("- said in a group to somebody else, not to you: found because a search "
                     "asked for it — never treat it as said to you")
    if hit.pulled:
        lines.append("- not matched by the words searched: listed because it replaced what "
                     "matched")
    if hit.history:
        lines.append(f"- timeline: {_timeline(hit)}")
    lines += ["", *_quote(hit.text, 700)]
    if hit.history:
        lines += ["", "### What it replaced — history, never what holds today", ""]
        for old in hit.history:
            lines.append(f"- SUPERSEDED · {_label(old)} · {_where(old)} · {_dated(old)} · "
                         f"{old.origin}")
            lines += [f"  {q}" for q in _quote(old.text, HISTORY_EXCERPT)]
    return lines


def render(found: Found, *, heading: str, by: str = ENGINE) -> str:
    """One search as the file the role opens — every hit with where it is, its date and where the
    date came from, how it was read, and its standing; every superseded item under what replaced
    it; and, first, whether the search could look by meaning at all."""
    who = ("The engine searched the product's memory for this message before you were asked"
           if by == ENGINE else "The engine ran the search you asked for")
    lines = [f"# Found in the product's memory — {heading}", "",
             f"{who}: its documents, its requirements and the decisions recorded in them, its "
             f"closed cards, its other conversations and what they were distilled into. "
             f"{len(found.hits)} hit(s), best first, out of the {found.searched} item(s) this "
             f"conversation may search.", "",
             f"Searched for: \"{' '.join(found.query.text.split())[:QUERY_CHARS]}\"", ""]
    if found.degraded:
        lines += [f"SEMANTIC SEARCH IS OFF OR PARTIAL: {found.degraded}. What is here was found "
                  f"by its exact words, its metadata and its dates — something said in other "
                  f"words may be missing: say you could not find it, never that it does not "
                  f"exist.", ""]
    else:
        lines += [f"Found by exact words, by meaning ({found.embedder}), by metadata and by "
                  f"date.", ""]
    lines += ["How to read a hit: each says where it is, the date it carries and where that date "
              "came from, and how it was read. A document is EVIDENCE — what somebody wrote, on a "
              "day; a requirement is what was agreed. A SUPERSEDED item is listed only under what "
              "replaced it — when you mention it, give the timeline and say what holds today. A "
              "decision \"read by a model\" is a model's summary of a document: cite the "
              "document. Never name a person from another conversation.", ""]
    if not found.hits:
        lines += ["Nothing matched. That is what this search found — not proof that nothing "
                  "exists: say you could not find it.", ""]
    for n, hit in enumerate(found.hits, start=1):
        lines += [*_hit_lines(n, hit), ""]
    if found.withheld:
        lines += [f"{found.withheld} superseded item(s) matched whose replacement this "
                  f"conversation cannot be shown: they are not listed, because a superseded item "
                  f"is only ever shown beside what replaced it.", ""]
    return "\n".join(lines).rstrip() + "\n"


# ── the record ──────────────────────────────────────────────────────────────────────────────────

def searches_path(key: str) -> Path:
    from openfactory.paths import product_state_dir

    return product_state_dir(key) / SEARCHES_FILE


def _entry(hit: Hit) -> dict:
    return {"id": hit.id, "kind": hit.kind, "source": hit.source, "locator": hit.locator,
            "date": hit.date, "status": hit.status, "pulled": hit.pulled,
            "history": [h.id for h in hit.history]}


def record(key: str, *, by: str, found: Found, conversation: str = "", round_: int = 0,
           now: datetime | None = None) -> None:
    """Append one search to the product's record, and forget what is past retention. Never raises:
    a record that could not be written is an ERROR line, and the search still answers."""
    from openfactory.memory.transcript import RETENTION_DAYS
    from openfactory.util.filelock import Waited, lock_beside

    when = now or datetime.now(UTC)
    line = json.dumps({
        "ts": when.isoformat(timespec="seconds"), "by": by, "round": round_,
        "query": found.query.text, "conversation": conversation_digest(conversation),
        "audience": found.query.audience, "overheard": found.query.overheard,
        "degraded": found.degraded, "embedder": found.embedder, "searched": found.searched,
        "withheld": found.withheld, "hits": [_entry(h) for h in found.hits]},
        ensure_ascii=False, sort_keys=True)
    path = searches_path(key)
    cutoff = (when - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
    lock = lock_beside(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock.acquire(timeout=RECORD_WAIT_SECONDS)
        except Waited:
            log.error("OPENFACTORY_PRODUCT_SEARCH_RECORD_UNLOCKED product=%s — appended without "
                      "the record's lock", key)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            return
        try:
            _forget_old(path, cutoff)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        finally:
            lock.release()
    except OSError as exc:
        log.error("OPENFACTORY_PRODUCT_SEARCH_UNRECORDED product=%s by=%s (%s)", key, by, exc)
        return
    log.info("OPENFACTORY_PRODUCT_SEARCH product=%s by=%s round=%d hits=%d withheld=%d "
             "degraded=%s", key, by, round_, len(found.hits), found.withheld,
             "yes" if found.degraded else "no")


def forget_conversation(key: str, conversation: str) -> int:
    """Drop the searches made in conversation `conversation` from the product's record — each
    carries the person's words as its query (#335). Under the record's lock; RAISES `Waited`."""
    from openfactory.util.filelock import lock_beside, replace_atomically

    path = searches_path(key)
    digest = conversation_digest(conversation)
    if not digest or not path.is_file():
        return 0
    lock = lock_beside(path)
    lock.acquire(timeout=RECORD_WAIT_SECONDS)
    try:
        kept, gone = [], 0
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                mine = str(json.loads(raw).get("conversation", "")) == digest
            except ValueError:
                mine = False
            if mine:
                gone += 1
            else:
                kept.append(raw)
        if gone:
            replace_atomically(path, "".join(f"{raw}\n" for raw in kept))
        return gone
    finally:
        lock.release()


def _forget_old(path: Path, cutoff: str) -> None:
    """Rewrite the record without the searches older than `cutoff` — only when its oldest line is,
    which one line's read answers."""
    from openfactory.util.filelock import replace_atomically

    try:
        with path.open(encoding="utf-8") as handle:
            first = handle.readline()
    except FileNotFoundError:
        return
    try:
        oldest = str(json.loads(first).get("ts", ""))
    except ValueError:
        oldest = ""
    if oldest and oldest >= cutoff:
        return
    kept = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            if str(json.loads(raw).get("ts", "")) >= cutoff:
                kept.append(raw)
        except ValueError:
            continue
    replace_atomically(path, "".join(f"{raw}\n" for raw in kept))


def forget_conversations(key: str, projects=()) -> int:
    """EVERYTHING DERIVED FROM THE PRODUCT'S CONVERSATIONS, DELETED — the other half of a deletion
    request (`openfactory project forget-conversations`, ADR-0053 D6): the lines the product's
    index holds, the search record (its queries are a person's words), and each registry project's
    recall index, which the index's sync reads its lines from and would read them back from. All
    three are derived: the next turn rebuilds them from a store that no longer holds the rows.
    Returns how many lines the index held."""
    from openfactory.memory.recall import INDEX_FILE
    from openfactory.paths import project_memory_dir

    projects = list(projects)
    gone = 0
    index = Index(key)
    if index.path.exists():
        with index.open() as con:
            lines = list(Index.groups(con, "turn:"))
            with con:
                Index.drop_groups(con, lines)
        gone = len(lines)
    searches_path(key).unlink(missing_ok=True)
    for project in projects:
        (Path(project_memory_dir(project)) / INDEX_FILE).unlink(missing_ok=True)
    log.warning("OPENFACTORY_PRODUCT_INDEX_FORGOT product=%s lines=%d — the index's conversation "
                "lines, the search record and %d recall index(es), on a deletion request", key,
                gone, len(projects))
    return gone


def recorded(key: str) -> list[dict]:
    """Every search the product's record holds, oldest first — what a test and an operator read."""
    try:
        text = searches_path(key).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    out = []
    for raw in text.splitlines():
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


__all__ = [
    "BEFORE", "DONE_BEFORE", "ENGINE", "FOUND_DIR", "ROLE", "SWITCH_ENV", "before_the_turn",
    "done_before", "embedder", "enabled", "for_the_role", "forget_conversations", "query_of",
    "record", "recorded", "refresh", "render", "run", "said_of",
]
