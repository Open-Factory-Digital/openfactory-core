"""A typed `Case` per conversation — the intake as state, not as a re-reading (#33, hole 7).

MULTI-TURN INTAKE HAD NOWHERE TO LIVE. The staged proposal is one slot per conversation with a
two-hour expiry: it holds a DRAFT awaiting a yes, and nothing before it. "What did you expect?
Which screen? Can you reproduce it?" over four turns had no typed state — the model re-derived
the intake from the transcript every turn, and in a busy room a second proposal displaced the
first in silence (`staging.remember` admits it in a sentence). The `Case` is that state:

    collecting  →  proposed  →  confirmed  →  filed
         ↘ dropped (a no, an expiry, a displacement)

opened by one person in one conversation, carrying what they said (`facts`), what the role asked
back (`asked`), the kind the role read (`kind`), the draft once staged, and the result once
written. The role gets it beside the conversation as "this intake so far", so it asks only what
is still missing instead of starting over; a displaced case goes back to collecting with its
facts kept, which is the loss the room used to take.

WHERE IT LIVES. In process, like `staging._PENDING`, and mirrored to the project's memory
directory (`paths.project_memory_dir`) as one JSON file — the installation's derived state, the
same home the recall index has. The staging keeps its own durable mirror (the panel's pending
questions); a case is not a question to anybody, so it does not go there.

THE HOOKS ARE INSIDE THE STAGING, NOT IN EVERY BRANCH THAT STAGES. Twelve branches of the channel
call `remember`; one hook in `remember`, one in `consume`, one in `forget` and one in `confirm`
move every case — the rule that a state machine nobody has to remember to call is the only kind
that stays true.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, Field

from openfactory.util.bounded import BoundedDict

log = logging.getLogger("openfactory.product.case")

COLLECTING = "collecting"
PROPOSED = "proposed"
CONFIRMED = "confirmed"
FILED = "filed"
DROPPED = "dropped"
OPEN_STATES = frozenset({COLLECTING, PROPOSED, CONFIRMED})

#: How long an intake stays open without a word. A day: a person who asked something at 17:00 and
#: answers the role's question at 09:00 is still in the same intake; a week later they are not.
CASE_TTL_SECONDS = 24 * 60 * 60
#: How many cases one project keeps in memory — a cap, not a policy (`staging._MAX_PENDING`).
_MAX_CASES = 500
CASES_FILE = "cases.json"
_FACT_MAX = 400
_ASKED_MAX = 200

#: One bucket per project this worker has touched — bounded like every module-level cache here
#: (`test_no_unbounded_growth`): the projects a worker serves are the registry's, not traffic's,
#: and each bucket is itself capped at `_MAX_CASES`.
_CASES: BoundedDict[str, dict[str, Case]] = BoundedDict(64)
_LOADED: BoundedDict[str, bool] = BoundedDict(64)
#: which project a conversation key belongs to — `forget(thread)` knows no project, and a thread
#: key names one conversation; bounded because a worker's live conversations are, too
_THREAD_PROJECT: BoundedDict[str, str] = BoundedDict(512)
_LOCK = threading.Lock()
_URL = re.compile(r"https?://\S+")
_REF = re.compile(r"#(\d+)")
_KIND_OF_ENTRY = {"answer": "request"}


class Case(BaseModel):
    """One intake, typed and kept across turns."""

    id: str
    thread: str
    opened_by: str
    kind: str = ""                       # request | defect | ticket | decision | queue | reorder…
    state: str = COLLECTING
    facts: list[str] = Field(default_factory=list)   # what the person said, in order
    asked: list[str] = Field(default_factory=list)   # what the role asked back
    draft: dict = Field(default_factory=dict)        # the staged entry's fields, once proposed
    result: dict = Field(default_factory=dict)       # ref / url / what was said, once filed
    note: str = ""                                   # why it was dropped, or set back
    opened_ts: float = 0.0
    updated_ts: float = 0.0

    @property
    def open(self) -> bool:
        return self.state in OPEN_STATES


def _name(project) -> str:
    return str(getattr(project, "name", "") or "")


def _path(project) -> Path | None:
    try:
        from openfactory.paths import project_memory_dir
        return project_memory_dir(project) / CASES_FILE
    except Exception:  # noqa: BLE001 — a project shape with no home on disk keeps its cases in memory
        log.debug("no memory directory for %s — cases stay in this process", _name(project),
                  exc_info=True)
        return None


def _bucket(project, *, now: float) -> dict[str, Case]:
    """This project's cases, loaded from disk once, expired on every touch."""
    name = _name(project)
    if name not in _CASES:
        _CASES[name] = {}
    cases = _CASES[name]
    if name not in _LOADED:
        _LOADED[name] = True
        path = _path(project)
        if path is not None and path.is_file():
            try:
                for raw in json.loads(path.read_text(encoding="utf-8")).get("cases", []):
                    case = Case.model_validate(raw)
                    cases.setdefault(case.id, case)
            except (OSError, ValueError) as exc:
                log.info("could not read the cases of %s (%s)", name, exc)
    for cid in [c for c, case in cases.items()
                if case.open and now - case.updated_ts > CASE_TTL_SECONDS]:
        cases[cid] = cases[cid].model_copy(update={"state": DROPPED, "note": "expired"})
    while len(cases) > _MAX_CASES:
        oldest = min(cases.values(), key=lambda c: c.updated_ts)
        del cases[oldest.id]
    return cases


