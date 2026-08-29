"""The ARCHAEOLOGY: what a repository's own history says about where the work actually is.

The backfill has four inputs and until this module it read one — the tree as it stands. That input
says what the code IS, and it is the weakest of the four for the decision the backfill actually has
to make: where to spend itself, and which of its own claims to trust.

`product/brownfield.py` already names what is missing, and already ranks it first:

    asked    a person asked for it — an issue, a PR, a comment with an author and a date. Real
             provenance, and the strongest thing a brownfield pass can find. It is also the tier
             most often missed, BECAUSE IT MEANS READING THE TRACKER'S HISTORY RATHER THAN THE CODE.

Three things only history can answer, and each changes what the backfill does:

  * WHERE THE WORK IS. A 40,000-line module untouched since 2019 does not need a concept before the
    factory can start; the file six people changed last month does. Without this the backfill
    describes a monolith uniformly and finishes never. Measured on a real produced bundle: its
    largest concept and its most-changed file are the same file — and nothing in the bundle knew
    that, so nothing could have prioritised it.
  * WHICH ABSENCE IS DELIBERATE. A test that was deleted is a decision. A test commented out three
    years ago and never restored is a hole nobody chose. The tree cannot tell them apart; both read
    to a scanner as "no test here".
  * WHO TO ASK. A question addressed to "the team" is not addressed to anybody. `git` knows whose
    name is on those lines.

WHY THIS MODULE MAY RUN `git` WHEN `infer.py` MAY NOT
-----------------------------------------------------
`infer.py` forbids `subprocess` outright and a test enforces the ban. That ban is about a specific
danger and it is not weakened here: `infer` runs on the CLIENT'S OWN CHECKOUT, on their laptop,
before anybody has agreed to anything — and running a command there can truncate a shared dev
database (card #99 §4.1, attack 2).

This module never runs on the client's checkout and never runs the client's commands. It runs on a
clone THE PLATFORM MADE, in a temporary directory, and the only binary it invokes is `git`. Those
are different acts. The promise it makes in exchange:

  * it runs `git`, and nothing else. Never `setup:`, never `validate:`, never a build.
  * it never reaches the network. `rev-parse`, `rev-list` and `log` touch no remote.
  * it writes nothing — not to the repository, not to a report file. It returns an object.
  * same repository state → identical object. Every list is sorted with an explicit key, and the
    clock is an argument rather than a call, so a caller can pin it.

A SHALLOW CLONE HAS NO HISTORY, AND THAT HAS TO BE SAID OUT LOUD
-----------------------------------------------------------------
This is the failure this module will hit most often and the one that would do the most damage
quietly. `clone_for_proposal` clones `--depth 1`, so the checkout the backfill already has carries
exactly ONE commit — and every honest question about churn answers "1, everywhere". A caller
reading that as "this repository barely changes" would rank every area identically and be confident
about it. That is the absence-read-as-compliance failure this codebase has paid for before.

So `unavailable` is a SENTENCE, never a silence, and `files` is empty whenever it is set. The three
states are distinguishable on purpose, the same way `BundleManifest` distinguishes never-surveyed
from surveyed-and-clean:

    unavailable non-empty                the platform COULD NOT LOOK, and this says why
    unavailable empty, files empty       it looked; the window is genuinely quiet
    unavailable empty, files non-empty   it looked and found work

`clone_for_proposal(history=True)` is what produces a checkout this module can read.
"""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

#: How far back to look. A year covers one full cycle of a team's seasons — a release, an audit,
#: a compliance window — so a file that matters yearly is not read as dead.
DEFAULT_WINDOW_DAYS = 365

#: Commits read at most. A fifteen-year monolith can carry six figures of them, and the object this
#: builds is held in memory and rendered into a prompt. Hitting it sets `truncated`, because a
#: silently short answer to "where is the work" is worse than no answer (§ the module docstring).
MAX_COMMITS = 20_000

#: Author names kept per file. `author_count` carries the true number, so the cap never reads as
#: "this file has one owner" when it has thirty.
MAX_AUTHORS_PER_FILE = 8

#: `git log` on a large repository is the only slow call here. Bounded so a monolith degrades to a
#: named unavailability rather than a hung onboarding.
TIMEOUT_SECONDS = 180

