"""The job runner — the deterministic maestro (ADR-0001 state machine).

Slice 1 (the walking skeleton) drives: get_ticket → SPEC_VALIDATION → prepare →
setup → execute → commit → validate → open PR. It stops before REVIEWING/REPAIRING
and the D-12 lifecycle (those layer on next). The orchestrator itself stays
deterministic (D-11); each step is a seam onto an adapter.
"""

from __future__ import annotations

import logging
import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path

from openfactory import namespace
from openfactory.adapters.agent.base import AgentContext, CodingAgentAdapter
from openfactory.adapters.forge.base import ForgeAdapter
from openfactory.adapters.notify.base import Level, NullNotifier
from openfactory.adapters.notify.base import Notifier as NotifierT
from openfactory.adapters.reviewer.base import ReviewerAdapter, ReviewInput
from openfactory.adapters.sandbox.base import SandboxAdapter, Workspace
from openfactory.adapters.tracker.base import TrackerAdapter
from openfactory.contracts import (
    AgentRunMetric,
    AgentRunResult,
    DecisionRequest,
    JobState,
    Manifest,
    ReviewResult,
    RunResult,
    Suppression,
    Ticket,
    ValidationResult,
    parse_decision,
)
from openfactory.contracts.bot import BotIdentity
from openfactory.observability import EventKind, EventSink, JobEvent, NullEventSink, now_iso
from openfactory.orchestrator.context import build_context
from openfactory.orchestrator.errors import SetupFailed, SpecValidationError
from openfactory.orchestrator.merge_policy import format_review, review_event, should_auto_merge
from openfactory.orchestrator.risk import assess as risk_assess
from openfactory.orchestrator.risk import of_attempt as risk_of_attempt
from openfactory.orchestrator.validation import (
    applicable_validations,
    as_gate,
    scope_explosion,
)
from openfactory.policy import census as census_policy
from openfactory.policy import protected as protected_policy
from openfactory.policy.census import inventory_command, inventory_of
from openfactory.policy.census import vanished as census_vanished
from openfactory.policy.protected import violations as protected_violations
from openfactory.techlead import voice as tl_voice

_SETUP_TIMEOUT = 1800
#: The census ENUMERATES; it does not build. `_SETUP_TIMEOUT` is sized for `dotnet restore`
#: and `npm ci`, and lending it to a collect-only command means a census that hangs holds a
#: worker for half an hour and then returns None — which gates. Its own budget fails faster
#: and to the same place.
_CENSUS_TIMEOUT = 300
_VALIDATION_TIMEOUT = 1800
_E2E_POLL = 15  # seconds between polls of the dispatched e2e run (ADR-0008)
_E2E_TIMEOUT = 1500  # give up watching the e2e run after ~25min (a stuck run reports, not hangs)
_E2E_MAX_ERRORS = 5  # consecutive poll failures before we stop and report the REAL error


def _all_passed(validations: list[ValidationResult]) -> bool:
    """ADVISORY GATES ARE EXCLUDED (C-37). They run, they report, and they never decide.

    This one predicate is what the repair loop, the merge decision and the job's own outcome all
    hang on, so excluding advisory here is what makes "reports but never blocks" true everywhere
    at once rather than in three places that can drift. A security or licence scan on a real
    codebase starts noisy; wired as a blocking gate it is the first thing a client turns off —
    after the platform has paid an agent to try to fix a CVE in a transitive dependency."""
    return all(v.passed for v in validations if not v.advisory)


# A gate that can be silenced by a comment is no gate. If a diff ADDS a coverage/lint/
# type/security suppression, the "green" gates no longer prove what they claim, so the
# change must never auto-merge — it goes to a human. Detected from the diff itself, so
# it holds even when the LLM reviewer misses it. (engineering.md #12)
_SUPPRESSION_RE = re.compile(
    r"#\s*(pragma:\s*no\s*cover|noqa|type:\s*ignore|nosec|nocov)", re.IGNORECASE
)


def _added_suppressions(diff: str) -> list[str]:
    """Gate-suppression comments introduced by this diff (added '+' lines only, never
    context or removed lines, and never the '+++' file header)."""
    out: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            m = _SUPPRESSION_RE.search(line)
            if m:
                out.append(re.sub(r"\s+", " ", m.group(1).strip().lower()))
    return out


def _suppression_details(diff: str) -> list[Suppression]:
    """Like `_added_suppressions`, but keeps WHERE each one landed — the file (from the
    `+++ b/…` header) and the added line's text — so the panel can point the human straight at
    what to review instead of a bare "forcing human review"."""
    out: list[Suppression] = []
    cur_file = ""
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur_file = line[6:].strip()
            continue
        if line.startswith("+") and not line.startswith("+++"):
            m = _SUPPRESSION_RE.search(line)
            if m:
                out.append(Suppression(
                    kind=re.sub(r"\s+", " ", m.group(1).strip().lower()),
                    file=cur_file,
                    snippet=line[1:].strip()[:200],
                ))
    return out


def _failure_log(validations: list[ValidationResult]) -> str:
    return "\n\n".join(
        f"$ {v.command}  (exit {v.exit_code})\n{v.output_tail}"
        for v in validations
        if not v.passed
    )


#: The heading `_review_lines` writes and `_republish_review` finds the section by. ONE SPELLING:
#: a writer and a reader that each carry their own would agree until one of them is edited, and the
#: failure is silent — the amendment simply never lands.
_REVIEW_HEADING = "## Review — "


def _review_lines(r: ReviewResult) -> list[str]:
        """The pull request's review section — the ONE place it is composed (#187).

        Extracted from `_pr_body` because it is now written twice: once when the pull request is
        opened, and again whenever a pass rewrites the code under it. A second copy is how the
        card and the pull request came to say different things about one review.

        A REVIEW THAT COULD NOT BE READ IS NOT A REJECTION, AND THIS HEADING SAID IT WAS. The
        reviewer already distinguishes the two in its `summary` (adapters/reviewer/claude_code.py)
        and the DECISION deliberately stays `rejected`, because proceeding as if reviewed is the
        unsafe default. But the heading is what a human skims on the PR, and `## Review — rejected
        (score 0)` above the sentence "reviewer output could not be parsed" asserts a judgement of
        the code that nobody made.

        Seen on the first real Azure DevOps ticket (fx-ado PR #9, 2026-08-06): a correct diff
        meeting all five acceptance criteria, headed "rejected". Whoever opens that PR goes looking
        for what is wrong with the code; the thing to fix is the reviewer.

        A score of 0 is likewise reported only when one was given. Printing `(score 0)` for a
        review that produced no score is the same lie in smaller type.
        """
        unread = r.score == 0 and not r.findings and (
            "could not be parsed" in (r.summary or "") or "never ran" in (r.summary or ""))
        out = [f"{_REVIEW_HEADING}DID NOT COMPLETE" if unread
               else f"{_REVIEW_HEADING}{r.decision} (score {r.score})", r.summary]
        if unread:
            out.append("> This is not a judgement about the diff — nothing reviewed it. "
                       "The gates above are the only automated evidence here.")
        for f in r.findings:
            loc = f" ({f.file}:{f.line})" if f.file else ""
            out.append(f"- **{f.severity}**{loc}: {f.description}")
        return out

def _actionable_review(review: ReviewResult) -> bool:
    """Whether a rejection is worth an autonomous fix (ADR-0006): it must carry concrete
    findings. A rejection with no findings is a vague verdict → escalate, don't guess."""
    return bool(review.findings)


# The bot marks a ticket it is actively working with this label (a GitHub App can't be an issue
# assignee). Added on pickup; removed the moment the job leaves a working state (parked/done).
#
# NO PICTOGRAPH, AND THAT IS NOT A STYLE CHOICE — it was `"🤖 sdlc-working"` and one vendor
# refuses it outright. Measured live, one character at a time: Azure DevOps answers `TF401407: The
# tag name is invalid. It contains invalid characters` to `🤖 sdlc-working`, to `🤖sdlc-working`
# and to a bare `🤖`, while `✓ done` and `→ next` are fine — it rejects anything outside the BMP.
# Jira separately refuses the space. So the emoji cost a per-vendor sanitiser in two adapters and
# bought a label that reads, on a client's own board, as though a toy wrote it.
_BOT_WORKING_LABEL = "openfactory-working"


def _spec_refusal(ticket: Ticket) -> None:
    """Refuse a ticket with no acceptance criteria, NAMING what the parser did see.

    The bare message used to be "ticket has no acceptance criteria", and the first client to write
    a ticket in Portuguese got it about a ticket carrying five of them — the parser matched English
    headings only (fixed in `tracker/parse.py`). The alias table closes today's gap; this closes
    the NEXT one, whatever heading a client's template turns out to use. A refusal that lists the
    sections it found is a rename away from working. One that denies what is on the screen is an
    argument nobody can win."""
    from openfactory.adapters.tracker.parse import section_names

    found = section_names(ticket.raw or "")
    if not found:
        raise SpecValidationError(
            "ticket has no acceptance criteria — in fact no sections at all. Add a "
            "`## Acceptance criteria` (or `## Critérios de aceite`) heading with one `- ` bullet "
            "per criterion, so the job can tell when it is done."
        )
    raise SpecValidationError(
        "ticket has no acceptance criteria. The sections I found were "
        + ", ".join(f"'{name}'" for name in found)
        + " — none of them reads as a criteria heading. Rename one to `## Acceptance criteria` "
          "or `## Critérios de aceite`, with one `- ` bullet per criterion."
    )


def _is_app_login(login: str) -> bool:
    """Whether a bot login belongs to a GitHub App, which cannot be an issue assignee.

    NOT the safety net — the try/except at the call site is, and it is provider-neutral. This is
    the optimisation on top of it: `name[bot]` is a login GitHub itself mints and will never accept
    as an assignee, so attempting it spends an API call to be told so on every pickup, and logs a
    warning on every ticket. A warning that fires every time is a warning nobody reads.

    Deliberately narrow. A tracker whose bot is an ordinary user — a PAT-based GitHub bot, a GitLab
    or Jira service account — has no such suffix, so it is still claimed exactly as before. If a
    second provider ever mints unassignable logins of its own shape, this becomes a question for
    the tracker port rather than another suffix here."""
    return login.endswith("[bot]")


class TestWorkRefused(RuntimeError):
    """A ticket labelled `factory-test` was pointed at a board that does not accept it (ADR-0027).

    An exception rather than a quiet `RunResult`: this is a misrouting, not an outcome of the work,
    and a job that ends "successfully having done nothing" is the shape of every silent failure in
    this codebase's ledger."""
_WORKING_STATES = frozenset({
    JobState.SPEC_VALIDATION, JobState.PREPARING, JobState.PLANNING,
    JobState.IMPLEMENTING, JobState.VALIDATING, JobState.REVIEWING, JobState.REPAIRING,
})


_CONTINUE_BRIEF = (
    "You were cut off mid-implementation (turn limit) — your previous work is intact in this "
    "workspace. CONTINUE from where you stopped and FINISH the ticket: complete the remaining "
    "acceptance criteria, make the tests pass, stay strictly in scope. Do not redo or rewrite "
    "what already works."
)


def _recovery_brief(prev: AgentRunResult) -> str:
    """The fresh recovery pass's brief (ADR-0013 D5): what happened + the standing orders.
    The workspace itself carries the partial work; the role file carries the doctrine."""
    return (
        f"A previous executor stopped unfinished: {prev.summary[:300]}\n"
        "The workspace contains its partial work. Assess the diff against the acceptance "
        "criteria, then FINISH the remainder — or, if it cannot fit, SIMPLIFY to the core "
        "criteria and deliver a smaller, fully-tested, mergeable change (say exactly what "
        "you cut). Never widen scope; never discard the existing work."
    )


def _suppression_repair_brief(details: list[Suppression]) -> str:
    """Frame the added gate-suppressions as a fix brief for the executor (ADR-0011): resolve
    them in the sandbox — remove what can be made testable, keep+justify only the genuinely
    untestable — before a human is ever involved."""
    lines = [
        "This change ADDED gate-suppression comment(s). A suppressed gate is not a passed gate,",
        "so resolve them now — staying strictly in scope:",
        "- PREFER to REMOVE each suppression by making the code properly covered (add a focused",
        "  test) or restructuring so the gate passes honestly.",
        "- KEEP a suppression ONLY if the line is genuinely untestable (thin composition-root",
        "  wiring, an unreachable defensive branch, external I/O) — and give it a clear",
        "  `- <reason>` matching this codebase's existing convention.",
        "- Do NOT add any NEW suppression, and NEVER silence lint/type/security (noqa /",
        "  type: ignore / nosec) — fix the underlying issue instead.",
        "Keep every existing gate green.",
        "",
        "Suppression(s) added by this change:",
    ]
    for s in details:
        loc = f"{s.file}: " if s.file else ""
        lines.append(f"- [{s.kind}] {loc}{s.snippet}")
    return "\n".join(lines)


def _review_findings_log(review: ReviewResult) -> str:
    """Frame the reviewer's rejection as a fix brief for the executor (ADR-0006) — the same
    role the failing-gate log plays for the validation-repair loop."""
    lines = [
        "The independent code review REJECTED this change. Address every finding below,",
        "staying strictly in scope (fix the problem — do NOT silence gates or delete tests):",
        "",
        f"Reviewer summary: {review.summary}" if review.summary else "",
    ]
    for f in review.findings:
        loc = f" ({f.file}:{f.line})" if f.file else (f" ({f.file})" if f.file else "")
        lines.append(f"- [{f.severity}]{loc} {f.description}")
    return "\n".join(x for x in lines if x != "")


def _review_sentence(result) -> str:
    """What this platform's own reviewer found, as lines to hang under an announcement — or "".

    THROUGH `review.verdict.headline`, never composed here: the panel's gate item renders the same
    verdict, and a second wording is how two surfaces come to describe one fact differently. It
    also already knows the three answers apart — approved, rejected, and NOT REVIEWED — which is
    the distinction this announcement was missing.

    At most three points, because this rides on a notification somebody reads on a phone; the
    panel and the tech-lead have the dense form.
    """
    from openfactory.review.verdict import headline

    review = getattr(result, "review", None)
    verdict = review.model_dump() if hasattr(review, "model_dump") else (review or {})
    head = headline(verdict if isinstance(verdict, dict) else {})
    out = f"\n{head['word']} — {head['clause']}"
    for point in (head.get("points") or [])[:3]:
        out += f"\n· {point}"
    return out


def _review_event_detail(review: ReviewResult) -> list[dict]:
    """A compact, panel-facing view of the findings so a REJECTION shows WHY on the live feed
    (not just a bare score). Bounded — a handful of findings, short descriptions — so the
    OPENFACTORY_EVENT log line stays a sane size."""
    out: list[dict] = []
    for f in review.findings[:8]:
        out.append({
            "severity": f.severity,
            "description": (f.description or "")[:200],
            "file": f.file or "",
            "line": f.line or 0,
        })
    return out


log = logging.getLogger("openfactory.orchestrator")

#: Above this, the map's generation is worth a log line. Not a limit — a number somebody sees.
#: Measured 2026-07-29: 0.24s for 215 files, so this fires only on a repo an order of magnitude
#: larger, which is exactly when an operator wants to know before it becomes a mystery.
_KNOWLEDGE_SLOW_SECONDS = 5.0


