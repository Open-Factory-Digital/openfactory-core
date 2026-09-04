"""Activities — the side-effecting steps, each a durable, retryable unit.

An activity is where the framework touches the outside world (clone, run the
agent, tests, open a PR, tag, observe an environment). Temporal records each
one's result in history, so a crash resumes from the last completed activity
instead of restarting the job.

Every job runs in a Fargate task (run_job, promote_staging, release_prod), so the
side-effecting work happens where gh + credentials + the cloned repo live, and the
launcher's job-tag idempotency (re-attach / reconcile) makes retries safe. The forge
operations themselves are find-or-create idempotent. Each activity offloads its
blocking launcher call to a thread so the event loop stays free to heartbeat.
"""

from __future__ import annotations

import asyncio
import re as _re_module
import shutil
import subprocess
import time
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from openfactory.adapters.channel.registry import channel_destination
from openfactory.adapters.sandbox.registry import installed_box_traits, remote_box
from openfactory.contracts import JobState, RunResult
from openfactory.contracts.refs import canonical_ref, ref_label, ref_sort_key
from openfactory.factory import build_runner, resolve_box_image
from openfactory.registry import ProjectRegistry
from openfactory.runtime.card_repo import _checkout_key, _ref_repo, _runner_view
from openfactory.runtime.temporal.io import (
    AdjustInput,
    AskInput,
    CiRepairInput,
    CoordinatorInput,
    CoordinatorItem,
    CoordinatorSayInput,
    DeployNotifyInput,
    DeployStatusInput,
    HoldSyncInput,
    JobMetricsInput,
    JobParams,
    KnowledgeRefreshInput,
    MergeCheckInput,
    PreflightInput,
    PreflightVerdict,
    ProductAnswerInput,
    ProductAskInput,
    ProductBaselineInput,
    ProductBreakdownInput,
    ProductCardInput,
    ProductNeedsActionInput,
    ProductQueueInput,
    ProductSayInput,
    PromoteInput,
    RatePauseInput,
    ReleaseInput,
    ReviewLoopInput,
    ReviewPassInput,
    RunJobInput,
    ScanInput,
    SplitInput,
    StartJobsInput,
    TicketRef,
)


def _resolved_image(project, *, sandbox: str, explicit: str | None = None) -> str:
    """`resolve_box_image`, made NON-RETRYABLE at the activity boundary (#66).

    `resolve_box_image` raising means a project declares `box.image` for a sandbox that cannot
    honour it (ADR-0037 D4) — a DECLARATION, not a transient condition. Repeating the identical
    call cannot change the answer; the fix is a person editing the registry. Left as a plain
    `ValueError`, the SDK's default retry policy burns the activity's whole budget (3–5 attempts,
    seconds to low minutes of backoff) re-asking a question that will not change, and only THEN
    reaches a human — with the retries having bought nothing but delay before the (now correctly
    diagnosable, thanks to `describe`) park note is written.

    Every OTHER config refusal this function's callers might raise (an unknown project, an
    unreadable manifest) is a `KeyError`/`FileNotFoundError` from a DIFFERENT layer and is left
    to retry as before — narrowing this to the one call proven non-retryable rather than wrapping
    the whole activity body, which would silently swallow genuinely transient failures nearby."""
    try:
        return resolve_box_image(project, sandbox=sandbox, explicit=explicit)
    except ValueError as exc:
        raise ApplicationError(str(exc), non_retryable=True) from exc


def _project_or_none(project_name: str):
    """The Project behind a name, or None. The coordinator's queue items carry only the name, and
    the judging sandbox needs the project to know which harness credentials it declared."""
    try:
        return ProjectRegistry().get(project_name)
    except Exception as exc:  # noqa: BLE001 — advisory path; a miss must degrade, not raise
        # Said out loud: degrading to None means the judging sandbox declares no harness
        # credential, so on a Bedrock deployment this is the difference between a tech-lead that
        # answers and one that cannot reach a model at all.
        activity.logger.warning("could not resolve project %r for a judging sandbox (%s)",
                                project_name, str(exc)[:120])
        return None


def _judge_for(project_name: str):
    """The JUDGMENT harness configured for a project, resolved by name.

    Some tech-lead surfaces only carry the project's name (the coordinator's queue items), so the
    Project has to be looked up. A registry miss falls back to the default harness — but SAYS SO,
    because a silent fallback is how an experiment ends up reporting clean numbers for a harness
    nobody chose. This path is advisory and best-effort by design (ADR-0015), so it must degrade
    rather than fail; loudly is the compromise."""
    from openfactory.adapters.agent import build_techlead

    try:
        return build_techlead(ProjectRegistry().get(project_name))
    except ValueError:
        raise  # an unknown harness KIND is a config error — never paper over it
    except Exception:  # noqa: BLE001 — a registry miss/hiccup, not a config error
        activity.logger.warning(
            "judgment harness: could not resolve project %r — using the default harness",
            project_name)
        return build_techlead(None)


async def _heartbeat_while(fn, detail: str, *, tick=None) -> RunResult:
    """Run blocking work in a thread while heartbeating every ~30s, so Temporal sees the
    activity is alive (a dead worker trips heartbeat_timeout instead of the full ceiling).
    On cancellation/timeout the pending thread-task is cancelled, never leaked (H7).

    `tick` IS THE ONLY MOMENT ANYTHING IS AWAKE DURING A FOUR-HOUR PASS (C-39). `fn` blocks a
    worker thread for as long as the agent runs; this loop is already up every 30 seconds to
    heartbeat, and until now it used that to say the WORKER is alive — which is not the same claim
    as the AGENT is working, and the difference is the whole of #82. A `tick` that returns a
    sentence has it appended to the heartbeat detail, so the engine's own view of the activity
    carries it too.

    IT MUST NEVER BE ABLE TO END THE WORK. A watcher raising here would cancel a pass that was
    perfectly healthy, so it is called defensively — the heartbeat is what keeps the activity
    alive, and it is issued whether or not the tick succeeded."""
    work = asyncio.create_task(asyncio.to_thread(fn))
    try:
        while not work.done():
            note = ""
            if tick is not None:
                try:
                    note = tick() or ""
                except Exception as exc:  # noqa: BLE001 — observing must not kill the observed
                    activity.logger.warning("the harness watcher raised (%s) — the pass continues "
                                            "unwatched", str(exc)[:160])
            activity.heartbeat(f"{detail} — {note}" if note else detail)
            await asyncio.wait({work}, timeout=30)
        return work.result()
    finally:
        # the underlying Fargate task is stopped by the workflow's cleanup compensation
        if not work.done():
            work.cancel()


# ═════════════════════════════════════════════════════════════════════════════════════════════════
# WATCHING THE HARNESS WHILE IT RUNS (C-39, #82)
#
# The arithmetic already existed and was reached only from the END: `stream.pulses_of` turns a
# harness stream into pulses, `watch.read_harness` turns pulses into named stalls, and both were
# called from the 4h wall and the no-result branch. So the platform's answer to "is the agent
# stuck?" was correct and four hours late by construction.
#
# What was missing was somebody holding the other end of the pipe. `SandboxAdapter.tail()` is that
# end; this is the thing that pulls on it. Nothing here is new judgment — every decision is made by
# the same two functions the wall already uses, which is the card's "um cérebro só": a second
# decision path diverges from the first within three months.
#
# IT OBSERVES AND REPORTS. It never signals, throttles, kills or answers the agent — the card's own
# risk note says an interrupted pass leaves a half-written worktree and a half-pushed branch, and
# that interrupting is a second step, after thresholds have proven they do not fire on healthy runs.
# ═════════════════════════════════════════════════════════════════════════════════════════════════

#: THE LIVE WATCHER IS WHAT MAKES THE SILENCE SIGNAL EXIST AT ALL, and this line is where.
#:
#: Only opencode stamps its events with a wall clock, so post-mortem the other three harnesses
#: cannot answer "no event for N minutes" and `read_harness` honestly reports itself blind to it.
#: Reading LIVE removes the question: a pulse that arrives now happened now. The stamp is applied
#: only where the stream did not carry one, so a harness with a real clock keeps its own.
def _stamped(pulses: list, now: float) -> list:
    from dataclasses import replace

    return [p if p.at is not None else replace(p, at=now) for p in pulses]


class HarnessWatch:
    """One job's live reading of its own harness. Not a thread, not a clock — `tick()` is called by
    whoever already has one (`_heartbeat_while`, every ~30s).

    THE STATE IS PER PASS AND DIES WITH THE ACTIVITY: one pulse list, bounded by the events a
    single harness invocation emits (turns and tool calls — hundreds, not millions), released when
    this object is. Nothing module-level, nothing that outlives the job.
    """

    def __init__(self, *, harness: str, project: str, issue: str) -> None:
        self.harness = harness
        self.project = project
        self.issue = issue
        self._box = None
        self._events = None
        self._pulses: list = []
        #: when the box last produced ANY line, parseable or not. See `_still_writing`.
        self._last_line: float | None = None
        #: stall kinds already reported for this pass. A four-hour silence would otherwise put the
        #: same line in the panel 480 times, and a feed that repeats itself is one nobody reads on
        #: the tick that matters (`techlead.watch.worth_saying` makes the same argument for the
        #: hourly rounds).
        self._said: set[str] = set()

    def attach(self, runner) -> None:
        """The box to read and the journal to report into — BOTH from the runner, which is the
        object that actually holds them. Called from inside the worker thread the moment the runner
        exists, because that is the earliest anything can be watched; before it, `tick()` says so
        rather than reporting a quiet agent."""
        self._box = getattr(runner, "sandbox", None)
        self._events = getattr(runner, "events", None)

    def read(self, *, now: float):
        """The reading right now, or `None` when nothing could be read — and the difference is the
        whole discipline. `None` here means *could not look*: the runner does not exist yet, the
        box cannot read its own output, or this harness has no reader. `[]` pulses would mean *read
        it and it was empty*, which is a different sentence and is `read_harness`'s to write."""
        from openfactory.adapters.agent.stream import pulses_of
        from openfactory.techlead.watch import read_harness

        if self._box is None:
            return None
        try:
            new = self._box.tail()
        except Exception as exc:  # noqa: BLE001 — advisory; a box that cannot answer is not a job
            activity.logger.warning("could not read the box for %s#%s (%s)",
                                    self.project, self.issue, str(exc)[:120])
            return None
        if new is None:
            return None  # the box says it cannot read itself — never "the agent said nothing"
        if new:
            self._last_line = now
        fresh = pulses_of(self.harness, "".join(new))
        if fresh is None and not self._pulses:
            return None  # no reader for this harness: nothing may be concluded, ever
        self._pulses.extend(_stamped(fresh or [], now))
        # `grant_known=False`: the tool allow-list belongs to the agent adapter's invocation and
        # does not reach here, so the "reaching for what it was never granted" signal reports
        # itself unanswerable rather than reading absence as good behaviour.
        return self._not_the_next_command(read_harness(self._pulses, now=now, grant_known=False),
                                          now=now)

    def _not_the_next_command(self, reading, *, now: float):
        """Drop a silence finding while the box is demonstrably still writing.

        ONE BOX RUNS THREE THINGS: `setup:`, then the harness, then `validate:` — and the port's
        `tail()` says what was written, not which of them wrote it. So the agent's last pulse keeps
        ageing through a twenty-minute test suite, and a reading taken then says the harness has
        been quiet for twenty minutes. True about the harness, useless as an alarm, and a false
        alarm is how a watcher gets turned off before the real one fires.

        THIS IS NOT A SECOND CLASSIFIER, and the distinction matters because a second decision path
        is what this card explicitly forbids. `read_harness` still decides everything; this declines
        to REPORT one of its findings when the raw stream contradicts the premise it was computed
        from — the harness cannot be silent while lines are arriving.

        IT CANNOT HIDE THE STALL IT EXISTS FOR. A harness stuck at a prompt, looping inside its own
        thinking, or waiting on an approval nobody will give writes NOTHING — no lines at all — so
        `_last_line` stops moving and the finding stands. What it hides is a box that is busy with
        something else, which was never the thing being looked for."""
        from dataclasses import replace

        from openfactory.techlead.watch import HARNESS_SILENCE_MINUTES, SILENT

        if not reading.stalls or self._last_line is None:
            return reading
        if now - self._last_line >= HARNESS_SILENCE_MINUTES * 60:
            return reading
        kept = tuple(s for s in reading.stalls if s.kind != SILENT)
        return reading if len(kept) == len(reading.stalls) else replace(reading, stalls=kept)

    def tick(self) -> str:
        """Called on the heartbeat. Returns a short line for the heartbeat detail, and puts a
        stall in the job's own journal — the same sink every other event on this card goes to, so
        it lands in the panel beside them (ADR-0038: the panel is the reference surface)."""
        import time

        reading = self.read(now=time.time())
        if reading is None or not reading.stalled:
            return ""
        fresh = [s for s in reading.stalls if s.kind not in self._said]
        if not fresh:
            return ""
        self._said.update(s.kind for s in fresh)
        # ONE BRAIN. The same classifier that reads a park note reads this one, so a live stall and
        # a stall found at the wall are described and remedied identically. `reading.note` is
        # already written to be read by `classify` — see `HarnessReading.note`, which explains why
        # its wording avoids the TRANSIENT rules on purpose.
        from openfactory.techlead.classify import classify, remedy_for

        verdict = classify(reading.note)
        remedy = remedy_for(verdict)
        self._say(f"o harness parece travado: {reading.note}",
                  stalls=[s.kind for s in fresh], cause=verdict.cause,
                  remedy=remedy.action, say=remedy.say)
        return "; ".join(s.kind for s in fresh)

    def _say(self, message: str, **data) -> None:
        """Into the JOB'S OWN journal, under the job's own id — not a parallel feed.

        `_pf_emit` below keys its events `openfactory-<project>-<issue>` because the pre-flight runs
        before a job exists. This one runs INSIDE a job, and `machine._emit` keys every event of
        that job by the ticket ref, so an id of a different shape here would put the one line that
        says "this pass is stuck" in a stream of its own, next to but not among the events an
        operator is reading. Best-effort like every journal write: a telemetry hiccup must never
        end a pass, and losing the line is said out loud because a lost warning reads exactly like
        a healthy run."""
        try:
            from openfactory.observability.events import JobEvent, now_iso

            ref = canonical_ref(self.issue)
            self._events.emit(JobEvent(ts=now_iso(), job_id=ref, ticket_id=ref,
                                       kind="warning", message=message, data=data))
        except Exception:  # noqa: BLE001 — the journal is additive; never fail a job over it
            activity.logger.warning(
                "the harness watcher found a stall on %s#%s and could not journal it: %s",
                self.project, self.issue, message[:200])


def _watch_for(inp: RunJobInput) -> HarnessWatch | None:
    """A watcher for this job, or `None` WITH A REASON SAID OUT LOUD.

    A box that cannot be read must not get a watcher: it would attach, receive nothing for four
    hours and report a calm agent — silence read as health, which is the defect this whole card is
    about. `BoxTraits.streams` is the question, asked before anything starts believing an empty
    stream, and today `fargate` answers no (the harness's output never leaves the task; only the
    orchestrator's own `OPENFACTORY_EVENT:` lines reach CloudWatch). Saying so in the log is
    the honest
    half: an unwatched pass should be a known gap, not an assumption."""
    from openfactory.adapters.agent.registry import harness_kind

    try:
        # THE INSTALLED lookup, like every other activity-side question: the built-in table asked
        # here refused a plugin box before its `streams` was ever read, and the log blamed "an
        # unknown box" — a stranger's box that streams was never watched, for the wrong reason.
        if not installed_box_traits(inp.sandbox).streams:
            activity.logger.info(
                "the %r box cannot be read while it runs, so %s#%s runs unwatched — a stall in "
                "this pass stays invisible until the wall", inp.sandbox, inp.project, inp.issue)
            return None
        harness = harness_kind(_project_or_none(inp.project), "executor")
        return HarnessWatch(harness=harness, project=inp.project, issue=inp.issue)
    except Exception as exc:  # noqa: BLE001 — a watcher is advisory; never fail a job to build one
        activity.logger.warning("could not build a harness watcher for %s#%s (%s)",
                                inp.project, inp.issue, str(exc)[:120])
        return None


@activity.defn
async def run_job(inp: RunJobInput) -> RunResult:
    """Drive one ticket to a PR: get_ticket → sandbox → execute → validate →
    review → open PR. The whole existing JobRunner, as one durable step.

    A REMOTE box (`installed_box_traits(kind).remote`) runs the whole job on another machine
    through the row's own runner; a local one runs the JobRunner here (container/worktree)."""
    # Discriminates THIS run's tasks (R8) AND this lifecycle-loop iteration: an operator
    # "Resume" after an impediment must launch a FRESH task, not reconcile the previous
    # iteration's stale stopped result (same shape as repair_ci's -r{attempt}).
    run_id = activity.info().workflow_run_id
    if inp.attempt:
        run_id = f"{run_id}-a{inp.attempt}"
    # THE WATCHER IS BUILT HERE BECAUSE THIS IS THE ONLY PLACE THAT IS AWAKE (C-39). `_do_run_job`
    # blocks a worker thread for the whole pass; the heartbeat loop below is the one thing still
    # running, so it is what pulls on the box. `watch` is None for a box that cannot be read, and
    # `_watch_for` says so in the log rather than attaching a watcher that would see nothing.
    watch = _watch_for(inp)
    return await _heartbeat_while(
        lambda: _do_run_job(inp, run_id, watch=watch),
        f"{inp.project}#{inp.issue} via {inp.sandbox}",
        tick=watch.tick if watch else None,
    )


def _do_run_job(inp: RunJobInput, run_id: str | None = None,
                watch: HarnessWatch | None = None) -> RunResult:
    # BY TRAIT, NOT BY NAME. `if inp.sandbox == "fargate"` stood here, and it meant a third box
    # declaring `remote=True` was built as a LOCAL adapter by this line while `stop_job` ignored
    # it — the two halves of one lifecycle disagreeing about where the job is (measured with an
    # `ssh` row, 2026-08-24). The row's runner is the only thing that knows how to run it there.
    if installed_box_traits(inp.sandbox).remote:
        return _run_remote(inp, run_id)
    project = ProjectRegistry().get(inp.project)
    # C-18: the runner works the CARD's repository. The ref stays qualified — it is the platform's
    # identity for this job (workflow id, journal, ledger) — while every adapter under it is built
    # against that one repo, where a bare `#1` is unambiguous.
    view, repo_key = _runner_view(project, inp.issue)
    runner = build_runner(
        view, inp.issue, sandbox=inp.sandbox, image=inp.image, review=inp.review,
        repo_key=repo_key,
    )
    # THE HANDOFF, and it is the whole reason the watcher is reachable at all. The box is built
    # inside `build_runner`, three layers below this activity, and the agent adapter calls it three
    # layers further down — so a push callback would have had to be threaded through both. The
    # runner holds the box and the journal as plain fields, and this line is where the watcher
    # (which lives one frame up, in the loop that stays awake) is given them.
    if watch is not None:
        watch.attach(runner)
    result = runner.run(inp.issue, resume_handle=inp.resume_handle,
                        spent_turns=inp.spent_turns, decision=inp.decision)  # C2 + D4 + a choice
    # which A/B arm this run was in (ADR-0017's gate) — see the box path for why it's stamped
    # at the boundary, and why a dashboard dimension is never allowed to fail a finished run.
    try:
        result.knowledge = runner.knowledge_arm()
    except Exception:  # noqa: BLE001 — a DASHBOARD dimension must never fail a finished run
        # The ticket lands with no arm and the A/B silently loses a data point. Still must not fail
        # a run that succeeded — but a comparison quietly missing rows is worse than a visible gap.
        activity.logger.warning("could not record the knowledge arm for #%s", inp.issue)
    return result






def _box_for(inp: RunJobInput):
    from openfactory.runtime.boxed_job import BoxConfig

    project = ProjectRegistry().get(inp.project)
    # C-18: the box clones and works THE CARD'S repo; inside it the ref is bare — branch names,
    # issue ops and board moves all happen against that one repo, where bare is unambiguous.
    card_repo, bare_issue = _ref_repo(project, inp.issue)
    return BoxConfig(
        project=inp.project,
        issue=bare_issue,
        repo=card_repo,
        board_owner=project.tracker.options.get("board_owner"),
        board_number=project.tracker.options.get("board_number"),
        # WHICH provider the box talks to. Read off the project rather than assumed: the seam was
        # honoured here and then abandoned inside the container (ADR-0022 §1).
        tracker_kind=project.tracker.kind,
        forge_kind=(project.forge.kind if project.forge else None) or project.tracker.kind,
        # …AND EACH AXIS'S COORDINATES (#162). Whole, because they are the provider's own
        # vocabulary: `board_owner`/`board_number` above are two keys of GitHub Projects' that an
        # earlier fix hand-picked, and a box told only those cannot build an Azure adapter at all.
        tracker_options=dict(project.tracker.options or {}),
        forge_options=dict((project.forge.options if project.forge else None) or {}),
        review=inp.review,
        resume_handle=inp.resume_handle,  # C2: propagate to the remote box via env
        spent_turns=inp.spent_turns,  # D4: the effort budget's running total
        decision=inp.decision,  # a resolved human choice, injected into the box's agent
    )


def _run_remote(inp: RunJobInput, run_id: str | None = None) -> RunResult:
    """The whole job on the box's own machine, through the row's runner (`RemoteBox.launch`)."""
    from openfactory.observability.registry import journal_for
    from openfactory.paths import events_file

    project = ProjectRegistry().get(inp.project)
    # tee the task's streamed events into the host journal the panel reads (dedup: a
    # retry that re-tails from the head must not duplicate the feed — R7).
    journal = journal_for(events_file(project, inp.issue), dedup=True)
    # THE A/B ARM (knowledge/experiment.py) is decided HERE, on the worker, and carried into the
    # box. The box is credential-less by design, so it cannot read the metrics that say how the
    # arms are balanced so far — deciding there would degrade to "always inject" every time and the
    # experiment would never run while looking as though it did. No-op unless a window is open.
    from openfactory.knowledge.experiment import arm_env, arm_for

    extra_env = ({} if not getattr(project, "knowledge_experiment", False)
                 else arm_env(arm_for(project)))
    return remote_box(inp.sandbox).launch(
        _box_for(inp), journal=journal, run_id=run_id, extra_env=extra_env or None
    )


# ---------------------------------------------------------------------------
# Pre-flight sizing gate (ADR-0013 D2) — runs on the WORKER, before any Fargate.


def _tracker_for(project):
    """A tracker bound to `project` — chosen by the REGISTRY, never named here.

    THE single construction point on the worker: every activity that needs a tracker comes through
    this, so a client on Jira changes one registry value and nothing in this file."""
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.credentials import tracker_token_for
    from openfactory.factory import _bot_token_provider

    tok = tracker_token_for(project)
    return build_tracker(project, token=tok,
                         token_provider=None if tok else _bot_token_provider())


def _sizer_result_text(res) -> str:
    """The sizer's FULL final message — the sizer writes its analysis FIRST and the JSON verdict
    LAST, so the 1000-char cap chops the verdict off (live bug: #37's 3509-char response). One
    shared reader now; this name stays because the call sites read better with it."""
    from openfactory.adapters.agent.base import final_text

    return final_text(res)

def _parse_verdict(text: str) -> PreflightVerdict | None:
    """Extract the sizer's LAST fenced JSON block. None → caller degrades to fit. Tolerates
    prose around the block and minor sloppiness; never raises."""
    import json as _json
    import re as _re

    try:
        blocks = _re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, _re.DOTALL)
        raw = blocks[-1] if blocks else None
        if raw is None:  # maybe bare JSON without a fence
            m = _re.search(r"\{[^{}]*\"verdict\"[\s\S]*\}", text)
            raw = m.group(0) if m else None
        if raw is None:
            return None
        d = _json.loads(raw)
        v = str(d.get("verdict", "")).lower()
        if v not in ("fit", "split", "unclear"):
            return None
        return PreflightVerdict(
            verdict=v,
            estimated_files=d.get("estimated_files"),
            reasons=str(d.get("reasons", ""))[:800],
            children=[c for c in (d.get("children") or []) if isinstance(c, dict)][:4],
            questions=[str(q)[:300] for q in (d.get("questions") or [])][:6],
        )
    except Exception as exc:  # noqa: BLE001 — a malformed verdict degrades, never crashes
        # None means "the gate had no opinion", so the job runs. Right as a default, but if the
        # gate is malformed EVERY time it has silently stopped gating anything.
        activity.logger.warning("pre-flight verdict unreadable (%s) — the job runs ungated", exc)
        return None


# The marker every auto-split child carries in its title. Single source of truth: the splitter
# writes it, and pre-flight reads it to recognise its own children and NEVER re-size them.
_SPLIT_CHILD_MARK = "[auto-split of #"


def _pf_emit(sink, project: str, issue: str, kind: str, message: str, **data) -> None:
    """Stream one pre-flight/split event as an `OPENFACTORY_EVENT:` line on the worker's stdout
    (→ /ecs/openfactory-worker), tagged with this job's id so the panel can tail the sizing LIVE.
    The step runs on the WORKER (no Fargate task), so without this it is invisible on the
    board — the operator sees a silent card and assumes 'nothing is happening'. Best-effort:
    a telemetry hiccup must never break sizing."""
    try:
        from openfactory.observability.events import JobEvent, now_iso

        sink.emit(JobEvent(ts=now_iso(), job_id=f"openfactory-{project}-{issue}",
                           ticket_id=str(issue),
                           kind=kind, message=message, data=data))
    except Exception:  # noqa: BLE001 — the journal is additive; never fail a job over it
        # The panel's live feed loses this line, and journalling that fails repeatedly reads to an
        # operator exactly like a job doing nothing.
        activity.logger.warning("journal entry lost for %s#%s (%s)", project, issue, kind)


