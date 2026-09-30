"""A human gate's answer is acted on only with the panel's seal (`openfactory.gate_seal`).

THE ADVISORY. `JobWorkflow.approve_prod` and `JobWorkflow.human_merge_gate` authenticated the
person in the PANEL and then trusted whatever `approver` / `by` reached the workflow — so a signal
sent straight to the engine, which compose published on every interface with no authentication,
approved a production release without the password the gate is documented to require.

Held here: the seal itself (round trip, every field bound, the job bound, expiry, a key the other
half does not share), and that the panel's two senders seal exactly what the worker will check.
The workflow half — a forged answer releases and merges nothing, and leaves the gate open — is
in `test_temporal_workflow.py` and `test_the_merge_gate_is_heard_on_every_path.py`, which need
an engine.
"""

from __future__ import annotations

import asyncio
import os
import stat

import pytest

from openfactory import gate_seal

WF = "openfactory-job-p-10"


@pytest.fixture(autouse=True)
def _no_declared_key(monkeypatch):
    monkeypatch.delenv(gate_seal.VARIABLE, raising=False)


def test_a_sealed_answer_verifies():
    seal = gate_seal.seal(gate_seal.APPROVE_PROD, WF, "1.2.0", "alice", "ship it")
    assert gate_seal.refusal(seal, gate_seal.APPROVE_PROD, WF, "1.2.0", "alice", "ship it") == ""


@pytest.mark.parametrize("changed", [
    (gate_seal.APPROVE_PROD, WF, "1.2.1", "alice", "ship it"),        # another version
    (gate_seal.APPROVE_PROD, WF, "1.2.0", "mallory", "ship it"),      # another approver
    (gate_seal.APPROVE_PROD, WF, "1.2.0", "alice", "ship it!"),       # another comment
    (gate_seal.APPROVE_PROD, "openfactory-job-p-11", "1.2.0", "alice", "ship it"),  # another job
    (gate_seal.MERGE_GATE, WF, "1.2.0", "alice", "ship it"),          # another gate
], ids=["version", "approver", "comment", "job", "gate"])
def test_a_seal_binds_every_field_the_workflow_acts_on(changed):
    seal = gate_seal.seal(gate_seal.APPROVE_PROD, WF, "1.2.0", "alice", "ship it")
    kind, wf, *fields = changed
    assert "does not match" in gate_seal.refusal(seal, kind, wf, *fields)


def test_fields_cannot_be_shifted_across_their_boundaries():
    """A separator-joined message would let `("a,b", "c")` and `("a", "b,c")` share a seal."""
    seal = gate_seal.seal(gate_seal.MERGE_GATE, WF, "adjust", "x,y", "z")
    assert gate_seal.refusal(seal, gate_seal.MERGE_GATE, WF, "adjust", "x", "y,z")


@pytest.mark.parametrize("token, reason", [
    ("", "carries no seal"),
    ("garbage", "unknown version"),
    ("v1.99999999999.abc", "malformed"),
    ("v1.notanumber.n.abc", "malformed"),
    ("v9.99999999999.n.abc", "unknown version"),
])
def test_what_is_not_a_seal_is_refused_by_name(token, reason):
    assert reason in gate_seal.refusal(token, gate_seal.APPROVE_PROD, WF, "1", "a", "")


def test_a_seal_expires():
    seal = gate_seal.seal(gate_seal.APPROVE_PROD, WF, "1", "a", "", now=1_000_000)
    assert gate_seal.refusal(seal, gate_seal.APPROVE_PROD, WF, "1", "a", "",
                             now=1_000_000 + gate_seal.TTL_SECONDS - 1) == ""
    assert "expired" in gate_seal.refusal(seal, gate_seal.APPROVE_PROD, WF, "1", "a", "",
                                          now=1_000_000 + gate_seal.TTL_SECONDS + 1)


