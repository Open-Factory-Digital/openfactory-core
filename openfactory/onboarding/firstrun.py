"""The environment's FIRST ROUND — prove the loop before a real ticket is ever picked up.

Between "this deployment is configured" and "a client's card runs" there is nothing. Measured
against HEAD, three commands sit on either side of that gap and none of them crosses it:

    openfactory doctor <p>         reads PREREQUISITES — docker, the harness on PATH, the manifest
    loads
    openfactory box prove <p>      proves the BOX — the image, the toolbox, `setup:`, `validate:` on
                            untouched main, the harness binary, the auth route, TLS egress
    preflight_check(...)    sizes a TICKET — is this card small enough to run

Every one of them is upstream of the only question a client in the room actually asks: *does the
factory work here?* The product owner drew that line himself (2026-08-06): *"running a first round…
comes BEFORE a pre-flight, because the pre-flight is about the task — this would be about the
ENVIRONMENT"*. A pre-flight is about a card. This is about the ENVIRONMENT, and the only way to
answer it is to run the loop:

    a real box → a real harness pass → a real diff → the client's real gates → a real reviewer

and then say what each stage did, what it cost, and — the point — WHERE IT WOULD HAVE FAILED.

THE SCAR THIS MUST NOT REOPEN, AND WHY THE SAFETY HERE IS PHYSICAL
------------------------------------------------------------------
`openfactory/policy/test_work.py` opens with the wreckage: eleven tickets whose only purpose was to
watch
the pipeline move — *"Add GET /heartbeat endpoint (live autonomy demo)"* — went through planning,
execution, review and merge, and left eleven constant-returning endpoints in a client's accounting
product. `contracts/project.py::accepts_test_work` was the guard born from it, and it answers a
DIFFERENT question: *may this CARD run on this board?* Measured: `grep -rn accepts_test_work` finds
the field, its default `False`, the refusal, the tests, and NOT ONE project that sets it true. It
is deny-by-default with an empty allowlist — the bench ADR-0027 D1 describes was never built — so
nothing this module could do would be permitted by it, and nothing it does is protected by it
either.

So this round is not made safe by a policy that could be edited. It is made safe by being
physically unable to reach the things that got damaged:

    may touch                              never touches
    ─────────────────────────────────────  ──────────────────────────────────────────────────
    the client's repository, as a          the TRACKER — no ticket created, commented or moved.
      THROWAWAY clone the box makes          There is no tracker object in this module. Not a
    the box, the image, the toolbox          stub, not an in-memory double: no field on `Probes`
    the client's own gates                   holds one, so there is no call to make
    the reviewer                           their BRANCHES — every git remote is REMOVED from the
                                             clone, and verified gone, BEFORE the agent starts
                                           their PR LIST — nothing here imports a forge
                                           their BOARD — not even READ to choose work, because
                                             the ticket is synthetic and owned by the platform

That table is the design, not a promise about it. A round that can only fail inside a temporary
directory needs no allowlist to be safe, and `tests/test_onboarding_firstrun.py` asserts each line
of it — including the one that matters most, which is that a client's `box.env` names do NOT cross
into the rehearsal box (§ THE CREDENTIAL IS THE GUARANTEE below).

AND THE FIRST WORD OF THAT TABLE — "THROWAWAY" — IS A PROPERTY OF THE BOX, NOT OF THIS FILE, so it
is now READ rather than asserted. `ContainerSandbox.prepare` clones (`git clone --local
--no-hardlinks` into a temporary directory) and every line above holds. `WorktreeSandbox.prepare`
does `git worktree add` INSIDE the repository it was handed, where none of them does: a linked
worktree shares its parent's config, so `git remote remove origin` in it deletes `origin` from the
CLIENT'S OWN repository, permanently, while this round reports `isolation ok` and goes on to spend
two agent passes. `OPENFACTORY_SANDBOX=worktree` is a documented value, `default_sandbox()` returns
it
verbatim, and its builder ignores the `image=`/`project=` arguments `probes_for` passes instead of
rejecting them — so nothing but this guard stood between that configuration and that damage.
`_owns_its_checkout` asks git itself (`OWN_CHECKOUT_PROBE`), in the box, before `setup:`, before
the removal and before the agent.

THE CREDENTIAL IS THE GUARANTEE, NOT THE REMOTE
------------------------------------------------
Removing `origin` is the second layer and it was very nearly sold as the first. `container.py`
(`_passthrough_env`) injects the names listed in `box.env` into the box, and `contracts/project.py`
says so in its own comment: *"every name listed here is a value agent-written code can read from
inside the box"*. A client whose CI restores private packages with `SYSTEM_ACCESSTOKEN`, or whose
scanners authenticate with a forge token, will have named exactly those — and
`git push https://$TOKEN@host/...` needs no remote at all. `box.network` defaults to `bridge`,
which is full outbound internet.

So the rehearsal box is built with `extra_env` reduced to the NAMES OF THE HARNESS'S OWN AUTH ROUTE
(`box_prove._route_names(resolve_route(project))`) and nothing else. The client's `box.env` is read,
reported, and discarded. What still crosses is `container._AUTH_ENV_VARS` — the two hard-coded
harness credentials — which is stated here rather than hidden because it is the honest boundary:
this module reduces what it controls, and the round cannot run at all without a credential for the
model.

WHAT IT RUNS, AND WHY THE CONTENT IS DELIBERATELY BORING
---------------------------------------------------------
Taking work from the client's backlog recreates the accident exactly. Generating *"add a /heartbeat
endpoint"* IS the accident, one layer of indirection away. The only defensible synthetic ticket is
one whose output cannot survive the round and which nobody would be tempted to keep:

    add ONE test, in this repository's own framework, asserting something already true.

It exercises every organ — the agent has to read the repo, find the test convention, write in it;
the gates then run against a REAL diff (which untouched `main` can never produce, the C-35 lesson);
the reviewer reads a real change. And when the round ends the clone is destroyed, so the diff is
irrelevant to the client's product BY CONSTRUCTION rather than by anyone's restraint.

IT REPORTS AS IT GOES, BECAUSE THE ROOM IS THE PRODUCT
-------------------------------------------------------
A client's developers are sitting there. An agent pass is minutes; a legacy test suite is more. A
design whose first proof of life arrives at the end has already lost the room. So `rehearse` takes
`on_start(name)` and `on_stage(stage)` and calls them around every station — `box ready`,
`workspace prepared`, `agent ran (N turns, $X)`, `gates ran (which, exit codes)`, `review returned
(decision, score)`. Two callbacks rather than one with a nullable argument, because "started" and
"finished with no answer" are different facts and this codebase has paid for collapsing those.

AND IT SAYS WHAT IT WILL COST BEFORE IT SPENDS
-----------------------------------------------
This burns real tokens on a real model, twice. `estimate_cost` answers from THIS deployment's own
telemetry (`observability/query.records_of_kind(project, "agent_run")` — the executor and review
rows it has actually recorded), never from a number somebody typed. `rehearse` refuses to start
without `Consent(spend_approved=True)` and returns the estimate as its whole result, having called
no harness at all.

`None` IS NOT ZERO, and this is where that rule earns its keep: a deployment with no history gets
`usd_low is None` and a sentence saying so. Returning `0.0` would present an unmeasured round as a
free one, and free always wins an argument it should not be in.

THREE MARKERS, THE SAME THREE `readiness.py` USES. `ok` / `FAIL` / `----`, where `----` is a stage
that could not be answered here — a gate stage nobody has cleared to run, a stage the round never
reached because an earlier one stopped it. It is deliberately not a shade of `ok`: absence reading
as compliance is this codebase's most expensive defect class, and a rehearsal that skipped the
gates and printed a green verdict would be the most expensive instance of it yet.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from openfactory import namespace
from openfactory.onboarding.readiness import LOCAL, WORKER

log = logging.getLogger("openfactory.onboarding.firstrun")

__all__ = [
    "DEFAULT_TURN_CAP",
    "LOCAL",
    "REHEARSAL_BRANCH",
    "REHEARSAL_ID",
    "STAGES",
    "WORKER",
    "Consent",
    "Estimate",
    "Probes",
    "Rehearsal",
    "Stage",
    "estimate_cost",
    "first_round",
    "probes_for",
    "rehearsal_ticket",
    "rehearse",
]

#: The stations, in the order they run and in the order they are reported.
#:
#: A LITERAL, and the reason is the same one `readiness.ROLE_PROMPTS` gives for being one: the
#: obvious implementation is "whatever `rehearse` happened to append", and then a station that
#: silently stops running produces a shorter report that still reads complete. A test asserts every
#: name here appears in the result of a full round, so dropping a station reddens by name.
STAGES: tuple[str, ...] = (
    "box", "workspace", "setup", "isolation", "agent", "diff", "gates", "review", "teardown",
)

#: `machine._SETUP_TIMEOUT` — the same wall a real job gives the client's install commands. A
#: rehearsal that timed out where a job would not have would report a failure that is ours.
SETUP_TIMEOUT = 1800

#: Stations that can spend money. Everything else is 0 tokens by construction.
COSTED_STAGES: tuple[str, ...] = ("agent", "review")

#: The synthetic ticket's id, and it is deliberately NOT a tracker reference.
#:
#: `#142`, `PROJ-31` and `owner/repo#7` are what every tracker in this platform speaks. This is
#: none of them, on purpose: the id travels into the agent's prompt, the job journal and the
#: reviewer's input, and the one thing that must never happen is a human — or a future code path
#: that resolves refs — reading it as a card on somebody's board. A test pins the shape.
REHEARSAL_ID = "rehearsal/first-round"

#: The throwaway branch. Never pushed: nothing in this module can push (there is no forge here),
#: and the remote is removed before the agent runs. No legacy twin, for the same reason — a name
#: that never leaves the machine has nobody left over to answer to.
REHEARSAL_BRANCH = f"{namespace.BRANCH_PREFIX}/env-rehearsal"

#: The round's OWN turn ceiling, and it is deliberately far below a real ticket's.
#:
#: `Manifest.effort_budget_turns` governs a JOB, enforced by `machine.py` counting turns between
#: passes. Nothing here is a job, so none of that machinery applies and a rehearsal without its own
#: ceiling is the disease reproduced inside the remedy: an unbounded agent pass, in front of a
#: client, on the platform's own demo. The work is "add one passing test" — a pass that has not
#: managed it in 25 turns has found something about this environment worth reporting, which is the
#: round's actual product.
DEFAULT_TURN_CAP = 25

#: How many agent passes a full round makes: the executor, then the reviewer. Named because the
#: estimate multiplies by it and a silent change there changes a number a human consented to.
AGENT_PASSES = 2

#: TWO ANSWERS FROM ONE `git rev-parse`, AND THEY DIFFER ONLY WHEN THIS CHECKOUT IS SOMEBODY
#: ELSE'S. `--git-dir` is where THIS working tree's refs live; `--git-common-dir` is the config and
#: object store it WRITES TO. In a repository of its own they are the same string; in a linked
#: worktree the second points at the repository this one was carved out of.
#:
#: MEASURED WITH REAL GIT (2.50) IN BOTH DIRECTIONS BEFORE IT WAS WRITTEN HERE, because a probe
#: that cannot tell the two apart is worse than no probe:
#:
#:     a plain checkout                                → `.git`  `.git`
#:     `git clone --local --no-hardlinks` (the box's)  → `.git`  `.git`
#:     `git worktree add`                              → `<other>/.git/worktrees/x`  `<other>/.git`
#:
#: It is asked of git rather than of a box's name because the thing that must be true is a property
#: of the CHECKOUT, and a new box joins this platform without asking this module's permission.
OWN_CHECKOUT_PROBE = "git rev-parse --git-dir --git-common-dir"

#: The telemetry roles the estimate is built from — the two passes this round makes. `machine.py`
#: writes `role="executor"` and `role="review"` rows (`AgentRunMetric.role`), so these are the rows
#: that describe THIS work rather than a planner or a sizer pass that costs something else.
COSTED_ROLES: tuple[str, ...] = ("executor", "review")


# ── what it will cost, before it spends ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Estimate:
    """What this round will cost, measured from what this deployment has already spent.

    `usd_low is None` means COULD NOT DETERMINE and never "free". The distinction is the whole
    value of the object: a deployment that has never run a ticket has no basis for a number, and
    printing `$0.00` there would put an unmeasured round into a comparison it would then win."""

    #: Agent passes this round will make.
    passes: int
    #: The observed range, or None on both when there is no basis. Never one without the other.
    usd_low: float | None
    usd_high: float | None
    #: How many past runs the range came from. 0 whenever the range is None.
    sample: int
    #: The sentence a human reads — always says where the number came from, or why there is none.
    basis: str
    #: The round's own turn ceiling. Reported even when the money is unknown, because it is the
    #: only bound that still exists in that case.
    turn_cap: int
    #: Whether the harness this project runs can be TOLD that ceiling, or only measured against it
    #: afterwards. An unenforceable cap presented as a cap is a bound nobody has.
    cap_enforced: bool = True

    @property
    def unknown(self) -> bool:
        return self.usd_low is None

    def render(self) -> list[str]:
        money = ("cost: UNKNOWN" if self.unknown
                 else f"cost: ${self.usd_low:.2f} – ${self.usd_high:.2f}")
        cap = (f"cap {self.turn_cap} turns" if self.cap_enforced
               else f"cap {self.turn_cap} turns (REPORTED ONLY — this harness takes no turn limit)")
        return [f"  this round makes {self.passes} agent pass(es) · {money} · {cap}",
                f"  {self.basis}"]


@dataclass(frozen=True)
class Consent:
    """A human's answer to the two questions this round is not allowed to answer for them.

    Both default to withheld. A round that ran because nobody said no is a round that spent a
    client's money on an assumption, and the second field is worse than money — see `gates_may_run`.
    """

    #: The caller saw an `Estimate` and accepted it. False → `rehearse` returns the estimate and
    #: calls no harness at all.
    spend_approved: bool = False

    #: MAY THE CLIENT'S OWN GATES RUN HERE? Three values, and the third is the honest default.
    #:
    #: True   somebody said yes, out loud, and it is recorded below.
    #: False  somebody said NO — a fifteen-year-old suite that talks to a shared dev database will
    #:        truncate that database, from a workshop, in front of the people who own it. The
    #:        gates stage is then `----`, the round still runs, and the verdict says PARTIAL.
    #: None   nobody was asked. The gates run only when a VALID box proof already exists for the
    #:        exact same commands — because `box prove` has then already run them in this box, so
    #:        the round adds no exposure that the platform has not already taken. With no such
    #:        proof the stage is `----` and carries the question, which is a stall that ASKS
    #:        rather than a stall that is silent.
    gates_may_run: bool | None = None

    #: Who said so. A consent with no name is a consent nobody gave, and this line lands in the
    #: report a client reads.
    by: str = ""


def _numbers(rows: list[dict], role: str) -> list[float]:
    """The recorded dollar costs of one role's past runs. Rows without a number are DROPPED.

    A row whose `cost_usd` is absent is a harness that did not report a price (Codex reports tokens
    and no price), not a run that was free. Counting it as 0.0 would drag both ends of the range
    toward zero in proportion to how many of this deployment's runs are unpriced — quietly, and
    most on the deployments least able to notice."""
    out: list[float] = []
    for row in rows:
        if str(row.get("role") or "") != role:
            continue
        raw = row.get("cost_usd")
        if raw is None:
            continue
        try:
            value = float(raw)  # DynamoDB hands back Decimal
        except (TypeError, ValueError):
            continue
        if value >= 0:
            out.append(value)
    return out


def estimate_cost(p: Probes) -> Estimate:
    """What this round will cost, from this deployment's OWN spend — or an honest refusal.

    THE RANGE IS min..max OF WHAT ACTUALLY HAPPENED, per role, summed. Not an average: an average
    of two runs is a number with the authority of a measurement and the content of a coin flip,
    and the question a human is answering ("may I spend this?") is answered by the worst case, not
    by the typical one. A range also carries its own honesty — a wide one says this deployment's
    tickets vary, which is true and worth seeing before the first one runs.

    THREE DIFFERENT NEGATIVE ANSWERS, THREE DIFFERENT SENTENCES, because they send a reader in
    three different directions:

        telemetry unreadable   `past_runs()` → None. Nothing may be concluded; the metrics sink is
                               the thing to look at.
        no rows at all         `[]`. This deployment has never run a ticket for this project. That
                               is not a fault — it is the state every new client is in, and it is
                               precisely when this round is most useful.
        rows with no prices    the harness reports tokens and not dollars. Saying "no history"
                               there would be false, and a reader would go looking for the wrong
                               thing.
    """
    cap_enforced = p.turn_cap_enforced()
    rows = p.past_runs()
    if rows is None:
        return Estimate(
            passes=AGENT_PASSES, usd_low=None, usd_high=None, sample=0, turn_cap=p.turn_cap,
            cap_enforced=cap_enforced,
            basis="this deployment's telemetry could not be read, so there is no basis for a "
                  "number — the bound below is the only one that applies",
        )
    per_role = {role: _numbers(rows, role) for role in COSTED_ROLES}
    priced = {role: values for role, values in per_role.items() if values}
    if not priced:
        detail = (f"{len(rows)} past agent run(s) are recorded for {p.project_name} and none of "
                  "them carries a price — this harness reports effort, not dollars"
                  if rows else
                  f"this deployment has recorded no agent run for {p.project_name} yet, which is "
                  "exactly the state a first round exists for")
        return Estimate(passes=AGENT_PASSES, usd_low=None, usd_high=None, sample=0,
                        turn_cap=p.turn_cap, cap_enforced=cap_enforced, basis=detail)
    low = sum(min(values) for values in priced.values())
    high = sum(max(values) for values in priced.values())
    counted = ", ".join(f"{len(values)} {role}" for role, values in sorted(priced.items()))
    unpriced = sorted(role for role in COSTED_ROLES if not per_role[role])
    tail = (f"; no priced {' or '.join(unpriced)} run has ever been recorded, so that pass is NOT "
            "in this range" if unpriced else "")
    return Estimate(
        passes=AGENT_PASSES, usd_low=low, usd_high=high,
        sample=sum(len(values) for values in priced.values()), turn_cap=p.turn_cap,
        cap_enforced=cap_enforced,
        basis=f"measured from {counted} run(s) this deployment recorded for {p.project_name}{tail}",
    )


# ── one station's outcome ───────────────────────────────────────────────────────────────────────

@dataclass
class Stage:
    """What one station did. `readiness.Finding`'s vocabulary, plus what a round costs.

    `ok` alone cannot carry three states and this module needs all three, so `answered` is here for
    the same reason it is there: a gates stage nobody cleared to run is neither a pass nor a
    failure, and both readings do damage — `ok` certifies gates that never ran, `not ok` reports a
    failure nobody can act on."""

    name: str
    ok: bool
    message: str
    #: Required whenever `ok` is False — enforced by `_fail`, the only way this module builds one.
    remedy: str = ""
    #: Which machine answered: `worker` or `local`. Never omitted (see `readiness`'s docstring).
    measured_on: str = ""
    #: False = no answer exists here. Never counted as a pass, never counted as a failure.
    answered: bool = True
    #: False = the round stopped upstream and this station never ran. Renders like `answered=False`
    #: because it is also "no answer", but the MESSAGE says which of the two happened — a reader
    #: who cannot tell "we did not run this" from "we ran it and could not tell" is a reader who
    #: will re-run the round to find out.
    reached: bool = True
    seconds: float = 0.0
    cost_usd: float | None = None
    num_turns: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def line(self) -> str:
        marker = "ok  " if self.ok else "FAIL"
        if not self.answered or not self.reached:
            marker = "----"
        bits = [f"{self.seconds:.1f}s"] if self.seconds else []
        if self.num_turns is not None:
            bits.append(f"{self.num_turns} turns")
        if self.cost_usd is not None:
            bits.append(f"${self.cost_usd:.4f}")
        elif self.name in COSTED_STAGES and self.answered and self.reached:
            # A costed pass that reported no price must SAY so. Printing nothing here is how an
            # unpriced harness reads as a free one two lines further down.
            bits.append("cost not reported")
        suffix = f"  [{' · '.join(bits)}]" if bits else ""
        head = (self.message.splitlines() or [""])[0]
        return f"  {marker}  {self.name:<10} {head}{suffix}"


def _ok(name: str, message: str, *, on: str, **kw) -> Stage:
    return Stage(name=name, ok=True, message=message, measured_on=on, **kw)


def _fail(name: str, message: str, remedy: str, *, on: str, **kw) -> Stage:
    """A failing station, and `remedy` is positional and required — `readiness._fail`'s rule.

    A stage with no remedy is a symptom handed to the one person in the room who does not yet know
    this system, which on the day this runs is everybody."""
    return Stage(name=name, ok=False, message=message, remedy=remedy, measured_on=on, **kw)


def _unanswered(name: str, message: str, *, on: str, reached: bool = True) -> Stage:
    """No answer exists here. `ok=True` because it blocks nothing; `answered=False` so it can never
    be counted, rendered or read as a pass."""
    return Stage(name=name, ok=True, message=message, measured_on=on, answered=False,
                 reached=reached)


# ── the whole round ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Rehearsal:
    """Every station, plus the sentence a client reads.

    `verdict` is a PROPERTY for the reason `readiness.Report` gives: a verdict stored beside its
    evidence can drift from it, and the one guarantee this object exists to make is that its
    sentence and its stages are the same fact."""

    project: str
    measured_on: str
    sandbox_kind: str
    estimate: Estimate
    consent: Consent
    stages: list[Stage] = field(default_factory=list)
    #: Set when the round never started. Rendered instead of a stage list.
    not_run: str = ""

    @property
    def failed(self) -> list[Stage]:
        return [s for s in self.stages if s.reached and s.answered and not s.ok]

    @property
    def unanswered(self) -> list[Stage]:
        return [s for s in self.stages if s.reached and not s.answered]

    @property
    def skipped(self) -> list[Stage]:
        return [s for s in self.stages if not s.reached]

    @property
    def verdict(self) -> str:
        """`LOOP PROVEN` · `WOULD FAIL AT <stage>` · `PARTIAL — …` · `NOT RUN — …`.

        WOULD FAIL outranks PARTIAL because they answer different questions and only one of them
        is about the client: a failed station is a thing that will stop their first real ticket,
        whatever else was also left unasked."""
        if self.not_run:
            return f"NOT RUN — {self.not_run}"
        if self.failed:
            return f"WOULD FAIL AT {self.failed[0].name}"
        pending = len(self.unanswered) + len(self.skipped)
        if pending:
            return f"PARTIAL — {pending} stage(s) unanswered"
        return "LOOP PROVEN"

    @property
    def proven(self) -> bool:
        return self.verdict == "LOOP PROVEN"

    @property
    def exit_code(self) -> int:
        """0 ONLY for a fully proven loop. PARTIAL is not success: it is a round that did not ask
        the question it exists to ask, and a caller that exits 0 on it has published a green tick
        for an environment nobody finished measuring."""
        return 0 if self.proven else 1

    @property
    def spent_usd(self) -> float | None:
        """What was actually spent. `None` when NO pass reported a price — never 0.0."""
        prices = [s.cost_usd for s in self.stages if s.cost_usd is not None]
        return sum(prices) if prices else None

    @property
    def costed_passes_run(self) -> int:
        """How many money-spending stations actually ran — priced or not.

        `spent_usd is None` cannot tell "no pass ran" from "a pass ran and reported no price", and
        those are opposite sentences to put in front of somebody paying. This is the discriminator.
        """
        return len([s for s in self.stages
                    if s.name in COSTED_STAGES and s.reached and s.answered])

    @property
    def unpriced_passes(self) -> int:
        """Passes that ran and reported no price. Printed beside `spent_usd`, because a total that
        silently omits a pass is a total a client will compare against a competitor's."""
        return len([s for s in self.stages
                    if s.name in COSTED_STAGES and s.reached and s.answered
                    and s.cost_usd is None])

    @property
    def seconds(self) -> float:
        return sum(s.seconds for s in self.stages)

    @property
    def would_fail(self) -> list[str]:
        """WHERE A REAL TICKET WOULD HAVE DIED — the round's actual product.

        Every failed station, in the order the pipeline hits them, each with what to do about it.
        A round whose verdict is `LOOP PROVEN` returns `[]`, which is a reading and not a gap."""
        return [f"{s.name}: {(s.message.splitlines() or [''])[0]} → {s.remedy}"
                for s in self.failed]

    def header(self) -> list[str]:
        """Provenance FIRST, because it changes what every line under it means."""
        who = f" (approved by {self.consent.by})" if self.consent.by else ""
        lines = [f"{self.project} — first round · measured on: {self.measured_on} · box: "
                 f"{self.sandbox_kind}{who}"]
        if self.measured_on != WORKER:
            lines.append(
                "  this is NOT the machine that runs your tickets: the docker daemon, the "
                "environment and the proofs read below are this one's."
            )
        lines.extend(self.estimate.render())
        return lines

    def render(self) -> list[str]:
        lines = [*self.header(), ""]
        for stage in self.stages:
            lines.append(stage.line())
            for extra in (stage.message.splitlines() or [""])[1:]:
                lines.append(f"  {'':<6}{'':<10}  {extra}")
            if not stage.ok and stage.remedy:
                lines.append(f"  {'':<6}{'':<10}→ {stage.remedy}")
        lines.append("")
        spent = self.spent_usd
        if self.not_run:
            money = "spent: nothing — this round never started"
        elif not self.costed_passes_run:
            # NOTHING RAN IS NOT THE SAME ANSWER AS RAN AND WAS NOT PRICED, and the branch below
            # said the second for both. Measured on the first real run of `env rehearse`: the box
            # was unproven, the round stopped at station one, no harness was ever constructed —
            # and the report read `spent: not reported by this harness`, which is a claim about a
            # harness that was never invoked. A client reading it has to assume something ran and
            # went unmeasured. This is the `None` vs `[]` rule (could not read / read and empty)
            # arriving in the one line of the report that is about their money.
            money = "spent: nothing — no agent pass was reached"
        elif spent is None:
            money = "spent: not reported by this harness"
        else:
            money = f"spent: ${spent:.4f}"
            if self.unpriced_passes:
                money += (f" (+{self.unpriced_passes} pass(es) whose cost the harness did not "
                          "report — the real total is higher)")
        lines.append(f"{self.verdict} · {self.seconds:.1f}s · {money}")
        for line in self.would_fail:
            lines.append(f"  would fail — {line}")
        return lines


