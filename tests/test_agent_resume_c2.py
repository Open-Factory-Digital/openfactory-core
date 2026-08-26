"""C2 — perfect session resume (claude_code adapter side).

A rate-limit PAUSE is a pause, not a redo: on resume the agent must CONTINUE its prior
session (restore the CLI state + `--resume <id>`) instead of replanning/re-implementing and
re-burning tokens (partner-reported). This proves the adapter-private machinery: the opaque
handle, the S3 snapshot/restore round-trip, phase-scoped resume, and — crucially — that every
piece DEGRADES to a cold (fresh) run when unconfigured, so resume is a bonus and never a new
failure mode. The core stays agnostic (it only round-trips the opaque handle).
"""

from __future__ import annotations

import io
import json
import shutil

import add_ons
import pytest

from openfactory.adapters.agent.base import AgentContext
from openfactory.adapters.agent.claude_code import (
    ClaudeCodeAdapter,
    _decode_handle,
    _encode_handle,
    _parse_stream,
    _restore_session,
    _snapshot_session,
)
from openfactory.contracts import AcceptanceCriterion, AgentRunResult, Ticket


def _ticket() -> Ticket:
    return Ticket(id="#40", title="x", objective="x", repo="o/app",
                  acceptance_criteria=[AcceptanceCriterion(text="c")])


# ---- opaque handle: round-trip + rejection of anything we didn't emit -----------------------

def test_handle_round_trips():
    h = _encode_handle("execute", "sess-1", "resume/o-app/40/sess-1.tar.gz")
    d = _decode_handle(h)
    assert d == {"v": 1, "phase": "execute", "session": "sess-1",
                 "state_key": "resume/o-app/40/sess-1.tar.gz"}


@pytest.mark.parametrize("bad", [
    "", "   ", "not json", "{}", json.dumps({"v": 2, "session": "s"}),  # wrong version
    json.dumps({"v": 1, "phase": "execute"}),                          # no session
    json.dumps(["v", 1]),                                              # not a dict
    json.dumps({"v": 1, "session": ""}),                              # empty session
])
def test_decode_rejects_foreign_or_garbage(bad):
    # a foreign/blank/garbled handle must decode to None → the run starts COLD, never crashes.
    assert _decode_handle(bad) is None


# ---- snapshot/restore: full round-trip through a REAL box, and degradation at every step -----
#
# The box is a real `WorktreeSandbox` with HOME redirected, not a double. Until #118 these tests
# drove the adapter with `sandbox=None` and asserted against the ORCHESTRATOR's own `~/.claude`,
# which is the same filesystem only when the box is a worktree — so nothing here could see that on
# the default local box (a container) the session the adapter archived was never the session the
# harness wrote. A real box is what makes the two the same question.

