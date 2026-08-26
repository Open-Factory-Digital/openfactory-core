"""The box can be read WHILE it runs, and it says whether it can (C-39, #82).

The tech-lead's arithmetic landed last round: `stream.pulses_of` turns a harness stream into
pulses and `watch.read_harness` turns pulses into named stalls. Both were reached only from the
FAILURE paths of the four adapters — the 4h wall and the no-result branch — so the answer arrived
after the pass was already over. The reason was one line in the port:

    subprocess.run(command, capture_output=True, ...)

`capture_output=True` means the output does not EXIST until the process exits. Every harness
narrates itself as JSON lines the entire time, and nobody was holding the other end.

WHAT IS PROVEN HERE, and it is deliberately not "a callback exists":

  * a line reaches a reader BEFORE the process ends — proven by making the process WAIT for
    something the reader does, so a buffered implementation cannot pass by luck or by timing;
  * `None` and `[]` stay different answers. `tail()` returning `[]` means read-and-nothing-new; a
    box that cannot read its own output returns `None`, and the `streams` trait says which it is
    before a watcher starts believing a stream of empty lists;
  * the return value did not move — same exit code, same text, now with stderr interleaved in the
    order it was actually written rather than appended in a block;
  * the wall keeps whatever was already written, ON BOTH BOXES. It did not: the container — the
    production box — called `timeout_result(command, timeout)` where the function takes three
    arguments, so at the four-hour wall the whole transcript was gone on the one run nobody can
    re-observe;
  * an observer that raises cannot end a four-hour pass;
  * the `streams` trait says what is true, checked AGAINST the implementation rather than beside
    it. A trait that claims a capability the box lacks is worse than no trait: a watcher attached
    to a box that silently drops the callback receives nothing, and nothing is indistinguishable
    from a healthy agent. That is this house's signature defect, and the card names it.
"""

from __future__ import annotations

import inspect
import shutil
import subprocess
import threading
import time

import pytest

from openfactory.adapters.sandbox.base import SandboxAdapter, Workspace
from openfactory.adapters.sandbox.container import ContainerSandbox
from openfactory.adapters.sandbox.registry import BOXES, box_traits, build_sandbox
from openfactory.adapters.sandbox.timeouts import TIMEOUT_EXIT, timed_out
from openfactory.adapters.sandbox.worktree import WorktreeSandbox


def _ws(path) -> Workspace:
    return Workspace(path=path, host_path=path, branch="sdlc/1", base_branch="main")


#: A command that CANNOT FINISH until the observer has acted on its first line. `gate` is created
#: by the callback, so an implementation that buffers until exit deadlocks and dies on the wall —
#: which is a loud, deterministic failure rather than a flaky timing assertion. This is the whole
#: liveness proof; everything else here is a property of the return value.
def _gated(gate) -> str:
    return f"echo first-line; while [ ! -f {gate} ]; do sleep 0.05; done; echo after-the-gate"


# ── the port's own shape: pull, and None ≠ [] ────────────────────────────────────────────────────

def test_a_reader_on_another_thread_sees_a_line_before_the_process_ends(tmp_path):
    """THE CONTRACT THE PORT ACTUALLY CARRIES. `run` blocks its caller for the whole pass — that is
    the four hours — so the only thing that can look inside them is another thread. It polls
    `tail()`, and the process cannot finish until the poller has acted on the first line."""
    box = WorktreeSandbox(root=tmp_path)
    gate = tmp_path / "gate"
    seen: list[str] = []
    stop = threading.Event()

    def poll() -> None:
        while not stop.is_set():
            new = box.tail()
            assert new is not None, "a local box can always read its own output"
            seen.extend(new)
            if any(line.startswith("first-line") for line in seen):
                gate.write_text("go")
            time.sleep(0.02)

    watcher = threading.Thread(target=poll, daemon=True)
    watcher.start()
    try:
        rc, out = box.run(workspace=_ws(tmp_path), command=_gated(gate), timeout=20)
    finally:
        stop.set()
        watcher.join(timeout=5)
    # THE LAST LINE IS DRAINED HERE, NOT ASSERTED OUT OF THE POLLER, AND WITHOUT THIS THE TEST IS
    # FLAKY — measured at roughly one run in ten. `after-the-gate` is written microseconds before
    # the process exits, so `run` can return and `stop` be set while the poller is inside its 20 ms
    # sleep; it then exits having never asked for that line. The property under test is that a line
    # reached a reader BEFORE the process ended, and that is carried entirely by `rc == 0` — the
    # command cannot finish unless the poller wrote the gate mid-run. A guard that fails one time in
    # ten teaches people to re-run it, which is how a real failure gets re-run too.
    seen.extend(box.tail() or [])

    assert rc == 0, f"the poller never saw a line — a buffered box deadlocks here: {out!r}"
    assert [line.rstrip("\n") for line in seen] == ["first-line", "after-the-gate"]