# ── the synthetic ticket ────────────────────────────────────────────────────────────────────────

def rehearsal_ticket(repo: str, base_branch: str = "") -> object:
    """The ticket the PLATFORM owns — small, verifiable, and true of any codebase.

    WHY THIS ONE AND NOT A USEFUL ONE, which is the only interesting decision in this module.
    Three candidates were on the table and two of them are the eleven-endpoint accident:

      * take a card from the client's backlog — that is literally running their product work in a
        round designed to throw its output away, and the day somebody decides the output was too
        good to waste, the whole physical guarantee is gone;
      * generate a plausible small feature ("add a /heartbeat endpoint") — that IS the accident.
        The eleven tickets were exactly this, generated for exactly this reason;
      * add one test that already passes.

    The third has a property the other two lack: nobody wants to keep it. There is no version of
    this round where somebody looks at the diff and argues for preserving it, which means the
    physical guarantee (no remote, destroyed clone) never has to survive a temptation.

    And it is not a toy. To write one passing test the agent must find the test framework, its
    conventions, an existing behaviour worth asserting, and produce something the CLIENT'S OWN
    GATES then accept — which is the entire loop, exercised against a real diff. Untouched `main`
    can never produce that: it is the C-35 lesson (`box_prove.component_gates`), where 47 agent
    turns ended in `ruff: not found` because the per-component gates had never run against
    anything.

    THE PROMPT SAYS WHAT THIS IS. An agent told to write a test in a client's repository, with no
    explanation, may reasonably decide the repository needs a test SUITE. The objective therefore
    opens by saying this is a rehearsal whose output is destroyed — which is true, and which is the
    difference between a bounded pass and an agent quietly starting a refactor.

    AND IT HAS A LEGITIMATE WAY TO SAY "NO". A repository with no test framework at all is a real
    answer about this environment and a useful one; inventing a framework there would produce a
    green round about a factory that would fail on the client's first real card."""
    from openfactory.contracts import AcceptanceCriterion, Ticket

    return Ticket(
        id=REHEARSAL_ID,
        repo=repo,
        base_branch=base_branch or None,
        title="Environment rehearsal — add one test that already passes",
        objective=(
            "This is OpenFactory's environment rehearsal. It is not part of your product, "
            "and nothing you write here is kept: this checkout has no git remote, and the whole "
            "workspace is destroyed the moment this round ends.\n\n"
            "Add exactly ONE test, using this repository's own test framework and its own "
            "conventions, asserting something that is ALREADY TRUE of existing code — a pure "
            "function's documented return value, a constant, a parser handling an input it "
            "already handles. The test must pass against the code as it stands.\n\n"
            "Change no production source file. Add no dependency. Do not touch CI, build or "
            "packaging files.\n\n"
            "If this repository has no test framework at all, write nothing, say so in your final "
            "message, and stop. That is a true and useful answer about this environment; inventing "
            "a framework would not be."
        ),
        acceptance_criteria=[
            AcceptanceCriterion(
                text="exactly one test is added — a new test file, or one new test in an "
                     "existing test file"),
            AcceptanceCriterion(
                text="no file outside the repository's test tree is modified"),
            AcceptanceCriterion(
                text="the project's own test gate passes with the new test present"),
        ],
        in_scope=["the repository's existing test tree"],
        out_of_scope=[
            "production source files", "dependencies and lockfiles",
            "CI, workflow, build and packaging files", "documentation",
        ],
        labels=[],
    )


