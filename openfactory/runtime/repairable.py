"""Whether a CI repair has anything to repair — asked at the point of action, by every caller.

THE WORKER ASKED AND THE BOX DID NOT (#184). `_run_ci_repair` reads the pull request's checks
through the one table (`contracts/checks.py`) before it launches anything. But on a REMOTE box the
pass runs inside the task, and `boxed_job.run_ci_repair` fetched its own log and ran the agent
whatever came back — an empty log included — so the rule held on one door and not on the other,
and the brief the agent got was built from a second read that could differ from the one the
decision was made from. This is the gate both doors go through, and the log it hands back is the
one the decision was made from.

A THIRD MOVE, CHEAPER THAN AN AGENT (#756). A blocking check can fail for a reason no changed file
touches — a flaky integration test, a busy shared environment — and an agent paid to repair it
changes nothing, attempt after attempt, until the repair cap parks the card. `changed_paths` and
`log_names_the_change` are the rule the worker asks before it launches: when the failing log names
no file the pull request changes, the failed jobs are re-run instead. The rule is a guess, and it
guesses wrong in the commonest real-regression shape (changed `src/billing/invoice_totals.ts`,
failing `tests/checkout.spec.ts`, #258's review), so it is trusted ONCE PER WATCH, on the first repair
attempt: a wrong "unrelated" then costs one CI re-run, spending one of the two repair attempts,
rather than the whole repair budget spent on re-runs.

AN UNREADABLE OR CUT DIFF ANSWERS "RELATED". `changed_paths` answers `None` for a diff the forge
could not read and for one `truncated` cut — the file the log names may sit past the cut — and the
caller launches the agent as it did before. "Could not see the change" is never "the change
touches nothing in the log". An empty log never reaches the rule: `what_to_repair` holds it first.
"""

from __future__ import annotations

import posixpath
import re
import time
from collections.abc import Callable

from openfactory.adapters.forge.base import DIFF_CUT_MARKER
from openfactory.contracts import JobState, RunResult
from openfactory.contracts.checks import ASK, REPAIR, decide
from openfactory.contracts.checks import read as read_checks
from openfactory.techlead.classify import GATE


def what_to_repair(forge_of: Callable[[], object], issue: str,
                   pr_url: str) -> tuple[RunResult | None, str]:
    """`(the hold, "")` when no agent should run on this pull request, else `(None, the log)`.

    THE HOLD CARRIES `merge_refused`, the mark the resume path reads: the work is on the branch
    and the pull request is open, so a person who settles the check and resumes goes back to the
    MERGE watch — not through a full agent pass that re-does work that already exists.

    AN UNREADABLE FORGE IS HELD TOO, and says so. The alternative is what this replaces: launch
    the pass anyway and let it guess. One forge read is retried once, because a hold costs a
    person's attention and a blip should not.

    `forge_of` BUILDS the forge, inside the retry: a credential that fails to mint is the same
    answer as a forge that does not respond."""
    decision, failure = None, ""
    for attempt in (1, 2):
        try:
            decision = decide(read_checks(forge_of(), pr_url))
            break
        except Exception as exc:  # noqa: BLE001 — any forge failure is the same answer here
            failure = str(exc)[:160]
            if attempt == 1:
                time.sleep(2)
    if decision is not None and decision.action == REPAIR:
        return None, decision.evidence
    if decision is not None and decision.action != ASK:
        # The red check went green — or stopped blocking — between the watch's read and this one.
        # Nothing to repair and nobody to ask: the watch carries on, and the pull request is as
        # the reviewer read it (`code_changed=False` brings the stale marker back down, #179).
        return RunResult(ticket_id=issue, state=JobState.PR_OPEN, pr_url=pr_url,
                         code_changed=False,
                         note="no check that blocks this merge is failing — nothing to repair"), ""
    # THE HOLD SAYS WHAT IT IS, AND DOES NOT LEAVE IT TO ITS OWN PROSE. The note below carries a
    # check's NAME and the vendor's remedy — words a team or a forge chose — and the tech-lead's
    # classifier reads a hold's note to decide who acts. A blocking check called "rate-limit
    # tests" was read as throttling and auto-resumed three times at a full agent pass each
    # (measured 2026-09-19). `ASK` is a gate either way: a check no change to the code settles,
    # or one with no log to act on; both wait for a person on the forge.
    #
    # AND THE UNREADABLE FORGE DECLARES NOTHING, deliberately. All this branch knows is the
    # vendor's own error, which is the one case where the sentence IS the evidence — a 403 and a
    # throttle need different people, and the rules read that better than a guess made here.
    if decision is not None:
        note, hold_cause = decision.note, GATE
    else:
        note, hold_cause = (
            f"the checks on this pull request could not be read ({failure}), so no repair pass "
            f"was launched on a failure nobody saw — resume to read them again"), ""
    return RunResult(ticket_id=issue, state=JobState.ON_HOLD, pr_url=pr_url,
                     merge_refused=True, code_changed=False, note=note,
                     hold_cause=hold_cause), ""


#: git's C-style escapes inside a quoted path (`quote_c_style` in git's quote.c); an octal `\ooo`
#: is one BYTE of the UTF-8 name, so the name is rebuilt as bytes and decoded once.
_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def _unquote(text: str) -> tuple[str, str] | None:
    """`(the path, what follows)` for a git-quoted path at the start of `text`, else `None`."""
    out, i = bytearray(), 1
    while i < len(text):
        ch = text[i]
        if ch == '"':
            return out.decode("utf-8", "replace"), text[i + 1:]
        if ch != "\\":
            out += ch.encode("utf-8")
            i += 1
        elif text[i + 1:i + 4].isdigit() and len(text[i + 1:i + 4]) == 3:
            out.append(int(text[i + 1:i + 4], 8) & 0xFF)
            i += 4
        elif text[i + 1:i + 2] in _C_ESCAPES:
            out.append(_C_ESCAPES[text[i + 1]])
            i += 2
        else:
            return None
    return None


