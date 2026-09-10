"""One card, one machine, nothing hosted — the whole cycle (ADR-0049 slice 5).

`test_the_factory_runs_without_a_cloud.py` proves the spine runs where no cloud SDK will import.
This proves the promise #87 is about, which is larger and narrower at once: a person with a
repository, a terminal and their own coding-agent login runs the factory — no account at a forge,
no tracker, no PAT, no Docker, and **nothing leaves the machine**. So the probe blocks the cloud
SDKs *and every socket*: the harness is scripted, so a run that opens one is reaching for something
this deployment does not have.

WHAT IS DRIVEN, and all of it through the real doors: `openfactory project init` on a bare path,
`act card_create`, `act card_move` to TO-DO, `poll --sandbox worktree`. Then the platform's own
work: spec validation, the worktree box, the agent, the manifest's gates against the file the agent
really wrote, the SHARED `HarnessReviewer`, the pull request in `board.db`, the fast-forward into
`main`, and the card in Done.

THE THREE ENDINGS ARE ALL HERE, because two of them are where the money is:

  · it lands — and the card reaches **Done**, which the attended driver could not do until this
    slice (`after_merge.py`);
  · the person has an uncommitted edit over the same file — the merge is refused in **git's own
    sentence**, the pull request stays open and their working tree is untouched;
  · the agent hits a usage limit with work already written — the pass **keeps** it, and the next
    poll finishes the job.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import textwrap

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Kept in step with the import guard by IMPORTING it — two lists of "what counts as a cloud"
#: would disagree the first time somebody adds a vendor to one of them.
from tests.test_the_core_does_not_need_a_cloud import CLOUD_SDKS  # noqa: E402


def _probe(body: str) -> str:
    """A subprocess where no cloud SDK imports and no socket opens, with `body` run inside it.

    THE SOCKET BLOCK IS THE NEW HALF, and it is aimed at LEAVING rather than at sockets: every
    client in this process — urllib, httpx, a Temporal client, any SDK — reaches the network
    through `connect`, `create_connection` or a name lookup, so all three are refused and each one
    records what was dialled. Constructing a socket is deliberately still allowed: asyncio builds
    its own self-pipe out of one, and the action layer is async, so a block on the CONSTRUCTOR
    fails the run on the platform's own local machinery and proves nothing about the network.
    """
    return textwrap.dedent(f"""
        import builtins, socket, sys, tempfile
        from pathlib import Path

        real = builtins.__import__
        BLOCKED = {CLOUD_SDKS!r}
        reached, dialled = [], []

        def guarded(name, *a, **k):
            if name.split(".")[0].replace("_", "-") in BLOCKED:
                reached.append(name)
                raise ImportError(f"{{name}} is not installed on this deployment")
            return real(name, *a, **k)

        def no_connect(self, address, *a, **k):
            dialled.append(f"connect {{address}}")
            raise OSError("this deployment has no network")

        def no_connection(address, *a, **k):
            dialled.append(f"create_connection {{address}}")
            raise OSError("this deployment has no network")

        def no_dns(host, *a, **k):
            dialled.append(f"getaddrinfo {{host}}")
            raise OSError("this deployment resolves no names")

        builtins.__import__ = guarded
        socket.socket.connect = no_connect
        socket.socket.connect_ex = no_connect
        socket.create_connection = no_connection
        socket.getaddrinfo = no_dns
        sys.path.insert(0, "tests")
    """) + textwrap.dedent(body)


def _run(probe: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                          cwd=str(ROOT), timeout=900)


def _ok(done: subprocess.CompletedProcess, what: str) -> None:
    assert done.returncode == 0 and "OK" in done.stdout, (
        f"{what}\n--- stdout ---\n{done.stdout[-3000:]}\n--- stderr ---\n{done.stderr[-3000:]}")


# ── the probe's own twins: a guard that cannot see the defect proves nothing ─────────────────────

def test_the_probe_can_SEE_a_run_that_reaches_for_the_cloud():
    """Every assertion below is of the form "the run finished", which a probe that blocked
    nothing satisfies perfectly. This repository has shipped guards that were green over live
    defects for exactly that reason."""
    done = _run(_probe("""
        def a_path_the_import_guard_cannot_see():
            import boto3            # noqa: F401 — the shape of the defect
            return "reached AWS"

        try:
            a_path_the_import_guard_cannot_see()
        except ImportError:
            print("BLOCKED:", reached); raise SystemExit(3)
        print("NOT BLOCKED — the probe is decoration")
    """))

    assert done.returncode == 3, done.stdout + done.stderr
    assert "boto3" in done.stdout


def test_the_probe_can_SEE_a_run_that_opens_a_socket():
    """The twin for the half this file adds. A deployment that reaches the network fails HERE,
    named, rather than passing quietly on a laptop that happens to be online."""
    done = _run(_probe("""
