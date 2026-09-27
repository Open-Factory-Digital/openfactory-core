"""A box can be handed text the command line never carries (#326).

THE DEFECT THIS IS THE FIRST HALF OF. Every command reaches a box as one shell string, so a
harness's prompt reaches it as an argv element — and Linux caps a SINGLE argument at
`MAX_ARG_STRLEN`, 32 pages, 128 KiB, whatever `ARG_MAX` says. A project whose documents are large
therefore kills the invocation before the harness is a process:

    OSError: [Errno 7] Argument list too long: '/bin/sh'

Measured on a real deployment: with 51 ADRs inlined, one prompt was 367,315 bytes and the whole
`sh -c` string 369,709. The sizer died first, so the ticket also ran unsized on its way to failing.

WHAT IS HERE IS THE CHANNEL AND NOTHING ELSE. No harness is routed through it, no prompt has moved
off argv, and no hand-rolled double in this suite had to change — which is the point: three agent
passes died trying to do the channel and the routing together, because the moment a prompt leaves
`command`, every double that reads it back out of `sb.commands[0]` fails.

AND IT IS NOT ON THE PORT. `SandboxAdapter` is `@runtime_checkable` and `check_box` reports every
missing method as a finding, so a method added there is instantly required of the container box, a
cloud box from an add-on package, and every double. It is an OPTIONAL capability reached by
`getattr`, exactly like `guidelines_path` and the harness port's `recognises_model`.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

from openfactory.adapters.sandbox.base import SandboxAdapter, Workspace
from openfactory.adapters.sandbox.container import _INPUT_DIR, ContainerSandbox
from openfactory.adapters.sandbox.worktree import WorktreeSandbox

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Past the ceiling THIS PLATFORM HAS, which is not the same ceiling everywhere (review of #349).
#:
#: Linux caps a SINGLE argument at `MAX_ARG_STRLEN`, 32 pages, and nothing in `sysconf` reports it.
#: macOS has no per-argument cap at all — it caps the whole list, at `ARG_MAX`, 1 MiB on a
#: maintainer's machine — so a 128 KiB payload goes through the command line there and the control
#: below passed the prompt it was written to prove cannot be passed: the file went red on a Mac and
#: the mutation plan could not run at all (baseline RED). That is the #121 class
#: `test_the_suite_runs_where_a_maintainer_sits.py` exists for: green in CI, red at the desk.
_TOO_BIG_FOR_ARGV = "x" * ((32 * 4096 + 1) if sys.platform.startswith("linux")
                           else os.sysconf("SC_ARG_MAX") + 1)


# ── the shape of the seam ────────────────────────────────────────────────────────────────────────

def test_the_capability_is_NOT_on_the_protocol():
    """A method on `SandboxAdapter` is required of every box that ever conforms, including one
    written outside this repository. This one is offered, not demanded."""
    assert "stage_input" not in dir(SandboxAdapter)
    assert hasattr(WorktreeSandbox, "stage_input") and hasattr(ContainerSandbox, "stage_input")


def test_a_box_without_it_still_conforms():
    """The negative half of the same sentence: a box that never heard of the channel is a valid
    box, and `isinstance` still says so."""
    from openfactory.conformance.adapters import check_box

    box = WorktreeSandbox(root=ROOT / ".nowhere")
    assert isinstance(box, SandboxAdapter)
    assert [f for f in check_box(box) if "stage" in f.rule] == []


def test_a_box_whose_capability_cannot_be_CALLED_is_a_finding():
    """Having it with a signature the caller cannot use is worse than not having it: the caller
    reaches it by `getattr` inside a job, and a TypeError there is the argv failure wearing a
    different hat."""
    from openfactory.conformance.adapters import check_box

    class _PositionalOnly(WorktreeSandbox):
        def stage_input(self, workspace, text, /):  # cannot be called with keywords at all
            return "/tmp/x"

    class _WrongNames(WorktreeSandbox):
        def stage_input(self, *, ws, body):  # keyword-only, and not the keywords the caller uses
            return "/tmp/x"

    for cls in (_PositionalOnly, _WrongNames):
        findings = [f for f in check_box(cls(root=ROOT / ".nowhere")) if "stage" in f.rule]
        assert findings, f"{cls.__name__} cannot be called as the caller calls it"
        assert "cannot be called" in findings[0].detail


@pytest.mark.parametrize("spelling", ["by-keyword", "kwargs"])
def test_a_signature_the_caller_CAN_call_is_not_a_finding(spelling):
    """The alarming-direction half, and the reason the check asks `bind` rather than judging the
    spelling (review of #349). Both of these are called perfectly well by
    `stage_input(workspace=…, text=…)`, and a red line at the door for a call that works sends
    whoever wrote an ordinary add-on box to fix nothing."""
    from openfactory.conformance.adapters import check_box

    class _ByKeyword(WorktreeSandbox):
        def stage_input(self, workspace, text):  # ordinary parameters, called by keyword
            return "/tmp/x"

    class _Kwargs(WorktreeSandbox):
        def stage_input(self, **kw):  # a box that forwards
            return "/tmp/x"

    cls = _ByKeyword if spelling == "by-keyword" else _Kwargs
    assert [f for f in check_box(cls(root=ROOT / ".nowhere")) if "stage" in f.rule] == []


# ── the worktree box ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def worktree(tmp_path):
    box = WorktreeSandbox(root=tmp_path / "worktrees")
    ws = Workspace(path=tmp_path / "worktrees" / "job", branch="openfactory/1", base_branch="main")
    ws.path.mkdir(parents=True)
    return box, ws


def test_the_text_arrives_whole_even_past_the_argv_ceiling(worktree):
    """The measurement the channel exists for: a payload that `sh -c` cannot carry as an argument
    is read back, in full, THROUGH THE BOX'S OWN `run` — with only a short path on the line."""
    box, ws = worktree
    path = box.stage_input(workspace=ws, text=_TOO_BIG_FOR_ARGV)

    assert path
    rc, out = box.run(workspace=ws, command=f"wc -c < {path}", timeout=60)
    assert rc == 0 and out.strip() == str(len(_TOO_BIG_FOR_ARGV))
    assert len(f"wc -c < {path}") < 4096, "the command line must stay short — that is the point"


def test_the_same_payload_on_the_command_line_still_fails(worktree):
    """The control. Without this channel the caller has no way to deliver it, and the failure is
    the one reported from a real job rather than something this test invented."""
    import shlex
    import subprocess

    box, ws = worktree
    with pytest.raises(OSError) as raised:
        subprocess.run(f"wc -c <<< {shlex.quote(_TOO_BIG_FOR_ARGV)}", shell=True,
                       cwd=ws.path, capture_output=True, timeout=30)
    assert raised.value.errno == 7  # E2BIG, 'Argument list too long'


def test_the_staged_file_is_OUTSIDE_the_workspace(worktree):
    """THE ONE THING THIS MUST NOT GET WRONG. A job commits with `git add -A`, so a prompt staged
    inside the checkout is committed into the ticket's own pull request — the ticket's diff then
    carries the prompt that produced it, in every job, for ever."""
    box, ws = worktree
    path = pathlib.Path(box.stage_input(workspace=ws, text="the prompt") or "")

    assert path.is_file()
    assert not path.is_relative_to(ws.path), f"{path} is inside the workspace {ws.path}"


def test_a_real_git_worktree_stays_clean_after_staging(tmp_path):
    """The same claim, asked of git rather than of a path comparison: `git status --porcelain` in
    the workspace sees nothing, so `git add -A` has nothing to sweep."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    (repo / "file.txt").write_text("seed")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "seed"], check=True,
                   capture_output=True)

    box = WorktreeSandbox(root=tmp_path / "worktrees")
    ws = box.prepare(repo_path=repo, base_branch="main", branch="openfactory/1")
    box.stage_input(workspace=ws, text="the prompt")

    status = subprocess.run(["git", "-C", str(ws.path), "status", "--porcelain"],
                            capture_output=True, text=True).stdout
    assert status.strip() == "", f"the staged prompt reached the tree: {status!r}"


def test_the_file_is_not_world_readable(worktree):
    """A prompt carries the ticket, and a worktree box runs on a machine with other people's
    processes on it."""
    box, ws = worktree
    path = pathlib.Path(box.stage_input(workspace=ws, text="secret-ish") or "")
    assert path.stat().st_mode & 0o077 == 0, oct(path.stat().st_mode)


def test_a_root_it_cannot_write_degrades_to_None(tmp_path, caplog):
    """`None` means "keep the command line you have" — never an exception, because a box that
    cannot stage must not take the job with it."""
    blocked = tmp_path / "blocked"
    blocked.write_text("I am a file, not a directory")
    box = WorktreeSandbox(root=blocked / "worktrees")
    ws = Workspace(path=tmp_path, branch="b", base_branch="main")

    with caplog.at_level("WARNING"):
        assert box.stage_input(workspace=ws, text="anything") is None
    assert "could not stage" in caplog.text


def test_a_text_that_cannot_be_ENCODED_degrades_like_any_other_failure(worktree, caplog):
    """`UnicodeEncodeError` is a `ValueError`, not an `OSError` (review of #349).

    The docstrings promise None — and the caller's own command line — whenever the text cannot be
    staged. Catching only `OSError` kept that promise for a full disk and broke it for a string: a
    lone surrogate, which is what a `surrogateescape`-decoded file becomes, came out of
    `stage_input` as an exception and would have taken the job with it.
    """
    box, ws = worktree
    with caplog.at_level("WARNING"):
        assert box.stage_input(workspace=ws, text="a\udcffb") is None
    assert "could not stage" in caplog.text


def test_the_container_degrades_on_the_same_text(monkeypatch):
    """The same promise, the same reason, on the other box."""
    import openfactory.adapters.sandbox.container as mod

    monkeypatch.setattr(mod, "_host", lambda *a, **k: (0, ""))
    monkeypatch.setattr(mod.ContainerSandbox, "_quiet_host", lambda self, *a, **k: (0, ""))
    box = ContainerSandbox(image="img", project="acme")
    ws = box.prepare(repo_path=ROOT, base_branch="main", branch="openfactory/1")

    assert box.stage_input(workspace=ws, text="a\udcffb") is None


def test_cleanup_removes_what_this_box_staged(worktree):
    """The docstring said the prompt goes where the box "already removes", and nothing removed it —
    so every staged prompt, each carrying its ticket, stayed on the machine at 0600 for good
    (review of #349). `cleanup` sweeps what THIS box staged, and only that."""
    box, ws = worktree
    mine = pathlib.Path(box.stage_input(workspace=ws, text="my prompt") or "")
    somebody_elses = mine.parent / "prompt-another-job.txt"
    somebody_elses.write_text("not mine to delete")

    box.cleanup(workspace=ws)

    assert not mine.exists(), "the staged prompt outlived the box that wrote it"
    assert somebody_elses.exists(), "cleanup swept a prompt this box did not stage"


def test_cleanup_survives_a_prompt_that_is_already_gone(worktree):
    """A second cleanup, a tmpdir a test framework wiped, an operator who deleted it — none of
    those may raise out of teardown."""
    box, ws = worktree
    path = pathlib.Path(box.stage_input(workspace=ws, text="p") or "")
    path.unlink()
    box.cleanup(workspace=ws)  # must not raise


# ── the container box ────────────────────────────────────────────────────────────────────────────

class _Daemon:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args, timeout=None):
        self.calls.append(list(args))
        if args[:2] == ["docker", "inspect"]:
            return 1, "No such object"
        return 0, ""

    def copies(self) -> list[list[str]]:
        return [a for a in self.calls if a[:2] == ["docker", "cp"]]


@pytest.fixture
def daemon(monkeypatch):
    import openfactory.adapters.sandbox.container as mod

    d = _Daemon()
    monkeypatch.setattr(mod, "_host", d)
    monkeypatch.setattr(mod.ContainerSandbox, "_quiet_host", lambda self, *a, **k: d(*a, **k))
    return d


def test_the_container_copies_it_in_under_tmp_and_answers_with_that_path(daemon, tmp_path):
    """`docker cp`, not a mount, for `export_home_dir`'s reason: a containerised worker's own path
    means nothing to the HOST's daemon. And under `/tmp`, because the workspace is the clone."""
    box = ContainerSandbox(image="img", project="acme")
    ws = box.prepare(repo_path=ROOT, base_branch="main", branch="openfactory/1")

    path = box.stage_input(workspace=ws, text=_TOO_BIG_FOR_ARGV)

    assert path and path.startswith(_INPUT_DIR + "/")
    assert _INPUT_DIR.startswith("/tmp/"), "a staged prompt must not land in the mounted clone"
    assert str(ws.path) not in path
    copied = daemon.copies()
    assert copied and copied[0][-1] == f"{box._container}:{path}"


def test_the_container_writes_the_whole_payload_to_the_file_it_copies(daemon, tmp_path):
    """What is copied is what was asked for — the host-side file, read before docker takes it."""
    seen: list[str] = []

    def _capture(args, timeout=None):
        if args[:2] == ["docker", "cp"]:
            seen.append(pathlib.Path(args[2]).read_text(encoding="utf-8"))
        return daemon(args, timeout=timeout)

    import openfactory.adapters.sandbox.container as mod

    box = ContainerSandbox(image="img", project="acme")
    box.prepare(repo_path=ROOT, base_branch="main", branch="openfactory/1")
    ws = Workspace(path=pathlib.Path("/workspace"), branch="openfactory/1", base_branch="main")
    mod._host = _capture
    box._quiet_host = lambda *a, **k: _capture(*a, **k)  # type: ignore[method-assign]

    box.stage_input(workspace=ws, text=_TOO_BIG_FOR_ARGV)

    assert seen == [_TOO_BIG_FOR_ARGV]


def test_a_container_with_no_box_yet_answers_None(tmp_path):
    """Before `prepare` there is nowhere to put it, and a path into a container that does not
    exist is the kind of answer the caller would act on."""
    box = ContainerSandbox(image="img")
    ws = Workspace(path=tmp_path, branch="b", base_branch="main")
    assert box.stage_input(workspace=ws, text="anything") is None


def test_a_refused_copy_degrades_to_None(monkeypatch, tmp_path):
    """The daemon can refuse, and the caller must get the same `None` the worktree box gives."""
    import openfactory.adapters.sandbox.container as mod

    calls: list[list[str]] = []

    def _refusing(args, timeout=None):
        calls.append(list(args))
        if args[:2] == ["docker", "cp"]:
            return 1, "Error response from daemon: no such container"
        if args[:2] == ["docker", "inspect"]:
            return 1, "No such object"
        return 0, ""

    monkeypatch.setattr(mod, "_host", _refusing)
    monkeypatch.setattr(mod.ContainerSandbox, "_quiet_host",
                        lambda self, *a, **k: _refusing(*a, **k))
    box = ContainerSandbox(image="img", project="acme")
    ws = box.prepare(repo_path=ROOT, base_branch="main", branch="openfactory/1")

    assert box.stage_input(workspace=ws, text="anything") is None


# ── the conformance recorder, so a stranger's adapter is held to the same channel ────────────────

def test_the_conformance_recorder_captures_what_it_was_handed():
    """`_RecordingSandbox` is the stand-in an ADAPTER's conformance runs against. It captures the
    text for the same reason it captures `command`: what the harness said is the thing under test,
    and a recorder that dropped it would make an adapter using the channel look silent."""
    from openfactory.conformance.adapters import _RecordingSandbox

    box = _RecordingSandbox()
    path = box.stage_input(workspace=None, text="the prompt")

    assert box.staged == ["the prompt"]
    assert path.startswith("/tmp/openfactory-input/"), path