def _one_path(text: str) -> str | None:
    """A `rename from`/`rename to` value: the rest of the line, quoted when git had to."""
    if text.startswith('"'):
        got = _unquote(text)
        return got[0] if got is not None and not got[1].strip() else None
    return text or None


#: What `_header_paths` answers when its two sides cannot be told apart without the `rename` or
#: `copy` lines that follow: an UNQUOTED name may hold a space (git quotes only control
#: characters, `"`, a backslash and, under the default `core.quotePath`, bytes above 0x7F), so
#: `a/x b/y b/z` has two readings.
_NAMED_BELOW: list[str] = []


def _header_paths(rest: str) -> list[str] | None:
    """Both sides of `diff --git <a> <b>`, without `a/` and `b/`; `None` when it is not that shape.

    A header whose sides name the same file is split where they do, spaces and all. Sides that
    differ belong to a rename or a copy, whose `rename from`/`rename to` lines name both; when the
    header alone cannot say where one ends, `_NAMED_BELOW` asks the caller to read those lines."""
    if rest.startswith('"'):
        got = _unquote(rest)
        if got is None:
            return None
        left, rest = got[0], got[1].lstrip(" ")
        right = _one_path(rest)
    elif ' "b/' in rest:  # `a/x "b/\303\251"`: only the second side needed quoting
        cut = rest.index(' "b/')
        left, right = rest[:cut], _one_path(rest[cut + 1:])
    else:
        cuts = [m.start() for m in re.finditer(" b/", rest)]
        same = [c for c in cuts if rest[2:c] == rest[c + 3:]]
        if not same and len(cuts) != 1:
            return _NAMED_BELOW if rest.startswith("a/") and cuts else None
        cut = (same or cuts)[0]
        left, right = rest[:cut], rest[cut + 1:]
    if right is None or not left.startswith("a/") or not right.startswith("b/"):
        return None
    return [left[2:], right[2:]]


_NAMING = ("rename from ", "rename to ", "copy from ", "copy to ")


def changed_paths(diff: str | None) -> list[str] | None:
    """The files a pull request's diff changes, both sides of a rename, or `None` when unseen.

    `None` FOR A DIFF THE FORGE COULD NOT READ (`pr_diff` answers `None`), FOR ONE IT CUT (it
    carries `DIFF_CUT_MARKER`: the files past the cut are not in it), and for text that is not a
    git diff, or a file this cannot name: each is "could not see the change", and the caller
    treats it as related. `[]` is a diff that changes nothing. Read from the `diff --git` headers
    and the `rename`/`copy` `from`/`to` lines, each path once, in the order first met."""
    if diff is None or DIFF_CUT_MARKER in diff:
        return None
    paths: list[str] = []
    headers, owed = 0, 0
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            if owed:
                return None
            headers += 1
            found = _header_paths(line[len("diff --git "):])
            if found is None:
                return None
            if found is _NAMED_BELOW:
                owed = 2
        elif line.startswith(_NAMING):
            one = _one_path(line.split(" ", 2)[2])
            if one is None:
                return None
            found, owed = [one], max(owed - 1, 0)
        else:
            continue
        paths += [p for p in dict.fromkeys(found) if p not in paths]
    if owed or (diff.strip() and not headers):
        return None
    return paths


#: A character a file name can hold. A changed file is named in a log only where the character on
#: its LEFT is not one of these: `a.py` is a suffix of `data.py`, and is not that file.
_NAME_CHAR = r"[\w.\-]"

#: A colour code, as an ESC byte or as the two characters `^[` that `gh run view --log-failed`
#: prints in its place (0 ESC bytes in 789,642 of jest's run 39405383814, gh 2.102.0,
#: 2026-10-20). Left in, its closing `m` stands on the left of a name a tool colours on its own,
#: and jest's `FAIL ... ^[[1mutils.test.ts` read as naming no changed file.
_COLOUR = re.compile(r"(?:\x1b|\^\[)\[[0-9;]*[A-Za-z]")


def log_names_the_change(log: str, paths: list[str]) -> bool:
    """Whether the failing log names any changed file: its basename with its extension, with the
    start of the log or a character no file name holds on its left.

    THE BASENAME DECIDES EVERY CASE. A log that names the full path names its basename too, after
    a `/` — or after a Windows runner's `\\` (`D:\\a\\x\\x\\src\\billing\\invoice.py(12)`), since
    neither is a character a name holds. Matching the full path as well, and reading `\\` as `/`,
    changed no answer (2026-10-20: cutting either left every row green), so neither is done. So
    `lib/invoice.py` in a log reads as naming `src/billing/invoice.py`: a wrong "related"
    launches the agent, which is what happened before this rule existed.

    COLOUR CODES ARE NOT WORDS: they are dropped before the log is read. CASE-SENSITIVE, like
    the file systems the runners check out onto. NEVER THE STEM: `invoice` is any word in a
    sentence, and reading it as `invoice.py` would launch an agent on every log that says
    "invoice". Nothing is required on the RIGHT, so `a.pyc` reads as naming `a.py`, the same
    wrong "related"."""
    text = _COLOUR.sub("", log)
    for path in paths:
        name = posixpath.basename(path)
        if name and re.search(rf"(?<!{_NAME_CHAR}){re.escape(name)}", text):
            return True
    return False
