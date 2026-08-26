"""Being on call, not being invoked (ADR-0020 §3).

Everything else the tech-lead does happens because something called it: a job parked, somebody asked
a question, a ticket needed sizing. That is a good diagnostician and a bad colleague. The failures
that cost the most are the ones no single event reports:

    a park nobody answered      #478 held the floor for eighteen hours and no event fired again
    an idle floor with a queue  the poller should be picking work up, and is not
    the same cause, again       three tickets failing the same way is one systemic problem
                                wearing three ticket numbers, and each diagnosis saw only its own

PURE, so the claim "the factory is stuck" is arithmetic somebody can check rather than something a
model asserted. The activity gathers the state; this decides what is worth saying.

IT REPORTS AND, WHERE IT IS CLEARLY SAFE, RESUMES. Nothing here writes code, closes a ticket or
touches a release. The strongest action it takes is to press the button a human would have pressed
on a job that stopped for a reason the factory already knows how to fix — and it says that it did.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from openfactory.techlead import voice

#: A park that nobody answered for this long is not "awaiting a human", it is forgotten — and it is
#: holding the single-line floor the whole time. Deliberately hours, not minutes: a person deserves
#: a chance to answer before an agent starts narrating their inbox back to them.
STUCK_PARK_HOURS = 3

#: A floor that is idle while TO-DO is not empty for this long means the pickup path is broken, not
#: busy. The poller ticks every three minutes, so anything past a few of those is a symptom.
IDLE_MINUTES = 20

#: How long a job may RUN before the rounds treat it as stuck rather than busy.
#:
#: `AGENT_TIMEOUT` is 4h and a job may make several passes (plan, execute, repair, review), so a
#: real one can legitimately be long. Beyond this it is not long, it is wedged — and the cost of
#: being wrong is one message, while the cost of never noticing is the whole floor: a single slot
#: per project means one wedged job stops the factory indefinitely.
LONG_RUNNING_HOURS = 10

#: How long a job may sit at a HUMAN GATE before the rounds mention it.
#:
#: A GATE IS NOT A STALL, and conflating the two produced the worst message this platform has sent
#: (pilot, 2026-08-16). His pull request waited overnight for him to merge it, and the round
#: announced *"#87 rodando há 10h sem parar nem terminar — mais do que qualquer passada real leva …
#: não consegui identificar a causa"* — three false statements about a healthy job, plus two verbs
#: its gate does not accept, addressed to the very person it was waiting for.
#:
#: Eight hours, so a PR opened in the afternoon is not chased the same evening: a person deserves a
#: night before an agent narrates their inbox back to them. That is the same argument as
#: `STUCK_PARK_HOURS`, with more room, because nothing is wrong here — the factory is doing exactly
#: what it was told and the only news is how long it has been true.
GATE_WAIT_HOURS = 8

#: How many times a cause must repeat across DIFFERENT tickets before it stops being bad luck.
RECURRENCE = 3

STUCK, IDLE, RECURRING = "stuck-park", "idle-floor", "recurring-cause"
#: A job waiting on a PERSON at a gate it opened on purpose. Its own kind, because everything about
#: it differs from `STUCK`: the tone, the remedy, the verbs, and whether anything is wrong.
WAITING = "waiting-on-you"


#: THE TICKET IS THE PROVIDER'S OWN STRING, never a number (#69, and C-05's discipline).
#:
#: This whole module used `int`, and the activity that feeds it matched workflow ids with `(\d+)`.
#: On a Jira or Azure DevOps deployment — refs like `CONT-412` — that matched NOTHING, so `parked`
#: was always empty. The blindness was total rather than partial: `_idle_minutes` derives idleness
#: FROM the parked list, so the idle-floor finding could not fire either, and the rounds returned
#: "clean" every hour for ever while the floor was held.
#:
#: `str` is also what keeps the message EXECUTABLE. `report()` below tells a person to reply
#: `resume {ticket}`, and the operator grammar now accepts a Jira ref (C-05, in
#: `contracts/commands.py`) — an int here would hand them a command their own channel
#: could not parse back.
@dataclass
class Parked:
    """One job holding the floor, and what it is waiting on."""

    ticket: str
    hours: float
    note: str = ""
    kind: str = "impediment"       # impediment | rate_limit | self_healing
    #: Automatic attempts already burned before this park, as a NUMBER (#124). It used to live
    #: only inside the note's wording and be recovered by regex, which wired the escalation to a
    #: sentence somebody was about to translate.
    attempts_spent: int = 0
    #: WHEN THE ENGINE ITSELF WILL RESUME IT (#146). Absent for a park that holds until somebody
    #: answers. Its absence was the whole defect: patience could only be measured in hours-since-
    #: parked, so a job twenty-five minutes from resuming on its own was announced to a client as
    #: "waiting on a decision from you" — and the panel, reading the same job, said the opposite.
    wakes_at: str = ""


@dataclass
class AtAGate:
    """One job waiting for a PERSON at a gate the flow opened deliberately.

    NOT A `Parked`, and the separation is the fix. A park is a job that could not continue; a gate
    is a job that will not continue without a decision that was always going to be human — the
    merge (`merge_policy: human`) and the production release (D-12). Both hold the floor and both
    look identical from Temporal, which is exactly how one became the other's message."""

    ticket: str
    hours: float
    #: which gate: `merge` | `prod_approval` | `ci`. It decides the sentence AND the remedy, so it
    #: is a value here rather than something the renderer infers.
    #:
    #: `ci` IS THE ONE THAT ALMOST GOT AWAY. A job with auto-merge armed sits in the very same
    #: merge watch, answering the very same query, while it waits for a BUILD — and the first cut
    #: of this fix would have told the operator *"o PR está pronto e o portão é de vocês"* about a
    #: job nobody can advance. That is the false alarm this file exists to kill, one size smaller.
    gate: str = "merge"
    #: Why this gate cannot hear an answer, when it cannot (`view.gate_cannot_hear`). A pre-patch
    #: replay accepts no answer at all, so offering somebody the buttons would be offering a button
    #: that does nothing — the exact shape `human-merge-gate` was patched to end.
    deaf: str = ""


