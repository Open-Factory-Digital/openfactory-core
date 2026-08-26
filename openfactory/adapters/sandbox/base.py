"""SandboxAdapter — the ephemeral environment for a job (ADR-0001 D-4).

Two implementations behind this one Protocol:

- **ContainerSandbox** — the real, production path. A Docker container delivers the
  isolation D-4 actually promises: bounded CPU and memory, ephemeral secrets, a
  filesystem restricted to the mounted clone. This is where autonomous,
  arbitrary-code execution belongs.

  It does NOT bound the network, and this list used to say it did. The box has full
  outbound internet by default and must: the harness dials its API and `setup:`
  installs dependencies. A deployment that needs egress bounded passes its own
  network; the framework does not pretend to have done it. See
  `container.py` for why a false security claim is worse than none.
- **WorktreeSandbox** — a lightweight local/test double (git worktree). It isolates
  only the *code state* (no CPU/mem/network/secret isolation), so it is for fast
  orchestrator tests and local debugging without a Docker daemon — not for running
  untrusted work.

Ephemeral in the code state either way; a dependency cache is persisted separately
(a mounted volume for the container) so we don't pay a full install per job.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from openfactory.adapters.sandbox.timeouts import timeout_result

log = logging.getLogger("openfactory.sandbox")


class Workspace(BaseModel):
    path: Path
    branch: str
    base_branch: str
    # Where the SAME checkout lives on the ORCHESTRATOR's filesystem. For the worktree sandbox
    # that is `path` itself; for the container sandbox `path` is the in-container mount point
    # (/work) and this is the host clone bind-mounted there. Anything the orchestrator reads
    # directly (rather than through `run()`) must use this — e.g. the Knowledge Layer, which
    # judges the bundle against the job's OWN checkout. None → the orchestrator can't read the
    # workspace from here and the caller degrades (never guesses a path).
    host_path: Path | None = None


@runtime_checkable
class SandboxAdapter(Protocol):
    def prepare(
        self, *, repo_path: Path, base_branch: str, branch: str, checkout_existing: bool = False,
        remote_url: str | None = None,
    ) -> Workspace:
        """Create an isolated, ephemeral workspace. Normally a fresh `branch` off `base_branch`;
        with `checkout_existing=True`, start from the already-pushed remote `branch` instead
        (the CI-repair path works on the open PR's branch — ADR-0004).

        `remote_url` MEANS HERE WHAT IT MEANS ON `publish_branch` AND `rebase_onto_base`: an
        authenticated HTTPS URL from the forge, carrying the bot token, passed as an argument so
        git never persists it. Absent → the repo's ambient `origin`.

        THE ASYMMETRY WAS THE BUG (found live on fx-mono#1's adjust, 2026-08-04). This was the one
        git-fetching method on the port that took no credential, so it could only ever reach
        `origin` — and the worker's repo cache deliberately keeps a TOKENLESS origin, because
        agents read that checkout and a ticket can ask one to print `.git/config`. On a private
        repository the fetch therefore failed for want of a password, and both adapters
        misreported it: the container said "couldn't find remote ref" about a branch sitting on
        the forge, and the worktree silently started from base and force-pushed over the PR."""
        ...

    def harness_path(self, name: str) -> str:
        """Where the agent CLI called `name` lives IN THIS BOX.

        The adapters used to emit a bare `claude` / `codex` / `kimi` and let `PATH` resolve it.
        That is correct on a worktree, where the host is the operator's own machine, and wrong in a
        container: under ADR-0037 the image is the CLIENT's, and Debian's and Alpine's stock
        `/etc/profile` assign `PATH` unconditionally, so a toolbox announced through `PATH` is
        discarded by an ordinary base image before the command runs.

        The box answers because only the box knows. `execute(sandbox=, workspace=, context=)`
        already hands it to the adapter, so the question costs nothing — and a box that joins later
        (an SSH runner, a remote VM) answers it once instead of every adapter growing a branch.
        """
        ...

    def run(self, *, workspace: Workspace, command: str, timeout: int) -> tuple[int, str]:
        """Run a command in the workspace; return (exit_code, combined_output).
        This is how the *platform* runs validation — independently of the agent."""
        ...

    def tail(self) -> list[str] | None:
        """Lines the CURRENTLY RUNNING command has written since the last call to this — the door
        this port did not have (C-39).

        Every implementation ran `subprocess.run(capture_output=True)`, which means the output does
        not EXIST until the process exits. All four harnesses narrate themselves as JSON lines the
        entire time; nobody was holding the other end, so the first reading of a four-hour pass
        arrived four hours late by construction.

        `None` AND `[]` ARE DIFFERENT ANSWERS AND THAT IS THE WHOLE POINT.

            None   this box cannot read its own output. Nothing may be concluded.
            []     read it; nothing new since the last call.

        Collapsing them is this codebase's most expensive defect: an unreadable board reading as an
        empty queue, an unparsed review reading as a rejection. Here it would be a watcher attached
        to a box it cannot see, reporting a calm agent for four hours. A box answers `None` here
        exactly when it answers `streams=False` in `registry.BoxTraits`, and the trait exists so a
        caller can decide BEFORE it starts believing a stream of empty lists.

        PULL, NOT PUSH, AND THE PORT DECIDED THAT RATHER THAN THE CONVENIENCE. The obvious shape is
        `run(..., on_output=callback)`, which is what #82 proposed and what the two local boxes
        still offer. It cannot be the PORT's shape: a callback is a live object, so a signature with
        one closes the door on a box that runs somewhere else — the exact accident C-09
        (`tests/test_ports_are_serialisable.py`) exists to prevent, and it names `Callable` as the
        first thing it must refuse. A pull returns data, travels, and is the shape a remote box
        already has: `runtime/fargate/launcher._tail(task_arn, token)` is this method with the
        cursor made explicit, written months before the question was asked.

        IT IS READ FROM ANOTHER THREAD WHILE `run` BLOCKS. That is the point — the caller of `run`
        is inside the four hours. An implementation must therefore be safe to call concurrently
        with its own `run`, and must never block on it.

        THE CURSOR IS PER BOX, NOT PER READER. Concurrency here is one job per box (see
        `ContainerSandbox.__init__`), and a second reader would silently steal the first one's
        lines. If a second consumer ever appears, that is a real change, not a detail.
        """
        ...

    def export_home_dir(self, *, workspace: Workspace, relative: str, dest: Path) -> bool:
        """Copy a directory from the box's HOME onto the ORCHESTRATOR's filesystem. True if `dest`
        now holds it.

        THE HARNESS'S STATE IS NOT THE WORKSPACE'S. A CLI keeps its session under `$HOME`, outside
        the clone, and `$HOME` is the one part of a box that is neither mounted nor shared: the
        container box mounts the checkout, the toolbox and nothing else, so everything the harness
        learned during a four-hour pass is destroyed with the container. That is what made durable
        resume a cloud-only capability — the deployment WITH an object store could keep a session
        across a rate-limit pause and the free one could not, so the same pause cost the free
        deployment a full replan and a second agent pass (#118).

        `relative` is resolved against the HOME OF THE BOX, which only the box knows — the image is
        the client's and its user is the client's choice. It must be a relative path with no `..`
        segment: it becomes an argument to a copy the orchestrator issues, and configuration is not
        code review.

        BEST-EFFORT, LIKE EVERY OTHER HALF OF RESUME. A box that cannot do this answers False (and
        says so through `BoxTraits.transfers_state` BEFORE anybody starts believing it), a missing
        directory answers False, and a failure answers False — never an exception. Losing a session
        costs a cold run; raising here would turn a resumable pause into a failed job."""
        ...

    def import_home_dir(self, *, workspace: Workspace, src: Path, relative: str) -> bool:
        """The mirror of `export_home_dir`: put a directory back under this box's HOME. True if
        the box now holds it.

        MERGES, AND THE ALTERNATIVE WAS DESTRUCTIVE. The first cut of this replaced the target —
        which is harmless in a container nobody has used yet, and on the `worktree` box means
        `rm -rf $HOME/.claude/projects` in the PROCESS's own home: the operator's history and any
        concurrent job's transcript, deleted to restore one session. A box's HOME is not a
        per-job directory on every box, so the contract cannot assume it is."""
        ...

    def diff_paths(self, *, workspace: Workspace) -> list[str]:
        """Paths changed vs base — the source of truth for touched components (D-6)."""
        ...

    def publish_branch(self, *, workspace: Workspace, remote_url: str | None = None) -> None:
        """Push the branch to the forge so a PR can be opened. If `remote_url` is
        given (an authenticated HTTPS URL from the forge, carrying the bot token), the
        push goes there — so it is attributed to the bot; otherwise it uses the repo's
        ambient `origin`. Runs with the HOST's credentials — never from inside the
        sandbox, so forge push rights stay out of the untrusted-code environment."""
        ...

    def rebase_onto_base(
        self, *, workspace: Workspace, base: str, remote_url: str | None = None
    ) -> str:
        """Fetch the latest `base` and, if the branch is behind it, rebase onto it — so every
        merge lands on the current base (merge-queue-lite; the framework is serial). Like
        `publish_branch`, it runs with the HOST's credentials (never inside the sandbox).
        Returns "up_to_date" (nothing to do), "rebased" (moved onto a newer base → the caller
        re-validates before merging), or "conflict" (textual conflict → aborted, tree left
        clean for a human)."""
        ...

    def cleanup(self, *, workspace: Workspace) -> None:
        ...


# ═════════════════════════════════════════════════════════════════════════════════════════════════
# ONE PUMP, TWO BOXES (C-39)
#
# `WorktreeSandbox.run` and `ContainerSandbox.run` are the same problem wearing two argv: a local
# subprocess whose output has to be readable WHILE it runs and complete WHEN it ends. Written once,
# here beside the Protocol it implements, because the two had already drifted — the worktree kept
# the partial output at a timeout and the container threw it away, on the box that matters most.
#
# It lives in the port module rather than a new one so the contract and its only reference
# implementation stay in the same file; a box that is not a local subprocess (an SSH runner, a
# remote VM) implements the contract its own way and answers the `streams` trait accordingly.
# ═════════════════════════════════════════════════════════════════════════════════════════════════

#: How long to wait for the reader to finish after the process has stopped. The pipe is drained
#: continuously, so on a normal exit at most an OS buffer is left and this is never approached. It
#: is a WALL, for the one case it cannot be: a grandchild that inherited stdout and outlives the
#: process we killed keeps the write end open, and `readline` would block on it for ever.
#: `subprocess.run(timeout=...)` — what this replaces — hangs indefinitely in exactly that case,
#: because it kills the child and then `communicate()`s without a bound.
_DRAIN_SECONDS = 10.0


class OutputBuffer:
    """What the box's current command has written, readable from another thread while it writes.

    THE READER AND THE WRITER ARE DIFFERENT THREADS BY CONSTRUCTION. `run` blocks its caller for the
    length of the pass — that is the four hours — so anything that wants to look inside those four
    hours is necessarily somewhere else. A lock costs nanoseconds per line and removes the need to
    reason about which list operations happen to be atomic under which build of the interpreter.

    ONE CURSOR, because there is one job per box (`ContainerSandbox.__init__` says so in as many
    words). `take()` is destructive on purpose: an incremental reader that had to remember how much
    it had already seen would be a second place for the same off-by-one, and this repository has
    paid for a cursor kept in two places before.

    THE GENERATION IS WHAT KEEPS ONE COMMAND'S GHOST OUT OF THE NEXT ONE'S OUTPUT, and it is the
    price of the buffer being shared across a box's commands rather than owned by one `run`. See
    `start()` and `add()`."""

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._taken = 0
        #: which command these lines belong to. Bumped by `start()`; carried by the reader thread
        #: `run_and_stream` spawns, and checked on every `add`.
        self._run = 0
        self._lock = threading.Lock()

    def start(self) -> int:
        """A new command begins; returns the generation its reader must quote back.

        WITHOUT THE RESET, `tail()` WOULD REPLAY THE PREVIOUS COMMAND — a box runs `setup:`, then
        the harness, then `validate:`, all through the same instance, and a watcher polling across
        the boundary would read the setup's output as the agent's.

        WITHOUT THE GENERATION, THE PREVIOUS COMMAND CAN STILL WRITE INTO THIS ONE, which is the
        harder half and the one the reset alone does not cover. When a run hits its wall and a
        grandchild outlives the process we killed, `run_and_stream` deliberately ABANDONS its
        reader thread rather than block on a pipe that will never close — and that thread is still
        holding this buffer. MEASURED, not theorised: a walled command whose orphan printed one
        line eight seconds later had that line come back as the first line of the NEXT command's
        output. Downstream that is not cosmetic — `machine` reads `sandbox.run("git diff
        --name-only …")` line-for-line as the set of touched paths, a `validate:` gate's log is
        handed to the agent as the failing-gate brief, and the live watcher would parse the dead
        command's stream-json as the current one's pulses and let a stale line suppress a genuine
        stall. `subprocess.run(capture_output=True)` — what this replaces — could not do this,
        because each call owned its own buffers; the shared one is what made it possible."""
        with self._lock:
            self._lines, self._taken = [], 0
            self._run += 1
            return self._run

    def add(self, line: str, run: int) -> bool:
        """Record a line, unless it belongs to a command this buffer has already moved past.
        `False` means "you have been superseded" — the caller stops reading."""
        with self._lock:
            if run != self._run:
                return False
            self._lines.append(line)
            return True

    def take(self) -> list[str]:
        """Lines added since the last `take()`. `[]` means read-and-nothing-new, never "unreadable"
        — the box answers that by returning None from `tail()` before it ever gets here."""
        with self._lock:
            new = self._lines[self._taken:]
            self._taken = len(self._lines)
            return new

    def text(self) -> str:
        with self._lock:
            return "".join(self._lines)


def run_and_stream(
    proc: subprocess.Popen, *, command: str, timeout: int, buffer: OutputBuffer | None = None,
    on_output: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    """Drive an already-started process to its end: `(exit_code, combined_output)`, with every
    complete line added to `buffer` and handed to `on_output` as it arrives.

    `proc` must have been started with `stdout=PIPE`, `stderr=STDOUT` and `text=True` — the caller
    owns the argv (a shell string on the host, a `docker exec` list for the box) and this owns the
    reading.

    TWO WAYS TO SEE THE SAME LINES, and they are the same lines. `buffer` is what the port's
    `tail()` reads — pull, serialisable, the contract. `on_output` is the push convenience the two
    local boxes offer on top of it (#82 asked for it by name); it cannot be on the port, because a
    `Callable` in a port signature closes the door on an out-of-process box by accident, which is
    what C-09 refuses. Neither is a second source of truth: both are fed here, once, per line.

    A READER THREAD, NOT A READ LOOP IN THIS ONE, and that is the whole reason the timeout still
    works. Reading lines on this thread would block in `readline()` for as long as the harness says
    nothing — which is precisely the stall this exists to notice — and the wall-clock wall would
    never fire. So the thread blocks on the pipe and this thread blocks on `wait(timeout=…)`; the
    clock belongs to the process, the lines belong to the reader.

    ONE OUTPUT, INTERLEAVED. The two implementations used to return `stdout + stderr` — every line
    of one, then every line of the other — because `capture_output=True` hands back two strings.
    Merging at the pipe means the order a reader sees is the order the process wrote, which is what
    a human reading a failed validation needs and what a live parser needs to be given at all.
    """
    # The buffer IS the accumulator, not a copy of one. A local `lines` list beside it would be a
    # second record of the same stream, and the two would disagree the first time one of them was
    # reset — so `run` builds its return value from the same object `tail()` reads.
    sink = buffer if buffer is not None else OutputBuffer()
    generation = sink.start()
    complained = False

    def reader() -> None:
        nonlocal complained
        # `iter(readline, "")` rather than `for line in proc.stdout`: explicit about reading ONE
        # line per call, with no promise of read-ahead buffering to reason about.
        for line in iter(proc.stdout.readline, ""):
            # A reader this function gave up on (see `_DRAIN_SECONDS` below) is still blocked here
            # on an orphan's pipe. The moment the box starts its NEXT command this thread stops
            # being a reader and becomes a contaminant, so it stops at the first line it cannot
            # place — including the push side, whose observer belongs to a run that has returned.
            if not sink.add(line, generation):
                return
            if on_output is None:
                continue
            try:
                on_output(line.rstrip("\n"))
            except Exception as exc:  # noqa: BLE001 — an observer must never end the run
                # ONCE, not per line. A watcher that raises raises on every line, and a four-hour
                # pass would write a hundred thousand identical warnings — which is how a log stops
                # being read. Said at all because a silent swallow here makes a broken watcher look
                # exactly like a quiet harness, and this line is the only thing that tells them
                # apart (the same reasoning `stream.reading_of` states for its own log).
                if not complained:
                    complained = True
                    log.warning(
                        "the output observer raised (%s) — the run continues and its lines are "
                        "still captured, but whatever was watching this stream is now blind to it",
                        str(exc)[:160])

    thread = threading.Thread(target=reader, name="openfactory-sandbox-output", daemon=True)
    thread.start()
    walled = False
    try:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            walled = True
            proc.kill()
            # The DIRECT child only — the same reach `subprocess.run(timeout=…)` has always had
            # here. A process-group kill would also reach the harness the shell spawned, and it is
            # deliberately NOT done: the boxes run in the worker's own process group, so a deploy's
            # SIGTERM reaching the harness is what stops an orphaned agent from burning tokens
            # after the worker dies. `start_new_session=True` would buy a tidier kill and pay for
            # it by turning a bounded leak into an unbounded one. (The container box has its own
            # answer — see `ContainerSandbox.run`.)
            try:
                proc.wait(timeout=_DRAIN_SECONDS)
            except subprocess.TimeoutExpired:
                log.warning("the sandboxed process ignored SIGKILL for %.0fs", _DRAIN_SECONDS)
    finally:
        thread.join(timeout=_DRAIN_SECONDS)
        if thread.is_alive():
            # A GRANDCHILD OUTLIVED THE PROCESS WE KILLED and still holds the write end of the
            # pipe, so `readline` cannot return. Measured, not theorised: `sh -c 'echo x; sleep 30'`
            # with a 2s wall leaves `sleep` holding it.
            #
            # DO NOT CLOSE THE PIPE HERE. `close()` needs the buffer lock that the blocked
            # `readline` is holding, so it waits exactly as long as the orphan lives — the first
            # cut of this function did, and a 2s timeout took 30.02s to return, the full lifetime
            # of the orphan. The daemon thread and the garbage collector deal with it; giving up
            # on the read is the entire point of the wall.
            #
            # WHAT THE ABANDONED THREAD MAY STILL DO IS BOUNDED BY THE BUFFER'S GENERATION. It goes
            # on appending to THIS command's lines (they are this command's — the orphan is its
            # child), and it stops dead at the first line it reads after the box starts another
            # command. Without that check its late output arrived as the NEXT command's first line;
            # see `OutputBuffer.start`.
            log.warning(
                "gave up waiting for the output reader after %.0fs — a process that outlived the "
                "one we killed still holds this pipe, so the tail of the output may be missing",
                _DRAIN_SECONDS)
        else:
            try:
                proc.stdout.close()
            except Exception as exc:  # noqa: BLE001 — cleanup, but cleanup that can still surprise
                # ALREADY CLOSED IS THE EXPECTED CASE AND IT IS STILL WORTH A LINE. This handler
                # was written for an idempotent close, which is true — and it would swallow a
                # descriptor error just as quietly, on the one code path that owns the only record
                # of what a four-hour agent pass did. Debug, because it is noise on the happy path
                # and the whole story on the day it is not.
                log.debug("closing the box's output pipe raised (%s) — the capture above is "
                          "already complete, so this is cleanup rather than loss", exc)
                pass
    captured = sink.text()
    # WHATEVER IT HAD ALREADY WRITTEN. On a four-hour agent pass this partial stream is the only
    # account of what the agent did, and the container box used to discard it — `timeout_result`
    # has taken a third argument the whole time and the production box passed two.
    return timeout_result(command, timeout, captured) if walled else (proc.returncode, captured)