def _do_preflight(inp: PreflightInput) -> PreflightVerdict:
    """Judge the ticket BEFORE launching any Fargate. Every failure path returns fit+degraded
    — the gate can only ever help; it must never become a new way to block the pipeline."""
    import tempfile
    from pathlib import Path

    from openfactory.adapters.agent import build_techlead
    from openfactory.adapters.forge.registry import clone_url_for
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.adapters.sandbox.registry import judging_worktree
    from openfactory.credentials import deployment_forge_token, forge_token_for
    from openfactory.observability.registry import journal_for
    from openfactory.orchestrator.context import build_context
    from openfactory.runtime.repo_cache import RepoCache, current_branch
    from openfactory.techlead import voice as tl_voice

    project = ProjectRegistry().get(inp.project)
    tracker = _tracker_for(project)
    # THE TICKET IS THE CLIENT'S (#160). Everything this gate writes onto it is unprompted — it
    # comments before anything runs, to say why — and it went out in English on every project.
    _lang = str(getattr(project, "language", "") or "")
    events = journal_for(None, live=True)  # live pre-flight feed → panel (no Fargate task)
    _pf_emit(events, inp.project, inp.issue, "state", "sizing",
             note="pre-flight — judging INVEST (one small, testable outcome?)")
    # Intentional skips (the gate is OFF, or an e2e ticket) are silent; a FAILURE to actually
    # size (broken gate: no token, clone/sizer error, garbage verdict) must NEVER be silent —
    # it means the ticket ran UNSIZED and nobody knew (the live #37 bug). Surface those loudly:
    # a warning comment on the ticket + a log line, so a degraded gate is always visible.
    _INTENTIONAL = {"disabled", "e2e ticket"}

    def degrade(reason: str) -> PreflightVerdict:
        _pf_emit(events, inp.project, inp.issue,
                 "note" if reason in _INTENTIONAL else "warning",
                 f"pre-flight did not size ({reason}) — proceeding UNSIZED")
        if reason not in _INTENTIONAL:
            print(f"OPENFACTORY_PREFLIGHT: DEGRADED for {inp.project}#{inp.issue} — "
                  f"{reason}", flush=True)
            try:
                tracker.comment(
                    f"#{inp.issue.lstrip('#')}",
                    tl_voice.say(tl_voice.NARRATION, "preflight.unsized", _lang, why=reason))
            except Exception:  # noqa: BLE001 — surfacing is best-effort, never blocks
                # Nobody is told the ticket went through UNSIZED — the one case this warning exists
                # for, so a later "why was this so big?" has an answer.
                activity.logger.warning("could not warn #%s that it proceeded unsized", inp.issue)
        return PreflightVerdict(degraded=reason)

    # `project.repo_path` is a REGISTRY value — on Fargate it's where the entrypoint clones
    # to (a real path inside that container); on the WORKER it names no real directory at
    # all. So the worker must sync its OWN cached checkout FIRST and load the manifest from
    # THAT — never from `project.repo_path` directly (the bug that made every worker-side
    # preflight degrade: "no manifest at /work/<project>/.sdlc/project.yaml").
    #
    # THE CARD'S repo, not the project's (C-18): each source repo carries its own manifest, and
    # sizing a `…-web` ticket against `…-api`'s components is sizing the wrong world.
    repo, _ = _ref_repo(project, inp.issue)
    cache_key = _checkout_key(project, repo)
    # PER PROJECT (`forge_token_for`): this clones the CARD'S repository, and on a
    # deployment hosting two forges the process-wide value is the other vendor's.
    token = forge_token_for(project) or deployment_forge_token(project)
    # THE BASE BRANCH IS NOT KNOWN UNTIL THE MANIFEST LOADS, and the manifest lives inside the
    # checkout — so the first sync asks for the registry's named base if there is one and OTHERWISE
    # for nothing at all, letting the clone land where the repository points (#162). It used to ask
    # for the literal `main`, which is not a guess that costs a fetch: on a `master` repository
    # `--branch main` names nothing, the clone fails, and this function degrades — so EVERY ticket
    # on such a client proceeded UNSIZED, hourly, with a message blaming reachability. The manifest
    # itself is expected identical across branches; we re-sync below if it names another.
    # THE URL RESOLUTION IS INSIDE THE GUARD, not just the clone. `clone_url_for` goes through the
    # forge registry, which RAISES on a kind it does not know — correctly, because a clone aimed at
    # the wrong host is the most expensive configuration error there is. But the preflight's entire
    # contract is that it never stops a ticket: it degrades and says so, loudly, on the card. A
    # ValueError escaping here would turn a misconfigured registry row into a dead job, which is
    # worse than the unsized ticket this function exists to avoid. It read as a pure function until
    # the URL became a provider question, so the old `try` did not need to cover it.
    try:
        url = clone_url_for(project, repo, token=token)
    except Exception as exc:  # noqa: BLE001 — a bad provider row must degrade, never kill the job
        return degrade(f"clone: {str(exc)[:160]}")
    from openfactory.loader import load_manifest_base_branch

    asked = load_manifest_base_branch(project, default="")
    repo_path = RepoCache().sync(cache_key, url, asked)
    if repo_path is None:
        return degrade("clone: could not reach the repo for a worker-side checkout")

    try:
        from openfactory.loader import load_manifest  # local: the tests' patch seam
        manifest = load_manifest(project.model_copy(update={"repo_path": str(repo_path)}))
    except Exception as exc:  # noqa: BLE001
        return degrade(f"manifest: {str(exc)[:120]}")
    if not manifest.preflight.enabled:
        return degrade("disabled")
    # RE-SYNC AGAINST WHAT WE ACTUALLY LANDED ON, not against the literal `main`. Comparing to
    # `main` re-fetched every `master` repository whose manifest says `master` — and, worse, did
    # NOT re-fetch a `main`-registered project whose manifest names a different base, because the
    # comparison was about the wrong branch entirely.
    # `declared_base_branch`, NOT `base_branch` — the field has the schema default `"main"`, so
    # reading it as a declaration re-clones a `master` client at a branch that does not exist,
    # one line after resolving the right one. Adversarial review, 2026-08-20.
    declared = manifest.declared_base_branch
    if declared and declared != current_branch(repo_path):
        repo_path = RepoCache().sync(cache_key, url, declared)
        if repo_path is None:
            return degrade(f"clone: could not sync branch {declared!r}")

    try:
        ticket = tracker.get_ticket(inp.issue)
    except Exception as exc:  # noqa: BLE001
        return degrade(f"ticket: {str(exc)[:120]}")
    # A ticket that is ITSELF a split child is already a scoped, sized work unit — NEVER
    # re-size it. Re-sizing recurses: the sizer splits the child again (and again), a runaway
    # cascade that spawns ever-smaller Plan 92x… tickets. The auto-split title marker is how we
    # recognise our own children; they go straight to fit → the pipeline codes them. (A child
    # that truly is too big is a human call — re-drop it, don't let the gate loop.)
    if _SPLIT_CHILD_MARK in (ticket.title or ""):
        _pf_emit(events, inp.project, inp.issue, "note",
                 "fit — split child (already scoped by an earlier split), going to code",
                 verdict="fit")
        return PreflightVerdict(verdict="fit")
    # e2e tickets aren't implemented at all (ADR-0008) — sizing is meaningless for them
    if manifest.e2e_workflow and manifest.e2e_label.lower() in ticket.labels:
        return degrade("e2e ticket")

    if not manifest.preflight.code_check:
        repo_path = None  # text-only judgment — the sizer gets no checkout to explore

    try:
        ctx = build_context(manifest, repo_path or Path(project.repo_path), ticket)
        # Sizing is INVEST-only (owner decision): judge conceptual cohesion — one outcome or
        # several — NOT a file-count budget. So we give the sizer the repo to understand the
        # change, but no numeric budget to tally against.
        ctx.guidelines.append(
            ("Working directory: a read-only checkout of the repo. "
             if repo_path else "No code checkout was provided — judge from the ticket text alone. ")
            + "Judge size by INVEST (one cohesive, independent, testable outcome), "
              "never by counting files."
        )
        agent = build_techlead(project)  # the sizer is JUDGMENT, not coding
        if not hasattr(agent, "size"):  # a future adapter without a sizer → gate is a no-op
            return degrade("adapter has no sizer")
        # code_check=false → no checkout for the sizer to explore; give it the (unused-for-
        # read) cache root so Workspace has a valid path — the sizer's prompt already says
        # "no code checkout was provided" and its tools are read-only Read/Grep/Glob anyway.
        ws = Workspace(path=repo_path or Path(tempfile.gettempdir()), branch=manifest.base_branch,
                       base_branch=manifest.base_branch)
        sandbox = judging_worktree(
            project, root=Path(tempfile.gettempdir()) / "openfactory-preflight")
        res = agent.size(sandbox=sandbox, workspace=ws, context=ctx)
        if not res.ok and res.pause_reason:
            return degrade(f"agent paused: {res.pause_reason}")
        sizer_text = _sizer_result_text(res)
        verdict = _parse_verdict(sizer_text)
        if verdict is None:
            # Log the tail so a genuinely malformed verdict is diagnosable without a rerun.
            print(f"OPENFACTORY_PREFLIGHT: unparseable verdict ({len(sizer_text)} chars) "
                  f"tail={sizer_text[-300:]!r}", flush=True)
            return degrade("unparseable verdict")
    except Exception as exc:  # noqa: BLE001
        return degrade(f"sizer: {str(exc)[:120]}")

    # Stream the verdict so the operator SEES the decision land, live, on the card.
    if verdict.verdict == "split":
        titles = ", ".join(c.get("title", "?") for c in verdict.children)
        _pf_emit(events, inp.project, inp.issue, "note",
                 f"verdict: SPLIT into {len(verdict.children)} — {titles}", verdict="split")
    elif verdict.verdict == "unclear":
        _pf_emit(events, inp.project, inp.issue, "note",
                 "verdict: UNCLEAR — needs the ticket clarified first", verdict="unclear")
    else:
        _pf_emit(events, inp.project, inp.issue, "note",
                 "verdict: FIT — one small change, proceeding into the pipeline", verdict="fit")

    # Surface the judgment on the ticket so the operator sees WHY before anything runs.
    try:
        if verdict.verdict == "unclear":
            qs = ("\n".join(f"- {q}" for q in verdict.questions)
                  or tl_voice.say(tl_voice.NARRATION, "preflight.no-questions", _lang))
            tracker.comment(ticket.id, tl_voice.say(tl_voice.NARRATION, "preflight.unclear",
                                                    _lang, questions=qs))
        elif verdict.verdict == "split":
            kids = "\n".join(f"- **{c.get('title', '?')}** — {c.get('objective', '')}"
                             for c in verdict.children)
            tracker.comment(ticket.id, tl_voice.say(tl_voice.NARRATION, "preflight.too-large",
                                                    _lang, why=verdict.reasons, children=kids))
    except Exception:  # noqa: BLE001 — commentary is cosmetic
        activity.logger.warning("could not comment the sizing verdict on #%s", inp.issue)
    return verdict


def _clipped(text: str, limit: int) -> str:
    """`text` cut at a WORD boundary, with an ellipsis when it was cut.

    A hard slice ends mid-word and can leave an unbalanced bracket: the pilot's own split
    announcement read "…with an unaddressed 1/day quota conflict) to)." — a sentence that stops
    in the middle of a thought, with a stray `to` and a parenthesis that closes nothing. A reader
    cannot tell that from a sentence the model wrote badly.
    """
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    # `rsplit` WITH NO SEPARATOR RETURNS THE WHOLE STRING, so a single word longer than the cap
    # comes back intact rather than empty — the `or clean[:limit]` this line used to carry was a
    # branch nothing could reach, found by a mutation that removed it and stayed green.
    cut = clean[:limit].rsplit(" ", 1)[0].rstrip(" ,;:([{-")
    return f"{cut}…"


def _child_title(parent_title: str, i: int, parent_ref: str) -> str:
    """The child's issue title — DETERMINISTIC, derived ONLY from the parent, NEVER from the
    LLM's per-child text. That is what makes the split idempotent: a re-run of the sizer
    (a re-drop, a workflow retry) produces the SAME titles, so find-or-create REUSES the
    existing children instead of spawning a fresh duplicate set — the bug that littered the
    board with 30 near-identical 'Plan 92x' issues. The title also carries the parent→child
    link and marks the ticket auto-generated:
        'Plan 92 — Guest hardening'  →  'Plan 92a — Guest hardening [auto-split of #37]'
    Deliberately independent of the child COUNT (no i/N), so even a re-size that proposes a
    different number of children still matches a,b,c… by letter. The child's SPECIFIC scope
    (the LLM's objective + criteria) lives in the body, never the title."""
    import re as _re

    letters = "abcdefghijklmnopqrstuvwx"
    # Strip any prior auto-split marker off the parent text so a (defensive) re-split can't
    # stack '[auto-split of #37] [auto-split of #385]' tails — the title stays clean.
    clean = (parent_title.split(_SPLIT_CHILD_MARK, 1)[0].strip()
             if _SPLIT_CHILD_MARK in parent_title else parent_title)
    m = _re.search(r"(Plan\s+\d+)", clean, _re.IGNORECASE)
    tag = f"[auto-split of {parent_ref}]"
    if m:
        desc = clean.split(" — ", 1)[1].strip() if " — " in clean else ""
        base = f"{m.group(1)}{letters[i]}" + (f" — {desc}" if desc else "")
    else:  # no house 'Plan N' — suffix the whole parent title with the letter
        base = f"{clean.strip()} ({letters[i]})"
    return f"{base} {tag}"


def _child_body(child: dict, parent_ref: str, order: int, total: int) -> str:
    # The LLM's specific framing moves to the body (the title is deterministic) so the card
    # still shows WHAT this child covers — as a Focus line, plus the full objective/criteria.
    focus = str(child.get("title", "")).strip()
    head = f"**Focus:** {focus}\n\n" if focus else ""
    crits = ("\n".join(f"- {c}" for c in (child.get("criteria") or []))
             or "- (define before running)")
    ordering = (f"\n\n## Out of scope\n- Everything covered by the sibling sub-tickets of "
                f"{parent_ref} (this is part {order}/{total}; run in order).")
    return (f"{head}## Objective\n{child.get('objective', '')}\n\n"
            f"## Acceptance criteria\n{crits}{ordering}\n\n"
            f"_Auto-split from {parent_ref} by the pre-flight sizer (ADR-0013)._")


def _children_safe(tracker, parent_ref: str) -> list[str]:
    """Native child refs of `parent_ref`, defensively (a tracker may not implement linkage)."""
    fn = getattr(tracker, "children_of", None)
    if not fn:
        return []
    try:
        return fn(parent_ref) or []
    except Exception as exc:  # noqa: BLE001 — a tracker may not implement linkage
        activity.logger.info("could not read the children of %s (%s) — treating it as childless",
                             parent_ref, exc)
        return []


def _link_safe(tracker, parent_ref: str, child_ref: str) -> None:
    """Best-effort native parent→child link (no-op if the tracker doesn't support it)."""
    fn = getattr(tracker, "link_child", None)
    if not fn:
        return
    try:
        fn(parent_ref, child_ref)
    except Exception as exc:  # noqa: BLE001 — a link is not worth failing a split
        # The child is orphaned: it exists, but nothing connects it to what it came from, and the
        # epic that spawned it will never look complete.
        activity.logger.warning("could not link %s under %s (%s)",
                                child_ref, parent_ref, str(exc)[:120])


def _ticket_url_or(tracker, ref: str, fallback: str) -> str:
    """The provider's own ticket URL, or `fallback` — never an exception, never empty.

    ASKED, NOT COMPOSED (`TrackerAdapter.ticket_url`), because a vendor's URL shape is the
    provider's knowledge: the literal this replaced ignored `GH_HOST`, so a GitHub Enterprise
    deployment linked to public github.com where a same-named repository may belong to somebody
    else.

    DEFENSIVE ON PURPOSE, which the first version was not. Only the GitHub Projects board
    consumes this value (it attaches a card by URL; Jira and Azure Boards ignore it), so it is a
    nicety at a call site whose job is MOVING THE CARD — and an adapter or a test double without
    the method, or one that raises, must not stop the move. Measured: three suites went red the
    moment this was called unguarded.
    """
    ask = getattr(tracker, "ticket_url", None)
    if not callable(ask):
        return fallback
    try:
        return (ask(ref) or "").strip() or fallback
    except Exception as exc:  # noqa: BLE001 — a link is never worth failing a board move for
        # SWALLOWED, BUT NEVER SILENT (the house rule, enforced by test_no_silent_failures):
        # degrading to a composed link is correct here and still a fact somebody debugging a
        # wrong URL needs to find.
        activity.logger.info("the tracker could not give a URL for %s — using the composed "
                             "one (%s)", ref, exc)
        return fallback


def _child_to_todo(tracker, ref: str) -> bool:
    """Queue one split child in TO-DO, reporting whether the move POSITIVELY happened.

    `tracker.set_state` swallows the board adapter's bool (its base contract returns None), so a
    rate-limited `gh project item-edit` left children column-less — invisible to the poller's
    exact-match `items_in_status("TO-DO")` — while the parent's close comment and the Slack
    announcement claimed they were queued. When the tracker exposes its board, ask the board
    directly and keep the bool; a tracker without one (labels, Jira) reports no outcome, so
    no-raise is the only success signal it has."""
    board = getattr(tracker, "board", None)
    repo = getattr(tracker, "repo", "")
    num = canonical_ref(ref)
    # `num.isdigit()` used to gate this too — a second place the platform quietly assumed GitHub.
    # The ref now travels as the provider's own string; the URL below is still GitHub-shaped, which
    # is honest: this whole branch only runs when the tracker HAS a `board` attribute, and today
    # that is only the GitHub adapter.
    if board is not None and hasattr(board, "set_status") and repo and num:
        # the ref may carry its repo (C-18): the URL and the board match must both follow it
        from openfactory.contracts.refs import split_repo_ref

        card_repo, bare = split_repo_ref(num, repo)
        # ASKED OF THE TRACKER, NOT COMPOSED HERE. Only the GitHub Projects board consumes this
        # (it attaches a card by URL; Jira and Azure Boards ignore it), so the literal was not
        # WRONG — it was in the wrong place, and `ticket_url` exists on the port precisely
        # because a vendor's URL shape is the provider's knowledge. It also honours GH_HOST,
        # which this literal did not: on GitHub Enterprise it pointed at public github.com,
        # where a same-named repository may belong to somebody else.
        return bool(board.set_status(
            issue=num,
            # vendor-url-ok: the PORT is asked first (`_ticket_url_or`) and answers for all three
            # vendors; this literal is the fallback for a tracker OBJECT without the method — a
            # test double, or an adapter mid-migration. It is safe to be GitHub-shaped because
            # `issue_url` is consumed by the GitHub Projects board alone: Jira and Azure Boards
            # take the argument and ignore it.
            issue_url=_ticket_url_or(tracker, num,
                                     f"https://github.com/{card_repo}/issues/{bare}"),
            state=JobState.TODO))
    tracker.set_state(ref, JobState.TODO)
    return True


def _do_split(inp: SplitInput) -> str:
    """Create the children, LINK them to the parent natively, and close it. IDEMPOTENT on two
    levels: (1) DECISION — if the tracker already records native children for this parent, the
    split was already taken, so reuse them and never split twice; (2) per-child — deterministic
    titles make find-or-create reuse an existing child. Together they killed the '8 re-runs →
    30 duplicate Plan 92x issues' bug.

    Children go straight to TO-DO in ORDER (ADR-0013 D3, owner decision — keep the flow
    autonomous). Single-line strict makes this dependency-safe: the poller picks them one at a
    time in board order (creation order = 92a before 92b), and holds the floor until each MERGES
    — so 92b only runs once 92a's code is on main. `split_to_todo: false` reverts to Backlog."""
    from openfactory.observability.registry import journal_for

    project = ProjectRegistry().get(inp.project)
    tracker = _tracker_for(project)
    events = journal_for(None, live=True)  # live split feed → panel (same card as the sizing)
    try:
        from openfactory.loader import load_manifest  # local: the tests' patch seam
        to_todo = load_manifest(project).split_to_todo
    except Exception as exc:  # noqa: BLE001 — config trouble → the safe default (autonomous flow)
        # THIS DEFAULT SPENDS MONEY: the children go straight to TO-DO and the poller picks them
        # up, on a project that may have asked for Backlog. Autonomy is the right default, and a
        # config read that failed is exactly when somebody should know which default was taken.
        activity.logger.warning(
            "could not read %s's split policy (%s) — sending the children straight to TO-DO",
            inp.project, str(exc)[:120])
        to_todo = True
    parent_ref = f"#{inp.issue.lstrip('#')}"
    n = len(inp.children)

    # DECISION idempotency: if the parent already carries the WHOLE set of native children, this
    # ticket was already split — reuse them, don't create a second set (nor a second close
    # comment).
    #
    # AGAINST THE DECISION, NEVER AGAINST ZERO. "Some children exist" and "the split is done" are
    # different facts, and reading the first as the second turns any interruption mid-loop into a
    # permanently truncated split reported as success: the forge answers `#a` and `#b`, children
    # three and four are never created, the parent is never closed, and the workflow returns
    # `done`. That interruption is now ordinary rather than exotic — `find_ticket` RAISES when the
    # search is throttled (adapters/tracker/github.py: search carries a much lower limit than
    # issue creation), which is exactly the shape that leaves half a set behind. The loop below is
    # find-or-create on deterministic titles, so resuming re-uses what exists and finishes the
    # rest.
    existing = _children_safe(tracker, parent_ref)
    if existing and len(existing) >= n:
        links = ", ".join(existing)
        _pf_emit(events, inp.project, inp.issue, "state", "done",
                 note=f"already split → {links} (reusing, no duplicates)")
        return f"already split into {links}"
    if existing:
        activity.logger.warning(
            "OPENFACTORY_SPLIT_RESUMED %s — %d of %d children exist; a previous pass stopped "
            "mid-split, "
            "so the rest are created and the parent is closed now", parent_ref, len(existing), n)
        _pf_emit(events, inp.project, inp.issue, "note",
                 f"resuming an interrupted split ({len(existing)} of {n} already created)")

    parent = tracker.get_ticket(parent_ref)
    _pf_emit(events, inp.project, inp.issue, "state", "splitting",
             note=f"creating {n} children and closing the parent")
    refs: list[str] = []
    stragglers: list[str] = []  # created but NOT positively queued — every claim below wears this
    for i, child in enumerate(inp.children):
        # DETERMINISTIC title → find-or-create reuses an existing child on a re-run instead
        # of duplicating it (idempotent split). The LLM framing goes in the body.
        title = _child_title(parent.title, i, parent_ref)
        ref = tracker.find_ticket(title=title) or tracker.create_ticket(
            title=title, body=_child_body(child, parent_ref, i + 1, n))
        refs.append(ref)
        _link_safe(tracker, parent_ref, ref)  # native parent→child (traceability + decision idem)
        queued = False
        if to_todo:
            # Move to TO-DO in creation order so the poller picks 92a before 92b.
            try:
                queued = _child_to_todo(tracker, ref)
            except Exception as exc:  # noqa: BLE001 — the split happened; the queueing did not
                activity.logger.warning("split child %s: board move raised (%s)",
                                        ref, str(exc)[:120])
            if not queued:
                # A never-moved child sits column-less, unreachable by the poller's exact-match
                # TO-DO scan — work that vanishes unless a person hears which card to drag.
                stragglers.append(ref)
                activity.logger.error(
                    "OPENFACTORY_SPLIT_CHILD_NOT_QUEUED %s — created but not in TO-DO; nothing "
                    "picks "
                    "it up until somebody moves it", ref)
        dest_note = ("TO-DO" if queued
                     else ("NOT QUEUED — move it by hand" if to_todo else "Backlog"))
        _pf_emit(events, inp.project, inp.issue, "note", f"created {title} → {dest_note}")
    links = ", ".join(refs)
    if not to_todo:
        where = "in Backlog — drag to TO-DO in order when ready"
    elif stragglers:
        # The parent still closes (the split DID happen), but its record must never claim a queue
        # position the board refused — that claim is how work vanishes behind a confirmation.
        #
        # THE SAME SENTENCE THE CHANNEL GETS, and it had the same defect: "drag them" about one
        # refused card. This half lands on the CLIENT'S TICKET, which outlives the channel message
        # and is where somebody reads the history six months later.
        one = len(stragglers) == 1
        where = (f"in TO-DO except {', '.join(stragglers)} — the board move failed; "
                 + ("drag that one to TO-DO after the others or it will never run" if one
                    else "drag those to TO-DO in order or they will never run"))
    else:
        where = "in TO-DO — they will run one at a time, in order (single-line)"
    tracker.close_ticket(
        parent_ref,
        f"Pre-flight: too large for one autonomous ticket ({inp.reasons[:300]}).\n"
        f"Split into: {links} ({where}).",
    )
    _pf_emit(events, inp.project, inp.issue, "state", "done",
             note=f"split complete → {links} ({where})")
    try:  # ADR-0015: announce the split in Slack — a split MODIFIES the planned sequence (new
        # tickets, new order), so the humans who queued it must hear WHAT changed and how the board
        # looks now, not discover extra cards silently. Best-effort; never fails the split.
        from openfactory.factory import notifier_for_project
        from openfactory.techlead import voice as tl_voice

        # IN THE PROJECT'S LANGUAGE (#160). This announcement was welded Portuguese and reached
        # every client of every deployment — the split is unprompted by definition, so nobody
        # asked for it in any language.
        lang = str(getattr(project, "language", "") or "")
        # THE STUCK CHILD IS MARKED IN THE LIST. The sentence names its ref and the list under it
        # repeated three near-identical titles, so a reader had to cross-reference a number
        # against them to find the one card they had to move (measured on the pilot).
        stuck_note = tl_voice.say(tl_voice.NARRATION, "split.not-queued", lang)
        kids = "\n".join(
            f"  {'⚠' if r in stragglers else '•'} {r} — "
            f"{_child_title(parent.title, i, parent_ref)}"
            + (f"  ← {stuck_note}" if r in stragglers else "")
            for i, r in enumerate(refs))
        head = tl_voice.say(tl_voice.NARRATION, "split.head", lang, parent=parent_ref,
                            title=parent.title[:80], n=n, why=_clipped(inp.reasons, 160))
        if to_todo and stragglers:
            # ONE OR SEVERAL IS A DIFFERENT SENTENCE — see the note on these rows. English needs
            # the agreement and Portuguese hid the defect, which is why both rows exist.
            body = tl_voice.say(
                tl_voice.NARRATION,
                "split.straggler-one" if len(stragglers) == 1 else "split.stragglers",
                lang, n=n, stuck=", ".join(stragglers), children=kids)
        else:
            body = tl_voice.say(
                tl_voice.NARRATION, "split.created", lang, children=kids,
                where=tl_voice.say(tl_voice.NARRATION,
                                   "split.to-todo" if to_todo else "split.to-backlog", lang))
        notifier_for_project(project).notify(
            message=head + body, level="warning" if stragglers else "info")
    except Exception:  # noqa: BLE001 — the narration is additive; never fail the split
        activity.logger.warning("could not announce the split of %s", parent_ref)
    if stragglers:
        return f"split into {links} (not queued: {', '.join(stragglers)})"
    return f"split into {links}"


@activity.defn
async def split_ticket(inp: SplitInput) -> str:
    """ADR-0013 D3 — the autonomous splitter: children created with the .a/.b naming, parent
    linked + closed. The children land in Backlog; sequencing stays a human decision."""
    return await _heartbeat_while(
        lambda: _do_split(inp), f"split {inp.project}#{inp.issue}"
    )


@activity.defn
async def preflight_check(inp: PreflightInput) -> PreflightVerdict:
    """ADR-0013 D2: size the ticket on the worker (text INVEST + read-only code estimate)
    BEFORE any Fargate launch. Degrades to verdict='fit' on ANY trouble."""
    result = await _heartbeat_while(
        lambda: _do_preflight(inp), f"preflight {inp.project}#{inp.issue}"
    )
    return result


@activity.defn
async def stop_job(inp: RunJobInput) -> int:
    """Cleanup: stop whatever a REMOTE box left running for this job (0 for a local box, whose
    process died with the worker). Called by the workflow when a job ends abnormally, so nothing
    is left orphaned and billing.

    THE SAME QUESTION `_do_run_job` ASKS, answered from the same row — it used to ask `!= "fargate"`
    and return 0 for every other kind, which for a remote add-on box is the orphaned task the
    `remote` trait exists to prevent, reported as a clean sweep."""
    if not installed_box_traits(inp.sandbox).remote:
        return 0
    return await asyncio.to_thread(lambda: remote_box(inp.sandbox).stop(_box_for(inp)))


def _run_promotion(
    project_name: str, issue: str, phase: str, extra_env: dict, run_id: str | None = None,
    *, sandbox: str,
) -> RunResult:
    """One promotion phase (`staging` | `release`) on the job's box.

    ONLY A REMOTE BOX HAS AN IMPLEMENTATION TODAY, and this says so rather than dying on a missing
    vendor environment. The phase runs the box program (`runtime/boxed_job.py`) with
    `OPENFACTORY_PROMOTE_PHASE` set, which the local boxes do not run — they run a `JobRunner`, and
    it has no promotion verb. Until it does, a local deployment whose manifest declares
    environments reaches this refusal by NAME instead of a `KeyError` about another vendor's
    cluster; it is non-retryable because repeating it cannot change the answer."""
    from openfactory.runtime.boxed_job import BoxConfig
    from openfactory.runtime.temporal.io import default_sandbox

    # "" = the deployment's box, resolved HERE on the worker: the promotion inputs are built inside
    # the workflow body, which may not read the environment (see `PromoteInput.sandbox`).
    sandbox = sandbox or default_sandbox()
    if not installed_box_traits(sandbox).remote:
        raise ApplicationError(
            f"the {phase!r} promotion phase has no implementation for the local {sandbox!r} box: "
            f"promotion runs the box program on a remote box only. Either run the deployment on "
            f"a remote box or drop `environments:` from the manifest until a local promotion "
            f"exists — nothing was promoted.", non_retryable=True)
    project = ProjectRegistry().get(project_name)
    card_repo, bare_issue = _ref_repo(project, issue)  # C-18: promote acts on the card's repo
    box = BoxConfig(
        project=project_name,
        issue=bare_issue,
        repo=card_repo,
        board_owner=project.tracker.options.get("board_owner"),
        board_number=project.tracker.options.get("board_number"),
        tracker_kind=project.tracker.kind,
        forge_kind=(project.forge.kind if project.forge else None) or project.tracker.kind,
        tracker_options=dict(project.tracker.options or {}),   # #162, as in `_box_for`
        forge_options=dict((project.forge.options if project.forge else None) or {}),
    )
    return remote_box(sandbox).launch(
        box,
        variant=f"-{phase}",
        extra_env={"OPENFACTORY_PROMOTE_PHASE": phase, **extra_env},
        timeout=1800,  # 30min — below the activity's 40min ceiling (R2)
        run_id=run_id,
    )