@dataclass
class Finding:
    kind: str
    detail: str
    ticket: str | None = None
    #: what the tech-lead intends to do about it, in the client's terms
    action: str = ""
    #: whether it can act on this itself
    resumable: bool = False
    #: how far this has gone: hours for a park, minutes for an idle floor, tickets for a recurring
    #: cause. Used to decide whether a repeat is worth saying again (see `worth_saying`), never
    #: shown — the reader gets the sentence, not the counter.
    progress: float = 0.0

    @property
    def key(self) -> str:
        """What makes this the SAME finding across rounds.

        `progress` is deliberately excluded — an hourly park would otherwise get a new key every
        hour and be reported for ever. `resumable` is deliberately included: a park that stops
        being self-healing and starts needing a person has materially changed, and that change is
        the most important thing the round can say."""
        return f"{self.kind}:{self.ticket or '-'}:{int(self.resumable)}"


@dataclass
class FloorState:
    parked: list[Parked] = field(default_factory=list)
    running: int = 0
    queued: list[str] = field(default_factory=list)
    idle_minutes: float = 0.0
    #: `(ticket, hours)` for jobs that are RUNNING and have been for longer than any real pass
    #: takes. A workflow-task failure loop — TMPRL1100 after a deploy, an unregistered activity —
    #: is not parked, so it answers `awaiting_action` falsy and is counted as running. Nothing
    #: else in this file could ever see it: the idle finding requires `running == 0`, and one such
    #: job holds the single-slot floor for ever while looking like work.
    long_running: list[tuple[str, float]] = field(default_factory=list)
    #: Jobs waiting on a PERSON at a gate. They answer `awaiting_action` falsy, exactly like a
    #: wedged job, which is why they used to land in `long_running` and be announced as stuck.
    at_a_gate: list[AtAGate] = field(default_factory=list)
    #: cause → how many DIFFERENT tickets failed that way recently
    recent_causes: dict[str, int] = field(default_factory=dict)