def test_tail_hands_over_each_line_once(tmp_path):
    """A cursor, not a snapshot: the second call must not repeat the first call's lines. A watcher
    that re-read the whole stream every tick would count one tool call as twenty and report a loop
    on every healthy pass."""
    box = WorktreeSandbox(root=tmp_path)
    box.run(workspace=_ws(tmp_path), command=r"printf 'a\nb\n'", timeout=20)

    assert [line.rstrip("\n") for line in box.tail()] == ["a", "b"]
    assert box.tail() == [], "read it, and there is nothing new — which is not the same as None"


def test_a_new_command_does_not_replay_the_previous_one(tmp_path):
    """One box runs `setup:`, then the harness, then `validate:`. A watcher polling across that
    boundary would read the setup's output as the agent's and measure a pass that never happened."""
    box = WorktreeSandbox(root=tmp_path)
    box.run(workspace=_ws(tmp_path), command="echo from-setup", timeout=20)
    box.run(workspace=_ws(tmp_path), command="echo from-the-agent", timeout=20)

    assert [line.rstrip("\n") for line in box.tail()] == ["from-the-agent"]


@pytest.mark.parametrize("kind", ["worktree", "container"])
def test_a_box_that_has_run_nothing_says_empty_not_unreadable(kind, tmp_path):
    """`[]` = I read, and there is nothing. `None` = I could not read. A box that has simply not
    started yet is the first, and answering `None` there would make every watcher treat a healthy
    idle box as blind — the same collapse in the other direction."""
    assert build_sandbox(kind, root=tmp_path, image="x").tail() == []


# ── the push convenience, over the same lines ────────────────────────────────────────────────────

def test_the_worktree_box_hands_over_a_line_before_the_process_ends(tmp_path):
    gate = tmp_path / "gate"
    seen: list[str] = []

    def observe(line: str) -> None:
        seen.append(line)
        if line == "first-line":
            gate.write_text("go")  # only reachable if the line arrived DURING the run

    rc, out = WorktreeSandbox(root=tmp_path).run(
        workspace=_ws(tmp_path), command=_gated(gate), timeout=20, on_output=observe)

    assert rc == 0, f"the run did not finish — a buffered box deadlocks here: {out!r}"
    assert seen == ["first-line", "after-the-gate"]
    assert not timed_out(rc, out)


def test_the_observer_gets_whole_lines_without_their_newline(tmp_path):
    """A JSONL reader is handed one event per call; a half line would be unparseable and a line
    with its newline still attached would make every consumer strip it."""
    seen: list[str] = []
    WorktreeSandbox(root=tmp_path).run(
        workspace=_ws(tmp_path), command=r"printf 'a\nbb\nccc\n'", timeout=20,
        on_output=seen.append)
    assert seen == ["a", "bb", "ccc"]


def test_a_run_with_no_observer_behaves_exactly_as_before(tmp_path):
    """Backwards compatible by construction: every existing call site passes nothing."""
    rc, out = WorktreeSandbox(root=tmp_path).run(
        workspace=_ws(tmp_path), command="echo out; echo err >&2; exit 7", timeout=20)
    assert rc == 7
    assert "out" in out and "err" in out


