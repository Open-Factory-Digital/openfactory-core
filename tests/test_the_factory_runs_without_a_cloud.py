"""The factory RUNS with no cloud, not merely IMPORTS with no cloud.

`test_the_core_does_not_need_a_cloud.py` guards three things a careless commit can undo: no cloud
SDK in the core dependencies, every `boto3` import function-level, the default sinks cloud-free.
All three are about LOADING. It proves a stranger's `pip install` works and their `import openfactory`
works — and stops there.

WHAT IT CANNOT SEE is a code path that reaches for a vendor at RUN time. A journal that writes to
CloudWatch unconditionally, a metrics sink that resolves to DynamoDB by inference, a memory read
that assumes a table: none of those touch module scope, so the import guard is green over every
one of them, and the failure arrives on the client's first ticket rather than on our build.

That gap is this repository's signature defect in its most expensive form — green in every test,
broken only where somebody pays us — and it is the one the product owner named:

    *"acho que temos que descolar totalmente da versão que está na nuvem."*

So this file takes a ticket ALL THE WAY THROUGH the factory — spec validation, the agent, the
gates, the pull request, the reviewer and the merge — inside a subprocess where every cloud SDK
refuses to import. Nothing is stubbed to make it pass: the run uses the real `JobRunner`, the real
`WorktreeSandbox` and a real git repository, exactly as `test_walking_skeleton` does.

THE SPINE TESTS ARE BORROWED, NOT COPIED. A second copy of "what a full run looks like" would
drift from the first, and the copy is always the one that stops covering the interesting case. The
probe imports `test_walking_skeleton` and runs ITS tests, so anything that file learns tomorrow is
proved cloud-free the same day.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Kept in step with the import guard by IMPORTING it rather than repeating it — two lists of
#: "what counts as a cloud" would disagree the first time somebody adds a vendor to one of them.
from tests.test_the_core_does_not_need_a_cloud import CLOUD_SDKS  # noqa: E402

#: The spine, from the ticket to the merge. Each is an EXISTING test that already runs the real
#: orchestrator against a real git repo — what is new is the world they run in.
#:
#: `test_auto_policy_merges_when_safe` is the one that matters most and the reason the scope goes
#: this far: it is the only one that reaches `MERGED`, which is where the tail of the run lives —
#: the part a client sees last and we are least likely to exercise.
_SPINE = (
    "test_full_spine_opens_pr",
    "test_reviewer_verdict_is_attached_and_state_walked",
    "test_journal_captures_states_actions_and_validations",
    "test_auto_policy_merges_when_safe",
)


def _probe(body: str) -> str:
    """A subprocess that refuses every cloud SDK, with `body` run inside it.

    THE BLOCK IS ON `__import__`, not on `sys.modules`, because a lazy import inside a function is
    exactly the shape this file exists to catch — it happens long after the module loaded, and
    only a live hook is present when it fires.
    """
    return textwrap.dedent(f"""
        import builtins, sys, tempfile
        from pathlib import Path

        real = builtins.__import__
        BLOCKED = {CLOUD_SDKS!r}
        reached = []

        def guarded(name, *a, **k):
            if name.split(".")[0].replace("_", "-") in BLOCKED:
                reached.append(name)
                raise ImportError(f"{{name}} is not installed on this deployment")
            return real(name, *a, **k)

        builtins.__import__ = guarded
        sys.path.insert(0, "tests")
        {body}
    """)


def _run(probe: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                          cwd=str(ROOT), timeout=600)


def test_this_probe_can_SEE_a_run_that_reaches_for_the_cloud():
    """THE POSITIVE TWIN, AND IT COMES FIRST. Every assertion below is of the form "the run
    finished", which a probe that never blocked anything satisfies perfectly — and this repository
    has shipped guards that were green over live defects for exactly that reason, three times.

    So: a body that does what the defect would do — a lazy import, inside a function, long after
    module load — must fail the probe and be REPORTED as the cloud reaching, not as some other
    crash."""
    done = _run(_probe("""
        def a_path_the_import_guard_cannot_see():
            import boto3            # noqa: F401 — the shape of the defect
            return "reached AWS"

        try:
            a_path_the_import_guard_cannot_see()
        except ImportError:
            print("BLOCKED:", reached)
            raise SystemExit(3)
        print("NOT BLOCKED — the probe is decoration")
    """))

    assert done.returncode == 3, (
        f"the probe let a function-level cloud import through, so every other test in this file "
        f"proves nothing:\n{done.stdout[-800:]}\n{done.stderr[-800:]}")
    assert "boto3" in done.stdout, done.stdout


@pytest.mark.parametrize("name", _SPINE)
def test_a_ticket_crosses_the_WHOLE_factory_with_every_cloud_SDK_BLOCKED(name):
    """One ticket, from the board to the merge, on a deployment that has no cloud account.

    Driven through `test_walking_skeleton`'s own fixtures so this is the REAL spine: the real
    `JobRunner`, the real `WorktreeSandbox`, a real git repository with a real bare origin pushed
    to. The tracker, forge and agent are that file's fakes — deliberately, because they stand for
    GitHub and an LLM, neither of which is the axis under test here.

    `repo.__wrapped__` is the fixture's undecorated function: pytest cannot hand a fixture to a
    subprocess, and re-implementing it here would be the copy this file's docstring refuses.
    """
    done = _run(_probe(f"""
        import test_walking_skeleton as spine

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = spine.repo.__wrapped__(root)
            spine.{name}(repo, root)
        assert not reached, f"the run reached for {{reached}}"
        print("OK")
    """))

    assert done.returncode == 0 and "OK" in done.stdout, (
        f"`{name}` cannot run on a deployment without a cloud account. Everything below the "
        f"traceback ran with boto3 and friends refusing to import — which is what a stranger's "
        f"laptop and the OSS compose file look like:\n{done.stderr[-2500:]}")


def test_the_conversation_store_the_OSS_distribution_ships_records_AND_DELETES():
    """The obligation, exercised in the same world rather than asserted in ours.

    Deleting a client's conversation used to reach for DynamoDB by hand while recording went
    through the configured sink, so the right to be forgotten held on the one vendor we pay for.
    The unit tests for that fix run in a process where boto3 is importable; this runs it where it
    is not, which is the deployment the promise was broken on.
    """
    done = _run(_probe("""
        import os
        with tempfile.TemporaryDirectory() as tmp:
            os.environ.pop("OPENFACTORY_METRICS_TABLE", None)
            os.environ["OPENFACTORY_METRICS_SINK"] = "sqlite"
            os.environ["OPENFACTORY_METRICS_DB"] = str(Path(tmp) / "m.db")

            from openfactory.memory import transcript

            transcript.record("acme", thread="C1", role="person", text="o saldo vem errado")
            assert transcript.recent("acme", thread="C1"), "nothing was recorded"
            gone = transcript.forget_project("acme")
            assert gone == 1, gone
            assert transcript.recent("acme", thread="C1") == [], "the turns survived"
        assert not reached, f"the store reached for {reached}"
        print("OK")
    """))

    assert done.returncode == 0 and "OK" in done.stdout, (
        f"a client's conversation cannot be recorded and deleted without a cloud account:\n"
        f"{done.stderr[-2000:]}")