def watch(state: FloorState, *, language: str | None = None,
          now: datetime | None = None) -> list[Finding]:
    """What is worth saying about the floor right now, in the project's own language (#124).

    Every finding here is the factory speaking FIRST, on a schedule nobody asked for — so the
    language is the project's configured one, never a question's. Absent, it answers English.

    A WAIT THE ENGINE OWNS IS NOT WORTH SAYING (#146). This module predates `wakes_at`: until the
    park could say when it woke, patience had to be hours-since-parked, and a cause the classifier
    could not name had to escalate. So a job twenty-five minutes from resuming on its own was
    announced to a client as "waiting on a decision from you… reply `resume`" — asking a human to
    type the very thing the engine was about to do — while the panel, given the same job, said "it
    retries by itself at 22:25". `wait_is_over` is now the single rule both of them ask.
    """
    from openfactory.floor.ladder import wait_is_over
    from openfactory.techlead.classify import classify, remedy_for

    when = now or datetime.now(UTC)
    out: list[Finding] = []

    for job in state.parked:
        if job.hours < STUCK_PARK_HOURS:
            continue
        # STILL ITS OWN BUSINESS, so it is not a person's yet. The park that carries no deadline —
        # an impediment holding until somebody answers — is unaffected: `wait_is_over` says so.
        if not wait_is_over(job.wakes_at or None, job.kind, when):
            continue
        verdict = classify(job.note)
        # THE LANGUAGE THIS ROUND WAS GIVEN (#160). `remedy.say` is rendered below as the whole
        # `action` a channel reads, and this call dropped the argument — so a project configured
        # for one language got its escalation sentence in the deployment default, next to a
        # `detail` on the same line that was localized correctly.
        remedy = remedy_for(verdict, language=language)
        # A park the factory could have fixed, still sitting there, is the #478 shape exactly: it
        # predates the classifier, or the remedy was never attempted. Pressing resume is the button
        # a person would press, and it says so rather than doing it quietly.
        if remedy.action == "retry":
            out.append(Finding(
                kind=STUCK, ticket=job.ticket, resumable=True, progress=job.hours,
                detail=voice.say(voice.FINDING, "park.self-healing", language,
                                 hours=job.hours),
                action=voice.say(voice.FINDING, "park.retrying", language,
                                 detail=voice.say(voice.DETAIL, verdict.detail, language))))
        else:
            # THE ESCALATION CARRIES ITS OWN WAY OUT (C-27). "esperando uma decisão de vocês"
            # was true and useless: a policy park needs the rule said and the scope change named;
            # a project-config park needs "the fix is in YOUR repo, here is the command". The
            # remedy already wrote that sentence — repeating a generic one here threw it away.
            out.append(Finding(
                kind=STUCK, ticket=job.ticket, resumable=False, progress=job.hours,
                detail=voice.say(voice.FINDING, "park.needs-you", language, hours=job.hours),
                action=remedy.say or voice.say(voice.OUTCOME, "still-holding", language)))

    # A GATE, SAID AS A GATE. Nothing is wrong, nobody needs diagnosing, and the two verbs the
    # channel grammar accepts (`resume` / `skip`) do not apply — `contracts/commands.py` excludes
    # merge and release on purpose, so telling somebody to type one would be telling them to type
    # something their own channel cannot parse. The panel is where these are answered.
    for job in state.at_a_gate:
        # A BUILD IS NOT A PERSON. An armed auto-merge waits in the same place and answers the same
        # query; chasing somebody about it after eight hours is the same false alarm wearing a
        # smaller hat, so it gets the wedged-job's patience and its own sentence.
        if job.hours < (LONG_RUNNING_HOURS if job.gate == "ci" else GATE_WAIT_HOURS):
            continue
        if job.gate == "ci":
            out.append(Finding(
                kind=WAITING, ticket=job.ticket, resumable=False, progress=job.hours,
                detail=voice.say(voice.FINDING, "gate.ci.detail", language, hours=job.hours),
                action=voice.say(voice.FINDING, "gate.ci.action", language)))
        elif job.deaf:
            # A GATE THAT CANNOT HEAR MUST NOT BE OFFERED BUTTONS. Telling somebody to press one
            # that is read by no code is the silent forever-wait wearing a working button, which
            # is what `human-merge-gate` was patched to end.
            out.append(Finding(
                kind=WAITING, ticket=job.ticket, resumable=False, progress=job.hours,
                detail=voice.say(voice.FINDING, "gate.deaf.detail", language, hours=job.hours),
                action=job.deaf))
        elif job.gate == "prod_approval":
            out.append(Finding(
                kind=WAITING, ticket=job.ticket, resumable=False, progress=job.hours,
                detail=voice.say(voice.FINDING, "gate.approval.detail", language,
                                 hours=job.hours),
                action=voice.say(voice.FINDING, "gate.approval.action", language)))
        else:
            out.append(Finding(
                kind=WAITING, ticket=job.ticket, resumable=False, progress=job.hours,
                detail=voice.say(voice.FINDING, "gate.merge.detail", language, hours=job.hours),
                action=voice.say(voice.FINDING, "gate.merge.action", language)))

    for ticket, hours in state.long_running:
        # `resumable=False`, AND EVERY VERB REMOVED (sweep B5, 2026-08-16). A wedged job is not
        # parked, so nothing that answers a park can touch it: the `resume` the factory pressed
        # was a signal a failing workflow task never consumes — reported as RESUMED anyway — and
        # the `skip` this message dictated bounces CONFLICT for the same reason. Both exits dead,
        # announced as working, on the one job type that holds the single-slot floor for ever.
        # The only real exit is the engine's own terminate, so that is what is named; the panel's
        # Engine button opens it.
        out.append(Finding(
            kind=STUCK, ticket=ticket, resumable=False, progress=hours,
            detail=voice.say(voice.FINDING, "wedged.detail", language, hours=hours),
            action=voice.say(voice.FINDING, "wedged.action", language, ticket=ticket)))

    if state.running == 0 and state.queued and state.idle_minutes >= IDLE_MINUTES:
        out.append(Finding(
            kind=IDLE, resumable=False, progress=state.idle_minutes,
            detail=voice.say(voice.FINDING, "idle.detail", language,
                             minutes=state.idle_minutes, queued=len(state.queued)),
            action=voice.say(voice.FINDING, "idle.action", language)))

    for cause, times in sorted(state.recent_causes.items(), key=lambda kv: -kv[1]):
        if times >= RECURRENCE:
            out.append(Finding(
                kind=RECURRING, resumable=False, progress=float(times),
                detail=voice.say(voice.FINDING, "recurring.detail", language,
                                 times=times, cause=cause),
                action=voice.say(voice.FINDING, "recurring.action", language)))
    return out