@activity.defn
async def check_pr_merged(inp: MergeCheckInput) -> bool:
    """Read-only: has the PR actually been merged? The workflow polls this durably
    between PR_OPEN and promotion, so staging is never verified against a base that
    doesn't contain the change (A2). Runs on the worker (gh + bot creds baked)."""

    forge = _forge_for(ProjectRegistry().get(inp.project))
    return await asyncio.to_thread(lambda: forge.pr_merged(pr=inp.pr_url))


@activity.defn
async def check_pr_status(inp: MergeCheckInput) -> str:
    """Read-only: the PR's lifecycle state — "merged" | "closed" | "open". The durable
    merge-watch polls this so a PR a human CLOSES without merging ends the watch at once
    (ADR-0007) instead of holding the floor until the merge deadline. Worker (gh + creds)."""

    forge = _forge_for(ProjectRegistry().get(inp.project))
    return await asyncio.to_thread(lambda: forge.pr_status(pr=inp.pr_url))


def _forge_for(project):
    """The project's forge — chosen by the REGISTRY, never named here.

    THE single construction point on the worker: six activities built one independently, each
    repeating the same repo fallback and the same token dance. A client on another forge now
    changes one registry value and nothing in this file."""
    from openfactory.adapters.forge.registry import build_forge
    from openfactory.credentials import forge_token_for
    from openfactory.factory import _bot_token_provider

    # PER PROJECT, because one deployment hosts N projects and they no longer share a forge. The
    # process-wide `forge_token()` that stood here is a GitHub credential on every deployment that
    # sets OPENFACTORY_BOT_TOKEN, and this is the helper EVERY forge read in this file goes through.
    tok = forge_token_for(project)
    return build_forge(project, token=tok,
                       token_provider=None if tok else _bot_token_provider())


@activity.defn
async def pr_mergeable_state(inp: MergeCheckInput) -> str:
    """Read-only: the PR's mergeability ('clean'/'behind'/'blocked'/'dirty'/'unstable'/'unknown')
    so the merge-watch can KEEP A BEHIND PR FRESH instead of waiting on a merge that never fires
    (busy-main starvation). Worker (gh + creds)."""
    forge = _forge_for(ProjectRegistry().get(inp.project))
    return await asyncio.to_thread(lambda: forge.mergeable_state(pr=inp.pr_url))


@activity.defn
async def update_pr_branch(inp: MergeCheckInput) -> bool:
    """Bring a BEHIND PR up to date with its base via GitHub's update-branch API, so auto-merge
    can proceed — the self-heal for a PR that keeps falling behind other developers' merges.
    Best-effort: False on any error (the loop then escalates rather than looping forever)."""
    forge = _forge_for(ProjectRegistry().get(inp.project))
    return await asyncio.to_thread(lambda: forge.update_branch(pr=inp.pr_url))


@activity.defn
async def force_merge_pr(inp: MergeCheckInput) -> bool:
    """Merge NOW, bypassing the up-to-date gate — the executable 'merge it now' option a human
    picked on a starving PR. True on success; False if even admin merge is refused (stays
    parked). Worker (gh + creds)."""
    forge = _forge_for(ProjectRegistry().get(inp.project))

    def _do() -> bool:
        try:
            forge.force_merge(pr=inp.pr_url)
            return True
        except Exception as exc:  # noqa: BLE001 — refusal is an answer; it parks
            activity.logger.warning("admin merge refused for %s (%s) — the PR stays parked",
                                    inp.pr_url, exc)
            return False

    return await asyncio.to_thread(_do)


@activity.defn
async def merge_pr_now(inp: MergeCheckInput) -> bool:
    """Land the PR a human just approved at the merge gate (#68). True on success.

    `forge.merge_pr`, NOT `force_merge` — and that distinction is the whole of this function.
    `force_merge_pr` above uses `gh pr merge --admin`, which rides through the client's OWN branch
    protection: their required reviews, their required checks. It is correct THERE because it
    fires only on a PR already reported clean, where there is nothing left to bypass. Here a
    person is answering a gate on a PR that may still be blocked, and the platform must not be the
    way somebody gets around a rule their own organisation set.

    REFUSAL IS AN ANSWER, returned rather than raised, exactly as `force_merge_pr` does — the
    caller turns False into a parked question naming branch protection, because a merge button
    that quietly does nothing is the failure this card exists to end."""
    forge = _forge_for(ProjectRegistry().get(inp.project))

    def _do() -> bool:
        try:
            forge.merge_pr(pr=inp.pr_url)
            return True
        except Exception as exc:  # noqa: BLE001 — refusal is an answer; the caller asks again
            activity.logger.warning("merge refused for %s (%s) — the human is told why",
                                    inp.pr_url, exc)
            return False

    return await asyncio.to_thread(_do)


@activity.defn
async def close_pr(inp: MergeCheckInput) -> bool:
    """Close the PR a human discarded at the merge gate, WITHOUT merging (#68).

    Nothing is deleted: `gh pr close` leaves the branch and its commits exactly where they are, so
    discard is reversible and does not deserve the password gate a production release has. Said
    out loud because 'discard' sounds destructive and a human reading the button deserves to know
    it is not."""
    forge = _forge_for(ProjectRegistry().get(inp.project))

    def _do() -> bool:
        try:
            forge.close_pr(pr=inp.pr_url)
            return True
        except Exception as exc:  # noqa: BLE001 — the job is ending either way; say why
            activity.logger.warning("could not close %s (%s) — the job still frees the floor, so "
                                    "the PR may be left open on the forge", inp.pr_url, exc)
            return False

    return await asyncio.to_thread(_do)


@activity.defn
async def adjust_pr(inp: AdjustInput) -> RunResult:
    """One repair pass against a HUMAN's own words, on the same branch and the same PR (#68).

    The same machinery as `repair_ci` — `machine.repair_ci` checks out the existing branch, runs
    one agent pass, commits and pushes — with the person's sentence in the prose slot instead of a
    CI log. Same per-attempt idempotency scoping, and for the same reason: a genuine second pass
    must launch a fresh task rather than reconcile the first one's stale STOPPED result."""
    run_id = f"{activity.info().workflow_run_id}-a{inp.attempt}"
    return await _heartbeat_while(
        lambda: _run_adjust(inp, run_id), f"{inp.project}#{inp.issue} adjust"
    )


def _run_adjust(inp: AdjustInput, run_id: str | None = None) -> RunResult:
    """The human's instruction reaches the agent through the SAME slot a CI log does.

    FRAMED AS A REVIEW INSTRUCTION, not as a build failure. The slot is named `failure_log` and
    everything else that fills it is machine output; handing an agent a person's sentence with no
    framing invites it to hunt for a stack trace that is not there."""
    instruction = (inp.instruction or "").strip()
    briefing = (
        "A HUMAN REVIEWED THIS PULL REQUEST AND ASKED FOR A CHANGE. This is not a build failure "
        "and there is no log to read — it is a review comment. Make exactly the change asked for, "
        "on the branch that is already checked out, and nothing else.\n\n"
        f"What they asked for:\n{instruction}\n"
    )
    repair = CiRepairInput(project=inp.project, issue=inp.issue, pr_url=inp.pr_url,
                           sandbox=inp.sandbox, attempt=inp.attempt)
    return _run_ci_repair(repair, run_id, ci_log=briefing)


@activity.defn
async def review_pr(inp: ReviewPassInput) -> RunResult:
    """Re-run the independent reviewer on the open PR as it stands, because a person asked (#181).

    Same machinery, same box, one difference that matters everywhere: it writes nothing. So it
    needs no `instruction` slot, cannot conflict with a repair on the same PR (its own variant and
    idempotency suffix), and the verdict it brings back REPLACES the one the gate was showing."""
    run_id = f"{activity.info().workflow_run_id}-v{inp.attempt}"
    return await _heartbeat_while(
        lambda: _run_review_pass(inp, run_id), f"{inp.project}#{inp.issue} re-review"
    )


def _run_review_pass(inp: ReviewPassInput, run_id: str | None = None) -> RunResult:
    project = ProjectRegistry().get(inp.project)
    repo, _ = _ref_repo(project, inp.issue)  # C-18: it reads where the card's PR lives
    if not installed_box_traits(inp.sandbox).remote:  # a local box reads it inline
        view, repo_key = _runner_view(project, inp.issue)
        # `review=True`, ALWAYS. The repair path builds its runner with `review=False` because
        # its job is to write; here the reviewer IS the job, and a runner assembled without one
        # would answer "this deployment has no reviewer" about a deployment that has one.
        return build_runner(
            view, inp.issue, sandbox=inp.sandbox,
            image=_resolved_image(project, sandbox=inp.sandbox), review=True,
            repo_key=repo_key,
        ).review_pr(inp.issue, pr_url=inp.pr_url)

    from openfactory.observability.registry import journal_for
    from openfactory.paths import events_file
    from openfactory.runtime.boxed_job import BoxConfig

    box = BoxConfig(
        project=inp.project, issue=inp.issue, repo=repo,
        board_owner=project.tracker.options.get("board_owner"),
        board_number=project.tracker.options.get("board_number"),
        tracker_kind=project.tracker.kind,
        forge_kind=(project.forge.kind if project.forge else None) or project.tracker.kind,
        tracker_options=dict(project.tracker.options or {}),   # #162, as in `_box_for`
        forge_options=dict((project.forge.options if project.forge else None) or {}),
    )
    journal = journal_for(events_file(project, inp.issue), dedup=True)
    return remote_box(inp.sandbox).launch(
        box, variant="-review",
        extra_env={"OPENFACTORY_PR": inp.pr_url, "OPENFACTORY_REVIEW_PASS": "1"},
        journal=journal, timeout=1800, run_id=run_id,
    )


@activity.defn
async def check_ci_status(inp: MergeCheckInput) -> str:
    """Read-only: the PR's aggregate CI state — "success" | "failure" | "pending" | "none".
    The durable workflow polls this to react to a red CI (ADR-0004). Worker (gh + creds)."""

    forge = _forge_for(ProjectRegistry().get(inp.project))
    return await asyncio.to_thread(lambda: forge.pr_ci_status(pr=inp.pr_url))


@activity.defn
async def repair_ci(inp: CiRepairInput) -> RunResult:
    """One CI-repair pass on the open PR (ADR-0004): an ephemeral task checks out the branch,
    fixes it from the failing CI logs, and pushes. Idempotent by job tag like run_job — but
    scoped PER ATTEMPT: a genuine second attempt within the same workflow run must launch a
    fresh task, not reconcile the first attempt's stale STOPPED result (which ECS keeps ~1h,
    far longer than the 2-min CI poll). Suffixing the run_id with the attempt makes Temporal
    RETRIES of one attempt still converge (same attempt → same suffix) while a NEW attempt
    reads as a distinct run and runs fresh."""
    run_id = f"{activity.info().workflow_run_id}-r{inp.attempt}"
    return await _heartbeat_while(
        lambda: _run_ci_repair(inp, run_id), f"{inp.project}#{inp.issue} ci-repair"
    )


def _run_ci_repair(inp: CiRepairInput, run_id: str | None = None,
                   ci_log: str | None = None) -> RunResult:
    project = ProjectRegistry().get(inp.project)
    repo, _ = _ref_repo(project, inp.issue)  # C-18: the repair runs where the card's PR lives
    if not installed_box_traits(inp.sandbox).remote:  # a local box runs the repair inline
        from openfactory.adapters.forge.registry import build_forge
        from openfactory.credentials import forge_token_for

        # `ci_log` is passed in ONLY by the human-adjust path (#68), which has a person's
        # sentence rather than a build log. None means the ordinary CI repair, which fetches
        # the real logs — the fetch must not happen when a caller already has the prose,
        # both because it is a wasted forge read and because a green PR has no failed logs.
        view, repo_key = _runner_view(project, inp.issue)  # C-18: the card's own repository
        if ci_log is None:
            ci_log = build_forge(view, token=forge_token_for(view)).failed_ci_logs(pr=inp.pr_url)
        # RESOLVED, not hard-coded. This built the runner with the framework's image while holding
        # the project — so a client who configured their own box got it everywhere EXCEPT the CI
        # repair, which is the shape of bug that surfaces on the second failure of the day and
        # looks like the repair agent being incompetent rather than the toolchain being absent.
        return build_runner(
            view, inp.issue, sandbox=inp.sandbox,
            image=_resolved_image(project, sandbox=inp.sandbox), review=False,
            repo_key=repo_key,
        ).repair_ci(inp.issue, ci_log, pr_url=inp.pr_url)

    from openfactory.observability.registry import journal_for
    from openfactory.paths import events_file
    from openfactory.runtime.boxed_job import BoxConfig

    box = BoxConfig(
        project=inp.project, issue=inp.issue, repo=repo,
        board_owner=project.tracker.options.get("board_owner"),
        board_number=project.tracker.options.get("board_number"),
        tracker_kind=project.tracker.kind,
        forge_kind=(project.forge.kind if project.forge else None) or project.tracker.kind,
        tracker_options=dict(project.tracker.options or {}),   # #162, as in `_box_for`
        forge_options=dict((project.forge.options if project.forge else None) or {}),
    )
    journal = journal_for(events_file(project, inp.issue), dedup=True)
    # A DIFFERENT VARIANT AND A DIFFERENT FLAG for the human path, so the box knows it is acting
    # on a review comment rather than a red build, and so the launcher's idempotency tag cannot
    # collide with a CI repair on the same PR.
    human = ci_log is not None
    extra = {"OPENFACTORY_PR": inp.pr_url}
    extra["OPENFACTORY_ADJUST" if human else "OPENFACTORY_CI_REPAIR"] = "1"
    if human:
        extra["OPENFACTORY_ADJUST_TEXT"] = ci_log
    return remote_box(inp.sandbox).launch(
        box, variant="-adjust" if human else "-ci-repair",
        extra_env=extra,
        journal=journal, timeout=1800, run_id=run_id,
    )


@activity.defn
async def fetch_ticket_title(inp: TicketRef) -> str:
    """Read-only: the ticket's title, so the workflow can stamp it into its memo and the panel
    shows "#123 Add health check" instead of a bare number. Best-effort — the caller ignores a
    failure (a title is cosmetic, never worth failing or delaying a job for). Worker (creds)."""

    tracker = _tracker_for(ProjectRegistry().get(inp.project))
    return await asyncio.to_thread(lambda: tracker.get_ticket(inp.issue).title)


@activity.defn
async def mark_needs_action(inp: HoldSyncInput) -> str:
    """Reconcile the board to a parked (Needs Action) state from the WORKFLOW, and return the
    ticket's CREATOR login so the caller can route the escalation to them (there is no assignee
    in a lights-out flow). The in-job orchestrator normally sets the tracker status as it parks —
    but a crash or activity timeout kills the job BEFORE it can, so the ticket silently stays
    'In progress' while it's really waiting for a human (the hole #394 hit). Best-effort and
    idempotent. Returns "" if the author can't be read. Worker (creds)."""
    tracker = _tracker_for(ProjectRegistry().get(inp.project))
    try:
        state = JobState(inp.state)
    except ValueError:
        # A state nobody defined means a caller is out of step with the contract — the ticket is
        # parked safely, but something upstream is wrong.
        activity.logger.warning("unknown job state %r — treating #%s as on hold",
                                inp.state, inp.issue)
        state = JobState.ON_HOLD

    def _apply() -> str:
        author = ""
        try:
            author = tracker.get_ticket(inp.issue).author or ""
        except Exception:  # noqa: BLE001 — the creator is a nice-to-have, never worth failing
            # The escalation goes out addressed to nobody in particular.
            activity.logger.warning("could not find who created #%s", inp.issue)
            author = ""
        tracker.set_state(inp.issue, state, reason=inp.note or None)
        return author

    try:
        return await asyncio.to_thread(_apply)
    except Exception:  # noqa: BLE001 — reconciliation is best-effort; never fail the park
        activity.logger.warning(
            "mark_needs_action: could not set %s#%s → %s", inp.project, inp.issue, state.value)
        return ""


@activity.defn
async def record_outcome(inp: HoldSyncInput) -> str:
    """Write a job's TERMINAL state into its journal — the record that outlives the engine.

    THE LIE THIS ENDS (pilot, 2026-08-17). The journal is written by the in-box orchestrator, and
    the outcome is decided by the WORKFLOW — after that box is gone. So `#89`'s journal read, in
    full: … validating → reviewing → `review: rejected`, and then nothing. Its `open_pr` had
    raised (the branch carried zero commits, which GitHub refuses), the workflow caught it and
    parked the job, the BOARD said *Needs Action* and the engine agreed — and the durable record
    stopped one event short of the only fact anybody needed.

    That is not a cosmetic gap. Temporal's default namespace keeps 24h of history; a day later the
    engine is empty and this file is the ONLY answer to "what happened to #89". Both readers that
    matter get it wrong: the panel's Recent runs called a parked job `reviewing`, and the operator
    was told *nothing shipped yet* about a floor that had shipped two tickets.

    ONE CALL SITE, AT THE ONE EXIT (`JobWorkflow.run`), on purpose. The terminal state is decided
    in a dozen branches — a crash, a rate-limit ladder giving up, an operator's skip, an answered
    merge gate, a chain that ends at its last stage — and a rule that has to be remembered in each
    of them is a rule most of them will eventually forget. That is the defect this platform has
    shipped seventeen times; the fix is a seam, not a reminder.

    APPENDS, NEVER REWRITES. The journal is append-only like every other record here: the run's
    own `reviewing` stays true (it WAS reviewing), and this adds what it became.

    NEVER RAISES. The job has already ended; nothing about recording that may fail it.
    """
    def _write() -> str:
        from openfactory.observability.events import JobEvent, now_iso
        from openfactory.observability.registry import journal_for
        from openfactory.paths import events_file

        project = ProjectRegistry().get(inp.project)
        sink = journal_for(events_file(project, inp.issue))
        note = (inp.note or "").strip()
        sink.emit(JobEvent(
            ts=now_iso(), job_id=f"#{inp.issue}", ticket_id=f"#{inp.issue}",
            kind="state", message=inp.state, data={"reason": note or None, "by": "the workflow"},
        ))
        return inp.state

    try:
        return await asyncio.to_thread(_write)
    except Exception as exc:  # noqa: BLE001 — the job ended; the record failing must not undo it
        activity.logger.warning(
            "OPENFACTORY_OUTCOME_NOT_JOURNALLED %s#%s ended as %s and its journal does not say so "
            "(%s) — once the engine's retention window passes, nothing will",
            inp.project, inp.issue, inp.state, str(exc)[:160])
        return "unrecorded"


@activity.defn
async def settle_ticket(inp: HoldSyncInput) -> str:
    """Record a job's TERMINAL outcome on the tracker: the board column, and one comment saying
    why it ended there.

    SEPARATE FROM `mark_needs_action`, WHICH IS THE PARKED TWIN. That one also reads the ticket's
    author, because a park has to be escalated to somebody; an ended job has nobody to route to,
    and the read is a request against the same credential the poller and every running job share.
    Two jobs, two activities — the alternative was calling something named `mark_needs_action` to
    mark a ticket done, which is the kind of sentence a maintainer later believes.

    WHY THE WORKFLOW HAS TO DO THIS AT ALL (pilot, 2026-08-16). The in-job orchestrator writes the
    tracker state as it goes, but the human-gated merge happens OUTSIDE it: the operator answers
    the gate, the workflow lands the PR, and the machine that owns the writing has long since
    returned. `JobState.MERGED` also maps to *In review* by design (merged is still overseen while
    it deploys), so for a project whose manifest declares no `environments:` — which is every
    project this platform's own onboarding creates — the promotion tail never runs, nothing ever
    writes `DONE`, and the card sits in *In review* for ever. The board's terminal column was
    unreachable.

    BEST-EFFORT, LIKE ITS TWIN. The ticket has already merged. Nothing about recording that may
    fail the job or hold the floor."""
    tracker = _tracker_for(ProjectRegistry().get(inp.project))
    try:
        state = JobState(inp.state)
    except ValueError:
        activity.logger.warning("unknown job state %r — not settling #%s", inp.state, inp.issue)
        return "unknown-state"
    try:
        await asyncio.to_thread(
            lambda: tracker.set_state(inp.issue, state, reason=inp.note or None))
    except Exception:  # noqa: BLE001 — the merge stands whatever the tracker says
        activity.logger.warning(
            "settle_ticket: could not set %s#%s → %s", inp.project, inp.issue, state.value)
        return "failed"
    return state.value


@activity.defn
async def check_deploy_status(inp: DeployStatusInput) -> dict:
    """Read-only: the deploy workflow's outcome on the PR's MERGE commit —
    {"status": success|failure|pending|none, "run_url": ..., "sha": ...}. The abandoned
    deploy-watch polls this and only NOTIFIES; it never gates (ADR-0005). Worker (gh + creds)."""

    forge = _forge_for(ProjectRegistry().get(inp.project))

    def _read() -> dict:
        sha = forge.merge_commit_sha(pr=inp.pr_url)
        if not sha:  # not merged yet (shouldn't happen post-merge) → nothing to watch
            return {"status": "none", "run_url": None, "sha": None}
        status, url = forge.deploy_run_status(sha=sha, workflow=inp.workflow)
        return {"status": status, "run_url": url, "sha": sha}

    return await asyncio.to_thread(_read)


@activity.defn
async def notify_deploy(inp: DeployNotifyInput) -> None:
    """Emit the deploy-watch's outcome via the project's notifier (ADR-0005). A best-effort
    side channel — the merge already happened and the floor is free; this only informs."""
    from openfactory.factory import notifier_for_project
    from openfactory.techlead import voice as tl_voice

    project = ProjectRegistry().get(inp.project)
    lang = str(getattr(project, "language", "") or "")
    icon = {"success": "✅", "failure": "❌", "timeout": "⏱️"}.get(inp.status, "ℹ️")
    level = "info" if inp.status == "success" else "error"
    where = f" — {inp.run_url}" if inp.run_url else ""
    # A GREEN DEPLOY IS AN INVITATION, NOT A RECEIPT (#122). The outcome used to be reported as a
    # CI run URL, which answers "was the pipeline green" and says nothing about whether the change
    # is right — so the person who has to look at it was never told where to look. With an address
    # declared, the sentence carries it and asks.
    #
    # AND WITHOUT ONE IT ASKS NOTHING, deliberately: the previous shape of this idea told a client
    # the change was "in the test environment, go and have a look" with no address at all, which is
    # worse than silence because it costs somebody a reply to find out where.
    invite = ""
    if inp.status == "success" and inp.url:
        invite = tl_voice.say(tl_voice.NARRATION, "deploy.invitation", lang, url=inp.url)
        level = "action_required"
    # THE STATUS WORD IS TRANSLATED TOO (#160), and it is the one that carries the news: a
    # Portuguese-speaking client reading "deploy failure" is being told the outcome in a language
    # they did not ask for, at the moment they most need to understand it. An unknown status falls
    # through as itself rather than as a key — the adapter's word is better than a placeholder.
    status = tl_voice.say(tl_voice.NARRATION, f"deploy.status.{inp.status}", lang)
    msg = tl_voice.say(tl_voice.NARRATION, "deploy.outcome", lang, icon=icon,
                       project=inp.project, issue=inp.issue, env=inp.env,
                       status=inp.status if status.startswith("deploy.status.") else status,
                       where=where, invite=invite)
    await asyncio.to_thread(lambda: notifier_for_project(project).notify(message=msg, level=level))
    # THE SECOND SURFACE, from the SAME event (#122, the operator's decision on 2026-08-16:
    # *"os 2 podem comunicar isso… se a empresa não estiver usando [o PO], continua sendo
    # relevante independente do canal"*). The operator half above always runs — it does not depend
    # on the product module being switched on, which is the failure this card was opened for. The
    # client half is additive and silent when there is no client to tell.
    if inp.status == "success" and inp.url:
        await asyncio.to_thread(_invite_the_client_to_look, project, inp)


@activity.defn
async def promote_staging(inp: PromoteInput) -> RunResult:
    """Post-merge: observe staging; if green, park at AWAITING_PROD_APPROVAL. Runs the box
    program on the job's REMOTE box (it has the forge credential and the cloned manifest — the
    worker has neither), H12."""
    run_id = activity.info().workflow_run_id
    return await _heartbeat_while(
        lambda: _run_promotion(inp.project, inp.issue, "staging", {}, run_id,
                               sandbox=inp.sandbox),
        f"{inp.project}#{inp.issue} staging",
    )


@activity.defn
async def release_prod(inp: ReleaseInput) -> RunResult:
    """Tag → prod on an authenticated human approval, then observe prod (D-12). On the job's
    remote box, like `promote_staging`."""
    run_id = activity.info().workflow_run_id
    return await _heartbeat_while(
        lambda: _run_promotion(
            inp.project, inp.issue, "release",
            {
                "OPENFACTORY_RELEASE_VERSION": inp.version,
                "OPENFACTORY_RELEASE_APPROVER": inp.approver,
                "OPENFACTORY_RELEASE_COMMENT": inp.comment,
            },
            run_id,
            sandbox=inp.sandbox,
        ),
        f"{inp.project}#{inp.issue} release",
    )


# --- the autonomous trigger (A1): board scan + workflow start, driven by PollWorkflow ---
def rate_pause_marker(kind: str, reset_epoch: int) -> str:
    """The once-per-window marker's file name, keyed by (tracker kind, reset epoch).

    `rate-pause-<kind>-<epoch>.said`; the kind is reduced to the characters a file name on any
    volume takes, so a stranger's add-on kind cannot name a path. An input with no kind (a
    history written before budgets were read per vendor) keeps the name that shape had,
    `rate-pause-<epoch>.said`, so a marker it wrote before the deploy still counts."""
    slug = "".join(c if c.isalnum() or c in "_-" else "_" for c in (kind or ""))
    return f"rate-pause-{slug}-{reset_epoch}.said" if slug else f"rate-pause-{reset_epoch}.said"


