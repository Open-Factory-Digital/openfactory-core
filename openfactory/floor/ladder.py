"""The ladder: six words, nine rungs, one answer — and no IO whatsoever.

PURE, for the same reason `techlead/watch.py` is pure: the claim "this factory will not pick up
your card" is arithmetic somebody can check, not something a screen asserted. The gathering half
lives next door in `gather.py`; this decides.

THE LADDER, first match wins. The rung is carried out on the result so a caller — or a guard — can
assert WHICH one fired rather than only what it said:

    1  the builds disagree        this page and the worker are different code; trust nothing
    2  (the browser's own)        reserved: only a client knows it has gone blind. See __init__.
    3  the engine is not answering
    4  Stopped                    no card will be picked up, and it says why
    5  Needs you                  a human is the blocker
    6  Waiting on a clock         machine-owned, self-clearing, always names the time
    7  Working                    a card is in production
    8  an input is unread         it cannot be established, so nothing is promised
    9  Armed                      nothing running, and the next card WILL be taken
    10 a standing loop is dark    never the headline — see below

`Armed` HAD TO EARN ITS PLACE. Every other word is triggered by bad news, so `Armed` would have
meant "no bad news arrived" — which is exactly what the old `running` meant, and `running` was
wrong on a paused poller. It requires positive evidence: the poller is on, it has ACTUALLY FIRED
inside the window it promises, and the engine still has a next tick queued.

RUNG 10 IS DELIBERATELY BELOW `Armed`. A paused tech-lead round does not stop pickup — cards still
start and still ship — so it must never take the headline, or red stops meaning "no card will be
picked up" and a working factory reads as broken. It is pinned into the demoted list instead, where
the cap cannot drop it.

`None` IS AN ANSWER EVERYWHERE IN HERE. Every input this module reads is optional, and an input
nobody paid to read is reported as unread rather than assumed healthy — which is what lets a caller
choose its own cadence (see `gather.py`) without the result quietly becoming a lie.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

#: The six words, their short form for a badge, and the treatment a surface should give them.
#: `level` is deliberately not a severity number: `clock` is not "less bad" than `warn`, it is a
#: different kind of thing, and a surface that ranked them would paint a self-clearing wait as a
#: small problem.
WORDS: dict[str, tuple[str, str, str]] = {
    "working": ("Working", "Working", "ok"),
    "armed": ("Armed", "Armed", "ok"),
    "clock": ("Waiting on a clock", "Waiting", "clock"),
    "needs": ("Needs you", "Needs you", "warn"),
    "stopped": ("Stopped", "Stopped", "err"),
    "unknown": ("Unknown", "Unknown", "unknown"),
}

#: A tick is LATE after two intervals plus a minute of grace, and DEAD after six. Late is a doubt
#: ("it may have stalled"); dead is a statement ("nothing is being picked up"). Both are expressed
#: in the schedule's OWN interval, so a deployment that polls hourly is not called stalled by a
#: rule written for one that polls every three minutes.
LATE_TICKS, DEAD_TICKS = 2, 6
TICK_GRACE_S, DEAD_FLOOR_S = 60.0, 1800.0

#: Past its own stated wake-up by this much, a self-clearing wait has stopped clearing itself.
OVERDUE_S = 600.0

#: The waits the ENGINE resumes without anybody. They may carry no deadline and still not be a
#: person's problem: a rate-limit park sleeps on a timer, an armed auto-merge clears when CI
#: passes. Everything else that names no wake-up is holding until a human answers.
SELF_CLEARING = frozenset({"rate_limit", "merge_wait"})

#: Demoted causes shown under the headline. Capped, because a list nobody finishes reading is a
#: list nobody reads — but a Stopped or Needs-you row is pinned and never dropped by the cap.
ALSO_CAP = 3


@dataclass
class FloorInputs:
    """Everything the ladder reads. Every field optional; `None` means "not read", never "fine".

    A caller populates what it can afford — see `gather.py`'s three cadences — and the ladder
    reports the rest as unread instead of promising something it could not check.
    """

    jobs: list[dict] | None = None            # runtime.temporal.view.list_jobs rows
    intake: dict | None = None                # runtime.temporal.view.intake
    build: dict | None = None                 # the build-stamp agreement report
    projects: list[dict] | None = None        # name / enabled / box{state,gate,detail}
    inbox: list[dict] | None = None           # the "what needs a human" feed; None = read FAILED
    budget: dict | None = None                # {state: ok|low|unread|not_reported, vendor, …}
    connected: bool | None = None             # could the engine be reached at all
    engine_error: str = ""                    # raw, for a detail line — never a headline
    engine_address: str = ""
    now: datetime | None = None               # injected so a test states a moment


@dataclass
class Cause:
    """One true thing about the floor right now. The winner becomes the headline; the rest are
    demoted rather than dropped — the old header named ONE held project and never mentioned that
    two others were held too."""

    rung: int
    cause: str
    clause: str
    kind: str = "unknown"                     # a key of WORDS
    project: str = ""
    detail: str = ""
    cmd: str = ""
    meta: str = ""
    pinned: bool = False
    actions: list[dict] = field(default_factory=list)

    @property
    def word(self) -> str:
        return WORDS[self.kind][0]

    @property
    def short(self) -> str:
        return WORDS[self.kind][1]

    @property
    def level(self) -> str:
        return WORDS[self.kind][2]


@dataclass
class FloorState:
    """What every surface renders. Nothing here is re-derived downstream — that is the point."""

    scope: str                                 # "" = the deployment, else a project name
    word: str
    short: str
    level: str
    rung: int
    cause: str
    clause: str
    line: str
    detail: str = ""
    cmd: str = ""
    meta: str = ""
    actions: list[dict] = field(default_factory=list)
    also: list[dict] = field(default_factory=list)
    also_more: int = 0
    census: dict | None = None
    census_line: str = ""
    #: DEPLOYMENT SCOPE ONLY: every project's own verdict, so an index of cards costs ONE call
    #: rather than one per card. The census is a count of exactly these, computed in the same pass
    #: — two answers derived from one walk cannot disagree about how many projects are stopped.
    per_project: dict | None = None

    @property
    def ok(self) -> bool:
        return self.level == "ok"

    def as_dict(self) -> dict:
        """The wire shape. Explicit rather than `asdict`, so adding a private field to the
        dataclass cannot silently widen a payload that third parties consume."""
        return {"scope": self.scope, "word": self.word, "short": self.short, "level": self.level,
                "rung": self.rung, "cause": self.cause, "clause": self.clause, "line": self.line,
                "detail": self.detail, "cmd": self.cmd, "meta": self.meta,
                "actions": self.actions, "also": self.also, "also_more": self.also_more,
                "census": self.census, "census_line": self.census_line,
                "per_project": self.per_project, "ok": self.ok}


# ── the evidence that `Armed` is allowed to exist ───────────────────────────────────────────────

def poller_evidence(intake: dict | None) -> dict:
    """Whether the thing that picks work up is actually ticking, not merely switched on.

    "Not paused" is a setting. "Fired two minutes ago on a three-minute schedule" is a fact, and
    only the second lets a screen promise that the next card gets taken (#140).
    """
    if not intake or intake.get("known") is not True:
        return {"verdict": "unread"}
    if intake.get("on") is False:
        return {"verdict": "paused", "note": str(intake.get("note") or "")}
    every = intake.get("every_s")
    if not every:
        return {"verdict": "no-interval"}
    late = every * LATE_TICKS + TICK_GRACE_S
    dead = max(every * DEAD_TICKS, DEAD_FLOOR_S)
    ago, nxt = intake.get("fired_ago_s"), intake.get("next_in_s")
    if ago is None:
        # NEVER FIRED is not the same as STOPPED firing. A schedule created a minute ago has no
        # history and is perfectly healthy; one created an hour ago and still empty means nobody
        # is taking its ticks. Without this every fresh deployment reads as broken for its first
        # three minutes — the first thing a new operator would ever see.
        born = intake.get("created_ago_s")
        if intake.get("num_actions") == 0 and born is not None and born <= late \
                and nxt is not None and nxt > 0:
            return {"verdict": "starting", "next_at": intake.get("next_at")}
        return {"verdict": "never-fired", "born": born}
    if nxt is None or nxt <= 0 or ago > dead:
        return {"verdict": "dead", "ago": ago, "at": intake.get("fired_at")}
    if ago > late:
        return {"verdict": "late", "ago": ago, "every": every, "next_at": intake.get("next_at"),
                "skipped": intake.get("skipped_overlap")}
    return {"verdict": "live", "ago": ago, "every": every, "next_at": intake.get("next_at"),
            "at": intake.get("fired_at")}


def wait_is_over(wakes_at: object, kind: str, now: datetime) -> bool:
    """Is this machine-owned wait a person's problem yet?

    THE ONE DEFINITION, and it is one because two of them disagreed out loud (#146). The panel
    said "it retries by itself at 22:25" about the same job the tech-lead announced in a client's
    Slack as "waiting on a decision from you… reply `resume`" — summoning a human to type what the
    engine was about to do unprompted. Both readers ask this now.

    `wakes_at` is the deadline the WORKFLOW sleeps on (#140). `retry_at` is the vendor's claim,
    which this platform deliberately refuses to obey — so it may be shown and may never decide, or
    a surface and the engine disagree about the same fact.
    """
    wake = _parse(wakes_at)
    if wake is not None:
        return (now - wake).total_seconds() > OVERDUE_S
    # No deadline AT ALL means nothing will move it on its own — a person's problem the moment it
    # is true, not after a timer nobody set.
    #
    # EXCEPT FOR THE WAITS THE ENGINE OWNS, which is the whole point of the distinction. A
    # rate-limit park always carries a timer. An armed auto-merge carries none — it clears when CI
    # passes — and calling that overdue announced "it should have resumed by now and has not"
    # about a build doing exactly what it should. (A merge gate that really is a person's problem
    # is `auto: false`, and rung 5 names it as one from the job's own state; nothing here needs to
    # guess it.)
    return wakes_at is None and kind not in SELF_CLEARING


def need_kind(job: dict) -> str:
    """WHY this job needs a person, from the row itself (#148).

    The engine already says which gate a job is at — `awaiting_your_merge`, `awaiting_prod_approval`
    — and this used to flatten every one of them to `impediment`, whose phrase falls through to the
    park's own `note`. So a pull request waiting for a review was announced as "waiting for CI / the
    merge", which named the wrong blocker: `auto: false` means the CI is not what is holding it, the
    person reading the sentence is.

    The inbox says the same thing in the same words; this is the path taken when the inbox has not
    been read, and it must not be the poorer answer.
    """
    act = job.get("action") or {}
    state = str(job.get("state") or "")
    # THE ORDER IS THE INBOX'S, because two orders is two answers (#164). `/api/inbox` built the
    # same vocabulary in its own branches and put `decision` first, `wedged` fifth and carried a
    # sixth word — `rate_limit` — that this function did not have at all. Both are read as "why
    # does this need a person", so a rate-limited park was `impediment` on one surface and
    # `rate_limit` on the other, about the same job at the same instant.
    if act.get("decision"):
        return "decision"
    if state == "awaiting_your_merge" or (act.get("kind") == "merge_wait" and not act.get("auto")
                                         and not act.get("working")):
        return "merge"
    if state == "awaiting_prod_approval":
        return "approval"
    if state == "paused" or act.get("kind") == "rate_limit":
        return "rate_limit"
    if job.get("wedged"):
        return "wedged"
    return "impediment"


def _is_asked_of_somebody(act: dict) -> bool:
    """Whether an action payload is a QUESTION — for a person or for a clock — rather than the
    engine describing what it is doing right now (#151).

    Only one payload is the second kind so far: a merge wait whose repair pass is in flight. The
    operator already answered it; the machine is acting on that answer; the payload survives only
    to name the pull request being rewritten. Written as a question about the payload rather than
    a list of states, because the next such payload should land here rather than in three rungs.
    """
    if not act:
        return False
    return not (act.get("kind") == "merge_wait" and act.get("working"))


def _machine_still_owns(job: dict, now: datetime) -> bool:
    """Whether the engine will move this job on its own, so nobody need be summoned yet.

    ASKED OF `wait_is_over`, not decided here: two definitions of this question are what #146
    already cost — the panel saying "it retries by itself at 22:25" about the job the tech-lead
    was announcing in a client's Slack as "waiting on a decision from you".

    A wedged job is NEVER machine-owned however it is parked: wedged means nothing can move it,
    which is the opposite claim.
    """
    if job.get("wedged") is True:
        return False
    act = job.get("action") or {}
    kind = str(act.get("kind") or "")
    if kind not in SELF_CLEARING:
        return False
    # AN UNARMED MERGE GATE IS A PERSON'S, TIMER OR NOT — the same distinction #166 made explicit
    # on the tracker port. `merge_wait` is in `SELF_CLEARING` because an ARMED one clears when CI
    # passes; with `auto: false` the reader is the blocker and nothing will move it. `wait_is_over`
    # says so in its own words and cannot act on it, because it is handed a kind and a deadline
    # and never the row. Measured: without this line a human merge gate fell out of `needs`
    # entirely and the floor answered rung 8, "could not read whether anybody is needed".
    if kind == "merge_wait" and not act.get("auto"):
        return False
    return not wait_is_over(act.get("wakes_at"), kind, now)


def is_overdue(job: dict, now: datetime) -> bool:
    """The same question, asked about a job row."""
    act = job.get("action") or {}
    return wait_is_over(act.get("wakes_at"), str(act.get("kind") or ""), now)


def _parse(when: object) -> datetime | None:
    if not isinstance(when, str) or not when:
        return None
    try:
        got = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except ValueError:
        return None
    return got if got.tzinfo else got.replace(tzinfo=UTC)


def _dur(seconds: float | None) -> str:
    if seconds is None:
        return ""
    s = max(0, round(seconds))
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{round(s / 60)} min"
    return f"{s / 3600:.1f}h"


def _at(iso: object) -> str:
    got = _parse(iso)
    return got.strftime("%H:%M") if got else ""


NEED_PHRASE = {
    "decision": "the agent is asking which way to go",
    "merge": "a pull request is waiting on your review",
    "approval": "a release is waiting on your production approval",
    "wedged": "it has been running for hours and nothing left can advance it",
    "overdue": "it should have resumed by now and has not",
    "rate_limit": "it is parked and past its own retry time",
}


# ── the ladder ──────────────────────────────────────────────────────────────────────────────────

def causes(inputs: FloorInputs, project: str = "") -> list[Cause]:
    """Every cause that is true right now, for this scope — unsorted.

    THE LADDER IS THE SORT, not a chain of early returns. That is what lets the demoted causes
    survive to be shown under the headline instead of being silently dropped.
    """
    now = inputs.now or datetime.now(UTC)
    out: list[Cause] = []
    jobs = [j for j in (inputs.jobs or []) if not project or j.get("project") == project]
    rows = [p for p in (inputs.projects or []) if not project or p.get("name") == project]
    intake = inputs.intake

    # ── 1. the builds disagree ──────────────────────────────────────────────────────────────────
    build = inputs.build or {}
    if build.get("agree") is False:
        other = next(iter(build.get("others") or {}), "another half")
        out.append(Cause(1, "builds_disagree",
                         f"this page was served by build {build.get('stamp') or '?'}; the {other} "
                         f"is running a different one, so nothing here can be trusted",
                         kind="unknown",
                         cmd="docker compose --env-file .env.compose up -d --build"))

    # ── 3. the engine is not answering ──────────────────────────────────────────────────────────
    if inputs.connected is False:
        if not inputs.engine_address:
            out.append(Cause(3, "engine_down",
                             "this deployment has no durable engine installed — no card will ever "
                             "be picked up", kind="stopped"))
        else:
            # The engine failing to answer is not proof the worker stopped: it may be running jobs
            # perfectly. Unknown, and the raw exception stays OFF the headline because it can carry
            # addresses and stack fragments.
            out.append(Cause(3, "engine_down",
                             "the engine did not answer, so this cannot say what the floor is "
                             "doing", kind="unknown", detail=inputs.engine_error))

    # ── 4. Stopped — nothing will be picked up ──────────────────────────────────────────────────
    ev = poller_evidence(intake)
    if ev["verdict"] == "paused":
        note = ev.get("note") or ""
        out.append(Cause(4, "poller_paused",
                         "the poller is paused — no card in TO-DO will be picked up anywhere"
                         + (f" ({note})" if note else ""), kind="stopped",
                         detail="there is no button for this yet — resume the schedule on the "
                                "engine"))
    elif ev["verdict"] == "dead":
        out.append(Cause(4, "poller_stalled",
                         f"the poller last fired {_dur(ev.get('ago'))} ago and has no next tick — "
                         f"nothing is being picked up", kind="stopped"))
    elif ev["verdict"] == "never-fired":
        out.append(Cause(4, "poller_stalled",
                         "the poller has never fired — no worker is taking its ticks",
                         kind="stopped"))
    for p in rows:
        name = str(p.get("name") or "")
        box = p.get("box") or {}
        if p.get("enabled") is False:
            out.append(Cause(4, "pickup_off",
                             f"pickup for {name} is off — a card in TO-DO will not be taken, "
                             f"whatever the engine is doing", kind="stopped", project=name,
                             pinned=True,
                             actions=[{"key": "enable", "label": "Turn pickup on",
                                       "tone": "primary", "project": name}]))
        elif box.get("gate"):
            out.append(Cause(4, "box_gate",
                             f"{name} will be refused — {box.get('detail') or box.get('gate')}",
                             kind="stopped", project=name, pinned=True,
                             cmd=f"openfactory box prove {name}"))

    # ── 5. Needs you ────────────────────────────────────────────────────────────────────────────
    # `inbox is None` means the READ failed, not that nothing needs anybody — so the engine's own
    # `attention` flag is the fallback, and the failed read is reported at rung 8 rather than
    # rendered as a clean floor. A failed read shown as "nothing needs you" is the most dangerous
    # sentence this module could produce.
    if inputs.inbox is not None:
        needs = [i for i in inputs.inbox if not project or i.get("project") == project]
    else:
        # A MACHINE-OWNED WAIT THAT IS NOT OVER IS NOT A PERSON'S PROBLEM (#164), and this line
        # answered that question without asking `wait_is_over` — the one definition written for
        # exactly it. A fresh rate-limit park carries `attention: True` from the engine (it IS
        # holding the floor) and lands here as rung 5, "Needs you", about a job the engine
        # resumes by itself in half an hour. Measured: a park waking in 30 minutes announced as
        # a person's.
        #
        # `attention` STAYS THE ENGINE'S WORD for "this job is not progressing"; what this adds is
        # WHOSE problem that is, which is the distinction rung 5 exists to make and the inbox
        # below has always made.
        needs = [{"project": j.get("project"), "issue": j.get("issue"),
                  "kind": need_kind(j),
                  "note": (j.get("action") or {}).get("note") or ""}
                 for j in jobs
                 if (j.get("attention") is True or j.get("wedged") is True)
                 and not _machine_still_owns(j, now)]
    seen = {(str(i.get("project")), str(i.get("issue"))) for i in needs}
    needs += [{"project": j.get("project"), "issue": j.get("issue"), "kind": "overdue"}
              for j in jobs if j.get("action") and is_overdue(j, now)
              and (str(j.get("project")), str(j.get("issue"))) not in seen]
    if needs:
        first = needs[0]
        clause = (f"{len(needs)} answers are waiting — the oldest is {first.get('project')} "
                  f"#{first.get('issue')}") if len(needs) > 1 else (
            f"{first.get('project')} #{first.get('issue')} — "
            f"{NEED_PHRASE.get(str(first.get('kind')), str(first.get('note') or '')) or
               'it stopped and will not restart by itself'}")
        out.append(Cause(5, "needs_you", clause, kind="needs",
                         project=str(first.get("project") or ""), pinned=True,
                         actions=[{"key": "inbox",
                                   "label": "Answer them" if len(needs) > 1 else "Answer it",
                                   "tone": "primary"}]))

    # ── 6. waiting on a clock ───────────────────────────────────────────────────────────────────
    budget = inputs.budget or {}
    if budget.get("state") == "low":
        until = budget.get("reset_at")
        # THE VENDOR IS A VALUE THE ADAPTER PUT ON THE BUDGET, never a word this sentence owns:
        # this rung used to say "the GitHub budget" for every deployment, on a floor that names
        # no vendor anywhere else.
        vendor = str(budget.get("vendor") or budget.get("kind") or "API")
        out.append(Cause(6, "budget",
                         f"the {vendor} budget is spent ({budget.get('remaining')} left) — the "
                         f"poller skips its projects" + (f" until {until}" if until else ""),
                         kind="clock",
                         detail="work already running continues; the quota resets by itself and "
                                "nothing here needs a person"))
    for j in jobs:
        act = j.get("action") or {}
        who = f"{j.get('project')} #{j.get('issue')}"
        if act.get("kind") == "rate_limit" and not is_overdue(j, now):
            when = _at(act.get("wakes_at"))
            out.append(Cause(6, "rate_park",
                             f"{who} is parked on a usage limit"
                             + (f" — it retries by itself at {when}" if when
                                else " — it retries by itself"),
                             kind="clock", project=str(j.get("project") or "")))
        elif act.get("kind") == "merge_wait" and act.get("auto"):
            out.append(Cause(6, "merge_auto", f"{who} is merging itself — waiting on CI",
                             kind="clock", project=str(j.get("project") or "")))

    # ── 7. Working ──────────────────────────────────────────────────────────────────────────────
    # AN ACTION PAYLOAD IS NOT ALWAYS A QUESTION (#151). Its presence used to disqualify a job from
    # Working without exception, because every payload meant "parked on somebody". A merge wait
    # with a repair pass in flight breaks that: the payload names the PR an agent is rewriting and
    # nobody is being asked anything. Excluded from Working, it matched no other rung either — so
    # the floor answered "Armed — nothing is running" over a job at full throttle, which is the
    # same lie as the one this card is fixing, pointing the other way.
    running = [j for j in jobs
               if j.get("status") == "running" and not j.get("wedged")
               and not _is_asked_of_somebody(j.get("action") or {})]
    if running:
        if len(running) > 1:
            names = ", ".join(f"{j.get('project')} #{j.get('issue')}" for j in running[:2])
            out.append(Cause(7, "running", f"{len(running)} cards in production — {names}",
                             kind="working"))
        else:
            one = running[0]
            title = f" · {one.get('title')}" if one.get("title") else ""
            out.append(Cause(7, "running", f"{one.get('project')} #{one.get('issue')}{title}",
                             kind="working", project=str(one.get("project") or "")))

    # ── 8. an input is unread ───────────────────────────────────────────────────────────────────
    # A LATE POLLER IS ITS OWN SENTENCE. It is the one rung-8 cause where the fact IS known and is
    # merely bad; folding it into "I could not read…" produced "I could not read why the poller
    # last fired 30 min ago", which reads as confusion about our own instrument.
    if ev["verdict"] == "late":
        skipped = ev.get("skipped")
        out.append(Cause(8, "poller_late",
                         f"the poller last fired {_dur(ev.get('ago'))} ago and it ticks every "
                         f"{_dur(ev.get('every'))} — it may have stalled, so the next card is not "
                         f"promised", kind="unknown",
                         detail=(f"{skipped} ticks were skipped because the previous scan was "
                                 f"still running") if skipped else
                                (f"the engine still lists the next tick at {_at(ev.get('next_at'))}"
                                 if ev.get("next_at") else "")))
    unread: list[str] = []
    if ev["verdict"] == "unread":
        unread.append("whether the poller schedule is running")
    if ev["verdict"] == "no-interval":
        unread.append("how often the poller ticks, so it cannot say whether it is late")
    if inputs.projects is None:
        unread.append("which projects exist and whether their boxes are proven")
    # THE INBOX IS NOT A SEPARATE FACT — it is a RENDERING of the same job rows, with executable
    # options attached. So a missing inbox only leaves us blind when the jobs are missing too;
    # with them in hand the engine's own `attention` flag answers the same question, and calling
    # that "unread" would downgrade a floor we can actually see.
    #
    # Caught live rather than by the suite (2026-08-19): `gather` never fetched the inbox, so this
    # fired on every healthy deployment and the floor reported Unknown, permanently, to everybody.
    if inputs.inbox is None and inputs.jobs is None and inputs.connected is not False:
        unread.append("what needs a human — neither the inbox nor the job list could be read")
    for p in rows:
        name = str(p.get("name") or "")
        if p.get("enabled") is None:
            unread.append(f"whether {name} takes cards")
        if (p.get("box") or {}).get("state") == "unknown":
            unread.append(f"whether {name}'s box would be refused")
    if unread and ev["verdict"] != "starting":
        out.append(Cause(8, "unread", f"nothing is running, and it could not read {unread[0]}",
                         kind="unknown", detail=" · ".join(unread)))

    # ── 10. a standing loop is dark ─────────────────────────────────────────────────────────────
    for sid, w in sorted(((intake or {}).get("watchers") or {}).items()):
        if project and not sid.endswith(f"-{project}"):
            continue
        who = sid.removeprefix("openfactory-")
        if w.get("on") is False:
            out.append(Cause(10, "watcher_dark",
                             f"the {who} round is paused — cards still start, nobody reviews "
                             f"between runs" + (f" ({w['note']})" if w.get("note") else ""),
                             kind="needs", project=project, pinned=True))
        elif w.get("known") is False:
            out.append(Cause(10, "watcher_dark",
                             f"it could not read whether the {who} round is running",
                             kind="unknown", project=project, pinned=True))

    # ── 9. Armed ────────────────────────────────────────────────────────────────────────────────
    if not out or all(c.rung >= 8 for c in out):
        if ev["verdict"] == "starting":
            out.append(Cause(9, "armed",
                             "nothing is running — the poller has just been created and its first "
                             "tick is queued", kind="armed",
                             meta=f"first scan at {_at(ev.get('next_at'))}" if ev.get("next_at")
                                  else ""))
        else:
            every = f" · it ticks every {_dur(ev.get('every'))}" if ev.get("every") else ""
            where = f" in {project}'s TO-DO" if project else " in TO-DO"
            out.append(Cause(9, "armed",
                             f"nothing is running — the next card{where} will be picked up",
                             kind="armed",
                             # NEVER "the last scan completed": `fired_ago_s` proves a tick FIRED,
                             # and a dead worker leaves the schedule firing into an empty queue.
                             meta=(f"the poller last fired {_dur(ev.get('ago'))} ago{every}"
                                   if ev.get("at") else "")))
    return out


#: A cause that is a CONSEQUENCE of the winner is not a second problem. Without this a blind engine
#: reports its own blindness three times, once per fact it could not read — and buries the one an
#: operator can act on.
DOWNSTREAM: dict[str, tuple[str, ...]] = {
    "engine_down": ("unread", "armed", "needs_you", "running", "rate_park", "poller_stalled",
                    "poller_paused", "poller_late"),
    "poller_paused": ("poller_stalled", "poller_late", "armed", "unread"),
    "poller_late": ("armed",),
    "builds_disagree": (),      # it casts doubt on everything; it explains nothing
}


def state(inputs: FloorInputs, project: str = "") -> FloorState:
    """The floor's one answer, for one scope."""
    found = sorted(causes(inputs, project), key=lambda c: (c.rung, c.project))
    if not found:  # defensive: `causes` always appends Armed, so this is unreachable by design
        found = [Cause(9, "armed", "nothing is running", kind="armed")]
    win = found[0]
    rest = [c for c in found[1:] if c.cause not in DOWNSTREAM.get(win.cause, ())]
    pinned = [c for c in rest if c.pinned]
    plain = [c for c in rest if not c.pinned]
    also = pinned + plain[:ALSO_CAP]
    # NO CENSUS FROM A LIST NOBODY COULD READ. `census_of` over `None` returns six zeroes and a
    # total of 0 — which reads as 'this deployment has no projects', a claim, on exactly the
    # failure where the honest answer is that we do not know.
    per_project, census = (None, None)
    if not project and inputs.projects is not None:
        per_project, census = _walk(inputs)
    return FloorState(
        scope=project, word=win.word, short=win.short, level=win.level, rung=win.rung,
        cause=win.cause, clause=win.clause, line=f"{win.word} — {win.clause}",
        detail=win.detail, cmd=win.cmd, meta=win.meta, actions=win.actions,
        also=[{"level": c.level, "word": c.word, "clause": c.clause, "cause": c.cause,
               "project": c.project, "cmd": c.cmd, "pinned": c.pinned} for c in also],
        also_more=max(0, len(rest) - len(also)),
        census=census, census_line=census_line(census) if census else "",
        per_project=per_project,
    )


def _walk(inputs: FloorInputs) -> tuple[dict, dict]:
    """Every project's own verdict, and the census counted from exactly those.

    ONE PASS, TWO ANSWERS, deliberately. Counting the buckets separately from deciding the words
    would be two computations over the same facts — the defect this whole module exists to end,
    reappearing inside it. It also makes an index of cards cost one call: the panel used to run
    the ladder per card in the browser.
    """
    per: dict[str, dict] = {}
    census = dict.fromkeys(("working", "needs", "clock", "armed", "stopped", "unknown"), 0)
    census["total"] = 0
    for p in inputs.projects or []:
        name = str(p.get("name") or "")
        one = state(inputs, name)
        per[name] = {"word": one.word, "short": one.short, "level": one.level,
                     "cause": one.cause, "clause": one.clause, "cmd": one.cmd}
        bucket = {"ok": "armed" if one.cause == "armed" else "working", "clock": "clock",
                  "warn": "needs", "err": "stopped", "unknown": "unknown"}[one.level]
        census[bucket] += 1
        census["total"] += 1
    return per, census


def census_of(inputs: FloorInputs) -> dict:
    """The census alone, for a caller that wants only the counts."""
    return _walk(inputs)[1]


def census_line(census: dict) -> str:
    """Non-zero buckets only. Six zeroes on a healthy deployment is the six-pills mistake wearing
    a new name."""
    label = {"working": "working", "needs": "needs you", "clock": "waiting", "armed": "armed",
             "stopped": "stopped", "unknown": "unknown"}
    order = ("working", "needs", "clock", "armed", "stopped", "unknown")
    return " ".join(f"· {census[k]} {label[k]}" for k in order if census.get(k))