#: How much a finding must WORSEN before it is worth repeating, per kind. Not a mute button: a park
#: nobody answers is still said again, six hours later, with the new number. The point is that an
#: unchanged situation restated on the hour trains everybody to skim past the channel — and the one
#: hour that matters is the one they skim.
#: `WAITING` is the loosest of them on purpose: a gate that is doing its job is news once a shift,
#: not once an hour. Twice a day is enough to keep a forgotten pull request from becoming a
#: forgotten week, and quiet enough that nobody learns to skim the channel.
REPEAT_AFTER = {STUCK: 6.0, IDLE: 60.0, RECURRING: 2.0, WAITING: 12.0}


def worth_saying(findings: list[Finding], said: dict[str, float]) -> tuple[list[Finding], dict]:
    """`(what to say now, what to remember)`.

    Observed in the client's channel: the same park reported identically at 21h and again at 21h38.
    Twice in forty minutes is not vigilance, it is noise, and it is how a channel stops being read.

    A finding is said when it is NEW, when it has materially changed (`key` covers a park that
    stops being self-healing), or when it has got meaningfully worse since it was last mentioned.
    Everything still being watched is carried forward, so a thing that goes away and comes back is
    reported again rather than suppressed by a stale entry."""
    say: list[Finding] = []
    remember: dict[str, float] = {}
    for f in findings:
        last = said.get(f.key)
        threshold = REPEAT_AFTER.get(f.kind, 6.0)
        if last is None or (f.progress - last) >= threshold:
            say.append(f)
            remember[f.key] = f.progress
        else:
            remember[f.key] = last  # still true, still watched, just not worth repeating
    return say, remember