# ── the world, as callables ─────────────────────────────────────────────────────────────────────

@dataclass
class Probes:
    """Everything `rehearse` needs to know about the world.

    INJECTED FOR THE REASON `doctor.py` AND `box_prove.py` INJECT: every branch below has to be
    reachable in a test without docker, a network, a registry, a GitHub App or a dollar. A first
    round that could only be exercised on a healthy deployment is a first round nobody can show
    reporting illness — which is the only thing it is for.

    THERE IS NO TRACKER FIELD AND NO FORGE FIELD, and that absence is the design. A stub would be
    a thing to call; a raising double would be a thing to call and then catch. Nothing here holds
    one, so `rehearse` has no expression it could write that reaches a client's board."""

    project_name: str
    #: `worker` or `local` (`readiness.where_this_answers_for`). Never guessed.
    measured_on: Callable[[], str]
    #: Which box a JOB would get here (`runtime/temporal/io.default_sandbox`). Reported, because a
    #: round taken in a box the factory does not use proves the wrong box.
    sandbox_kind: Callable[[], str]
    #: The image that box runs (`factory.resolve_box_image`).
    image: Callable[[], str]
    #: `(ok, detail, remedy)` — is the box PROVEN for these exact commands right now?
    #:
    #: COMPOSED, NEVER RE-IMPLEMENTED. Stations 1-5 of the card's list (image digest, toolbox
    #: variant, image contract, `setup:`, `validate:` on untouched main, per-component gate
    #: executability, harness binary, auth route inside the box, TLS egress) are `box_prove.prove`,
    #: they are good, and they cost nothing. Re-running them here would double a ten-minute wait;
    #: re-writing them here would be a second implementation that drifts. So this consults the
    #: recorded proof and REFUSES to spend money without one — which is also the C-35 lesson stated
    #: as a precondition: paying for an agent pass to discover `ruff: not found` is the exact waste
    #: `box prove` was built to stop.
    box_ready: Callable[[], tuple[bool, str, str]]
    #: Whether a valid proof covers the very commands the gates stage would run. Feeds the
    #: `gates_may_run is None` branch — see `Consent`.
    gates_already_proven: Callable[[], bool]
    #: The NAMES the client asked their box to receive (`project.box.env`). READ AND DISCARDED —
    #: it is here so the report can say what was withheld, never so the box can receive it.
    client_box_env: Callable[[], tuple[str, ...]]
    #: The names the rehearsal box IS built with: the harness auth route's, and nothing else.
    route_env_names: Callable[[], tuple[str, ...]]
    #: Build the box. Constructed, not started — `prepare` is what touches a daemon.
    build_box: Callable[[], object]
    #: The resolved repository DIRECTORY (`factory.resolve_repo_path`) and its manifest.
    repo_path: Callable[[], object]
    manifest: Callable[[], object]
    #: The real executor for this project (`adapters.agent.registry.build_executor`).
    executor: Callable[[], object]
    #: The real reviewer, or None when this project reviews with nothing.
    reviewer: Callable[[], object | None]
    #: `(ticket, workspace) -> AgentContext` — the same `orchestrator.context.build_context` a job
    #: gets, so the agent arrives with this project's real constraints and guidelines.
    context: Callable[[object, object], object]
    #: Past `agent_run` telemetry rows for this project. `None` = could not be read at all, which
    #: is not the same answer as `[]` and must not print the same sentence.
    past_runs: Callable[[], list[dict] | None]
    #: The commit identity (`credentials.bot_identity`).
    bot: Callable[[], object]
    #: Whether the executor can be TOLD the turn ceiling. False → it is measured afterwards and the
    #: report says so, rather than presenting a bound nobody holds.
    turn_cap_enforced: Callable[[], bool]
    turn_cap: int = DEFAULT_TURN_CAP