def _save(project, cases: dict[str, Case]) -> None:
    path = _path(project)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"cases": [c.model_dump() for c in cases.values()]},
                                   ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log.info("could not save the cases of %s (%s)", _name(project), exc)


def _put(project, cases: dict[str, Case], case: Case, *, now: float) -> Case:
    case = case.model_copy(update={"updated_ts": now})
    cases[case.id] = case
    _THREAD_PROJECT[case.thread] = _name(project)
    _save(project, cases)
    return case


def current(project, thread: str, user: str, *, now: float | None = None) -> Case | None:
    """The open case this person has in this conversation, or None."""
    now = time.time() if now is None else now
    with _LOCK:
        cases = _bucket(project, now=now)
        mine = [c for c in cases.values()
                if c.thread == thread and c.opened_by == user and c.open]
        return max(mine, key=lambda c: c.updated_ts) if mine else None


def _latest_open(cases: dict[str, Case], thread: str, *, states=OPEN_STATES) -> Case | None:
    found = [c for c in cases.values() if c.thread == thread and c.state in states]
    return max(found, key=lambda c: c.updated_ts) if found else None


def note_turn(project, thread: str, user: str, text: str, answer, *,
              now: float | None = None) -> Case:
    """One turn of an intake: what the person said, what the role asked back, what kind the role
    read. Opens the case on the first turn; every later turn by the same person in the same
    conversation joins it until it is filed or dropped."""
    now = time.time() if now is None else now
    with _LOCK:
        cases = _bucket(project, now=now)
        mine = [c for c in cases.values()
                if c.thread == thread and c.opened_by == user and c.open]
        case = max(mine, key=lambda c: c.updated_ts) if mine else Case(
            id=f"{thread}|{user}|{now:.3f}", thread=thread, opened_by=user, opened_ts=now,
            updated_ts=now)
        facts = [*case.facts, (text or "").strip()[:_FACT_MAX]] if (text or "").strip() \
            else list(case.facts)
        asked = list(case.asked)
        reply = str(getattr(answer, "text", "") or "").strip()
        if reply:
            last = reply.splitlines()[-1].strip()
            if last.endswith("?"):
                asked.append(last[:_ASKED_MAX])
        kind = case.kind or _kind_read(answer)
        return _put(project, cases, case.model_copy(update={"facts": facts, "asked": asked,
                                                             "kind": kind}), now=now)