#: What actually happened to a resumable finding, filled in by the caller AFTER it tried.
RESUMED, RESUME_FAILED = "resumed", "resume_failed"


def report(findings: list[Finding], *, agent_name: str = "",
           outcomes: dict[str, str] | None = None, language: str | None = None) -> str:
    """What the channel is told. Empty when there is nothing to say — a watcher that speaks every
    hour to say "tudo bem" is one nobody reads on the hour that matters.

    SAYS WHAT HAPPENED, NOT WHAT IT MEANT TO DO. The channel used to read "vou tentar de novo
    agora" on a retry that had already failed with a TypeError — an announcement of an action that
    never occurred, which is precisely the "confident wrong remedy" ADR-0020 §Consequences warns
    about: once somebody learns the messages are aspirational, they stop trusting all of them.
    `outcomes` is filled in by the caller after acting, so the sentence describes the past."""
    if not findings:
        return ""
    outcomes = outcomes or {}
    sig = f"{agent_name.strip()}: " if agent_name.strip() else ""
    # THE HEADLINE MUST NOT CONTRADICT THE LINES UNDER IT. "tem coisa parada" over a list whose
    # every item is a gate working exactly as configured is the same false alarm one level up: the
    # reader takes the alarm from the first line and never reaches the sentence that says nothing
    # is wrong.
    only_gates = all(f.kind == WAITING for f in findings)
    head = voice.say(voice.HEADLINE, "gates-only" if only_gates else "trouble", language)
    lines = [f"{sig}{head}", ""]
    for f in findings:
        who = f"*#{f.ticket}* " if f.ticket else ""
        # keyed by the finding's identity, not its ticket number: a ticket resumed THIS round can
        # also carry an unacknowledged review finding, and keying by number rewrote the ack
        # reminder into "retomei" — losing the one instruction that line existed to deliver
        did = outcomes.get(f.key)
        if did == RESUMED:
            action = voice.say(voice.OUTCOME, "resumed", language)
        elif did == RESUME_FAILED:
            action = voice.say(voice.OUTCOME, "resume-failed", language, ticket=f.ticket)
        else:
            action = f.action
        lines.append(f"• {who}{f.detail} — {action}")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════════════════════════
# THE HARNESS'S OWN PULSE (C-39)
#
# Everything above watches the FLOOR: jobs, parks, queues — the state machine's view. None of it
# can see inside a running pass. The harness narrates itself the whole time (see
# `adapters/agent/stream.py`), and until now that narration was read once, after the process was
# dead, to fill in a result. So a harness that stops for a need it cannot report — a loop, a wait,
# a tool it will never be granted — is invisible until the 4h wall fires, and the wall's own
# sentence has to GUESS between three causes ("stuck, looping, or the ticket is too big").
#
# WHAT THIS IS AND IS NOT. This is the arithmetic: pulses in, named stalls out, pure, no clock of
# its own, no I/O — so "the harness went quiet" is something a person can check rather than
# something a model asserted, exactly like `watch()` above. It is NOT the ticker: nothing here
# polls, and the latency of the answer is entirely the caller's. Wired at the wall (which is where
# the guessing was), it turns a guess into a measurement; wired to a live reader — the part that
# needs `SandboxAdapter.run(on_output=…)`, which this pass does not build — the same arithmetic,
# unchanged, answers in two minutes instead of four hours.
#
# IT NEVER LETS BLINDNESS READ AS HEALTH. Two of the three signals cannot be computed on three of
# the four harnesses, for stated reasons, and a reading says so in `blind_to` instead of returning
# an empty list of stalls. "No stall found" and "could not look" are different sentences and the
# whole value of this module is that it never confuses them: an unreadable board reading as an
# empty queue is the defect this house repeats, and an empty stream reading as a calm agent is the
# same defect wearing a different hat.
# ═════════════════════════════════════════════════════════════════════════════════════════════════

SILENT, SPINNING, BLOCKED = "harness-silent", "harness-spinning", "harness-blocked"

