"""A pause costs the same on a free deployment as on a paid one (#118).

A rate-limit pause is a pause, not a redo: the harness's session is kept and the next run
continues it. That capability existed only where an object store did — so the deployment with an
AWS bucket kept its work and the free, open-source one replanned and re-implemented, burning a
second agent pass on a machine paying for its own tokens. The product's claim is the opposite:
*nothing is lost by having no cloud, only the vendor.*

Two things had to be true at once, and neither was:

  1. THE SESSION HAS TO COME FROM THE BOX THAT WROTE IT. The adapter read the ORCHESTRATOR's own
     `~/.claude`, which is the same filesystem only when the box is a worktree — the shape of the
     cloud path. On the default local box the harness runs through `docker exec`, so its session
     was in the container's HOME and died with it. Setting a bucket on such a deployment did not
     enable resume; it uploaded the WORKER's transcripts (the tech-lead's, the sizer's — client
     repository content) to S3 and still ran cold.
  2. WHERE IT IS KEPT HAS TO HAVE A FREE ROW. `put_object` is not a place, it is a vendor.

The guards below are the two halves, plus the properties that must survive both: the box says
whether it can do this at all, the store is bounded, and every step still degrades to a cold run
rather than to a failed job.
"""

from __future__ import annotations

import tarfile
import time
from pathlib import Path

import pytest

from openfactory.adapters.sandbox import WorktreeSandbox
from openfactory.adapters.sandbox.base import Workspace
from openfactory.adapters.sandbox.registry import BOXES, box_traits


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A real box whose HOME is a directory this test owns."""
    home = tmp_path / "boxhome"
    (home / ".claude" / "projects" / "dir").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    work = tmp_path / "work"
    work.mkdir()
    ws = Workspace(path=work, host_path=work, branch="b", base_branch="main")
    return WorktreeSandbox(root=tmp_path / "wt"), ws, home


# ── 1. the capability is the BOX's, and it is declared ──────────────────────────────────────────

def test_every_box_answers_whether_it_can_carry_a_session():
    """A default here would be a claim made on a future box's behalf — the rule `streams` and
    `honours_image` are written under. Checked against the TABLE, so a new row cannot skip it."""
    for kind in BOXES:
        assert isinstance(box_traits(kind).transfers_state, bool), (
            f"the box {kind!r} does not say whether a paused session survives it")


def test_the_trait_is_checked_against_the_implementation_not_written_beside_it():
    """The two local boxes claim True; the claim is only worth what the object DOES.

    `callable(getattr(box, "export_home_dir"))` was the first version of this and could not fail:
    both adapters subclass the `SandboxAdapter` Protocol, whose method bodies are `...`, so a box
    that never implemented the method inherits a callable returning None — a claim checked against
    a stub the contract itself supplied (caught in review, 2026-08-15). Ask the CLASS, and then
    ask the object for a real answer."""
    from openfactory.adapters.sandbox.registry import build_sandbox

    for kind in ("worktree", "container"):
        built = build_sandbox(kind, root=Path("/tmp"), image="x")
        assert box_traits(kind).transfers_state is True
        for method in ("export_home_dir", "import_home_dir"):
            assert method in vars(type(built)), (
                f"{kind} claims it can carry a session and inherits the port's empty {method}")
        # and it ANSWERS, rather than returning the Protocol stub's None
        answer = built.export_home_dir(
            workspace=Workspace(path=Path("/tmp"), branch="b", base_branch="main"),
            relative=".claude/does-not-exist", dest=Path("/tmp/openfactory-nope"))
        assert answer is False, f"{kind} answered {answer!r} where the port promises a bool"


def test_no_trait_may_acquire_a_default():
    """Derived from the dataclass, so the rule covers a field added tomorrow rather than the four
    somebody remembered. A default is the whole failure `streams` documents: an answer given on a
    future box's behalf by whoever wrote this file."""
    import dataclasses

    from openfactory.adapters.sandbox.registry import BoxTraits

    defaulted = [f.name for f in dataclasses.fields(BoxTraits)
                 if f.default is not dataclasses.MISSING
                 or f.default_factory is not dataclasses.MISSING]
    assert not defaulted, (
        f"these traits answer for a box that has not been written yet: {defaulted}")