class _FakeS3:
    """A minimal in-memory S3 double: put/get by (bucket, key)."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket, Key, Body):  # noqa: N803 — boto3's kwargs
        self.store[(Bucket, Key)] = Body

    def get_object(self, *, Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(self.store[(Bucket, Key)])}


def _box_with_home(tmp_path, monkeypatch, *, session: str = "", project_dir: str = "p1"):
    """A real box whose HOME holds a harness session, plus the workspace to address it with."""
    from openfactory.adapters.sandbox import WorktreeSandbox
    from openfactory.adapters.sandbox.base import Workspace

    home = tmp_path / "boxhome"
    (home / ".claude" / "projects" / project_dir).mkdir(parents=True)
    if session:
        (home / ".claude" / "projects" / project_dir / f"{session}.jsonl").write_text("x\n")
    monkeypatch.setenv("HOME", str(home))
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    ws = Workspace(path=work, host_path=work, branch="b", base_branch="main")
    return WorktreeSandbox(root=tmp_path / "wt"), ws, home


def test_snapshot_and_restore_round_trip(tmp_path, monkeypatch):
    # Take the session out of the box, wipe the box, put it back → the files come back intact,
    # with nothing configured: the FREE store is the default (#118).
    monkeypatch.delenv("OPENFACTORY_RESUME_BUCKET", raising=False)
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    box, ws, home = _box_with_home(tmp_path, monkeypatch)
    # the CLI names a transcript after its session id — that is what `--resume <id>` reads back
    (home / ".claude" / "projects" / "p1" / "sess-1.jsonl").write_text('{"turn": 1}\n')

    key = _snapshot_session("sess-1", "o-app", "40", sandbox=box, workspace=ws)
    assert key == "resume/o-app/40/sess-1.tar.gz"
    assert (tmp_path / "store" / key).is_file()  # kept, on this machine, for free

    shutil.rmtree(home / ".claude" / "projects")
    assert _restore_session(key, sandbox=box, workspace=ws) is True
    assert (home / ".claude" / "projects" / "p1" / "sess-1.jsonl").read_text() == '{"turn": 1}\n'


def test_snapshot_needs_a_box_not_a_bucket(tmp_path, monkeypatch):
    # The session belongs to the box that wrote it. With no box to ask there is nothing to take —
    # and reading the ORCHESTRATOR's own home instead is exactly the defect #118 removed.
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    assert _snapshot_session("sess-1", "o-app", "40") == ""
    assert _snapshot_session("sess-1", "o-app", "40", sandbox=None, workspace=None) == ""


def test_restore_is_noop_without_a_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    box, ws, _ = _box_with_home(tmp_path, monkeypatch)
    assert _restore_session("resume/o-app/40/never-stored.tar.gz", sandbox=box, workspace=ws) is False
    assert _restore_session("", sandbox=box, workspace=ws) is False


def test_restore_survives_a_store_failure(tmp_path, monkeypatch):
    # A broken store (missing object, unreadable file, dead network) must not crash resume.
    monkeypatch.setenv("OPENFACTORY_RESUME_BUCKET", "b")
    box, ws, _ = _box_with_home(tmp_path, monkeypatch)

    class _BoomS3:
        def get_object(self, **_):
            raise RuntimeError("NoSuchKey")

    boto3 = add_ons.sdk("boto3", "openfactory/adapters/agent/s3_session_store.py")
    monkeypatch.setattr(boto3, "client", lambda svc: _BoomS3())
    assert _restore_session("resume/o-app/40/missing.tar.gz", sandbox=box, workspace=ws) is False


def test_snapshot_survives_a_store_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_RESUME_BUCKET", "b")
    box, ws, _ = _box_with_home(tmp_path, monkeypatch, session="sess-1")

    class _BoomS3:
        def put_object(self, **_):
            raise RuntimeError("AccessDenied")

    boto3 = add_ons.sdk("boto3", "openfactory/adapters/agent/s3_session_store.py")
    monkeypatch.setattr(boto3, "client", lambda svc: _BoomS3())
    assert _snapshot_session("sess-1", "o-app", "40", sandbox=box, workspace=ws) == ""


def test_the_cloud_store_is_still_the_one_a_bucket_selects(tmp_path, monkeypatch):
    # The free store is the DEFAULT, not the only one: a deployment whose boxes run where this
    # worker cannot reach them still crosses the session through its object store, under the same
    # `resume/` prefix its bucket policy and lifecycle rule were written for.
    from vendor_addons import install

    install(monkeypatch, "session_store.s3")  # the vendor row is an add-on; installed for the test
    monkeypatch.setenv("OPENFACTORY_RESUME_BUCKET", "b")
    monkeypatch.delenv("OPENFACTORY_SESSION_STORE", raising=False)
    # POINTED AT THE FREE STORE ON PURPOSE: "the free store was written to as well" is only an
    # assertion if this is where the free store would write (it defaulted elsewhere, so the check
    # watched a path nothing could ever create — caught in review, 2026-08-15).
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    box, ws, home = _box_with_home(tmp_path, monkeypatch, session="sess-1")
    fake = _FakeS3()
    boto3 = add_ons.sdk("boto3", "openfactory/adapters/agent/s3_session_store.py")
    monkeypatch.setattr(boto3, "client", lambda svc: fake)

    key = _snapshot_session("sess-1", "o-app", "40", sandbox=box, workspace=ws)
    assert key == "resume/o-app/40/sess-1.tar.gz"
    assert ("b", key) in fake.store, "a deployment with a bucket stopped using it"
    assert not (tmp_path / "store").exists(), "the free store was written to as well"

    # AND THE READ HALF, positively. Every assertion about the cloud store used to be either a
    # write or a failure, so nothing here could tell bytes from a stream — an object that reads
    # `["Body"]` instead of `["Body"].read()` passed the whole suite while every cloud resume ran
    # cold. A negative guard cannot see a missing value (2026-08-15).
    import shutil as _sh

    _sh.rmtree(home / ".claude" / "projects")
    assert _restore_session(key, sandbox=box, workspace=ws) is True
    assert (home / ".claude" / "projects" / "p1" / "sess-1.jsonl").is_file()


# ---- --resume flag: present only on a real resume, on the right phase ------------------------

def test_cli_adds_resume_flag_when_session_given():
    a = ClaudeCodeAdapter()
    cmd = a._cli("do it", harness="claude", tools=[], model=None, resume_session="sess-9")
    assert "--resume" in cmd and "sess-9" in cmd


def test_cli_omits_resume_flag_by_default():
    a = ClaudeCodeAdapter()
    assert "--resume" not in a._cli("do it", harness="claude", tools=[], model=None)


def test_resume_session_only_on_matching_phase(tmp_path, monkeypatch):
    # A handle for the EXECUTE phase must not resume the PLAN call (wrong session → garbage).
    monkeypatch.delenv("OPENFACTORY_RESUME_BUCKET", raising=False)
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    box, ws, _ = _box_with_home(tmp_path, monkeypatch, session="sess-x")
    key = _snapshot_session("sess-x", "o-app", "40", sandbox=box, workspace=ws)
    handle = _encode_handle("execute", "sess-x", key)
    ctx = AgentContext(ticket=_ticket(), resume_handle=handle)
    a = ClaudeCodeAdapter()

    assert a._resume_session_for("execute", ctx, box, ws) == "sess-x"  # matching phase → resume
    assert a._resume_session_for("plan", ctx, box, ws) == ""           # other phase → cold
    assert a._resume_session_for("execute", AgentContext(ticket=_ticket()), box, ws) == ""


def test_resume_session_cold_when_restore_fails(tmp_path, monkeypatch):
    # Handle points at state that's gone → we must NOT pass --resume (it would error); run cold.
    monkeypatch.setenv("OPENFACTORY_RESUME_BUCKET", "b")
    box, ws, _ = _box_with_home(tmp_path, monkeypatch)

    class _BoomS3:
        def get_object(self, **_):
            raise RuntimeError("NoSuchKey")

    boto3 = add_ons.sdk("boto3", "openfactory/adapters/agent/s3_session_store.py")
    monkeypatch.setattr(boto3, "client", lambda svc: _BoomS3())
    handle = _encode_handle("execute", "sess-x", "resume/o-app/40/sess-x.tar.gz")
    ctx = AgentContext(ticket=_ticket(), resume_handle=handle)
    assert ClaudeCodeAdapter()._resume_session_for("execute", ctx, box, ws) == ""


def test_resume_is_cold_when_there_is_no_box_to_restore_into(tmp_path, monkeypatch):
    """A session belongs to a box. Asked without one — as every judging call is — the answer is
    cold, never the orchestrator's own home standing in for the box's."""
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    box, ws, _ = _box_with_home(tmp_path, monkeypatch, session="sess-x")
    key = _snapshot_session("sess-x", "o-app", "40", sandbox=box, workspace=ws)
    ctx = AgentContext(ticket=_ticket(), resume_handle=_encode_handle("execute", "sess-x", key))

    assert ClaudeCodeAdapter()._resume_session_for("execute", ctx) == ""


# ---- session id capture from the stream -----------------------------------------------------

def test_parse_stream_captures_session_id_from_result():
    out = "\n".join([
        json.dumps({"type": "system", "subtype": "init", "session_id": "sess-42"}),
        json.dumps({"type": "result", "subtype": "success", "result": "done",
                    "is_error": False, "session_id": "sess-42", "total_cost_usd": 0.1}),
    ])
    res = _parse_stream(0, out, allowed_tools=[])
    assert res.ok
    assert res.resume_handle == "sess-42"  # carried so a later pause can resume it


def test_parse_stream_captures_session_id_even_without_result_event():
    # A hard cutoff can leave no result event; the init event's session_id must still survive.
    out = json.dumps({"type": "system", "subtype": "init", "session_id": "sess-99"})
    res = _parse_stream(1, out, allowed_tools=[])
    assert res.resume_handle == "sess-99"


# ---- end-to-end through _invoke: pause snapshots + upgrades the handle; resume applies it ----

def test_invoke_on_ratelimit_pause_snapshots_and_encodes_handle(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENFACTORY_RESUME_BUCKET", raising=False)
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("OPENFACTORY_AGENT_TOKENS", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "solo")
    box, ws, _ = _box_with_home(tmp_path, monkeypatch, session="sess-live")

    a = ClaudeCodeAdapter()
    monkeypatch.setattr(a, "_invoke_once", lambda *ar, **k: AgentRunResult(
        ok=False, pause_reason="rate_limit", retry_at="16:00", resume_handle="sess-live"))
    ctx = AgentContext(ticket=_ticket())
    res = a._invoke(box, ws, "p", "execute", tools=[], model=None, context=ctx)

    assert res.pause_reason == "rate_limit"
    d = _decode_handle(res.resume_handle)
    assert d and d["phase"] == "execute" and d["session"] == "sess-live"
    assert d["state_key"] == "resume/o-app/-40/sess-live.tar.gz"  # _safe: #40 → -40
    assert (tmp_path / "store" / d["state_key"]).is_file()  # the session was actually kept


def test_invoke_resume_passes_matching_session_to_cli(tmp_path, monkeypatch):
    # On resume, _invoke must hand the paused session to _invoke_once (→ --resume) for the
    # matching phase. Proves the continue path is wired end-to-end inside the adapter.
    monkeypatch.delenv("OPENFACTORY_RESUME_BUCKET", raising=False)
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("OPENFACTORY_AGENT_TOKENS", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "solo")
    box, ws, _ = _box_with_home(tmp_path, monkeypatch, session="sess-x")
    key = _snapshot_session("sess-x", "o-app", "40", sandbox=box, workspace=ws)
    handle = _encode_handle("execute", "sess-x", key)

    a = ClaudeCodeAdapter()
    got = {}

    def spy_once(sandbox, workspace, prompt, phase, *, tools, model, context, resume_session=""):
        got["resume_session"] = resume_session
        return AgentRunResult(ok=True, summary="continued")

    monkeypatch.setattr(a, "_invoke_once", spy_once)
    ctx = AgentContext(ticket=_ticket(), resume_handle=handle)
    res = a._invoke(box, ws, "p", "execute", tools=[], model=None, context=ctx)

    assert res.ok
    assert got["resume_session"] == "sess-x"  # the session was resumed, not started cold


def test_invoke_still_pauses_when_the_session_cannot_be_kept(tmp_path, monkeypatch):
    # Nothing to snapshot (the harness wrote no session): the pause still works and the handle
    # carries an empty state_key, so the resume knows to run cold rather than to error.
    monkeypatch.delenv("OPENFACTORY_RESUME_BUCKET", raising=False)
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("OPENFACTORY_AGENT_TOKENS", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "solo")
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    (tmp_path / "empty-home").mkdir()
    from openfactory.adapters.sandbox import WorktreeSandbox
    from openfactory.adapters.sandbox.base import Workspace

    work = tmp_path / "work2"
    work.mkdir()
    box = WorktreeSandbox(root=tmp_path / "wt2")
    ws = Workspace(path=work, host_path=work, branch="b", base_branch="main")

    a = ClaudeCodeAdapter()
    monkeypatch.setattr(a, "_invoke_once", lambda *ar, **k: AgentRunResult(
        ok=False, pause_reason="rate_limit", resume_handle="sess-live"))
    res = a._invoke(box, ws, "p", "execute", tools=[], model=None,
                    context=AgentContext(ticket=_ticket()))
    d = _decode_handle(res.resume_handle)
    assert d and d["phase"] == "execute" and d["state_key"] == ""  # cold resume marker


def test_resume_gate_requires_the_session_transcript(tmp_path, monkeypatch):
    # Audit HIGH: passing --resume for a session the CLI can't find ERRORS the invocation,
    # turning a resumable pause into a bogus hold. The gate must run cold when the restored
    # state doesn't actually contain <session>.jsonl — and it is asked IN THE BOX, because that
    # is the filesystem the CLI will read it from.
    monkeypatch.delenv("OPENFACTORY_RESUME_BUCKET", raising=False)
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    box, ws, home = _box_with_home(tmp_path, monkeypatch, session="OTHER-session")
    key = _snapshot_session("sess-x", "o-app", "40", sandbox=box, workspace=ws)
    handle = _encode_handle("execute", "sess-x", key)
    ctx = AgentContext(ticket=_ticket(), resume_handle=handle)

    assert ClaudeCodeAdapter()._resume_session_for("execute", ctx, box, ws) == ""  # cold, not broken


def test_snapshot_scopes_to_projects_and_skips_symlinks(tmp_path, monkeypatch):
    # Audit MED/LOW: the archive must contain ONLY projects/ (never credentials/settings) and no
    # symlinks (agent-writable HOME → restored symlinks would be a persistence channel).
    import io
    import tarfile

    monkeypatch.delenv("OPENFACTORY_RESUME_BUCKET", raising=False)
    monkeypatch.setenv("OPENFACTORY_RESUME_DIR", str(tmp_path / "store"))
    box, ws, home = _box_with_home(tmp_path, monkeypatch, session="sess-1")
    claude = home / ".claude"
    (claude / ".credentials.json").write_text("SECRET\n")
    (claude / "settings.json").write_text("{}\n")
    (claude / "projects" / "p1" / "link").symlink_to("/etc/passwd")

    key = _snapshot_session("sess-1", "o-app", "40", sandbox=box, workspace=ws)
    blob = (tmp_path / "store" / key).read_bytes()
    names = tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz").getnames()
    assert any("sess-1.jsonl" in n for n in names)  # the transcript is there
    assert not any("credentials" in n or "settings" in n for n in names)  # secrets are NOT
    assert not any(n.endswith("/link") for n in names)  # symlinks skipped