@activity.defn
async def announce_rate_pause(inp: RatePauseInput) -> bool:
    """Tell a human the factory is standing still because the API budget ran out.

    THE SELF-IMPOSED WAIT IS STILL A WAIT. The poller skips a tick to protect the quota — right,
    and invisible: it said so to a workflow log, so the floor went quiet for up to an hour and
    the operator learned about it from an unrelated command failing (2026-08-14: *"what limit?
    não recebi nenhum aviso"*). ADR-0038 D2: a wait is a question, never a state.

    ONCE PER RESET WINDOW PER VENDOR, not once per tick — the poller runs every three minutes
    and an alarm on every one of them is an alarm somebody learns to filter. The marker carries
    the reset epoch, so the NEXT exhaustion (a different window) speaks again — and the tracker
    KIND, because budgets are read per vendor now and two vendors spent in the same window (or
    both reporting no reset, epoch 0) shared one marker: the second stayed silent (found by the
    branch's own review, 2026-08-26). Best-effort throughout: the announcement never decides
    whether the poll may end."""
    from openfactory.box_prove import PROOF_DIR
    from openfactory.factory import notifier_for_project

    marker = PROOF_DIR / rate_pause_marker(inp.kind, inp.reset_epoch)
    try:
        if marker.exists():
            return False
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(inp.remaining))
    except OSError:
        pass  # a read-only proofs dir must not silence the announcement itself

    from openfactory.techlead import voice as tl_voice

    said = False
    # COMPOSED PER PROJECT (#160). One text for every project was one language for every project,
    # and this is the broadest unprompted message the platform sends — it reaches every client of
    # the deployment at once. Rendering inside the loop also lets each sentence name the project
    # whose `doctor` would answer it, instead of the `<project>` placeholder a reader has to fill
    # in themselves.
    #
    # THE VENDOR'S NAME IS A PARAMETER, not a word in the sentence — and not a literal in this
    # activity either, which is what it was ("GitHub", right for exactly one tracker). The
    # adapter names itself on the `Budget` it reports and the poller carries that name here.
    #
    # ONLY THE PROJECTS ON THE EXHAUSTED VENDOR are told (`inp.projects`): a Jira project on a
    # mixed deployment is still being scanned, and a message saying its pickups are paused would
    # be false. An empty list is the pre-per-vendor shape and means everybody, so a history
    # written before this field existed replays with the meaning it had.
    for project in ProjectRegistry().list():
        if inp.projects and str(getattr(project, "name", "") or "") not in inp.projects:
            continue
        try:
            lang = str(getattr(project, "language", "") or "")
            name = str(getattr(project, "name", "") or "")
            when = (time.strftime("%H:%M", time.localtime(inp.reset_epoch)) if inp.reset_epoch
                    else tl_voice.say(tl_voice.NARRATION, "rate-pause.soon", lang))
            text = tl_voice.say(tl_voice.NARRATION, "rate-pause", lang,
                                forge=inp.vendor or "API",
                                resource=inp.resource, remaining=inp.remaining, when=when,
                                project=name or "<project>")
            await asyncio.to_thread(
                lambda p=project, t=text: notifier_for_project(p).notify(
                    message=t, level="warning"))
            said = True
        except Exception as exc:  # noqa: BLE001 — a channel is an ADD-ON; never the gate
            activity.logger.warning("could not announce the rate pause for %s (%s)",
                                    getattr(project, "name", "?"), exc)
    return said


@activity.defn
async def tracker_budgets() -> list[dict]:
    """The API budget of every tracker credential the enabled projects use — one row per
    (kind, credential), read through the PORT, so the poller can skip the projects on an
    exhausted vendor and keep scanning the rest.

    IT WAS `github_budget()`, WHICH ASKED ONE VENDOR BY NAME WITH NO PROJECT IN SCOPE. On a Jira
    deployment every tick spawned `gh api rate_limit` and logged a GitHub remedy; on a mixed one a
    spent GitHub quota parked the Jira projects too, because the whole tick was skipped. Each row
    carries `state` (`ok | low | unread | not_reported`), the projects that share the credential,
    and — when the vendor reports one — the numbers and the vendor's own name. `unread` keeps the
    poller failing OPEN: it scans anyway, as it always has, and the floor says the safety net is
    missing rather than pretending the budget is fine."""
    from openfactory.floor.reading import budgets

    return await asyncio.to_thread(budgets)


@activity.defn
async def scan_projects() -> list[dict]:
    """Enabled projects that have a board — the poller's work list, from the registry.

    HAVING A BOARD IS ASKED OF THE FACTORY, NOT OF THE CONFIG. This filtered on
    `board_owner`/`board_number`, which are GitHub Projects coordinates — and a Jira project has
    neither, because there its workflow STATUS is the column and the project itself is the board.
    So a Jira deployment was never scanned at all: box proven, credential wired, `DAR-2` sitting
    in TO-DO, and the poller's work list simply did not contain it (F-02, found live 2026-08-05).

    `build_board` already answers this question for every provider — it is the one place that
    knows what a board needs — so the filter asks IT rather than pattern-matching one vendor's
    configuration. The coordinates still travel, because the GitHub path reads them downstream."""
    from openfactory.adapters.board import build_board

    out: list[dict] = []
    for p in ProjectRegistry().list():
        if not p.enabled:
            continue
        bo = p.tracker.options.get("board_owner")
        bn = p.tracker.options.get("board_number")
        try:
            has_board = build_board(p) is not None
        except Exception as exc:  # noqa: BLE001 — an unknown provider is reported downstream
            # …by `scan_todo`, which raises naming the known kinds, where there is a person to
            # tell. Dropping the project from the WORK LIST here would take that report away and
            # leave a configured project simply never polled — so it stays in on its coordinates,
            # and the reason it could not be resolved is said once per tick rather than never.
            activity.logger.warning(
                "could not resolve a board for %s (%s) — keeping it in the poll list so the "
                "scan reports the real problem instead of silently never looking",
                p.name, str(exc)[:160])
            has_board = bool(bo and bn)
        if has_board:
            out.append({
                # `or ""` because these are GITHUB coordinates and a Jira project has none.
                # `ScanInput` types them `str`, so passing None through failed validation INSIDE
                # the workflow — which is not one broken project, it is the whole poll tick
                # dying on every tick, for every project. Empty is the honest value: this
                # provider's board is not addressed by coordinates.
                "project": p.name, "board_owner": bo or "", "board_number": bn or "",
                # explicit pickup_status wins; else THE BOARD ANSWERS FOR ITSELF (C-14).
                #
                # That last step used to be the literal "TO-DO", with a comment claiming a
                # Portuguese board needed zero extra config. True for one provider: GitHub's
                # canonical board really is spelled that way. Azure Boards spells it "To Do", so a
                # correctly-configured ADO deployment asked for a column that does not exist and
                # read an empty queue every tick — the silent stall, arriving through the front
                # door of the platform's own default. Each adapter already held the answer; there
                # was no way to ask for it until `pickup_column()` existed.
                "pickup_status": (p.tracker.options.get("pickup_status")
                                  or _pickup_column(p)),
            })
    return out


def _pickup_column(project) -> str:
    """What this project's board calls its pickup column — never a guess this module makes.

    Best-effort by design: this runs inside the poll tick's work-list build, which must not die
    because one project's board could not be constructed. The platform default is the fallback and
    it is the honest one, because a caller downstream reports which column it looked for."""
    from openfactory.adapters.board import build_board

    try:
        board = build_board(project)
        got = board.pickup_column() if board is not None else ""
    except Exception as exc:  # noqa: BLE001 — one bad project must not stop the whole tick
        activity.logger.warning(
            "could not ask %s's board what it calls its pickup column (%s) — falling back to "
            "'TO-DO', which is right for GitHub and wrong for at least Azure Boards",
            getattr(project, "name", "?"), str(exc)[:160])
        got = ""
    return got or (project.tracker.options.get("columns") or {}).get("todo") or "TO-DO"


@activity.defn
async def available_slots() -> int:
    """Free slots on the floor = max_concurrent_jobs() minus the JobWorkflows currently RUNNING
    (globally — the floor is a single shared agent token in v1). The poller starts at most this
    many new tickets per tick, so a TO-DO batch is picked up ONE at a time in order, never all
    at once. Excludes the deploy-watch children + the poller itself (WorkflowType filter): a
    merged job that spawned a deploy-watch has ALREADY freed the floor (ADR-0005)."""
    from openfactory.runtime.temporal import max_concurrent_jobs
    from openfactory.runtime.temporal.connection import connect

    client = await connect()
    running = 0
    async for _ in client.list_workflows(
        'WorkflowType = "JobWorkflow" AND ExecutionStatus = "Running"'
    ):
        running += 1
    return max(0, max_concurrent_jobs() - running)


