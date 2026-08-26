"""The durable record says how a job ended — not what it was doing when the box died (#131).

THE PILOT'S OWN #89, read off his disk on 2026-08-17. Its journal, in full:

    … validating → reviewing → review: rejected (score 0) · advisory

and then nothing. What actually happened: `open_pr` raised — the branch carried zero commits,
which GitHub refuses — the workflow caught it and parked the job, the BOARD moved the card to
*Needs Action*, and the engine agreed. Only the file that outlives the engine never learned.

WHY IT IS NOT COSMETIC. Temporal's default namespace keeps **24 hours** of history. A day later
the engine held nothing, and this file was the only answer to "what happened to #89" — so the
panel's Recent runs reported a parked job as `reviewing`, and the floor told its operator
*"nothing shipped yet"* about a day on which it shipped two tickets. The record that exists
precisely BECAUSE the engine forgets was the one lying.

THE CAUSE IS STRUCTURAL, not a missing line. The journal is written by the in-box orchestrator;
the terminal state is decided by the WORKFLOW, after that box is gone — a crash, the rate-limit
ladder giving up, an operator's skip, an answered merge gate, a chain finishing at its last
stage. Writing it per-branch would be the same rule spread over a dozen sites, which is the
"one branch forgot" defect this platform has shipped seventeen times. So it is written at the ONE
exit every job passes through, and this file holds that seam shut.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from openfactory.contracts import JobState

# ── 1. the seam: one exit, every path ───────────────────────────────────────────────────────────

def test_EVERY_way_a_job_can_end_writes_its_outcome():
    """Derived from `run`'s own control flow: each `return` and each `raise` in it must be
    preceded by the journal call. A new terminal branch added later fails here rather than
    shipping another silent ending."""
    from openfactory.runtime.temporal.workflow import JobWorkflow

    body = ast.parse(inspect.cleandoc("\n" + inspect.getsource(JobWorkflow.run)))
    exits = [n for n in ast.walk(body) if isinstance(n, ast.Return | ast.Raise)]
    assert len(exits) >= 3, f"`run` has {len(exits)} exits — this guard is measuring nothing"

    text = ast.unparse(body)
    assert text.count("_journal_outcome") == len(exits), (
        f"`run` has {len(exits)} ways to end and journals {text.count('_journal_outcome')} of "
        f"them — the ones it misses vanish from the record the moment the engine forgets")


def test_the_normal_ending_carries_the_RESULT_state_and_not_a_guess():
    from openfactory.runtime.temporal.workflow import JobWorkflow

    src = inspect.getsource(JobWorkflow.run)
    assert "result.state.value" in src, (
        "the outcome is journalled as something other than what the job actually returned")


@pytest.mark.parametrize("ending,expect", [
    ("CancelledError", JobState.ON_HOLD),
    ("Exception", JobState.FAILED),
])
def test_an_ABNORMAL_ending_is_recorded_too(ending, expect):
    """#89 died on the crash path. A record that only covers the happy exits is the same lie
    with a smaller blast radius.

    Matched on the ENUM as the source spells it — asserting the string value would pass only
    while somebody happened to write the literal, which is the opposite of what this file wants."""
    from openfactory.runtime.temporal.workflow import JobWorkflow

    tree = ast.parse(inspect.cleandoc("\n" + inspect.getsource(JobWorkflow.run)))
    handler = next(h for n in ast.walk(tree) if isinstance(n, ast.Try) for h in n.handlers
                   if ending in ast.unparse(h.type))
    said = ast.unparse(handler)
    assert "_journal_outcome" in said, f"the {ending} path ends in silence"
    assert f"JobState.{expect.name}" in said, (
        f"the {ending} path records something other than {expect.value}")


def test_a_CANCELLED_job_records_through_the_cancellation():
    """An activity started while a workflow is being cancelled is dropped unless it is shielded —
    the rule `_cleanup` above it already pays for. A job an operator STOPPED is exactly the one
    whose record somebody goes looking for."""
    from openfactory.runtime.temporal.workflow import JobWorkflow

    tree = ast.parse(inspect.cleandoc("\n" + inspect.getsource(JobWorkflow.run)))
    handler = next(h for n in ast.walk(tree) if isinstance(n, ast.Try) for h in n.handlers
                   if "CancelledError" in ast.unparse(h.type))
    # ON THE JOURNAL'S OWN CALL, not on the handler as a whole. `"shield=True" in unparse(handler)`
    # was satisfied by the `_cleanup(params, shield=True)` sitting one line above — so deleting the
    # journal's shield left the guard green and the outcome of a cancelled job unrecorded. Found by
    # mutating it, on the same day an audit named this exact class.
    call = next(n for n in ast.walk(handler) if isinstance(n, ast.Call)
                and getattr(n.func, "attr", "") == "_journal_outcome")
    assert any(k.arg == "shield" and getattr(k.value, "value", None) is True
               for k in call.keywords), (
        "the outcome of a cancelled job is written by an activity the cancellation drops")
    assert "asyncio.shield" in inspect.getsource(JobWorkflow._journal_outcome)


def test_it_is_VERSIONED_because_it_is_a_new_command():
    """A new activity on a path in-flight jobs already replay diverges every one of them
    (TMPRL1100) — a failure this codebase has hit before and writes a rule about."""
    from openfactory.runtime.temporal.workflow import JobWorkflow

    src = inspect.getsource(JobWorkflow._journal_outcome)
    assert 'workflow.patched("journal-the-outcome")' in src
    gate = src.index('workflow.patched("journal-the-outcome")')
    assert src.index("execute_activity") > gate, (
        "the command is issued before the patch gate decides whether it may be")


def test_recording_NEVER_fails_the_job_it_describes():
    from openfactory.runtime.temporal.workflow import JobWorkflow

    src = inspect.getsource(JobWorkflow._journal_outcome)
    assert "except Exception" in src and "warning" in src, (
        "a journal that will not write now takes the job down with it, or does so in silence")


# ── 2. the write itself ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def journal(tmp_path, monkeypatch):
    """The real activity, writing to a real file, through the real path helper."""
    from openfactory.runtime.temporal import activities as act

    class Project:
        name = "acme"

    monkeypatch.setattr("openfactory.registry.ProjectRegistry.get", lambda self, n: Project())
    monkeypatch.setattr("openfactory.paths.project_log_dir", lambda p: tmp_path)
    monkeypatch.setattr(act, "ProjectRegistry", lambda: type("R", (), {"get": lambda s, n: Project()})())
    return tmp_path


def _run(**kw):
    import asyncio

    from openfactory.runtime.temporal.activities import record_outcome
    from openfactory.runtime.temporal.io import HoldSyncInput

    return asyncio.run(record_outcome(HoldSyncInput(project="acme", issue="89", **kw)))


def test_the_outcome_lands_in_the_jobs_own_journal(journal):
    import json

    assert _run(state="on_hold", note="gh pr create failed: No commits between main and x") \
        == "on_hold"

    written = [json.loads(ln) for ln in (journal / "89-events.jsonl").read_text().splitlines()]
    assert [e["kind"] for e in written] == ["state"]
    assert written[0]["message"] == "on_hold"
    assert "No commits between" in written[0]["data"]["reason"], (
        "the record says the job ended and not WHY — which is the half a person needs")
    assert written[0]["ticket_id"] == "#89"


def test_it_APPENDS_and_never_rewrites_what_the_run_recorded(journal):
    """The run WAS reviewing; that stays true. Append-only is how every record here works, and it
    is what lets somebody read the sequence rather than a final answer with no history."""
    path = journal / "89-events.jsonl"
    path.write_text('{"ts":"t","job_id":"#89","ticket_id":"#89","kind":"state",'
                    '"message":"reviewing","data":{}}\n')

    _run(state="on_hold", note="parked")

    lines = path.read_text().splitlines()
    assert len(lines) == 2 and "reviewing" in lines[0] and "on_hold" in lines[1]


def test_a_journal_that_cannot_be_written_does_not_fail_the_job(journal, monkeypatch, caplog):
    """The job has already ended and the board already knows. But it is LOGGED — a record that
    quietly stopped recording outcomes looks exactly like a quiet floor."""
    monkeypatch.setattr("openfactory.paths.project_log_dir",
                        lambda p: (_ for _ in ()).throw(OSError("read-only")))

    with caplog.at_level("WARNING"):
        assert _run(state="done") == "unrecorded"
    assert any("OPENFACTORY_OUTCOME_NOT_JOURNALLED" in r.getMessage() for r in caplog.records)


# ── 3. what the readers do with it ──────────────────────────────────────────────────────────────

def test_the_log_LIST_reports_the_last_state_the_journal_holds(journal):
    """`/api/jobs` derives a run's state from its journal — which is why the missing terminal
    event surfaced as the panel calling a parked job `reviewing`. With the outcome written, the
    same derivation tells the truth; nothing about the reader needed changing, and that is the
    point of fixing the cause."""
    import json

    path = journal / "89-events.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in [
        {"ts": "1", "job_id": "#89", "ticket_id": "#89", "kind": "state", "message": "reviewing",
         "data": {}},
    ]) + "\n")
    _run(state="on_hold", note="branch had zero commits")

    last_state = [json.loads(ln) for ln in path.read_text().splitlines()
                  if json.loads(ln)["kind"] == "state"][-1]
    assert last_state["message"] == "on_hold"