def test_stdout_and_stderr_arrive_in_the_order_they_were_written(tmp_path):
    """`capture_output=True` hands back two strings, so both boxes returned every stdout line and
    THEN every stderr line — an order the process never produced. Merging at the pipe is what makes
    a live reader possible at all, and it also stops a failed validation from being read backwards.
    """
    seen: list[str] = []
    _, out = WorktreeSandbox(root=tmp_path).run(
        workspace=_ws(tmp_path), command="echo one; echo two >&2; echo three", timeout=20,
        on_output=seen.append)
    assert seen == ["one", "two", "three"]
    assert out.splitlines() == ["one", "two", "three"]


# ── the wall keeps what was already written — the container's own defect ─────────────────────────

def test_the_worktree_wall_keeps_the_partial_output(tmp_path):
    """THE MARKER IS NOT IN THE COMMAND, and that is not fussiness — it is what this guard is for.

    Written first as `echo how-far-it-got; …` it passed against a mutation that discarded the
    partial output entirely, because `timeout_result` echoes the command line (`$ echo
    how-far-it-got`) into its own header. The assertion was reading the question back as the
    answer. So the marker is produced by the process and appears nowhere in what was asked of it."""
    (tmp_path / "trace.txt").write_text("how-far-it-got\n")
    rc, out = WorktreeSandbox(root=tmp_path).run(
        workspace=_ws(tmp_path), command="cat trace.txt; exec sleep 30", timeout=2)
    assert rc == TIMEOUT_EXIT and timed_out(rc, out)
    assert "how-far-it-got" in out


def test_the_container_wall_keeps_the_partial_output_too(tmp_path, monkeypatch):
    """THE PRODUCTION BOX WAS THE ONE THAT THREW IT AWAY.

    `except subprocess.TimeoutExpired: return timeout_result(command, timeout)` — two arguments to
    a function that takes three. The worktree passed its partial output and the container passed
    none, so the four-hour wall arrived on the box that matters most with the transcript already
    discarded, and `read_harness` was handed `[]` — which it correctly refuses to read as an idle
    agent, meaning the honest answer to "what did it do for four hours?" was *nothing can be said*.

    Docker is substituted at `Popen`, NOT at the sandbox: the argv is thrown away and a real local
    shell runs in its place, so everything under test — the timeout, the kill, the drain, the
    partial capture — is the code that runs in production against a real process. The docker hop
    itself is proven separately, against a real container, below."""
    box = ContainerSandbox(image="irrelevant", project="p")
    box._container = "no-such-container"
    real_popen = subprocess.Popen

    def instead_of_docker(_argv, **kw):
        return real_popen("echo partial-work; exec sleep 30", shell=True, **kw)

    monkeypatch.setattr(subprocess, "Popen", instead_of_docker)

    rc, out = box.run(workspace=_ws(tmp_path), command="claude -p ...", timeout=2)

    assert rc == TIMEOUT_EXIT and timed_out(rc, out)
    assert "partial-work" in out, "the production box discarded the transcript at the wall"


def test_a_walled_command_s_late_output_cannot_land_in_the_next_command(tmp_path, monkeypatch):
    """THE COST OF SHARING ONE BUFFER ACROSS A BOX'S COMMANDS, and the reset alone does not pay it.

    When the wall fires and a grandchild outlives the process we killed, `run_and_stream` abandons
    its reader thread on purpose — blocking on a pipe that will never close is the hang the wall
    exists to prevent. That thread still holds the box's buffer, so its next line lands wherever the
    buffer is pointing, and by then the box has moved on: measured before this guard existed, an
    orphan that printed one line eight seconds after its command was killed came back as the FIRST
    LINE of the next command's output and of the next `tail()`.

    That is not cosmetic downstream. `machine` reads `sandbox.run("git diff --name-only …")`
    line-for-line as the set of touched paths; a `validate:` gate's output is handed back to the
    agent as the failing-gate brief; and the live watcher would read the dead command's stream-json
    as the current one's pulses. `subprocess.run(capture_output=True)` could not do this — each call
    owned its buffers — so the shared buffer is what introduced it.

    `_DRAIN_SECONDS` is shortened so the abandonment happens in half a second instead of ten; the
    orphan then speaks well inside the second command, which is the whole scenario."""
    import openfactory.adapters.sandbox.base as base

    monkeypatch.setattr(base, "_DRAIN_SECONDS", 0.5)
    box = WorktreeSandbox(root=tmp_path)

    rc, _ = box.run(
        workspace=_ws(tmp_path), timeout=1,
        command="(sleep 3; echo leaked-from-the-killed-command) & sleep 30")
    assert rc == TIMEOUT_EXIT
    box.tail()  # the watcher drains what the walled command left, as it would on its next tick

    rc, out = box.run(workspace=_ws(tmp_path), command="sleep 5; echo real-file.py", timeout=30)

    assert rc == 0
    assert out.splitlines() == ["real-file.py"], (
        "a command that was killed six seconds ago wrote into this one's output")
    assert [line.rstrip("\n") for line in box.tail()] == ["real-file.py"]


