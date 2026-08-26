"""CodingAgentAdapter — the interface to whatever actually writes code.

v1 ships ClaudeCodeAdapter (over the `claude -p` CLI); Aider/others drop in behind
the same Protocol. The adapter is a generic worker (ADR-0001 D-5): its *behavior*
comes entirely from the AgentContext assembled per job, never from the framework.

The agent runs *through the sandbox*, not directly: on a WorktreeSandbox that means
a host subprocess in the worktree; on a ContainerSandbox that means `docker exec`
inside the container. The adapter builds the command; the sandbox runs it. This is
what keeps container isolation real — the agent never escapes to the host.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from openfactory.adapters.sandbox.base import SandboxAdapter, Workspace
from openfactory.contracts import AgentRunResult, Ticket


class AgentContext(BaseModel):
    """The closed package handed to the worker — the "manual" it wears.

    Assembled by the orchestrator from the cascade + project knowledge (D-2/D-9):
    the ticket, the always-on constraints (ADRs), the small guidelines, and a
    derived doc index the agent pulls from on demand.
    """

    ticket: Ticket
    guidelines: list[str] = Field(default_factory=list)  # inlined content (small)
    constraints: list[str] = Field(default_factory=list)  # ADRs, inlined (the constitution)
    doc_index: str = ""  # derived table-of-contents; agent pulls full docs on demand
    # Knowledge Layer, Phase 1: a rendered, generated module map ("where things live + why"),
    # injected so the agent navigates to the right code faster and then verifies it against the
    # real files (§7). Empty unless the project opts in (manifest.knowledge_map) AND a fresh,
    # non-orphaned bundle exists — a stale/missing bundle degrades to "" (§12), never misleads.
    knowledge_map: str = ""
    allowed_tools: list[str] = Field(default_factory=list)  # the permission matrix
    plan: str = ""  # the planner's execution plan, handed to the executor (plan→execute)
    # C2: an OPAQUE resume token from a prior PAUSED attempt (a rate-limit pause). When present,
    # the adapter RESUMES its prior session (e.g. `claude --resume <id>` + restored state)
    # instead of starting cold. Adapter-private meaning; the orchestrator only round-trips it.
    resume_handle: str = ""
    # A human's answer to a DecisionRequest this ticket parked on (e.g. a planner blocker),
    # injected on resume so the agent proceeds with the chosen option instead of re-asking:
    # "DECISION A — <label> (chosen by <who>)". Empty on a normal run.
    decision: str = ""


@runtime_checkable
class CodingAgentAdapter(Protocol):
    """The harness that WRITES CODE. Two methods are required; everything else is an optional
    capability the orchestrator probes for with `hasattr` and degrades without.

    That split is not decoration — it is the honest contract, and it is what makes a second
    harness (Codex, Kimi, …) a tractable amount of work. A minimal adapter implements two
    methods and loses no correctness: it just doesn't unlock the features below.

    OPTIONAL CAPABILITIES (probe → what you lose without it):
      - `plan(...)          -> AgentRunResult`  — the read-only planner stage. Without it the
        project's `planner_stage: true` is ignored and the executor investigates + implements in
        one warm context (ADR-0014's default anyway).
      - `continue_execute(...)`                — resume an execution cut off by the turn cap in
        the SAME session. Without it a turn-capped run falls through to `recover`, or parks.
      - `recover(...)`                         — a fresh pass over the partial work (ADR-0013 D5).
        Without it a stuck run parks for a human instead of self-healing.

    The judgment-side methods (`size`, `advise`, `diagnose`, `chat`) are NOT part of this
    protocol — see `JudgmentAgentAdapter`. A coding harness never has to implement them.
    """

    def execute(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext
    ) -> AgentRunResult:
        """Implement the ticket inside `workspace`, running through `sandbox`, within
        the granted permissions. Uses `context.plan` when present. Returns a result."""
        ...

    def repair(
        self,
        *,
        sandbox: SandboxAdapter,
        workspace: Workspace,
        context: AgentContext,
        failure_log: str,
    ) -> AgentRunResult:
        """Given validation failures, attempt a fix. Called inside the bounded
        REPAIRING loop."""
        ...


@runtime_checkable
class JudgmentAgentAdapter(Protocol):
    """The harness that JUDGES — the pre-flight sizer and the tech-lead's brain. Deliberately a
    SEPARATE axis from the coding harness (ADR-0017's sibling decision).

    Why separate: what you want to swap and measure is who *writes the code*. These calls are a
    different job — read-only reasoning over a ticket, a failure, or a question in Slack — and
    their quality gates the whole pipeline (a bad sizing verdict wastes an entire
    execute/test/review chain). So a deployment can run Codex as its coder while keeping a
    known-good judge, and swapping the coder does NOT silently move the tech-lead with it.

    `size` is optional (probed): without it the pre-flight sizing gate is a no-op and tickets run
    unsized. The rest are called unconditionally by the tech-lead surfaces.
    """

    def advise(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, situation: str
    ) -> AgentRunResult:
        """The coordinator's humanized take on a parked DecisionRequest (ADR-0015)."""
        ...

    def diagnose(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, situation: str
    ) -> AgentRunResult:
        """The tech-lead's impediment diagnosis, verified against a real checkout (ADR-0015)."""
        ...

    def chat(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, question: str
    ) -> AgentRunResult:
        """A read-only answer to a teammate's question in Slack (ADR-0015 v2)."""
        ...


def final_text(res) -> str:
    """The agent's COMPLETE final message — the one way to read a harness result.

    `AgentRunResult.summary` is capped at ~1000 characters, which is right for the operator-facing
    job line it was built for and wrong for every consumer that needs the content. The cap does not
    announce itself: prose ends mid-word, and JSON — which four callers parse out of this text —
    ends mid-token, so the parse fails and the caller reports "could not read the answer" while
    nothing anywhere says the output was CUT rather than wrong.

    THIS FUNCTION EXISTS BECAUSE IT WAS WRITTEN THREE TIMES. The sizer worked around the cap after
    a live bug (#37's 3509-char verdict truncated to 1000); the Slack bot copied the workaround;
    the product role copied it again on 2026-07-29. Each consumer had to KNOW to work around it —
    and the reviewer, which parses a whole ReviewResult out of the same field, never did. A defect
    that has to be remembered at every call site is a defect at the source; on a pilot about to
    serve N clients, the ones that get remembered are whichever the first client happened to hit.

    Falls back to the capped summary only when the raw stream cannot be read at all."""
    import json

    for line in reversed((getattr(res, "raw_output", "") or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except Exception:  # noqa: BLE001
            # not-a-failure: an agent stream carries non-JSON lines by design (progress, prose);
            # skipping one is parsing, not error handling
            continue
        if isinstance(event, dict) and event.get("type") == "result" and event.get("result"):
            return str(event["result"])
    return getattr(res, "summary", "") or ""



def json_envelope(out: str) -> dict | None:
    """The JSON envelope a harness CLI printed, ignoring anything it said around it.

    A HARNESS CLI IS A PROGRAM, AND PROGRAMS TALK. `claude -p --output-format json` emits its
    envelope on stdout — and above it, whatever it felt like mentioning:

        Warning: Opus: Opus 5 not available — using Opus 4.5 for this session
        {"is_error":false,"num_turns":1,...}

    A bare `json.loads` on that raises on character one. The reviewer did exactly that, so the
    INDEPENDENT REVIEW — one of this platform's three product claims — came back
    `rejected / score 0 / "reviewer output could not be parsed"` on a diff that was fine, with a
    valid envelope sitting one line below. Reproduced live on fx-ado PR #10.

    THE BANNER IS NOT AN EDGE CASE. An update notice, a login hint, a deprecation, a model
    substitution, a proxy warning — every one of them is a line a CLI may print on any client's
    machine on any day, and none of them says anything is wrong. A parser that treats the first
    byte as the start of the document is a parser that fails on the vendor's release schedule.

    `None` when there is genuinely no object to find, so the caller can still tell "said nothing
    parseable" from "said a verdict". Trailing prose is tolerated too (`raw_decode` stops at the
    end of the value), because the same reasoning applies to whatever a CLI appends."""
    decoder = json.JSONDecoder()
    for start in _object_starts(out or ""):
        try:
            value, _ = decoder.raw_decode(out, start)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _object_starts(text: str):
    """Offsets worth trying as the start of the envelope: the first `{` of each line, then any.

    Line-anchored first because a CLI prints its envelope on its own line, and starting there skips
    a `{` that happens to sit inside a warning's prose."""
    seen: list[int] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        brace = line.find("{")
        if brace != -1:
            seen.append(offset + brace)
        offset += len(line)
    return seen


def prose_only(out: str) -> str:
    """Everything a harness CLI said that is NOT a stream event — i.e. plain stderr.

    A PAUSE DETECTOR MUST NEVER READ AN EVENT. Every adapter that text-matches its output for
    `429`/`401`/`403` did so over the RAW stream, and that stream carries two things those bare
    numbers appear in for entirely innocent reasons:

      * generated identifiers — `ses_02d429e0dffe…`, `prt_fd2a429fe…`, codex's `thread_id`. They
        are dense digits, so some fraction of them contain `429`, and because ids advance with
        time the false positives arrive in CONTIGUOUS BURSTS: every run in a window fails
        together, which reads exactly like a real outage rather than like a parser bug;
      * THE AGENT'S OWN TOOL OUTPUT — a diff, a test name, a log line. A client whose code handles
        HTTP 429 (any rate-limiting library, any API wrapper) would park its own jobs by writing
        about the number.

    Either way the job parks as `rate_limit` or `auth`, and the retry is scheduled against a limit
    nobody hit. Restricting the fallback to non-event lines leaves it doing the only job it was
    ever for: reading a CLI that died before it emitted any JSON at all.

    Found on the OpenCode adapter by adversarially replaying a real captured run (2026-08-05), then
    swept across the class — `codex` and `kimi` carried the identical pattern, copied between
    adapters exactly as the bug was.
    """
    return "\n".join(line for line in (out or "").splitlines()
                     if not line.strip().startswith("{"))


def ticket_brief(context: AgentContext) -> str:
    """The ticket and its knowledge cascade, as EVERY harness hands it to its CLI — one builder.

    THERE WERE THREE, AND THEY DISAGREED ABOUT WHAT THE AGENT IS TOLD. The reference harness had
    `_ticket_context` (with the card's Context, without its In-scope list); codex had
    `_ticket_brief` (without either), and kimi and opencode imported codex's — so a card whose
    author wrote a `## Context` section, which `parse.py` fills from the body, reached three of
    the four harnesses with that section silently dropped, under a docstring claiming "the same
    knowledge cascade every harness receives". The fields are decided HERE, once: everything the
    contract carries that an implementer should read, in the order a person would read it.

    Role-neutral on purpose — "who you are" is the role prompt (`roles.role_prompt`), prepended
    by the adapter. The sizer's spec-only view is a different question and keeps its own text
    (`techlead._ticket_text`)."""
    t = context.ticket
    parts = [f"# Ticket {t.id}: {t.title}", "", "## Objective", t.objective]
    if t.context:
        parts += ["", "## Context", t.context]
    if t.in_scope:
        parts += ["", "## In scope"] + [f"- {x}" for x in t.in_scope]
    if t.acceptance_criteria:
        parts += ["", "## Acceptance criteria"] + [f"- {c.text}" for c in t.acceptance_criteria]
    if t.out_of_scope:
        parts += ["", "## Out of scope"] + [f"- {x}" for x in t.out_of_scope]
    if context.constraints:
        parts += ["", "## Constraints (ADRs — must not be violated)"] + list(context.constraints)
    if context.guidelines:
        parts += ["", "## Project guidelines"] + list(context.guidelines)
    if context.doc_index:
        parts += ["", "## Reference docs (read the relevant one before touching that area)",
                  context.doc_index]
    if context.knowledge_map:
        # A generated map of where things live — use it to JUMP to the right code, then open
        # and verify the real files (the code is ground truth; the map can lag it).
        parts += ["", "## Repository module map (navigation aid — verify against the real files)",
                  context.knowledge_map]
    if context.decision:
        # A human already answered a decision this ticket parked on (a planner blocker). Surface
        # it prominently so the agent PROCEEDS with that choice and never re-asks.
        parts += ["", "## Decision already made (by a human — follow it, do NOT re-ask)",
                  context.decision]
    return "\n".join(parts)


def wall_result(phase: str, model: str | None, harness: str, out: str,
                *, granted: Sequence[str] = ()) -> AgentRunResult:
    """A wall-clock stop, phrased so the tech-lead's diagnosis reads the CAUSE.

    NAMED `wall_result`, NOT `timeout_result`: `sandbox.timeouts.timeout_result` already exists,
    is public, and means the exit-code conversion the sandbox performs. Two functions with one
    name and two meanings is how a reader picks the wrong one.

    HERE, IN THE NEUTRAL BASE, BECAUSE IT LIVED IN ONE VENDOR'S ADAPTER. `codex.py`, `kimi.py` and
    `opencode.py` imported it from `claude_code.py`, so blocking that module broke the other three
    at import time: a third-party harness needing the shared wall shape had to depend on a
    competitor's connector, and the reference harnesses could not be split apart at all.

    Deliberately NOT a `pause_reason`: a rate-limit pause auto-resumes on a timer because the
    limit lifts by itself, and a run that burned four hours does not get better by waiting. It is
    an impediment — the job parks, the tech-lead diagnoses it with this sentence as the raw
    failure, and a human decides whether to resume, split, or drop it.

    THE SENTENCE USED TO GUESS AND NOW IT MEASURES (C-39). "stuck, looping, or the ticket is far
    larger than it looks" is three hypotheses offered to whoever reads the park, and the stream
    sitting in `out` already distinguishes them: a harness that went quiet, one that repeated the
    same call forty times, and one that spent the pass reaching for a tool it was never granted
    look nothing alike event-for-event. The guess stays — it is still the right advice when the
    stream cannot settle it — and the measurement is appended to it.

    THE READING NEVER CLAIMS MORE THAN THE STREAM SUPPORTS. Three of the four harnesses stamp no
    time on their events, so "no event for N minutes" is unavailable post-mortem for them and the
    note says so rather than reading as calm. `now` is the host clock at the moment of the kill,
    which is the right instant to measure the last event against.

    THIS SENTENCE IS READ BY A MACHINE BEFORE IT IS READ BY A PERSON. It becomes the hold note
    (`machine._hold`, "agent stopped: <summary>"), and the workflow's self-heal rung classifies
    that note before anybody sees it: `classify` → `transient` → wait 15 min → resume. So a phrase
    chosen for a human can spend four more hours of agent time by accident, and one did — the
    original wording said the task was "still running", which is the literal phrase `classify`'s
    transient rule uses for a CI check that has not finished yet. Anything added here has to be
    read back through `classify` — see the guard in `tests/test_the_harness_pulse.py` that
    classifies the WHOLE summary, not just the reading."""
    import time

    from openfactory.adapters.agent.stream import reading_of
    from openfactory.adapters.sandbox.timeouts import AGENT_TIMEOUT

    hours = AGENT_TIMEOUT / 3600
    reading = reading_of(harness, out, granted=granted, now=time.time())
    return AgentRunResult(
        ok=False,
        summary=(
            f"The {phase} agent hit the {hours:.0f}h wall-clock wall and was stopped. A task that "
            f"has run for {hours:.0f}h without finishing has a problem — it is stuck, looping, or "
            f"the ticket is far larger than it looks. Review the partial work on the branch and "
            f"decide: resume, split it, or drop it. "
            f"What the harness's own stream shows: {reading.note}."
        ),
        model=model or "default",
        harness=harness,
        raw_output=(out or "")[-20000:],
    )
