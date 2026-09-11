"""The product owner's facts as FILES — the board whole, the open loops, the decisions register
(#33, slice 4; ADR-0041's pattern, on the PO's side of the line).

THE TECH-LEAD OUTGREW THE PROSE PROMPT AND SO HAS THIS ROLE. `role.py::_board_section` injects the
board as prose under a budget, and the budget is honest — it drops titles and never identities,
and says which — but a budget is still a cut: `Done` is rendered as numbers alone, a column's
tail loses its titles, and the open loops and the decisions the role asked people for reach the
prompt only as the one-line `pending` summary. The tech-lead had exactly this shape (#169) and
moved the facts to files the harness greps (`techlead/pack.py`); the product role's docs and code
are files already, and this makes the board, the loops and the decisions files beside them.

WHAT IS IN THE PACK, AND WHY EACH FILE. `board.md` is the board WHOLE — every card, every title,
every state, grouped by column, no budget: the section in the prompt stays as the cheap first
read and this is where a question about #511 is answered. `loops.md` is what the product role is
waiting on a person for (a decision asked, a delivery awaiting "did it work?"), with when it was
asked and whether it has been chased. `decisions.md` is the register: every decision the role
asked for, open or answered, with its outcome — the memory of "what did we agree" that lived
only in the ledger and reached no prompt.

THE MANIFEST IS THE INSTRUMENT. `README.md` names every file AND every fact that could not be
gathered, with the reason — the tech-lead's rule that UNREADABLE is not absence, kept verbatim.
It is also the measurement #33 asks for: how often the role needs a fact nobody gathered decides
whether a planner is ever justified, and a manifest that lists its gaps is what makes the count
possible. `module.py` logs one line per pass with the file and gap counts for the same reason.

PURE TEXT OVER WHAT THE MODULE ALREADY READ. The board came from `_board_cards()` (one paginated
query behind the snapshot cache); the ledger from `memory.store.read`. This module renders and
writes; it reaches no provider, so it can keep the role's promise never to raise.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from openfactory.memory.ledger import DECISION, Loop, fold, waiting
from openfactory.techlead.pack import _MIN_BODY, _PREFIX, _exclude, manifest, pack_dir

log = logging.getLogger("openfactory.product")

#: Whose loops the pack renders. The tech-lead's are its own pack's business.
OWNER = "product"

#: The files, in the order the manifest lists them.
FILES = ("board.md", "loops.md", "decisions.md")


# ── rendering ───────────────────────────────────────────────────────────────────────────────────

def render_board(cards) -> str:
    """Every card, every title, every state — grouped by column, numbered, unbudgeted.

    `None` is a FAILED read and renders to nothing: the caller records the gap, and a file saying
    "the board is empty" over a read that failed would be the claim this pack exists to prevent."""
    if cards is None:
        return ""
    if not cards:
        return ("# The board, whole\n\nThe board is empty as read for this message — no cards in "
                "any column.\n")
    by_column: dict[str, list] = {}
    for card in sorted(cards, key=lambda c: _number(c)):
        by_column.setdefault(str(getattr(card, "column", "") or "(no column)"), []).append(card)
    lines = [
        "# The board, whole",
        "",
        f"{len(cards)} cards as read for this message — every title, grouped by column. The "
        "prompt's own board section is a budgeted rendering of this same reading; when a "
        "question turns on a card it omitted, the card is here. A card absent from THIS file is "
        "absent from the reading, which is not the same as absent from the product.",
        "",
    ]
    for column, in_column in sorted(by_column.items(), key=lambda kv: -len(kv[1])):
        lines += [f"## {column} ({len(in_column)})", ""]
        for card in in_column:
            state = str(getattr(card, "state", "") or "")
            reason = str(getattr(card, "state_reason", "") or "")
            tag = f" [{state}{':' + reason if reason else ''}]" if state else ""
            title = str(getattr(card, "title", "") or "").strip()
            lines.append(f"- #{_number(card)}{tag}" + (f" — {title}" if title else ""))
        lines.append("")
    return "\n".join(lines)


def render_loops(rows: list[Loop]) -> str:
    """What the product role is waiting on a person for — each with when, and whether chased."""
    open_loops = sorted(waiting(rows, owner=OWNER), key=lambda x: x.ts)
    lines = ["# What is waiting on a person", ""]
    if not open_loops:
        lines.append("Nothing is open: no decision asked, no delivery awaiting a verdict.")
        return "\n".join(lines) + "\n"
    lines.append(f"{len(open_loops)} open loop(s) the product role opened and a person has not "
                 f"closed. Each closes by OBSERVATION — a decision when it is answered, a "
                 f"delivery when the client says whether it worked — never by anybody saying so.")
    lines.append("")
    for loop in open_loops:
        lines.append(_loop_line(loop))
    return "\n".join(lines) + "\n"


def render_decisions(rows: list[Loop]) -> str:
    """The register: every decision the role asked a person for, open or answered, with its
    outcome — oldest first, so the reading is the history and not a snapshot."""
    decisions = sorted((x for x in fold(rows) if x.kind == DECISION and x.owner == OWNER),
                       key=lambda x: x.ts)
    lines = ["# The decisions register", ""]
    if not decisions:
        lines.append("No decision has been asked of anybody yet.")
        return "\n".join(lines) + "\n"
    lines.append(f"{len(decisions)} decision(s) the product role asked a person for. An open one "
                 f"is still theirs to take; an answered one says how it ended, in the ledger's own "
                 f"word — never a guess about what was decided.")
    lines.append("")
    for loop in decisions:
        verdict = "OPEN" if loop.waiting else f"ANSWERED ({loop.outcome or 'no outcome recorded'})"
        asked = str((loop.context or {}).get("asked", "") or "").strip()
        lines.append(f"- {loop.ts[:10] or '?'} `{loop.subject}` — {verdict}"
                     + (f": {asked}" if asked else "")
                     + (f" (in {loop.about})" if loop.about else ""))
    return "\n".join(lines) + "\n"


def _loop_line(loop: Loop) -> str:
    asked = str((loop.context or {}).get("asked", "") or "").strip()
    chased = f", chased {loop.chased_ts[:10]}" if loop.chased_ts else ""
    about = f" (about {loop.about})" if loop.about else ""
    detail = f": {asked}" if asked else ""
    return f"- {loop.kind} `{loop.subject}`{about} — since {loop.ts[:10] or '?'}{chased}{detail}"


def _number(card) -> int:
    try:
        return int(getattr(card, "number", 0) or 0)
    except (TypeError, ValueError):
        return 0


# ── gathering ───────────────────────────────────────────────────────────────────────────────────

def gather(project_name: str, cards, *, read=None) -> tuple[dict[str, str], list[str]]:
    """`(files, gaps)` — the three renderings, and every fact that could NOT be gathered.

    The board is handed in (the module read it once for the prompt already); the ledger is read
    here through `memory.store.read`, and a read that raises becomes a GAP with its reason, never
    an empty file: an empty `loops.md` over an unreadable ledger would tell the role nobody is
    waiting on anybody, which is the silence ADR-0021 exists to make impossible."""
    files: dict[str, str] = {}
    gaps: list[str] = []
    board = render_board(cards)
    if board:
        files["board.md"] = board
    else:
        gaps.append("the board could not be read for this message — the platform could not "
                    "look; do not report any card as absent, say the board was not readable")
    try:
        if read is None:
            from openfactory.memory import store as loop_store

            rows = loop_store.read(project_name)
        else:
            rows = read(project_name)
    except Exception as exc:  # noqa: BLE001 — an unreadable ledger is a gap, not a crash
        gaps.append(f"the open-loop ledger could not be read ({exc}) — what is waiting on a "
                    f"person and the decisions register are unknown, not empty")
        return files, gaps
    files["loops.md"] = render_loops(rows)
    files["decisions.md"] = render_decisions(rows)
    return files, gaps


# ── writing ─────────────────────────────────────────────────────────────────────────────────────

def write_facts(root: Path, *, files: dict[str, str], gaps: list[str]) -> Path | None:
    """Write the pack under `root` and return its directory, or None when it could not be.

    THE PREVIOUS PACK IS REMOVED FIRST. The tech-lead writes into a per-job worktree that is
    thrown away; this role's workspace is a STABLE root rebuilt in place on every message
    (`module.py::_workspace`), so a random directory per message would accumulate one per
    conversation turn for ever. Only our own prefix is touched — never the client's files.

    NONE IS A REAL ANSWER: an unwritable pack means the prompt's budgeted sections stand alone
    and `mounted` does not name a door that is not there."""
    try:
        root = Path(root)
        for stale in root.glob(f"{_PREFIX}*"):
            if stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)
        into = pack_dir(root)
        if into.exists():  # a collision on 8 random hex is not a collision, it is a wrong tree
            log.warning("refusing to write the product facts: %s already exists", into)
            return None
        into.mkdir(parents=True)
        written: list[str] = []
        for name in FILES:
            body = files.get(name, "")
            if body and len(body.strip()) >= _MIN_BODY:
                (into / name).write_text(body, encoding="utf-8")
                written.append(name)
        (into / "README.md").write_text(manifest(into.name, written, list(gaps)),
                                        encoding="utf-8")
        if (root / ".git").is_dir():
            # A composed workspace root is not a repository and gets no `.git/` conjured into
            # it; a root that IS one keeps our scratch out of the client's `git status`.
            _exclude(root, into.name)
        return into
    except OSError as exc:  # noqa: BLE001 — an unwritable disk costs the pack, never the answer
        log.warning("could not write the product facts (%s) — answering from the prompt's own "
                    "sections", exc)
        return None