def test_a_walled_run_returns_within_its_own_bound(tmp_path):
    """MEASURED, because the first cut of this did not. `close()` on the pipe needs the buffer lock
    that the blocked `readline` holds, so closing it waited for the orphan to die: a 2s timeout took
    30.02s to return — the full lifetime of the `sleep 30` that outlived the shell we killed. The
    wall is only a wall if giving up is bounded."""
    started = time.monotonic()
    rc, _ = WorktreeSandbox(root=tmp_path).run(
        workspace=_ws(tmp_path), command="echo x; sleep 30", timeout=2)
    elapsed = time.monotonic() - started
    assert rc == TIMEOUT_EXIT
    assert elapsed < 25, f"the wall took {elapsed:.1f}s to give up on a 2s timeout"


# ── an observer is an observer ───────────────────────────────────────────────────────────────────

def test_an_observer_that_raises_does_not_end_the_run(tmp_path, caplog):
    """The callback runs on the reader thread with the agent mid-pass. A watcher bug must cost the
    watching, never the four hours of work — and it must SAY so, because a silent swallow makes a
    broken observer look exactly like a quiet harness."""
    def explode(_line: str) -> None:
        raise RuntimeError("the watcher is broken")

    with caplog.at_level("WARNING", logger="openfactory.sandbox"):
        rc, out = WorktreeSandbox(root=tmp_path).run(
            workspace=_ws(tmp_path), command=r"printf 'a\nb\nc\n'", timeout=20, on_output=explode)

    assert rc == 0
    assert out.splitlines() == ["a", "b", "c"], "the lines are still captured for the caller"
    said = [r for r in caplog.records if "observer raised" in r.getMessage()]
    assert len(said) == 1, "said once per run, not once per line — a 4h pass would flood the log"


# ── the contract, and the trait that answers for it ──────────────────────────────────────────────

def test_the_port_itself_declares_the_door():
    """On the Protocol, not merely on the two classes that happen to implement it: a box that joins
    later has to answer for `tail()` rather than discover it in someone else's adapter."""
    assert hasattr(SandboxAdapter, "tail")
    assert inspect.signature(SandboxAdapter.tail).return_annotation == "list[str] | None"


def test_the_door_is_a_pull_because_a_push_would_close_another_one():
    """C-09 (`tests/test_ports_are_serialisable.py`) refuses a `Callable` in a port signature: a
    callback needs a live process on the other side, so it closes the door on an out-of-process box
    by accident rather than by decision. #82 proposed `run(..., on_output=…)` ON THE PORT, and that
    is the one shape it could not have — this is the same capability as data.

    Asserted here as well as there because the two tests fail differently: C-09 catches the drift
    for every port, and this one says WHY this port took the shape it did, next to the thing it
    constrains."""
    hints = inspect.get_annotations(SandboxAdapter.run)
    assert "on_output" not in hints, (
        "the port took a callback — an out-of-process box can no longer implement it, and that "
        "door should close by decision, not by a signature nobody re-read")