# ── the round ───────────────────────────────────────────────────────────────────────────────────

def _box_cannot_answer_this_question(kind: str) -> tuple[str, str] | None:
    """`(message, remedy)` when this box cannot make the round MEAN anything, else `None`.

    A DIFFERENT CLAIM FROM `_owns_its_checkout`, AND THEY ARE KEPT APART ON PURPOSE. That one is
    about SAFETY and is measured in the box; this one is about VALIDITY and is a table lookup. A
    round is an answer to *"does the factory work HERE"*, and "here" is the image a ticket would
    actually run in — ADR-0037 makes that image the CLIENT's. `BoxTraits.honours_image is False`
    says this box cannot run it, so a green round taken in one certifies a box no ticket ever gets.

    ASKED OF THE BOX'S OWN TRAITS, NEVER OF A VENDOR NAME. `factory.resolve_box_image` states the
    rule and pays for the alternative in its own docstring: its first version tested
    `sandbox == "fargate"` and therefore let `worktree` — the CLI's default — ignore the client's
    declared image in silence.

    AN UNKNOWN KIND IS NOT THIS FUNCTION'S TO REPORT. The registry raises with the list of boxes it
    does know, which is a better sentence than one invented here; returning `None` lets it through
    to that raise. It is unreachable in practice — this runs after `build_sandbox` has already
    accepted the kind — and it is written anyway, because a guard whose failure mode is a
    `KeyError` inside a report is not a guard."""
    from openfactory.adapters.sandbox.registry import box_traits

    try:
        traits = box_traits(kind)
    except ValueError:
        return None
    if traits.honours_image:
        return None
    return (
        f"the `{kind}` box cannot run this project's image, so a round taken in it would prove a "
        "box no ticket of yours ever runs in",
        f"`{kind}` ignores `box.image` by construction (`BoxTraits.honours_image`), and this "
        "round's entire product is a verdict about YOUR environment — the image, its toolchain, "
        "your `setup:` inside it. Point the deployment at a box that runs the declared image "
        "(`OPENFACTORY_SANDBOX=container`) and run the round again. Nothing was started",
    )