def _kind_read(answer) -> str:
    if getattr(answer, "is_defect", False):
        return "defect"
    if getattr(answer, "is_ticket", False):
        return "ticket"
    if getattr(answer, "is_reorder", False):
        return "reorder"
    if getattr(answer, "gesture", "") == "queue":
        return "queue"
    if getattr(answer, "is_request", False):
        return "request"
    if getattr(answer, "decisions", None):
        return "decision"
    return ""


def _draft_of(entry: dict) -> dict:
    kind = str(entry.get("kind") or _KIND_OF_ENTRY.get("answer" if "answer" in entry else "",
                                                         "request"))
    out: dict = {"kind": kind}
    for key in ("title", "number", "numbers", "term", "restated", "requirement", "reason",
                "decision", "in_favour_of"):
        if entry.get(key):
            out[key] = entry[key] if not isinstance(entry[key], list) else list(entry[key])
    return out


def proposed(project, thread: str, entry: dict, *, displaced: dict | None = None,
             now: float | None = None) -> Case | None:
    """The staging took a draft in this conversation: the latest open case here is now proposed
    with it. THE DISPLACED ONE GOES BACK TO COLLECTING, facts kept — the room's loss, closed."""
    now = time.time() if now is None else now
    with _LOCK:
        cases = _bucket(project, now=now)
        draft = _draft_of(entry)
        losing: list[Case] = []
        if displaced is not None:
            gone = _draft_of(displaced)
            losing = [c for c in cases.values()
                      if c.thread == thread and c.state == PROPOSED
                      and c.draft.get("kind") == gone.get("kind")]
        # THE TARGET IS CHOSEN BEFORE THE DISPLACED ARE MOVED, and they keep their own stamp: set
        # back with a fresh `updated_ts`, the displaced case became "the latest open one" and
        # took the very proposal that had displaced it.
        lost = {c.id for c in losing}
        candidates = [c for c in cases.values() if c.thread == thread
                      and c.state in (COLLECTING, PROPOSED) and c.id not in lost]
        case = max(candidates, key=lambda c: c.updated_ts) if candidates else None
        for old in losing:
            _put(project, cases, old.model_copy(update={
                "state": COLLECTING, "draft": {},
                "note": "displaced by another proposal in this conversation — say it again "
                        "when the floor is free; nothing you said was lost"}), now=old.updated_ts)
        if case is None:
            return None
        return _put(project, cases, case.model_copy(update={
            "state": PROPOSED, "kind": draft["kind"], "draft": draft, "note": ""}), now=now)


def confirmed(project, thread: str, entry: dict, *, now: float | None = None) -> Case | None:
    now = time.time() if now is None else now
    with _LOCK:
        cases = _bucket(project, now=now)
        case = _matching(cases, thread, entry, states=frozenset({PROPOSED}))
        return _put(project, cases, case.model_copy(update={"state": CONFIRMED}),
                    now=now) if case else None


def filed(project, thread: str, entry: dict, said: str, *, now: float | None = None) -> Case | None:
    """The executor ran: the confirmed case is filed, with the ref and the URL the reply carries."""
    now = time.time() if now is None else now
    with _LOCK:
        cases = _bucket(project, now=now)
        case = _matching(cases, thread, entry, states=frozenset({CONFIRMED, PROPOSED}))
        if case is None:
            return None
        url = _URL.search(said or "")
        ref = _REF.search(said or "")
        result = {"said": (said or "")[:300]}
        if url:
            result["url"] = url.group(0).rstrip(".,)")
        if ref:
            result["ref"] = f"#{ref.group(1)}"
        return _put(project, cases, case.model_copy(update={"state": FILED, "result": result}),
                    now=now)


