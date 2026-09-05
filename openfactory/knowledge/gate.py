"""The knowledge gate — for each file a change touches, is there recorded knowledge to change it?

"A FILE NOTHING DESCRIBES IS THE LEAST SAFE FILE TO CHANGE, NOT THE FREEST" — a gate read as "no
concept, no objection" is inverted. `orchestrator/risk.py` already takes that stance for the
manifest's components (a path no component declares needs a human); this is the same stance one
level down, against the knowledge bundle: the inventory says what a file IS, the coverage table
says whether its kind was excused from description, the concepts say what describes it, and the
checker says whether that description still matches the bytes.

THE VERDICTS ARE THE REFERENCE GATE'S MINUS `needs-signoff` (ADR-0046; the port's first decision:
autonomy is the product, and a citation that moved is refused by a fingerprint, not by a missing
signature):

  clear        described by at least one concept whose citation of this file still holds
  exempt       of a kind the coverage table excuses wholesale (tests, docs, configuration…) —
               represented by the inventory alone, and clear for the same reason
  new-file     not in the inventory the bundle was built from — nothing recorded can be missing
               about a file that did not exist yet. Never blocks.
  stale        described, and the concept read bytes that are no longer there
  gap-blocked  a recorded unknown on this file that blocks: a high credential risk, a file no
               rule could place, an open question
  no-concept   of a kind nothing excuses, and nothing describes it. THE ONE THAT BLOCKS ON PURPOSE.
  no-bundle    nothing is published for this repository at all — every file, the same verdict

THE STANCE IS THE CHANGE'S, NOT A FILE'S. Green (every file clear, exempt or new) may run alone;
amber (something stale) merges with a person; dark (no-concept, gap-blocked, no-bundle) is refused
with the question asked. What a stance DOES is the project's `okf_gate` setting — `off`, `advise`,
`enforce` — read by the machine and by `merge_policy`; nothing here decides about merging.

JUDGED AGAINST THE BASE, NOT THE BRANCH. The question is whether the knowledge covers the file as
it was before the change, so the checker compares each citation with the base checkout; run
against the branch, every file the agent just edited would read as stale by construction.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from openfactory.knowledge import check as _check
from openfactory.knowledge.contracts import Gap
from openfactory.knowledge.inventory import WHY_NOT, classify, read_inventory
from openfactory.knowledge.okf import read_concepts, read_manifest

log = logging.getLogger("openfactory.knowledge.gate")

CLEAR = "clear"
EXEMPT = "exempt"
NEW_FILE = "new-file"
STALE = "stale"
GAP_BLOCKED = "gap-blocked"
NO_CONCEPT = "no-concept"
NO_BUNDLE = "no-bundle"

GREEN = "green"
AMBER = "amber"
DARK = "dark"

#: The gap kinds that block a change to the file they name. `credential-risk` blocks only when the
#: scanner graded it high — a placeholder in an example file is listed, not a wall. `dead-code`
#: and `unreadable` are recorded and do not block: nothing about them makes the change less safe.
BLOCKING_GAPS = frozenset({"credential-risk", "unclassified", "open-question"})
_DARK_VERDICTS = frozenset({NO_CONCEPT, GAP_BLOCKED, NO_BUNDLE})
_NO_BUNDLE_REASON = "nothing is published for this repository — run the backfill"
#: how many paths a question names before it says "and N more"
MAX_NAMED = 6
#: how many file lines a pull request body carries before it says "and N more"
MAX_LINES = 24

_MARK = {CLEAR: "🟢", EXEMPT: "🟢", NEW_FILE: "🟢", STALE: "🟡",
         GAP_BLOCKED: "🔴", NO_CONCEPT: "🔴", NO_BUNDLE: "🔴"}
_MODE_SAYS = {
    "advise": "informs, blocks nothing",
    "enforce": "an amber change merges with a person; a dark one is parked with the question",
    "off": "off",
}


class FileVerdict(NamedTuple):
    """One file of the change, judged."""

    path: str
    verdict: str
    reason: str = ""
    concepts: tuple[str, ...] = ()


class GateReport(NamedTuple):
    """Every file of one change, judged against one bundle."""

    files: tuple[FileVerdict, ...]
    bundle_commit: str = ""

    def count(self, verdict: str) -> int:
        return sum(1 for f in self.files if f.verdict == verdict)

    def stance(self) -> str:
        """The change's colour: the worst file decides, because one undescribed file is the one
        the reviewer will not know to look at."""
        verdicts = {f.verdict for f in self.files}
        if verdicts & _DARK_VERDICTS:
            return DARK
        if STALE in verdicts:
            return AMBER
        return GREEN

    def question(self) -> str:
        """What a person is asked when the change is dark — and "" otherwise.

        NAMES THE FILES AND BOTH WAYS OUT. A hold that says "knowledge missing" is an alarm; one
        that says which files, and that the remedy is a backfill or a deliberate merge by hand, is
        a decision somebody can take in the time it takes to read it."""
        if self.stance() != DARK:
            return ""
        if self.count(NO_BUNDLE):
            return (f"{_NO_BUNDLE_REASON} before the factory can vouch for a change; until then a "
                    f"person reads every change")
        parts = []
        undescribed = [f.path for f in self.files if f.verdict == NO_CONCEPT]
        blocked = [f for f in self.files if f.verdict == GAP_BLOCKED]
        if undescribed:
            parts.append(f"{len(undescribed)} file(s) nothing describes ({_named(undescribed)})")
        if blocked:
            parts.append(f"{len(blocked)} with a recorded unknown ("
                         + "; ".join(f"`{f.path}` — {f.reason}" for f in blocked[:MAX_NAMED])
                         + (f"; and {len(blocked) - MAX_NAMED} more" if len(blocked) > MAX_NAMED
                            else "") + ")")
        return ("this change touches " + " and ".join(parts)
                + ". Author the knowledge first — run the backfill, or raise `okf_concept_budget` "
                  "so the renewal reaches these — or accept the risk and merge by hand.")

    def summary(self) -> str:
        """One line a log and an event can carry."""
        counts = ", ".join(f"{self.count(v)} {v}" for v in
                           (CLEAR, EXEMPT, NEW_FILE, STALE, GAP_BLOCKED, NO_CONCEPT, NO_BUNDLE)
                           if self.count(v))
        where = f" — bundle at {self.bundle_commit[:8]}" if self.bundle_commit else ""
        return (f"knowledge gate: {self.stance()} — {len(self.files)} file(s): "
                f"{counts or 'none'}{where}")


def _named(paths: list[str]) -> str:
    shown = ", ".join(f"`{p}`" for p in paths[:MAX_NAMED])
    return shown + (f", and {len(paths) - MAX_NAMED} more" if len(paths) > MAX_NAMED else "")


def judge(bundle_dir: Path | None, repo: Path, changed: Iterable[str]) -> GateReport:
    """Judge every path in `changed` against the bundle at `bundle_dir`, checked against `repo`.

    `bundle_dir` None means nothing is published: every file is `no-bundle`, and the stance is
    dark — the least-known state a repository can be in, said rather than waved through. A
    bundle from before the inventory existed classifies each path by name (`inventory.classify`),
    so a test file is still exempt and a code file still owed; it cannot tell a new file from an
    old one, and does not pretend to."""
    paths = sorted({str(p).strip().replace("\\", "/") for p in changed if str(p).strip()})
    if bundle_dir is None:
        return GateReport(tuple(FileVerdict(p, NO_BUNDLE, _NO_BUNDLE_REASON) for p in paths))
    bundle = Path(bundle_dir)
    concepts = read_concepts(bundle)
    inventory = read_inventory(bundle)
    manifest = read_manifest(bundle)
    if not concepts and inventory is None:
        return GateReport(tuple(FileVerdict(p, NO_BUNDLE, "the published bundle holds no "
                                            "concepts and no inventory") for p in paths))
    report = _check.check_concepts(bundle, Path(repo)) if concepts else _check.CheckReport(())
    state = {(c.title, s.path): s.verdict for c in report.concepts for s in c.sources}
    citing: dict[str, list[str]] = {}
    for concept in concepts:
        for source in concept.sources:
            citing.setdefault(source.path, []).append(concept.title)
    excused: dict[str, str] = {row.kind: row.reason for row in (manifest.coverage if manifest
                                                                 else []) if row.excused}
    if not excused:
        # A MANIFEST WITHOUT ROWS is excused by the same table the backfill derives its rows from,
        # so a bundle written before the table existed does not turn every test file dark.
        excused = {kind: reason for kind, (reason, ok) in WHY_NOT.items() if ok}
    gaps: dict[str, list[Gap]] = {}
    for gap in (manifest.gaps if manifest else []):
        if gap.path:
            gaps.setdefault(gap.path, []).append(gap)
    files: list[FileVerdict] = []
    for path in paths:
        kind = inventory.kind_of(path) if inventory is not None else classify(path)[0]
        if inventory is not None and not kind:
            files.append(FileVerdict(path, NEW_FILE, "not in the inventory the bundle was built "
                                                     "from — nothing recorded can be missing "
                                                     "about a file that did not exist yet"))
            continue
        blocking = [g for g in gaps.get(path, ()) if _blocks(g)]
        titles = tuple(citing.get(path, ()))
        if blocking:
            files.append(FileVerdict(path, GAP_BLOCKED, f"{blocking[0].kind}: "
                                                        f"{blocking[0].detail}", titles))
            continue
        if titles:
            broken = [t for t in titles if state.get((t, path)) in (_check.STALE, _check.MISSING)]
            if broken:
                files.append(FileVerdict(path, STALE, f"'{broken[0]}' read bytes that are no "
                                                      f"longer there", titles))
                continue
            unverified = all(state.get((t, path)) == _check.UNVERIFIABLE for t in titles)
            files.append(FileVerdict(path, CLEAR, f"described by '{titles[0]}'"
                                     + (" — citation unverified (a bundle from before "
                                        "fingerprints)" if unverified else ""), titles))
            continue
        if kind in excused:
            files.append(FileVerdict(path, EXEMPT, f"{kind} — {excused[kind]}"))
            continue
        files.append(FileVerdict(path, NO_CONCEPT, f"nothing describes this {kind or 'file'}"))
    return GateReport(tuple(files), bundle_commit=(manifest.source_commit if manifest else ""))


def _blocks(gap: Gap) -> bool:
    if gap.kind not in BLOCKING_GAPS:
        return False
    if gap.kind == "credential-risk":
        return (getattr(gap, "severity", "") or "high") == "high"
    return True


def changed_paths(repo: Path) -> list[str]:
    """The change as `git status` sees it — staged, unstaged AND untracked.

    NOT A `diff --name-only` PIPE, for the reference gate's reason: that pipe drops the staged and
    the untracked paths, which are most of what a change ADDS, so a gate fed by it exits clean
    having never seen the file it would have blocked. A renamed path is reported under its new
    name. A repository git cannot read yields `[]`, which the caller must not read as "nothing
    changed"."""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                             cwd=str(repo), capture_output=True, text=True, check=False,
                             timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    paths: list[str] = []
    for line in out.stdout.splitlines():
        if len(line) < 4:
            continue
        rest = line[3:]
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        paths.append(rest.strip().strip('"'))
    return sorted(set(paths))