def test_something_actually_ASKS_the_trait(caplog):
    """A declaration nobody consults is this repository's signature defect wearing a contract:
    `base.py` promises the box "says so BEFORE anybody starts believing it", so somebody has to
    be listening. The composition point is where the box is chosen and the only place that can
    warn before a pause instead of after the bill."""
    import logging

    from openfactory.factory import _warn_if_a_pause_will_cost_a_second_pass

    class _P:
        name = "acme"

    with caplog.at_level(logging.WARNING):
        _warn_if_a_pause_will_cost_a_second_pass(_P(), "fargate")
    assert any("starts cold" in r.getMessage() for r in caplog.records), (
        "a box that cannot carry a session says nothing")

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        _warn_if_a_pause_will_cost_a_second_pass(_P(), "container")
        _warn_if_a_pause_will_cost_a_second_pass(_P(), "not-a-box")
    assert not caplog.records, "a box that CAN carry a session was reported as if it could not"


def test_a_box_that_cannot_reach_its_own_state_says_so():
    """`fargate` has no local adapter at all — there is nothing on this side of the wire to copy
    from, and answering True would send every snapshot into a silent no-op."""
    assert box_traits("fargate").transfers_state is False


# ── 2. the round trip, with nothing configured ──────────────────────────────────────────────────

def test_a_deployment_with_no_cloud_keeps_a_paused_session(tmp_path, monkeypatch, box):
    from openfactory.adapters.agent.claude_code import _restore_session, _snapshot_session

    sandbox, ws, home = box
    monkeypatch.delenv("OPENFACTORY_RESUME_BUCKET", raising=False)
    monkeypatch.delenv("OPENFACTORY_SESSION_STORE", raising=False)
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    (home / ".claude" / "projects" / "dir" / "s.jsonl").write_text("EIGHTY PERCENT OF THE WORK\n")

    key = _snapshot_session("s", "acme-app", "-7", sandbox=sandbox, workspace=ws)
    assert key, "a free deployment could not keep its own session"

    # the pause: everything the box held is gone
    import shutil

    shutil.rmtree(home / ".claude")

    assert _restore_session(key, sandbox=sandbox, workspace=ws) is True
    assert (home / ".claude" / "projects" / "dir" / "s.jsonl").read_text() == (
        "EIGHTY PERCENT OF THE WORK\n")


def test_no_vendor_is_consulted_on_the_free_path(tmp_path, monkeypatch, box):
    """Not "it works without AWS" — "it never asks AWS". A failed credential lookup on every
    pause is how a log full of alarms about a service nobody runs teaches an operator to stop
    reading logs."""
    import sys

    from openfactory.adapters.agent.claude_code import _restore_session, _snapshot_session

    sandbox, ws, home = box
    monkeypatch.delenv("OPENFACTORY_RESUME_BUCKET", raising=False)
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    (home / ".claude" / "projects" / "dir" / "s.jsonl").write_text("x\n")
    monkeypatch.delitem(sys.modules, "boto3", raising=False)

    key = _snapshot_session("s", "acme-app", "-7", sandbox=sandbox, workspace=ws)
    _restore_session(key, sandbox=sandbox, workspace=ws)

    assert "boto3" not in sys.modules, (
        "keeping a session on the local disk reached for an AWS client")


def test_the_free_store_is_the_default_and_a_bucket_is_the_opt_in(monkeypatch):
    from openfactory.adapters.agent.session_store import session_store_kind

    for var in ("OPENFACTORY_SESSION_STORE", "OPENFACTORY_RESUME_BUCKET"):
        monkeypatch.delenv(var, raising=False)
    assert session_store_kind() == "file", "a deployment with nothing configured gets nothing"

    monkeypatch.setenv("OPENFACTORY_RESUME_BUCKET", "b")
    assert session_store_kind() == "s3", "a deployment that HAS an object store should use it"

    monkeypatch.setenv("OPENFACTORY_SESSION_STORE", "file")
    assert session_store_kind() == "file", "what the deployment SAYS must beat what it can infer"


