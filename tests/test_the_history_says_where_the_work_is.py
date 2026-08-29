"""The archaeology: what `onboarding/history.py` may claim, and what it must refuse to claim.

WHAT THESE GUARD, in one sentence each:

  * a SHALLOW checkout is declared, never reported as a quiet repository. This is the guard the
    module exists around: `clone_for_proposal` clones `--depth 1`, so every caller that reaches
    this module by the ordinary route has one commit and an honest churn answer of "1, everywhere".
    A caller reading that as "nothing changes here" would rank every area identically — the
    absence-read-as-compliance failure, with a new mouth.
  * every other way of failing to look NAMES ITSELF: no `git`, not a checkout, no commits.
  * the object is REPRODUCIBLE. Same checkout, same `now`, identical answer — which is what makes
    it diffable against last week's, the same promise `infer` and `build_bundle` already keep.
  * the ranking is by CHURN, and a path that stopped existing is kept and marked rather than
    dropped.

The fixtures build real git repositories with pinned dates and authors. `git` is the one binary
this module may run, so a test that faked it would be proving nothing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openfactory.onboarding.history import (
    MAX_AUTHORS_PER_FILE,
    RepoHistory,
    change_surface,
    hot_areas,
    read_history,
    tickets_in,
    who_to_ask,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None,
                                reason="the archaeology reads a real repository with real git")

#: Pinned so every window in this file is arithmetic, not a race with the wall clock.
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)


def _git(repo: Path, *args: str, when: str = "", who: str = "Ada Lovelace") -> None:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": who, "GIT_AUTHOR_EMAIL": "dev@example.invalid",
                "GIT_COMMITTER_NAME": who, "GIT_COMMITTER_EMAIL": "dev@example.invalid"})
    if when:
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                    "-C", str(repo), *args], check=True, capture_output=True, env=env)


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "Ada Lovelace")
    _git(root, "config", "user.email", "dev@example.invalid")
    return root


def _commit(repo: Path, files: dict[str, str], subject: str, when: str,
            who: str = "Ada Lovelace") -> None:
    for name, body in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A", when=when, who=who)
    _git(repo, "commit", "-q", "-m", subject, when=when, who=who)


@pytest.fixture()
def worked(tmp_path: Path) -> Path:
    """A repository where the work is unmistakably in one place: `billing/invoice.py` is touched
    by three commits and two people; `legacy/frozen.py` once, four years ago."""
    repo = _repo(tmp_path / "worked")
    _commit(repo, {"legacy/frozen.py": "# untouched since\n"},
            "initial import", "2022-01-04T09:00:00+00:00")
    _commit(repo, {"billing/invoice.py": "def total():\n    return 0\n"},
            "feat: invoices #101", "2026-06-02T09:00:00+00:00")
    _commit(repo, {"billing/invoice.py": "def total():\n    return 1\n"},
            "fix: rounding AB#4412", "2026-07-14T09:00:00+00:00", who="Grace Hopper")
    # `billing/audit.py` sorts BEFORE `billing/invoice.py` alphabetically and is touched once.
    # Without it the churn ranking and the alphabetical ranking coincide on this fixture, and a
    # `change_surface` that had lost its sort entirely would pass its own guard — the trap this
    # codebase has already paid for twice (a test whose input cannot reach the cut).
    _commit(repo, {"billing/invoice.py": "def total():\n    return 2\n",
                   "billing/tax.py": "RATE = 0.23\n",
                   "billing/audit.py": "TRAIL = True\n"},
            "fix: tax BILL-77", "2026-08-20T09:00:00+00:00", who="Grace Hopper")
    return repo


# ── the control: it works at all ─────────────────────────────────────────────────────────────────

def test_control_a_repository_with_history_returns_a_populated_object(worked: Path) -> None:
    """The control every other guard here stands on. If this goes red, nothing below means
    anything — read this failure first."""
    out = read_history(worked, now=NOW)

    assert out.usable, out.unavailable
    assert out.unavailable == ""
    assert out.commits_read == 3          # the 2022 import is outside a 365-day window
    assert out.head
    assert {f.path for f in out.files} == {
        "billing/invoice.py", "billing/tax.py", "billing/audit.py"}


# ── the guard this module exists around ──────────────────────────────────────────────────────────

def test_a_shallow_checkout_is_declared_not_reported_as_a_quiet_repository(
        worked: Path, tmp_path: Path) -> None:
    """`clone_for_proposal` clones `--depth 1`. A shallow checkout's log is one commit, so the
    honest churn answer is "1, everywhere" — and a caller that read that as "this repository
    barely changes" would rank every area identically and be confident about it.

    So: `unavailable` says so, and `files` is EMPTY. Both halves matter — a caller must not be
    able to average a refusal with an answer."""
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "--depth", "1", "--quiet",
                    f"file://{worked}", str(shallow)], check=True, capture_output=True)

    out = read_history(shallow, now=NOW)

    assert not out.usable
    assert "shallow" in out.unavailable
    assert "history=True" in out.unavailable          # the remedy, not just the diagnosis
    assert out.files == []


def test_a_full_clone_of_the_same_repository_is_usable(worked: Path, tmp_path: Path) -> None:
    """The positive twin of the guard above. Without it, a `read_history` that refused
    unconditionally would pass the shallow test and be useless."""
    full = tmp_path / "full"
    subprocess.run(["git", "clone", "--quiet", f"file://{worked}", str(full)],
                   check=True, capture_output=True)

    out = read_history(full, now=NOW)

    assert out.usable, out.unavailable
    assert out.files


# ── every other way of failing to look names itself ──────────────────────────────────────────────

def test_a_directory_that_is_not_a_checkout_says_so_and_does_not_raise(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    out = read_history(plain, now=NOW)

    assert not out.usable
    assert "not a git checkout" in out.unavailable
    assert out.files == []


def test_a_repository_with_no_commits_says_so(tmp_path: Path) -> None:
    """A born-empty repository is the state `onboard` already handles one layer up. It is not a
    crash and it is not a quiet repository."""
    out = read_history(_repo(tmp_path / "born-empty"), now=NOW)

    assert not out.usable
    assert out.unavailable
    assert out.files == []


def test_git_missing_from_path_is_a_sentence_not_a_traceback(worked: Path, monkeypatch) -> None:
    """The deployed container is built from the client's own image, and this platform does not get
    to assume what is in it. A missing binary answers like every other refusal here."""
    monkeypatch.setenv("PATH", "")

    out = read_history(worked, now=NOW)

    assert not out.usable
    assert "git" in out.unavailable.lower()
    assert out.files == []


def test_the_three_states_are_distinguishable(worked: Path, tmp_path: Path) -> None:
    """`unavailable` set = could not look. `unavailable` empty with no files = looked, and the
    window is genuinely quiet. Empty with files = looked and found work. A caller ranking areas
    branches on `usable`, and these must not collapse into each other."""
    could_not_look = read_history(tmp_path / "nowhere", now=NOW)
    looked_and_quiet = read_history(worked, window_days=1, now=NOW)
    looked_and_found = read_history(worked, now=NOW)

    assert (not could_not_look.usable) and could_not_look.files == []
    assert looked_and_quiet.usable and looked_and_quiet.files == []
    assert looked_and_found.usable and looked_and_found.files


# ── reproducible ─────────────────────────────────────────────────────────────────────────────────

def test_the_same_checkout_read_twice_is_identical(worked: Path) -> None:
    """A proposal you cannot diff against last week's is a proposal nobody can review — `infer`'s
    rule, and this object is read by the same reviewers."""
    first = read_history(worked, now=NOW)
    second = read_history(worked, now=NOW)

    assert first.model_dump() == second.model_dump()


def test_the_files_come_back_sorted_by_path(worked: Path) -> None:
    """`files` is documented as sorted by path, and a caller diffing this object against last
    week's is the reason. Insertion order happens to be stable inside one run, which is exactly why
    this needs its own guard: two reads agreeing proves nothing about two RUNS agreeing after a
    commit landed in between."""
    paths = [f.path for f in read_history(worked, window_days=365 * 6, now=NOW).files]

    assert paths == sorted(paths)


def test_hitting_the_commit_ceiling_is_declared(worked: Path, monkeypatch) -> None:
    """A fifteen-year monolith carries six figures of commits and this object is rendered into a
    prompt, so there is a ceiling. A short answer to "where is the work" that does not say it is
    short is the failure this whole module is written against."""
    monkeypatch.setattr("openfactory.onboarding.history.MAX_COMMITS", 1)

    out = read_history(worked, now=NOW)

    assert out.truncated is True
    assert out.commits_read == 1
    assert out.usable          # truncated is still an ANSWER — it says how much of one


def test_a_history_read_whole_does_not_claim_truncation(worked: Path) -> None:
    """The positive twin. Without it, `truncated = True` unconditionally passes the guard above."""
    assert read_history(worked, now=NOW).truncated is False


def test_the_clock_is_an_argument_so_the_window_is_pinnable(worked: Path) -> None:
    """`now` is passed, never called. Without that the window drifts under the caller and two runs
    an hour apart disagree for no reason a reader could find."""
    inside = read_history(worked, window_days=365, now=NOW)
    outside = read_history(worked, window_days=365,
                           now=datetime(2030, 1, 1, tzinfo=UTC))

    assert inside.files
    assert outside.files == []
    assert outside.usable          # a quiet window is an ANSWER, not a refusal


def test_the_window_excludes_what_is_older_than_it(worked: Path) -> None:
    """`legacy/frozen.py` was touched once, in 2022. A 365-day window must not see it — that is
    the whole point of a window, and it is what stops a fifteen-year monolith reading as uniformly
    busy."""
    narrow = read_history(worked, window_days=365, now=NOW)
    wide = read_history(worked, window_days=365 * 6, now=NOW)

    assert "legacy/frozen.py" not in {f.path for f in narrow.files}
    assert "legacy/frozen.py" in {f.path for f in wide.files}


# ── what the ranking says ────────────────────────────────────────────────────────────────────────

def test_the_change_surface_ranks_by_churn(worked: Path) -> None:
    """THE ORDERING THE BACKFILL SPENDS ITSELF BY. `billing/invoice.py` has three commits and
    `billing/tax.py` one, so the first must come first — otherwise a concept gets written for the
    file nobody touches."""
    surface = change_surface(read_history(worked, now=NOW))
    paths = [f.path for f in surface]

    assert paths == ["billing/invoice.py", "billing/audit.py", "billing/tax.py"]
    assert paths != sorted(paths), "the fixture must not let alphabetical order pass as ranking"
    assert surface[0].commits == 3
    assert surface[0].author_count == 2


def test_a_path_that_stopped_existing_is_kept_and_marked(worked: Path) -> None:
    """A deleted file is a finding — "this team stopped doing X in March" — so it is recorded with
    `present=False` rather than dropped. But `change_surface` excludes it by default, because a
    caller choosing where to WRITE a concept cannot write one about a path that is gone."""
    _git(worked, "rm", "-q", "billing/tax.py", when="2026-08-25T09:00:00+00:00")
    _git(worked, "commit", "-q", "-m", "chore: retire tax AB#9001",
         when="2026-08-25T09:00:00+00:00")

    out = read_history(worked, now=NOW)
    gone = [f for f in out.files if f.path == "billing/tax.py"]

    assert gone and gone[0].present is False
    assert "billing/tax.py" not in {f.path for f in change_surface(out)}
    assert "billing/tax.py" in {f.path for f in change_surface(out, present_only=False)}


def test_a_merge_does_not_inflate_the_commits_the_window_held(tmp_path: Path) -> None:
    """`commits_read` is what a reader uses to judge how much history the window carried, so a
    merge-commit workflow must not report twice the activity of a squash-merge one on identical
    work — and this platform serves both, on the same board.

    THE PER-FILE COUNT WAS NEVER AT RISK, and the first version of this guard asserted that it
    was: `git log --name-only` emits no paths for a merge commit, so removing `--no-merges` left
    every file's count untouched and the mutation survived. `commits_read` is the number the flag
    actually protects, so it is the number asserted."""
    repo = _repo(tmp_path / "merged")
    _commit(repo, {"app.py": "x = 1\n"}, "base", "2026-08-01T09:00:00+00:00")
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, {"app.py": "x = 2\n"}, "feat: side", "2026-08-02T09:00:00+00:00")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--no-ff", "-q", "-m", "Merge pull request #7", "side",
         when="2026-08-03T09:00:00+00:00")

    out = read_history(repo, now=NOW)
    app = next(f for f in out.files if f.path == "app.py")

    assert out.commits_read == 2     # base + the side commit; the merge is not one of them
    assert app.commits == 2          # and it never was, for the reason in the docstring


def test_the_dates_span_the_window_oldest_and_newest(worked: Path) -> None:
    """`--since` walks newest-first, so the first date seen for a path is its most recent. Getting
    this backwards would report every file as last touched on the day it entered the window."""
    invoice = next(f for f in read_history(worked, now=NOW).files
                   if f.path == "billing/invoice.py")

    assert invoice.last_touched == "2026-08-20"
    assert invoice.first_touched == "2026-06-02"


# ── the `asked` tier: which work item touched this file ──────────────────────────────────────────

def test_the_work_items_that_touched_a_file_are_collected(worked: Path) -> None:
    """The link `product/brownfield.py` calls the strongest evidence tier there is, and the one it
    says is most often missed."""
    invoice = next(f for f in read_history(worked, now=NOW).files
                   if f.path == "billing/invoice.py")

    assert invoice.tickets == ["#101", "AB#4412", "BILL-77"]


def test_ticket_references_are_read_and_lookalikes_are_not() -> None:
    """`#123` and `AB#123` are unambiguous. A bare `KEY-123` is not — `UTF-8` and `SHA-256` have
    the same shape — so the stoplist is the price of reading Jira keys at all, and it has to
    actually hold."""
    assert tickets_in("fix: rounding AB#4412 and #101") == ["#101", "AB#4412"]
    assert tickets_in("feat: PROJ-9 adds the thing") == ["PROJ-9"]
    assert tickets_in("chore: normalise to UTF-8 and SHA-256") == []
    assert tickets_in("docs: see ADR-0041") == []
    assert tickets_in("no references here") == []


# ── who to ask ───────────────────────────────────────────────────────────────────────────────────

def test_who_to_ask_names_the_people_on_that_path(worked: Path) -> None:
    """A question addressed to "the team" is addressed to nobody. This is the routing
    `followup.py` already does for assignees, applied to a file."""
    out = read_history(worked, now=NOW)

    assert who_to_ask(out, "billing/invoice.py") == ["Ada Lovelace", "Grace Hopper"]
    assert who_to_ask(out, "does/not/exist.py") == []


def test_the_author_cap_never_reads_as_the_true_count(tmp_path: Path) -> None:
    """The cap keeps a prompt bounded. `author_count` carries the truth, so a file thirty people
    have touched is never rendered as one with eight owners."""
    repo = _repo(tmp_path / "crowded")
    for n in range(MAX_AUTHORS_PER_FILE + 4):
        _commit(repo, {"shared.py": f"version = {n}\n"}, f"chore: bump {n}",
                "2026-08-10T09:00:00+00:00", who=f"Dev {n:02d}")

    shared = next(f for f in read_history(repo, now=NOW).files if f.path == "shared.py")

    assert len(shared.authors) == MAX_AUTHORS_PER_FILE
    assert shared.author_count == MAX_AUTHORS_PER_FILE + 4


# ── areas ────────────────────────────────────────────────────────────────────────────────────────

def test_hot_areas_groups_the_work_by_directory(worked: Path) -> None:
    """The seed of the per-area readiness the gate will read. An area is the unit a licence to
    operate is granted over, and a directory is the coarsest honest one a repository offers before
    anybody has written a concept."""
    areas = hot_areas(read_history(worked, window_days=365 * 6, now=NOW), depth=1)

    assert areas[0] == ("billing", 5)      # invoice 3 + tax 1 + audit 1
    assert ("legacy", 1) in areas


def test_a_file_at_the_root_reports_an_area_and_not_a_blank(tmp_path: Path) -> None:
    """`""` renders as a blank row and reads as a bug. `.` is a directory."""
    repo = _repo(tmp_path / "flat")
    _commit(repo, {"main.py": "print(1)\n"}, "init", "2026-08-10T09:00:00+00:00")

    assert hot_areas(read_history(repo, now=NOW)) == [(".", 1)]


# ── the object's own promises ────────────────────────────────────────────────────────────────────

def test_an_unusable_history_never_carries_files() -> None:
    """The invariant every caller relies on: a refusal and an answer cannot be averaged. Guarded on
    the model rather than on one code path, because there are five ways to become unavailable."""
    refused = RepoHistory(repo="/nowhere", unavailable="the checkout is shallow")

    assert not refused.usable
    assert refused.files == []


def test_reading_a_repository_writes_nothing_into_it(worked: Path) -> None:
    """It returns an object. Not a report file, not a note in the tree — and above all no commit,
    because this runs on a checkout that goes on to host an agent and reach a box proof."""
    before = subprocess.run(["git", "-C", str(worked), "status", "--porcelain"],
                            capture_output=True, text=True, check=True).stdout
    head_before = subprocess.run(["git", "-C", str(worked), "rev-parse", "HEAD"],
                                 capture_output=True, text=True, check=True).stdout

    read_history(worked, now=NOW)

    after = subprocess.run(["git", "-C", str(worked), "status", "--porcelain"],
                           capture_output=True, text=True, check=True).stdout
    head_after = subprocess.run(["git", "-C", str(worked), "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=True).stdout
    assert (before, head_before) == (after, head_after)