# Record and field separators. NOT NUL, which would be the obvious choice and cannot be used: it
# travels inside a `--pretty=format:` argument, and an argv string is NUL-terminated — `subprocess`
# refuses it with `ValueError: embedded null byte` before `git` is ever reached. ASCII RS and US
# are the next-safest thing that no commit subject carries, and a record that does carry one is
# skipped rather than guessed at (see the parse loop).
#
# `--name-only` output is safe to split on newlines because git quotes any path containing a
# control character even under `core.quotePath=false` (see `_unquote`).
_RECORD = "\x1e"
_FIELD = "\x1f"

# ── ticket references in a commit subject ────────────────────────────────────────────────────────
# The `asked` tier of `product/brownfield.py` needs the link from a file to the work item that
# caused it to change. On every forge this platform speaks to, a squash-merged pull request puts
# that reference in the subject line — which is why the subject is the only thing read here.
#
# `#123` and `AB#123` are unambiguous. A bare `KEY-123` is not: `UTF-8`, `ISO-8601` and `SHA-256`
# have the same shape, so the stoplist below is the price of reading Jira-style keys at all. It is
# a candidate list, deliberately — a wrong ticket reference costs a ranking place, and a missing
# one costs the strongest evidence tier there is.
# The two alternatives are not cosmetic. `\b#101` NEVER MATCHES — a space followed by `#` is not a
# word boundary, because neither character is a word character — so the obvious single pattern
# silently found `AB#4412` and dropped every bare `#101` beside it. Caught by the guard, 2026-08-29.
_TICKET_HASH = re.compile(r"(?:\b(AB)#|(?<![\w#])#)(\d{1,7})\b")
_TICKET_KEY = re.compile(r"\b([A-Z][A-Z0-9]{1,9})-(\d{1,7})\b")
_NOT_A_PROJECT_KEY = frozenset({
    "ADR", "AES", "ANSI", "API", "ASCII", "CVE", "GPT", "HTTP", "IEEE", "ISO", "JSON", "MD5",
    "PEP", "RFC", "RGB", "RSA", "SHA", "SQL", "TLS", "URL", "UTC", "UTF", "UUID", "XML", "YAML",
})


class FileHistory(BaseModel):
    """One path, and what the repository's own log says happened to it."""

    #: repo-relative POSIX path, as `git` reports it
    path: str
    #: commits in the window that touched it.
    #:
    #: MERGES NEVER REACHED THIS NUMBER, and the first version of this comment claimed they did.
    #: `git log --name-only` emits no paths at all for a merge commit unless asked with `-m`/`-c`,
    #: so a merge-commit workflow was never double-counting a file — the mutation that removed
    #: `--no-merges` left every per-file count identical, which is how the claim was caught
    #: (2026-08-29). What `--no-merges` actually protects is `RepoHistory.commits_read`.
    commits: int = 0
    #: author names, sorted, capped at `MAX_AUTHORS_PER_FILE`. NAMES ONLY — never the email, which
    #: is client PII this object has no use for and which travels into a prompt.
    authors: list[str] = Field(default_factory=list)
    #: the true number of distinct authors, so the cap above is never read as the answer
    author_count: int = 0
    #: ISO date (YYYY-MM-DD) of the most recent commit in the window, "" when none
    last_touched: str = ""
    #: ISO date of the oldest commit IN THE WINDOW — not the file's birth, which a windowed log
    #: cannot see. Named `first_touched` rather than `created` for that reason.
    first_touched: str = ""
    #: candidate work-item references seen in the subjects of those commits, sorted
    tickets: list[str] = Field(default_factory=list)
    #: does the path exist in the tree now? A path that stopped existing is kept rather than
    #: dropped — "this was deleted in March" is a finding, and silence is not.
    present: bool = True