def test_an_unknown_store_raises_rather_than_keeping_nothing():
    """Falling back to a store that keeps nothing is indistinguishable from a job that never
    paused — the rule every axis in this platform is held to."""
    from openfactory.adapters.agent.session_store import build_session_store

    with pytest.raises(ValueError, match="unknown session store"):
        build_session_store("minio")


# ── 3. the store is bounded, and the bound is real ──────────────────────────────────────────────

def test_a_new_snapshot_replaces_that_jobs_older_ones(tmp_path, monkeypatch):
    """Only the newest session is reachable — the older keys are unreferenced the moment a new
    handle is minted, so keeping them is pure growth on the shared state volume."""
    from openfactory.adapters.agent.session_store import FileSessionStore

    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    store = FileSessionStore()
    store.put(key="resume/app/1/old.tar.gz", blob=b"old")
    store.put(key="resume/app/1/new.tar.gz", blob=b"new")

    kept = sorted(p.name for p in (tmp_path / "store" / "resume" / "app" / "1").glob("*.tar.gz"))
    assert kept == ["new.tar.gz"]
    assert store.get(key="resume/app/1/new.tar.gz") == b"new"


def test_snapshots_past_the_retention_window_are_swept(tmp_path, monkeypatch):
    from openfactory.adapters.agent.session_store import RETENTION_SECONDS, FileSessionStore

    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    store = FileSessionStore()
    stale = tmp_path / "store" / "resume" / "other" / "9" / "ancient.tar.gz"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")
    old = time.time() - RETENTION_SECONDS - 60
    import os

    os.utime(stale, (old, old))

    store.put(key="resume/app/1/fresh.tar.gz", blob=b"fresh")

    assert not stale.exists(), "a session store nobody sweeps fills the volume the registry is on"
    assert (tmp_path / "store" / "resume" / "app" / "1" / "fresh.tar.gz").is_file()


def test_a_key_that_is_not_this_stores_address_is_refused(tmp_path, monkeypatch):
    """The key arrives from a handle that has been round-tripped through the durable engine and
    the board. It is checked, not trusted: an absolute path or a `..` would write outside."""
    from openfactory.adapters.agent.session_store import FileSessionStore

    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    store = FileSessionStore()
    for hostile in ("/etc/passwd", "resume/../../escape.tar.gz", "elsewhere/x.tar.gz", ""):
        assert store.put(key=hostile, blob=b"x") is False
        assert store.get(key=hostile) is None
    assert not (tmp_path / "escape.tar.gz").exists()


# ── 4. what must not leak, on either store ──────────────────────────────────────────────────────

def test_only_the_transcripts_leave_the_box(tmp_path, monkeypatch, box):
    """Scoped to `projects/`: a harness HOME also holds credentials and settings, and the archive
    crosses a machine boundary on the cloud path."""
    from openfactory.adapters.agent.claude_code import _snapshot_session

    sandbox, ws, home = box
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    (home / ".claude" / "projects" / "dir" / "s.jsonl").write_text("x\n")
    (home / ".claude" / ".credentials.json").write_text("SECRET\n")
    (home / ".claude" / "settings.json").write_text("{}\n")

    key = _snapshot_session("s", "acme-app", "-7", sandbox=sandbox, workspace=ws)
    names = tarfile.open(tmp_path / "store" / key).getnames()

    assert any(n.endswith("s.jsonl") for n in names)
    assert not any("credential" in n or "settings" in n for n in names)


def test_a_symlink_never_crosses_into_the_next_box(tmp_path, monkeypatch, box):
    """The agent can write into its own HOME, and a symlink restored into the NEXT box would be a
    persistence channel. Dropped twice — by the box on the way out and by the archive."""
    from openfactory.adapters.agent.claude_code import _snapshot_session

    sandbox, ws, home = box
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    (home / ".claude" / "projects" / "dir" / "s.jsonl").write_text("x\n")
    (home / ".claude" / "projects" / "dir" / "escape").symlink_to("/etc/passwd")

    key = _snapshot_session("s", "acme-app", "-7", sandbox=sandbox, workspace=ws)
    names = tarfile.open(tmp_path / "store" / key).getnames()

    assert not any(n.endswith("escape") for n in names)