#: THESE FOUR NUMBERS ARE FIRST CUTS, NOT MEASUREMENTS, and that is why nothing acts on them yet.
#:
#: The card is explicit that a threshold out of a hunch is dangerous in both directions: too short
#: kills a legitimate pass (an agent can sit minutes inside one slow test suite), too long resolves
#: nothing. The resolution is not a better hunch — it is that the FIRST cut only observes. Every
#: consumer today annotates a pass that has ALREADY ended badly, so a wrong number costs one wrong
#: sentence in a diagnosis a human is reading anyway, never an interrupted run and never a
#: half-written worktree. They are parameters on `read_harness` precisely so a deployment that has
#: measured its own runs can pass its own, and so tuning does not mean editing this file.

#: Quiet for this long is the story rather than a pause between two tool calls. Twelve minutes is
#: anchored on the longest gap anybody has a REASON to expect — one full test suite inside a cold
#: container — and it has not been measured against real runs, which is stated rather than implied.
HARNESS_SILENCE_MINUTES = 12.0

#: The same call, with the same argument, this many times in a row. Not "the same tool" — `Bash`
#: twenty times is a normal pass; `Bash: pytest -q` twenty times is a loop.
SAME_CALL_REPEATS = 8

#: Turns in a row in which the model used no tool at all. One or two is ordinary (it is explaining
#: itself, or writing its final answer); six is a model talking to itself while the meter runs.
BARREN_TURNS = 6

#: Attempts at a tool this invocation never granted. Deliberately not one: the read-only planner
#: PROBES `Edit`/`Write` by design and is denied by design — `_parse_stream` already filters those
#: out of the action trace for that reason. Three or more is no longer probing, it is a harness
#: spending its pass on a door that is never going to open.
UNGRANTED_ATTEMPTS = 3


@dataclass(frozen=True)
class Stall:
    """One thing the stream says the harness was doing instead of working."""

    kind: str
    #: factual and measured, in the harness result's own language (English) — it is appended to an
    #: `AgentRunResult.summary`, travels the ordinary failure path into the park note, and is read
    #: back by `classify` there. Deliberately NOT phrased to hit a classifier rule: see
    #: `HarnessReading.note`.
    detail: str


@dataclass(frozen=True)
class HarnessReading:
    """What one harness stream is evidence of — including what it is evidence of NOTHING about."""

    stalls: tuple[Stall, ...] = ()
    #: signals this stream could not answer AT ALL, by name (`"silence"`, `"looping"`,
    #: `"ungranted"`). Non-empty is the honest half of every reading here: a `stalls` of `()` with
    #: `blind_to` of `("silence",)` means "nothing looked wrong in what could be seen, and the
    #: silence question was never asked" — which is a different thing from a healthy pass and must
    #: read differently.
    blind_to: tuple[str, ...] = ()
    #: how many pulses were read. Zero with a live process behind it means the record is missing,
    #: not that the agent was idle.
    events: int = 0
    #: dollars the stream itself reported, when it reported any. None ≠ free.
    spent_usd: float | None = None
    #: seconds since the last pulse, when the stream carries a clock and the caller supplied `now`.
    quiet_seconds: float | None = None

    @property
    def stalled(self) -> bool:
        return bool(self.stalls)

    @property
    def note(self) -> str:
        """One line, always non-empty, saying what the stream showed — including "nothing wrong".

        NEVER EMPTY, on purpose. A reader that says nothing when it found nothing is
        indistinguishable from one that was never called, and this repository has shipped that
        exact ambiguity: a negative guard with no positive twin cannot see a missing value, and
        absence reads as compliance. A clean pass gets a sentence too.

        WRITTEN FOR `classify`, NOT AGAINST IT. This text ends up in the park note the tech-lead's
        classifier reads, and that classifier is deterministic string rules — so a phrase chosen
        carelessly here silently relabels the failure downstream. "not granted" rather than
        "permission denied" is deliberate: the latter matches the ENVIRONMENT rule and would send a
        human to fix infrastructure over a harness that was merely asking for the wrong tool.
        Nothing here matches a TRANSIENT rule either, so an unreadable stream can never degrade
        into an automatic retry — the same asymmetry `classify` states as its own bias.

        THAT PROPERTY IS NOT SUFFICIENT AND CHECKING ONLY THIS SENTENCE MISSES THE BUG. `classify`
        reads the whole park note, of which this is a clause; the sentence it is appended to can
        carry a match all by itself, and did — the 4h wall said the task was "still running", which
        is the transient rule for a CI check that has not finished, so a wall-clock kill quietly
        auto-resumed 15 minutes later. Anything that changes what a caller wraps around this has to
        be re-read through `classify` as the caller assembles it, not as it is written here."""
        parts = [s.detail for s in self.stalls]
        if not parts:
            parts.append(
                f"nothing in the stream looks like a stall ({self.events} events read)"
                if self.events else "no harness events were read")
        if self.spent_usd:
            parts.append(f"the pass had billed ${self.spent_usd:.2f} by then")
        if self.blind_to:
            parts.append(
                "this stream cannot answer " + ", ".join(self.blind_to)
                + " — that is a gap in what the framework can see, not a clean bill of health")
        return "; ".join(parts)