class RepoHistory(BaseModel):
    """What one read of one repository's log can say — and, deliberately, what it cannot."""

    #: the checkout that was read, absolute, as it was handed over
    repo: str
    #: the commit the checkout is on. Provenance for this object, not a freshness test.
    head: str = ""
    window_days: int = DEFAULT_WINDOW_DAYS
    #: the ISO date the window opens at, "" when nothing was read
    since: str = ""
    #: commits the window held, EXCLUDING merges. A reader compares this against `files` to judge
    #: how much history the window actually carried, so a merge-commit workflow counting its
    #: merges would report twice the activity of a squash-merge one on identical work.
    commits_read: int = 0
    #: `MAX_COMMITS` was reached, so `files` describes the most recent part of the window only
    truncated: bool = False
    #: one row per path touched in the window, sorted by path
    files: list[FileHistory] = Field(default_factory=list)
    #: WHY THE PLATFORM COULD NOT LOOK, in one sentence. Empty means it looked. `files` is always
    #: empty when this is set, so no caller can average the two.
    unavailable: str = ""

    @property
    def usable(self) -> bool:
        """True when this object is an ANSWER rather than a refusal. A caller ranking areas must
        branch on this, not on `len(files)` — those differ exactly on the shallow clone, which is
        the commonest case in this platform."""
        return not self.unavailable


