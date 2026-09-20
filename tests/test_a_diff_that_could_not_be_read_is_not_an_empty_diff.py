"""A diff the sandbox could not read is never reported as a change that touched no files (#251).

THE DEFECT. Both shipped sandbox rows ended `diff_paths` with

    return [ln for ln in out.splitlines() if ln.strip()] if rc == 0 else []

so a `git` that failed, a missing base ref, a `docker exec` that did not run and a timeout all
arrived as "this change touched no files". The port declared no unreadable state, although its
immediate neighbours do (`tail() -> list[str] | None`, `export_home_dir -> bool`), and no test
pinned the fold — it was a silent default, not a contract.

WHAT READ IT AS AN ANSWER. `machine.py::_validate` reads the diff ONCE and asks it three
questions, and all three take `[]` for *nothing changed*:

    risk_assess          `risk.py` says it outright: "`diff_paths` of None or `[]` means nothing
                         changed — there is no risk to assess". No undeclared paths, no high-risk
                         component, so `promoted_gates` promotes nothing: the advisory gates are
                         never made blocking.
    protected_violations `protected.py`: "an empty diff is not a violation: nothing changed, so
                         nothing reached the verifier". No protected hits.
    touched              no per-component gates run at all; only the repo-wide ones.

Those three land in `merge_policy.should_auto_merge`. A pull request whose diff could not be read
cleared "may this merge by itself" reporting **no protected paths, no undeclared paths and no
risk** — including a change that edited the manifest naming the gates.

AND IN THE OTHER DIRECTION: `_preserve_for_hold` discarded the agent's partial work —
`if not self.sandbox.diff_paths(...): return None  # nothing was written` — so a failed read
turned a resumable hold into a fresh restart.

ONE PLACE IN THE TREE ALREADY KNEW, and paid for it alone: `onboarding/firstrun.py` took a second
read of `git status --porcelain` with the comment *"`diff_paths` swallows a non-zero exit into
`[]`, so 'nothing was written' and 'the diff could not be read' arrive identical"*.

WHAT IS HELD HERE: `None` is the port's word for "could not read", `[]` still means the change
touched nothing, the merge gate refuses on the first and not on the second, and the hold keeps
the work it cannot prove is absent.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory.adapters.sandbox.base import Workspace
from openfactory.adapters.sandbox.worktree import WorktreeSandbox
from openfactory.contracts import Manifest, RunResult, ValidationResult
from openfactory.orchestrator.merge_policy import should_auto_merge


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t.dev"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "a.py").write_text("a = 1\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    return repo


# ═══ the port: None is "could not read", [] is "nothing changed" ════════════════════════════════

def test_a_diff_git_could_not_produce_is_None_and_not_an_empty_list(tmp_path):
    """THE DEFECT, on the shipped worktree row. The base ref does not exist, so `git diff` exits
    non-zero — the same rc a missing `.git`, a pruned base or a timeout produces."""
    repo = _repo(tmp_path)
    box = WorktreeSandbox(root=tmp_path / "wt")

    answer = box.diff_paths(workspace=Workspace(
        path=repo, branch="feature", base_branch="refs/heads/nothing-like-this"))

    assert answer is None, f"an unreadable diff came back as {answer!r}"


def test_a_change_that_really_touched_nothing_is_still_an_empty_list(tmp_path):
    """The answer this must not spoil — and the one the hold below depends on."""
    repo = _repo(tmp_path)
    box = WorktreeSandbox(root=tmp_path / "wt")

    assert box.diff_paths(workspace=Workspace(
        path=repo, branch="main", base_branch="main")) == []


def test_a_change_that_touched_files_is_the_list_of_them(tmp_path):
    repo = _repo(tmp_path)
    _git(["checkout", "-q", "-b", "feature"], repo)
    (repo / "b.py").write_text("b = 1\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "work"], repo)
    box = WorktreeSandbox(root=tmp_path / "wt")

    assert box.diff_paths(workspace=Workspace(
        path=repo, branch="feature", base_branch="main")) == ["b.py"]


@pytest.mark.parametrize("row", ["worktree", "container"])
def test_both_shipped_rows_declare_the_unreadable_state(row):
    """A port whose two providers disagree about which answer means "unreadable" is not a port —
    and the container row's read can fail for one more reason than the worktree's, because its
    `docker exec` may not run at all."""
    import inspect

    from openfactory.adapters.sandbox import base, container, worktree

    module = {"worktree": worktree, "container": container}[row]
    klass = next(v for _n, v in vars(module).items()
                 if inspect.isclass(v) and v.__module__ == module.__name__
                 and hasattr(v, "diff_paths"))
    for owner in (klass, base.SandboxAdapter):
        rendered = str(inspect.signature(owner.diff_paths).return_annotation)
        assert "None" in rendered, f"{owner.__name__}.diff_paths cannot say it could not read"


#: Read rather than driven, and the reason is named per row: the container's `diff_paths` needs a
#: docker daemon, and `_preserve_for_hold` needs a whole job to reach. The house rule is that a
#: guard reads the THING, and this is its documented fallback (the shape `#194`'s sweep uses):
#: assert the source says what cannot be executed here, so the fold cannot come back in silence.
#: `(file, function, role)` — `says` produces the `None`, `asks` consumes it.
READS_NONE_APART = [
    ("openfactory/adapters/sandbox/container.py", "diff_paths", "says"),
    ("openfactory/orchestrator/machine.py", "_preserve_for_hold", "asks"),
]


def _source_of(path: str, fn: str) -> str:
    import ast

    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / path).read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == fn)
    return ast.unparse(node)


@pytest.mark.parametrize("path, fn, role", READS_NONE_APART)
def test_what_cannot_be_driven_here_still_says_None_apart_from_empty(path, fn, role):
    """The producer must have a word for a read that did not land; the consumer must branch on
    `is not None` rather than on truthiness, which is the fold itself — it is what discarded the
    agent's partial work whenever the read failed."""
    body = _source_of(path, fn)

    if role == "says":
        assert "return None" in body, f"{path}::{fn} has no word for a read that did not land"
        assert "else []" not in body, f"{path}::{fn} still folds a failed read into an empty one"
    else:
        assert "is not None" in body or "is None" in body, (
            f"{path}::{fn} tells `None` from `[]` by truthiness, which is the fold itself")