@activity.defn
async def scan_todo(inp: ScanInput) -> list[str]:
    """Issue numbers currently in the board's pickup column (read-only)."""
    from openfactory.box_prove import announce_gate, clear_gate_announcement, gate_reason
    from openfactory.credentials import tracker_token_for
    from openfactory.factory import _bot_token_provider

    project = ProjectRegistry().get(inp.project)

    # THE BOX IS PROVEN BEFORE ANYTHING IS PICKED UP (ADR-0037 D5). Configuration is a declaration
    # and a proof is a fact — about a world that moves, so it expires when the image, the toolbox
    # or this project's own commands change underneath it.
    #
    # HERE rather than in the workflow body, deliberately: this activity already loads the project
    # and already returns `[]` for "no board configured". Putting the gate in the body would be a
    # new command in a workflow with jobs in flight, which breaks replay (TMPRL1100) and needs a
    # `workflow.patched()` gate. This needs neither.
    # The sandbox is resolved HERE, in the activity, rather than carried on `ScanInput`. Adding a
    # field with a `default_factory` that reads the environment would be evaluated inside the
    # workflow body — the determinism rule `adapters/sandbox/registry.py` states — and adding one
    # without a factory means the poller passes it, which is a workflow-body change for nothing.
    from openfactory.runtime.temporal.io import default_sandbox

    async def _gate(repo: str = "") -> str | None:
        """One repo's gate verdict, OFF the event loop and BOUNDED. `gate_reason` may resolve
        a checkout (a network fetch) and ask docker for a digest; unbounded it was a sync call
        that could hold this worker's whole event loop on one slow remote (adversarial review,
        2026-08-13). On timeout the repo is HELD with the reason said — never silently."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: gate_reason(project, sandbox=default_sandbox(),
                                        **({"repo": repo} if repo else {}))),
                timeout=60)
        except Exception as exc:  # noqa: BLE001 — undecided (incl. timeout) is its own verdict
            which = repo or "the project"
            return (f"the box gate could not decide for {which} within its budget "
                    f"({type(exc).__name__}) — holding this repo's cards; retrying next tick")

    # THE DEFAULT REPO'S GATE HOLDS THE DEFAULT REPO'S CARDS — no longer the whole project.
    # Returning [] here held every FOREIGN repo's freshly proven cards on the default repo's
    # expired proof, contradicting the shipped per-repo contract ("front never waits on back's
    # paperwork" — adversarial review, 2026-08-13). The verdict is taken once, used per card.
    default_held = await _gate()
    if default_held:
        announce_gate(inp.project, default_held, registry_name=inp.project)
        # BOTH CONTRACTS, precisely: the original gate never spent board quota on a project
        # that cannot run anything, and the per-repo contract says a proven foreign repo must
        # not wait on the default's paperwork. A foreign card is only ever admitted on a proof
        # that exists on disk — so with the default held and NO foreign proof recorded, nothing
        # could be admitted and the board is not read; one foreign proof appears and the
        # per-candidate loop below takes over.
        from openfactory import box_prove as _bp

        # ASKED OF `box_prove`, not spelled here: `doctor` asks the same question to decide
        # whether an unreadable API budget is a safety net anybody needs yet, and one condition
        # written twice is how two answers to one question start to drift.
        if not _bp.foreign_proofs_recorded(inp.project):
            return []
    else:
        clear_gate_announcement(inp.project)  # so the NEXT breakage speaks

    tok = tracker_token_for(project)
    if not tok:
        prov = _bot_token_provider()
        tok = prov() if prov else None
    # Through the FACTORY: `ScanInput` already carries the project, so the poller never needs to
    # know which vendor keeps the columns — the registry decides.
    from openfactory.adapters.board import build_board

    board = build_board(project, token=tok)
    if board is None:
        activity.logger.warning("no board configured for %s/%s — the pickup queue is empty by "
                                "configuration, not because nothing is waiting",
                                inp.board_owner, inp.board_number)
        return []
    candidates = await asyncio.to_thread(
        lambda: [str(n) for n in board.items_in_status(inp.pickup_status)]
    )
    if not candidates:
        return []
    # A CLOSED ISSUE IN THE PICKUP COLUMN IS A STALE CARD, NOT WORK (found live, 2026-08-04):
    # fx-py-simple#1 merged, its card stayed in TO-DO (the board move had failed on that
    # deployment), and the next tick RE-RAN the delivered ticket — a full agent pass spent to
    # discover there was nothing to do, ending in "gh pr create: No commits between main and
    # sdlc/1", parked ON_HOLD, holding the single-slot floor. Checked here, per candidate,
    # through the tracker port: candidates are at most a handful and only exist on non-quiet
    # ticks, so the quota cost is a few reads exactly when work is about to be spent.
    #
    # THE STALE CARD IS ALSO HEALED, best-effort: filtering alone would re-log the same skip
    # every three minutes for ever, and the card's own issue already says where it belongs.
    tracker = _tracker_for(project)
    open_refs = await _open_refs(tracker, candidates)
    for ref in [r for r in candidates if r not in open_refs]:
        state = "closed"
        activity.logger.warning(
            "OPENFACTORY_STALE_PICKUP_CARD #%s is %s but sits in %r — not re-running delivered "
            "work; "
            "moving the card to Done", ref, state, inp.pickup_status)
        try:
            # set_STATUS, not a literal column name: on a board whose columns the client renamed
            # (C-14) the healing must speak the same map every other move speaks
            from openfactory.contracts import JobState as _JS

            heal_repo, heal_bare = _ref_repo(project, ref)  # C-18: the card's own repo
            # the provider's own URL shape (see the sibling call above); the literal stays as
            # the fallback for a tracker that cannot say
            # vendor-url-ok: as the sibling above — the port answers first, and only the GitHub
            # Projects board reads this value.
            healed_url = _ticket_url_or(
                tracker, ref, f"https://github.com/{heal_repo}/issues/{heal_bare}")
            await asyncio.to_thread(
                lambda r=ref, u=healed_url: board.set_status(
                    issue=r, issue_url=u, state=_JS.DONE))
        except Exception:  # noqa: BLE001 — healing is a bonus; the filter already protected the money
            activity.logger.warning("could not move the stale card #%s — it will be skipped "
                                    "again next tick", ref)

    # C-18'S HALF OF THE GATE (2026-08-13). The project-level gate at the top answered for the
    # DEFAULT repository — it runs before the board is read, so no card and therefore no repo is
    # known there. A qualified card belongs to ANOTHER repository, with its own manifest, its
    # own toolchain and its own proof; admitting it on the default repo's proof was the gate
    # standing open while looking closed (measured: a `web` card rode the `api` proof). Checked
    # once per distinct foreign repo — candidates are a handful and only exist on non-quiet
    # ticks, the same cost argument the stale-card check above already makes.
    from openfactory.runtime.card_repo import _is_default_repo

    admitted: list[str] = []
    held_by_repo: dict[str, str | None] = {}
    for ref in open_refs:
        card_repo, _bare = _ref_repo(project, ref)
        # _is_default_repo, not string equality: an ADO card arrives QUALIFIED
        # (`Deskline/fx-ado`) while the registry row is bare (`fx-ado`) — equality read
        # the default repo as foreign and held its cards on a proof that can never exist
        if _is_default_repo(project, card_repo):
            if not default_held:
                admitted.append(ref)
            continue
        if card_repo not in held_by_repo:
            held_by_repo[card_repo] = await _gate(card_repo)
        key = _checkout_key(project, card_repo)
        if held_by_repo[card_repo]:
            # per-key marker so repos don't overwrite each other; the NOTIFIER is the
            # project's — a composite key is not a registry name
            announce_gate(key, held_by_repo[card_repo], registry_name=inp.project)
            continue
        clear_gate_announcement(key)
        admitted.append(ref)
    return admitted


async def _open_refs(tracker, candidates: list[str]) -> list[str]:
    """Which candidates the tracker still considers OPEN.

    Extracted so it can be exercised against the REAL `Ticket`. It could not be before: the check
    was inline, and every test reached it through a double that invented a `state` attribute the
    contract did not have — so the suite was green while the guard could not fire. A guard proven
    against a fake carrying a field the product lacks proves the fake.

    `state=None` (the provider was not asked) reads as OPEN, deliberately: a tracker that cannot
    answer must not silently stop every pickup. The same reasoning applies to an unreadable
    ticket — refusing on a read failure lets one flaky API call halt intake, which is the worse
    of the two failures."""
    out: list[str] = []
    for ref in candidates:
        try:
            ticket = await asyncio.to_thread(tracker.get_ticket, ref)
            state = str(getattr(ticket, "state", None) or "open").lower()
        except Exception as exc:  # noqa: BLE001 — an unreadable ticket must not hold the queue
            activity.logger.warning("could not read #%s while scanning TO-DO (%s) — picking it "
                                    "up anyway; the job itself will find out", ref, exc)
            out.append(ref)
            continue
        if state == "open":
            out.append(ref)
    return out


#: The wall a JobWorkflow hits when nothing else stops it. Past the 14-day merge wait, because a
#: job legitimately parked on a human is not a job that failed — this exists for the one that
#: cannot progress at all, which no other bound in the system can see.
JOB_EXECUTION_CEILING_DAYS = 21


@activity.defn
async def start_jobs(inp: StartJobsInput) -> list[str]:
    """Start a JobWorkflow per ticket (id openfactory-{project}-{issue}). Idempotent: a ticket
    whose workflow is already running is skipped (WorkflowAlreadyStarted) — the card may
    sit in TODO for a minute until the job moves it. Dragging a completed ticket back to
    TODO intentionally re-runs it (a fresh run id — R8 keeps it from adopting old results)."""
    from datetime import timedelta

    from openfactory.runtime.temporal import TASK_QUEUE
    from openfactory.runtime.temporal.connection import connect

    client = await connect()
    # STAMPED HERE, at launch, because the workflow body may not resolve it: reading the registry
    # or the environment inside a workflow replays differently on a worker started with a different
    # configuration (ADR-0037 D4). Resolved once for the whole batch — every issue in it belongs to
    # the same project, and a per-issue resolve would be N registry reads for one answer.
    # ONE REGISTRY READ, used twice: the image this deployment runs and the language this project
    # speaks first (#124). Both are per-project facts an activity may look up and a workflow may
    # not, which is why they ride on `JobParams` rather than being fetched later.
    project = ProjectRegistry().get(inp.project)
    image = _resolved_image(project, sandbox=inp.sandbox)
    # THE BOX'S TRAITS, STAMPED HERE FOR THE SAME REASON AS THE IMAGE. The workflow asks whether
    # its box is remote and idempotent, and may only ask the built-in table; an add-on's box is
    # known on this side (`installed_box_traits` reads the entry points, which is I/O) and travels
    # to the workflow as data — `JobParams.traits` says what happens when it is absent.
    traits = installed_box_traits(inp.sandbox)
    started: list[str] = []
    for issue in inp.issues:
        try:
            await client.start_workflow(
                "JobWorkflow",
                JobParams(project=inp.project, issue=issue, sandbox=inp.sandbox, image=image,
                          language=str(getattr(project, "language", "") or ""), box=traits),
                id=f"openfactory-{inp.project}-{issue}",
                task_queue=TASK_QUEUE,
                # THE ONLY WORKFLOW WITHOUT A CEILING, and the only one that holds a floor. The
                # poller, the product sweep and the tech-lead rounds all carry one for exactly
                # this reason; a job that cannot make progress — a workflow-task failure loop
                # after a deploy, an unregistered activity type — sat running for ever, counted
                # as work by the rounds, holding the single slot.
                #
                # GENEROUS ON PURPOSE. A real job legitimately waits for a human: the merge gate
                # is 14 days by default. This is not a deadline for the WORK, it is the wall a
                # wedged workflow eventually hits, so it is set past the longest legitimate wait
                # rather than near the longest agent pass.
                execution_timeout=timedelta(days=JOB_EXECUTION_CEILING_DAYS),
            )
            started.append(issue)
        except Exception as exc:  # already running for this ticket → correct no-op
            if "AlreadyStarted" not in type(exc).__name__:
                raise
    activity.logger.info("poll started %s for %s", started, inp.project)
    return started


# --- the project's tech-lead coordinator (v0: advisory) --------------------------------
def _do_coordinate(item: CoordinatorItem) -> dict:
    """Reason as the project's tech lead over a parked decision and return a humanized briefing
    + a recommended option. v0 is ADVISORY — it never acts; a human still decides. Also posts
    the briefing on the ticket (a durable channel). Best-effort: {} on any trouble (the decision
    still stands with its raw options)."""
    import tempfile
    from pathlib import Path

    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.adapters.sandbox.registry import judging_worktree
    from openfactory.contracts import parse_advice

    opts = "\n".join(
        f"- {o.get('key')}: {o.get('label')}"
        + (f" — {o.get('consequence')}" if o.get("consequence") else "")
        + (" (mechanically recommended)" if o.get("recommended") else "")
        for o in item.options
    ) or "- (no explicit options)"
    situation = (
        f"A **{item.kind or 'decision'}** on ticket #{item.issue} (project {item.project}) is "
        f"PARKED and needs a human.\n\n"
        f"Problem: {item.note or item.question}\n\n"
        f"Question to the human: {item.question}\n\n"
        + (f"Context: {item.context}\n\n" if item.context else "")
        + f"Options offered:\n{opts}\n\n"
        "Give your tech-lead briefing as the json block (summary, recommend <one option key>, "
        "rationale, watch_outs)."
    )
    tmp = Path(tempfile.mkdtemp(prefix="openfactory-coordinator-"))
    try:
        res = _judge_for(item.project).advise(
            sandbox=judging_worktree(_project_or_none(item.project), root=tmp),
            workspace=Workspace(path=tmp, branch="main", base_branch="main"),
            situation=situation,
        )
        advice = parse_advice(_sizer_result_text(res))
    except Exception as exc:  # noqa: BLE001 — the decision still parks; it just parks unexplained
        activity.logger.warning("could not read the coordinator's advice for %s (%s)",
                                item.issue, str(exc)[:120])
        advice = None
    finally:
        # `tmp` is the sandbox root for the advise call and is dead the moment it returns. Without
        # this the worker — which never restarts — kept one directory per PARKED DECISION forever.
        shutil.rmtree(tmp, ignore_errors=True)
    if advice is None:
        print(f"OPENFACTORY_COORDINATOR: no parseable advice for "
              f"{item.project}#{item.issue}", flush=True)
        return {}
    try:  # post the humanized take on the ticket (durable, channel-agnostic)
        tracker = _tracker_for(ProjectRegistry().get(item.project))
        rec = next((o for o in item.options
                    if str(o.get("key", "")).lower() == advice.recommend.lower()), None)
        reclabel = rec.get("label") if rec else advice.recommend
        body = (f"**Tech-lead take** — {advice.summary}\n\n"
                f"**Recommends: `{advice.recommend}` · {reclabel}** — {advice.rationale}"
                + (f"\n\n⚠️ Watch out: {advice.watch_outs}" if advice.watch_outs else ""))
        tracker.comment(f"#{item.issue.lstrip('#')}", body)
    except Exception:  # noqa: BLE001 — the comment is a bonus; the advice still signals back
        activity.logger.warning("could not post the coordinator's advice on %s", item.issue)
    return advice.model_dump()


@activity.defn
async def coordinator_advise(item: CoordinatorItem) -> dict:
    """ADR-00XX (the coordinator): the tech lead's humanized briefing on a parked decision.
    v0 advisory — returns {summary, recommend, rationale, watch_outs} (or {} if it can't opine)."""
    return await _heartbeat_while(lambda: _do_coordinate(item),
                                  f"coordinate {item.project}#{item.issue}")  # type: ignore[return-value]


def _do_diagnose(inp: HoldSyncInput) -> bool:
    """The tech lead on an IMPEDIMENT (ADR-0015): produce a HandOff and render it to BOTH surfaces
    — a rich ticket comment (durable) and the channel (the voice).

    PUBLISHING ONLY, SINCE C-23. Producing the diagnosis moved to `techlead/diagnosis.py`, because
    this function was the ONLY way to get one: the tech-lead could explain a failure the moment it
    happened and never again, and a human looking at a job that parked yesterday had nowhere to
    ask. That is `openfactory-tech-lead-layer-gap`, and it is why the `diagnose` action sat in the
    catalog
    as a row that refused.

    THE TWO CALLERS PUBLISH DIFFERENTLY, which is why the split is here and not one layer up. This
    path MUST post, because nobody is watching a job that just parked. An operator asking
    `diagnose` from the panel must not: they are looking at the answer, and a duplicate comment per
    question is how a ticket becomes unreadable.

    Best-effort: returns False on any trouble — the raw [state] note from mark_needs_action still
    stands, so the human is never left with nothing."""
    from openfactory.contracts import handoff_to_markdown, handoff_to_plain
    from openfactory.factory import notifier_for_project
    from openfactory.techlead import diagnosis

    project = ProjectRegistry().get(inp.project)
    tracker = _tracker_for(project)
    # C-18 (the ref may carry the card's own repo) is the TRACKER's problem now: `ticket_url`
    # locates a qualified or bare ref exactly as every other method does, so this no longer
    # unpacks a repo and a number just to concatenate a vendor's URL shape by hand.
    ref = str(inp.issue).strip()

    ho = diagnosis.diagnose(project, issue=inp.issue, state=inp.state, note=inp.note,
                            tracker=tracker)
    if ho is None:
        print(f"OPENFACTORY_TECHLEAD: no parseable handoff for "
              f"{inp.project}#{inp.issue}", flush=True)
        return False

    posted = False
    try:  # durable record on the ticket
        tracker.comment(ref, handoff_to_markdown(ho, raw_note=inp.note))
        posted = True
    except Exception as exc:  # noqa: BLE001 — the channel below may still carry it
        activity.logger.warning("the diagnosis never reached ticket %s (%s)", ref, str(exc)[:120])
    try:  # the voice — this project's channel (Null when unconfigured → no-op locally)
        # ASK THE TRACKER. This built a github.com URL by hand, so a Jira deployment's park
        # alert — the one clickable line on a message that exists to get a human to act — sent
        # them to an issue that does not exist there.
        try:
            link = tracker.ticket_url(ref)
        except Exception as exc:  # noqa: BLE001 — a missing link must not lose the diagnosis
            # Said out loud: the alert still goes, but WITHOUT the one line a human clicks, and a
            # silent degradation here reads as "the platform does not link tickets".
            activity.logger.warning("no ticket link for %s (%s)", ref, str(exc)[:120])
            link = ""
        notifier_for_project(project).notify(
            message=handoff_to_plain(ho, ref=link), level="action_required")
    except Exception:  # noqa: BLE001 — the ticket comment already carries the diagnosis
        activity.logger.warning("the diagnosis never reached the channel for %s", ref)
    return posted


@activity.defn
async def techlead_ask(inp: AskInput) -> dict:
    """The tech-lead answers a free-text question — on the worker, with the worker's credentials.

    Off the event loop for the same reason `_ask` documented before it moved here:
    `conversation.answer` clones a repository, shells out to `gh` and runs an agent process."""
    project = ProjectRegistry().get(inp.project)
    answer = await asyncio.to_thread(_conversation_answer, project, inp.question,
                                     tuple(inp.can or ()), inp.thread or "")
    return {"text": answer.text, "suggestion": list(answer.suggestion or []),
            "spend": dict(answer.spend or {})}


def _conversation_answer(project, question: str, can: tuple[str, ...] = (), thread: str = ""):
    from openfactory.techlead import conversation

    return conversation.answer(project, question, can=can, thread=thread)


@activity.defn
async def product_role_ask(inp: ProductAskInput) -> dict:
    """The product role drafts — on the worker, with the worker's credentials and its box.

    THE WHOLE ANSWER COMES BACK, not a summary of it. `product_propose` commits exactly the text a
    human read and refuses to re-derive one, because a second draft from the same words is a
    different text — so anything this drops is a field the sign-off surface can no longer honour.

    Off the event loop for the same reason `techlead_ask` is: `draft` builds a git worktree of the
    documentation repo AND the code, then runs an agent process against it.

    IT RETURNS THE ROLE'S REFUSAL RATHER THAN RAISING. `draft` answers
    `ProductAnswer(ok=False, error=…)` when it cannot see the corpus — a private docs repository
    with no credential is the ordinary case, not an exception — and the action layer turns that
    into a refusal carrying the role's own sentence. Raising here would spend a Temporal retry
    deciding that a permission problem is still a permission problem."""
    project = ProjectRegistry().get(inp.project)
    answer = await asyncio.to_thread(_product_draft, project, inp.question, inp.asked_by,
                                     inp.thread)
    return {"ok": bool(getattr(answer, "ok", False)),
            "error": str(getattr(answer, "error", "") or ""),
            "answer": answer.model_dump(mode="json")}


def _product_draft(project, request: str, asked_by: str, thread: str = ""):
    """The conversational turn, then a draft only if the role read it as a REQUEST.

    WITH ITS MEMORY, SINCE #33. This turn used to hand the role the question alone, so on the web
    every message was turn one — and the transcript the `say` path keeps was written under the
    project's name for everybody at once. Now the person's turn is recorded ON ARRIVAL under
    `thread` (the panel keys it per person, or per unidentified browser), the earlier turns of
    THAT conversation are handed to the role, and the reply is recorded after it — the same three
    moves `_product_conversation` makes, on the door the panel actually opens.

    THE ROW CALLED THE WRONG VERB, and the shape of the bug is that nothing failed. `draft`
    returns `ProductAnswer(ok=True, draft=…, raw=…)` and sets no `text`, so `product_ask` answered
    every question with an EMPTY SENTENCE — and its `is_request`, `is_defect`, `gesture` and
    `decisions` were structurally always false, because only `answer` fills them (role.py: `answer`
    returns `text=…, is_request=…, decisions=…, gesture=…`; `draft` returns none of it). The row's
    own docstring described `answer`'s behaviour — *"only drafts one when it reads the message as a
    REQUEST"* — while the call underneath drafted unconditionally and said nothing. A promise the
    answer SHAPE could not keep, which no prompt and no model would have fixed.

    TWO PASSES, AND ONLY WHEN IT IS A REQUEST. This is what the Slack path has always done —
    converse, and offer a draft when the person asked for something to be built — so it is the
    same spend reaching a second transport, not new spend. A question costs one pass and gets a
    real sentence; a request costs two and comes back committable.

    Imported inside the call, like every other agent path here: `openfactory.product.module` pulls
    in the
    corpus loader and the authoring stack, and a worker that cannot import them must still start
    and say so per-activity rather than fail at registration."""
    from openfactory.memory import transcript
    from openfactory.product.module import ProductModule

    module = ProductModule(project, via="api")
    name = getattr(project, "name", "") or ""
    key = (thread or "").strip() or name
    arrival = transcript.record(name, thread=key, role="person", text=request, actor=asked_by)
    before = transcript.render(
        [t for t in transcript.recent(name, thread=key)
         if not (arrival and getattr(t, "ts", None) == arrival)],
        agent_name=getattr(getattr(project, "product", None), "agent_name", "") or "")
    said = module.answer(request, conversation=before)
    if getattr(said, "ok", False) and str(getattr(said, "text", "") or "").strip():
        transcript.record(name, thread=key, role="agent", text=str(said.text))
    if not getattr(said, "ok", False) or not getattr(said, "is_request", False):
        return said
    # THE DRAFT IS ATTACHED, NEVER SUBSTITUTED: `product_propose` commits exactly the object it is
    # handed, and the client has to be able to read the sentence they are signing off beside it.
    drafted = module.draft(request, asked_by=asked_by)
    if not getattr(drafted, "ok", False) or getattr(drafted, "draft", None) is None:
        # The conversation still happened and still has something to say. Losing the answer here
        # because the drafting half failed would replace a real reply with silence.
        return said
    return said.model_copy(update={"draft": drafted.draft})


@activity.defn
async def product_role_break_down(inp: ProductBreakdownInput) -> list[dict]:
    """Turn an accepted requirement into units of work — on the worker, where the agent runs.

    ONE RESULT PER CARD, carried whole. `break_down` answers a LIST of `WriteResult`, and the
    difference between "filed three" and "filed two, and the third already existed" is the whole
    content of the sentence a client reads afterwards — a boolean here would throw it away."""
    project = ProjectRegistry().get(inp.project)
    results = await asyncio.to_thread(_product_break_down, project, inp.number, inp.actor)
    return [{"ok": bool(getattr(r, "ok", False)), "detail": str(getattr(r, "detail", "") or ""),
             "ref": str(getattr(r, "ref", "") or ""), "url": str(getattr(r, "url", "") or ""),
             "existed": bool(getattr(r, "existed", False))}
            for r in (results or [])]


@activity.defn
async def product_role_answer(inp: ProductAnswerInput) -> dict:
    """Resolve a staged proposal by token — on the worker, where the agent runs.

    THE OUTCOME TRAVELS BESIDE THE SENTENCE, never inferred from it. `answer_staged` names six
    (`done`, `rejected`, `unauthorized`, `gone`, `replaced`, `expired`) and the caller maps them
    onto a refusal code; telling them apart by comparing Portuguese prose is how a refusal gets
    recorded as a decision — the reason the gate started returning a pair at all (C-33)."""
    project = ProjectRegistry().get(inp.project)

    def _run():
        from openfactory.product.confirm import answer_staged
        from openfactory.product.module import ProductModule

        # BUILT HERE, WITH THE CALLER'S `via` — AND THE GATE IS TOLD TOO. The gate builds its own
        # module when handed none, and that default says "slack"; but the module's `via` covers
        # only the module's writes, and the gate's own `may_act` kept its default, so a panel
        # approval was stamped as a Slack one in the only record that says who authorised a
        # change to a client's requirements, by the very call that had built the module right.
        via = inp.via or "api"
        return answer_staged(project, token=inp.token, approved=inp.approved, user=inp.actor,
                             module=ProductModule(project, via=via), via=via)

    code, sentence = await asyncio.to_thread(_run)
    return {"outcome": str(code or ""), "message": str(sentence or "")}


@activity.defn
async def product_role_queue(inp: ProductQueueInput) -> dict:
    """Propose what should start next — on the worker, where the agent runs.

    THE READINESS AND THE ORDERING TRAVEL SEPARATELY, because they are different kinds of claim:
    the first is arithmetic over the board and is true whatever the model said, the second is the
    judgement. Collapsing them would lose the answer the role most needs to be able to give —
    *"nothing is ready; these eleven need acceptance criteria first"* — and turn it into a
    confident list it invented."""
    project = ProjectRegistry().get(inp.project)
    state, proposal, error = await asyncio.to_thread(_product_queue_proposal, project, inp.limit)

    def _dump(x):
        return x.model_dump(mode="json") if hasattr(x, "model_dump") else x

    return {"error": str(error or ""),
            "readiness": _dump(state) if state is not None else None,
            "proposal": _dump(proposal) if proposal is not None else None}


#: The two card verbs this activity may run. A registry rather than a free string, for the reason
#: every other registry here exists: an unknown verb must be refused by name, not silently do
#: nothing while the caller reports success.
_CARD_VERBS = ("refine", "align")


@activity.defn
async def product_role_card(inp: ProductCardInput) -> dict:
    """`refine` or `align` one card — on the worker, where the agent runs."""
    if inp.verb not in _CARD_VERBS:
        return {"ok": False, "detail": f"unknown card verb {inp.verb!r} — this deployment does: "
                                       f"{', '.join(_CARD_VERBS)}", "ref": "", "url": "",
                "existed": False}
    project = ProjectRegistry().get(inp.project)
    result = await asyncio.to_thread(_product_card_write, project, inp)
    return {"ok": bool(getattr(result, "ok", False)),
            "detail": str(getattr(result, "detail", "") or ""),
            "ref": str(getattr(result, "ref", "") or ""),
            "url": str(getattr(result, "url", "") or ""),
            "existed": bool(getattr(result, "existed", False))}


def _product_card_write(project, inp: ProductCardInput):
    from openfactory.product.module import ProductModule

    module = ProductModule(project, via="api")
    if inp.verb == "refine":
        return module.refine(inp.number, actor=inp.actor)
    return module.align_card(inp.number, requirement=inp.requirement, actor=inp.actor)


@activity.defn
async def product_role_baseline(inp: ProductBaselineInput) -> dict:
    """The brownfield first pass — on the worker, where the agent runs and the docs repo is.

    THE SENTENCE IS COMPOSED HERE for the same reason its neighbour's is: `voice.baseline_done`
    runs the failure detail through `client_safe_detail` and DELIBERATELY DROPS THE PULL REQUEST
    URL, and a caller that rebuilt the sentence from the raw fields would quietly undo both.

    NO AUTHORISATION HERE. The row asked before dispatching — `baseline` is on the documented list
    of verbs that write without checking, so a second check in this activity would either be
    decoration or a second place for the answer to differ."""
    project = ProjectRegistry().get(inp.project)

    def _run():
        from openfactory.product.module import ProductModule
        from openfactory.product.voice import baseline_done

        module = ProductModule(project, via=inp.via or "api")
        cfg = getattr(project, "product", None)
        lang = getattr(project, "language", None)
        name = getattr(cfg, "agent_name", "") or ""
        try:
            result = module.baseline(areas=inp.areas)
        except Exception as exc:  # noqa: BLE001 — a crash here must still reach the person
            activity.logger.exception("the baseline pass crashed for %s", inp.project)
            return {"ok": False, "existed": False, "url": "", "ref": "",
                    "text": baseline_done(ok=False, detail=str(exc)[:200], language=lang,
                                          agent_name=name)}
        return {"ok": bool(result.ok), "existed": bool(result.existed),
                "url": str(result.url or ""), "ref": str(result.ref or ""),
                "text": baseline_done(ok=result.ok, url=result.url, detail=result.detail,
                                      existed=result.existed, language=lang, agent_name=name)}

    return await asyncio.to_thread(_run)


@activity.defn
async def product_role_needs_action(inp: ProductNeedsActionInput) -> dict:
    """What is parked and whose problem it is — on the worker, where the agent runs.

    THE SENTENCE IS COMPOSED HERE, not by the row, and that is not an accident of convenience:
    `voice.needs_action_report` reads `review.mine()` and `review.handed_back()`, and a `Review`
    that crossed the workflow boundary as JSON has values and no methods. Sending the text back
    keeps ONE composer; rebuilding the object on the far side would be a second one, drifting from
    the first the day somebody changes what counts as `mine`.

    IT WRITES NOTHING — `review_needs_action` hardcodes `may_act=False` at both of its return
    sites, so every decision is an observation. What it spends is model calls, one per parked
    ticket, which is why it is here rather than in the caller's process."""
    project = ProjectRegistry().get(inp.project)

    def _run():
        from openfactory.product.module import ProductModule
        from openfactory.product.voice import needs_action_report

        module = ProductModule(project, via=inp.via or "api")
        review, error = module.review_needs_action(limit=inp.limit)
        if review is None:
            return None, "", str(error or "")
        cfg = getattr(project, "product", None)
        text = needs_action_report(review, language=getattr(project, "language", None),
                                   agent_name=getattr(cfg, "agent_name", "") or "")
        return review, text, ""

    review, text, error = await asyncio.to_thread(_run)
    if review is None:
        # THE DIAGNOSIS STAYS ON THIS SIDE. It is loader/board prose written for an operator —
        # English, with the client's own repo slug in it — and the caller turns this into a
        # sentence saying the problem is ours.
        activity.logger.warning("[%s] needs-action could not read the board: %s",
                                inp.project, error[:400])
        return {"ok": False, "error": error, "text": "", "decisions": []}

    return {
        "ok": True, "error": "", "text": text,
        "mine": len(review.mine()), "theirs": len(review.handed_back()),
        "decisions": [{"ticket": getattr(d.verdict, "ticket", None),
                       "cause": str(getattr(d.verdict, "cause", "") or ""),
                       "acted": bool(getattr(d, "acted", False))}
                      for d in (getattr(review, "decisions", None) or ())],
    }


@activity.defn
async def product_role_say(inp: ProductSayInput) -> dict:
    """One conversational turn — on the worker, with its credentials and its box."""
    project = ProjectRegistry().get(inp.project)
    answer = await asyncio.to_thread(_product_conversation, project, inp)
    return {"ok": bool(getattr(answer, "ok", False)),
            "error": str(getattr(answer, "error", "") or ""),
            "answer": answer.model_dump(mode="json")}


def _product_conversation(project, inp: ProductSayInput):
    """The turn, WITH ITS MEMORY — and with what is still waiting.

    THREE THINGS THE SLACK PATH DOES THAT A NAIVE ROW WOULD DROP, each of which was a defect:

    1. THE PERSON'S TURN IS RECORDED ON ARRIVAL, before the model is asked, so a concurrent
       follow-up sees it. It is excluded from the history handed to the prompt, because it is
       already the question being asked and history is strictly what came before.
    2. WHAT IS STILL WAITING travels as `pending`. Its absence is what once let the role announce
       five registered requirements it had only PROPOSED — the staged draft was invisible to the
       sentence describing the corpus.
    3. WHAT IT ASKED A HUMAN FOR BECOMES A TRACKED LOOP. A request made in conversation used to
       live in a chat message and die when it scrolled away; nobody would ever have been reminded,
       which is the silent wait this platform exists to make impossible.

    AND TWO MORE THE FIRST VERSION OF THIS TURN DROPPED (2026-08-25), which is what made the Slack
    package unremovable — the capabilities were reachable from it and from nowhere else:

    4. WHAT SHE ASKED LAST IS ANSWERED FIRST. `product.channel.settle` is the stage the chat
       handler and this turn share, and what it rescues HERE is the client's "worked / did not
       work" on an open delivery (`settle_acceptance`, ADR-0025) with the client's release behind
       it: that verdict had exactly one production caller, in `runtime/slack/`, so on a panel
       deployment the sweep opened acceptance loops nobody could close. The stage's other two
       branches — a typed yes or no on a staged proposal, a late yes on one that expired — run on
       this path and find nothing today, because nothing stages a proposal under the panel's key
       (the panel proposes through `product_propose` and answers tokens through `product_answer`;
       the staging producers are chat-only). They are not claimed: `settle`'s docstring says the
       same and `test_nothing_stages_a_proposal_under_the_panel_s_key_yet` measures it. A settled
       turn comes back as the sentence alone: it carries no draft, and `product_say` reads
       `draft is None` as "nothing to propose" — the truth of it.
    5. THE DECISIONS SHE ASKED FOR ARE CLOSED by the person replying — before her new reply can
       open fresh ones, and only on a message she will actually read, which this one is: every
       typed intent was routed before this workflow started (`_say_as_an_intent`).

    THE TRANSPORT TRAVELS TO THE GATE. `inp.via` is what the row's actor carried (`panel`, `cli`);
    it builds the module AND is handed to `settle`, so the release gate behind a "funcionou o #12"
    records where the approver spoke from. Before, the module said `api` and the gate said `slack`
    for the same person in the same turn."""
    from openfactory.memory import transcript
    from openfactory.product.channel import settle
    from openfactory.product.module import ProductModule
    from openfactory.product.role import ProductAnswer
    from openfactory.product.staging import _proposal_summary

    via = inp.via or "api"
    module = ProductModule(project, via=via)
    name = getattr(project, "name", "") or ""
    thread = inp.thread or name
    arrival = transcript.record(name, thread=thread, role="person", text=inp.message,
                                actor=inp.asked_by)
    settled = settle(project, text=inp.message, user=inp.asked_by, thread=thread, module=module,
                     via=via)
    if settled.reply is not None:
        transcript.record(name, thread=thread, role="agent", text=settled.reply)
        return ProductAnswer(ok=True, text=settled.reply)

    said = transcript.render(
        [t for t in transcript.recent(name, thread=thread)
         if not (arrival and getattr(t, "ts", None) == arrival)],
        agent_name=getattr(getattr(project, "product", None), "agent_name", "") or "")
    pending = _proposal_summary(settled.waiting) if settled.waiting else ""

    try:
        module.close_decisions_answered()
    except Exception:  # noqa: BLE001 — bookkeeping must never cost the reply
        activity.logger.warning("[%s] could not close answered decisions", name, exc_info=True)
    answer = module.answer(inp.message, conversation=said, pending=pending)
    if getattr(answer, "ok", False):
        transcript.record(name, thread=thread, role="agent",
                          text=str(getattr(answer, "text", "") or ""))
        if getattr(answer, "decisions", None):
            try:
                module.record_decisions(answer.decisions)
            except Exception:  # noqa: BLE001 — a lost loop must not cost the reply
                activity.logger.warning(
                    "OPENFACTORY_PRODUCT_DECISIONS_UNRECORDED project=%s — it asked a human for "
                    "something "
                    "and nothing is tracking it", name, exc_info=True)
    return answer


def _product_queue_proposal(project, limit: int):
    from openfactory.product.module import ProductModule

    return ProductModule(project, via="api").propose_queue(limit=limit)


def _product_break_down(project, number: int, actor: str):
    from openfactory.product.module import ProductModule

    return ProductModule(project, via="api").break_down(number, actor=actor)


@activity.defn
async def diagnose_impediment(inp: HoldSyncInput) -> bool:
    """ADR-0015 — the tech lead's diagnosis of a parked impediment, posted to the ticket + Slack.
    Best-effort and bounded; the raw note stands if it can't opine. Worker (agent + gh + creds)."""
    return await _heartbeat_while(lambda: _do_diagnose(inp),
                                  f"diagnose {inp.project}#{inp.issue}")  # type: ignore[return-value]


def _metrics_sink():
    """The metrics sink this deployment configured (observability/registry.py).

    Which one is a REGISTRY decision now, not a conditional here: `OPENFACTORY_METRICS_SINK` names
    it
    outright, and absent that the answer is inferred exactly as it always was — DynamoDB when
    `OPENFACTORY_METRICS_TABLE` is set by terraform, else Null. Still one place, so the activity
    stays
    simple and tests can monkeypatch it; the difference is that a deployment can now say `sqlite`
    without a code change, which is what the local distribution needs."""
    import os

    from openfactory.observability.registry import build_metrics_sink, metrics_sink_kind

    kind = metrics_sink_kind()
    return build_metrics_sink(
        kind,
        table=os.environ.get("OPENFACTORY_METRICS_TABLE"),
        path=os.environ.get("OPENFACTORY_METRICS_DB") or "openfactory-metrics.db",
    )


@activity.defn
async def record_job_metrics(inp: JobMetricsInput) -> None:
    """Persist per-invocation + job-summary cost telemetry (observability.metrics → the panel's
    cost dashboard: spend by period / model / harness). One item per agent run + one job summary.
    BEST-EFFORT: a telemetry write must NEVER affect the job (the sink already swallows write
    errors; this also shields the build/serialize). Worker (has AWS creds +
    OPENFACTORY_METRICS_TABLE)."""
    from openfactory.observability.metrics import MetricRecord

    def _do() -> None:
        sink = _metrics_sink()
        for r in inp.agent_runs:
            sink.record(MetricRecord(
                project=inp.project, ticket=inp.issue, ts=inp.ts, kind="agent_run",
                role=r.get("role", ""), model=r.get("model", ""), harness=r.get("harness", ""),
                cost_usd=r.get("cost_usd"), num_turns=r.get("num_turns"),
                input_tokens=r.get("input_tokens"), output_tokens=r.get("output_tokens"),
                # `.get` and not `.get(..., 0)`: an absent dimension stays absent all the way to
                # the row, because a pass nobody could read must not average as a pass that did
                # nothing.
                tool_calls=r.get("tool_calls"), repeated_calls=r.get("repeated_calls"),
                refused_calls=r.get("refused_calls"),
                turns_to_first_edit=r.get("turns_to_first_edit")))
        sink.record(MetricRecord(
            project=inp.project, ticket=inp.issue, ts=inp.ts, kind="job", role="_job_",
            state=inp.state, title=inp.title, wall_s=inp.wall_s,
            total_cost_usd=inp.total_cost_usd, pr_url=inp.pr_url,
            knowledge=inp.knowledge))

    try:
        await asyncio.to_thread(_do)
    except Exception:  # noqa: BLE001 — telemetry is additive; never let it fail the job
        activity.logger.warning("record_job_metrics failed for %s#%s", inp.project, inp.issue)


@activity.defn
async def notify_coordinator(item: CoordinatorItem) -> None:
    """SignalWithStart the project's ALWAYS-ALIVE coordinator with a parked decision — starts it
    if not running (idempotent by the deterministic id openfactory-coordinator-<project>), else just
    delivers the signal. Best-effort: a coordinator hiccup must never block the parked job."""
    from openfactory.runtime.temporal import TASK_QUEUE
    from openfactory.runtime.temporal.connection import connect

    try:
        client = await connect()
        await client.start_workflow(
            "CoordinatorWorkflow", CoordinatorInput(project=item.project),
            id=f"openfactory-coordinator-{item.project}", task_queue=TASK_QUEUE,
            start_signal="on_decision", start_signal_args=[item],
        )
    except Exception:  # noqa: BLE001 — the decision is already visible; advice is additive
        activity.logger.warning("notify_coordinator failed for %s#%s", item.project, item.issue)


@activity.defn
async def notify_coordinator_say(inp: CoordinatorSayInput) -> None:
    """SignalWithStart the project's coordinator with a narrated lifecycle update — a panel toast
    AND the project's Slack channel, so the tech-lead voices the whole lifecycle (ADR-0015).

    NEEDS_ACTION IS SENT HERE, not left to the diagnosis. It used to be skipped to avoid a
    double-send, on the reasoning that `diagnose_impediment` would post the full HandOff — which
    made the ONLY alert for a parked job a side effect of an expensive, failure-prone operation
    whose failure is deliberately swallowed. On 2026-07-27 that diagnosis could not run (its agent
    could not authenticate and its GitHub reads were throttled), so #478 parked and the channel
    stayed silent for eighteen hours while the floor was held and nothing else ran.

    An alert that depends on a model call and a repo clone is not an alert. This one needs neither:
    the ticket number, the reason and what to do. The diagnosis still follows when it can, and reads
    as the detail on an alert people have already seen rather than as the first they hear of it.

    `deploy` stays skipped — `notify_deploy` already speaks it."""
    from openfactory.runtime.temporal import TASK_QUEUE
    from openfactory.runtime.temporal.connection import connect

    try:
        client = await connect()
        await client.start_workflow(
            "CoordinatorWorkflow", CoordinatorInput(project=inp.project),
            id=f"openfactory-coordinator-{inp.project}", task_queue=TASK_QUEUE,
            start_signal="say", start_signal_args=[inp.text, inp.kind],
        )
    except Exception:  # noqa: BLE001
        activity.logger.warning("coordinator say failed for %s", inp.project)
    if inp.kind in ("pickup", "merge", "needs_action"):  # the tech-lead's voice in Slack
        try:

            from openfactory.factory import notifier_for_project

            project = ProjectRegistry().get(inp.project)
            msg = inp.text  # e.g. "▶ Picking up #425" — enrich with the TITLE so it reads on mobile
            m = _ref_in(inp.text)
            if m:
                try:
                    title = _tracker_for(project).get_ticket(m).title
                    if title:
                        msg = f"{inp.text} — {title}"
                except Exception:  # noqa: BLE001 — the title is a bonus; fall back to the number
                    activity.logger.debug("no title for %s; announcing the number alone",
                                          inp.text[:40])
            level = "warning" if inp.kind == "needs_action" else "info"
            # `about` IS THE WHOLE FIX AND IT GOES THROUGH THE PROTOCOL. This message names a
            # ticket in prose and asks for an answer; without telling the provider WHICH ticket,
            # a reply in the alert's own thread — "skip", the verb this very alert asks for —
            # resolves to nothing, because the number lives only in text the parser never sees.
            #
            # Declared here and LINKED by the provider, rather than the core reaching into Slack
            # to register a thread id: the core does not know what a thread is, and a test enforces
            # that it never learns (test_provider_seams). A provider with no message identity
            # ignores `about` and the caller degrades to requiring the number typed out.
            about = m or ""
            await asyncio.to_thread(
                lambda: notifier_for_project(project).notify(
                    message=msg, level=level, about=about))
        except Exception:  # noqa: BLE001 — the panel toast already fired; Slack is additive
            activity.logger.warning("coordinator say -> slack failed for %s", inp.project)


#: A ticket ref as it appears in a sentence the platform wrote — `#425`, `DAR-3`, `CONT-412`,
#: or `owner/name#12`. Anchored to a word boundary so prose around it does not bleed in.
_REF_IN_TEXT = _re_module.compile(
    r"(?:(?<=\s)|^)("
    r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*#[A-Za-z0-9]+"   # owner/name#12
    r"|#\d+"                                                                # #425
    r"|[A-Za-z][A-Za-z0-9]*-\d+"                                            # DAR-3, CONT-412
    r")\b"
)


def _ref_in(text: str) -> str:
    r"""The ticket this sentence is about, or "".

    THIS WAS `re.search(r"#(\d+)")`. On a Jira or Azure DevOps deployment — refs like `CONT-412`
    — it never matched, so `about` was always empty and the needs-action alert arrived with no
    ticket identity attached. The comment beside `about` already says what that costs: "a reply in
    the alert's own thread — `skip`, the verb this very alert asks for — resolves to nothing".

    So the escalation worked and its executable option was not executable from where it was
    offered: the letter of the invariant kept, the spirit broken, and only on the trackers we do
    not run ourselves. Same class as #69, which this codebase fixed in `techlead_watch` and left
    here.

    The `#` is stripped from a bare numeric ref because that is what every tracker method takes."""
    m = _REF_IN_TEXT.search(f" {text or ''}")
    return m.group(1).lstrip("#") if m else ""


def _do_refresh_knowledge(inp: KnowledgeRefreshInput) -> str:
    """The Knowledge Pipeline (§11), post-merge: regenerate the module map from the base branch's
    NEW state and publish it into the project's CONTEXT repository (D-2/D-3 — never the client's
    own source repo). Returns a short outcome word for the log — "off" / "no-repo" /
    "no-context" / "unchanged" / "published" / "failed".

    Opt-in (`manifest.knowledge_map`) and best-effort throughout: this runs AFTER the ticket has
    merged, so nothing it does may fail the job or hold the floor. The two properties that make
    it safe to run on every merge:

    - **It converges.** The bundle is built from commit X and published as a NEW commit, so the
      provenance stamps always differ. `write_bundle` compares the DERIVED content instead and
      writes nothing when the sources are unchanged, so a refresh triggered by the previous
      refresh is a no-op instead of an endless commit chain (§22 D-5).
    - **It doesn't disturb the client.** Publishing goes into the context repository the platform
      itself created — never the client's `main` — so it fires no deploy and puts no client PR
      behind (see `openfactory.knowledge.pipeline`).

    "no-context": the project has no `product.docs_repo` — never onboarded with a context
    repository, or onboarded before one existed. A real, legitimate state (the doctor already
    treats a missing context repo as a PASS-with-note, not a FAIL) — checked FIRST, before the
    source repo is even resolved, so a never-onboarded project doesn't pay for a clone it can't
    use, the same way the source-repo check below short-circuits before the source is synced.
    """
    from datetime import UTC, datetime

    from openfactory.adapters.forge.registry import clone_url_for
    from openfactory.credentials import deployment_forge_token, forge_token_for
    from openfactory.knowledge import build_bundle, write_bundle
    from openfactory.knowledge.bundle import BUNDLE_DIRNAME
    from openfactory.knowledge.pipeline import (
        discard_fetched_bundle,
        fetch_published_bundle,
        okf_subpath,
        publish_bundle,
    )
    from openfactory.loader import load_manifest
    from openfactory.runtime.repo_cache import RepoCache

    project = ProjectRegistry().get(inp.project)

    docs_repo = (getattr(getattr(project, "product", None), "docs_repo", "") or "").strip()
    if not docs_repo:
        return "no-context"

    # SYNC BEFORE READING THE MANIFEST. `project.repo_path` is a REGISTRY value — on Fargate it is
    # where the entrypoint clones to; on the WORKER it names no real directory at all. Loading the
    # manifest from it raises "no manifest at /work/<project>/.openfactory/project.yaml" before
    # this ever reaches a checkout, which is why no bundle was ever published: the refresh died on
    # its first line every time, silently, because the caller treats a failure here as best-effort.
    #
    # This is the SAME bug `_do_preflight` above already carries a comment about. It was fixed
    # there and repeated here.
    repo = (project.forge.repo if project.forge else None) or project.tracker.repo or ""
    token = forge_token_for(project) or deployment_forge_token(project) or ""
    if not repo:
        return "no-repo"
    url = clone_url_for(project, repo, token=token)
    # THE SAME RUNTIME CREDENTIAL AS THE SOURCE URL ABOVE, DELIBERATELY NOT
    # `onboard.py::context_clone_url` — that resolver's own docstring warns the onboarding
    # credential and the runtime credential can resolve to DIFFERENT credentials with different
    # repository visibility on some deployments. This activity is a runtime actor like the rest
    # of the job path, not onboarding, so it must match `product/module.py`'s runtime pattern.
    context_url = clone_url_for(project, docs_repo, token=token)
    subpath = okf_subpath(repo)
    # base_branch isn't known until the manifest loads, so the first sync asks for the registry's
    # declared base and otherwise for NOTHING, letting the clone land where the repository points
    # (#162). The comment above is right that this was `_do_preflight`'s bug repeated here — and
    # the repetition included the `"main"`, which is not a guess costing a fetch: on a `master`
    # repository `--branch main` names nothing and the refresh dies on its first line, which is
    # exactly the silence the comment above describes.
    from openfactory.loader import load_manifest_base_branch
    from openfactory.runtime.repo_cache import current_branch

    repo_path = RepoCache().sync(project.name, url,
                                 load_manifest_base_branch(project, default=""))
    if repo_path is None:
        return "no-repo"

    manifest = load_manifest(project.model_copy(update={"repo_path": str(repo_path)}))
    if not manifest.knowledge_map:
        return "off"
    declared = manifest.declared_base_branch     # the FILE's word, never the schema default
    if declared and declared != current_branch(repo_path):
        repo_path = RepoCache().sync(project.name, url, declared)
        if repo_path is None:
            return "no-repo"

    published: Path | None = None
    try:
        # Bring the ALREADY-published bundle into the tree first, so `write_bundle` compares
        # against what is live. Without this a fresh clone has no bundle, every refresh looks
        # like a change, and the convergence guarantee above evaporates.
        published = fetch_published_bundle(context_url, subpath=subpath)
        dest = Path(repo_path) / BUNDLE_DIRNAME
        if published is not None:
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(published, dest)

        head = subprocess.run(["git", "-C", str(repo_path), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30, check=False)
        commit = head.stdout.strip() if head.returncode == 0 else ""
        bundle = build_bundle(Path(repo_path), commit=commit,
                             generated_at=datetime.now(UTC).isoformat())
        if write_bundle(bundle, Path(repo_path)) is None:
            return "unchanged"
        from openfactory.credentials import bot_identity

        bot = bot_identity()
        ok = publish_bundle(dest, context_url, subpath=subpath, source_commit=commit,
                            author=(bot.name or "openfactory-bot",
                                    bot.email or "openfactory-bot@local"))
        return "published" if ok else "failed"
    except Exception:  # noqa: BLE001 — the ticket already merged; knowledge must never break it
        activity.logger.warning("knowledge refresh failed for %s", inp.project, exc_info=True)
        return "failed"
    finally:
        discard_fetched_bundle(published)
        # Never leave OUR generated bundle in the shared repo cache: the next job's worktree
        # would inherit it as an untracked file and `git add -A` would commit the map into that
        # ticket's PR. Restore-then-clean rather than a blind delete, because a project may
        # legitimately keep `knowledge/` COMMITTED in its own repo (Phase 1's shape) — there the
        # directory is tracked content that must survive us having written into it.
        for args in (["checkout", "--", BUNDLE_DIRNAME], ["clean", "-fdq", BUNDLE_DIRNAME]):
            subprocess.run(["git", "-C", str(repo_path), *args],
                           capture_output=True, timeout=60, check=False)


@activity.defn
async def refresh_knowledge(inp: KnowledgeRefreshInput) -> str:
    """ADR/§11 — regenerate + publish the project's module map after a merge. Opt-in, bounded,
    best-effort: a failure here never touches the merged ticket. Worker (git + App creds)."""
    return await asyncio.to_thread(lambda: _do_refresh_knowledge(inp))


#: Where a sweep remembers what it already reported. The metrics table, because it is already
#: there, already read by the panel, and survives the worker being replaced — which an in-process
#: memory does not, and a sweep that forgets on every deploy re-reports everything.
_SWEEP_KIND = "product_sweep"

#: What the tech-lead's last round already said. Same mechanism as the sweep's memory and for the
#: same reason: a watcher with no memory repeats itself, and a channel that repeats itself is one
#: nobody reads on the hour that matters.
_WATCH_KIND = "techlead_watch"

#: TWO memories now ride this kind, one per thing the hourly round remembers, so every reader of it
#: must say WHICH. Read by kind alone, the orphan repair's row is the newest `techlead_watch` row
#: on the rounds that follow a repair, it carries no `said`, and the watcher would read it as "I
#: have never mentioned anything" — repeating every standing finding on the hour.
_WATCH_ROLE = "_watch_"
_REPOINT_ROLE = "_repoint_"


def _watch_history(project_name: str) -> dict[str, float]:
    """`finding key → how far it had gone when we last mentioned it`."""
    try:
        from openfactory.api.metrics_view import scan_records

        rows = [r for r in scan_records()
                if r.get("kind") == _WATCH_KIND
                and str(r.get("role") or _WATCH_ROLE) == _WATCH_ROLE
                and str(r.get("pk") or r.get("project") or "") == project_name]
        if not rows:
            return {}
        rows.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
        raw = (rows[0].get("extra") or {}).get("said") or ""
        out: dict[str, float] = {}
        for part in str(raw).split("|"):
            key, _, value = part.rpartition("=")
            if key:
                try:
                    out[key] = float(value)
                except ValueError:
                    continue
        return out
    except Exception as exc:  # noqa: BLE001
        # No memory means every round reports everything again — noisy, but never silent, which is
        # the right way round for this failure. Still worth saying so somebody can fix it.
        activity.logger.warning("techlead watch: could not read what the last round said (%s) — "
                                "this round may repeat itself", exc)
        return {}


def _remember_watch(project_name: str, said: dict[str, float]) -> None:
    try:
        from datetime import UTC, datetime

        from openfactory.observability.metrics import MetricRecord

        _metrics_sink().record(MetricRecord(
            project=project_name, ticket=_WATCH_ROLE, ts=datetime.now(UTC).isoformat(),
            kind=_WATCH_KIND, role=_WATCH_ROLE,
            extra={"said": "|".join(f"{k}={v}" for k, v in sorted(said.items()))}))
    except Exception as exc:  # noqa: BLE001 — remembering is an optimisation, never the job
        activity.logger.warning("techlead watch: could not record what it said for %s (%s) — the "
                                "next round may repeat it", project_name, exc)


#: A row that says only "this store took a write". It records no sweep and carries no findings, so
#: every reader of `_SWEEP_KIND` skips it; its whole job is to give the NEXT round's read something
#: to come back with, since a read that returns nothing proves nothing.
_SWEEP_PROBE = "probe"


def _sweep_rows(project_name: str) -> list[dict] | None:
    """This project's sweep memory, newest first — or `None` when the read proved nothing.

    THREE ANSWERS, NOT TWO, because one caller cannot live on two. `scan_records` degrades to `[]`
    on a throttled scan, absent credentials or a table that is not there yet, which is the same
    shape as a store that has genuinely never been written. To the findings memory those two mean
    the same thing — report something twice. To the arrival they are opposites: one is a client who
    has never met this role, the other is a client who has been working with her for weeks.

    THE PROOF IS THE TABLE ANSWERING AT ALL, not this project having a row in it. The table is
    shared by every project, every job, every agent run and every client message, so a completely
    empty return is the one state a failed read cannot be told apart from — and a return with any
    row in it is a read that demonstrably works, which makes the absence of this project's rows an
    observation rather than a guess.
    """
    try:
        from openfactory.api.metrics_view import scan_records

        rows = scan_records()
    except Exception as exc:  # noqa: BLE001
        activity.logger.warning("product sweep: could not reach the memory store for %s (%s)",
                                project_name, exc)
        return None
    if not rows:
        return None
    mine = [r for r in rows
            if r.get("kind") == _SWEEP_KIND
            and str(r.get("pk") or r.get("project") or "") == project_name
            and not (r.get("extra") or {}).get(_SWEEP_PROBE)]
    mine.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    return mine


def _last_sweep_keys(project_name: str) -> list[str]:
    """What the previous sweep found, as `ticket:kind` fingerprints. `[]` on any trouble — the cost
    of forgetting is one repeated report, which is far cheaper than a sweep that fails."""
    rows = _sweep_rows(project_name)
    if rows is None:
        # An unreadable history means every finding looks NEW, so the sweep reports the whole
        # backlog as if it just appeared — the exact noise the "only what changed" rule prevents.
        activity.logger.warning("could not read what the last sweep reported for %s — this sweep "
                                "may repeat findings that are not new", project_name)
        return []
    if not rows:
        return []
    raw = (rows[0].get("extra") or {}).get("findings") or ""
    return [k for k in str(raw).split(",") if k]


def _sweep_history(project_name: str) -> dict | None:
    """The last sweep's snapshot of the board, `{}` when this project has provably never been
    swept, and `None` when the store proved nothing at all.

    A count on its own says how bad things are; the same count next to last week's says whether
    anybody is winning. That is the difference between a report and a trend, and it costs one extra
    field on a record already being written.

    THIS ROW IS ALSO THE ONLY COPY OF "I HAVE ALREADY INTRODUCED MYSELF TO THIS CLIENT", which is
    why its absence is split in two. Every other fact the sweep and the rounds remember is
    re-derived from live state every pass — the board says what is rotten, the corpus says what is
    promised, the ledger says what is unanswered — so losing one of those costs a repetition.
    Nothing anywhere says whether this role has ever spoken to this client. An absence read as "we
    have never met" is therefore not a repetition; it is a first-contact message to somebody who
    has been working with her for weeks."""
    rows = _sweep_rows(project_name)
    if rows is None:
        return None
    if not rows:
        return {}
    # A row that carried nothing is still a sweep that happened. The arrival is decided on the ROW
    # existing, never on what it holds, or a memory row that lost its fields greets the client
    # again on the strength of its own emptiness.
    return (rows[0].get("extra") or {}) or {"backlog": ""}


def _probe_sweep_memory(project_name: str) -> None:
    """Leave behind a row that says only "this store took a write".

    A round that cannot tell an empty memory from an unreadable one never introduces itself, and
    for a client whose factory has recorded nothing yet that state would otherwise be permanent —
    nothing else would put a first row in the table for them, and the arrival would be owed for
    ever. The next round reads this one, which is the read proving itself, finds no sweep recorded,
    and arrives one cadence late. That delay is the entire price of never greeting a stranger who
    is not one."""
    try:
        from datetime import UTC, datetime

        from openfactory.observability.metrics import MetricRecord

        _metrics_sink().record(MetricRecord(
            project=project_name, ticket="_sweep_", ts=datetime.now(UTC).isoformat(),
            kind=_SWEEP_KIND, role="_sweep_", extra={_SWEEP_PROBE: "1"}))
    except Exception as exc:  # noqa: BLE001 — a probe must never fail the schedule it rides on
        activity.logger.warning("product sweep: could not probe the memory store for %s (%s) — "
                                "this project's arrival stays owed", project_name, exc)


def _remember_sweep(project_name: str, keys: list[str], ts: str, backlog: int = 0) -> None:
    try:
        from openfactory.observability.metrics import MetricRecord

        _metrics_sink().record(MetricRecord(
            project=project_name, ticket="_sweep_", ts=ts, kind=_SWEEP_KIND, role="_sweep_",
            extra={"findings": ",".join(keys), "backlog": str(backlog)}))
    except Exception as exc:  # noqa: BLE001 — remembering is an optimisation, never the job
        # Except for the one fact this row is the only copy of. A lost findings list costs a
        # repeated report; a lost FIRST row costs a client their second first-contact message,
        # because nothing else records that this role has already arrived.
        activity.logger.error("OPENFACTORY_PRODUCT_SWEEP_UNREMEMBERED project=%s (%s) — this round "
                              "is not "
                              "in the memory; the next one repeats it, and if this was the arrival "
                              "it introduces itself again", project_name, exc)


@activity.defn
async def product_sweep(project_name: str) -> str:
    """The product role's scheduled look at the board, posted to its own channel (ADR-0019).

    READ-ONLY, on a schedule exactly as it is on request: this role has the least context precisely
    when it is told to look at everything at once, and a card it moved at 6am is a card somebody
    has to un-move.

    STAYS QUIET WHEN THERE IS NOTHING TO SAY. A daily message that says "nothing out of place" every
    day for three weeks trains people to skip it, and then it is invisible on the day it matters.
    """
    def _do() -> str:
        from datetime import UTC, datetime

        from openfactory.product.module import ProductModule
        from openfactory.product.voice import triage_report

        project = ProjectRegistry().get(project_name)
        cfg = getattr(project, "product", None)
        # `channel_destination`, not `channel_id` (C-25 review): the bare field is a Slack rule,
        # and it silenced every panel-channel deployment — provider shipped, gate never passed.
        if cfg is None or not getattr(cfg, "enabled", True) \
                or not channel_destination(project, cfg.channel_id or ""):
            return "off"

        module = ProductModule(project)

        # THE FIRST SWEEP IS AN ARRIVAL, not a report. Nobody has met this role yet, and a first
        # message that opens with six board findings is a stranger handing you a list.
        from openfactory.adapters.channel import build_channel

        channel = build_channel(project)
        history = _sweep_history(project_name)
        if history is None:
            # THE ONE THING THIS SWEEP MAY NOT GUESS. A store that answered nothing at all looks
            # exactly like one that has never been written, and reading the second as the first
            # sends a client who has been working with this role for weeks her first-contact
            # message — every cadence, for as long as the read stays broken.
            #
            # NOTHING IS SAID AT ALL on such a round, not merely the arrival. Every message below
            # is gated on a memory in the table that just answered nothing: the report would
            # restate the whole backlog as new, and the follow-through dedupes against a ledger in
            # the same table. Skipping the round costs a week of latency and no facts — the board,
            # the corpus and the ledger are all re-read next pass — while the two repairs that
            # cannot wait a week (the proposal rescue, the orphaned cards) ride the HOURLY round.
            activity.logger.error(
                "OPENFACTORY_PRODUCT_SWEEP_MEMORY_UNPROVEN project=%s — the memory store answered "
                "nothing, so this round cannot tell a new client from one it has already met; "
                "saying nothing this pass", project_name)
            _probe_sweep_memory(project_name)
            return "memory-unproven"
        if not history:
            # POST FIRST, remember after: a non-empty history routes every later sweep to the
            # triage path, so committing the marker before a failed intro would mean the client's
            # first-ever message from this role is a bare board report a cadence later. A dropped
            # intro leaves history empty and the next sweep introduces again.
            if not _product_post(channel, project, cfg, module.introduce()):
                return "intro-dropped"
            _remember_sweep(project_name, [], datetime.now(UTC).isoformat())
            return "introduced"

        report, error = module.triage_board()
        if report is None:
            activity.logger.warning("product sweep: %s could not read the board (%s)",
                                    project_name, error)
            return "unreadable"

        # ONLY WHAT IS NEW. Without this the same findings arrive every single run until somebody
        # fixes them, which is how a scheduled report becomes wallpaper — and then it is invisible
        # on the day it says something that matters.
        previous = _last_sweep_keys(project_name)
        fresh = report.since(previous)

        # ── FOLLOW THROUGH runs on EVERY sweep that could read the board — including the quiet
        # ones. It used to sit behind the freshness returns below, which coupled closing, chasing
        # and "está pronto" to whether NEW rot appeared that week: the week somebody finally wrote
        # the missing criteria was, by construction, a week with nothing new — so the question
        # stayed open for ever and the thank-you was never said. Quiet weeks are exactly when
        # follow-through is the only thing worth doing.
        followed = _product_followup(project, module, report, cfg)

        if not fresh.observations:
            # Nothing needed posting, so remembering the keys claims nothing about the channel —
            # it only prunes resolved findings and refreshes the backlog count.
            _remember_sweep(project_name, report.keys(), datetime.now(UTC).isoformat(),
                            backlog=len(report.observations))
            if not previous:
                return f"clean {followed}"   # first look, nothing wrong: no report to post
            return f"nothing-new {followed}"

        # what did NOT change is reported as counts, not re-listed: a backlog must not vanish by
        # standing still, and forty repeated ticket numbers are what nobody reads twice
        seen = set(previous)
        standing: dict[str, int] = {}
        for o in report.observations:
            if f"{o.ticket}:{o.kind}" in seen:
                standing[o.kind] = standing.get(o.kind, 0) + 1

        text = triage_report(fresh, language=getattr(project, "language", None),
                             agent_name=getattr(cfg, "agent_name", "") or "",
                             standing=standing)
        # The keys commit ONLY after the report lands. Committed first, a dropped post turned
        # every fresh finding into "standing" for the next sweep — reported to nobody, ever,
        # with the loop that would heal it blinded by its own memory.
        if not _product_post(channel, project, cfg, text):
            return f"report-dropped:{len(fresh.observations)} {followed}"
        _remember_sweep(project_name, report.keys(), datetime.now(UTC).isoformat(),
                        backlog=len(report.observations))
        return f"reported:{len(fresh.observations)} {followed}"



    try:
        return await asyncio.to_thread(_do)
    except Exception:  # noqa: BLE001 — a sweep must never fail a schedule into a retry storm
        activity.logger.exception("product sweep failed for %s", project_name)
        return "error"

def _invite_the_client_to_look(project, inp) -> None:
    """The client's half of a green deploy: their words, their channel, the same address (#122).

    ADDITIVE AND SILENT. No product module, no channel, no client — no message, and the operator
    already has theirs. This is why the invitation is published from the deploy watch rather than
    from `product/`: a capability that only exists when an optional module is switched on is the
    defect this card was opened for, one layer up.

    IT NAMES THE TICKET WHEN THERE IS NO REQUIREMENT BEHIND IT. The client-facing delivery loop
    opens only for work filed FROM a requirement, and a ticket somebody dragged into TO-DO — the
    ordinary way a team adopting this works — never opens one. Keying the invitation off that loop
    would have made it unreachable for exactly the flow the pilot runs.

    NEVER RAISES: the deploy happened and the operator was told. Nothing about the second audience
    may cost the first one its message."""
    cfg = getattr(project, "product", None)
    if cfg is None or not getattr(cfg, "enabled", True):
        return
    destination = channel_destination(project, getattr(cfg, "channel_id", "") or "")
    if not destination:
        return  # no client to tell; the operator's notification already went out
    try:
        from openfactory.adapters.channel import build_channel
        from openfactory.product import voice

        # THE TITLE, NOT THE NUMBER — and best-effort, because a tracker that will not answer must
        # cost the client a vaguer sentence, never the message.
        what = ""
        try:
            what = str(getattr(_tracker_for(project).get_ticket(inp.issue), "title", "") or "")
        except Exception as exc:  # noqa: BLE001
            activity.logger.info("could not read #%s's title for the client's invitation (%s)",
                                 inp.issue, str(exc)[:120])
        text = voice.deploy_invitation(what=what, url=inp.url,
                                       language=getattr(project, "language", None))
        _product_post(build_channel(project), project, cfg, text)
    except Exception as exc:  # noqa: BLE001 — the client half is additive, never load-bearing
        activity.logger.warning(
            "could not invite the client to look at %s#%s on %s (%s) — the operator was told",
            inp.project, inp.issue, inp.env, str(exc)[:160])


def _product_post(channel, project, cfg, text: str) -> bool:
    """Say it to the client channel AND remember having said it — but only what was actually said.

    Every proactive post — the introduction, the triage report, a delivery notice, a question, a
    chase — went out through bare `channel.say` and into no record at all. So when a person
    answered her question, the first turn of that conversation (HER question) was the one turn her
    memory did not hold: she asked, was answered, and did not know what about. Keyed by the
    channel id, which is where a bare post lives (see product_channel.conversation_key).

    Returns whether the channel POSITIVELY delivered (`say`'s contract: bool, never raises).
    THE ONE SEAM every caller must gate its record on: a dropped post writes no transcript here
    and no ledger row at the call site, so the item stays eligible for the next sweep instead of
    being remembered as asked/announced/reported to a channel that never heard it (ADR-0021 —
    memory closes on observation, never on self-report)."""
    from openfactory.memory import transcript

    if not channel.say(project=project, channel=cfg.channel_id, text=text):
        activity.logger.error(
            "OPENFACTORY_PRODUCT_POST_DROPPED project=%s channel=%s chars=%d — nothing recorded; "
            "the "
            "item stays eligible for the next sweep",
            getattr(project, "name", ""), cfg.channel_id, len(text))
        return False
    transcript.record(getattr(project, "name", ""), thread=cfg.channel_id, role="agent",
                      text=text, channel=cfg.channel_id)
    return True


def _product_followup(project, module, report, cfg) -> str:
    """Close what the board resolved, ask what is new, chase what went quiet — once.

    Separated from the sweep body because it is a different job with a different failure mode: the
    report going wrong makes a message worse, this going wrong makes her forget, and the second is
    the one that has to be visible."""
    from openfactory.adapters.channel import build_channel
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import (
        ACCEPTANCE,
        CHASED,
        DECISION,
        QUESTION,
        chase_due,
        close_by_observation,
        waiting,
    )
    from openfactory.product import followup

    name = getattr(cfg, "agent_name", "") or ""
    lang = getattr(project, "language", None)

    # A LIVE provider client, or mentions cannot exist. Calling mention() bare used to run one
    # `gh api` per login (the shared App quota) toward a directory lookup that ALWAYS returned
    # empty — and poisoned two process caches on the way, so even later callers with a client got
    # nothing. Every "she names the person" promise was structurally a plain-text name.
    channel = build_channel(project)
    web_client = getattr(channel, "client", lambda _p: None)(project)

    def _mention(login: str) -> str:
        # NO TOKEN. `module.token` is the FORGE credential (`ProductModule.token` resolves through
        # `forge_token_for`), and handing it to a person lookup is how a GitHub App token reached
        # an Atlassian site. The tracker axis resolves its own from the project (#162).
        return channel.mention(login, web_client=web_client, project=project) if login else ""

    ledger = loop_store.read(project.name)
    open_now = waiting(ledger, owner=followup.OWNER)

    # 1. CLOSE what the world resolved. A question whose finding is gone was answered by the world,
    #    which is the only kind of answer that counts (see followup.py).
    live = {f"{o.ticket}:{o.kind}" for o in report.observations}
    resolved = followup.answered(open_now, live)
    settled = close_by_observation(ledger, resolved)

    # 2. SAY what got delivered — the sentence she could never say, unprompted, because the person
    #    who asked has no reason to be watching a board to find out it happened.
    done = followup.delivered(open_now, _closed_issue_numbers(module))
    # THREE-part keys — (kind, subject, about) — since the collision fix. A two-part unpack sat
    # here after that migration: on the FIRST completed delivery it raised ValueError, the
    # exception rode up to product_sweep's catch-all, and because the close never ran, the same
    # loop crashed every future sweep too — Nina permanently mute, panel forever "error". Caught
    # by audit before any delivery completed in production; the end-to-end sweep test now
    # executes this exact line.
    accepting: list = []
    announced: dict = {}
    for key, outcome in done.items():
        (_, subject, _about) = key
        loop = next((x for x in open_now if x.subject == subject), None)
        if loop is None:
            continue
        # The close and the acceptance question are gated on the ANNOUNCEMENT LANDING. Recorded
        # first, a dropped "está pronto" was never re-sent, and the 72h acceptance chase became
        # the client's first-ever message about that delivery — referencing an announcement that
        # never existed. A dropped post leaves the DELIVERY loop open for the next sweep.
        if not _product_post(channel, project, cfg,
                             followup.delivered_text(loop, agent_name=name, language=lang)
                             + followup.acceptance_question(loop, agent_name=name,
                                                            language=lang)):
            continue
        announced[key] = outcome
        # THE DELIVERY LOOP CLOSES; THE ACCEPTANCE LOOP OPENS. The board closing is the
        # factory agreeing with itself — it says nothing about whether the person who asked
        # got what they wanted. Only their answer closes this one (ADR-0025).
        accepting.append(followup.acceptance_of(
            loop.__class__(**{**loop.__dict__,
                              "context": {**(loop.context or {}),
                                          "channel": cfg.channel_id}}),
            ts=_now_iso()))
    settled += close_by_observation(ledger, announced)
    if settled:
        loop_store.write(project.name, settled)
        # The in-memory view must include what was just settled, or the chase pass below reads the
        # PRE-close ledger and reminds somebody about a question this very round resolved — a
        # message that tells the reader, precisely, that the agent is not paying attention.
        ledger = ledger + settled

    # 3. ASK what is new, at the person who can answer.
    ts = _now_iso()
    fresh = followup.to_open(
        followup.questions_from(report.observations, module._board_tickets or [],
                                language=lang),
        open_now, ts=ts)
    if fresh:
        # ONE message for the whole batch (see ask_batch): three separate posts, each repeating
        # the same closing paragraph, is what actually reached the client channel on 2026-07-28
        # — it reads as a machine emptying a queue rather than a colleague asking.
        # A dropped batch persists NO question rows: to_open dedupes against open QUESTION loops,
        # so a row for a never-delivered ask would suppress the question for ever.
        if not _product_post(channel, project, cfg, followup.ask_batch(
                [(loop, _mention(loop.context.get("person") or "")) for loop in fresh],
                agent_name=name, language=lang)):
            fresh = []

    # 4. CHASE what went quiet — ONCE. Two failure modes sit either side of this: a question that
    #    evaporates, and an agent that asks the same thing until somebody mutes the channel.
    ages = {(QUESTION, x.subject, x.about): _hours_since(x.ts)
            for x in open_now if x.kind == QUESTION}
    chased = chase_due(ledger, hours_open=ages, after_hours=followup.CHASE_AFTER_HOURS, ts=ts)
    # The chase pass wears the SAME cap as the ask pass, for the same reason. Thirteen questions
    # went out in one pre-cap burst (2026-07-28, the first real sweep); left uncapped, the 48h
    # chase would have replayed all thirteen as one burst of reminders a week later — the flood
    # arriving twice. The rest stay OPEN (not CHASED), so later passes take the next few.
    # A CHASED row is only written for a chase that LANDED — the one chase a question ever gets
    # must not be spent on a post nobody received; a dropped one stays OPEN for the next sweep.
    chased = [loop for loop in
              [x for x in chased if x.state == CHASED][:followup.MAX_QUESTIONS_PER_PASS]
              if _product_post(channel, project, cfg, followup.chase_text(
                  loop, mention=_mention(loop.context.get("person") or ""), agent_name=name,
                  days=max(2, int(_hours_since(loop.ts) // 24)), language=lang))]

    # 5. CHASE an unanswered "did it work?" — once, and never close it by time. Silence is not
    #    acceptance; an acceptance loop left open is the honest record of a delivery nobody
    #    confirmed, and it is supposed to stay visible until a person answers.
    acc_open = [x for x in waiting(ledger, owner=followup.OWNER) if x.kind == ACCEPTANCE]
    acc_ages = {(ACCEPTANCE, x.subject, x.about): _hours_since(x.ts) for x in acc_open}
    acc_chased = [loop for loop in
                  [x for x in chase_due(ledger, hours_open=acc_ages,
                                        after_hours=followup.ACCEPTANCE_AFTER_HOURS, ts=ts)
                   if x.state == CHASED and x.kind == ACCEPTANCE][:followup.MAX_QUESTIONS_PER_PASS]
                  if _product_post(channel, project, cfg, followup.acceptance_chase_text(
                      loop, mention=_mention(loop.context.get("asked_by") or ""),
                      agent_name=name))]

    # 6. CHASE a decision nobody made — once, and never closed by time. A decision she asked for
    #    and nobody answered is the most expensive thing to lose silently: work either stops or
    #    proceeds on an assumption nobody agreed to.
    dec_open = [x for x in waiting(ledger, owner=followup.OWNER) if x.kind == DECISION]
    dec_ages = {(DECISION, x.subject, x.about): _hours_since(x.ts) for x in dec_open}
    dec_chased = [loop for loop in
                  [x for x in chase_due(ledger, hours_open=dec_ages,
                                        after_hours=followup.DECISION_AFTER_HOURS, ts=ts)
                   if x.state == CHASED and x.kind == DECISION][:followup.MAX_QUESTIONS_PER_PASS]
                  if _product_post(channel, project, cfg, followup.decision_chase_text(
                      loop, mention=_mention(loop.context.get("person") or ""),
                      agent_name=name, language=lang))]

    # 7. LAND any proposal that is not in the base yet (ADR-0032) — also run on the HOURLY
    #    tech-lead rounds (see techlead_watch), because this failure is client-visible within one
    #    message while this sweep's cadence is a week.
    _land_product_proposals(project, token=module.token or "")

    loop_store.write(project.name, fresh + chased + accepting + acc_chased + dec_chased)
    return (f"asked:{len(fresh)} chased:{len(chased)} closed:{len(settled)} "
            f"accepting:{len(accepting)}")


def _land_product_proposals(project, *, token: str | None = None) -> list[str]:
    """Get every `req/*` proposal branch INTO the docs base (ADR-0032 recovery). Never raises.

    An unmerged proposal is client-visible within ONE message — the role denies its own
    requirement ("não encontrei o requisito N") until the branch lands — so this repair cannot
    ride only the weekly product sweep: that left up to seven days of denial, and none at all
    while the board was unreadable (the sweep skips follow-through entirely then). It runs on the
    HOURLY tech-lead rounds too, deliberately decoupled from both the board read and the sweep."""
    cfg = getattr(project, "product", None)
    if cfg is None or not getattr(cfg, "enabled", True) or not getattr(cfg, "docs_repo", ""):
        return []
    try:
        from openfactory.product.authoring import land_open_proposals
        from openfactory.product.module import ProductModule

        rescued = land_open_proposals(
            docs_repo=cfg.docs_repo,
            token=token if token is not None else (ProductModule(project).token or ""),
            base=getattr(cfg, "docs_branch", "main"))
        if rescued:
            activity.logger.warning("OPENFACTORY_PRODUCT_PROPOSAL_RESCUE project=%s landed %s "
                                    "proposal(s) into the base: %s",
                                    getattr(project, "name", ""), len(rescued),
                                    ", ".join(rescued))
        return rescued
    except Exception as exc:  # noqa: BLE001 — a rescue never breaks the round it rides on
        # A rotated token, a renamed docs repo or a worker image without `gh` makes this raise on
        # EVERY hourly round, and the client meets the failure inside one message: the role denies
        # its own requirement. Unnamed and uncaused, that is one warning an hour that nobody can
        # act on and no alert can be built from — the same silence the orphan repair below already
        # had to be taught out of.
        activity.logger.error("OPENFACTORY_PRODUCT_PROPOSAL_LAND_FAILED project=%s (%s) — open "
                              "proposals "
                              "are not in the base, so the role denies requirements it wrote",
                              getattr(project, "name", ""), exc, exc_info=True)
        return []


#: How many facts one memory row carries before the rest are dropped. A row is one DynamoDB item;
#: unbounded it eventually exceeds the item limit, the write starts failing, and a memory that
#: cannot be written is a client who hears the same announcement every hour. It bounds ONE round's
#: delta, not the memory — dropping is loud (see `_remember_repoint`) because a dropped fact is a
#: repair nobody will ever be told about.
_REPOINT_MEMORY_LIMIT = 500


def _repoint_facts(raw) -> list[tuple[str, int | None]]:
    """`card:requirement` pairs out of one stored field.

    A bare `510` is the FIRST shape this memory was written in, when the card alone was the key.
    Rows in that shape exist in the live table, and the requirement such an entry was announced at
    is the one the same row recorded as repaired — so the caller resolves it there rather than
    dropping it, which would re-announce a repair the client already heard about.

    THE CARD IS THE PROVIDER'S OWN STRING (C-05). It was `int(card)` behind an `.isdigit()` filter,
    so a `CONT-412` board's every fact was skipped on read AND could never be written — the memory
    was structurally empty on any tracker that does not number its tickets, and a memory that is
    always empty announces every repair for ever. Rows already in the live table are numeric and
    read back as `"510"`, which is exactly what `Ticket.number` carries for the same card, so the
    shapes meet without a migration."""
    out: list[tuple[str, int | None]] = []
    for part in str(raw or "").split("|"):
        card, _, requirement = part.partition(":")
        if not card.strip():
            continue
        out.append((card.strip(), int(requirement) if requirement.strip().isdigit() else None))
    return out


def _repoint_memory(project_name: str) -> tuple[dict[str, int], set[tuple[str, int]]]:
    """`{card: the requirement it now cites}` for every repair made, and every `(card, requirement)`
    the client has actually been told about.

    TWO FACTS, NOT ONE, and the whole point is that they can disagree: the repair is observed from
    the board write, the announcement only from the channel confirming the post. Collapsed into a
    single "done" flag, a repair whose message was dropped is either announced twice or never — and
    never is the one that ships silently, because the repair is idempotent and the second run finds
    nothing left to notice.

    THE PAIR IS THE KEY, NOT THE CARD. Supersession recurs — this client's chain already runs
    0002→0004→0006, three replacements in one day — so a card being repointed a SECOND time is the
    ordinary course of things, not an edge. Keyed by the card alone, that second repair counts as
    already announced the moment it is made: thirteen cards move onto a promise the client has never
    heard named, carrying criteria written against a text two supersessions old, and the paragraph
    that is the whole point of the message is never said.

    EVERY ROW, NOT THE NEWEST. A row is a DELTA of what one round learned and the memory is their
    union. `scan_records` swallows its own failures and returns `[]`, so an unreadable table is
    indistinguishable here from an empty one; read as a snapshot, the next round's write would
    REPLACE a row recording repairs the client was never told about — and nothing could rediscover
    them, the cards having stopped being orphans the moment they were repaired. Accumulated, a read
    that came back empty costs a round's delay and at worst one repeated sentence, never a fact.
    """
    repaired: dict[str, int] = {}
    announced: set[tuple[str, int]] = set()
    try:
        from openfactory.api.metrics_view import scan_records

        rows = [r for r in scan_records()
                if r.get("kind") == _WATCH_KIND
                and str(r.get("role") or "") == _REPOINT_ROLE
                and str(r.get("pk") or r.get("project") or "") == project_name]
        rows.sort(key=lambda r: str(r.get("ts") or ""))
        for row in rows:
            extra = row.get("extra") or {}
            # oldest → newest, so the citation in force is the LAST repair recorded for that card
            here = {c: r for c, r in _repoint_facts(extra.get("repaired")) if r is not None}
            repaired.update(here)
            for card, requirement in _repoint_facts(extra.get("announced")):
                resolved = requirement if requirement is not None else here.get(card)
                if resolved is not None:
                    announced.add((card, resolved))
        return repaired, announced
    except Exception as exc:  # noqa: BLE001
        # Forgetting here is not silence: the repair still runs (it is idempotent), the rows stay
        # where they are, and the client is told again or told next hour. Repeating an announcement
        # is the harmless side of this failure, which is why it is the side it falls on — and it is
        # only harmless because the write below never replaces what this read could not see.
        activity.logger.warning("OPENFACTORY_PRODUCT_ORPHANS_MEMORY_UNREAD project=%s (%s) — the "
                                "client "
                                "may hear about one of these repairs twice", project_name, exc)
        return repaired, announced


def _UNSTORABLE(ref: str) -> bool:
    """Whether a ref cannot survive this memory's `card:req|card:req` encoding."""
    return "|" in str(ref) or ":" in str(ref)


def _remember_repoint(project_name: str, repaired: dict[str, int],
                      announced: set[tuple[str, int]]) -> None:
    """Append what THIS round learned. One row is a delta; `_repoint_memory` unions them.

    DELTAS, NOT A SNAPSHOT, because a snapshot row supersedes the memory: a round whose read came
    back empty for any reason would erase repairs nobody has been told about, and a repaired card is
    no longer an orphan for a later round to rediscover. This one's facts exist nowhere else once
    the board is repaired, so the row is the only copy.

    WHICH IS NOT A LICENCE FOR THE SIBLINGS TO SNAPSHOT. `_watch_history` and `_last_sweep_keys`
    hold facts that ARE re-derived from live state every round, so a lost row there costs a
    repetition — but the row `_last_sweep_keys` reads is also the only record that this role has
    already introduced itself to this client, and that fact is derived from nothing at all. What
    makes a memory safe to lose is never the mechanism; it is what the round does with the answer,
    and the arrival is guarded where that decision is made (see `_sweep_history`)."""
    if not repaired and not announced:
        return
    try:
        from datetime import UTC, datetime

        from openfactory.observability.metrics import MetricRecord

        # A REF THAT WOULD CORRUPT THE ROW IS DROPPED LOUDLY, not written. `|` and `:` are this
        # field's own punctuation, and a provider free to issue arbitrary strings may put either in
        # a ticket id — one such ref would not merely lose itself, it would split into two
        # unrecognisable facts and desynchronise the whole memory.
        illegal = sorted({c for c in repaired if _UNSTORABLE(c)}
                         | {c for c, _ in announced if _UNSTORABLE(c)}, key=ref_sort_key)
        if illegal:
            activity.logger.error("OPENFACTORY_PRODUCT_ORPHANS_MEMORY_UNSTORABLE project=%s "
                                  "cards=%s — these refs carry this memory's own separators, so "
                                  "they cannot be remembered and will be announced again",
                                  project_name, ",".join(ref_label(c) for c in illegal))
        repaired = {c: r for c, r in repaired.items() if not _UNSTORABLE(c)}
        announced = {(c, r) for c, r in announced if not _UNSTORABLE(c)}
        if not repaired and not announced:
            return
        kept_repaired = dict(sorted(repaired.items(),
                                    key=lambda kv: ref_sort_key(kv[0]))[:_REPOINT_MEMORY_LIMIT])
        kept_announced = sorted(announced,
                                key=lambda pair: ref_sort_key(pair[0]))[:_REPOINT_MEMORY_LIMIT]
        dropped = (len(repaired) - len(kept_repaired)) + (len(announced) - len(kept_announced))
        if dropped:
            activity.logger.error("OPENFACTORY_PRODUCT_ORPHANS_MEMORY_FULL project=%s dropped=%d "
                                  "fact(s) "
                                  "— those cards were repaired and nobody will be told",
                                  project_name, dropped)
        extra = {}
        if kept_repaired:
            extra["repaired"] = "|".join(f"{c}:{r}" for c, r in kept_repaired.items())
        if kept_announced:
            extra["announced"] = "|".join(f"{c}:{r}" for c, r in kept_announced)
        _metrics_sink().record(MetricRecord(
            project=project_name, ticket=_REPOINT_ROLE, ts=datetime.now(UTC).isoformat(),
            kind=_WATCH_KIND, role=_REPOINT_ROLE, extra=extra))
    except Exception as exc:  # noqa: BLE001 — remembering is an optimisation, never the job
        activity.logger.warning("could not record the card repairs for %s (%s) — the next round "
                                "may announce them again", project_name, exc)


#: What the client hears when cards that cited a retired requirement were put back on the live one.
#: THE POINT OF THE MESSAGE is the second paragraph: the criteria on those cards were written
#: against a text that is no longer the promise, and the person who accepted the new promise is the
#: only one who can say whether they still want what those cards describe. Announcing the repair
#: without that is bookkeeping nobody needed to read.
#:
#: It names the requirement in force and the cards, and nothing else — the retired number, the
#: mapping and the writes are in the operator log, where somebody is paid to care about them.
_ORPHANS_REPOINTED = {
    "pt-BR": {
        "one": ("{head}Fiz um acerto por conta própria, e vocês precisam saber antes de qualquer "
                "trabalho começar: uma frente ainda se apoiava num texto anterior, que já não "
                "vale — passou a se apoiar no requisito {new}, que é a promessa em vigor "
                "({cards}).\n\nO que ela diz que precisa ser verdade para dar por pronta continua "
                "escrito como estava, do tempo do texto anterior. Não mexi nisso de propósito: "
                "mudaria o que vai ser construído, e isso é decisão de vocês. Se já não fizer "
                "sentido do jeito que está, é só dizer."),
        "many": ("{head}Fiz um acerto por conta própria, e vocês precisam saber antes de qualquer "
                 "trabalho começar: {n} frentes ainda se apoiavam num texto anterior, que já não "
                 "vale — passaram a se apoiar no requisito {new}, que é a promessa em vigor "
                 "({cards}).\n\nO que cada uma delas diz que precisa ser verdade para dar por "
                 "pronta continua escrito como estava, do tempo do texto anterior. Não mexi nisso "
                 "de propósito: mudaria o que vai ser construído, e isso é decisão de vocês. Se "
                 "alguma já não fizer sentido do jeito que está, é só dizer."),
    },
    "en": {
        "one": ("{head}I made a correction on my own, and you should know before any work starts: "
                "one piece of work still rested on an earlier text that no longer holds — it now "
                "rests on requirement {new}, which is what we promise today ({cards}).\n\n"
                "What it says has to be true before we call it done is still written the way it "
                "was, from back when the text was the other one. I left that alone on purpose: "
                "rewriting it would change what gets built, and that is your call. If it no "
                "longer makes sense as it stands, just say so."),
        "many": ("{head}I made a correction on my own, and you should know before any work "
                 "starts: {n} pieces of work still rested on an earlier text that no longer "
                 "holds — they now rest on requirement {new}, which is what we promise today "
                 "({cards}).\n\nWhat each of them says has to be true before we call it done is "
                 "still written the way it was, from back when the text was the other one. I "
                 "left that alone on purpose: rewriting it would change what gets built, and "
                 "that is your call. If any of them no longer makes sense as it stands, just "
                 "say so."),
    },
}


def _card_ref(ref: str) -> str:
    """The card a `WriteResult` is about, from the `#510` its writer put in `ref`. `""` when the
    result names nothing — which pairs with no orphan, so an unnamed write is never announced.

    THE PROVIDER'S OWN STRING (C-05), and this used to reduce it to the digits it contained. That
    was not merely wrong for a `CONT-412` board, which it silently dropped: the cards it produced
    were INTS and the orphans it was matched against are `Ticket.number`, which is a `str`. So
    `card in written` compared a string to a set of integers and was FALSE on every board, on every
    vendor — the repair ran, and every round reported "clean" and blamed a race that had not
    happened. Measured before this line changed: two cards repaired, nothing remembered, nothing
    said, `OPENFACTORY_PRODUCT_ORPHANS_UNPAIRED` logged about a window that never opened."""
    return str(ref or "").strip().lstrip("#").strip()


def _repointed_text(cards: list[str], requirement: int, *,
                    language: str | None, agent_name: str) -> str:
    """The sentence for ONE requirement in force, and the cards that now rest on it.

    Both templates say "a promessa em vigor" in the singular because that is what is true of any one
    card. A round that repairs two retired chains — ordinary, since chains are independent and the
    debt also accumulates across rounds whose post was dropped — earns two sentences, not a list of
    numbers glued into a sentence written for one. Taking the requirement as an argument is what
    makes the plural unwritable rather than merely unwritten."""
    from openfactory.product.voice import DEFAULT_LANGUAGE

    lang = (language or DEFAULT_LANGUAGE).strip()
    table = _ORPHANS_REPOINTED.get(lang) or _ORPHANS_REPOINTED[DEFAULT_LANGUAGE]
    # SORTED AS REFS AND RENDERED AS THE PROVIDER WRITES THEM (C-05). `sorted` on strings puts
    # "#10" before "#9", and `f"#{c}"` turns a Jira `CONT-412` into `#CONT-412` — punctuation
    # nobody on that board uses and a ref a reader cannot paste back.
    ordered = sorted(cards, key=ref_sort_key)
    return table["one" if len(ordered) == 1 else "many"].format(
        head=f"{agent_name}: " if agent_name.strip() else "",
        n=len(ordered),
        new=requirement,
        cards=", ".join(ref_label(c) for c in ordered))


async def _offer_the_release_to_the_client(project, client) -> str:
    """Ask the client to try what is parked waiting to go live — the staging bridge (board #6).

    THE CADENCE IS THE POINT. The weekly product sweep is where every other follow-up lives; this
    one cannot be there, because a parked release HOLDS THE PIPELINE. The change is built, staging
    is green, and nothing moves until somebody looks — so a week of silence is a week of a factory
    that finished and did not ship, which is exactly the stall this platform exists to make
    impossible. Hourly, on the tech-lead's rounds, beside the other two repairs that earned the
    same argument.

    IT RUNS HERE AND POSTS THERE. The tech-lead's round is where the live workflows are already
    listed, so asking costs no second Temporal sweep — but the message goes to the PRODUCT channel
    through the one seam that reaches it. The two surfaces stay apart (ADR-0026); only the code
    that observes is shared.

    OPENED ONLY IF THE ASK LANDED, the rule the delivery announcement already learned the hard way:
    a loop recorded for a post nobody received turns the 20h chase into the client's first-ever
    message about the release — a reminder about something they were never told.
    """
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import waiting
    from openfactory.product import followup, release

    cfg = getattr(project, "product", None)
    if cfg is None or not getattr(cfg, "enabled", True) \
            or not channel_destination(project, cfg.channel_id or ""):
        return ""     # no client to ask; the panel's operator path is untouched and still works
    try:
        pending = await release.parked_for_release(client, project.name)
    except Exception as exc:  # noqa: BLE001 — a round must not die because Temporal blinked
        activity.logger.info("release watch: could not list parked jobs (%s)", exc)
        return ""
    if not pending:
        return ""     # silent when there is nothing to ask — the expected case almost every hour

    from openfactory.adapters.channel import build_channel

    channel = build_channel(project)
    ledger = await asyncio.to_thread(loop_store.read, project.name)
    open_now = waiting(ledger, owner=followup.OWNER)
    # ALREADY ASKED IS NOT ASK AGAIN. Without this the same release is announced every hour until
    # somebody answers — the fastest way to teach a client to mute the channel that is trying to
    # give them a release button.
    asked = {followup.is_release(x) for x in open_now}
    name = getattr(cfg, "agent_name", "") or ""
    # THE DEPRECATED FALLBACK. `staging_url` is one string on the DEPLOYMENT's registry, with no
    # command that writes it and no way to name more than one stage; the manifest declares an
    # address per environment and the job carries the answer back from the box that read it
    # (#122). Kept working for deployments that already set it, and said out loud when it is what
    # ends up being used, because a value nobody can find is a value nobody can correct.
    fallback = str(getattr(cfg, "staging_url", "") or "")
    opened = []
    for issue, declared in pending:
        if str(issue) in asked:
            continue
        where = declared or fallback
        if not declared and fallback:
            activity.logger.info(
                "%s#%s has no `url:` in its manifest — falling back to the deployment's "
                "`staging_url`, which is deprecated", project.name, issue)
        text = followup.release_question(
            requirement=followup.requirement_behind(issue, open_now),
            where=where, agent_name=name,
            language=getattr(project, "language", None))
        if not await asyncio.to_thread(_product_post, channel, project, cfg, text):
            continue
        opened.append(followup.release_of(issue, channel=cfg.channel_id, ts=_now_iso(),
                                          requirement=followup.requirement_behind(issue, open_now),
                                          where=where))
    if opened:
        await asyncio.to_thread(loop_store.write, project.name, opened)
        activity.logger.warning(
            "OPENFACTORY_RELEASE_OFFERED project=%s issues=%s — the client was asked to try it; "
            "their "
            "answer is what releases", project.name, [x.subject for x in opened])
    return f"release-asked:{len(opened)}"


def _repoint_product_orphans(project) -> str:
    """Cards left citing a requirement that is no longer live, put back on the one that replaced
    it — and the client told, once, that it happened. Never raises.

    HOURLY, ON THE TECH-LEAD'S ROUNDS, not on the weekly product sweep, and the cadence is chosen
    by blast radius: a card citing a retired text is something the floor can start building against
    within the hour, under a printed rule telling the agent not to go beyond that requirement. A
    weekly healer repairs the citation after the work was already built against the wrong promise.
    Same round, same argument, as the proposal rescue above — and, like it, deliberately upstream of
    Temporal and of the floor queries, so a Temporal outage cannot also stop this.

    SILENT WHEN THERE IS NOTHING TO REPAIR: no post, no log line, no board write, no channel built.
    A repair that reports every hour is wallpaper by the second day, and this one is expected to
    find nothing almost every time it runs.

    THE READ-ONLY QUESTION IS ASKED FIRST. `orphaned_cards` is deterministic and costs no model
    call; `repoint_orphans` writes. Gating on the query is what makes the quiet path provably free
    of writes, and it is also the only place the successor number is available — a WriteResult does
    not carry it and the client's sentence is about nothing else.

    THE REPAIR IS GATED ON THE BOARD, THE ANNOUNCEMENT ON THE CHANNEL. Gating both on the channel
    left a project with a docs repo and a board but no product channel citing a retired text for
    ever, and saying nothing about it — the floor still builds from those cards. What a project
    without somebody to tell loses is the message, not the repair; the debt is kept, so a channel
    configured later still hears it.
    """
    cfg = getattr(project, "product", None)
    if cfg is None or not getattr(cfg, "enabled", True) or not getattr(cfg, "docs_repo", ""):
        return "off"
    name = getattr(project, "name", "")
    try:
        from openfactory.product.module import ProductModule

        module = ProductModule(project)
        orphans = module.orphaned_cards()
        repaired, announced = _repoint_memory(name)

        done = 0
        refused = 0
        if orphans:
            # NO ACTOR: nobody asked for this. Re-pointing a citation is bookkeeping the platform
            # owes, and putting a person's id on it would attribute a write to someone who never
            # made it — the same lie in the opposite direction from the writes that need one.
            #
            # THIS IS THE UNGATED WRITE, and it is the only one this factory makes into a client's
            # board with no human anywhere. The exemption to "nothing irreversible without a yes"
            # is declared beside the rule it departs from — the AUTHORITY block of
            # `openfactory/product/module.py` — together with the boundary that makes it safe: it
            # changes
            # which requirement a card CITES and nothing else. Nothing here may hand it a card or a
            # requirement; the moment a caller chooses the target, the argument above stops holding.
            results = module.repoint_orphans()
            # PAIRED BY THE CARD EACH RESULT NAMES, never by position. There is one result per card
            # WRITTEN, and a card whose citation already read correctly is skipped without one — so
            # the two lists are different lengths and a positional pair would name the wrong cards
            # to the client while leaving the repaired ones unannounced for ever.
            written = {_card_ref(getattr(r, "ref", "")) for r in results
                       if getattr(r, "ok", False)} - {""}
            fresh = {card: successor for (card, _cited, successor) in orphans
                     if card in written}
            refusals = [r for r in results if not getattr(r, "ok", False)]
            refused = len(refusals)
            # COUNTED FROM THE WRITES, NAMED WHERE THEY CAN BE: a refusal whose result names no
            # card must still be reported, or the one shape of this failure that carries no label
            # is also the one that passes in silence.
            named = sorted({_card_ref(getattr(r, "ref", "")) for r in refusals} - {""},
                           key=ref_sort_key)
            if refusals:
                # A ROUND THAT REPAIRED NOTHING IS NOT A CLEAN BOARD, and nothing else here would
                # say so: with every write refused there is no repair to log, no fact to remember
                # and no sentence to send, so the whole round used to pass in silence and report
                # itself clean. Every one of these writes goes through ONE credential to ONE
                # repository, which is why the ordinary shape of this failure is all of them at
                # once — an exhausted quota, a rotated token, a permission removed — repeating
                # hourly while the floor is free to pick up any of these cards and build against a
                # promise nobody holds. The per-card cause is on the product logger; what was
                # missing here is that it happened at all.
                activity.logger.error(
                    "OPENFACTORY_PRODUCT_ORPHANS_REFUSED project=%s refused=%d of=%d cards=%s "
                    "— the "
                    ""
                    "board "
                    "would not take the repair, so they still cite a requirement that was retired",
                    name, refused, len(orphans),
                    ",".join(ref_label(c) for c in named) or "unnamed")
            unpaired = sorted(written - set(fresh), key=ref_sort_key)
            if unpaired:
                # The board is asked once and written once, and it changes in between: a card whose
                # citation is edited onto the retired text inside that window is repaired without
                # this round ever seeing which requirement it moved onto, and it is not an orphan
                # for the next round to find. The sentence cannot be written truthfully, so the
                # write is at least never silent. The window closes only where the write accepts the
                # list it was asked about — `repoint_orphans` takes none, and a WriteResult carries
                # no successor to recover it from here.
                activity.logger.error(
                    "OPENFACTORY_PRODUCT_ORPHANS_UNPAIRED project=%s cards=%s — repaired on the "
                    "board "
                    "after this round read it, so they are neither remembered nor announced",
                    name, ",".join(ref_label(c) for c in unpaired))
            if fresh:
                done = len(fresh)
                activity.logger.warning(
                    "OPENFACTORY_PRODUCT_ORPHANS_REPOINTED project=%s cards=%s now citing %s",
                    name, ",".join(ref_label(c) for c in sorted(fresh, key=ref_sort_key)),
                    ",".join(f"REQ-{r}" for r in sorted(set(fresh.values()))))
                repaired.update(fresh)
                # PERSISTED BEFORE THE POST, because the board write already happened. Recorded
                # after it, a dropped announcement would leave a repair nothing owes a message for
                # — and the next round cannot rediscover it, the cards having stopped being orphans
                # the moment they were repaired.
                _remember_repoint(name, fresh, set())

        # "clean" IS A CLAIM ABOUT THE BOARD, so it is only ever said by a round that has one:
        # every refusal is carried into the report, or an hourly repair that achieves nothing reads
        # exactly like an hourly repair that had nothing to do.
        parts: list[str] = []
        if done:
            parts.append(f"repointed:{done}")
        if refused:
            parts.append(f"refused:{refused}")

        owed = {card: req for card, req in repaired.items() if (card, req) not in announced}
        if not owed:
            return " ".join(parts) or "clean"

        if not (cfg.channel_id or ""):
            # Only when something was repaired THIS round: owed survives every round until there is
            # somebody to say it to, and an hourly line about a standing debt is the wallpaper this
            # repair is written not to produce.
            if done:
                activity.logger.warning(
                    "OPENFACTORY_PRODUCT_ORPHANS_UNANNOUNCED project=%s cards=%s — this "
                    "project has "
                    ""
                    "no "
                    "product channel, so nobody was told the promise under them changed",
                    name, ",".join(ref_label(c) for c in sorted(owed, key=ref_sort_key)))
            return " ".join([*parts, f"unannounced:{len(owed)}"])

        from openfactory.adapters.channel import build_channel

        channel = build_channel(project)
        said: set[tuple[str, int]] = set()
        dropped = 0
        # ONE MESSAGE PER REQUIREMENT IN FORCE, so each sentence is true of every card it names.
        for requirement in sorted(set(owed.values())):
            cards = sorted((card for card, req in owed.items() if req == requirement),
                           key=ref_sort_key)
            if _product_post(channel, project, cfg, _repointed_text(
                    cards, requirement, language=getattr(project, "language", None),
                    agent_name=getattr(cfg, "agent_name", "") or "")):
                said |= {(card, requirement) for card in cards}
            else:
                dropped += len(cards)
        if said:
            _remember_repoint(name, {}, said)
            parts.append(f"announced:{len(said)}")
        if dropped:
            parts.append(f"announce-dropped:{dropped}")
        return " ".join(parts)
    except Exception as exc:  # noqa: BLE001 — a repair must never break the round it rides on
        # A build_channel or a registry entry that raises makes this dead EVERY hour, with cards
        # citing a retired requirement the whole time. Without the cause and a marker to alert on,
        # that is one unattributable warning an hour and nothing anybody can act on.
        activity.logger.error("OPENFACTORY_PRODUCT_ORPHANS_FAILED project=%s (%s) — cards "
                              "may still "
                              ""
                              "cite "
                              "a requirement that was retired", name, exc, exc_info=True)
        return "error"


def _finding_reminders(project_name: str, ledger: list, language: str = "") -> list:
    """Open review findings, as findings the round will report — chased once, then left visible.

    A loop that opens and nothing ever closes is the failure this whole module warns about, so the
    close here is an explicit human `ack #N` rather than an invented observation: a merged ticket
    carrying a critical review has no state change left to watch.

    `language` IS PASSED IN (#160): `report()` renders `detail` and `action` verbatim, so a
    finding composed here in one language survives the whole trip to the channel. Every other
    finding in that same list already came from `watch()`, which is localized — so a round could
    print four sentences in the project's language and this one in Portuguese."""
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import CHASED, FINDING, chase_due, waiting
    from openfactory.techlead import voice as tl_voice
    from openfactory.techlead.watch import STUCK, Finding

    open_findings = waiting(ledger, kind=FINDING, owner=OWNER)
    if not open_findings:
        return []
    ages = {(FINDING, x.subject, x.about): _hours_since(x.ts) for x in open_findings}
    chased = chase_due(ledger, hours_open=ages, after_hours=24.0, ts=_now_iso())
    chased = [x for x in chased if x.kind == FINDING and x.state == CHASED]
    if chased:
        loop_store.write(project_name, chased)
    return [
        Finding(
            # The subject verbatim (#69). `int(...) if isdigit() else None` dropped the ticket
            # entirely for a Jira/ADO ref, and `report()` renders `*#{ticket}*` only when it is
            # truthy — so the reminder lost the one number it was about, while the very next line
            # still told somebody to reply `ack CONT-412`.
            kind=STUCK, ticket=str(loop.subject) or None,
            resumable=False, progress=_hours_since(loop.ts),
            detail=tl_voice.say(tl_voice.NARRATION, "finding.unacked.detail", language,
                                detail=(loop.context or {}).get("detail", "")[:160]),
            action=tl_voice.say(tl_voice.NARRATION, "finding.unacked.action", language,
                                ticket=loop.subject),
        )
        for loop in chased
    ]


def _closed_issue_numbers(module) -> set[str]:
    """Which of the board's tickets were actually DELIVERED. Read from what the sweep already
    fetched — a second board read for this would spend the same GitHub quota twice for one number.

    CLOSED IS NOT DELIVERED. The previous rule was `state != "open"`, so an issue closed as a
    duplicate or as `not_planned` counted as delivery and the client was told "o que foi pedido no
    requisito N está pronto" about work that was cancelled. On 2026-07-29 eleven cards were closed
    as not_planned in one sitting — the failure was one sweep away.

    `not_planned` is excluded by NAME rather than `completed` being required, deliberately: a
    tracker that reports no reason at all (or a provider with no such concept) then still delivers,
    which is the behaviour every existing deployment had. Requiring the positive signal would
    silently stop announcing real deliveries the day a tracker omitted the field — trading a false
    delivery for a lost one.
    """
    # THE PREDICATE MOVED TO `Ticket.delivered` (product/triage.py), where `state_reason` already
    # lives, so the conversational surface reads the SAME rule instead of having none. The argument
    # above is preserved verbatim there; this is now the one caller that filters a set by it.
    return {t.number for t in (module._board_tickets or []) if t.delivered}


def _hours_since(iso: str) -> float:
    from datetime import UTC, datetime

    try:
        then = datetime.fromisoformat(iso)
        if then.tzinfo is None:
            then = then.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - then).total_seconds() / 3600.0)
    except (ValueError, TypeError):
        # An unreadable timestamp must never make something look old enough to chase — that would
        # ping somebody about a question asked a minute ago.
        activity.logger.info("could not read when a loop opened (%r) — not chasing it", iso)
        return 0.0


@activity.defn
async def techlead_watch(project_name: str) -> str:
    """The tech-lead's rounds (ADR-0020 §3): look at the floor, say what is stuck, resume what the
    factory already knows how to fix.

    Reads the live workflows rather than a stored snapshot, because the question is what is
    happening NOW — and a park that nobody answered is invisible to every other path here: no event
    fires again after the one that created it.

    Silent when there is nothing to say. A watcher that reports "all fine" every hour is one nobody
    reads on the hour that matters."""
    from datetime import UTC, datetime

    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import (
        REMEDY,
        close_by_observation,
        open_loop,
        reassert_waiting,
        waiting,
    )
    from openfactory.runtime.temporal import view as tv_view
    from openfactory.runtime.temporal.connection import connect
    from openfactory.runtime.temporal.view import parse_job_id as tv_parse_job_id
    from openfactory.techlead.classify import classify, remedy_for
    from openfactory.techlead.memory import learn_from, remedy_verdicts, temper
    from openfactory.techlead.memory import signature as mem_signature
    from openfactory.techlead.watch import (
        RESUME_FAILED,
        RESUMED,
        AtAGate,
        FloorState,
        Parked,
        report,
        watch,
        worth_saying,
    )

    try:
        project = ProjectRegistry().get(project_name)
    except Exception as exc:  # noqa: BLE001
        # A schedule exists for a project the registry cannot resolve: the rounds will return
        # "no-project" every hour, for ever, and look exactly like a quiet floor.
        activity.logger.error("techlead watch: project %r is not in the registry (%s) — these "
                              "rounds do nothing and nobody is watching that floor",
                              project_name, exc)
        return "no-project"

    # ADR-0032 recovery on the HOURLY cadence, BEFORE anything that can fail this round (the
    # Temporal read, the floor queries): an unmerged proposal makes the product role deny its own
    # requirement within one client message, and the weekly sweep was its only healer.
    await asyncio.to_thread(_land_product_proposals, project)

    # Cards still citing a requirement that was replaced, before the floor can pick one up and
    # build against a promise nobody holds any more. Same position and the same reason: upstream of
    # everything that can fail this round.
    await asyncio.to_thread(_repoint_product_orphans, project)

    client = await connect()

    # The staging bridge (board #6), on this round because a parked release holds the pipeline and
    # the weekly sweep would let it hold it for a week. Best-effort and upstream of nothing: a
    # failure here must not cost the floor report, which is what this activity is for.
    try:
        await _offer_the_release_to_the_client(project, client)
    except Exception as exc:  # noqa: BLE001
        activity.logger.warning("could not offer the parked release to the client (%s)", exc)

    parked: list[Parked] = []
    long_running: list[tuple[str, float]] = []
    at_a_gate: list[AtAGate] = []
    running = 0
    #: tickets whose state we POSITIVELY observed this round: parked, or running-and-answering.
    #: A query that failed contributes nothing — for the memory pass below, "could not see" must
    #: never be readable as anything at all.
    observed_tickets: set[str] = set()
    now = datetime.now(UTC)

    #: EVERY registered project, not just this one — read ONCE, outside the loop.
    #:
    #: `parse_job_id` splits a workflow id on the known project names, LONGEST FIRST. Handing it
    #: only `[project_name]` would defeat the very guard it exists for: with `["acme"]` alone,
    #: `openfactory-acme-web-478` parses as project `acme`, ticket `web-478`, and this project's
    #: rounds
    #: would count — and RESUME — a sibling project's job. With both names present, `acme-web`
    #: matches first and the id is correctly not ours. A test asserts exactly this.
    known_projects = [p.name for p in ProjectRegistry().list()]

    async for wf in client.list_workflows(
        'WorkflowType = "JobWorkflow" AND ExecutionStatus = "Running"'
    ):
        # `parse_job_id` RATHER THAN A LOCAL REGEX (#69). The regex here was
        # `^openfactory-{project}-(\d+)$` — digits only — so on a Jira/ADO deployment (`CONT-412`)
        # it
        # matched no workflow at all and this whole subsystem went blind: `parked` stayed empty,
        # and since `_idle_minutes` derives idleness FROM `parked`, the idle-floor finding could
        # not fire either. The rounds returned "clean" every hour while the floor was held.
        #
        # The shared parser carries the very guard this regex's own comment cited as its reason to
        # exist — it splits on the REGISTERED project names, longest first, so
        # `openfactory-acme-web-478`
        # cannot be read as project `acme` (see `runtime/temporal/view.py`, whose round-trip
        # property is asserted in tests/test_non_numeric_refs_reach_the_api.py). Passing
        # `known_projects` explicitly keeps this pure of a registry read on a hot path.
        project_of, ticket = tv_parse_job_id(str(wf.id), known_projects=known_projects)
        if project_of != project_name or not ticket:
            continue
        running += 1
        try:
            handle = client.get_workflow_handle(wf.id)
            state = await handle.query("awaiting_action")
        except Exception as exc:  # noqa: BLE001 — a job that cannot answer is left alone
            # Counted as running, which is the safe side; but if every job stops answering, the
            # rounds see a busy floor and never report the parks holding it.
            activity.logger.info("techlead watch: %s did not answer (%s) — counted as running",
                                 wf.id, exc)
            continue
        observed_tickets.add(ticket)
        hours_running = (now - wf.start_time).total_seconds() / 3600 if wf.start_time else 0.0
        if not state:
            # A GATE ANSWERS EXACTLY LIKE A WEDGED JOB, and that cost the pilot the worst message
            # this platform has sent (2026-08-16). `awaiting_action` is the PARK query — the merge
            # gate and the production gate have their own, and `view.answer_merge_gate` says so in
            # as many words: *"THE MERGE GATE IS NOT A PARK … `awaiting_action` is None"*. So a
            # pull request waiting overnight for its author was counted as RUNNING, crossed
            # `LONG_RUNNING_HOURS`, and was announced as *"rodando há 10h sem parar nem terminar —
            # não consegui identificar a causa"*, with two verbs its gate does not accept, to the
            # person it was waiting for.
            #
            # ASKED FROM ONE LIST (`view.HUMAN_GATES`), so a gate added to the workflow cannot be
            # invisible here — a guard derives that list from the workflow's own queries.
            gate, payload = "", {}
            for query, name in tv_view.HUMAN_GATES.items():
                try:
                    answer = await handle.query(query)
                except Exception as exc:  # noqa: BLE001 — one unanswered gate is not a verdict
                    activity.logger.info("techlead watch: %s did not answer %s (%s)",
                                         wf.id, query, exc)
                    continue
                if answer:
                    gate = name
                    payload = answer if isinstance(answer, dict) else {}
                    break
            if gate == "merge" and payload.get("auto"):
                # ARMED AUTO-MERGE IS WAITING FOR A BUILD, NOT FOR A PERSON. It sits in the same
                # watch and answers the same query; without this line the round would tell somebody
                # *"o portão é de vocês"* about a job nobody can advance.
                gate = "ci"
            if gate:
                running -= 1  # waiting on a person is not work; it holds the floor without using it
                at_a_gate.append(AtAGate(
                    ticket=ticket, hours=hours_running, gate=gate,
                    deaf=tv_view.gate_cannot_hear(payload) if gate == "merge" else ""))
                continue
            # RUNNING AND ANSWERING, so not parked — but a job in a workflow-task failure loop
            # answers exactly like this, for ever, holding the single slot while counted as work.
            # Nothing else could see it: the idle finding requires `running == 0`.
            #
            # ASKED OF `view.is_wedged`, NOT RE-DERIVED (#164). That function is the rule — "a
            # function rather than an expression, because it is a rule and rules get tested" — and
            # this line reproduced two of its three conditions with the third (`action is None`)
            # standing in as the `if not state` above. Two derivations of one rule is how the Stop
            # button and the alarm come to disagree about the same job, which is the defect
            # `is_wedged` was extracted to end.
            if tv_view.is_wedged({"action": None, "start_time": wf.start_time}, live=True):
                long_running.append((ticket, hours_running))
            continue
        running -= 1  # parked is not running: it holds the floor without using it
        parked.append(Parked(ticket=ticket, hours=hours_running,
                             note=str(state.get("note") or ""),
                             kind=str(state.get("kind") or "impediment"),
                             attempts_spent=int(state.get("attempts_spent") or 0),
                             # WHEN THE ENGINE ITSELF WILL RESUME IT (#146). The park has carried
                             # this since #140 and the rounds never read it, so a job minutes from
                             # resuming on its own was announced to a client as needing a decision
                             # — while the panel, reading the same payload, said the opposite.
                             wakes_at=str(state.get("wakes_at") or "")))

    queued = await asyncio.to_thread(_queued_tickets, project)
    state = FloorState(parked=parked, running=running, queued=queued,
                       long_running=long_running, at_a_gate=at_a_gate,
                       idle_minutes=_idle_minutes(parked, running),
                       recent_causes=await asyncio.to_thread(_recent_causes, project_name))

    # ── MEMORY FIRST (ADR-0021). Before deciding anything, close what the world already resolved.
    #
    # ONLY POSITIVE EVIDENCE CLOSES. The first version closed by ABSENCE — "not parked right now"
    # was read as "worked" — and a reviewer built two damning counterexamples from it: a deploy
    # mid-round makes the query fail, the ticket drops out of the parked set, and a still-broken
    # remedy is credited a success; or the resume simply un-parks the job for the ninety minutes
    # its agent pass runs, the next round sees it "not parked", and every slow-recurring failure
    # books `worked` for ever. One false `worked` poisons `hopeless()` permanently — it requires
    # worked == 0 — so the factory would retry a useless remedy at full price, indefinitely,
    # each attempt looking like diligence. The same not-seen-equals-fixed disease was fixed on the
    # product board the same day. Verdicts now:
    #     parked, same signature            → did-not-work
    #     parked, same cause, new wording   → still PENDING (same disease, different rash —
    #                                         neither credit nor blame on a string drift)
    #     parked, different cause           → worked (that failure, at least, is gone)
    #     gone from the floor              → ask Temporal for the workflow's TERMINAL state
    #     running / unqueryable            → still PENDING; absence is not an outcome
    parked_now = {p.ticket: (mem_signature(p.note), classify(p.note).cause) for p in parked}
    ledger = await asyncio.to_thread(loop_store.read, project_name)
    open_remedies = waiting(ledger, kind=REMEDY, owner=OWNER)
    # end-states for tickets gone from the floor, prefetched so the DECISION is a pure function
    # a test can hold row by row (remedy_verdicts) instead of logic buried in this activity
    terminal: dict[str, str] = {}
    for loop in open_remedies:
        # `str(...)`, not `_as_int(...)`: the ledger already stores the subject as the provider's
        # own string, and the int conversion mapped every non-numeric ref to 0 — falsy, so the
        # `if ticket` below skipped it, `terminal` was never populated, and every open remedy on a
        # Jira deployment stayed PENDING for ever (#69).
        ticket = str(loop.subject)
        if ticket and ticket not in parked_now and ticket not in observed_tickets \
                and ticket not in terminal:
            terminal[ticket] = await _terminal_outcome(client, project_name, ticket)
    verdicts = remedy_verdicts(open_remedies, parked_now=parked_now,
                               observed=observed_tickets, terminal=terminal)
    settled = close_by_observation(ledger, verdicts)

    # Keep every still-waiting loop inside the store's read window (see reassert_waiting): an open
    # obligation that ages out of view evaporates without a close, a log, or an ack.
    still_open = reassert_waiting(ledger + settled)
    if settled or still_open:
        await asyncio.to_thread(loop_store.write, project_name, settled + still_open)
        ledger = ledger + settled
    history = learn_from(ledger)

    # THE PROJECT SPEAKS FIRST HERE — a scheduled round nobody asked for — so it is the
    # configured language, never a question's (#124).
    lang = str(getattr(project, "language", "") or "")
    findings = watch(state, language=lang)

    # Review findings nobody has acknowledged yet, due for their one reminder. Computed BEFORE the
    # clean-floor return below: the first version lived after it, which quietly made the reminder
    # conditional on the floor ALSO having some unrelated problem — a merged ticket carrying a
    # critical finding would only ever be chased on a day something else happened to break too.
    reminders = await asyncio.to_thread(_finding_reminders, project_name, ledger, lang)

    if not findings and not reminders:
        # Nothing wrong now, so nothing is being watched — and the memory has to be cleared, or a
        # problem that comes back later is suppressed by an entry from the last time it happened.
        await asyncio.to_thread(_remember_watch, project_name, {})
        return "clean"

    # ── ACT FIRST, on EVERY finding — deduplication governs speech, never remediation. The first
    # version tempered-then-resumed only what survived worth_saying, which coupled the factory's
    # one remedy to its politeness: a resume whose signal failed at 21h could not be retried until
    # the 6h repeat threshold let the finding be MENTIONED again. Whether to try again is the
    # memory's decision (temper/hopeless); how often to talk about it is the channel's.
    resumed = []
    outcomes: dict[str, str] = {}
    opened: list = []
    acted: list = []
    parked_tickets = {p.ticket for p in parked}
    for finding in findings:
        # ONLY A PARKED FINDING IS TEMPERED OR RESUMED (sweep B5, 2026-08-16). The classifier and
        # the memory reason over a PARK NOTE; for a wedged or gate-held job there is none, so this
        # loop classified the empty string — UNKNOWN cause — and OVERWROTE the crafted message
        # with escalation boilerplate offering `resume`/`skip`, two verbs the engine refuses for
        # a job that is not parked. That boilerplate is the exact text of the false 10h alarm the
        # pilot received about his own healthy pull request.
        if finding.ticket not in parked_tickets:
            continue
        # WHAT THE RECORD SAYS COMES FIRST. A remedy that has failed twice on this same failure
        # with no successes is not tried a third time — it is escalated, carrying what was learned.
        # This is the whole point of having a memory: it can only make the factory more cautious.
        sig = _sig_of(finding, parked)
        # temper() is the ONE integration point between history and a remedy — the same function
        # the tests exercise. An inline re-implementation here (which is what v1 did) is how the
        # tested behaviour and the shipped behaviour quietly stop being the same thing.
        verdict_now = classify(next((p.note for p in parked if p.ticket == finding.ticket), ""))
        spent = next((p.attempts_spent for p in parked if p.ticket == finding.ticket), 0)
        tempered = temper(
            remedy_for(verdict_now, already_spent=spent, language=lang), history.get(sig))
        if finding.resumable and tempered.action != "retry":
            finding.resumable = False
            finding.action = tempered.say or (tempered.reason +
                                              " — precisa de alguém olhando a causa")
        if not (finding.resumable and finding.ticket):
            continue
        # One open remedy per (ticket, signature) at a time: a resume already in flight from the
        # last round — its job still running its agent pass — must not be stacked with another.
        if any(str(x.subject) == finding.ticket and x.about == sig for x in open_remedies):
            continue
        try:
            handle = client.get_workflow_handle(f"openfactory-{project_name}-{finding.ticket}")
            # `args=[...]`, NOT two positionals. `WorkflowHandle.signal` is
            # `(signal, arg=UNSET, *, args=[])` — `args` is keyword-only, so a second value
            # passed positionally is a TypeError before anything reaches the server. This was
            # the bug: the tech-lead's ONE remediation, pressing resume, raised on every
            # attempt in every deployment, and the handler logged no exception, so the round
            # reported the impediment and looked like it had acted on it.
            await handle.signal("act_on_impediment", args=["resume", ""])
            resumed.append(finding.ticket)
            outcomes[finding.key] = RESUMED
            acted.append(finding)
            # Opened as PENDING, never as a success — a later round decides by looking. The
            # cause travels with it so "same disease, different wording" stays undecidable
            # instead of being miscredited as a cure.
            opened.append(open_loop(
                REMEDY, str(finding.ticket), owner=OWNER, about=sig, ts=_now_iso(),
                context={"note": finding.detail[:200],
                         "cause": next((c for t, (g, c) in parked_now.items()
                                        if t == finding.ticket), "")}))
        except Exception as exc:  # noqa: BLE001 — saying it still matters if the signal missed
            # WHY it failed is the whole message. "could not resume #478" told an operator
            # nothing they could act on, and hid a TypeError for as long as it existed.
            activity.logger.warning(
                "techlead watch: could not resume #%s (%s: %s) — the impediment stays parked "
                "and a person has to press it", finding.ticket, type(exc).__name__, exc)
            # The channel is told the truth: it tried, it could not, a person must.
            outcomes[finding.key] = RESUME_FAILED
            acted.append(finding)

    if opened:
        await asyncio.to_thread(loop_store.write, project_name, opened)

    # ── SPEECH. Deduplicate the unchanged findings; what was ACTED ON this round is always said
    # (a quiet action is indistinguishable from no action), and the ack reminders ride along —
    # never resumable, the ticket already merged; the only button left is a person's `ack`.
    said = await asyncio.to_thread(_watch_history, project_name)
    acted_keys = {f.key for f in acted}
    quiet = [f for f in findings if f.key not in acted_keys]
    to_say, remember = worth_saying(quiet, said)
    await asyncio.to_thread(_remember_watch, project_name, remember)
    to_say = acted + to_say + reminders
    if not to_say:
        return f"nothing-new resumed:{len(resumed)}"

    text = report(to_say, agent_name="Tech lead", outcomes=outcomes, language=lang)
    channel = channel_destination(project, project.channel_id or "")
    if channel:
        from openfactory.adapters.channel import build_channel

        await asyncio.to_thread(
            lambda: build_channel(project).say(project=project, channel=channel, text=text))
    return f"reported:{len(to_say)} resumed:{len(resumed)}"


@activity.defn
async def open_review_loop(inp: ReviewLoopInput) -> str:
    """Record that something shipped carrying a review the factory did not act on (ADR-0021).

    Opened, not closed: the tech-lead's next round chases it once, and it closes when a person
    acknowledges. The alternative — announcing it and moving on — is what happened to #478, where a
    critical finding was produced, was correct, and reached nobody."""
    def _do() -> str:
        from openfactory.memory import store as loop_store
        from openfactory.memory.ledger import FINDING, open_loop

        loop = open_loop(
            FINDING, str(inp.issue), owner=OWNER, about=inp.decision, ts=_now_iso(),
            context={"detail": inp.detail[:400], "score": str(inp.score), "pr": inp.pr_url},
        )
        written = loop_store.write(inp.project, [loop])
        return f"opened:{written}"

    return await asyncio.to_thread(_do)


async def _terminal_outcome(client, project_name: str, ticket: str) -> str:
    """What actually happened to a job that is no longer on the running floor — or "" if we
    cannot tell, in which case the remedy loop stays PENDING rather than guessing.

    This is the positive-evidence half of "the ticket moved on": COMPLETED means the resume
    genuinely carried the job home; FAILED or TIMED_OUT means it did not survive; a human
    terminating or cancelling is neither — the loop closes neutral (`abandoned`), which
    `learn()` counts as neither success nor failure, so it can never tip `hopeless()` either
    way."""
    from temporalio.client import WorkflowExecutionStatus

    from openfactory.techlead.memory import DID_NOT_WORK, WORKED

    try:
        desc = await client.get_workflow_handle(f"openfactory-{project_name}-{ticket}").describe()
    except Exception as exc:  # noqa: BLE001 — cannot see → no verdict; PENDING is the honest state
        activity.logger.info("techlead memory: could not learn how #%s ended (%s) — its remedy "
                             "stays pending", ticket, exc)
        return ""
    status = desc.status
    if status == WorkflowExecutionStatus.COMPLETED:
        return WORKED
    if status in (WorkflowExecutionStatus.FAILED, WorkflowExecutionStatus.TIMED_OUT):
        return DID_NOT_WORK
    if status in (WorkflowExecutionStatus.TERMINATED, WorkflowExecutionStatus.CANCELED):
        return "abandoned"
    return ""  # still RUNNING under another id shape, or CONTINUED_AS_NEW — no verdict


#: Who owns the loops this activity opens. A string rather than a role object: the ledger is read
#: by other passes, and an owner they can filter on has to survive a scan.
OWNER = "techlead"


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _sig_of(finding, parked: list) -> str:
    """The failure fingerprint behind a finding, so history is looked up on WHAT BROKE rather than
    on which ticket it broke. The same throttling on #478 and #503 must reach one history, or a
    recurring problem is remembered as unrelated one-offs and nothing is ever learned."""
    from openfactory.techlead.memory import signature

    for job in parked:
        if job.ticket == finding.ticket:
            return signature(job.note)
    return signature(finding.detail)


def _idle_minutes(parked: list, running: int) -> float:
    """How long the floor has had nothing moving. A parked job holds the floor but is not work, so
    a board full of parks reads as idle — which is exactly what it is."""
    if running:
        return 0.0
    return 60.0 * max((p.hours for p in parked), default=0.0)


def _queued_tickets(project) -> list[str]:
    """What is waiting in TO-DO — the other half of "the floor is idle and could be working".

    RETURNS STRINGS, converting at this boundary (#69). `readiness().todo` is still `list[int]`
    and stays that way here: that is `product/queue.py`, whose int-vs-ref classification is C-05's
    remaining scope and must not be changed as a side effect of this fix. The tech-lead subsystem
    speaks the provider's own ref end to end, so the conversion belongs at the seam between them
    rather than being smeared through either side.

    THE TOKEN IS NOT OPTIONAL. Called with none, `gh` runs unauthenticated and the read fails with
    "please run gh auth login"; the empty list that came back was indistinguishable from an empty
    TO-DO, so the tech-lead's idle-floor finding could never fire. It was observed in production
    doing exactly that. Resolved the same way `ProductModule.token` resolves it, and for the same
    reason: every real caller constructs this with nothing."""
    from openfactory.credentials import deployment_tracker_token, tracker_token_for
    from openfactory.product.board import read_board
    from openfactory.product.queue import readiness

    # THE TRACKER'S AXIS, because a board IS a tracker object — `product/board._credential` says so
    # in writing and this site asked the forge anyway. It survived because that function tries
    # `tracker_token_for` first and only consults the caller's token after, so the wrong axis was
    # a last resort rather than the first. On a deployment whose two axes differ it is still the
    # wrong question, and the answer it produces is an empty board rather than an error.
    token = tracker_token_for(project) or deployment_tracker_token(project) or None
    tickets, error = read_board(project, token=token)
    if error:
        # An unreadable board is not an empty board. Reporting "nothing queued" here would tell the
        # tech-lead the floor has nothing to do — the exact opposite of what an unreadable board
        # means, and a lie it would then act on.
        activity.logger.warning(
            "techlead watch: could not read the board (%s) — this round cannot tell whether the "
            "floor is idle with work waiting, so it will not claim either way", error)
        return []
    return [str(n) for n in readiness(tickets).todo]


def _recent_causes(project_name: str) -> dict[str, int]:
    """How many DIFFERENT tickets failed each way lately. Three tickets failing the same way is one
    problem wearing three numbers, and no single diagnosis can see that."""
    from openfactory.techlead.classify import classify

    try:
        from openfactory.api.metrics_view import scan_records

        seen: dict[str, set] = {}
        for row in scan_records():
            if row.get("kind") != "job" or not row.get("note"):
                continue
            if str(row.get("pk") or row.get("project") or "") != project_name:
                continue
            cause = classify(str(row.get("note"))).cause
            seen.setdefault(cause, set()).add(str(row.get("ticket")))
        return {c: len(t) for c, t in seen.items()}
    except Exception as exc:  # noqa: BLE001 — a pattern we cannot see is not a reason to be silent
        # Losing this loses recurrence detection specifically: three tickets failing the same way
        # stop being one systemic cause and go back to looking like three unrelated parks.
        activity.logger.warning("could not read recent failure causes (%s) — this round cannot "
                                "spot a repeating cause", exc)
        return {}