@dataclass
class JobRunner:
    tracker: TrackerAdapter  # where the ticket lives
    forge: ForgeAdapter  # where the PR goes
    agent: CodingAgentAdapter
    sandbox: SandboxAdapter
    manifest: Manifest
    repo_path: Path
    reviewer: ReviewerAdapter | None = None  # optional independent review (D-5)
    events: EventSink = field(default_factory=NullEventSink)  # the job journal (D-13)
    bot: BotIdentity = field(default_factory=BotIdentity)  # the actor (commit author, D-12)
    notifier: NotifierT = field(default_factory=NullNotifier)  # push channel (A4)
    #: The project this ticket belongs to, so the ADR-0027 gate can ask whether its board accepts
    #: factory-test work. Optional so every existing construction keeps working — and `build_runner`
    #: (the ONE place production assembles a runner) passes it, which is what makes the gate real
    #: rather than decorative. Absent → no gate, and the test that pins the wiring says so.
    project: object | None = None

    def _job_branch(self, ticket: Ticket) -> str:
        """The branch this job works on — fresh work, a CI repair and a C2 resume alike.

        ONE NAME, RECALCULATED FROM THE TICKET ID ON EVERY ENTRY, so a repair finds the branch the
        open pull request tracks without anything having stored it. That property is what a
        rename of this prefix has to preserve: while the platform carried two spellings, a repair
        that recalculated the new name for a PR opened under the old one pushed its fix to a
        branch nobody watched — an agent ran, money was spent, and the repair appeared to have
        done nothing. The second spelling left on 2026-08-25; the property stays, in one place."""
        return namespace.job_branch(ticket.id)

    def run(
        self, ticket_ref: str, resume_handle: str | None = None, spent_turns: int = 0,
        decision: str = "",
    ) -> RunResult:
        """Drive one ticket to a PR. `resume_handle` (C2) is an OPAQUE token from a prior
        rate-limit PAUSE: when set, we RESTORE the paused attempt's partial worktree from its
        pushed branch and hand the token to the agent so it CONTINUES its session, instead of
        replanning/re-implementing from scratch (partner-reported re-burn). None → a fresh run.
        `spent_turns` carries the ticket's cumulative agent-turn count across resumes — the
        effort budget (ADR-0013 D4) governs the TICKET, not one attempt. `decision` is a human's
        resolved answer to a DecisionRequest this ticket parked on (a planner blocker): injected
        into the agent so it proceeds with that choice instead of re-asking."""
        self._turns = spent_turns  # cumulative effort; bumped by _count() after each agent call
        self._agent_runs: list[AgentRunMetric] = []  # per-invocation cost telemetry (metrics sink)
        self._decision = decision  # a resolved human choice to feed the planner/executor (once)
        self._assumptions: list[str] = []  # planner `assume` notes → surfaced in the PR
        ticket = self.tracker.get_ticket(ticket_ref)

        # THE FLOOR, BEFORE ANY AGENT CALL. `REQUIRED_VALIDATION_ROLES` was read only by the
        # `openfactory conformance` CLI, which nothing on this path invokes — so a project with an
        # empty
        # `validate:` block ran the agent and auto-merged on a vacuously satisfied floor.
        #
        # UNCONDITIONAL, AND IT USED TO BE AN ENVIRONMENT VARIABLE. `OPENFACTORY_ENFORCE_FLOOR`
        # existed
        # because turning the floor into a refusal would have stopped every project this platform
        # drove: not one declared a `security` gate, and a floor that arrives as an outage is a
        # floor an operator switches off. That reason expired the day `org_defaults/floor.yaml`
        # landed — every project now INHERITS a `security` gate needing only a POSIX shell and
        # `git`, both of which `box_prove`'s `contract` station already refuses an image without.
        # So the only way to fail this check is to declare no `test` command at all, and a project
        # with no test command is precisely what must not buy a paid agent pass.
        #
        # REMOVED RATHER THAN DEFAULTED TO ON, because a flag that can turn the floor off IS the
        # floor being negotiable, and four places said in writing that it is not: `policy/floor.py`
        # ("the non-negotiable guarantees… no project manifest may loosen these"),
        # `org_defaults/floor.yaml` ("there is no flag, and there is deliberately no
        # deployment-wide off switch, because an off switch for the floor is the first thing that
        # gets set"), `docs/architecture.md` §7 ("quality is a floor, not goodwill — a project
        # cannot switch off the gates the framework requires") and ADR-0001 D-2. The variable made
        # all four false — and, the part that decided
        # it, it was OFF BY DEFAULT, so on an open-source install, where nobody knows the name, the
        # guarantee did not exist at all. A default is not a preference in a distributed product;
        # it is what almost everybody gets.
        #
        # THE ESCAPE HATCH IS `advisory: true`, NOT AN OFF SWITCH. A gate that reports and never
        # blocks is how a noisy scanner on a fifteen-year-old codebase avoids being the first thing
        # a client disables (C-37), and the inherited `security` gate ships advisory for exactly
        # that reason. What has no escape hatch is declaring NO gate, because `all([])` is True and
        # that is a green light over nothing.
        # ADR-0027: a client's board carries the client's product. Checked HERE — the ticket is
        # already loaded, so it costs no API call, and it is before the box, before any agent pass
        # and long before a merge. Eleven smoke-test tickets once walked this whole path and left
        # eleven dead endpoints in a client's accounting product; there was no field to consult
        # and no gate to fail, so the question was never asked.
        from openfactory.policy.test_work import refusal_for

        refused = (refusal_for(self.project, str(ticket.id), list(ticket.labels or []))
                   if self.project is not None else "")
        if refused:
            log.warning("REFUSED %s", refused)
            try:  # say it where the person who labelled it will look
                self.tracker.comment(ticket.id, f"Refused — {refused}")
            except Exception:  # noqa: BLE001 — the refusal stands even if the comment fails
                log.warning("could not comment the refusal on %s", ticket.id)
            raise TestWorkRefused(refused)

        # The framework picks up a ticket regardless of who is assigned; the current
        # assignee is the OWNER to return to on an impediment. On pickup the bot makes
        # itself the sole assignee (remembering the owner).
        owner = self._owner_of(ticket_ref)
        if self.bot.login and not _is_app_login(self.bot.login):
            # BEST-EFFORT, like the label below and for a stronger reason: the claim is
            # bookkeeping and the delivery is the point. This line used to be bare, and the first
            # deployment whose bot login was set watched a ticket die on it — RuntimeError out of
            # `run()`, card left in TO-DO, nothing said anywhere. Assignment can be refused for
            # reasons that have nothing to do with the work: an outside collaborator, a suspended
            # account, an org that restricts assignees, a renamed user.
            try:
                self.tracker.set_assignees(ticket.id, [self.bot.login])
            except Exception as exc:  # noqa: BLE001 — never trade the delivery for the claim
                log.warning("could not claim %s as %s (%s) — working it unclaimed; the owner is "
                            "still tracked for impediments", ticket.id, self.bot.login,
                            str(exc)[:160])
        # Lights-out: a GitHub App can't be an issue assignee, so with no human assignee an
        # impediment is routed back to the CREATOR (they get @-mentioned + the coordinator speaks).
        owner = owner or ticket.author
        # Mark the ticket as actively worked by the bot — a LABEL (the App isn't assignable).
        # Removed again when the job leaves a working state (see _set_state). Best-effort.
        try:
            self.tracker.add_label(ticket.id, _BOT_WORKING_LABEL)
        except Exception as exc:  # noqa: BLE001 — a labelling hiccup must never derail the job
            log.warning("could not mark %s as being worked on (%s)", ticket.id, str(exc)[:120])

        # An `e2e`-labelled ticket isn't implemented — just run the e2e suite and report
        # (ADR-0008). This short-circuits the whole plan→execute→PR pipeline.
        if self._is_e2e_ticket(ticket):
            return self._run_e2e_check(ticket, owner)

        # THE FLOOR, AND IT SITS BELOW THE e2e BRANCH DELIBERATELY. Its whole justification is the
        # money: a project that declares no gates would run an agent, pass every gate vacuously
        # (`all([])` is True) and be eligible for auto-merge, so the refusal has to come before any
        # agent call and does. An e2e ticket makes NONE — it dispatches the client's own workflow
        # and reports that workflow's real conclusion — so holding it spends nothing to protect
        # nothing, and tells a client their test suite may not run because they declared no test
        # command. Surfaced by two e2e tests going red the moment the refusal became unconditional;
        # while it sat behind `OPENFACTORY_ENFORCE_FLOOR`, off by default, nothing could have shown
        # it.
        #
        # It also sits below the CLAIM above, which is where the owner is resolved — so the hold
        # returns the ticket to a person this code already knows, instead of re-reading assignees
        # in a second `try` that had its own failure mode.
        from openfactory.policy.conformance import floor_reason, profile_gate_reason

        if (short := floor_reason(self.manifest)) is not None:
            self._emit(ticket, "note", f"⚠️ quality floor: {short}")
            return self._hold(ticket, owner, short, JobState.ON_HOLD)

        # WHAT THIS PROJECT IS (ADR-0044), resolved ONCE and here — beside the floor, above the
        # workspace, before a single token is spent. The class shapes the guidelines the agent
        # reads and can strengthen the merge gate, so resolving it later would mean an agent that
        # already ran under rules the project did not ask for.
        #
        # A NAME THAT DOES NOT RESOLVE HOLDS THE JOB, WITH A VOICE. `resolve_profile` raising is
        # only half of "a hold, not a shrug" — the other half is that somebody is told. A project
        # that believes it is `regulated` and runs as the generic case is the failure this whole
        # mechanism exists to refuse, and a silent `return False` at merge time is that failure
        # wearing a hold's clothes.
        from openfactory.policy.profiles import ProfileError, resolve_profile

        try:
            self._profile = resolve_profile(self.manifest.profile, project_dir=self.repo_path)
        except ProfileError as exc:
            self._emit(ticket, "note", f"⚠️ profile: {exc}")
            return self._hold(ticket, owner, str(exc), JobState.ON_HOLD)

        # A GATE THE PROFILE NAMES MUST ALREADY EXIST TO BE PROMOTED. Checked here, statically,
        # the same point and for the same reason the floor is checked above — before any agent
        # call. `RiskPolicy.gates` can only promote a role some other layer already runs; a role
        # nothing defines is the exact silent no-op `gates:` shipped with once (ADR-0044).
        if (gate_issue := profile_gate_reason(self.manifest, self._profile)) is not None:
            self._emit(ticket, "note", f"⚠️ profile gates: {gate_issue}")
            return self._hold(ticket, owner, gate_issue, JobState.ON_HOLD)

        self._set_state(ticket, JobState.SPEC_VALIDATION)
        try:
            self._spec_validation(ticket)
        except SpecValidationError as exc:
            return self._hold(ticket, owner, str(exc), JobState.NEEDS_REFINEMENT)

        base = ticket.base_branch or self.manifest.base_branch
        # C2 resume: rebuild the workspace from the paused attempt's already-pushed branch so
        # the partial code is present, instead of a fresh branch off base. Best-effort — if the
        # branch isn't there (nothing was preserved), prepare() falls back cleanly and we replan.
        resuming = bool(resume_handle)
        branch = self._job_branch(ticket)

        self._set_state(ticket, JobState.PREPARING)
        if resuming:
            self._emit(ticket, "note", "▶ resuming a paused attempt — restoring partial work")
        ws = self.sandbox.prepare(
            repo_path=self.repo_path, base_branch=base, branch=branch,
            checkout_existing=resuming,
            # the same authenticated remote `publish_branch` pushes to — a resume fetches the
            # preserved branch from the FORGE, and the worker's cache origin carries no token
            remote_url=self.forge.push_remote(),
        )
        try:
            try:
                # `at_base` is `not resuming` and not `True`: a resume restores the paused
                # attempt's partial work, so this tree is no longer the base commit.
                self._run_setup(ticket, ws, at_base=not resuming)
            except SetupFailed as exc:
                # FAILED, not NEEDS_REFINEMENT: the ticket is fine, the environment is not. Sending
                # this back as a spec problem would ask somebody to rewrite a perfectly good ticket.
                return self._hold(ticket, owner, str(exc), JobState.FAILED, branch=branch)

            ctx = self._build_context(ticket, ws)
            ctx.resume_handle = resume_handle or ""  # the agent resumes its session if it can
            ctx.decision = self._decision  # a resolved human choice, injected into the agents

            # PLAN → the planner investigates (read-only) and drafts a testable plan. Optional:
            # an adapter that doesn't split roles simply has no plan() and we go straight to
            # execute (single-agent, as before).
            plan_cost = 0.0
            # ADR-0014: single-agent by default. The dedicated read-only planner runs ONLY when
            # the manifest opts in (planner_stage) AND the adapter exposes plan(). Otherwise the
            # executor investigates + plans + implements in one warm context (no handoff tax).
            if self.manifest.planner_stage and hasattr(self.agent, "plan"):
                self._set_state(ticket, JobState.PLANNING)
                plan_result = self.agent.plan(sandbox=self.sandbox, workspace=ws, context=ctx)
                for action in plan_result.actions:
                    self._emit(ticket, "agent_action", action, role="planner")
                self._emit_credential(ticket, plan_result)
                if plan_result.pause_reason:
                    return self._paused(
                        ticket, plan_result.pause_reason, plan_result.retry_at, branch=branch,
                        ws=ws, resume_handle=plan_result.resume_handle,
                    )
                ctx.plan = (plan_result.summary or plan_result.raw_output or "").strip()
                plan_cost = plan_result.cost_usd or 0.0
                self._count(plan_result, "planner")
                self._emit(ticket, "note", f"plan ready: {ctx.plan[:200]}",
                           cost_usd=plan_result.cost_usd, role="planner")
                # Task-sizing gate (ADR-0002): if the plan is too large (or the planner
                # returned a SPLIT verdict), refine BEFORE the expensive executor runs —
                # this is where intake size couples to the execution budget. NOT re-applied on a
                # C2 resume: the ticket already passed the gate on its first run, the work is
                # part-done, and a nondeterministic fresh "SPLIT" verdict would discard the
                # resumable session and the pushed partial (audit MED).
                if not resuming:
                    gate = self._plan_gate(ticket, ctx.plan, owner, branch)
                    if gate is not None:
                        return gate
                    # DecisionRequest gate: the planner may flag a design decision. `blocked`
                    # parks WITH options (no park without options — owner); `assume` proceeds but
                    # records the assumption; `proceed` runs on. A decision already injected this
                    # run (a resumed blocker) is trusted → never re-block.
                    dgate = self._plan_decision_gate(ticket, ctx.plan, owner, branch)
                    if dgate is not None:
                        return dgate

            # EXECUTE → the executor implements the plan with TDD.
            self._set_state(ticket, JobState.IMPLEMENTING)
            agent_result = self.agent.execute(sandbox=self.sandbox, workspace=ws, context=ctx)
            for action in agent_result.actions:
                self._emit(ticket, "agent_action", action, role="executor")
            self._emit_credential(ticket, agent_result)
            self._emit(
                ticket, "note", f"agent finished: {agent_result.summary[:200]}",
                cost_usd=agent_result.cost_usd, role="executor",
            )
            if agent_result.pause_reason:
                return self._paused(
                    ticket, agent_result.pause_reason, agent_result.retry_at, branch=branch,
                    ws=ws, resume_handle=agent_result.resume_handle,
                )
            self._count(agent_result, "executor")

            # A STOP THAT ASKS A QUESTION IS NOT A FAILURE TO RECOVER FROM (C-34, #71). The
            # DecisionRequest construct existed, the BLOCKED park existed, the panel's options UI
            # existed — and the only thing able to raise one was the planner, which is off by
            # default (ADR-0014). The executor — the agent that actually does the work in every
            # default-pipeline ticket — could only stop, and its genuine "I need you to choose"
            # arrived as a generic ON_HOLD: plain text, no options, indistinguishable from a
            # crash, with a bounded deadline instead of a decision's held-for-a-human wait.
            #
            # CHECKED BEFORE THE RECOVERY LADDER, deliberately: a question is not something to
            # "recover" from, and the ladder would have spent up to two agent passes trying to
            # push through a stop the executor made on purpose. ok=False only — a finished run
            # that happens to contain a fenced block is judged by its diff, not its prose.
            if not agent_result.ok and agent_result.pause_reason is None:
                dr = parse_decision(agent_result.raw_output or agent_result.summary)
                if dr is not None:
                    dr.stage = dr.stage or "execute"
                    self._record_decision(ticket, dr)
                    # ADR-0013 D1: the executor was told to leave the workspace continuable, and
                    # the resume carries the picked option INTO the same session via the handle.
                    handle = self._preserve_for_hold(ticket, ws, agent_result.resume_handle)
                    return self._hold(
                        ticket, owner, f"decision needed — {dr.question[:200]}",
                        JobState.BLOCKED, branch=branch, decision=dr, resume_handle=handle,
                        total_cost_usd=self._reported_cost(), spent_turns=self._turns,
                    )

            # RECOVERY LADDER (ADR-0013 D5): the executor stopped WITHOUT finishing (turn cap,
            # error) — recover autonomously before any human: rung 1 continues the same session
            # (cheapest, the in-flight reasoning survives); rung 2 is a fresh recovery pass that
            # may finish or SIMPLIFY. All inside the ticket's effort budget. Humans are for
            # decisions, not debugging (the OpenFactory essence).
            rec = 0
            while (not agent_result.ok and agent_result.pause_reason is None
                   and rec < self.manifest.recovery_max_attempts
                   and not self._over_effort()):
                rec += 1
                self._set_state(ticket, JobState.REPAIRING)
                self._emit(ticket, "note",
                           f"⛑ recovery {rec}/{self.manifest.recovery_max_attempts}: executor "
                           f"stopped unfinished ({agent_result.summary[:120]})")
                if rec == 1 and agent_result.resume_handle and \
                        hasattr(self.agent, "continue_execute"):
                    agent_result = self.agent.continue_execute(
                        sandbox=self.sandbox, workspace=ws, context=ctx,
                        handle=agent_result.resume_handle, brief=_CONTINUE_BRIEF)
                elif hasattr(self.agent, "recover"):
                    agent_result = self.agent.recover(
                        sandbox=self.sandbox, workspace=ws, context=ctx,
                        brief=_recovery_brief(agent_result))
                else:  # an adapter without recovery methods reuses repair (same shape)
                    agent_result = self.agent.repair(
                        sandbox=self.sandbox, workspace=ws, context=ctx,
                        failure_log=_recovery_brief(agent_result))
                for action in agent_result.actions:
                    self._emit(ticket, "agent_action", action, role="executor")
                self._emit_credential(ticket, agent_result)
                self._emit(ticket, "note", f"recovery {rec} finished: "
                                           f"{agent_result.summary[:150]}",
                           cost_usd=agent_result.cost_usd, role="executor")
                self._count(agent_result, "recovery")
                if agent_result.pause_reason:
                    return self._paused(
                        ticket, agent_result.pause_reason, agent_result.retry_at, branch=branch,
                        ws=ws, resume_handle=agent_result.resume_handle,
                    )

            if not agent_result.ok:
                # ADR-0013 D1: preserve whatever was written BEFORE holding — a hold with a
                # handle is RESUMABLE (continue, not redo). #37 lost $14 here pre-D1. The
                # message is decision-shaped: the human decides, never debugs.
                handle = self._preserve_for_hold(ticket, ws, agent_result.resume_handle)
                why = (self._effort_reason() if self._over_effort()
                       else f"agent stopped: {agent_result.summary}")
                return self._hold(
                    ticket, owner, why,
                    JobState.ON_HOLD, branch=branch, total_cost_usd=self._reported_cost(),
                    resume_handle=handle, spent_turns=self._turns,
                )

            total_cost = plan_cost + (agent_result.cost_usd or 0.0)
            if self._over_cost_ceiling(total_cost):
                handle = self._preserve_for_hold(ticket, ws, agent_result.resume_handle)
                return self._hold(
                    ticket, owner, self._cost_reason(total_cost),
                    JobState.ON_HOLD, branch=branch, total_cost_usd=self._reported_cost(),
                    resume_handle=handle, spent_turns=self._turns,
                )
            self._commit(ws, ticket)
            touched, validations = self._validate(ws, ticket)

            # Bounded repair loop (D-12): let the agent fix failing validations.
            attempts = 0
            while (
                not _all_passed(validations)
                and attempts < self.manifest.repair_max_attempts
                and not self._over_cost_ceiling(total_cost)
                and not self._over_effort()
            ):
                attempts += 1
                self._set_state(ticket, JobState.REPAIRING)
                rep = self.agent.repair(
                    sandbox=self.sandbox, workspace=ws,
                    context=self._build_context(ticket, ws), failure_log=_failure_log(validations),
                )
                if rep.pause_reason:
                    return self._paused(ticket, rep.pause_reason, rep.retry_at, branch=branch,
                                        ws=ws, resume_handle=rep.resume_handle)
                for action in rep.actions:
                    self._emit(ticket, "agent_action", action, role="executor")
                self._emit(
                    ticket, "note", f"repair {attempts}: {rep.summary[:150]}", cost_usd=rep.cost_usd
                )
                total_cost += rep.cost_usd or 0.0
                self._count(rep, "repair")
                self._commit(ws, ticket)
                touched, validations = self._validate(ws, ticket)

            # Stopped repairing because the ticket got too expensive (not because it's
            # green): hold with a cost reason rather than the generic "validations failed".
            if not _all_passed(validations) and self._over_cost_ceiling(total_cost):
                return self._hold(
                    ticket, owner, self._cost_reason(total_cost),
                    JobState.ON_HOLD, branch=branch, total_cost_usd=self._reported_cost(),
                )

            result = RunResult(
                ticket_id=ticket.id, state=JobState.VALIDATING, branch=branch,
                touched_components=touched, validations=validations,
                repair_attempts=attempts, total_cost_usd=self._reported_cost(),
                spent_turns=getattr(self, "_turns", 0),  # effort accounting (D4)
                agent_runs=getattr(self, "_agent_runs", []),  # per-model/harness cost telemetry
            )
            self._record_risk(result)
            if not result.all_passed:
                reason = f"validations failed after {attempts} repair attempt(s)"
                result.state, result.note = JobState.ON_HOLD, reason
                mention = f"@{owner} " if owner else ""
                self._say_on_ticket(ticket.id, f"{mention}On hold — {reason}")
                self._set_state(ticket, JobState.ON_HOLD, reason=reason)
                return result

            # one diff, reused for the deterministic diff-hygiene gate and the reviewer
            _, diff = self.sandbox.run(
                workspace=ws, command=f"git diff {base}..HEAD", timeout=120
            )
            # AN EMPTY DIFF IS AN ANSWER, NOT AN ERROR (pilot, 2026-08-16). The agent can finish a
            # pass having changed nothing — the ticket asks for a configuration or a verification
            # rather than code, or what it asks for is already true — and that is an ordinary
            # outcome the ticket's author needs told, in those words.
            #
            # It used to be discovered three layers later, by GITHUB: the branch was pushed, the PR
            # was opened, and the forge refused with `GraphQL: No commits between main and
            # openfactory/89`, which landed on the operator's panel as the whole park note. A fact
            # about the ticket, reported as a provider's error string, after paying for a review
            # pass on a diff with nothing in it. Measured on `#89 feat(billing): validate real
            # Stripe checkout end-to-end in staging` — a ticket whose honest answer was "this is
            # not code", produced as a GraphQL failure.
            #
            # WHICH of the two it is, is NOT guessed: the platform cannot tell "no code was needed"
            # from "the agent found nothing to do", and asserting either would be inventing the
            # half a human is being asked for.
            if not diff.strip():
                return self._hold(
                    ticket, owner,
                    f"the agent finished its pass and changed nothing — there is no commit on "
                    f"`{branch}`, so nothing was pushed and no pull request was opened. Either "
                    f"this ticket does not need code (a configuration or verification task, which "
                    f"this factory does not perform), or what it asks for is already true in the "
                    f"repository. Re-scope it into the change you want made, or do it by hand and "
                    f"close it.",
                    JobState.NEEDS_REFINEMENT, branch=branch,
                    total_cost_usd=result.total_cost_usd)
            result.added_suppressions = _added_suppressions(diff)
            result.suppression_details = _suppression_details(diff)

            # D-6's OWN CATCH (ADR-0001, ADR-0002 §3): "the diff is the source of truth for scope
            # explosion, checked after execution — this complements the plan gate, which catches it
            # before any code is written." `max_touched_components`/`max_diff_lines` existed on the
            # manifest for this since before ADR-0013's transitional plan-gate rewrite, and nothing
            # ever read them: the promise in the field's own comment ("abort to refinement past
            # this") had no code behind it. Checked here, BEFORE suppression-repair or review spend
            # a cent on a ticket that already needs a human's judgment about scope, not a fix.
            over = scope_explosion(touched, diff, self.manifest)
            if over:
                return self._hold(
                    ticket, owner, over, JobState.NEEDS_REFINEMENT,
                    branch=branch, total_cost_usd=self._reported_cost(),
                )

            # Suppression-repair (ADR-0011): the diff added gate-suppression(s). Before EVER
            # bothering a human, let the executor RESOLVE them in the sandbox — remove the ones
            # it can make properly testable, keep only the genuinely-untestable wiring. This is
            # "the sandbox catches it and the agent fixes it". Bounded; a fix that breaks a gate
            # holds. Whatever survives is then vetted by the reviewer + should_auto_merge.
            supp_attempts = 0
            while (
                result.added_suppressions
                and supp_attempts < self.manifest.suppression_repair_max_attempts
                and not self._over_cost_ceiling(total_cost)
            ):
                found = ", ".join(sorted(set(result.added_suppressions)))
                self._emit(ticket, "note",
                           f"diff adds gate-suppression(s) [{found}] — resolving in the sandbox")
                supp_attempts += 1
                self._set_state(ticket, JobState.REPAIRING)
                rep = self.agent.repair(
                    sandbox=self.sandbox, workspace=ws, context=self._build_context(ticket, ws),
                    failure_log=_suppression_repair_brief(result.suppression_details),
                )
                if rep.pause_reason:
                    return self._paused(ticket, rep.pause_reason, rep.retry_at, branch=branch,
                                        ws=ws, resume_handle=rep.resume_handle)
                for action in rep.actions:
                    self._emit(ticket, "agent_action", action, role="executor")
                self._emit(ticket, "note",
                           f"suppression-repair {supp_attempts}: {rep.summary[:150]}",
                           cost_usd=rep.cost_usd, role="executor")
                total_cost += rep.cost_usd or 0.0
                result.total_cost_usd = self._reported_cost()
                self._commit(ws, ticket)
                touched, validations = self._validate(ws, ticket)  # must stay green
                result.touched_components, result.validations = touched, validations
                self._record_risk(result)
                if not _all_passed(validations):
                    reason = (f"suppression-repair {supp_attempts} broke a gate (coverage?) — "
                              "needs a human")
                    result.state, result.note = JobState.ON_HOLD, reason
                    mention = f"@{owner} " if owner else ""
                    self._say_on_ticket(ticket.id, f"{mention}On hold — {reason}")
                    self._set_state(ticket, JobState.ON_HOLD, reason=reason)
                    return result
                _, diff = self.sandbox.run(
                    workspace=ws, command=f"git diff {base}..HEAD", timeout=120
                )
                result.added_suppressions = _added_suppressions(diff)
                result.suppression_details = _suppression_details(diff)
            if result.added_suppressions:  # genuinely-necessary ones survived → reviewer vets them
                found = ", ".join(sorted(set(result.added_suppressions)))
                self._emit(ticket, "note",
                           f"kept necessary suppression(s) [{found}] — reviewer will vet them")

            if self.reviewer is not None and self.manifest.review_mode != "off":
                self._set_state(ticket, JobState.REVIEWING)
                result.review = self.reviewer.review(
                    sandbox=self.sandbox,
                    workspace=ws,
                    review_input=ReviewInput(
                        ticket=ticket, diff=diff, validations=result.validations
                    ),
                )
                self._count_review(result.review)
                advisory = self.manifest.review_mode != "blocking"
                self._emit(
                    ticket, "review",
                    f"{result.review.decision} (score {result.review.score})"
                    + (" · advisory" if advisory else ""),
                    findings=len(result.review.findings),
                    detail=_review_event_detail(result.review),
                )
                # ADR-0014: in ADVISORY mode the findings are posted to the PR (below) as a comment
                # for a human — they never trigger the repair loop or block the merge. The
                # deterministic gates + the executor's own TDD are the quality floor.
                # Review-repair loop (ADR-0006, BLOCKING only): a REJECTED review with actionable
                # findings earns a bounded autonomous fix — feed the findings to the executor,
                # re-run every gate, and take an INDEPENDENT re-review — before handing to a human.
                rev_attempts = 0
                while (
                    not advisory
                    and result.review.decision == "rejected"
                    and rev_attempts < self.manifest.review_repair_max_attempts
                    and _actionable_review(result.review)
                    and not self._over_cost_ceiling(total_cost)
                ):
                    rev_attempts += 1
                    self._set_state(ticket, JobState.REPAIRING)
                    rep = self.agent.repair(
                        sandbox=self.sandbox, workspace=ws,
                        context=self._build_context(ticket, ws),
                        failure_log=_review_findings_log(result.review),
                    )
                    if rep.pause_reason:
                        return self._paused(ticket, rep.pause_reason, rep.retry_at, branch=branch,
                                            ws=ws, resume_handle=rep.resume_handle)
                    for action in rep.actions:
                        self._emit(ticket, "agent_action", action, role="executor")
                    self._emit(
                        ticket, "note", f"review-repair {rev_attempts}: {rep.summary[:150]}",
                        cost_usd=rep.cost_usd, role="executor",
                    )
                    # count it like every other invocation: this one was missing from the
                    # per-model/harness telemetry entirely, so a ticket that survived review only
                    # after a repair under-reported both its spend and its effort
                    self._count(rep, "review_repair")
                    total_cost += rep.cost_usd or 0.0
                    result.total_cost_usd = self._reported_cost()
                    self._commit(ws, ticket)
                    touched, validations = self._validate(ws, ticket)  # the fix must stay green
                    result.touched_components, result.validations = touched, validations
                    self._record_risk(result)
                    if not _all_passed(validations):
                        reason = f"review-repair {rev_attempts} broke a gate"
                        result.state, result.note = JobState.ON_HOLD, reason
                        mention = f"@{owner} " if owner else ""
                        self._say_on_ticket(ticket.id, f"{mention}On hold — {reason}")
                        self._set_state(ticket, JobState.ON_HOLD, reason=reason)
                        return result
                    _, diff = self.sandbox.run(  # fresh diff for the guard + re-review
                        workspace=ws, command=f"git diff {base}..HEAD", timeout=120
                    )
                    result.added_suppressions = _added_suppressions(diff)
                    result.suppression_details = _suppression_details(diff)
                    self._set_state(ticket, JobState.REVIEWING)
                    result.review = self.reviewer.review(
                        sandbox=self.sandbox, workspace=ws,
                        review_input=ReviewInput(
                            ticket=ticket, diff=diff, validations=result.validations
                        ),
                    )
                    # The RE-review too. Counting only the first would make the repair loop — the
                    # branch that exists precisely because something went wrong, and therefore the
                    # expensive one — the cheapest-looking part of the ticket.
                    self._count_review(result.review)
                    self._emit(
                        ticket, "review",
                        f"{result.review.decision} (score {result.review.score})"
                        f" [after repair {rev_attempts}]",
                        findings=len(result.review.findings),
                        detail=_review_event_detail(result.review),
                    )

            # push the branch to the forge (as the bot, host credentials) before the PR
            self.sandbox.publish_branch(workspace=ws, remote_url=self.forge.push_remote())
            pr = self.forge.open_pr(
                head=branch, base=base, title=f"{ticket.id}: {ticket.title}",
                body=self._pr_body(ticket, result),
            )
            result.pr_url = pr
            self._emit(ticket, "pr", f"opened {pr}", url=pr)

            # the reviewer's verdict on the PR (D-5). ADR-0014: in advisory mode review_event()
            # returns "comment" — informational, never a blocking request-changes.
            if result.review is not None:
                self.forge.review_pr(
                    pr=pr,
                    event=review_event(result.review, self.manifest.review_mode),
                    body=format_review(result.review),
                )

            # merge posture (D-12): auto-merge only when policy allows and it's safe;
            # otherwise hand to humans — request reviewers + comment the ticket.
            result.environments = list(self.manifest.environments.keys())
            result.post_merge_deploy = self.manifest.post_merge_deploy  # ADR-0005 watch config
            if should_auto_merge(self.manifest, result,
                                 profile=getattr(self, "_profile", None)):
                held = self._auto_merge(ticket, ws, pr, base, branch, result, owner)
                if held is not None:  # couldn't merge cleanly → held for a human
                    return held
            else:
                self.forge.request_reviewers(pr=pr, reviewers=self.manifest.reviewers)
                # WHAT OUR OWN REVIEWER FOUND, IN THE ANNOUNCEMENT (#149). This said
                # `PR ready for review: <url>` and nothing else, so a rejected pull request was
                # announced in exactly the words of an approved one — and a chat- or Slack-only
                # operator (and everybody reading the ticket) had no way to tell them apart.
                # The gate item on the panel was taught to carry the verdict; this half was not.
                #
                # `headline` is the one renderer, shared with the panel, so the two surfaces
                # cannot come to describe the same verdict differently — and it treats an absent
                # review as its own answer rather than as a clean one.
                said = _review_sentence(result)
                ready = self._say("job.pr-ready", pr=pr, review=said)
                self._say_on_ticket(ticket.id, ready)
                result.state = JobState.PR_OPEN
                # THE READER IS THE BLOCKER (#166). `pr_open` is two situations under one name and
                # this is the human-gate one: reviewers were just requested and nothing moves until
                # somebody answers. The board said "In review" with `Needs Action` reading zero
                # about exactly this card, on the pilot's own screen.
                self._set_state(ticket, JobState.PR_OPEN, needs_person=True)
                self._notify(f"{ticket.id} {ready}", "info")
            return result
        finally:
            self.sandbox.cleanup(workspace=ws)
            # the fetched knowledge bundle is a temp checkout — one leaked per job
            # would fill the worker's finite disk.
            self._drop_published_bundle()

    def repair_ci(self, ticket_ref: str, ci_log: str, pr_url: str = "") -> RunResult:
        """React to a red CI on the open PR (ADR-0004): check out the PR branch, let the
        executor fix it from the CI failure log, and re-push — the gate-repair loop's
        philosophy, sourced from GitHub CI instead of the sandbox gates. One pass; the
        durable workflow drives the bounded loop and confirms the merge. Returns to
        PR_OPEN (auto-merge armed) so the workflow re-checks CI after the push — UNLESS the
        fix silenced a gate, in which case auto-merge is disarmed and the PR goes to a human."""
        ticket = self.tracker.get_ticket(ticket_ref)
        owner = self._owner_of(ticket_ref)
        base = ticket.base_branch or self.manifest.base_branch
        branch = self._job_branch(ticket)
        self._set_state(ticket, JobState.REPAIRING)
        ws = self.sandbox.prepare(
            repo_path=self.repo_path, base_branch=base, branch=branch, checkout_existing=True,
            # THE OPEN PR'S BRANCH LIVES ON THE FORGE, not in the worker's cache — and the cache
            # keeps a deliberately tokenless origin, so without this a repair on a private
            # repository cannot reach the very branch it exists to repair (fx-mono#1, 2026-08-04)
            remote_url=self.forge.push_remote(),
        )
        try:
            # WHAT THE REVIEWER READ, MEASURED BEFORE THIS PASS CAN TOUCH IT (#179). Every exit
            # below goes through `as_left`, including the ones that give up before the agent
            # writes a line: "the pass could not act" and "the pass rewrote the pull request" are
            # opposite facts, and the verdict's staleness turns on which one happened.
            before = self._pr_diff(ws, base)

            def as_left(res: RunResult) -> RunResult:
                """Stamp the outcome with whether this pass changed the pull request.

                MEASURED AT THE EXIT, not assumed from the branch taken. An agent has the checkout
                and the push remote in hand and may commit on its own before it gives up, so
                "we did not reach `_commit`" is not the same statement as "nothing moved"."""
                now = self._pr_diff(ws, base)
                changed = None if (before is None or now is None) else (now != before)
                return res.model_copy(update={"code_changed": changed})

            try:
                # `at_base=False`: this workspace is an open pull request's branch, never the base
                # commit, so the main gate's baseline is deliberately not taken here.
                self._run_setup(ticket, ws)
            except SetupFailed as exc:
                # A CI repair against an environment that will not build produces a second failing
                # CI run and an agent chasing a fault that is not in the diff.
                return as_left(
                    self._hold(ticket, owner, str(exc), JobState.FAILED, branch=branch))
            # A PASS-LOCAL CENSUS, AND IT ANSWERS A DIFFERENT QUESTION FROM THE MAIN GATE'S. Not
            # "did this ticket delete tests" — this tree is not the base commit and cannot answer
            # that — but "did THIS repair pass delete tests", which is the one that matters here:
            # the agent below is told the CI is failing and asked to make it pass, and deleting a
            # failing test or renaming it out of collection is the cheapest way to do that. It
            # emits no suppression token, so the guard beside it cannot see it.
            repair_census_before = self._take_census(ws)
            rep = self.agent.repair(
                sandbox=self.sandbox, workspace=ws, context=self._build_context(ticket, ws),
                failure_log=f"The GitHub CI for this PR is FAILING. Make it pass.\n\n{ci_log}",
            )
            for action in rep.actions:
                self._emit(ticket, "agent_action", action, role="executor")
            self._emit(
                ticket, "note", f"ci-repair: {rep.summary[:150]}",
                cost_usd=rep.cost_usd, role="executor",
            )
            # count it like every other invocation. This one was invisible to the per-model/harness
            # telemetry and to the D4 effort budget — the THIRD place today where an agent ran, cost
            # money, and appeared nowhere. A ticket whose CI needed fixing under-reported both.
            self._count(rep, "ci_repair")
            if rep.pause_reason:
                return as_left(self._paused(ticket, rep.pause_reason, rep.retry_at, branch=branch,
                                            ws=ws, resume_handle=rep.resume_handle))
            if not rep.ok:
                return as_left(self._hold(
                    ticket, owner, f"ci-repair agent stopped: {rep.summary}",
                    JobState.ON_HOLD, branch=branch, total_cost_usd=self._reported_cost(),
                ))
            self._commit(ws, ticket)
            self.sandbox.publish_branch(workspace=ws, remote_url=self.forge.push_remote())
            # Gate-suppression guard (engineering.md #12) on the CI-repair path too: if the fix
            # SILENCED a gate (a noqa / pragma-no-cover / type-ignore / nosec suppression), a
            # green CI no longer proves what it claims — it must NOT auto-merge. The main run()
            # path enforces this before merging via should_auto_merge; CI-repair re-pushes to an
            # already-armed --auto PR, so it must actively DISARM auto-merge and hand to a human.
            after = self._pr_diff(ws, base)
            diff = after or ""
            #: Did this pass actually move the pull request? The same measurement `as_left` takes
            #: at the exits (#179) — read once here because two things turn on it: the verdict's
            #: staleness, and whether the PR's own body has anything to be re-dated about.
            pushed = before is not None and after is not None and after != before
            supp = _added_suppressions(diff)
            # THE VERIFIER'S OWN INPUTS, ON THE PATH WHOSE INCENTIVE POINTS STRAIGHT AT THEM. This
            # agent is told "the CI for this PR is FAILING, make it pass", and the cheapest way to
            # stop a gate failing is to retune the gate in the file that names it. `should_auto_
            # merge` cannot help here: this pass pushes to a pull request whose auto-merge is
            # ALREADY ARMED, so the gate has to be re-asked and the arming actively withdrawn —
            # exactly the contract the suppression guard above states and, until review on #18,
            # honoured for suppressions alone. A deleted `.openfactory/project.yaml` guard emits no
            # suppression token and sailed through.
            hits = protected_violations(self._pr_diff_paths(ws, base), self.manifest)
            # AND THE WINDOW BETWEEN THE ARMING AND THIS PASS. `should_auto_merge` refused an
            # unreadable floor when this pull request was armed, so normally there is nothing to
            # disarm — but a redeploy between the two is exactly when the floor stops parsing, and
            # letting the arming stand because the check ran EARLIER is the silent widening the
            # closed direction exists to refuse.
            unreadable = protected_policy.floor_unreadable(self.manifest)
            # AND THE SUITE ITSELF. The census the main path runs never reaches here — `_validate`
            # is not called on this path and neither is `should_auto_merge` — so a repair that made
            # CI green by deleting the failing tests pushed to an armed auto-merge with nothing in
            # its way. Compared against this pass's own baseline, taken before the agent ran.
            repair_census_after = (self._take_census(ws)
                                   if repair_census_before is not None else None)
            lost_tests = repair_census_before is not None and (
                repair_census_after is None or len(repair_census_after) < len(repair_census_before))
            if supp or hits or unreadable or lost_tests:
                found = ", ".join(sorted(set(supp)))
                # ONE EXIT AND ONE MESSAGE SHAPE for both reasons: a second disarm branch beside
                # this one is a second place for the next guard to be forgotten.
                why = []
                if supp:
                    why.append(f"gate-suppression(s) [{found}]")
                if hits:
                    shown = ", ".join(hits[:protected_policy.MAX_SHOWN])
                    why.append(f"a change to the verifier's own inputs [{shown}]")
                if unreadable and not hits:
                    why.append("a protected-path floor this deployment can no longer read "
                               "(OUR install, not this repository)")
                if lost_tests:
                    gone = census_vanished(repair_census_before, repair_census_after or ())
                    why.append(census_policy.reason(
                        len(repair_census_before),
                        None if repair_census_after is None else len(repair_census_after),
                        gone[:census_policy.MAX_SHOWN], len(gone)))
                because = " and ".join(why)
                if pr_url:  # disarm the armed auto-merge so a later green CI can't land it
                    self.forge.disable_auto_merge(pr=pr_url)
                    self.forge.request_reviewers(pr=pr_url, reviewers=self.manifest.reviewers)
                self._emit(
                    ticket, "note",
                    f"ci-repair diff adds {because} — auto-merge disarmed, forcing human review",
                )
                # The pass pushed and no reviewer read what it pushed, so the verdict standing on
                # the pull request is about a diff that is gone. #187: say so THERE too.
                if pushed:
                    self._republish_review(pr_url, review=None)
                return as_left(self._hold(
                    ticket, owner,
                    f"ci-repair added {because} — needs human review",
                    JobState.ON_HOLD, branch=branch, total_cost_usd=rep.cost_usd,
                    added_suppressions=supp, suppression_details=_suppression_details(diff),
                ))
            # THE PASS REVIEWS WHAT IT PRODUCED (#155). This path rewrites a pull request that the
            # reviewer has already read, and nothing here re-read it — so the only content review
            # the platform had went on describing a diff that no longer existed. #153 made that
            # verdict declare itself out of date, which is honest and useless: it left the merge
            # gate with no reading of the code in hand and, at the time, no way to get one — on
            # the pilot the tech-lead correctly recommended a re-review that was not yet an action.
            # (#181 made it one. This still runs: a reading nobody has to ask for and pay for beats
            # one they do, and the person at the gate should not have to buy what a pass that was
            # already standing in the checkout could hand them.)
            #
            # It is cheap HERE and nowhere else: the checkout, the sandbox and the diff are all in
            # hand, three lines up. Asking for this from outside would mean a fresh clone.
            #
            # REPAIR-REPAIR IS NOT THIS LOOP'S JOB. A rejection is reported, not acted on: the
            # bounded review-repair loop belongs to `run()` in blocking mode, and a human gate is
            # already where this path ends. The point is that the person deciding sees a verdict
            # about the code they are deciding on.
            if self.reviewer is not None and self.manifest.review_mode != "off":
                self._set_state(ticket, JobState.REVIEWING)
                review = self.reviewer.review(
                    sandbox=self.sandbox, workspace=ws,
                    review_input=ReviewInput(ticket=ticket, diff=diff, validations=[]),
                )
                self._count_review(review)
                self._emit(
                    ticket, "review",
                    f"{review.decision} (score {review.score}) [after repair]",
                    findings=len(review.findings), detail=_review_event_detail(review),
                )
            else:
                review = None
            # AND THE PULL REQUEST'S OWN BODY CATCHES UP (#187). The panel's card learned to say
            # `Review out of date`; the pull request went on opening with the first verdict, no
            # marker and no date — and it is the surface a reviewer naturally opens and the only
            # one a collaborator without the panel token has. A fresh reading REPLACES the section;
            # without one, what stands is dated rather than deleted.
            if pushed or review is not None:
                self._republish_review(pr_url, review=review)
            self._emit(ticket, "pr", "ci-repair pushed — CI re-running", url="")
            # CI IS RE-RUNNING on a pull request this platform just pushed to: the machine is the
            # one working. Whether a person is then needed is decided when the watch ends.
            self._set_state(ticket, JobState.PR_OPEN, needs_person=False)
            return as_left(RunResult(
                ticket_id=ticket.id, state=JobState.PR_OPEN, branch=branch,
                auto_merge=True, total_cost_usd=rep.cost_usd, review=review,
            ))
        finally:
            self.sandbox.cleanup(workspace=ws)
            # the fetched knowledge bundle is a temp checkout — one leaked per job
            # would fill the worker's finite disk.
            self._drop_published_bundle()

    def review_pr(self, ticket_ref: str, pr_url: str = "") -> RunResult:
        """Read the open pull request again, as it stands now, and publish a fresh verdict (#181).

        THE CLOSING HALF OF THE ADJUST LOOP. `review rejects → adjust fixes it → ??? → merge`: the
        platform had three buttons at the gate and no way to ask whether the change answered the
        finding it was made for. Its own tech-lead guidance said so out loud, and until this landed
        it read: *"nothing here re-runs the reviewer on demand — that capability does not exist, so
        'ask for a new review pass' is advice nobody can take"*. Refusing to promise it was right,
        and refusing is not a capability. The operator was left to merge on their own reading of
        the diff, which is the work an independent review exists to remove.

        NO AGENT PASS AND NO `setup:`. This writes nothing: it checks the branch out, reads the
        diff and asks the reviewer. Running the project's build first would make an honest read of
        a diff cost what a repair costs, and nothing here needs the environment to work — the
        reviewer's input is the diff and the ticket.

        A PASS, NOT A PROMISE. A deployment with review turned off answers "nothing re-read it"
        rather than silently leaving the old verdict standing wearing a fresh timestamp: the
        caller can then say so at the gate, which is the only honest end to a button somebody
        pressed.
        """
        ticket = self.tracker.get_ticket(ticket_ref)
        base = ticket.base_branch or self.manifest.base_branch
        branch = self._job_branch(ticket)
        if self.reviewer is None or self.manifest.review_mode == "off":
            return RunResult(
                ticket_id=ticket.id, state=JobState.PR_OPEN, branch=branch, code_changed=False,
                note="this deployment has no reviewer — nothing re-read the pull request",
            )
        ws = self.sandbox.prepare(
            repo_path=self.repo_path, base_branch=base, branch=branch, checkout_existing=True,
            # the open PR's branch lives on the forge, and the cache keeps a tokenless origin
            remote_url=self.forge.push_remote(),
        )
        try:
            diff = self._pr_diff(ws, base)
            if diff is None:
                return RunResult(
                    ticket_id=ticket.id, state=JobState.PR_OPEN, branch=branch,
                    code_changed=False,
                    note="the pull request's diff could not be read — nothing was re-reviewed",
                )
            self._set_state(ticket, JobState.REVIEWING)
            review = self.reviewer.review(
                sandbox=self.sandbox, workspace=ws,
                review_input=ReviewInput(ticket=ticket, diff=diff, validations=[]),
            )
            self._count_review(review)
            self._emit(
                ticket, "review", f"{review.decision} (score {review.score}) [re-reviewed]",
                findings=len(review.findings), detail=_review_event_detail(review),
            )
            # AND THE PULL REQUEST SAYS WHAT THE CARD SAYS (#187). A re-review CLEARS the
            # out-of-date marker rather than adding a second one: the section is replaced by this
            # reading, which is about the diff as it stands.
            self._republish_review(pr_url, review=review)
            # THE PERSON IS STILL THE ONE DECIDING. Unlike a repair pass, nothing here changed the
            # pull request, so the gate they are standing at does not close — it re-opens with a
            # reading of the code in hand.
            self._set_state(ticket, JobState.PR_OPEN, needs_person=True)
            return RunResult(
                ticket_id=ticket.id, state=JobState.PR_OPEN, branch=branch, review=review,
                code_changed=False, total_cost_usd=self._reported_cost(),
            )
        finally:
            self.sandbox.cleanup(workspace=ws)
            self._drop_published_bundle()

    # -- journal helpers --

    def _run_setup(self, ticket: Ticket, ws: Workspace, *, at_base: bool = False) -> None:
        """Run the manifest's `setup:` commands, stopping at the first failure.

        STOPPING IS THE POINT. Later commands presuppose the earlier ones — `dotnet build` after a
        failed `dotnet restore` produces a second, misleading error stacked on the real one — and
        continuing to the agent spends money producing a diff against an environment that does not
        work, whose validations then fail for reasons that have nothing to do with the diff.

        Both call sites used to call `sandbox.run` and throw the result away (ADR-0037 D3)."""
        for cmd in self.manifest.setup:
            rc, out = self.sandbox.run(workspace=ws, command=cmd, timeout=_SETUP_TIMEOUT)
            if rc == 0:
                continue
            tail = "\n".join((out or "").splitlines()[-40:])
            self._emit(ticket, "warning", f"setup failed: {cmd} (exit {rc})")
            raise SetupFailed(
                f"the environment could not be prepared — `{cmd}` exited {rc}."
                + (f"\n\n```\n{tail}\n```" if tail else "")
            )
        # THE CENSUS'S "BEFORE", AND `at_base` IS THE WHOLE OF ITS CORRECTNESS. The inventory
        # command imports the test suite, so it needs the dependencies `setup:` just installed, and
        # this is the last moment of setup — but "the last moment of setup" is not the same fact as
        # "the tree is still the base commit", and the first revision confused them.
        #
        # A RESUMED ATTEMPT PREPARES WITH `checkout_existing=True`, so the checkout already carries
        # the agent's partial work: a baseline taken here would absorb tests the agent had already
        # deleted, `after >= before` for the rest of the job, and pausing and resuming would be all
        # it took to defeat this gate. The CI-repair path checks out an open pull request's branch
        # unconditionally, so its "before" would be a census of the finished PR.
        #
        # NO BASELINE IS BETTER THAN A WRONG ONE, because `before is not None` is what switches the
        # gate on: a resumed attempt is simply not censused, which is a coverage gap somebody can
        # see rather than a gate that silently cannot fire. Carrying the ORIGINAL baseline across
        # the pause is the right answer and is open work — it crosses the durable resume contract
        # (`run(resume_handle=...)` → `boxed_job` → the Temporal workflow), which is not something
        # to widen from inside this PR.
        if at_base:
            self._census_before = self._take_census(ws)

    def _owner_of(self, ticket_ref: str) -> str | None:
        """Whoever the ticket belonged to before the bot claimed it, or None.

        BEST-EFFORT ON PURPOSE, and swept here together with the claim itself. This read exists for
        exactly one thing — routing an impediment back to a person — and `ticket.author` is already
        the fallback at both call sites. Letting a rate limit or a permissions gap on a courtesy
        read abort a delivery is the same trade the claim used to make, and it is never the right
        one."""
        try:
            return next(
                (a for a in self.tracker.assignees(ticket_ref) if a != self.bot.login), None
            )
        except Exception as exc:  # noqa: BLE001 — an unknown owner is survivable; a lost job isn't
            log.warning("could not read who owns %s (%s) — impediments will go to the ticket's "
                        "author instead", ticket_ref, str(exc)[:160])
            return None

    def _emit(self, ticket: Ticket, kind: EventKind, message: str, **data: object) -> None:
        self.events.emit(
            JobEvent(
                ts=now_iso(), job_id=ticket.id, ticket_id=ticket.id,
                kind=kind, message=message, data=data,
            )
        )

    def _set_state(self, ticket: Ticket, state: JobState, reason: str | None = None, *,
                   needs_person: bool | None = None) -> None:
        # THE FORGE IS A MIRROR OF THE TRANSITION, NOT THE TRANSITION. What actually decides what
        # happens next is this platform's own record — the event, the RunResult, and the alarm the
        # caller raises after. Once every tracker write learned to report a refusal by raising,
        # this line became able to abort the exits that exist so nobody waits in silence: a forge
        # with a revoked token stopped jobs from parking at all, and the panel went on showing them
        # as running. So a mirror that cannot be updated is an ERROR somebody must act on, never a
        # reason to abandon the transition itself.
        try:
            self.tracker.set_state(ticket.id, state, reason=reason, needs_person=needs_person)
        except Exception as exc:  # noqa: BLE001 — the job still transitions; the board lags
            log.error("OPENFACTORY_TICKET_STATE_UNRECORDED ticket=%s -> %s (%s) — the platform "
                      "moved on "
                      "and the board still shows the old state", ticket.id, state.value,
                      str(exc)[:160])
        self._emit(ticket, "state", state.value, reason=reason)
        # The bot stopped actively working (parked / done / handed to a human) → drop the working
        # label so it never lingers on a ticket the bot has let go. Best-effort.
        #
        # THE LABEL IS ADDED AND REMOVED BY EXACT STRING, so the one spelling this platform writes
        # is the one it removes. A second spelling — a rename that ships a new label while boards
        # still carry the old one — leaves "being worked on" on a card nobody is working, on the
        # client's board, permanently; the platform carried the removal of its former label until
        # 2026-08-25 for that reason, and a future rename of `_BOT_WORKING_LABEL` owes the same.
        if state not in _WORKING_STATES:
            try:
                self.tracker.remove_label(ticket.id, _BOT_WORKING_LABEL)
            except Exception as exc:  # noqa: BLE001 — never derail a job over a label
                # It lingers on a ticket the bot has let go, which reads as "still being worked
                # on" to anybody looking at the board.
                log.warning("the working label %r lingers on %s (%s)",
                            _BOT_WORKING_LABEL, ticket.id, str(exc)[:120])

    @staticmethod
    def _trajectory_of(res: AgentRunResult) -> dict:
        """What this pass DID, as metric dimensions — or nothing measured, said as nothing.

        AN EMPTY `raw_output` MUST NOT BECOME A MEASURED ZERO, and this is the whole reason the
        method exists rather than being three inline lines. `raw_output` defaults to `""`, and
        `pulses_of(harness, "")` answers `[]` — "read it, it held no events" — which summarises to
        a perfectly readable trajectory of zero tool calls. Recorded, that says the agent called no
        tools; what actually happened is that nobody captured its output. A pass whose stream was
        never captured and a pass that genuinely did nothing must not land in the same row, so an
        empty stream leaves every dimension None.

        Never raises: every caller is on the path of a pass that already happened, and telemetry
        that took a job down would be worse than telemetry that is absent."""
        if not (res.raw_output or "").strip():
            return {}
        try:
            from openfactory.adapters.agent.stream import pulses_of
            from openfactory.observability.trajectory import trajectory_of

            t = trajectory_of(pulses_of(res.harness or "", res.raw_output))
            if not t.readable:
                return {}
            return {"tool_calls": t.tool_calls, "repeated_calls": t.repeated,
                    "refused_calls": t.refused, "turns_to_first_edit": t.turns_to_first_edit}
        except Exception:  # noqa: BLE001 — a reading that fails is an absent number, not a crash
            log.warning("could not read the trajectory of a %s pass — the run is unaffected and "
                        "its trajectory dimensions are absent rather than zero", res.harness,
                        exc_info=True)
            return {}

    def _count(self, res: AgentRunResult, role: str = "") -> None:
        """Accumulate the ticket's effort (agent turns) — the budget's currency (ADR-0013 D4) —
        and collect this invocation's cost telemetry (observability.metrics) tagged with its
        role/model/harness, so the workflow can persist spend by dimension on completion."""
        self._turns = getattr(self, "_turns", 0) + (res.num_turns or 0)
        if not hasattr(self, "_agent_runs"):
            self._agent_runs = []  # lazily init on flows that don't go through run() (CI-repair)
        self._agent_runs.append(AgentRunMetric(
            role=role or "agent", model=res.model or "", harness=res.harness or "",
            cost_usd=res.cost_usd, num_turns=res.num_turns,
            input_tokens=res.input_tokens, output_tokens=res.output_tokens,
            **JobRunner._trajectory_of(res)))

    def _count_review(self, review) -> None:
        """Count the review as the agent pass it is.

        `_count` takes an `AgentRunResult`; a review comes back as a `ReviewResult`, so the two
        never met and the review's spend was simply absent from `_agent_runs`. With review ON by
        default and a whole independent pass over the full diff, the PR's `Cost:` line understated
        every ticket while presenting itself as the total."""
        if review is None or getattr(review, "cost_usd", None) is None:
            return
        if not hasattr(self, "_agent_runs"):
            self._agent_runs = []
        self._agent_runs.append(AgentRunMetric(
            role="review", model=review.model or "", harness=review.harness or "",
            cost_usd=review.cost_usd, num_turns=review.num_turns,
            input_tokens=review.input_tokens, output_tokens=review.output_tokens))

    def _reported_cost(self) -> float | None:
        """The ticket's cost — summing ONLY invocations that actually reported one, and None when
        nobody did.

        The old accumulation used `cost_usd or 0.0`, so a harness that does not emit cost (Codex
        reports tokens but no price) produced `total_cost_usd = 0.0`. The dashboard then renders
        $0.00 and that harness looks FREE — it would silently win every cost comparison, which is
        the exact opposite of what the telemetry exists to do. Unknown must read as unknown."""
        costs = [m.cost_usd for m in getattr(self, "_agent_runs", []) if m.cost_usd is not None]
        return sum(costs) if costs else None

    def _over_effort(self) -> bool:
        return getattr(self, "_turns", 0) >= self.manifest.effort_budget_turns

    def _effort_reason(self) -> str:
        return (f"effort budget exhausted ({getattr(self, '_turns', 0)}/"
                f"{self.manifest.effort_budget_turns} turns) — the pre-flight gate under-sized "
                "this ticket. Decide: split the remainder into a follow-up ticket, or raise "
                "effort_budget_turns and Resume (the partial work is preserved).")

    def _emit_credential(self, ticket: Ticket, res: object) -> None:
        """Surface WHICH credential the agent used (and whether it rotated) — agnostic panel
        visibility + proof that failover happens. The adapter fills `credential`; the core never
        reads the token itself. No-op for a keyless/single-credential adapter."""
        c = getattr(res, "credential", None)
        if not c:
            return
        rot = " · rotated ↻" if c.get("rotated") else ""
        self._emit(ticket, "note", f"credential {c.get('index')}/{c.get('total')} "
                                   f"({c.get('id')}){rot}", credential=c)

    def _is_e2e_ticket(self, ticket: Ticket) -> bool:
        """An on-demand e2e run (ADR-0008): the manifest declares an e2e workflow AND the ticket
        carries the e2e label. Then we don't implement — we just run e2e and report."""
        return bool(self.manifest.e2e_workflow) and \
            self.manifest.e2e_label.lower() in ticket.labels

    def _run_e2e_check(self, ticket: Ticket, owner: str | None) -> RunResult:
        """Dispatch the project's e2e workflow, watch it to completion, and report pass/fail on
        the ticket — no plan, no code, no PR (ADR-0008). Lets e2e leave the every-PR CI and run
        deliberately via a labelled ticket."""
        wf = self.manifest.e2e_workflow or ""
        base = ticket.base_branch or self.manifest.base_branch
        self._set_state(ticket, JobState.VALIDATING)
        self._emit(ticket, "note", f"e2e ticket — dispatching `{wf}` on {base} (no code change)")
        # Pin the run that exists BEFORE we dispatch. We then watch for a run with a DIFFERENT
        # id — the exact run we triggered — instead of comparing timestamps across the
        # container↔GitHub clock boundary (a race that can grab an old run or falsely time out)
        # or blindly taking latest_run (which any other trigger could win). (F3)
        try:
            prev = self.forge.latest_run(workflow=wf)
            prev_id = prev.get("id") if prev else None
        except Exception as exc:  # noqa: BLE001 — no baseline is survivable; a silent one is not
            # No baseline means the next run looks new whatever happens. Fine when there genuinely
            # was no previous run, misleading when the Actions API is simply unreadable — and the
            # wait that follows would otherwise sit there with nothing to explain it.
            log.warning("could not read the previous run of %s (%s) — the next run will be taken "
                        "as new, so a stale one may be mistaken for ours", wf, exc)
            prev_id = None
        try:
            self.forge.dispatch_workflow(workflow=wf, ref=base)
        except Exception as exc:
            return self._hold(ticket, owner, f"couldn't dispatch e2e `{wf}`: {exc}",
                              JobState.ON_HOLD)
        run: dict | None = None
        errors, last_err = 0, ""
        deadline = time.monotonic() + _E2E_TIMEOUT
        while time.monotonic() < deadline:
            time.sleep(_E2E_POLL)
            try:
                r = self.forge.latest_run(workflow=wf)
            except Exception as exc:
                # A transient blip is fine (retry); a PERSISTENT failure (revoked token, 5xx
                # storm) must not masquerade as a 25-min "didn't finish" timeout — report the
                # real cause so a human fixes the right thing (M5).
                errors += 1
                last_err = str(exc)
                if errors >= _E2E_MAX_ERRORS:
                    return self._hold(
                        ticket, owner,
                        f"couldn't read the e2e run after {errors} tries ({last_err[:150]}) — "
                        "check the bot's Actions access", JobState.ON_HOLD)
                continue
            errors = 0
            if not r or r.get("id") == prev_id:
                continue  # our dispatched run hasn't shown up yet (still the pre-dispatch run)
            run = r
            if r.get("status") == "completed":
                break
        if run is None or run.get("status") != "completed":
            url = (run or {}).get("url")
            return self._hold(ticket, owner, f"e2e run didn't finish in the watch window — {url}",
                              JobState.ON_HOLD, pr_url=url)
        url = run.get("url")
        passed = (run.get("conclusion") or "").lower() == "success"
        self._emit(ticket, "note", f"e2e {'PASSED' if passed else 'FAILED'} — {url}")
        if passed:
            self._say_on_ticket(ticket.id, self._say("job.e2e-passed", url=url))
            self._set_state(ticket, JobState.DONE)
            return RunResult(ticket_id=ticket.id, state=JobState.DONE, pr_url=url)
        return self._hold(ticket, owner, f"e2e suite is RED — {url}", JobState.ON_HOLD, pr_url=url)

    def _hold(
        self, ticket: Ticket, owner: str | None, reason: str, state: JobState, **extra: object
    ) -> RunResult:
        """Impediment: comment the reason, return the ticket to its owner, and stop
        (an alarm on the panel). With no parallelism the framework does not pick up
        another task — it halts here."""
        verb = self._say("job.verb.needs-refinement"
                         if state == JobState.NEEDS_REFINEMENT else "job.verb.on-hold")
        mention = f"@{owner} " if owner else ""
        self._say_on_ticket(ticket.id, self._say("job.hold", mention=mention, verb=verb,
                                                 reason=reason))
        # return the ticket to the owner (or leave it unassigned if there was none)
        # BEST-EFFORT, LIKE EVERY OTHER FORGE WRITE ON THIS PATH. Handing the ticket back is
        # valuable and it is not the act: the act is that this job STOPS and a person is told. A
        # forge refusing this call must not leave the platform believing the job is still running.
        if self.bot.login:
            try:
                self.tracker.set_assignees(ticket.id, [owner] if owner else [])
            except Exception as exc:  # noqa: BLE001 — the park stands; the handover did not
                log.error("OPENFACTORY_TICKET_UNASSIGNED ticket=%s owner=%s (%s) — the job parked "
                          "and the "
                          "ticket did not go back to anybody", ticket.id, owner or "-",
                          str(exc)[:160])
        self._set_state(ticket, state, reason=reason)
        self._notify(self._say("job.needs-you", ticket=ticket.id, state=state.value,
                               reason=reason), "action_required")
        extra.setdefault("agent_runs", getattr(self, "_agent_runs", []))  # spend before the park
        return RunResult(ticket_id=ticket.id, state=state, note=reason, **extra)  # type: ignore[arg-type]

    def _say(self, key: str, **params: object) -> str:
        """One catalogue entry, in this project's language (#160).

        EVERY SENTENCE THIS MACHINE PRODUCES IS UNPROMPTED — it comments on a ticket and posts to
        a channel to say what it just did, and nobody asked it to. `self.project` is the registry
        row and carries the language; absent (an ad-hoc construction) means English, which is what
        a deployment that configured nothing would get anyway.
        """
        return tl_voice.say(tl_voice.NARRATION, key,
                            str(getattr(self.project, "language", "") or ""), **params)

    def _notify(self, message: str, level: Level = "info") -> None:
        try:  # a broken channel must never fail the job
            self.notifier.notify(message=message, level=level)
        except Exception as exc:  # noqa: BLE001
            # A notifier that has been failing for a week looks exactly like a quiet week.
            log.warning("notification not delivered (%s): %s", str(exc)[:120], message[:120])

    def _say_on_ticket(self, ticket_id: str, body: str) -> None:
        """Write a comment that DESCRIBES what this machine just did, or is about to do.

        A COURTESY COMMENT MUST NEVER UNDO THE ACT IT DESCRIBES, and until the tracker learned to
        report a refused write that rule cost nothing to break: `comment` swallowed every failure,
        so nobody had to think about it. The moment the adapter started raising — correctly; a write
        that did not happen must not look like one that did — the first statement of `_hold` became
        able to abort the park. `_hold` IS the platform's no-silent-wait exit: it returns the ticket
        to its owner and raises the alarm, and a job that cannot say so must still park.

        So the failure is loud and the act continues. Losing the comment costs an audit trail, which
        is why this is an ERROR with a greppable marker rather than a shrug; losing the park costs a
        job nobody knows is stuck, which is the thing this platform exists to make impossible.
        """
        try:
            self.tracker.comment(ticket_id, body)
        except Exception as exc:  # noqa: BLE001 — the act stands; only the telling failed
            log.error("OPENFACTORY_TICKET_COMMENT_LOST ticket=%s (%s) — the tracker refused the "
                      "comment; "
                      "what it described still happened, and the ticket does not say so: %s",
                      ticket_id, str(exc)[:160], body[:160])

    def _paused(
        self, ticket: Ticket, reason: str | None, retry_at: str | None, branch: str = "",
        ws: Workspace | None = None, resume_handle: str | None = None,
    ) -> RunResult:
        """The agent can't proceed for an infra reason — not a code failure. A usage
        limit → PAUSED (the workflow resumes it durably after a backoff). An auth
        problem → ON_HOLD: retrying is pointless until a human fixes the token, and a
        PAUSED auth failure would burn ~48 futile resume launches (R9).

        C2: on a resumable (rate-limit) pause we PRESERVE the partial work — commit what the
        agent wrote so far and push the branch — and carry the agent's opaque `resume_handle`
        on the result, so the durable resume CONTINUES this attempt instead of restarting it."""
        handle = None
        if reason == "rate_limit":
            until = (self._say("job.paused-rate.until", retry_at=retry_at) if retry_at else "")
            msg = self._say("job.paused-rate", until=until)
            # THE NOTE STAYS ENGLISH, and stays built from its own words: it is an identity, not
            # prose. `classify()` reads it to decide what kind of failure this was and `memory`
            # hashes it to recognise the same failure twice — a note that changes with the
            # project's language would make the same park unrecognisable across two deployments.
            note = f"rate limited{f' — resumes after {retry_at}' if retry_at else ''}"
            state = JobState.PAUSED
            handle = self._preserve_partial(ticket, ws, branch, resume_handle)
        else:
            msg = self._say("job.auth-failed")
            note = "agent auth failed"
            state = JobState.ON_HOLD  # human-fixable only; never auto-resumed
        self._say_on_ticket(ticket.id, msg)
        self._emit(ticket, "warning", note, reason=reason, retry_at=retry_at)
        self._set_state(ticket, state, reason=note)
        self._notify(f"{ticket.id}: {note}", "warning")
        return RunResult(ticket_id=ticket.id, state=state, branch=branch, note=note,
                         retry_at=retry_at, resume_handle=handle,
                         spent_turns=getattr(self, "_turns", 0),
                         agent_runs=getattr(self, "_agent_runs", []))

    def _preserve_for_hold(
        self, ticket: Ticket, ws: Workspace, resume_handle: str | None
    ) -> str | None:
        """ADR-0013 D1 — preserve on a NON-pause stop (turn cap, agent stop, cost ceiling):
        commit + push whatever the agent wrote, and return the handle ONLY when there was real
        work to preserve. A hold that carries a handle is a RESUMABLE hold (the operator's
        Resume continues the attempt); no work → None → today's fresh-restart semantics (a
        spec-style hold must not turn into a bogus 'continue')."""
        try:
            self._commit(ws, ticket)  # no-ops on an empty tree
            if not self.sandbox.diff_paths(workspace=ws):
                return None  # nothing was written → plain hold, fresh restart on resume
            self.sandbox.publish_branch(workspace=ws, remote_url=self.forge.push_remote())
            self._emit(ticket, "note", "partial work pushed — Resume will continue it")
            # No session known → a non-empty sentinel: it still signals "restore the branch"
            # (bool-truthy) while decoding to nothing in any adapter (cold session, warm code).
            return resume_handle or "worktree-only"
        except Exception as exc:  # noqa: BLE001 — preserving is opportunistic; never fail the hold
            self._emit(ticket, "warning", f"couldn't preserve partial work ({str(exc)[:120]})")
            return None

    def _preserve_partial(
        self, ticket: Ticket, ws: Workspace | None, branch: str, resume_handle: str | None
    ) -> str | None:
        """Push whatever the agent wrote before the pause to the branch, so the resumed run
        (a fresh, ephemeral container) can restore it via checkout_existing. Returns the opaque
        resume_handle to round-trip — but only if the partial was actually preserved, so a
        resume never checks out a branch that was never pushed. Best-effort: any failure just
        degrades to a fresh restart (today's behaviour), never crashes the pause."""
        if ws is None:
            return resume_handle  # local/test path with no real git remote — nothing to push
        try:
            self._commit(ws, ticket)  # commit the partial tree (no-op if the agent wrote nothing)
            self.sandbox.publish_branch(workspace=ws, remote_url=self.forge.push_remote())
            self._emit(ticket, "note", "partial work pushed — resume will continue it")
            return resume_handle
        except Exception as exc:  # noqa: BLE001 — preserving is opportunistic; never fail the pause
            self._emit(ticket, "warning", f"couldn't preserve partial work ({str(exc)[:120]}) — "
                                          "resume will start fresh")
            return None  # no branch pushed → the resume must NOT try to check it out

    def _spec_validation(self, ticket: Ticket) -> None:
        """Deterministic spec-quality gate (D-8). Must NOT judge front/back — that is
        resolved from the diff (D-6). An optional LLM score is a later second stage."""
        if not ticket.objective.strip():
            raise SpecValidationError("ticket has no objective")
        if not ticket.acceptance_criteria:
            _spec_refusal(ticket)
        overlap = set(ticket.in_scope) & set(ticket.out_of_scope)
        if overlap:
            raise SpecValidationError(f"items in both in_scope and out_of_scope: {sorted(overlap)}")
        # TODO(next): referenced docs/deps exist (repo-dependent) + optional LLM judge score.

    def _plan_gate(
        self, ticket: Ticket, plan: str, owner: str | None, branch: str
    ) -> RunResult | None:
        """In-run sizing net (ADR-0002, transitional under ADR-0013). Sizing is now INVEST-only
        and primarily done by the pre-flight gate BEFORE Fargate — so this keeps ONLY the
        planner's explicit `SPLIT NEEDED` verdict (a cohesion judgment) and no longer enforces a
        file/step COUNT budget (owner decision: file count is not a sizing criterion). Retires
        entirely once the pre-flight gate is proven live (ADR-0013 Phase 5)."""
        split = re.search(r"SPLIT NEEDED:.*", plan, re.IGNORECASE | re.DOTALL)
        if split:
            return self._hold(
                ticket, owner, f"ticket too large — {split.group().strip()[:400]}",
                JobState.NEEDS_REFINEMENT, branch=branch,
            )
        return None

    def _plan_decision_gate(
        self, ticket: Ticket, plan: str, owner: str | None, branch: str
    ) -> RunResult | None:
        """Route the planner's structured status (ADR-0013 companion): `blocked` → PARK with a
        DecisionRequest so a human/bot picks a way forward (no park without options — owner);
        `assume` → record the assumption on the ticket + carry it into the PR, then proceed;
        `proceed`/none → run on. A decision already injected THIS run (a resumed blocker) is
        trusted and never re-blocks — so a resolved decision can't loop the gate."""
        if self._decision:  # the human already answered a blocker → proceed, don't re-ask
            return None
        m = re.search(r'"status"\s*:\s*"(proceed|assume|blocked)"', plan, re.IGNORECASE)
        status = (m.group(1).lower() if m else "proceed")
        if status == "blocked":
            dr = parse_decision(plan)
            if dr is None:  # blocked but gave no options → a bare needs-refinement (never silent)
                return self._hold(
                    ticket, owner, "the planner blocked but proposed no options — refine the "
                    "ticket or split it", JobState.NEEDS_REFINEMENT, branch=branch)
            dr.stage = dr.stage or "plan"
            self._record_decision(ticket, dr)
            return self._hold(
                ticket, owner, f"decision needed — {dr.question[:200]}",
                JobState.BLOCKED, branch=branch, decision=dr)
        if status == "assume":
            am = re.search(r'"assumption"\s*:\s*"((?:[^"\\]|\\.){1,400})"', plan)
            note = (am.group(1) if am else "").strip() or "(assumption recorded)"
            self._say_on_ticket(ticket.id, self._say("job.assumption", note=note))
            self._emit(ticket, "note", f"assumption: {note}", role="planner")
            self._assumptions.append(note)
        return None

    def _record_decision(self, ticket: Ticket, dr: DecisionRequest) -> None:
        """Post the DecisionRequest on the ticket so the question + options are DURABLE and
        answerable from any channel (the board is an interface — owner). The panel/API surface
        the same options live; `decisão: <key>` works in the CHANNEL (Slack), where a listener
        actually reads replies — nothing reads ticket comments back, and for months this comment
        said "reply here" about the one surface that could never hear the answer (#24 item 1)."""
        lines = [
            f"- **{o.key}** — {o.label}" + (f" · {o.consequence}" if o.consequence else "")
            + ("  _(recommended)_" if o.recommended else "")
            for o in dr.options
        ]
        body = (
            f"**Decision needed** — the job is on hold until you choose.\n\n"
            f"**{dr.question}**\n\n"
            + (f"{dr.context}\n\n" if dr.context else "")
            + "\n".join(lines)
            + "\n\nAnswer on the panel, or in the project channel with `decis\u00e3o: <key>`."
        )
        try:
            self.tracker.comment(ticket.id, body)
        except Exception as exc:  # noqa: BLE001 — recording is best-effort; the park still holds
            # The options exist only on the panel now: whoever reads the ticket sees a park with no
            # way to answer it.
            log.warning("could not record the decision options on %s (%s)",
                        ticket.id, str(exc)[:120])

    def _auto_merge(
        self, ticket: Ticket, ws: Workspace, pr: str, base: str, branch: str,
        result: RunResult, owner: str | None,
    ) -> RunResult | None:
        """Merge on the CURRENT base (merge-queue-lite; the framework is serial). Rebase onto
        the latest base first: if the base moved while the ticket ran, re-validate the merged
        result and re-push before merging — so nothing lands stale (a textual merge that
        breaks against newer code never sneaks in). A textual conflict, a post-rebase
        validation failure, or an unmergeable PR holds for a human — it never crashes."""
        status = self.sandbox.rebase_onto_base(
            workspace=ws, base=base, remote_url=self.forge.push_remote()
        )
        if status == "conflict":
            return self._hold(
                ticket, owner,
                f"PR {pr} conflicts with {base} and cannot be auto-rebased — needs a human "
                "rebase", JobState.ON_HOLD, branch=branch, total_cost_usd=result.total_cost_usd,
            )
        if status == "rebased":  # base advanced → the merged result must still pass every gate
            self._emit(ticket, "pr", f"{base} advanced — rebased, re-validating", url=pr)
            self._set_state(ticket, JobState.VALIDATING)
            _, result.validations = self._validate(ws, ticket)
            if not _all_passed(result.validations):
                return self._hold(
                    ticket, owner,
                    f"PR {pr} rebased onto {base} but validations then failed — needs a human",
                    JobState.ON_HOLD, branch=branch, total_cost_usd=result.total_cost_usd,
                )
            self.sandbox.publish_branch(workspace=ws, remote_url=self.forge.push_remote())
        try:
            self.forge.merge_pr(pr=pr)
        except Exception as exc:  # e.g. a race re-drifted it, or the merge is truly blocked
            return self._hold(
                ticket, owner,
                f"PR {pr} could not be merged ({str(exc)[:150]}) — needs a human",
                JobState.ON_HOLD, branch=branch, total_cost_usd=result.total_cost_usd,
            )
        # merge_pr either merged NOW (CI green / no required checks) or ARMED auto-merge
        # (required CI still pending). Only claim MERGED when it truly is; otherwise hand the
        # durable workflow the CI-watch/repair/merge loop (ADR-0004) — a red CI gets fixed,
        # not left armed forever.
        if self.forge.pr_merged(pr=pr):
            self._emit(ticket, "pr", "auto-merge complete", url=pr)
            result.state = JobState.MERGED
            self._set_state(ticket, JobState.MERGED)
            self._notify(self._say("job.merged", ticket=ticket.id, pr=pr), "info")
            return None
        self._emit(ticket, "pr", "auto-merge armed — awaiting CI", url=pr)
        result.state = JobState.PR_OPEN
        result.auto_merge = True
        # THE MACHINE IS WATCHING CI and nobody is needed — `In review` is the right column, and
        # saying so explicitly is what stops the default from having to mean two things.
        self._set_state(ticket, JobState.PR_OPEN, needs_person=False)
        return None

    def _over_cost_ceiling(self, cost: float) -> bool:
        """True once cumulative agent spend passes the manifest ceiling (ADR-0002) — the
        economic runaway guard, independent of the turn cap. No ceiling set → never trips."""
        return self.manifest.max_cost_usd is not None and cost > self.manifest.max_cost_usd

    def _cost_reason(self, cost: float) -> str:
        return (
            f"cost ceiling reached (${cost:.2f} > ${self.manifest.max_cost_usd:.2f}) — "
            "held for review; split the ticket or raise max_cost_usd"
        )

    def _knowledge_bundle(self, ticket: Ticket, tree: Path | None = None) -> Path | None:
        """The module map for THIS job, generated from THIS checkout (ADR-0023).

        DERIVED, NOT CACHED. The map is a pure function of the tree — same code in, same map out —
        and generating it costs 0.24s for 215 files (measured 2026-07-29). It used to be fetched
        from a published branch, which made it a CACHE: correct only while nothing had moved since
        the last publish. The publish fired on factory merges alone, so any other push — a person
        merging a PR, a hotfix, a dependency bump — left it describing an older commit. On
        2026-07-26 that window was TWENTY-TWO HOURS, and every job inside it found the checksums
        mismatched and ran with no map at all. Including #478, the ticket the A/B existed to
        measure: the experiment was quietly comparing two control arms.

        GENERATED FROM THE TREE THE AGENT WILL READ — `tree` is the sandbox workspace, and it
        falls back to `repo_path` only when there is no separate one. Getting this wrong is the
        same mistake one level down: `repo_path` is the shared, long-lived base clone, while the
        agent works in the workspace, so a map generated from the base would vouch for a tree
        nobody is looking at. An existing test caught exactly that in the first version of this
        method — the architecture is "derive from the tree in use", and the base clone is not it.

        There is no drift to detect and no trigger to get right.

        Written OUTSIDE the workspace: a bundle inside the agent's tree would be swept into the
        ticket's commit by `git add -A`, and every client PR would carry a copy of the map.

        Best-effort: a generation failure degrades to no map and says why. It is a navigation aid
        (ADR-0017 §7 — the code is the ground truth), never a reason to fail a ticket."""
        if not self.manifest.knowledge_map:
            return None
        if hasattr(self, "_bundle_dir"):
            return self._bundle_dir

        import time

        # THE CONTROL ARM GENERATES AND THROWS IT AWAY (ADR-0023 §4b). Skipping generation for the
        # control would be cheaper and would make the two arms differ in TWO variables — the
        # injection and ~0.3s of CPU — so any measured difference would have two explanations and
        # the convenient one would be chosen. The A/B exists to support a commercial claim; an
        # experiment that cannot support it is worse than none. The waste is a third of a second.
        treated = self._experiment_arm()

        started = time.perf_counter()
        try:
            from openfactory.knowledge.pipeline import generate_bundle_for

            generated = generate_bundle_for(tree or self.repo_path)
            elapsed = time.perf_counter() - started
            if treated:
                self._bundle_dir = generated
            else:
                # generated, measured, discarded — the arms now differ only in the injection
                from openfactory.knowledge.pipeline import discard_fetched_bundle

                discard_fetched_bundle(generated)
                self._bundle_dir = None
            # The bound is a NUMBER SOMEBODY SEES, not a limit that trips. A ten-thousand-file
            # monorepo would take ~11s — fine against a twenty-minute job, and something an
            # operator should learn from a log rather than from a mystery.
            if elapsed > _KNOWLEDGE_SLOW_SECONDS:
                self._emit(ticket, "warning",
                           f"knowledge: the map took {elapsed:.1f}s to generate — still cheap "
                           f"against a whole job, but worth knowing as the repo grows")
        except Exception as exc:  # noqa: BLE001 — knowledge is a bonus; never fail the job
            self._emit(ticket, "warning",
                       f"knowledge: could not generate the map ({str(exc)[:120]}) — "
                       "the agent runs without it")
            self._bundle_dir = None
        return self._bundle_dir

    def _drop_published_bundle(self) -> None:
        """Delete the generated bundle's temp directory. Always called from `run`'s `finally` —
        a leaked directory per job fills the worker's disk."""
        d = getattr(self, "_bundle_dir", None)
        if d is None:
            return
        from openfactory.knowledge.pipeline import discard_fetched_bundle

        discard_fetched_bundle(d)  # the temp layout is the pipeline's business, not ours
        self._bundle_dir = None

    def _build_context(self, ticket: Ticket, ws: Workspace | None = None) -> AgentContext:
        # The knowledge bundle is read from the JOB'S OWN CHECKOUT (`ws.host_path`), not from the
        # shared base clone — the map an agent verifies against must describe the code it is
        # looking at. And freshness is decided ONCE, on the clean initial checkout, then reused
        # for every repair/recovery context: those are built AFTER the agent edited the
        # workspace, so recomputing there would judge the bundle stale against the agent's own
        # uncommitted changes (a false positive that drops the map exactly when it is still
        # valid). `ws=None` (or a sandbox with no host-visible path) degrades to repo_path.
        ctx = build_context(self.manifest, self.repo_path, ticket,
                            knowledge_map=getattr(self, "_knowledge_map", None),
                            knowledge_path=ws.host_path if ws else None,
                            knowledge_bundle_dir=self._knowledge_bundle(
                                ticket, ws.host_path if ws else None),
                            # resolved once at the top of the job; `getattr` because not every
                            # path through this class reaches that point (the sizer builds a
                            # context of its own), and a missing class is the ordinary case.
                            profile=getattr(self, "_profile", None))
        if not hasattr(self, "_knowledge_map"):
            self._knowledge_map = ctx.knowledge_map  # freeze the clean-pass decision
        return ctx

    def _experiment_arm(self) -> bool:
        """Whether this ticket gets the map, when an A/B window is open. Decided ONCE per job and
        remembered: a second call mid-job that flipped would give the agent a map its own arm label
        denies, and the measurement would describe neither arm."""
        if not hasattr(self, "_arm_choice"):
            from openfactory.knowledge.experiment import arm_from_env

            assigned = arm_from_env()
            # None = nobody is running an experiment, so behave exactly as before: the project's
            # `knowledge_map` alone decides, and this method is a no-op.
            self._arm_choice = True if assigned is None else assigned
        return self._arm_choice

    def knowledge_arm(self) -> str:
        """Which A/B arm this run belongs to — see `RunResult.knowledge`. Reads the frozen
        clean-pass decision, so it reports what the agent was actually given, not the config.

        THREE OUTCOMES, and conflating the last two breaks the experiment. `off` means the map was
        deliberately withheld: either the project never opted in, or the A/B assigned this ticket to
        the control. `unavailable` means it opted in, this ticket was meant to have the map, and the
        map could not be trusted for that checkout — a control by accident rather than by choice.

        Reporting a deliberate control as `unavailable` is not a labelling nit: the arm chooser
        ignores `unavailable` precisely because nobody chose it, so every control run would leave
        the recorded balance unchanged and the next ticket would be assigned to the control again,
        forever. One treated ticket, then nothing but controls, on a dashboard showing the control
        as "map unavailable" — which reads as a malfunction rather than as an arm."""
        if not self.manifest.knowledge_map:
            return "off"
        if not self._experiment_arm():
            return "off"  # withheld on purpose by the A/B — a CHOSEN control
        return "injected" if getattr(self, "_knowledge_map", "") else "unavailable"

    def _pr_diff(self, ws: Workspace, base: str) -> str | None:
        """The pull request's diff as it stands in this checkout — `None` when git could not say.

        ONE HOME FOR THE QUESTION "what is in this pull request", because two callers now turn on
        the answer: the suppression scan and the reviewer read it as content, and #179 reads it as
        an IDENTITY — the same bytes mean the reviewer's verdict still describes this code.

        The exit code is honoured rather than discarded. A failed read used to hand the caller
        git's error message as if it were a diff, which scanned clean and compared unequal — a
        silent "the code changed" every time git could not answer.
        """
        rc, out = self.sandbox.run(
            workspace=ws, command=f"git diff {base}..HEAD", timeout=120
        )
        return out if rc == 0 else None

    def _pr_diff_paths(self, ws: Workspace, base: str) -> list[str]:
        """The pull request's changed PATHS — the same range as `_pr_diff`, asked by name.

        `sandbox.diff_paths` answers the same question against `workspace.base_branch`; this takes
        the base the caller is already holding, because the CI-repair path works on an open pull
        request and must not assume the two agree. A failed read returns `[]` — the gate that uses
        it treats an empty diff as "nothing reached the verifier", which is the honest reading of
        "git could not say" here only because the suppression scan beside it fails the same way.
        """
        rc, out = self.sandbox.run(
            workspace=ws, command=f"git diff --name-only {base}..HEAD", timeout=120
        )
        return [ln.strip() for ln in out.splitlines() if ln.strip()] if rc == 0 else []

    def _commit(self, ws: Workspace, ticket: Ticket) -> None:
        """Commit the working tree authored as the bot (D-12)."""
        msg = shlex.quote(f"{ticket.id}: {ticket.title}")
        author = (
            f"GIT_AUTHOR_NAME={shlex.quote(self.bot.name)} "
            f"GIT_AUTHOR_EMAIL={shlex.quote(self.bot.email)} "
            f"GIT_COMMITTER_NAME={shlex.quote(self.bot.name)} "
            f"GIT_COMMITTER_EMAIL={shlex.quote(self.bot.email)} "
        )
        # STRIP any agent change under .github/workflows/ before committing. The bot (a GitHub
        # App) is DELIBERATELY denied the `workflows` permission — so the agent can never rewrite
        # its own CI gates — and GitHub rejects the ENTIRE (atomic) push if a workflow file is in
        # the commit, losing all the work. So drop those changes here (revert modified workflow
        # files, remove newly-added ones) so the rest of the ticket still lands; a CI/workflow
        # change is human-only (the executor role knows this and notes it for a human). Scoped to
        # that one path → safe, and a no-op when the ticket didn't touch it.
        # …and it must NEVER be silent. Stripping is scope LOSS: a ticket whose acceptance
        # criteria included a CI change would otherwise merge green while that half quietly
        # never happened, and nobody would know until the gate they believe exists doesn't
        # fire. So record exactly what was dropped, put it in the job journal, and carry it
        # into the PR body as an explicit human to-do (see `_pr_body`).
        self._note_stripped_workflows(ws, ticket)
        strip_workflows = (
            "git checkout -- .github/workflows 2>/dev/null; "
            "git clean -fdq .github/workflows 2>/dev/null; "
        )
        self.sandbox.run(
            workspace=ws,
            command=f"{strip_workflows}git add -A && {author}git commit -m {msg} || true",
            timeout=120,
        )

    def _note_stripped_workflows(self, ws: Workspace, ticket: Ticket) -> None:
        """Record (and announce) any `.github/workflows/**` change about to be stripped. Purely
        observational — best-effort, and a failure here must never block the commit."""
        try:
            _, out = self.sandbox.run(
                workspace=ws,
                # `--untracked-files=all`: git collapses a wholly-new directory into a single
                # "?? .github/workflows/" line, which would tell the human a directory was
                # dropped without naming a single file they have to re-apply.
                command="git status --porcelain --untracked-files=all -- .github/workflows",
                timeout=60,
            )
        except Exception as exc:  # noqa: BLE001 — the strip itself still runs
            # Without this list nobody is told WHICH workflow files were dropped and must be
            # re-applied by hand — the strip stays correct, the hand-off stops being actionable.
            log.warning("could not list the stripped workflow files (%s) — the ticket will say "
                        "that CI files were dropped, but not which ones", exc)
            return
        # porcelain lines are "XY path" (and "XY old -> new" on a rename) — we want the paths
        paths = {
            ln[3:].strip().split(" -> ")[-1].strip('"')
            for ln in out.splitlines() if ln.strip()
        }
        known: set[str] = getattr(self, "_stripped_workflows", set())
        fresh = sorted(p for p in paths if p and p not in known)
        if not fresh:
            return
        self._stripped_workflows = known | set(fresh)
        self._emit(
            ticket, "warning",
            "⚠️ CI/workflow change dropped from the commit (the bot is denied the `workflows` "
            f"permission — human-only by design): {', '.join(fresh)}",
        )

    def _validate(self, ws: Workspace, ticket: Ticket) -> tuple[list[str], list[ValidationResult]]:
        self._set_state(ticket, JobState.VALIDATING)
        # THE DIFF IS READ ONCE AND ASKED BOTH QUESTIONS. `resolve_touched_components` answers
        # "which components did this match"; `assess` answers that AND "which paths matched none of
        # them", which nothing recorded — so the merge gate walked an empty list for a change
        # entirely outside the manifest and permitted it. Kept on `self` rather than widened into
        # this method's return type because three call sites unpack the pair, and a fourth element
        # nobody at those sites reads is a worse seam than one field the result-builders name.
        diff_paths = self.sandbox.diff_paths(workspace=ws)
        self._risk = risk_assess(diff_paths, self.manifest)
        # THE SAME DIFF, ASKED A THIRD QUESTION. Which of these paths are the verifier's own
        # inputs — the manifest that names the gates, and the profile that says what the project
        # is. Read here because this is where the diff already is, and recorded because the merge
        # gate holds a result rather than a diff.
        self._protected = protected_violations(diff_paths, self.manifest)
        # AND WHETHER THE QUESTION COULD BE ASKED AT ALL. An install that cannot read its own floor
        # gates too, but it is not a finding about this change — kept apart so the record never
        # claims the client touched files they did not touch.
        self._floor_unreadable = protected_policy.floor_unreadable(self.manifest)
        # THE WORKSPACE, NOT THE CENSUS. `_validate` runs on the initial pass, the repair pass, the
        # review-repair pass and the post-rebase re-validation — five call sites — and a census
        # taken at each cost a full test-collection run apiece while `_record_risk` overwrote the
        # field every time, so all but the last were paid for and discarded. The measurement is
        # taken once, where the result is built.
        self._census_ws = ws
        touched = list(self._risk.touched)
        # THE CLASS PROMOTES A GATE IT NAMES AT THIS RISK LEVEL FROM ADVISORY TO BLOCKING.
        # Computed here and passed IN, rather than read inside `_run_validations` via `self`,
        # because that method is reused as a plain function against
        # `onboarding.firstrun._GateHost` — a duck-typed stand-in with no `_profile`/`_risk` — and
        # `test_the_gate_loop_stays_reusable` pins its `self.` usage to exactly
        # `{sandbox, manifest, _emit}`. A parameter keeps the loop reusable; a new `self.` read
        # would raise there, caught silently by that stage's own broad `except Exception`.
        profile = getattr(self, "_profile", None)
        promoted = profile.promoted_gates(self._risk.level) if profile is not None else frozenset()
        return touched, self._run_validations(ws, touched, ticket, promoted_gates=promoted)

    def _take_census(self, ws: Workspace) -> tuple[str, ...] | None:
        """Enumerate the project's tests, or None if it cannot be enumerated.

        NONE IS NOT AN EMPTY CENSUS. A project that declares no inventory command has no census —
        ordinary, and most projects — and a command that fails has not told us there are zero
        tests. Both return None, and the gate treats "no before" as no census at all while
        treating "a before and no after" as the agent having broken enumeration, which is one of
        the failures this exists to catch.
        """
        cmd = inventory_command(self.manifest)
        if cmd is None:
            return None
        try:
            rc, out = self.sandbox.run(workspace=ws, command=cmd, timeout=_CENSUS_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 — a census is evidence, never a reason to lose a job
            log.warning("the test inventory command could not be run (%s) — no census this pass",
                        str(exc)[:160])
            return None
        if rc != 0:
            # THE SAME EXIT CODE MEANS TWO DIFFERENT THINGS and the operator has to be able to tell
            # them apart: a command that never worked (misconfigured, wrong path, missing tool) and
            # an agent that just broke enumeration read identically otherwise. `_run_setup` ran the
            # same command minutes ago, so the platform already knows which of the two this is.
            if getattr(self, "_census_before", None) is not None:
                log.warning(
                    "the test inventory command `%s` exited %s and it WORKED at setup — the change "
                    "under test appears to have broken enumeration; this holds the merge", cmd, rc)
            else:
                log.warning(
                    "the test inventory command `%s` exited %s — no census this pass. Check the "
                    "command: it runs in the same workspace as `setup:` and `validate:`", cmd, rc)
            return None
        ids = inventory_of(out)
        # THE NUMBER, WHERE AN ADOPTER CAN COMPARE IT. This filter cannot tell a test id from a
        # warning line, so the one defence against a noisy command is that the count is visible on
        # day one beside whatever the runner itself reports — 8529 here against pytest's own 8524
        # is the whole defect, and it is invisible unless somebody prints it.
        log.info("test census: %d identifiers from `%s`", len(ids), cmd)
        return ids

    def _record_risk(self, result: RunResult) -> None:
        """Put the half the gate could not see onto the result that the gate reads."""
        assessment = getattr(self, "_risk", None)
        if assessment is not None:
            result.undeclared_paths = list(assessment.undeclared_paths)
            result.undeclared_count = assessment.undeclared_count
        hits = getattr(self, "_protected", ()) or ()
        # TRUNCATED FOR A READER, COUNTED IN FULL. `protected_hits` is what a pull request
        # body prints; `protected_count` is the number, and it is taken here rather than
        # from the truncated list, which is what made the true number unrecoverable.
        result.protected_hits = list(hits[:protected_policy.MAX_SHOWN])
        result.protected_count = len(hits)
        result.floor_unreadable = bool(getattr(self, "_floor_unreadable", False))
        before = getattr(self, "_census_before", None)
        # TAKEN HERE, ONCE, AND ONLY IF THERE IS SOMETHING TO COMPARE IT WITH. A census with no
        # baseline gates nothing, so running the command to produce a number nobody reads is a
        # test-collection run spent on nothing.
        census_ws = getattr(self, "_census_ws", None)
        after = self._take_census(census_ws) if (before is not None and census_ws) else None
        result.test_census_before = None if before is None else len(before)
        result.test_census_after = None if after is None else len(after)
        if before is not None and after is not None:
            gone = census_vanished(before, after)
            result.test_census_gone = list(gone[:census_policy.MAX_SHOWN])
            result.test_census_gone_count = len(gone)

    def _run_validations(
        self, ws: Workspace, touched: list[str], ticket: Ticket,
        *, promoted_gates: frozenset[str] = frozenset(),
    ) -> list[ValidationResult]:
        # `promoted_gates` ARRIVES AS A PARAMETER, NEVER A `self.` READ — see the comment at the
        # one production call site (`_validate`) for why: this method also runs as a plain
        # function against `onboarding.firstrun._GateHost`, which carries no profile and no risk
        # assessment, and a guard test pins its `self.` usage to exactly
        # `{sandbox, manifest, _emit}`.
        results: list[ValidationResult] = []
        for name, raw in applicable_validations(touched, self.manifest).items():
            gate = as_gate(raw)
            cmd = gate.command
            # A scan measured in minutes must not borrow the test suite's wall, and a scanner that
            # hangs must not hold the floor for the test timeout.
            timeout = (gate.timeout_minutes * 60) if gate.timeout_minutes else _VALIDATION_TIMEOUT
            rc, out = self.sandbox.run(workspace=ws, command=cmd, timeout=timeout)
            # THE PROJECT'S CLASS CAN PROMOTE AN ADVISORY GATE TO BLOCKING, NEVER THE REVERSE — a
            # name in `promoted_gates` only ever turns `advisory` OFF; a role that was already
            # blocking is unaffected, and a role not in the map at all cannot be promoted (that is
            # `profile_gate_reason`'s refusal, before this method is ever called).
            advisory = gate.advisory and name not in promoted_gates
            vr = ValidationResult(
                name=name, command=cmd, exit_code=rc, passed=(rc == 0),
                output_tail="\n".join(out.splitlines()[-40:]),
                advisory=advisory,
            )
            results.append(vr)
            self._emit(
                ticket, "validation",
                f"{name}: {'PASS' if vr.passed else 'FAIL'}"
                + (" · advisory" if advisory else "")
                + (" · promoted by profile" if gate.advisory and not advisory else ""),
                command=cmd, exit_code=rc,
            )
        return results

    def _republish_review(self, pr_url: str, *, review: ReviewResult | None) -> bool:
        """Bring the pull request's own review section back into agreement with the card (#187).

        MEASURED ON THE PILOT. podbeam #119 was reviewed and rejected (score 58); an adjust pass
        repaired four of the findings and returned to the gate. At that instant the panel said
        `Review out of date` — correctly, that is what #181 built — and the pull request's body
        still opened with *"## Review — rejected (score 58)"*, with no marker and no date. A person
        who opens the PR, which is where a reviewer naturally goes and the only surface a
        collaborator without the panel token has, reads a verdict about code that no longer exists
        as if it were current.

        This is #164's shape in a second surface: one question, answered in two places, one of them
        silently wrong. The staleness was already computed; the pull request simply never asked.

        `review` GIVEN means a pass produced a fresh reading — the section is REPLACED, which is
        also how a re-review (#181) clears the marker instead of adding a second one. `None` means
        nothing re-read it, so what stands is correctly dated rather than deleted: the heading, the
        score and the decision are identity and stay, and every clause under them is stamped.

        BEST-EFFORT, ALWAYS. A forge that refuses a description edit must not fail the pass that
        was doing the work — but it may not be silent either, so the refusal is journalled.
        """
        if not pr_url:
            return False
        body = self.forge.pr_body(pr=pr_url)
        if body is None:
            # COULD NOT LOOK. Amending from a failed read would publish a body assembled out of
            # nothing over whatever the pull request really says.
            log.warning("OPENFACTORY_PR_BODY_UNREADABLE pr=%s — its review section still reads as "
                        "current", pr_url)
            return False
        rows = body.splitlines()
        start = next((i for i, row in enumerate(rows)
                      if row.startswith(_REVIEW_HEADING)), None)
        if start is None:
            return False  # a pull request this platform did not write a review section into
        end = next((i for i in range(start + 1, len(rows)) if rows[i].startswith("## ")),
                   len(rows))
        if review is not None:
            section = _review_lines(review)
        else:
            section = self._dated(rows[start:end])
            if section is None:
                return False  # already marked — one caveat, not a pile of them
        updated = "\n".join(rows[:start] + section + rows[end:])
        if updated == body:
            return False
        took = self.forge.set_pr_body(pr=pr_url, body=updated)
        if not took:
            log.warning("OPENFACTORY_PR_BODY_REFUSED pr=%s — the review section on the pull "
                        "request still describes a diff that is gone", pr_url)
        return took

    def _dated(self, section: list[str]) -> list[str] | None:
        """The section as it stands, correctly dated — or None when it already says so.

        WHAT THE REVIEWER SAID STANDS. Deleting it would be the opposite mistake: its reasoning is
        what tells a person where to look in the new diff. It may only stop being presented as
        current — which is why the heading survives untouched and everything under it is stamped,
        clause by clause, exactly as the panel stamps its own points (#154: a reader applies a
        warning to the clause it was standing next to).
        """
        caveat = self._say("pr.review.out-of-date")
        if any(row.strip() == caveat.strip() for row in section):
            return None
        was = self._say("pr.review.was")
        head, *rest = section
        stamped = [row if (not row.strip() or row.lstrip().startswith(">") or row.startswith(was))
                   else f"{was}{row}" if not row.startswith("- ")
                   else f"- {was}{row[2:]}" for row in rest]
        return [head, "", caveat, ""] + stamped

    def _pr_body(self, ticket: Ticket, result: RunResult) -> str:
        lines = [
            f"Automated by OpenFactory for {ticket.id}.",
            "", f"Closes {ticket.id}",  # auto-closes the issue on merge
            "", "## Objective", ticket.objective, "", "## Validations",
        ]
        for v in result.validations:
            # An advisory FAILURE must not wear the same ❌ as a blocking one — the two ask
            # opposite things of the reader (fix this now / look at this when you can) — and it
            # must not be hidden either: an advisory result nobody sees is a log, not a gate.
            mark = "✅" if v.passed else ("⚠️" if v.advisory else "❌")
            note = " · advisory, does not block" if v.advisory and not v.passed else ""
            lines.append(f"- {mark} `{v.name}`: `{v.command}` (exit {v.exit_code}){note}")
        if any(v.advisory and not v.passed for v in result.validations):
            failed = ", ".join(f"`{v.name}`" for v in result.validations
                               if v.advisory and not v.passed)
            lines += ["", f"> {failed} reported findings. These gates are **advisory**: they did "
                          "not block this merge and did not trigger a repair pass. The output is "
                          "in the job log."]
        if result.review is not None:
            lines += ["", *_review_lines(result.review)]
        # Scope loss must be visible where the human decides to merge. The bot is deliberately
        # denied the `workflows` permission, so any CI change the agent wrote was stripped
        # before the commit — say so here, or this PR reads as "the whole ticket landed".
        stripped = sorted(getattr(self, "_stripped_workflows", set()))
        if stripped:
            lines += [
                "", "## ⚠️ CI/workflow changes NOT included",
                "The agent changed CI/workflow file(s), which this bot is deliberately not "
                "allowed to push (CI/CD is human-only). They were dropped so the rest of the "
                "ticket could land — **a human must apply them separately**:",
            ]
            lines += [f"- `{p}`" for p in stripped]
        if result.touched_components:
            lines += ["", f"Touched components: {', '.join(result.touched_components)}"]
        # THE VERDICT THE GATE REACHED, ON THE PULL REQUEST THE GATE DECIDED ABOUT. The line above
        # printed only when something matched, so a change entirely outside the manifest's own
        # components said NOTHING here — and silence reads as "no components were involved" rather
        # than "these paths are declared by nobody", which is the opposite of the truth and the
        # more dangerous of the two.
        assessment = risk_of_attempt(self.manifest, result)
        risk_note = assessment.note
        if not risk_note.startswith("risk: not expressed"):
            lines += ["", risk_note]
        # THE SUPPRESSIONS THAT SURVIVED THE REPAIR LOOP. `should_auto_merge` has refused on this
        # since ADR-0011 and the pull request never said so: a green gate that was silenced is not
        # a green gate, and the person deciding could not tell that from one that simply passed.
        if result.added_suppressions:
            found = ", ".join(f"`{k}`" for k in sorted(set(result.added_suppressions)))
            lines += ["", f"this change adds gate-suppression(s) {found} that survived the repair "
                          f"pass — a gate that was silenced no longer proves what it claims, so "
                          f"this is human-gated"]
        # AND THE GATE BESIDE IT, FOR THE SAME REASON. A deterministic gate that holds a merge and
        # says nothing leaves a human reading a pull request that looks exactly like an ordinary
        # "ready for review" — they cannot tell that anything held it, let alone which file. This
        # module's own docstring calls that "a gate nobody can argue with".
        protected_note = protected_policy.reason(
            tuple(result.protected_hits), result.protected_count or None,
            unreadable_floor=result.floor_unreadable)
        if protected_note:
            lines += ["", protected_note]
        # AND THE CENSUS, ON THE SAME PRINCIPLE. This one had no caller at all: a suite that
        # stopped collecting held the merge and the pull request said nothing about it, so the
        # person deciding could not see the one signal — the vanished identifiers — that survives
        # a count the noise moved the wrong way.
        census_note = census_policy.reason(
            result.test_census_before, result.test_census_after,
            tuple(result.test_census_gone), result.test_census_gone_count or None)
        if census_note:
            lines += ["", census_note]
        # THE CLASS, WHEN THE CLASS IS THE REASON. A `regulated` project whose profile sent an
        # ordinary change to a person saw a pull request that said nothing about why: the manifest
        # says `auto`, the risk note says `normal`, and the two together read as a platform that
        # ignored the client's own configuration. The class is the missing sentence, and it is the
        # one thing the client themselves declared.
        profile = getattr(self, "_profile", None)
        if self.manifest.profile and profile is None:
            lines += ["", f"the manifest declares `profile: {self.manifest.profile}` and this "
                          f"attempt never resolved it, so nothing here may merge by itself — that "
                          f"is OUR wiring and not this repository"]
        elif profile is not None and profile.requires_human(assessment.level):
            lines += ["", f"this project is `{' → '.join(profile.names)}`, and that class sends a "
                          f"`{assessment.level.value}` change to a person even where "
                          f"`merge_policy` says `auto`"]
        if result.total_cost_usd is not None:
            lines += ["", f"Cost: ${result.total_cost_usd:.4f}"]
        return "\n".join(lines)