class _Runner:
    """One round in progress. A class only so the stations can share the box, the clock and the
    two callbacks without threading nine arguments through eight functions."""

    def __init__(self, p: Probes, consent: Consent,
                 on_start: Callable[[str], None] | None,
                 on_stage: Callable[[Stage], None] | None) -> None:
        self.p = p
        self.consent = consent
        self._on_start = on_start
        self._on_stage = on_stage
        self.on = p.measured_on()
        self.stages: list[Stage] = []
        self.box: object | None = None
        self.workspace: object | None = None
        self.ticket: object | None = None
        self.diff_text: str = ""
        self.touched: list[str] = []
        self.validations: list[object] = []

    # -- announcing -------------------------------------------------------------------------
    def announce(self, name: str) -> float:
        """A station is STARTING — the room needs the plan advancing, not just its outcomes, and an
        agent pass is minutes of silence otherwise.

        ONLY STATIONS THAT ACTUALLY RUN ARE ANNOUNCED. A station the round never reached still
        arrives on `on_stage` (as `----`, so the report cannot read as complete when it is not) but
        was never started, and announcing a start that never happened would be the same lie in the
        live view that a truncated report is in the written one."""
        if self._on_start is not None:
            try:
                self._on_start(name)
            except Exception:  # noqa: BLE001 — a broken console must never fail a round
                log.warning("the first-round progress callback raised on %s", name)
        return time.monotonic()

    def finish(self, stage: Stage, started: float | None = None) -> Stage:
        if started is not None and not stage.seconds:
            stage.seconds = time.monotonic() - started
        self.stages.append(stage)
        if self._on_stage is not None:
            try:
                self._on_stage(stage)
            except Exception:  # noqa: BLE001
                log.warning("the first-round stage callback raised on %s", stage.name)
        return stage

    def skip_rest(self, after: str) -> None:
        """Every station this round never reached, reported by name.

        A REPORT THAT SIMPLY STOPS IS A REPORT THAT LIES BY OMISSION. `STAGES` is what a full round
        does; a run that died at `workspace` and printed three lines reads, to somebody who has
        never seen a complete one, like a round with three stations. So the remaining names are
        emitted as `----` saying which station stopped the round."""
        seen = {s.name for s in self.stages}
        for name in STAGES:
            if name in seen:
                continue
            self.finish(_unanswered(
                name, f"not reached — the round stopped at `{after}`", on=self.on, reached=False))

    # -- the stations -----------------------------------------------------------------------
    def box_stage(self) -> bool:
        started = self.announce("box")
        try:
            ok, detail, remedy = self.p.box_ready()
        except Exception as exc:  # noqa: BLE001 — a broken probe is a finding, not a traceback
            self.finish(_fail("box", f"could not ask whether the box is proven: {exc}",
                              "this is a fault in the check itself — run `openfactory box "
                              f"status {self.p.project_name}` by hand to see the raw error",
                              on=self.on), started)
            return False
        if not ok:
            self.finish(_fail("box", detail, remedy, on=self.on), started)
            return False
        self.finish(_ok("box", detail, on=self.on), started)
        return True

    def workspace_stage(self) -> bool:
        started = self.announce("workspace")
        withheld = tuple(self.p.client_box_env())
        carried = tuple(self.p.route_env_names())
        kind = self.p.sandbox_kind()
        try:
            self.box = self.p.build_box()
        except Exception as exc:  # noqa: BLE001 — an unbuildable box IS the finding
            # NAME THE BOX KIND. `build_sandbox` RAISES for a remote box, and a cloud deployment
            # declares one (`OPENFACTORY_SANDBOX=fargate`; nothing is inferred from a cluster
            # variable).
            # A remedy about `docker ps -a` on that deployment sends a reader to a daemon that was
            # never involved — the same shape as `doctor`'s board message blaming a credential for
            # a board that does not exist.
            #
            # THE BUILD IS ITS OWN TRY, AHEAD OF THE TRAIT CHECK BELOW, so this message keeps the
            # box that cannot be built at all. A guard placed before it would answer the remote box
            # with a sentence about images and lose the only accurate thing said about fargate.
            self.finish(_fail(
                "workspace", f"the {kind} box could not be started: {str(exc)[:300]}",
                "this is the box itself, before any of your commands ran — a leftover container "
                "from a crashed run, an image that cannot keep alive, a daemon that refused, or a "
                "box kind this process cannot drive directly (a remote one). `docker ps -a` and "
                f"remove anything named {self.rehearsal_box_prefix()}*",
                on=self.on), started)
            return False
        if refusal := _box_cannot_answer_this_question(kind):
            # BEFORE `prepare`, DELIBERATELY, and this is the whole reason the build was split out
            # above: `WorktreeSandbox.prepare` runs `git branch -D` and `git worktree add -b` IN
            # THE REPOSITORY IT WAS HANDED. Refusing after it would already have written a branch
            # into the client's own checkout — an artefact this round then does not clean up.
            self.finish(_fail("workspace", *refusal, on=self.on), started)
            return False
        try:
            manifest = self.p.manifest()
            self.workspace = self.box.prepare(
                repo_path=self.p.repo_path(), base_branch=manifest.base_branch,
                branch=REHEARSAL_BRANCH,
            )
        except Exception as exc:  # noqa: BLE001 — an unstartable workspace IS the finding
            self.finish(_fail(
                "workspace", f"the {kind} box could not make a workspace: {str(exc)[:300]}",
                "this is the clone itself, before any of your commands ran — an unreadable "
                "repository path, a base branch that does not exist in it, or a daemon that "
                f"refused. `docker ps -a` and remove anything named "
                f"{self.rehearsal_box_prefix()}*",
                on=self.on), started)
            return False
        if not self._owns_its_checkout(started):
            return False
        # THE IMAGE IS REPORTED, NEVER LOAD-BEARING. A client whose stack is .NET 8 asks which
        # image was proven, and until this line `Probes.image` was a documented seam that nothing
        # asked — the defect class this module's own docstring is about. `resolve_box_image` can
        # raise (a declared image a box cannot honour), and failing a box that is already RUNNING
        # over a label would be a failure invented by the report, so a read that fails says so.
        try:
            image = self.p.image()
        except Exception as exc:  # noqa: BLE001
            image = f"image unreadable ({str(exc)[:80]})"
        # NAME WHAT WAS WITHHELD, in the report a client reads. The reduction is the security
        # decision this round rests on, and a security decision nobody can see is one nobody can
        # check — the same reason `box.env` lists names in the registry instead of values.
        note = (f"; {len(withheld)} name(s) from this project's `box.env` were WITHHELD "
                f"({', '.join(sorted(withheld))})" if withheld else "")
        self.finish(_ok(
            "workspace",
            f"a throwaway clone of its own on `{REHEARSAL_BRANCH}` in {image}, carrying only the "
            f"harness route's {len(carried)} variable name(s){note}", on=self.on), started)
        return True

    def rehearsal_box_prefix(self) -> str:
        """What `docker ps` calls THIS round's box — and never a running job's.

        `probes_for` builds the box with `project=f"{name}-rehearsal"`, and `_container_name`
        prefixes `openfactory-`, so the round's containers are `openfactory-<name>-rehearsal-*`
        while a live job's are `openfactory-<name>-<issue>`. The remedies used to say "remove
        anything named `openfactory-<name>-*`", which matches both: an operator following that
        sentence during an incident kills the box of a job that is running. A remedy is an
        instruction, and an
        instruction that can destroy work is a defect in the same way a wrong verdict is.
        `test_the_remedy_names_the_box_this_round_actually_creates` ties this string to the name
        the live wiring really produces, so it cannot drift into being decoration."""
        return f"openfactory-{self.p.project_name}-rehearsal-"

    def _owns_its_checkout(self, started: float) -> bool:
        """PROVE THIS CHECKOUT IS A COPY — before `setup:`, before the agent, before the removal.

        THE SAFETY THIS WHOLE MODULE CLAIMS IS A PROPERTY OF THE BOX, NOT OF THIS FILE, and until
        this station asked, the module asserted it without reading it. The docstring above says
        *"the client's repository, as a THROWAWAY clone the box makes"* and *"every git remote is
        REMOVED from the clone"*. Both are true of `ContainerSandbox`, which does
        `git clone --local --no-hardlinks` into a temporary directory. Neither is true of
        `WorktreeSandbox`, which does `git worktree add` INSIDE the repository it was handed —
        and `OPENFACTORY_SANDBOX=worktree` is a documented value
        (`docs/reference/configuration.md`),
        returned verbatim by `default_sandbox()`, whose builder ignores the `image=`/`project=`
        arguments `probes_for` passes rather than rejecting them. So the round could be configured
        into it, in silence.

        WHAT THAT COSTS, MEASURED WITH REAL GIT RATHER THAN REASONED ABOUT: a linked worktree
        shares its parent's config, so `git remote remove origin` in the worktree deletes `origin`
        FROM THE CLIENT'S OWN REPOSITORY — permanently, since nothing here puts it back, and
        invisibly, since the round would then report `isolation ok` and go on to spend two agent
        passes. Every later fetch and push out of that checkout fails, for a reason nobody can
        connect to a rehearsal that said it proved the loop.

        So the guarantee is measured, once, in the box, before anything can act on it. A read that
        FAILS is not a pass: an unreadable answer here is exactly the shape ("absence reads as
        compliance") that this codebase pays for most."""
        rc, out = self.box.run(workspace=self.workspace, command=OWN_CHECKOUT_PROBE, timeout=60)
        lines = [line.strip() for line in (out or "").splitlines() if line.strip()]
        if rc != 0 or len(lines) != 2:
            self.finish(_fail(
                "workspace",
                f"could not ask this workspace whether it owns its own git directory: "
                f"`{OWN_CHECKOUT_PROBE}` exited {rc}\n{_tail(out, 6)}",
                "the round refuses to run in a checkout it cannot prove is a copy — the next "
                "stations run your `setup:`, remove every git remote and then start an agent, and "
                "each of those in a SHARED checkout edits the repository it came from",
                on=self.on), started)
            return False
        git_dir, common_dir = lines
        if git_dir != common_dir:
            self.finish(_fail(
                "workspace",
                f"this workspace SHARES another repository's git directory ({common_dir}) — it is "
                "a linked worktree, not a clone",
                "this round removes every git remote from the checkout it runs in, and in a "
                "linked worktree that edits the config of the repository it was carved from: the "
                "client's own `origin`, gone, with nothing here to put it back. Give the round a "
                "box that clones — `OPENFACTORY_SANDBOX=container`. Nothing was spent and no "
                "remote was "
                f"removed; the box did leave the branch `{REHEARSAL_BRANCH}` in that repository "
                f"when it made the worktree — `git branch -D {REHEARSAL_BRANCH}` there",
                on=self.on), started)
            return False
        return True

    def setup_stage(self) -> bool:
        """RUN THE CLIENT'S `setup:` IN THIS BOX — which a first version of this module did not.

        FOUND BY RUNNING IT, not by reading it. The round was measured end to end against
        `py-simple` on a real docker daemon and the gate stage reported `test=exit 1`: the box was
        fresh, `setup: python -m pip install -q pytest` had never run in it, and the client's own
        test command failed for a reason that had nothing to do with the client.

        The mistake was a reasonable-sounding one and worth naming, because it is the whole shape
        of this card: `box prove` DOES run `setup:` — in ITS box, which it then destroys. Composing
        that proof as a precondition (see `Probes.box_ready`) proves the commands WORK; it does not
        leave their effects anywhere this round can use. A job runs `setup:` in its own box
        (`machine.py`, just before the executor) for exactly the same reason, and a round claiming
        to be "the real machine" that skipped it would be measuring a box no ticket ever runs in.

        BEFORE THE ISOLATION STATION, DELIBERATELY. `setup:` is the CLIENT's own declared install —
        `git submodule update --init`, a private feed restore — and some of it legitimately needs
        the remote that the next station removes. Nothing here is agent-written code; the invariant
        this round makes is that the remote is gone before the AGENT runs, and it is."""
        started = self.announce("setup")
        commands = list(self.p.manifest().setup)
        if not commands:
            # `[]` IS A READING, NOT AN ABSENCE. A project whose box image already carries its
            # toolchain really does need no install, and reporting that as a gap would send
            # somebody to write a `setup:` line for nothing.
            self.finish(_ok("setup", "this project declares no setup command", on=self.on),
                        started)
            return True
        for command in commands:
            rc, out = self.box.run(workspace=self.workspace, command=command,
                                   timeout=SETUP_TIMEOUT)
            if rc != 0:
                self.finish(_fail(
                    "setup", f"`{command}` exited {rc}\n{_tail(out)}",
                    "this is YOUR `setup:` running in YOUR image — a private feed needing a "
                    "credential is the usual cause, and this round deliberately withholds every "
                    "name in `box.env` (it carries only the harness's own route), so a setup that "
                    "needs one will fail here and succeed in a real job. That difference is the "
                    "finding",
                    on=self.on), started)
                return False
        self.finish(_ok("setup", f"{len(commands)} command(s)", on=self.on), started)
        return True

    def isolation_stage(self) -> bool:
        """REMOVE EVERY REMOTE, AND PROVE IT IS GONE — before the agent exists in this round.

        What this stops is the AGENT: untrusted code, in a box with outbound internet, in a
        checkout that would otherwise know where the client's repository lives. It is not what
        stops the PLATFORM from pushing — nothing in this module imports a forge, and
        `publish_branch` is never called — and conflating the two is how a second layer gets sold
        as the first (see the module docstring on credentials).

        AND IT VERIFIES THE BASE REF SURVIVED, which is not paranoia but a measured trap.
        `git remote remove origin` deletes `refs/remotes/origin/*`, and `diff_paths` runs
        `git diff --name-only <base>..HEAD` and returns `[]` WHEN THAT COMMAND FAILS. So a base
        branch that only existed as a remote-tracking ref would make the diff station report "the
        agent wrote nothing" about a diff that is sitting right there — a failure wearing an
        answer's clothes, one station after the money was spent."""
        started = self.announce("isolation")
        box, ws = self.box, self.workspace
        rc, out = box.run(workspace=ws, command="git remote", timeout=60)
        if rc != 0:
            self.finish(_fail(
                "isolation", f"`git remote` exited {rc} in the box\n{_tail(out)}",
                "the round refuses to run an agent in a checkout whose remotes it could not "
                "read — that is the one guarantee it makes about your branches",
                on=self.on), started)
            return False
        remotes = [line.strip() for line in (out or "").splitlines() if line.strip()]
        for name in remotes:
            box.run(workspace=ws, command=f"git remote remove {name}", timeout=60)
        rc, out = box.run(workspace=ws, command="git remote", timeout=60)
        left = [line.strip() for line in (out or "").splitlines() if line.strip()]
        if rc != 0 or left:
            self.finish(_fail(
                "isolation",
                f"the clone still has remote(s) after removal: {', '.join(left) or '(unreadable)'}",
                "this round may not run an agent in a checkout that can reach your repository. "
                "Nothing was spent; the box is the thing to look at",
                on=self.on), started)
            return False
        base = self.p.manifest().base_branch
        rc, out = box.run(workspace=ws, command=f"git rev-parse --verify {base}", timeout=60)
        if rc != 0:
            self.finish(_fail(
                "isolation",
                f"`{base}` no longer resolves in the clone once the remotes are gone\n{_tail(out)}",
                f"the diff is read as `git diff {base}..HEAD`, and a base ref that does not "
                "resolve makes that command fail and report an EMPTY diff — the round would blame "
                f"the agent for writing nothing. Check `base_branch` in this project's manifest",
                on=self.on), started)
            return False
        self.finish(_ok(
            "isolation",
            f"{len(remotes)} remote(s) removed and verified gone ({', '.join(remotes) or 'none'}); "
            f"`{base}` still resolves", on=self.on), started)
        return True

    def agent_stage(self) -> bool:
        """One real pass of the real executor, on the synthetic ticket, in the real box."""
        started = self.announce("agent")
        manifest = self.p.manifest()
        self.ticket = rehearsal_ticket(repo=self.p.project_name,
                                       base_branch=manifest.base_branch)
        try:
            agent = self.p.executor()
            ctx = self.p.context(self.ticket, self.workspace)
            result = agent.execute(sandbox=self.box, workspace=self.workspace, context=ctx)
        except Exception as exc:  # noqa: BLE001
            self.finish(_fail("agent", f"the executor raised: {str(exc)[:300]}",
                              "this is the harness itself, not your code — check the box's "
                              "harness binary and auth route (`openfactory box prove` covers "
                              "both)",
                              on=self.on), started)
            return False
        cost = getattr(result, "cost_usd", None)
        turns = getattr(result, "num_turns", None)
        common = {"cost_usd": cost, "num_turns": turns,
                  "input_tokens": getattr(result, "input_tokens", None),
                  "output_tokens": getattr(result, "output_tokens", None)}
        # A PAUSE IS NOT A FAILURE OF THE ENVIRONMENT AND MUST NOT READ AS ONE. A rate limit or an
        # expired credential says nothing about whether this factory works here; reporting it as
        # `agent: FAIL` sends a client to look at their repository for a problem that is ours.
        if pause := getattr(result, "pause_reason", None):
            self.finish(_fail(
                "agent", f"the harness paused ({pause}) before finishing — this is OUR side, not "
                         "your environment",
                "a rate limit or an auth problem on the harness account. Nothing here is a "
                "finding about your repository; retry the round when it clears",
                on=self.on, **common), started)
            return False
        if not getattr(result, "ok", False):
            self.finish(_fail(
                "agent", f"the executor did not finish: "
                         f"{(getattr(result, 'summary', '') or '')[:200]}",
                "read the pass's own summary above — on a first round the usual causes are a "
                "repository with no test framework (a legitimate answer: see the round's ticket) "
                "or a box missing a tool the tests need",
                on=self.on, **common), started)
            return False
        over = (turns is not None and turns > self.p.turn_cap)
        message = f"{(getattr(result, 'summary', '') or 'finished')[:180]}"
        if over:
            message += (f"\nthe pass used {turns} turns, past this round's ceiling of "
                        f"{self.p.turn_cap} — a real ticket here will be expensive")
        self.finish(_ok("agent", message, on=self.on, **common), started)
        return True

    def diff_stage(self) -> bool:
        """Commit what the agent wrote, then read the diff — and never let a failure look empty."""
        started = self.announce("diff")
        box, ws = self.box, self.workspace
        manifest = self.p.manifest()
        base = manifest.base_branch
        bot = self.p.bot()
        import shlex

        author = (f"GIT_AUTHOR_NAME={shlex.quote(bot.name)} "
                  f"GIT_AUTHOR_EMAIL={shlex.quote(bot.email)} "
                  f"GIT_COMMITTER_NAME={shlex.quote(bot.name)} "
                  f"GIT_COMMITTER_EMAIL={shlex.quote(bot.email)} ")
        msg = shlex.quote(f"{REHEARSAL_ID}: environment rehearsal (never pushed)")
        box.run(workspace=ws, command=f"git add -A && {author}git commit -m {msg} || true",
                timeout=120)
        paths = list(box.diff_paths(workspace=ws))
        if not paths:
            # `diff_paths` swallows a non-zero exit into `[]`, so "nothing was written" and "the
            # diff could not be read" arrive identical. `git status --porcelain` tells them apart:
            # a dirty tree here means the COMMIT failed, which is our problem, not the agent's.
            rc, dirty = box.run(workspace=ws, command="git status --porcelain", timeout=60)
            if rc == 0 and (dirty or "").strip():
                self.finish(_fail(
                    "diff", "the agent wrote files and the commit did not take them:\n"
                            f"{_tail(dirty, 10)}",
                    "the working tree is dirty after `git add -A && git commit` — check the box's "
                    "git identity and whether the workspace is writable",
                    on=self.on), started)
                return False
            self.finish(_fail(
                "diff", "the agent produced no change at all — a real ticket here would open no PR",
                "read the agent's summary above. A repository with no test framework is a "
                "legitimate 'no' (the round's ticket asks for exactly that answer); anything else "
                "means the pass could not work in this box",
                on=self.on), started)
            return False
        # THE EXIT CODE IS READ, AND IT WAS NOT. This was `_, self.diff_text = box.run(...)`, so a
        # `git diff` that FAILED handed its own error text to the reviewer as the diff — and the
        # reviewer would then return a decision about the client's code that nothing had read. That
        # is fx-ado PR #9 (see `review_stage`) manufactured one station earlier, where it is worse:
        # there the envelope was unparseable and said so, here the input is a plausible-looking
        # string. `diff_paths` having just succeeded makes this unlikely, not impossible — and
        # "unlikely" is what every collapsed failure in this repository was before it happened.
        rc, diff_text = box.run(workspace=ws, command=f"git diff {base}..HEAD", timeout=120)
        if rc != 0:
            self.finish(_fail(
                "diff",
                f"{len(paths)} file(s) changed and `git diff {base}..HEAD` exited {rc}\n"
                f"{_tail(diff_text, 8)}",
                "the diff is the reviewer's ENTIRE input, so a round that carried on here would "
                "buy a judgement of your code from a pass that read an error message. The change "
                "is real; reading it is what failed",
                on=self.on), started)
            return False
        self.diff_text = diff_text
        from openfactory.orchestrator.validation import resolve_touched_components

        self.touched = resolve_touched_components(paths, manifest)
        where = f" · components: {', '.join(self.touched)}" if self.touched else ""
        self.finish(_ok("diff", f"{len(paths)} file(s): {', '.join(paths[:6])}"
                                f"{' …' if len(paths) > 6 else ''}{where}", on=self.on), started)
        return True

    def gates_stage(self) -> bool:
        """THE CLIENT'S OWN GATES, RUN BY THE FACTORY'S OWN GATE LOOP — not by a copy of it.

        `machine.JobRunner._run_validations` is called here as a plain function with a three-field
        stand-in for `self`. That looks like a trick and it is a deliberate refusal to write the
        loop twice: the loop resolves `applicable_validations` for the TOUCHED components, honours
        each gate's `advisory` flag and its `timeout_minutes`, and fills a `ValidationResult` the
        reviewer then reads. A twelve-line copy here would agree with it today and disagree with it
        the first time one of those details changes — and the disagreement would be invisible,
        because both would be green.

        The stand-in is safe because the method's `self` usage is bounded, and that boundary is
        ASSERTED rather than assumed: `test_the_gate_loop_stays_reusable` walks the method's AST
        and fails the day it reads a fourth attribute. Without that test this would be exactly the
        kind of cleverness that breaks in production and nowhere else."""
        started = self.announce("gates")
        if self.consent.gates_may_run is False:
            self.finish(_unanswered(
                "gates",
                "not run — somebody said this project's suite writes to a real system from here",
                on=self.on))
            return True
        if self.consent.gates_may_run is None and not self.p.gates_already_proven():
            self.finish(_unanswered(
                "gates",
                "not run — nobody has answered whether running your suite here writes to a real "
                "system (a shared dev database, a queue, a third-party sandbox), and no box proof "
                "covers these commands. Answer it, or run `openfactory box prove` first",
                on=self.on))
            return True
        from openfactory.orchestrator.machine import JobRunner

        host = _GateHost(sandbox=self.box, manifest=self.p.manifest())
        try:
            results = JobRunner._run_validations(host, self.workspace, self.touched, self.ticket)
        except Exception as exc:  # noqa: BLE001
            self.finish(_fail("gates", f"the gate loop raised: {str(exc)[:300]}",
                              "this is the platform's own validation runner, not your commands — "
                              "the raw error above is the thing to read",
                              on=self.on), started)
            return False
        self.validations = list(results)
        if not self.validations:
            # `applicable_validations` returning nothing is a READING, and a damaging one: a
            # project with no gates merges on a vacuously green run. `conformance`/`floor_reason`
            # is the component that owns that judgement, so this stage reports the fact and names
            # it rather than inventing a second floor here.
            self.finish(_fail(
                "gates", "this project declares no gate that a diff to these files would run",
                "a run with no gates reports green having proven nothing — declare at least "
                f"`validate.test` in the manifest, then "
                f"`openfactory conformance {self.p.project_name}`",
                on=self.on), started)
            return False
        blocking = [v for v in self.validations if not v.passed and not v.advisory]
        def _said(v) -> str:
            if v.passed:
                return "pass"
            # "could not run" and "exit 127" are the same number and different facts; the operator
            # reading this line is deciding whether to look at the code or at the image.
            return "could not run" if v.unrunnable else f"exit {v.exit_code}"

        summary = " · ".join(
            f"{v.name}={_said(v)}" + (" (advisory)" if v.advisory else "")
            for v in self.validations)
        if blocking:
            # A COMMAND THAT IS NOT IN THE BOX GETS THE OTHER REMEDY, and this is the moment it is
            # most likely to be found: the advice below is about the client's CODE and costs an
            # agent pass per attempt, which is exactly the wrong thing to tell somebody whose box
            # is missing `ruff`. A real ticket does not enter the repair loop for this any more —
            # it holds — so promising that here would also be describing behaviour that is gone.
            never_ran = [v for v in blocking if v.unrunnable]
            if len(never_ran) == len(blocking):
                self.finish(_fail(
                    "gates", f"{summary}\n" + "\n".join(f"{v.name}: {v.unrunnable}"
                                                        for v in never_ran),
                    "the command is not available where the gates run, so nothing was checked. "
                    "This is the box, not your code: install the tool in the image (or correct "
                    "the command in the manifest) and run this again — a real ticket holds here "
                    "rather than paying an agent to repair a diff that is not what is wrong",
                    on=self.on), started)
                return False
            self.finish(_fail(
                "gates", f"{summary}\n{_tail(blocking[0].output_tail, 12)}",
                "these are YOUR gates, run by the factory against a diff that only adds a test. "
                "A real ticket would enter the repair loop here — which costs another agent pass "
                "per attempt, so this is the most expensive thing on this list to leave broken",
                on=self.on), started)
            return False
        self.finish(_ok("gates", summary, on=self.on), started)
        return True

    def review_stage(self) -> bool:
        started = self.announce("review")
        reviewer = self.p.reviewer()
        if reviewer is None:
            self.finish(_unanswered(
                "review", "this project reviews with nothing — `review_mode` is off, or no "
                          "reviewer is configured for its harness", on=self.on))
            return True
        from openfactory.adapters.reviewer.base import ReviewInput

        try:
            result = reviewer.review(
                sandbox=self.box, workspace=self.workspace,
                review_input=ReviewInput(ticket=self.ticket, diff=self.diff_text,
                                         validations=list(self.validations)),
            )
        except Exception as exc:  # noqa: BLE001
            self.finish(_fail("review", f"the reviewer raised: {str(exc)[:300]}",
                              "the reviewer is its own harness pass — check its auth route and "
                              "the harness binary in the box",
                              on=self.on), started)
            return False
        common = {"cost_usd": getattr(result, "cost_usd", None),
                  "num_turns": getattr(result, "num_turns", None),
                  "input_tokens": getattr(result, "input_tokens", None),
                  "output_tokens": getattr(result, "output_tokens", None)}
        # A REVIEW THAT COULD NOT BE READ IS NOT A REJECTION. `machine._pr_body` learned this on
        # fx-ado PR #9 — a correct diff headed "rejected" because the envelope did not parse — and
        # a first round is where that mistake costs most: the one thing a client is watching is
        # whether the independent review works, and "rejected" about our own parser reads as the
        # factory judging their code.
        summary = (getattr(result, "summary", "") or "")
        unread = (result.score == 0 and not result.findings
                  and ("could not be parsed" in summary or "never ran" in summary))
        if unread:
            self.finish(_fail(
                "review", f"the reviewer produced nothing readable: {summary[:160]}",
                "this is not a judgement about the diff — nothing reviewed it. The reviewer "
                "harness is what to look at, not the code",
                on=self.on, **common), started)
            return False
        self.finish(_ok("review", f"{result.decision} (score {result.score}) · "
                                  f"{len(result.findings)} finding(s)", on=self.on, **common),
                    started)
        return True

    def teardown_stage(self) -> None:
        """DESTROY THE CLONE, AND REPORT WHETHER IT WAS DESTROYED.

        The physical guarantee ends here. A cleanup that failed silently leaves a container holding
        a checkout of the client's code on the worker — so a leak is a stage, with a remedy, rather
        than a `log.warning` nobody configured a handler for (the `save()` lesson: this CLI sets up
        no logging at all, so a warning is a message to nobody)."""
        started = self.announce("teardown")
        if self.box is None or self.workspace is None:
            self.finish(_unanswered("teardown", "no box was ever started", on=self.on), started)
            return
        try:
            self.box.cleanup(workspace=self.workspace)
        except Exception as exc:  # noqa: BLE001
            self.finish(_fail(
                "teardown", f"the rehearsal's box could not be destroyed: {str(exc)[:200]}",
                "a container holding a clone of your repository is still on this machine — "
                f"`docker ps -a` and remove anything named {self.rehearsal_box_prefix()}*",
                on=self.on), started)
            return
        self.finish(_ok("teardown", "the clone and its box are gone", on=self.on), started)