import socket as s
try:
    s.create_connection(("example.invalid", 443), timeout=1)
except OSError:
    print("BLOCKED:", dialled)
    try:
        s.socket().connect(("127.0.0.1", 9))
    except OSError:
        print("BLOCKED TOO:", dialled)
        raise SystemExit(3)
print("NOT BLOCKED — the socket hook is decoration")
"""))

    assert done.returncode == 3, done.stdout + done.stderr
    assert "create_connection" in done.stdout and "connect (" in done.stdout


# ── the cycle ───────────────────────────────────────────────────────────────────────────────────

#: The first hour, as a person types it: register the repository, write a card, queue it. Every
#: line is a real door — nothing here reaches into the registry or the board by hand.
_SETUP = """
    import one_machine as om
    root = Path(tmp)
    repo = om.a_repository(root)
    om.a_deployment(root)
    om.register_the_harness({harness})
    code, out = om.cli("project", "init", "myapp", str(repo))
    assert code == 0, out
    om.plug_the_project_in(repo, merge_policy="{policy}")
    code, out = om.cli("act", "card_create", "-p", "myapp", "-P", "title=Add the feature",
                       "-P", f"body={{om.CARD_BODY}}")
    assert code == 0, out
    code, out = om.cli("act", "card_move", "-p", "myapp", "-i", "1", "-P", "column=TO-DO")
    assert code == 0, out
"""

_NOTHING_LEFT = """
assert not reached, f"the run reached for {reached}"
assert not dialled, f"the run dialled {dialled}"
print("OK")
"""


def test_a_card_crosses_the_WHOLE_factory_on_one_machine():
    done = _run(_probe("""
with tempfile.TemporaryDirectory() as tmp:
""" + _SETUP.format(harness="", policy="auto") + """
    code, out = om.cli("poll", "myapp", "--sandbox", "worktree")
    assert code == 0, out

    # the change is IN the person's own repository, on their base branch
    log = om.git(repo, "log", "--oneline", "-2", "main").stdout
    assert "Add the feature" in log, log
    assert (repo / om.FEATURE).read_text().strip() == om.VALUE
    # nothing of theirs was disturbed by the fast-forward
    assert om.git(repo, "status", "--porcelain").stdout == ""
    # the pull request is a row in the file beside the registry, and it is merged
    pr = om.pull_request(root)
    assert pr["state"] == "merged", pr
    assert pr["head"] == "openfactory/1" and pr["base"] == "main"
    # and the card is in DONE — the ending the attended driver could not reach
    assert om.card_column(root) == "done", om.card_column(root)
""" + _NOTHING_LEFT))

    _ok(done, "a card cannot cross the factory on one machine with nothing hosted")


def test_a_persons_uncommitted_edit_REFUSES_the_merge_in_gits_own_words():
    """The one thing a factory that merges into somebody's own checkout must never do is
    overwrite what they were in the middle of. Git refuses it; what this proves is that the
    refusal REACHES the person — on the card, in git's words — and that the tree is exactly as
    they left it."""
    done = _run(_probe("""
