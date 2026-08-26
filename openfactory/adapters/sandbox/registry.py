"""Which box a job runs in — resolved from config, never from a conditional (C-10).

ADR-0022 graded eight provider axes and marked **sandbox** as "fine": two implementations, a
Protocol, dispatch. That was the one row it got wrong, and the reason it escaped is that **Fargate
does not look like an adapter.** It is not an implementation of `SandboxAdapter` — the launcher
runs the whole job inside the task — so it lived as a parallel path selected by
`if sandbox == "fargate"` in roughly eight places, three of them inside the Temporal workflow body.

THE THREE WORKFLOW SITES ARE NOT ASKING THE SAME QUESTION, and seeing that is the design:

    is the box REMOTE?        `_cleanup` must stop a task the worker cannot see
    is it IDEMPOTENT?         whether a failed attempt may be retried at all

The second is not about Fargate. The comment beside it always said so: *"fargate is idempotent
(re-attach/reconcile) so it retries; the local coarse path re-runs the agent + dup comments, so it
stays single-attempt."* That is a property of the box, and it belongs with the box rather than
transcribed into the lifecycle as a vendor name.

THEY ARE KEPT INDEPENDENT even though today they coincide. A remote box without re-attach — an SSH
runner, a plain EC2 instance — would be remote and NOT idempotent, and collapsing the two into one
flag would silently start retrying it, which for this platform means a second agent pass and a
duplicated set of tracker comments.

PURE, because it is called from inside a workflow body. No I/O, no clock, no environment: a trait
that read `os.environ` would replay differently on a worker started with a different configuration,
which is the exact class of bug `workflow.patched()` exists to paper over.

THE AXIS IS OPEN, AND THE WORKFLOW'S LOOKUP IS NOT. Two lookups on purpose (the review that opened
the box axis measured the hazard before the code was written): `box_traits` reads the BUILT-IN table
and nothing else, because it runs inside the workflow body and `plugins._load()` scans site-packages
and imports a stranger's package — an answer that depends on what is installed on the worker doing
the replay. `installed_box_traits`, `build_sandbox` and `remote_box` run on the activity side and DO
consult the add-ons; a plugin box's traits reach the workflow as DATA on `JobParams`, stamped by the
activity that starts the job (`io.JobParams.traits`).

A REMOTE BOX CARRIES ITS RUNNER IN THE ROW. The lifecycle used to dispatch a remote box by name —
`if inp.sandbox == "fargate":` in four activities, each importing the vendor's launcher by hand —
so a third box declaring `remote=True` would have received its traits and then been built as a LOCAL
adapter by `run_job`, while `stop_job` returned 0 for anything not called "fargate": the two halves
disagreed, and the orphaned task the `remote` trait exists to prevent was exactly what it would
have produced (measured with an `ssh` row, 2026-08-24). Now the row for a remote box is
`(traits, build, remote)`, the third slot REQUIRED — checked when the table is built, so a remote
row without a runner fails at import rather than by silently running on the worker.

THE CORE DESCRIBES `fargate` AND NO LONGER IMPLEMENTS IT. Its traits stay here as pure data, so a
job started before this change replays on a worker that has this table; its runner is supplied by
the fargate package through the `openfactory.adapters` entry-point group, the same door a stranger's
box uses. Delete `runtime/fargate/` and this module still imports, `box_traits("fargate")` still
answers, and `remote_box("fargate")` refuses naming the entry point that is missing — which is what
"the cloud is an add-on" (ADR-0040 D3) means when it is measured rather than claimed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from openfactory.adapters.sandbox.timeouts import LAUNCHER_TIMEOUT

if TYPE_CHECKING:
    from openfactory.contracts import RunResult
    from openfactory.observability import EventSink
    from openfactory.runtime.boxed_job import BoxConfig

#: The entry-point axis a box registers under (`box.<kind>` → a callable returning a row).
AXIS = "box"
#: The entry-point axis that supplies the RUNNER of a box the core describes but does not
#: implement (`box_runner.<kind>` → a callable returning a `RemoteBox`). No built-in has one:
#: the core ships no remote runner at all, only the description of the one it used to ship.
RUNNER_AXIS = "box_runner"


@runtime_checkable
class EventTail(Protocol):
    """What a remote box hands the panel so it can follow a job it cannot see: each call answers
    only the events that are NEW since the last one, so a stream can poll it every few seconds
    without re-reading the whole log."""

    def fetch_new(self) -> list[dict]: ...


@runtime_checkable
class RemoteBox(Protocol):
    """The runner of a box on a machine this worker cannot reach — the three things the lifecycle
    asks of it, and nothing a provider happens to offer (ADR-0022 §3).

    `launch` runs the WHOLE job somewhere else and brings the `RunResult` back; `stop` sweeps
    whatever a job left running when it ended abnormally, and says how many it stopped; `tail`
    is how the panel follows the job's journal while it is being written on another machine.
    """

    def launch(self, box: BoxConfig, *, journal: EventSink | None = None, variant: str = "",
               extra_env: dict | None = None, timeout: int = LAUNCHER_TIMEOUT,
               run_id: str | None = None) -> RunResult: ...

    def stop(self, box: BoxConfig) -> int: ...

    def tail(self, project: str, issue: str) -> EventTail: ...

#: The framework's own box image — the ONE place this string is written.
#:
#: It used to be a literal in six: two CLI options, two Temporal input models, the CI-repair
#: activity, and the builder below. Six places to disagree, and they did:
#: `OPENFACTORY_SANDBOX_IMAGE`,
#: which docker-compose.yml sets, was read by none of them, so the OSS distribution ran an image
#: different from the one it declared. Resolution now happens once, in `factory.resolve_box_image`
#: (ADR-0037 D4); this constant is only its last fallback.
DEFAULT_BOX_IMAGE = "openfactory-python"


@dataclass(frozen=True)
class BoxTraits:
    """What the lifecycle needs to know about a box, without knowing which one it is."""

    name: str

    #: Does the job run on a machine this worker cannot reach? Decides whether an abnormal end
    #: leaves something behind that has to be stopped explicitly.
    remote: bool

    #: Does this box run the image the project declares? False means `box.image` cannot take
    #: effect — the whole job runs in a task whose image is baked (fargate), or there is no image
    #: at all (worktree, a git worktree on the host). A declaration that cannot take effect must be
    #: REFUSED rather than ignored, and asking the question here rather than testing for a vendor
    #: name means a new box cannot join without answering it (ADR-0022, ADR-0037 D4).
    honours_image: bool

    #: Is re-running a failed attempt safe? True only when the box RE-ATTACHES to work already in
    #: flight rather than starting it again. For a box that does not, a retry costs a second agent
    #: pass and duplicates every comment the first one wrote.
    idempotent: bool

    #: Can this box hand a caller the running command's output WHILE it runs
    #: (`SandboxAdapter.tail()`)? False means nothing can watch a harness in this box before its
    #: process exits, and the answer about a stall arrives at the wall — up to four hours late by
    #: construction. It is the same claim the box makes by returning a list rather than `None` from
    #: `tail()`, asked BEFORE anything starts believing a stream of empty lists.
    #:
    #: REQUIRED, LIKE `honours_image`, AND FOR THE SAME REASON WRITTEN LARGER. A default would be a
    #: claim made on a new box's behalf by whoever wrote this dataclass. `True` by default hands a
    #: watcher to a box that drops the callback — and a watcher that receives no events cannot tell
    #: that from a harness that is working quietly, which is this repository's signature defect
    #: wearing its most expensive hat: the answer is silence and silence reads as health. `False` by
    #: default is safer but still a lie in the other direction — a box that CAN stream reads as
    #: blind, and nobody investigates a capability the table says is absent. So a box that joins
    #: answers, in the same breath as it answers the other three.
    streams: bool

    #: Does this box bound anything beyond the CODE STATE — CPU, memory, network, secrets, the
    #: filesystem outside the clone? False means the agent's arbitrary code runs with whatever the
    #: process that launched it has, which `worktree`'s own entry has always said in words:
    #: *"never for untrusted work"*.
    #:
    #: IT IS A TRAIT BECAUSE THE ALTERNATIVE WAS A VENDOR NAME. `_start_durable` refused anything
    #: that was not `"fargate"`, on the reasoning *"the cloud worker has no other execution
    #: path"* — true of the deployment it was written on and false of the one this product SHIPS,
    #: where the durable engine is Temporal OSS and the box is `container`. The effect was that a
    #: compose install could not start a durable job at all: the human merge gate, park/resume and
    #: every deadline were reachable only on our own cloud. Asking a box what it BOUNDS, rather
    #: than what it is called, is the difference between a rule and a coincidence.
    #:
    #: `honours_image` is NOT this question and cannot stand in for it — `fargate` answers False
    #: there (its image is baked into the task) while isolating more than either local box.
    isolates_resources: bool

    #: Can the orchestrator move a directory out of this box's HOME and back into the next one
    #: (`export_home_dir` / `import_home_dir`)? False means whatever the harness learned during the
    #: pass dies with the box, so a paused job resumes COLD: it replans, re-implements, and burns a
    #: second agent pass on work that was already done.
    #:
    #: REQUIRED, for the reason `streams` is written large above. This capability is the difference
    #: between a deployment that keeps its work across a rate-limit pause and one that pays for it
    #: twice, and until #118 it existed only where an object store did — which made the free,
    #: open-source deployment the one that paid. A default here would hand that answer to whoever
    #: wrote this dataclass on behalf of a box that has not been written yet.
    transfers_state: bool


def _worktree(**kw):
    from openfactory.adapters.sandbox import WorktreeSandbox

    root = kw.get("root")
    # `extra_env` too: `factory.py` forwards `box.env` for every box, and a worktree that dropped
    # it would authenticate the harness in the container and not on the host — the same
    # declaration honoured by one box and silently ignored by the other.
    return WorktreeSandbox(root=Path(root) if root else Path.cwd() / ".openfactory-worktrees",
                           extra_env=tuple(kw.get("extra_env") or ()))


def judging_worktree(project, *, root):
    """A host worktree that carries the harness credentials THIS project declared.

    The judging roles — the sizer, the tech-lead's chat and diagnosis, the product module — each
    built a bare `WorktreeSandbox(root=…)`, which scrubs every AWS variable from the workload's
    environment. That is right when the harness talks to a vendor API and the variables are only
    our infrastructure's identity. It is wrong the moment the harness authenticates THROUGH a
    cloud: on a Bedrock deployment the executor and reviewer keep working (they run in the box,
    where `box.env` passes the names through) and every judging role loses its credential.

    One function rather than four call sites repeating it, because the failure mode of getting
    this wrong is silence — a tech-lead that answers "could not answer", a size gate that
    degrades — and three-out-of-four would look exactly like four-out-of-four.
    """
    from openfactory.adapters.sandbox import WorktreeSandbox

    box = getattr(project, "box", None) if project is not None else None
    return WorktreeSandbox(root=root, extra_env=tuple(getattr(box, "env", None) or ()))


def _container(**kw):
    """EVERY knob, not just the image.

    This passed `image=` alone, so `cpus`, `memory`, `network` and `cache_volume` were documented
    parameters that no caller could set — the signature-level form of this repository's signature
    defect. Two of them were load-bearing: `cache_volume` is why the docstring could claim a
    dependency cache the platform never actually mounted (a full install, every job, for ever), and
    `network` is the only way a deployment can bound what agent-written code reaches.

    Passed through by NAME rather than `**kw` so an unknown key is a TypeError here — at
    construction, naming itself — instead of a silently ignored setting, which is the failure this
    whole registry exists to prevent (ADR-0018)."""
    from openfactory.adapters.sandbox import ContainerSandbox

    known = ("project", "toolbox", "cache_volume", "cpus", "memory", "network", "extra_env")
    return ContainerSandbox(
        image=kw.get("image") or DEFAULT_BOX_IMAGE,
        **{k: kw[k] for k in known if kw.get(k) is not None},
    )


def no_local_adapter(kind: str) -> Callable[..., object]:
    """The `build` slot of a remote row: there is no local `SandboxAdapter` to build, and asking
    for one must say so rather than return a lie — pretending otherwise is what kept this axis off
    ADR-0022's audit. Exported so an add-on's remote row can use the same refusal."""

    def _refuse(**_kw):
        raise ValueError(
            f"the {kind!r} box is remote: there is no local SandboxAdapter to build. Its runner "
            f"runs the whole job on another machine — ask `remote_box({kind!r})` for it."
        )

    return _refuse


def runner_from_addon(kind: str) -> Callable[..., RemoteBox]:
    """The `remote` slot of a row the core DESCRIBES and an add-on IMPLEMENTS.

    Resolved through the plugin group at call time, never by importing the vendor package from
    here: the whole point of the row is that the package can be absent. `builtin={}` because the
    `box_runner` axis has no built-in rows to shadow — the core ships descriptions, not runners.
    """

    def _resolve(**kw) -> RemoteBox:
        from openfactory import plugins

        build = plugins.builder(RUNNER_AXIS, kind, builtin={})
        if build is None:
            raise RuntimeError(
                f"the {kind!r} box is remote and its runner is not installed on this deployment: "
                f"install the add-on that declares the `{RUNNER_AXIS}.{kind}` entry point in the "
                f"`{plugins.GROUP}` group{plugins.install_hint(RUNNER_AXIS, kind)}. Nothing was "
                f"launched."
            )
        return _checked_runner(kind, build(**kw))

    return _resolve


def _checked_runner(kind: str, runner: object) -> RemoteBox:
    """REFUSED rather than defaulted when the add-on hands back something that is not a runner —
    a launcher missing `stop` would leave every abnormal end orphaned, silently."""
    if not isinstance(runner, RemoteBox):
        raise TypeError(
            f"the runner for the {kind!r} box does not satisfy RemoteBox (launch/stop/tail): got "
            f"{type(runner).__name__}")
    return runner


def _checked(rows: dict[str, tuple]) -> dict[str, tuple]:
    """Every row answers for itself, AT IMPORT. A remote box without a runner is the orphaned-task
    defect waiting to happen; a local box with one is two facts in one row; a row filed under a
    kind its traits do not name is a row that answers the wrong question. The same check admits
    an add-on's row, so a stranger's mistake is refused with the same words as ours would be."""
    for kind, row in rows.items():
        _check_row(kind, row)
    return rows


def _check_row(kind: str, row: object) -> tuple:
    if not isinstance(row, tuple) or len(row) not in (2, 3):
        raise TypeError(f"the {kind!r} box row must be (traits, build) or (traits, build, remote); "
                        f"got {type(row).__name__}")
    traits, build = row[0], row[1]
    if not isinstance(traits, BoxTraits):
        raise TypeError(f"the {kind!r} box row does not start with BoxTraits; got "
                        f"{type(traits).__name__}")
    if traits.name != kind:
        raise TypeError(f"the box row filed under {kind!r} describes {traits.name!r}")
    if not callable(build):
        raise TypeError(f"the {kind!r} box row's build slot is not callable")
    remote = row[2] if len(row) == 3 else None
    if traits.remote and remote is None:
        raise TypeError(
            f"the {kind!r} box is remote and its row carries no runner: a remote box without a "
            f"`(traits, build, remote)` third slot would be built as a LOCAL adapter by run_job "
            f"and left alone by stop_job")
    if not traits.remote and remote is not None:
        raise TypeError(f"the {kind!r} box is local and its row carries a remote runner — a row "
                        f"says one thing about where a job runs, not two")
    return row


#: kind → (traits, build) for a local box, (traits, build, remote) for a remote one. A new box
#: joins as one row — here, or through the `box.<kind>` entry point without editing this file.
BOXES: dict[str, tuple] = _checked({
    # Isolates the CODE STATE only — no CPU, memory, network or secret isolation. For fast
    # orchestrator tests and local debugging without a Docker daemon; never for untrusted work.
    # `streams`: a plain local `Popen` with a pipe — the shortest distance there is between the
    # harness's stdout and a reader.
    "worktree": (BoxTraits("worktree", remote=False, honours_image=False, idempotent=False,
                           # the CODE STATE and nothing else — see the entry above: no CPU,
                           # memory, network or secret isolation, "never for untrusted work"
                           streams=True, isolates_resources=False,
                           # the harness is a child of this process, so its HOME is a directory on
                           # the same filesystem — a copy, not a transfer
                           transfers_state=True), _worktree),
    # The reference path. Its own docstring calls Docker "the real, production path": bounded
    # CPU and memory, ephemeral secrets, a filesystem restricted to the mounted clone. NOT the
    # network — the box has outbound internet by default because the harness needs it.
    # `streams`: `docker exec` is itself a local subprocess on the worker, and the daemon relays
    # the container process's output through it live.
    "container": (BoxTraits("container", remote=False, honours_image=True, idempotent=False,
                            # bounded CPU and memory, ephemeral secrets, a filesystem
                            # restricted to the mounted clone — its own entry above says so
                            streams=True, isolates_resources=True,
                            # `docker cp` reads and writes on the CLIENT's side of the daemon, so
                            # the bytes land on the worker even under docker-out-of-docker, where a
                            # `-v` path the worker invents is created empty on the host instead
                            # (measured both ways, 2026-08-15)
                            transfers_state=True), _container),
    # A whole job inside an ECS task. Retryable because the launcher re-attaches to a running task
    # and reconciles a finished one.
    #
    # `streams=False`, AND IT WAS MEASURED RATHER THAN ASSUMED — the card names this box as the one
    # risk in the trait, so guessing "probably not, it's remote" would have been the same shape of
    # answer it warns about. Two independent reasons, one structural and one observed:
    #
    #   STRUCTURAL — there is no local `SandboxAdapter` here at all. `_remote` below raises; the
    #   launcher runs the WHOLE job inside the task, so there is no `tail()` on this side of the
    #   wire to call. (This is the one box for which the port's PULL shape is not academic: a
    #   fargate adapter could implement `tail()` over `launcher._tail`, which already returns new
    #   lines and a cursor. What it would return is the orchestrator's events, not the harness's —
    #   see below — so the trait would still be False until that changes.)
    #
    #   OBSERVED — the only thing that crosses back is CloudWatch, and it does not carry the
    #   harness. Four real task streams from `/ecs/openfactory-sandbox` (eu-west-2, tasks 399412…,
    #   784aa4…, 7962b3…, b53c99…) were read: 712 log lines, of which 699 are
    #   `OPENFACTORY_EVENT:` envelopes from the in-task `StdoutEventSink`, 4 are the task's own
    #   result
    #   lines, 9 are prose — and ZERO are harness events. That is not an accident of sampling: the
    #   agent adapter captures the harness stream through `sandbox.run` and writes it to a
    #   transcript file inside the task, so it never reaches the task's stdout and therefore never
    #   reaches the log group. The host sees the orchestrator's narration of the job, at state
    #   changes, which is a different and much coarser thing than the harness's own pulse.
    #
    # Making this True would be worse than not having the trait: the ticker would attach, receive
    # nothing for four hours, and report a calm agent.
    #
    # DESCRIBED HERE, IMPLEMENTED ELSEWHERE. The traits are pure data and stay in the core so a
    # job in flight keeps replaying; the runner is the fargate package's, reached through the
    # `box_runner.fargate` entry point — the module docstring says why the two are split.
    # THIS ROW MOVES OUT WITH THE RUNNER (a whole `box.fargate` add-on row) once the box axis's
    # traits-as-data (`JobParams.box`, stamped by `start_jobs`) has carried a REAL plugin box
    # through a job end to end; until then `params.traits()` falls back to it for the histories
    # that predate the stamp.
    "fargate": (BoxTraits("fargate", remote=True, honours_image=False, idempotent=True,
                          # a whole ECS task: its own CPU and memory limits, its own network and
                          # task role, nothing of the worker's filesystem
                          streams=False, isolates_resources=True,
                          # STRUCTURAL, like `streams`: there is no local adapter here at all
                          # (the build slot refuses), so there is nothing on this side of the wire
                          # to copy from. The job's own box INSIDE the task is a `worktree`, which
                          # answers True — that is where the session is taken, and an object store
                          # is how it crosses back from a task the worker cannot reach.
                          transfers_state=False),
                no_local_adapter("fargate"), runner_from_addon("fargate")),
})


def _key(kind: str) -> str:
    return (kind or "").strip().lower()


def _row(kind: str, *, installed: bool) -> tuple:
    """The row for `kind`: a built-in, or — only when `installed` — an add-on's.

    `installed=False` is the WORKFLOW's lookup and consults nothing that could differ between two
    workers replaying the same history. `installed=True` is the activity side: an add-on's row is
    validated by the same `_check_row` as ours, and REFUSED rather than defaulted when it is not
    a row — the plugin loader hands back whatever the entry point named, and an entry point that
    names a bare builder would otherwise be read as a box with no traits at all."""
    key = _key(kind)
    row = BOXES.get(key)
    if row is not None:
        return row
    if installed:
        from openfactory import plugins

        make = plugins.builder(AXIS, key, builtin=BOXES)
        if make is not None:
            return _check_row(key, make())
        known = ", ".join(plugins.known(AXIS, BOXES))
    else:
        known = ", ".join(sorted(BOXES))
    raise ValueError(f"unknown box {kind!r} — known: {known}")


def box_traits(kind: str) -> BoxTraits:
    """What the lifecycle may ask about a BUILT-IN box. Safe to call from a workflow body: a dict
    lookup. An add-on's box is unknown here on purpose — its traits reach the workflow as data
    (`io.JobParams.traits`); the activity side asks `installed_box_traits`."""
    return _row(kind, installed=False)[0]


def installed_box_traits(kind: str) -> BoxTraits:
    """`box_traits`, for the activity and application side: built-in OR installed add-on. Reads
    the entry points on first use, which is I/O and therefore not for a workflow body."""
    return _row(kind, installed=True)[0]


def build_sandbox(kind: str, **kw) -> object:
    """The local `SandboxAdapter` for this kind. Raises for a remote box, and for an unknown one.

    The unknown case matters more here than the raise elsewhere: the composition root used to pick
    with a ternary — `ContainerSandbox(...) if kind == "container" else WorktreeSandbox(...)` — so
    ANY other string, including a typo, silently produced a worktree. A worktree isolates the code
    state and nothing else, which means untrusted work running outside a sandbox because somebody
    mistyped a configuration value.
    """
    return _row(kind, installed=True)[1](**kw)


def remote_box(kind: str, **kw) -> RemoteBox:
    """The runner of a REMOTE box: what `run_job` launches on, `stop_job` sweeps with, and the
    panel tails through. Raises for a local box (it has nothing to launch elsewhere), for an
    unknown one, and — naming the entry point — for a described box whose add-on is absent."""
    row = _row(kind, installed=True)
    if not row[0].remote:
        raise ValueError(f"the {kind!r} box is local: it has no remote runner. `build_sandbox` "
                         f"builds its adapter.")
    return _checked_runner(_key(kind), row[2](**kw))