@dataclass
class _GateHost:
    """The three attributes `JobRunner._run_validations` reads, and nothing else.

    Deliberately not a `JobRunner`: constructing one requires a tracker and a forge, which is the
    precise pair this round may not hold. See `gates_stage` for why the real loop is called instead
    of copied, and `test_the_gate_loop_stays_reusable` for the assertion that keeps this honest."""

    sandbox: object
    manifest: object

    def _emit(self, ticket: object, kind: str, message: str, **data: object) -> None:
        """The job journal's seam. A round has no job and no journal, so this logs.

        NOT A `pass`. The gate loop emits one line per gate — the only place a long suite says
        anything while it runs — and swallowing them would make the quietest part of the round
        the one most likely to hang."""
        log.info("first round · %s · %s", kind, message)


def _tail(text: str, lines: int = 20) -> str:
    return "\n".join((text or "").splitlines()[-lines:])


def rehearse(p: Probes, *, consent: Consent,
             on_start: Callable[[str], None] | None = None,
             on_stage: Callable[[Stage], None] | None = None) -> Rehearsal:
    """Run the first round. Reports as it goes; spends nothing without consent.

    THE ORDER IS THE PIPELINE'S ORDER and every station is a precondition of the next, so a failure
    stops the round rather than stacking a second misleading error on top of the first — the same
    reasoning `box_prove.prove` states when it returns early ("everything after this would fail for
    one reason and say it six ways"). The stations that never ran are still REPORTED, by name, as
    `----`, so a short report can never be mistaken for a complete one.

    TEARDOWN ALWAYS RUNS. It is in a `finally`, because the one thing worse than a round that
    failed is a round that failed and left a container holding a clone of the client's repository.
    """
    on = p.measured_on()
    estimate = estimate_cost(p)
    run = Rehearsal(project=p.project_name, measured_on=on, sandbox_kind=p.sandbox_kind(),
                    estimate=estimate, consent=consent)
    if not consent.spend_approved:
        # NOTHING HAS BEEN CALLED YET, and that is the point of putting this first. The estimate
        # above reads telemetry and costs no tokens; the harness is not even constructed. A caller
        # gets the number, the bound, and a round it can decline.
        run.not_run = ("the spend was not approved — this round makes "
                       f"{estimate.passes} real agent pass(es)")
        return run

    runner = _Runner(p, consent, on_start, on_stage)
    try:
        if not runner.box_stage():
            runner.skip_rest("box")
        elif not runner.workspace_stage():
            runner.skip_rest("workspace")
        elif not runner.setup_stage():
            runner.skip_rest("setup")
        elif not runner.isolation_stage():
            runner.skip_rest("isolation")
        elif not runner.agent_stage():
            runner.skip_rest("agent")
        elif not runner.diff_stage():
            runner.skip_rest("diff")
        elif not runner.gates_stage():
            runner.skip_rest("gates")
        elif not runner.review_stage():
            runner.skip_rest("review")
    finally:
        if not any(s.name == "teardown" and s.reached for s in runner.stages):
            runner.stages = [s for s in runner.stages if s.name != "teardown"]
            runner.teardown_stage()
    run.stages = sorted(runner.stages, key=lambda s: STAGES.index(s.name))
    return run