with tempfile.TemporaryDirectory() as tmp:
""" + _SETUP.format(harness="", policy="auto") + """
    mine = repo / om.FEATURE
    mine.write_text("VALUE = 'mine, uncommitted'\\n")

    code, out = om.cli("poll", "myapp", "--sandbox", "worktree")
    assert code == 0, out

    assert mine.read_text() == "VALUE = 'mine, uncommitted'\\n", "their own work was touched"
    assert "Add the feature" not in om.git(repo, "log", "--oneline", "main").stdout
    pr = om.pull_request(root)
    assert pr["state"] == "open", pr
    assert om.card_column(root) == "needs_action", om.card_column(root)
    said = om.what_the_card_was_told(root)
    assert "overwritten by merge" in said, said
    assert om.FEATURE in said, said
""" + _NOTHING_LEFT))

    _ok(done, "a refused merge did not reach the person, or touched their tree")


def test_a_PAUSE_keeps_the_work_and_the_next_poll_finishes_the_job():
    """ADR-0013 D1 and slice 3b's data-loss defect, end to end: the harness stops at a usage limit
    with real edits already written. The pass keeps them on the job branch, and the next poll
    finishes the job instead of paying for the first pass twice."""
    done = _run(_probe("""
with tempfile.TemporaryDirectory() as tmp:
""" + _SETUP.format(harness="marker=Path(tmp) / 'paused-once', pauses_first=True",
                    policy="auto") + """
    code, out = om.cli("poll", "myapp", "--sandbox", "worktree")
    assert code == 0, out

    kept = om.git(repo, "show", f"openfactory/1:{om.FEATURE}").stdout
    assert "quota ran out" in kept, f"the paused pass lost its work: {kept!r}"

    # THE VENDOR'S RESET DOES NOT SHORTEN THE PLATFORM'S BACKOFF (#164). The harness said the
    # window reopened in the year 2000; the scheduler still holds the job for its own hour,
    # because two answers to "when may this resume" is how a surface comes to fire into a window
    # that is still closed.
    import time as clock
    from openfactory.registry import ProjectRegistry
    from openfactory.scheduler import ready_to_resume

    mine = ProjectRegistry().get("myapp")
    assert ready_to_resume(mine, clock.time()) == [], "resumed on the vendor's word"
    assert ready_to_resume(mine, clock.time() + 3700) == ["1"], "the backoff never comes round"

    # an hour later, on the poller's own clock — the cron tick that finds it ready
    was = clock.time
    clock.time = lambda: was() + 3700
    code, out = om.cli("poll", "myapp", "--sandbox", "worktree")
    clock.time = was
    assert code == 0, out
    assert om.card_column(root) == "done", om.card_column(root)
    assert (repo / om.FEATURE).read_text().strip() == om.VALUE
""" + _NOTHING_LEFT))

    _ok(done, "a paused pass lost its work, or the next poll could not finish the job")


# ── one sentence, two drivers ───────────────────────────────────────────────────────────────────

def test_the_merge_is_the_end_ONLY_when_nothing_follows():
    """The rule the attended driver just learned, stated where both can ask it. A project that
    declares a deploy watch or a promotion chain has more road: settling it at the merge would
    close a card whose deploy nobody has looked at yet."""
    from openfactory import after_merge

    assert after_merge.nothing_follows(deploy=None, environments=())
    assert not after_merge.nothing_follows(deploy=object(), environments=())
    assert not after_merge.nothing_follows(deploy=None, environments=("staging",))
    assert not after_merge.nothing_follows(deploy=None, environments=(), promote=True)


def test_BOTH_drivers_say_the_same_thing_and_neither_keeps_a_copy():
    """The durable workflow learned this on 2026-08-16 and the attended driver did not, which is
    how one card could end in *Done* and its twin in *In review* for ever. A second copy of the
    sentence is how they would drift apart again."""
    from openfactory import after_merge

    durable = (ROOT / "openfactory" / "runtime" / "temporal" / "workflow.py").read_text()
    attended = (ROOT / "openfactory" / "orchestrator" / "machine.py").read_text()

    assert "after_merge.NOTHING_FOLLOWS" in durable and "after_merge.NOTHING_FOLLOWS" in attended
    tell = "the factory is not looking"
    assert tell in after_merge.NOTHING_FOLLOWS
    assert tell not in durable, "the durable driver kept a copy of the sentence"
    assert tell not in attended, "the attended driver wrote its own"