def test_a_session_id_never_becomes_a_command_in_the_box(tmp_path, monkeypatch, box):
    """The id comes from a JSON stream the harness produced, and the gate interpolates it into a
    shell glob that runs INSIDE the client's box. It stops being trusted here."""
    from openfactory.adapters.agent.claude_code import _session_is_in_the_box

    sandbox, ws, home = box
    ran = []
    monkeypatch.setattr(sandbox, "run",
                        lambda **kw: ran.append(kw["command"]) or (0, ""))

    for hostile in ('x"; touch /tmp/pwned; #', "a b", "../../etc/passwd", "$(id)", "`id`", ""):
        assert _session_is_in_the_box(sandbox, ws, hostile) is False
    assert not ran, f"an unvalidated session id reached the box: {ran}"

    assert _session_is_in_the_box(sandbox, ws, "sess-abc.123") is True
    assert len(ran) == 1 and "sess-abc.123" in ran[0]


def _fake_docker(monkeypatch, *, home="/home/agent", fail=False):
    """A stand-in for the daemon that records the argv the box would have run."""
    from openfactory.adapters.sandbox import container as mod

    calls: list[list[str]] = []

    def fake_host(cmd, timeout=120):
        calls.append(cmd)
        if fail:
            return 1, "exec failed"
        if cmd[:2] == ["docker", "exec"] and "OFHOME" in (cmd[-1] or ""):
            return 0, f"OFHOME:{home}\n"
        return 0, ""

    monkeypatch.setattr(mod, "_host", fake_host)
    box = mod.ContainerSandbox(image="x", project="p")
    box._container = "openfactory-p-b"
    return box, calls


def test_restoring_into_a_container_merges_and_never_deletes(monkeypatch):
    """A box's HOME is not a per-job directory on every box. Removing the target to "replace" it
    is `rm -rf $HOME/.claude/projects` on the worktree box — the operator's own history and any
    concurrent job's transcript. And `docker cp <src> <box>:<dir>` NESTS when the directory
    exists, so the merge has to be the trailing-`/.` form or the session lands at
    `projects/projects/…`, where the harness never looks."""
    import tempfile as _tf

    box, calls = _fake_docker(monkeypatch)
    src = Path(_tf.mkdtemp())
    ws = Workspace(path=Path("/workspace"), branch="b", base_branch="main")

    assert box.import_home_dir(workspace=ws, src=src, relative=".claude/projects") is True

    flat = [" ".join(c) for c in calls]
    assert not any("rm -rf" in c for c in flat), "a restore deleted a directory it does not own"
    cp = next(c for c in flat if c.startswith("docker cp"))
    assert cp.endswith("openfactory-p-b:/home/agent/.claude/projects")
    assert f"{src}/." in cp, "the copy nests the source instead of merging its contents"


def test_the_box_is_asked_where_its_home_is(monkeypatch):
    """`/root` is right for the images this platform ships and wrong for any image with a
    non-root USER — which is what a hardened client image is."""
    box, _ = _fake_docker(monkeypatch)
    assert box._box_home() == "/home/agent"

    # unanswerable → nothing is attempted, rather than a guess written into the client's box
    box2, _ = _fake_docker(monkeypatch, fail=True)
    assert box2._box_home() == ""
    assert box2.export_home_dir(workspace=Workspace(path=Path("/workspace"), branch="b",
                                                    base_branch="main"),
                                relative=".claude/projects", dest=Path("/tmp/nope")) is False


def test_the_boxs_answer_survives_a_chatty_client_image(monkeypatch):
    """`_host` interleaves stdout and stderr and `printf` writes no newline, so a shell that says
    anything on stderr used to arrive glued to the path — and the box silently stopped being able
    to carry a session. The answer is tagged, so it is found rather than positioned."""
    from openfactory.adapters.sandbox import container as mod

    monkeypatch.setattr(mod, "_host", lambda cmd, timeout=120: (
        (0, "sh: no job control\nOFHOME:/home/agent\nWARNING: something\n")
        if "OFHOME" in (cmd[-1] or "") else (0, "")))
    box = mod.ContainerSandbox(image="x", project="p")
    box._container = "c"
    assert box._box_home() == "/home/agent"