def test_the_key_is_made_once_beside_the_registry_and_readable_by_its_owner_only(
        tmp_path, monkeypatch):
    """Compose mounts the registry's directory into the panel AND the worker — the one place both
    halves can find the same key without anybody writing one down."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "state" / "registry.yaml"))
    seal = gate_seal.seal(gate_seal.APPROVE_PROD, WF, "1", "a", "")
    key = tmp_path / "state" / gate_seal.FILENAME
    assert key.exists()
    assert stat.S_IMODE(os.stat(key).st_mode) == 0o600
    first = key.read_text()
    assert gate_seal.refusal(seal, gate_seal.APPROVE_PROD, WF, "1", "a", "") == ""
    assert key.read_text() == first, "the key was rewritten — every seal in flight would break"


def test_two_halves_with_different_keys_refuse_and_say_why(tmp_path, monkeypatch):
    monkeypatch.setenv(gate_seal.VARIABLE, "the-panels-key")
    seal = gate_seal.seal(gate_seal.APPROVE_PROD, WF, "1", "a", "")
    monkeypatch.setenv(gate_seal.VARIABLE, "the-workers-key")
    refused = gate_seal.refusal(seal, gate_seal.APPROVE_PROD, WF, "1", "a", "")
    assert "different gate keys" in refused and gate_seal.VARIABLE in refused


def test_an_empty_key_file_is_never_an_empty_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    (tmp_path / gate_seal.FILENAME).write_text("")
    with pytest.raises(RuntimeError, match="empty"):
        gate_seal.seal(gate_seal.APPROVE_PROD, WF, "1", "a", "")
    assert "cannot be read" in gate_seal.refusal("v1.99999999999.n.ab", gate_seal.APPROVE_PROD,
                                                 WF, "1", "a", "")


# ── the panel's two senders seal exactly what the worker checks ─────────────────────────────────

class _Handle:
    def __init__(self, answers):
        self.answers, self.signals = answers, []

    async def query(self, _query):
        return self.answers

    async def signal(self, signal, args):
        self.signals.append((signal, list(args)))


class _Client:
    def __init__(self, handle):
        self.handle, self.ids = handle, []

    def get_workflow_handle(self, wf_id):
        self.ids.append(wf_id)
        return self.handle


def test_the_panels_approval_carries_a_seal_the_worker_accepts():
    from openfactory.runtime.temporal import view

    handle = _Handle(True)
    client = _Client(handle)
    asyncio.run(view.approve_job(client, "p", "10", version="1.2.0", approver="alice",
                                 comment="ship it"))
    (_, args), = handle.signals
    version, approver, comment, seal = args
    assert gate_seal.refusal(seal, gate_seal.APPROVE_PROD, client.ids[0],
                             version, approver, comment) == ""


def test_the_panels_merge_answer_carries_a_seal_the_worker_accepts():
    from openfactory.runtime.temporal import view

    handle = _Handle({"pr_url": "https://x/pr/1", "auto": False})
    client = _Client(handle)
    asyncio.run(view.answer_merge_gate(client, "p", "10", answer="adjust",
                                       instruction="rename it", by="alice"))
    (_, args), = handle.signals
    answer, instruction, by, seal = args
    assert gate_seal.refusal(seal, gate_seal.MERGE_GATE, client.ids[0],
                             answer, instruction, by) == ""


def test_two_seals_of_the_same_answer_are_two_seals():
    """The workflow spends a seal once; a person who presses Merge twice in one second has
    answered twice, and the second must not look like a copy of the first."""
    one = gate_seal.seal(gate_seal.MERGE_GATE, WF, "merge", "", "alice", now=1_000_000)
    two = gate_seal.seal(gate_seal.MERGE_GATE, WF, "merge", "", "alice", now=1_000_000)
    assert one != two
    for seal in (one, two):
        assert gate_seal.refusal(seal, gate_seal.MERGE_GATE, WF, "merge", "", "alice",
                                 now=1_000_000) == ""


def test_a_probes_seal_answers_no_gate():
    seal = gate_seal.seal(gate_seal.PROBE, WF, "probe")
    assert gate_seal.refusal(seal, gate_seal.APPROVE_PROD, WF, "probe")
    assert gate_seal.refusal(seal, gate_seal.MERGE_GATE, WF, "probe")


def test_box_env_refuses_to_carry_the_gate_key():
    """The container box is the door the seal DOES hold on — as long as no configuration hands a
    job the key. `box.env` is a list of names that cross into the box; this one may not."""
    from openfactory.adapters.sandbox.container import ContainerSandbox

    with pytest.raises(ValueError, match=gate_seal.VARIABLE):
        ContainerSandbox(image="x", project="p", extra_env=("SOME_TOKEN", gate_seal.VARIABLE))


def test_the_gate_key_is_scrubbed_from_the_worktree_workload(monkeypatch):
    from openfactory.adapters.sandbox.worktree import _scrubbed_env

    monkeypatch.setenv(gate_seal.VARIABLE, "the-key")
    assert gate_seal.VARIABLE not in _scrubbed_env()


# ── the doctor says whether the worker accepts this side's seals ────────────────────────────────

def test_the_doctor_says_when_the_worker_accepts():
    from openfactory import doctor

    assert "accepts" in doctor.gate_key_line(ask=lambda: "")


def test_the_doctor_says_when_the_worker_refuses_and_what_to_set():
    from openfactory import doctor

    line = doctor.gate_key_line(ask=lambda: "the answer's seal does not match")
    assert line.startswith("WARNING") and "does not match" in line and gate_seal.VARIABLE in line


def test_no_answer_from_the_worker_is_not_a_disagreement():
    from openfactory import doctor

    def silent():
        raise TimeoutError("no worker polled the queue")

    line = doctor.gate_key_line(ask=silent)
    assert "could not ask" in line and "WARNING" not in line


# ── a refused approval is said in the inbox ─────────────────────────────────────────────────────

def test_a_refused_approval_is_said_in_the_inbox():
    """The panel told the person "approved"; the worker refused it and the gate waits on. The
    inbox — every channel's reading of "does anything need me" — says why."""
    import openfactory.api.app as mod

    class _TV:
        ATTENTION_STATES = frozenset({"awaiting_prod_approval"})

        @staticmethod
        async def connect():
            return object()

        @staticmethod
        async def list_jobs(_c, _ns):
            return [{"project": "acme", "issue": "1", "title": "t",
                     "state": "awaiting_prod_approval", "action": None, "wedged": False,
                     "refused": "the answer's seal does not match"}]

        @staticmethod
        async def review_verdicts(_c, jobs):
            return {}

    old = mod._temporal
    mod._temporal = lambda: (_TV(), "addr", "ns")
    try:
        (item,) = asyncio.run(mod.inbox())
    finally:
        mod._temporal = old
    assert "not acted on" in item["note"] and "does not match" in item["note"], item