# ═══ the merge gate: the three questions, and which answer refuses ══════════════════════════════

#: An attempt where EVERYTHING ELSE IS GREEN, which is the point: the three questions the diff
#: answers all said "nothing", so with the diff folded there was nothing left to refuse on.
_PASS = [ValidationResult(name="test", command="t", exit_code=0, passed=True)]


def _result(**kw) -> RunResult:
    base = {"ticket_id": "#1", "state": "pr_open", "validations": _PASS}
    return RunResult(**{**base, **kw})


def test_a_pull_request_whose_diff_could_not_be_read_does_not_merge_itself():
    """THE CONSEQUENCE. Everything else about this attempt is green — the gates passed, the review
    approved, nothing was suppressed — and that is the point: the three questions the diff answers
    all said "nothing", so nothing else was left to refuse."""
    assert should_auto_merge(Manifest(merge_policy="auto"),
                             _result(diff_unreadable=True)) is False


def test_but_a_change_that_touched_nothing_is_not_held_for_it():
    """`[]` is an answer. A no-op change is unusual, not unreadable, and holding it would gate on
    a fact nobody measured."""
    assert should_auto_merge(Manifest(merge_policy="auto"),
                             _result(diff_unreadable=False)) is True


def test_an_attempt_from_before_this_field_existed_reads_as_readable():
    """The rule the fields around it already state: an old result cannot answer a question nobody
    asked it, and inventing a gate for it would refuse merges on evidence that does not exist."""
    assert _result().diff_unreadable is False


def test_what_the_machine_measured_reaches_the_result_the_gate_reads():
    """THE WIRING, and it is not a formality: the gate above is a declaration about a field, and
    a field nothing sets is a gate nobody can trip. That is the exact shape
    `test_a_gate_that_holds_says_so_where_the_person_decides.py` exists for, one layer up.

    `_record_risk` is driven directly because every value it reads it reads with `getattr`, so
    the half under test is reachable without a whole job — and a whole job would prove the same
    thing through five other moving parts."""
    from types import SimpleNamespace

    from openfactory.orchestrator.machine import JobRunner

    unread, measured = _result(), _result()
    JobRunner._record_risk(SimpleNamespace(_diff_unreadable=True), unread)
    JobRunner._record_risk(SimpleNamespace(_diff_unreadable=False), measured)

    assert unread.diff_unreadable is True, "the machine measured it and the result never heard"
    assert measured.diff_unreadable is False


def test_the_machine_notices_which_of_the_two_the_sandbox_gave_it():
    """THE FIRST LINK. The port says `None`; `_validate` has to see it, or every gate below is a
    declaration about a value nobody ever sets.

    Read rather than driven, for this method specifically: `_validate` sets the job state, runs
    every gate the profile promotes and takes a census, so driving it would prove this one line
    through a dozen others. What is asked is the RULE — that the flag is derived from a `None`
    test — rather than one spelling of it, so a rewrite that keeps the meaning keeps this green.
    """
    import re

    body = _source_of("openfactory/orchestrator/machine.py", "_validate")

    assert re.search(r"_diff_unreadable\s*=\s*[^\n]*\bis None\b", body), (
        "`_validate` sets `_diff_unreadable` from something other than a `None` test — the two "
        "answers the port now gives are being folded back together here")