def dropped(project, thread: str, reason: str, *, entry: dict | None = None,
            now: float | None = None) -> Case | None:
    """A no, a forget, an expiry. `forget(thread)` knows no project, so with none given the
    thread is looked for in every project loaded here — a thread key names one conversation."""
    now = time.time() if now is None else now
    with _LOCK:
        if not _name(project):
            name = _THREAD_PROJECT.get(thread)
            if name is None:
                return None
            project = SimpleNamespace(name=name)
        cases = _bucket(project, now=now)
        case = (_matching(cases, thread, entry, states=frozenset({PROPOSED, CONFIRMED}))
                if entry else _latest_open(cases, thread, states=frozenset({PROPOSED, CONFIRMED})))
        if case is None:
            return None
        return _put(project, cases, case.model_copy(update={"state": DROPPED, "note": reason}),
                    now=now)


def _matching(cases: dict[str, Case], thread: str, entry: dict | None, *, states) -> Case | None:
    kind = _draft_of(entry)["kind"] if entry else ""
    found = [c for c in cases.values() if c.thread == thread and c.state in states
             and (not kind or c.draft.get("kind") == kind or c.kind == kind)]
    return max(found, key=lambda c: c.updated_ts) if found else None


def open_cases(project, thread: str, *, now: float | None = None) -> list[Case]:
    """Every open case in one conversation, newest first."""
    now = time.time() if now is None else now
    with _LOCK:
        cases = _bucket(project, now=now)
        return sorted((c for c in cases.values() if c.thread == thread and c.open),
                      key=lambda c: -c.updated_ts)


def render_case(case: Case) -> str:
    lines = [f"kind: {case.kind or 'not read yet'} · state: {case.state}"]
    if case.facts:
        lines.append("what they said:")
        lines += [f"- {f}" for f in case.facts[-8:]]
    if case.asked:
        lines.append("what you asked back:")
        lines += [f"- {a}" for a in case.asked[-6:]]
    if case.draft:
        parts = ", ".join(f"{k}: {v}" for k, v in case.draft.items() if k != "kind")
        lines.append(f"drafted: {case.draft.get('kind')}" + (f" — {parts}" if parts else ""))
    if case.result:
        lines.append("filed: " + ", ".join(f"{k}: {v}" for k, v in case.result.items()
                                            if k != "said"))
    if case.note:
        lines.append(f"note: {case.note}")
    return "\n".join(lines)


def block_for(project, thread: str, user: str, *, now: float | None = None) -> str:
    """The prompt block: this person's intake in this conversation, or "" when there is none."""
    case = current(project, thread, user, now=now)
    if case is None or not case.facts:
        return ""
    return "## This intake so far (typed — continue it, do not start over)\n" + render_case(case)


def hook(event: str, project, thread: str, entry: dict | None = None, *,
         displaced: dict | None = None, said: str = "") -> None:
    """The staging's and the executor's one door — never raises: a case is bookkeeping about a
    write, never the write."""
    try:
        if event == "proposed" and entry is not None:
            proposed(project, thread, entry, displaced=displaced)
        elif event == "confirmed" and entry is not None:
            confirmed(project, thread, entry)
        elif event == "filed" and entry is not None:
            filed(project, thread, entry, said)
        elif event == "rejected":
            dropped(project, thread, "rejected", entry=entry)
        elif event == "forgotten":
            dropped(project, thread, "forgotten", entry=entry)
    except Exception:  # noqa: BLE001
        log.info("the case of %s could not be moved on %s", thread, event, exc_info=True)


def _reset_for_tests() -> None:
    with _LOCK:
        _CASES.clear()
        _LOADED.clear()
        _THREAD_PROJECT.clear()


__all__ = [
    "CASE_TTL_SECONDS",
    "COLLECTING",
    "CONFIRMED",
    "DROPPED",
    "FILED",
    "PROPOSED",
    "Case",
    "block_for",
    "current",
    "hook",
    "note_turn",
    "open_cases",
    "render_case",
]