#: Every signal `read_harness` knows how to look for. Named once so "blind to everything" cannot
#: drift out of step with the list of things there are to be blind to.
HARNESS_SIGNALS = ("silence", "looping", "ungranted")


def read_harness(
    pulses: list | None,
    *,
    now: float | None = None,
    grant_known: bool = False,
    silence_minutes: float = HARNESS_SILENCE_MINUTES,
    same_call_repeats: int = SAME_CALL_REPEATS,
    barren_turns: int = BARREN_TURNS,
    ungranted_attempts: int = UNGRANTED_ATTEMPTS,
) -> HarnessReading:
    """What a harness's own stream says about it. Pure: `now` is passed in, never read.

    `pulses` is `adapters.agent.stream.pulses_of(...)`'s answer, and its three shapes are three
    different findings:

        None   no reader for that harness            → blind to everything
        []     read, and it contained nothing        → blind to everything, and SAY the stream was
                                                       empty rather than call the agent idle
        [...]  the events, in order

    The `[]` case is not hypothetical and it is not rare. `ContainerSandbox.run` — the production
    box — converts its timeout WITHOUT passing the partial output through (`timeout_result(command,
    timeout)`, no third argument), so on the box that matters most the four-hour wall arrives with
    the whole transcript already discarded. Reporting that as "the agent did nothing" would be a
    confident lie about the one run nobody can re-observe.
    """
    # The pulse VOCABULARY is defined once, by the layer that produces it, and imported rather than
    # transcribed — two copies of the string "tool" would disagree silently and would disagree
    # everywhere at once. Function-level like this module's `classify` import: the dependency stays
    # on the one call that needs it instead of coupling the tech-lead's package to the adapters at
    # import time.
    from openfactory.adapters.agent.stream import REFUSED, TOOL, TURN

    if not pulses:
        return HarnessReading(blind_to=HARNESS_SIGNALS, events=0)

    stalls: list[Stall] = []
    blind: list[str] = []

    # ── silence ──────────────────────────────────────────────────────────────────────────────────
    # Arithmetic over arrival times, so it needs both a clock in the stream and a `now` to measure
    # against. Neither is guessable: without the clock the gap is unknown, and inventing `now` from
    # the process's own wall time would measure the framework's latency, not the harness's silence.
    stamped = [p.at for p in pulses if p.at is not None]
    quiet: float | None = None
    if now is None or not stamped:
        blind.append("silence")
    else:
        quiet = now - max(stamped)
        if quiet >= silence_minutes * 60:
            stalls.append(Stall(SILENT, (
                f"the harness went quiet — no stream event for the last {quiet / 60:.0f} min")))

    # ── looping ──────────────────────────────────────────────────────────────────────────────────
    # Two shapes of going round in circles, and the second is the one that costs money quietly.
    tools = [p for p in pulses if p.kind == TOOL]
    repeat, call = _longest_repeat(tools)
    if repeat >= same_call_repeats:
        stalls.append(Stall(SPINNING, (
            f"the harness was repeating itself — the same call {repeat} times in a row ({call})")))
    barren = _longest_barren_run(pulses, turn=TURN, tool=TOOL)
    if barren >= barren_turns:
        stalls.append(Stall(SPINNING, (
            f"the harness was turning without working — {barren} turns in a row with no tool "
            f"call")))
    # THE BLINDNESS TEST IS PER QUESTION, NOT PER EVENT KIND, and getting that wrong is how this
    # reading hands out a clean bill of health it never earned.
    #
    # "Was it repeating itself?" is answerable only over calls whose ARGUMENT the stream recorded:
    # `_longest_repeat` refuses to count a pulse with an empty `key`, correctly, because two
    # un-described `bash` calls are not known to be the same one. But refusing to count is not the
    # same as being able to answer — and the earlier check here asked only whether a TOOL pulse
    # existed at all, so twenty shell-outs the stream never described came back as
    # "nothing in the stream looks like a stall (20 events read)" with `blind_to` empty.
    #
    # That is not a corner case: opencode's own captured events carry `state: {"input": {}}`
    # (tests/test_opencode_harness.py), and kimi's reader emits a bare tool name whenever it finds
    # no command — so the harness with the only clock is also the one most likely to produce
    # keyless calls. "Barren turns" is the other half of the same question and needs a TURN pulse.
    # Blind only when NEITHER half had anything to work with; either one answering is enough for
    # the reading to have looked.
    if not any(p.key for p in tools) and not any(p.kind == TURN for p in pulses):
        blind.append("looping")

    # ── reaching for what it was never granted ───────────────────────────────────────────────────
    # Structural, never textual: a REFUSED pulse exists because the tool is outside the allow-list
    # the framework itself passed to the CLI. Counted per TOOL NAME, because the grant is per tool
    # — three `Edit`s on three different files are three attempts at the same closed door.
    #
    # `grant_known` cannot be inferred from the pulses and must not be guessed. No REFUSED pulses
    # means EITHER "it only used tools it was given" OR "nobody told the reader what was given" —
    # two different facts with one appearance, and the second is the ordinary case (three of the
    # four harnesses have no per-tool allow-list to pass). Silently reading absence as good
    # behaviour is the negative-guard failure this codebase names: absence reads as compliance.
    if not grant_known:
        blind.append("ungranted")
    else:
        refusals = Counter(p.name for p in pulses if p.kind == REFUSED and p.name)
        if refusals:
            tool, times = refusals.most_common(1)[0]
            if times >= ungranted_attempts:
                stalls.append(Stall(BLOCKED, (
                    f"the harness kept reaching for {tool}, which this pass never granted it "
                    f"({times} attempts) — it was waiting on an approval nobody was going "
                    f"to give")))

    spent = sum(p.cost_usd for p in pulses if p.cost_usd)
    return HarnessReading(
        stalls=tuple(stalls), blind_to=tuple(blind), events=len(pulses),
        spent_usd=spent or None, quiet_seconds=quiet,
    )


def _longest_repeat(tools: list) -> tuple[int, str]:
    """`(longest run of the identical call, its label)`.

    Runs are counted over the tool calls ALONE, ignoring the turns and prose between them: a model
    that says "let me try that again" between two identical commands is looping harder, not less.
    A pulse whose `key` is empty breaks the run rather than extending it — the stream did not say
    what the call's argument was, so two of them are not known to be the same, and assuming they
    were would report a spin on any run that shells out a few times."""
    best, best_label = 0, ""
    run, key = 0, None
    for pulse in tools:
        if pulse.key and pulse.key == key:
            run += 1
        else:
            run, key = 1, (pulse.key or None)
        if key and run > best:
            best, best_label = run, pulse.label
    return best, best_label


def _longest_barren_run(pulses: list, *, turn: str, tool: str) -> int:
    """The most consecutive turns that produced no tool call. A tool resets the count; anything
    else (prose, usage, errors) is neither evidence of work nor of idleness and is stepped over."""
    best = run = 0
    for pulse in pulses:
        if pulse.kind == turn:
            run += 1
            best = max(best, run)
        elif pulse.kind == tool:
            run = 0
    return best