@pytest.mark.parametrize("kind", ["worktree", "container"])
def test_every_local_box_also_offers_the_push_convenience(kind, tmp_path):
    """Not on the port, on the two boxes that are physically local — #82 asked for it by name and a
    consumer may be written against it. It is not a second source of truth: `run_and_stream` feeds
    the callback and the buffer from the same line, once."""
    sig = inspect.signature(build_sandbox(kind, root=tmp_path, image="x").run)
    assert "on_output" in sig.parameters, f"the {kind} box cannot be watched"


@pytest.mark.parametrize("kind,streams", [("worktree", True), ("container", True),
                                          ("fargate", False)])
def test_the_trait_says_whether_this_box_can_be_watched(kind, streams):
    assert box_traits(kind).streams is streams


def test_the_trait_is_checked_against_the_implementation_not_written_beside_it():
    """THE GUARD THAT MAKES THE TRAIT WORTH HAVING. `streams=True` beside a box that cannot be read
    is the exact failure the card warns about: the watcher attaches, sees nothing for four hours,
    and reports a calm agent. So the claim is verified against the code that would have to honour it
    — every box that says True must be buildable and answer `tail()` with a list, and every box that
    says False must not be quietly capable of answering one.

    IT DOES NOT ASK FOR `on_output`, and that omission is the port's design rather than a gap: the
    push convenience is offered by the two boxes that are physically local (the test below) and is
    deliberately absent from the Protocol, so requiring it of every streaming box would assert the
    opposite of what `test_the_door_is_a_pull_because_a_push_would_close_another_one` protects."""
    for kind, row in BOXES.items():
        traits = row[0]  # (traits, build) for a local box, (traits, build, remote) for a remote one
        try:
            box = build_sandbox(kind, root="/tmp/openfactory-trait-probe", image="x")
        except ValueError:
            assert not traits.streams, (
                f"{kind} claims it streams and has no local adapter to stream from")
            continue
        # The box's own answer to the same question, in the only place it can be wrong at runtime:
        # `None` from `tail()` IS `streams=False` said again, and the two must not disagree.
        readable = box.tail() is not None
        assert readable is traits.streams, (
            f"{kind}: the trait says streams={traits.streams} and the box answers "
            f"tail()={'a list' if readable else 'None'}")


def test_a_new_box_has_to_answer_the_question():
    """Required, exactly like `honours_image`. A default would be a claim made on a future box's
    behalf by whoever wrote the dataclass — True hands a watcher to a box that drops it (silence
    reads as health), False hides a box that could have been watched (nobody investigates an
    absence the table already declared)."""
    from openfactory.adapters.sandbox.registry import BoxTraits

    with pytest.raises(TypeError):
        BoxTraits(name="ssh", remote=True, honours_image=True, idempotent=False)


def test_the_remote_box_answers_no_and_the_reason_is_recorded():
    """VERIFIED, NOT ASSUMED — the card names Fargate as the one risk in this trait, so "probably
    not, it's remote" would have been the same shape of answer it warns against.

    Structural: `build_sandbox("fargate")` raises, so there is no `run` on this side of the wire
    for a callback to attach to — the launcher runs the whole job inside the task.

    Observed: four real task streams from `/ecs/openfactory-sandbox` (eu-west-2) were read —
    712 log lines, 699 `OPENFACTORY_EVENT:` envelopes from the in-task sink, 4 result lines, 9 of prose,
    and ZERO harness events. The agent adapter captures the harness stream through `sandbox.run`
    and writes it to a transcript file inside the task, so it never reaches the task's stdout and
    therefore never reaches the log group. The host sees the orchestrator narrating state changes,
    which is a coarser thing than the harness's own pulse."""
    assert box_traits("fargate").streams is False
    with pytest.raises(ValueError, match="remote"):
        build_sandbox("fargate")


# ── the real docker hop, when there is a daemon AND an image to ask ──────────────────────────────