# ── the live wiring ─────────────────────────────────────────────────────────────────────────────

def probes_for(project, *, image: str | None = None, turn_cap: int = DEFAULT_TURN_CAP) -> Probes:
    """The real probes: the deployment's own box, harness, gates and reviewer.

    EVERY PROBE IS LAZY. Nothing here resolves a repository, loads a manifest, contacts a daemon or
    builds a harness — `probes_for` is cheap, so a test can construct it and assert on what the box
    WOULD be built with (which is how the credential-reduction guard is written) without needing
    docker."""
    from openfactory.adapters.agent.registry import build_executor, build_reviewer
    from openfactory.adapters.sandbox.registry import build_sandbox
    from openfactory.box_prove import _route_names, component_gates, is_valid, load
    from openfactory.credentials import bot_identity
    from openfactory.factory import resolve_box_image, resolve_repo_path
    from openfactory.loader import load_manifest
    from openfactory.onboarding.readiness import where_this_answers_for
    from openfactory.orchestrator.validation import gate_commands
    from openfactory.runtime.temporal.io import default_sandbox

    cached: dict[str, object] = {}

    def _repo():
        if "repo" not in cached:
            cached["repo"] = resolve_repo_path(project)
        return cached["repo"]

    def _manifest():
        if "manifest" not in cached:
            cached["manifest"] = load_manifest(project, repo_root=_repo())
        return cached["manifest"]

    def _image() -> str:
        return image or resolve_box_image(project, sandbox=default_sandbox())

    def _route_env() -> tuple[str, ...]:
        from openfactory.adapters.agent.routes import resolve_route

        return _route_names(resolve_route(project))

    def _proof():
        if "proof" not in cached:
            cached["proof"] = load(project.name)
        return cached["proof"]

    def _commands_hash() -> str:
        from openfactory.box_prove import _hash_commands

        m = _manifest()
        return _hash_commands(list(m.setup), gate_commands(m.validation), component_gates(m))

    def _gates_proven() -> bool:
        """Whether a VALID proof covers the very commands the gates stage would run.

        The commands hash is the load-bearing half: a proof taken before the client edited
        `validate:` covers different commands, and treating it as cover would be the checkbox
        `box_prove.is_valid` exists to replace."""
        proof = _proof()
        if proof is None:
            return False
        return is_valid(proof, digest=proof.digest, toolbox=proof.toolbox,
                        commands_hash=_commands_hash())

    def _box_ready() -> tuple[bool, str, str]:
        """Composed from `box_prove`, never re-derived. `is_valid` is asked with the CURRENT
        commands hash — the proof's own digest and toolbox are what it was taken against, and
        comparing those with themselves is `cli.py`'s bug, not a check."""
        proof = _proof()
        if proof is None:
            return (False, "the box has never been proven",
                    f"run `openfactory box prove {project.name}` — this round refuses to spend "
                    "an agent pass in a box nobody has checked can run your build (C-35: 47 "
                    "turns ended in `ruff: not found`)")
        if not proof.ok:
            return (False, f"the last box proof FAILED ({proof.at})",
                    f"run `openfactory box prove {project.name}` and fix what it reports — the "
                    "round below would fail for the same reason, at agent prices")
        if not _gates_proven():
            return (False, f"the box proof at {proof.at} no longer covers this project's commands",
                    f"`setup:`/`validate:` changed since the proof was taken — re-run "
                    f"`openfactory box prove {project.name}`")
        return (True, f"proven {proof.at} · {proof.image} @ {proof.digest[:19]}…", "")

    def _build_box():
        """THE REDUCED BOX. `extra_env` is the harness route's names and NOTHING ELSE.

        `factory.build_runner` forwards `project.box.env` here; this deliberately does not. That
        list is where a client names their forge token, their package-feed credential, their
        scanner key — every one of them readable by agent-written code inside the box, as
        `contracts/project.py` says in its own comment. A round whose safety rests on a removed git
        remote while handing the agent a push token has one layer, not two."""
        knobs = {
            key: value
            for key in ("network", "cache_volume", "cpus", "memory")
            if (value := getattr(getattr(project, "box", None), key, None)) is not None
        }
        import os

        if volume := (os.environ.get("OPENFACTORY_TOOLBOX_VOLUME") or "").strip():
            knobs["toolbox"] = volume
        return build_sandbox(default_sandbox(), image=_image(),
                             project=f"{project.name}-rehearsal",
                             root=_repo().parent / ".openfactory-worktrees",
                             extra_env=_route_env(), **knobs)

    def _agent():
        """The executor adapter, built AT MOST ONCE.

        CONSTRUCTING AN ADAPTER MAKES NO CALL AND COSTS NOTHING — the money is `execute()` and
        `review()`, and neither is reached without consent. It is cached anyway because
        `turn_cap_enforced` asks the same object a question, and `estimate_cost` runs BEFORE the
        consent gate: two independent builds there would be two harness constructions on a path
        whose entire promise is that it does nothing."""
        if "agent" not in cached:
            cached["agent"] = build_executor(project)
        return cached["agent"]

    def _executor():
        """The real executor, told the round's ceiling when its harness has one.

        `build_executor` takes no cap — the cap is the adapter's own (`ClaudeCodeAdapter.max_turns`,
        `--max-turns`). Setting it here rather than reporting a number afterwards is the difference
        between a bound and a description of what happened."""
        agent = _agent()
        if hasattr(agent, "max_turns"):
            agent.max_turns = turn_cap
        return agent

    def _context(ticket, workspace):
        from openfactory.orchestrator.context import build_context

        return build_context(_manifest(), _repo(), ticket,
                             knowledge_path=getattr(workspace, "host_path", None))

    def _past_runs() -> list[dict] | None:
        """This deployment's own recorded spend, or None when there is no memory to read.

        `records_of_kind` answers `[]` for both "nothing recorded" and "the read failed", which are
        opposite facts — so the absence of any sink is detected HERE, where it can still be told
        apart, rather than downstream where both arrive as an empty list."""
        import os

        from openfactory.api.metrics_view import _configured_sink
        from openfactory.observability.query import records_of_kind

        if _configured_sink() is None and not os.environ.get("OPENFACTORY_METRICS_TABLE"):
            return None
        return records_of_kind(project.name, "agent_run", limit=200)

    def _cap_enforced() -> bool:
        return hasattr(_agent(), "max_turns")

    return Probes(
        project_name=project.name,
        measured_on=lambda: where_this_answers_for(),
        sandbox_kind=default_sandbox,
        image=_image,
        box_ready=_box_ready,
        gates_already_proven=_gates_proven,
        client_box_env=lambda: tuple(getattr(getattr(project, "box", None), "env", None) or ()),
        route_env_names=_route_env,
        build_box=_build_box,
        repo_path=_repo,
        manifest=_manifest,
        executor=_executor,
        reviewer=lambda: (build_reviewer(project)
                          if getattr(_manifest(), "review_mode", "advisory") != "off" else None),
        context=_context,
        past_runs=_past_runs,
        bot=bot_identity,
        turn_cap_enforced=_cap_enforced,
        turn_cap=turn_cap,
    )