def render_gate_lines(verdicts: Iterable[object], *, stance: str, mode: str,
                      bundle_note: str = "", question: str = "") -> list[str]:
    """The pull request's account of the gate: the stance, what the mode makes of it, one line
    per file (capped), and the question when there is one. Takes anything with `.path`,
    `.verdict` and `.reason` — the report's rows or the result's records."""
    rows = list(verdicts)
    lines = ["## Knowledge",
             f"knowledge gate: **{stance}** (`{mode}` — {_MODE_SAYS.get(mode, mode)})"
             + (f" — {bundle_note}" if bundle_note else "")]
    for row in rows[:MAX_LINES]:
        lines.append(f"- {_MARK.get(row.verdict, '⚪')} `{row.path}` — {row.verdict}: {row.reason}")
    if len(rows) > MAX_LINES:
        lines.append(f"- … and {len(rows) - MAX_LINES} more")
    if question:
        lines += ["", f"> {question}"]
    return lines


__all__ = [
    "AMBER",
    "BLOCKING_GAPS",
    "CLEAR",
    "DARK",
    "EXEMPT",
    "GAP_BLOCKED",
    "GREEN",
    "NEW_FILE",
    "NO_BUNDLE",
    "NO_CONCEPT",
    "STALE",
    "FileVerdict",
    "GateReport",
    "changed_paths",
    "judge",
    "render_gate_lines",
]