def _docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def _the_box_image() -> str:
    """WHAT THIS DEPLOYMENT WOULD ACTUALLY RUN, asked of the one place that decides (ADR-0037 D4).

    It was the literal `"openfactory-python:latest"` — a string, and not the framework's box.
    `docker-compose.yml` sets `OPENFACTORY_SANDBOX_IMAGE: openfactory-python:sandbox`, so on the OSS
    stack this proved the docker hop against an image that deployment never runs — the exact defect
    `resolve_box_image` exists to end (six literals, none of them reading the variable the product
    documents). Asking the resolver also makes the skip below name the image THIS machine is
    missing, rather than a name somebody once copied into a test."""
    from openfactory.factory import resolve_box_image

    return resolve_box_image(sandbox="container")


def _image_is_built(image: str) -> bool:
    """`docker image inspect`, never `docker pull`.

    This image is built locally from `docker/base-python.Dockerfile` by the compose stack and
    exists in no registry, so "can it be pulled" is the wrong question: it spends a network round
    trip to answer `no` about an image that is sitting on the machine. `box_prove._resolve_digest`
    records that same measurement in production code."""
    return subprocess.run(["docker", "image", "inspect", image],
                          capture_output=True).returncode == 0


@pytest.mark.skipif(not _docker_ready(), reason="needs a docker daemon")
def test_the_container_box_really_streams_across_the_docker_boundary(tmp_path):
    """The trait claims `docker exec` relays the container process's output live. Everything else
    about the container box here substitutes `Popen`, which proves the pump and not the hop — so
    this one asks a real daemon, using the framework's own box image.

    The gate crosses the mount in the OTHER direction: the observer writes a file on the HOST into
    the bind-mounted clone, and the shell inside the box is waiting on it at `/workspace`. Nothing
    completes unless a line genuinely came out of the container while its process was still
    running.

    A DAEMON IS NOT AN IMAGE, AND THE SKIP ABOVE COULD NOT TELL THEM APART. A GitHub Actions runner
    has docker and has never built this repository's compose stack, so the box image is simply not
    there. Reported red from a runner on 2026-08-21 and reproduced here by hiding that one image
    from the local daemon: `docker run` exited **125** — *"Unable to find image
    'openfactory-python:latest' locally"* — and `prepare()` raised `RuntimeError`. Green on every
    machine that had ever run `docker compose build`, which is why it survived.

    THE PRECONDITION IS ASKED IN THE BODY, AT RUN TIME, and that is not a style choice — it is the
    property `test_ci_runs_what_we_run` states: collection stays identical on every machine (25
    tests here, measured with the image present and with it hidden), the test keeps its line in the
    report instead of quietly leaving the suite, and the reason carries the image name and the
    command that builds it. Where the image IS built, nothing about this body changed.

    BOTH DIRECTIONS WERE MEASURED, because a skip nobody can fail is decoration: with the image
    present it runs and asserts (1 passed), and with `OPENFACTORY_SANDBOX_IMAGE` pointed at a tag no
    daemon has it skips naming that tag — and pointed back at a tag that IS built, it runs again."""
    image = _the_box_image()
    if not _image_is_built(image):
        pytest.skip(f"the box image {image!r} is not built on this machine — "
                    f"`docker compose build` (or `docker build -f docker/base-python.Dockerfile "
                    f"-t {image} .`) makes it; the docker hop is unmeasured until it exists")

    repo = tmp_path / "repo"
    repo.mkdir()
    for argv in (["git", "init", "-b", "main"], ["git", "config", "user.email", "t@t"],
                 ["git", "config", "user.name", "t"], ["git", "commit", "--allow-empty", "-m", "x"]):
        assert subprocess.run(argv, cwd=repo, capture_output=True).returncode == 0

    box = ContainerSandbox(image=image, project="streamprobe")
    ws = box.prepare(repo_path=repo, base_branch="main", branch="sdlc/stream-probe")
    try:
        gate = ws.host_path / "gate"
        seen: list[str] = []

        def observe(line: str) -> None:
            seen.append(line)
            if line == "first-line":
                gate.write_text("go")

        rc, out = box.run(workspace=ws, command=_gated("/workspace/gate"), timeout=60,
                          on_output=observe)
        assert rc == 0, f"the box never saw the gate — output was buffered: {out!r}"
        assert seen == ["first-line", "after-the-gate"]
    finally:
        box.cleanup(workspace=ws)