def first_round(project, *, consent: Consent, image: str | None = None,
                turn_cap: int = DEFAULT_TURN_CAP,
                on_start: Callable[[str], None] | None = None,
                on_stage: Callable[[Stage], None] | None = None) -> Rehearsal:
    """`probes_for` + `rehearse` — the one call a transport makes.

    NOTHING REACHES THIS YET, AND SAYING SO IS THE POINT. As of this change there is no `CATALOG`
    row, no CLI command and no panel button for the first round: `openfactory/actions/catalog.py`
    and
    `openfactory/cli.py` belong to another slice of #99 and were deliberately not edited here. A
    capability nothing reaches does not exist — this codebase has shipped that defect some twenty
    times — so this is a stated gap rather than a discovered one, and the wiring is three facts:

      1. the entry point is `first_round(project, consent=…)`; `rehearse` is the same round with
         the world already injected (what a test drives), and `estimate_cost(probes_for(project))`
         gives the number alone, touching no harness;
      2. `catalog._entry_point(module, *names)` resolves a verb by the names ITS CALLER passes —
         the sibling rows pass `("propose", "infer")` and `("check",)` — so a row for this round
         passes `("first_round",)`;
      3. IT MUST NOT RUN IN THE PROCESS THAT SERVED THE REQUEST. `POST /api/act/{name}` runs an
         action wherever the API is hosted, and that process is not the one carrying the sandbox —
         no docker socket, no toolbox, no checkout. Ours happens to be an App Runner service; the
         rule is not about ours, because a deployment behind k8s or nginx splits the same way and
         a laptop running everything in one process hides the split entirely. So the row delegates
         to the worker exactly as `_scan` delegates to Temporal. Every station below needs a box.
    """
    return rehearse(probes_for(project, image=image, turn_cap=turn_cap), consent=consent,
                    on_start=on_start, on_stage=on_stage)


#: `#142`, `PROJ-31`, `owner/repo#7` — every ref shape a tracker in this platform speaks. The
#: synthetic ticket's id must match NONE of them; `test_the_synthetic_ticket_is_not_a_tracker_ref`
#: is what makes that structural rather than a convention somebody remembers.
TRACKER_REF_SHAPES: tuple[str, ...] = (
    r"^#\d+$", r"^[A-Z][A-Z0-9]+-\d+$", r"^[\w.-]+/[\w.-]+#\d+$", r"^\d+$",
)


def looks_like_a_tracker_ref(value: str) -> bool:
    """Whether this string would be read as a card on somebody's board."""
    return any(re.match(shape, value or "") for shape in TRACKER_REF_SHAPES)