def _git(repo: Path | str, args: list[str], *,
         timeout: int = TIMEOUT_SECONDS) -> tuple[int, str, str]:
    """`(returncode, stdout, stderr)`. A missing binary is a returncode, never an exception —
    a credential-shaped failure and an absent `git` must both reach the same named refusal."""
    try:
        done = subprocess.run(  # noqa: S603 — argv list, no shell, `git` only
            ["git", "-c", "core.quotePath=false", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 124, "", f"`git {args[0]}` did not finish in {timeout}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return done.returncode, done.stdout, done.stderr


def _unquote(path: str) -> str:
    """git quotes a path containing a control character even with `core.quotePath=false`, and it is
    the quoting that keeps `--name-only` one-path-per-line. Undo it, or return the path as it came
    — a path we cannot decode is still a path, and dropping it would be a silent omission."""
    if len(path) < 2 or not (path.startswith('"') and path.endswith('"')):
        return path
    try:
        return path[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
    except (UnicodeDecodeError, UnicodeEncodeError, ValueError):
        return path


def tickets_in(subject: str) -> list[str]:
    """Candidate work-item references in one commit subject, sorted and deduplicated.

    Kept public because it is the one piece of this module a caller may reasonably want alone —
    reading the same references out of a branch name or a pull request title."""
    found: set[str] = set()
    for prefix, number in _TICKET_HASH.findall(subject):
        found.add(f"{prefix}#{number}" if prefix else f"#{number}")
    for key, number in _TICKET_KEY.findall(subject):
        if key not in _NOT_A_PROJECT_KEY:
            found.add(f"{key}-{number}")
    return sorted(found)


def read_history(repo: Path | str, *, window_days: int = DEFAULT_WINDOW_DAYS,
                 now: datetime | None = None) -> RepoHistory:
    """Read `repo`'s own log and report where the work landed. Never raises.

    `now` is an argument rather than a call so the object is reproducible: two reads of the same
    checkout with the same `now` are identical, which is what makes this diffable against last
    week's — the same rule `infer` and `build_bundle` already keep."""
    root = Path(repo)
    out = RepoHistory(repo=str(root), window_days=window_days)

    rc, _, err = _git(root, ["rev-parse", "--is-inside-work-tree"])
    if rc == 127:
        out.unavailable = ("`git` is not on this machine's PATH, so the repository's history "
                           "cannot be read")
        return out
    if rc != 0:
        out.unavailable = f"{root} is not a git checkout ({(err or '').strip()[-120:]})"
        return out

    rc, shallow, _ = _git(root, ["rev-parse", "--is-shallow-repository"])
    if rc == 0 and shallow.strip() == "true":
        # THE COMMONEST CASE IN THIS PLATFORM, and the one worth the longest sentence: every
        # caller that reached here through `clone_for_proposal` has a `--depth 1` checkout, whose
        # log is one commit and whose honest churn answer is "1, everywhere".
        out.unavailable = ("the checkout is shallow — it carries one commit, so nothing can be "
                           "said about churn, authorship or age. Clone with `history=True` "
                           "(`clone_for_proposal`) to read the log")
        return out

    rc, head, err = _git(root, ["rev-parse", "HEAD"])
    if rc != 0:
        out.unavailable = ("the repository has no commits yet"
                           if "unknown revision" in (err or "") or "ambiguous" in (err or "")
                           else f"could not read HEAD ({(err or '').strip()[-120:]})")
        return out
    out.head = head.strip()

    stamp = (now or datetime.now(UTC)).astimezone(UTC)
    since = (stamp - timedelta(days=window_days)).date().isoformat()
    out.since = since

    rc, body, err = _git(root, [
        "log", "--no-merges", f"--since={since}", f"--max-count={MAX_COMMITS + 1}",
        f"--pretty=format:{_RECORD}%H{_FIELD}%an{_FIELD}%ad{_FIELD}%s",
        "--date=format:%Y-%m-%d", "--name-only",
    ])
    if rc != 0:
        out.unavailable = f"`git log` failed ({(err or '').strip()[-160:]})"
        return out

    rows: dict[str, dict] = {}
    records = [r for r in body.split(_RECORD) if r.strip()]
    if len(records) > MAX_COMMITS:
        out.truncated = True
        records = records[:MAX_COMMITS]
    out.commits_read = len(records)

    for record in records:
        header, _, names = record.partition("\n")
        parts = header.split(_FIELD)
        if len(parts) < 4:
            continue  # a record we cannot read is skipped, never guessed at
        _sha, author, date, subject = parts[0], parts[1], parts[2], _FIELD.join(parts[3:])
        refs = tickets_in(subject)
        for raw in names.splitlines():
            name = _unquote(raw.strip())
            if not name:
                continue
            row = rows.setdefault(name, {"commits": 0, "authors": set(), "tickets": set(),
                                         "last": "", "first": ""})
            row["commits"] += 1
            if author:
                row["authors"].add(author)
            row["tickets"].update(refs)
            # `--since` walks newest first, so the first date seen for a path is its most recent
            # and the last is the oldest IN THE WINDOW.
            if not row["last"]:
                row["last"] = date
            row["first"] = date

    out.files = sorted(
        (FileHistory(
            path=name,
            commits=row["commits"],
            authors=sorted(row["authors"])[:MAX_AUTHORS_PER_FILE],
            author_count=len(row["authors"]),
            last_touched=row["last"],
            first_touched=row["first"],
            tickets=sorted(row["tickets"]),
            present=(root / name).exists(),
        ) for name, row in rows.items()),
        key=lambda f: f.path)
    return out


def change_surface(history: RepoHistory, *, limit: int = 40,
                   present_only: bool = True) -> list[FileHistory]:
    """The files the work actually lands on, busiest first.

    THIS IS THE ORDERING THE BACKFILL SPENDS ITSELF BY. A concept written for the file six people
    changed last month is worth more than one written for a larger file nobody has touched since
    2019, and without this the two look identical.

    `present_only` because a caller ranking where to write concepts wants paths that still exist;
    a caller asking "what did this team stop doing" wants the rest, and passes False."""
    rows = [f for f in history.files if f.present or not present_only]
    rows.sort(key=lambda f: (-f.commits, -f.author_count, f.path))
    return rows[:limit]


def hot_areas(history: RepoHistory, *, depth: int = 2, limit: int = 20,
              present_only: bool = True) -> list[tuple[str, int]]:
    """`(directory, commits)` for the directories the work lands in, busiest first.

    The seed of the per-area readiness the gate will read: an AREA is the unit a licence to operate
    is granted over, and a directory prefix is the coarsest honest one a repository offers before
    anybody has written a concept. Files at the root report as `"."`, never as an empty string that
    a renderer would print as a blank row."""
    totals: dict[str, int] = {}
    for row in history.files:
        if present_only and not row.present:
            continue
        parts = row.path.split("/")
        # `a/b/c/d.cs` at depth 2 → `a/b`; `a/d.cs` → `a`; `d.cs` → `.` — never "", which a
        # renderer prints as a blank row and a reader reads as a bug.
        area = "/".join(parts[:depth]) if len(parts) > depth else "/".join(parts[:-1])
        totals[area or "."] = totals.get(area or ".", 0) + row.commits
    return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def who_to_ask(history: RepoHistory, path: str) -> list[str]:
    """The names on that path, busiest-file-first order preserved from the log.

    A question the backfill cannot answer is worth nothing addressed to "the team". This is the
    routing `followup.py` already does for assignees, applied to a file instead of a card. Returns
    `[]` for a path the window never saw — which is an answer, and a different one from "nobody
    owns it"."""
    for row in history.files:
        if row.path == path:
            return list(row.authors)
    return []