def test_a_transfer_that_hangs_answers_instead_of_raising(monkeypatch):
    """The port promises these never raise: losing a session costs a cold run, raising costs the
    job. `_host` raises TimeoutExpired, and a `docker cp` of a large session is where it happens."""
    import subprocess
    import tempfile as _tf

    from openfactory.adapters.sandbox import container as mod

    def hang(cmd, timeout=120):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(mod, "_host", hang)
    box = mod.ContainerSandbox(image="x", project="p")
    box._container = "c"
    ws = Workspace(path=Path("/workspace"), branch="b", base_branch="main")

    assert box.export_home_dir(workspace=ws, relative=".claude/projects",
                               dest=Path("/tmp/nope")) is False
    assert box.import_home_dir(workspace=ws, src=Path(_tf.mkdtemp()),
                               relative=".claude/projects") is False


def test_a_symlinked_session_directory_is_refused(monkeypatch):
    """`test -d` follows links, so a box whose `projects` is `ln -s /` would answer yes, copy the
    box's whole filesystem out, and then REPLACE the real snapshot with it."""
    box, calls = _fake_docker(monkeypatch)
    box.export_home_dir(workspace=Workspace(path=Path("/workspace"), branch="b",
                                            base_branch="main"),
                        relative=".claude/projects", dest=Path("/tmp/nope"))
    probe = " ".join(next(c for c in calls
                          if c[:2] == ["docker", "exec"] and "-d" in " ".join(c)))
    assert "! -L" in probe, "the box was asked if it is a directory, never if it is a link"


@pytest.mark.parametrize("hostile", ["/etc", "../../../etc", ".claude/../../..", ""])
def test_a_path_outside_the_boxs_home_is_refused(hostile, tmp_path, monkeypatch, box):
    """`relative` becomes an argument to a copy issued against the client's box."""
    sandbox, ws, home = box
    assert sandbox.export_home_dir(workspace=ws, relative=hostile, dest=tmp_path / "out") is False
    assert sandbox.import_home_dir(workspace=ws, src=tmp_path, relative=hostile) is False


def test_only_the_paused_session_leaves_the_home(tmp_path, monkeypatch, box):
    """THE SECOND HALF OF THE LEAK, and the one that survived the first fix.

    Taking the whole `projects/` tree is one job's worth in a container and the operator's ENTIRE
    history on the `worktree` box — which is where every judging role runs, inside the worker's own
    process. A snapshot exists to continue ONE session; the rest was never the feature."""
    from openfactory.adapters.agent.claude_code import _snapshot_session

    sandbox, ws, home = box
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    projects = home / ".claude" / "projects"
    (projects / "dir" / "mine.jsonl").write_text("the paused session\n")
    (projects / "other-repo").mkdir()
    (projects / "other-repo" / "someone-elses.jsonl").write_text("ANOTHER CLIENT'S CODE\n")

    key = _snapshot_session("mine", "acme-app", "-7", sandbox=sandbox, workspace=ws)
    names = tarfile.open(tmp_path / "store" / key).getnames()

    assert any(n.endswith("mine.jsonl") for n in names)
    assert not any("someone-elses" in n for n in names), (
        "the snapshot carried a session that has nothing to do with this job")
    # the CONTENT, not only the member names: the blob is gzipped, so scanning its bytes for the
    # other client's text would pass whether or not the file was in there.
    archive = tarfile.open(tmp_path / "store" / key)
    bodies = [archive.extractfile(n).read() for n in names if n.endswith(".jsonl")]
    assert bodies == [b"the paused session\n"]


def test_a_restore_never_deletes_what_it_did_not_put_there(tmp_path, monkeypatch, box):
    """On the worktree box HOME belongs to the PROCESS. A restore that replaced the directory
    would delete the operator's history and any concurrent job's transcript to put one file back."""
    from openfactory.adapters.agent.claude_code import _restore_session, _snapshot_session

    sandbox, ws, home = box
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    projects = home / ".claude" / "projects"
    (projects / "dir" / "mine.jsonl").write_text("x\n")
    key = _snapshot_session("mine", "acme-app", "-7", sandbox=sandbox, workspace=ws)

    # while this job was paused, the worker went on working
    (projects / "dir" / "mine.jsonl").unlink()
    (projects / "dir" / "another-job.jsonl").write_text("STILL RUNNING\n")

    assert _restore_session(key, sandbox=sandbox, workspace=ws) is True
    assert (projects / "dir" / "mine.jsonl").is_file(), "the session did not come back"
    assert (projects / "dir" / "another-job.jsonl").read_text() == "STILL RUNNING\n", (
        "restoring one session destroyed another job's transcript")


def test_a_session_too_large_to_keep_resumes_cold_rather_than_filling_the_disk(
        tmp_path, monkeypatch, box):
    """The harness home is written by the agent's own code, in a box it has root in, and the blob
    is built in memory on the volume that also carries the registry."""
    from openfactory.adapters.agent import claude_code as cc

    sandbox, ws, home = box
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    monkeypatch.setattr(cc, "_MAX_SNAPSHOT_BYTES", 64)
    (home / ".claude" / "projects" / "dir" / "big.jsonl").write_text("x" * 200_000)

    assert cc._snapshot_session("big", "acme-app", "-7", sandbox=sandbox, workspace=ws) == ""
    assert not list((tmp_path / "store").glob("**/*.tar.gz")), "an oversized blob was stored anyway"


def test_a_stale_snapshot_is_not_resumed(tmp_path, monkeypatch):
    """The retention window is a correctness bound, not only a disk one: past it the branch has
    moved and the ticket may not exist. The cloud twin's bucket enforces it by expiring the
    object, so the free store has to enforce it on the way out too."""
    import os

    from openfactory.adapters.agent.session_store import RETENTION_SECONDS, FileSessionStore

    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    store = FileSessionStore()
    store.put(key="resume/app/1/s.tar.gz", blob=b"old")
    blob = tmp_path / "store" / "resume" / "app" / "1" / "s.tar.gz"
    old = time.time() - RETENTION_SECONDS - 60
    os.utime(blob, (old, old))

    assert store.get(key="resume/app/1/s.tar.gz") is None, (
        "a week-old session was handed back — the free store outlives what the cloud one expires")


def test_the_free_store_falls_back_to_a_writable_home(tmp_path, monkeypatch):
    """`/var/lib/openfactory` is the compose worker's volume and nobody else's. A pip install run
    by an ordinary user cannot create it, and the capability would vanish with one WARNING."""
    from openfactory.adapters.agent import session_store as ss

    monkeypatch.delenv("OPENFACTORY_RESUME_DIR", raising=False)
    monkeypatch.setattr(ss, "_SYSTEM_DIR", tmp_path / "unwritable" / "resume")
    (tmp_path / "unwritable").write_text("not a directory")  # mkdir here must fail

    store = ss.FileSessionStore()
    assert store.put(key="resume/app/1/s.tar.gz", blob=b"x") is True
    assert store.get(key="resume/app/1/s.tar.gz") == b"x"
    assert "unwritable" not in str(store.root)


def test_the_adapter_never_reads_a_home_of_its_own_choosing(tmp_path, monkeypatch, box):
    """THE LEAK THIS REDESIGN CLOSED, asserted as a mechanism rather than as a coincidence.

    The adapter used to read the ORCHESTRATOR's `~/.claude` — which on the worker holds the
    judging roles' transcripts of client repositories. The property that replaced it is not "it
    happens to read the right directory": it is that the adapter asks the BOX and archives what
    the box hands over, so a box that hands over nothing produces nothing, whatever is lying
    around on the process's own filesystem.

    The first version of this guard distinguished the two homes with `CLAUDE_HOME` — an env var
    this change deleted every production read of, so the only thing it could still prove was that
    the test could set it (caught in review, 2026-08-15)."""
    from openfactory.adapters.agent.claude_code import _snapshot_session

    sandbox, ws, home = box
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    (home / ".claude" / "projects" / "dir" / "s.jsonl").write_text("the box's own session\n")

    asked = []
    monkeypatch.setattr(sandbox, "export_home_dir",
                        lambda **kw: asked.append(kw["relative"]) or False)

    assert _snapshot_session("s", "acme-app", "-7", sandbox=sandbox, workspace=ws) == "", (
        "the box handed over nothing and something was archived anyway")
    assert asked == [".claude/projects"], "the adapter did not ask the box at all"
    assert not list((tmp_path / "store").glob("**/*.tar.gz"))
