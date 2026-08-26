"""What kind of failure this is, and therefore what resolves it (ADR-0020).

Today's factory classifies by SYMPTOM and mostly by accident: a rate-limited token pauses, a
recognised auth string rotates, and everything else — every shape of infrastructure hiccup — becomes
an impediment for a human. On 2026-07-26 that turned GitHub throttling, the most trivially
self-healing failure a system can have, into eighteen hours of held floor and nothing running.

So the taxonomy here is the REMEDY:

    transient   wait and try again          the factory's own
    credential  rotate, then escalate       the factory's, until the pool is exhausted
    environment a human, named              infrastructure is wrong and no retry changes it
    requirement the product role            the ticket is the problem (ADR-0019 §6)
    code        a human engineer            the change is genuinely wrong
    policy      a rule held, on purpose     the org refused a write it is DESIGNED to refuse —
                                            say the rule and the way around it, never "unknown"
    project     the client's own config     their setup:/manifest/validate is broken; the fix is
                                            in THEIR repo, and the message must say exactly where
    unknown     a human, told so plainly    nobody could tell

DETERMINISTIC, ON PURPOSE. Whether a message says GitHub throttled us is a fact about a string, not
a judgement — and a classifier that costs a model call cannot run on the path where the model is the
thing that failed. The agent's diagnosis still writes the human-facing explanation; this only
decides who acts.

UNKNOWN NEVER DEGRADES TOWARD RETRY. Retrying a failure nobody understood is how a token pool burns
on something structurally broken and a loop looks like progress. The bias is always toward
escalation — the same asymmetry as `observed` never becoming `accepted`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from openfactory import namespace
from openfactory.techlead import voice

TRANSIENT, CREDENTIAL, ENVIRONMENT, REQUIREMENT, CODE, UNKNOWN = (
    "transient", "credential", "environment", "requirement", "code", "unknown")
#: C-27: the two classes a human used to resolve BY HAND, both previously "unknown". They are the
#: box/IO boundary's own shapes: a rule the org enforces on purpose, and a client repo whose own
#: commands are broken. Neither is the factory's to retry, and neither needs somebody who knows
#: this codebase — provided the message says what actually happened.
POLICY, PROJECT = "policy", "project"

#: Where the failure happened, because it decides what a retry COSTS. A box that died during setup
#: has burned no agent tokens; one that died mid-execution has, and re-running it pays again.
SETUP, AGENT, UNPLACED = "setup", "agent", "unplaced"

_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    # ---- transient: time alone fixes these -----------------------------------------------------
    (TRANSIENT, re.compile(
        r"rate.?limit(?:ed|ing)?\b|api rate limit|secondary rate limit|abuse detection|"
        r"was submitted too quickly|429\b|too many requests|quota exceeded", re.I), "throttled"),
    (TRANSIENT, re.compile(
        r"connection reset|connection refused|temporary failure in name resolution|"
        r"timed? ?out (?:while )?(?:connecting|reading)|network is unreachable|"
        r"tls handshake timeout|eof occurred|502 bad gateway|503 service unavailable|"
        r"504 gateway", re.I), "network"),
    (TRANSIENT, re.compile(
        r"capacityproviderexception|insufficient capacity|throttlingexception|"
        r"request limit exceeded|resource is not in the state", re.I), "cloud-capacity"),
    # A merge that lost a race, and a check that was still running. Both look like a hard failure
    # in the note and are neither: the branch moved because somebody else merged first, and CI that
    # overran its window has not failed, it is slow. Escalating either asks a person to press the
    # same button the factory could press itself.
    (TRANSIENT, re.compile(
        r"base branch was modified|head branch was modified|"
        r"pull request is not mergeable|merge already in progress|"
        r"didn'?t finish in the watch window|still (?:running|pending|queued)", re.I),
     "race"),

    # ---- credential: this token is bad; another may not be -------------------------------------
    (CREDENTIAL, re.compile(
        r"bad credentials|401 unauthorized|invalid.{0,12}(api key|token)|expired.{0,12}token|"
        r"authentication failed|disabled claude subscription|subscription access|"
        r"use an anthropic api key|please (run )?/?login|credit balance", re.I), "credential"),

    # ---- policy: the org refused a write it is DESIGNED to refuse (C-27) -----------------------
    # BEFORE environment, deliberately: the workflow-file rejection also says "permission", and
    # reading it as infrastructure sends a person to fix a rule that is working exactly as
    # intended. Lived here on 2026-08-01: the push rejection on `.github/workflows/**` is the
    # guardrail (CI/CD is human-only), and the escalation must carry the way AROUND it — take CI
    # out of the change — never a request to grant the bot the permission.
    (POLICY, re.compile(
        r"refusing to allow a github app to (?:create|update) workflow|"
        r"without `?workflows`? permission|"
        r"\.github/workflows.{0,80}(?:rejected|refused|denied)|"
        r"(?:rejected|refused|denied).{0,80}\.github/workflows|"
        r"push declined due to repository rule violations|"
        r"protected branch hook declined", re.I), "policy-rule"),

    # ---- project: the client's own configuration is broken (C-27) ------------------------------
    # `setup:`/`validate:` are the CLIENT's commands and the manifest is the CLIENT's file. These
    # used to land as "não consegui identificar a causa" — false, and the person it escalated to
    # then needed to know this codebase to discover the fix was never here at all.
    (PROJECT, re.compile(
        r"setup: .{0,120}exited \d|no manifest at |manifest: |"
        r"is not valid yaml|command not found|"
        r"validate .{0,40}(?:not found|unknown command)", re.I), "project-config"),

    # ---- environment: no retry changes this ----------------------------------------------------
    (ENVIRONMENT, re.compile(
        r"resource not accessible by integration|must have admin rights|403 forbidden|"
        r"permission denied|not authorized to perform|no such image|manifest unknown|"
        r"pull access denied|no space left on device", re.I), "permission-or-infra"),

    # ---- requirement: the ticket is the problem, and that belongs to the product role -----------
    (REQUIREMENT, re.compile(
        r"ticket too large|proposed no options|decision needed|needs? refinement|"
        r"acceptance criteria", re.I), "the-ticket"),

    # ---- code: the change is wrong -------------------------------------------------------------
    (CODE, re.compile(
        r"gate-suppression|suite is RED|validations then failed|conflicts with .* cannot be "
        r"auto-rebased|validations? failed after \d+ repair", re.I), "the-change"),

    # ---- the shapes a real park actually takes (C-27, measured 2026-08-05) ----------------------
    # Ten notes from this platform's own incident log were run through this classifier and SIX
    # came back `unknown` — which is the honest measure of the gap C-27 names. Each rule below is
    # one of those notes, and the `detail` is what its sentence gets to say.
    (REQUIREMENT, re.compile(
        r"no commits between .* and |nothing to commit|produced no diff", re.I),
     "empty-branch"),
    (ENVIRONMENT, re.compile(
        r"couldn'?t find remote ref|could not find remote ref|does not appear to be a git "
        r"repository|could not read username|authentication failed for", re.I),
     "forge-repo-or-credential"),
    (REQUIREMENT, re.compile(
        r"not merged within \d+d|merge deadline", re.I),
     "undecided-pr"),
    (REQUIREMENT, re.compile(
        r"agent stopped: turn cap|effort budget|cost ceiling", re.I),
     "ticket-too-big"),
)

#: How long to wait before trying a transient failure again, when the failure itself did not say.
#: GitHub's primary limit resets hourly, so a first attempt well inside that is wasted; a second
#: after it is usually enough.
_BACKOFF_SECONDS: tuple[int, ...] = (15 * 60, 45 * 60, 90 * 60)

#: How many times each class may be retried by the factory. Not one number, because the two kinds of
#: retry do not cost the same: waiting out a throttle consumes nothing, while re-running an agent
#: pays for a whole pass. Anything not listed is never retried.
_ATTEMPTS: dict[str, int] = {TRANSIENT: 3, CREDENTIAL: 2}

#: …and the cheap budget shrinks when the retry is expensive. A remedy that has not worked twice is
#: not a remedy; it is a loop with a good story.
_ATTEMPTS_IF_COSTLY: dict[str, int] = {TRANSIENT: 1, CREDENTIAL: 1}


#: LEGACY ONLY: a note whose PROSE says the automatic attempts are spent.
#:
#: The number is data now — `RunResult.attempts_spent`, carried into the park payload and handed
#: to `remedy_for` as `already_spent` (#124). This pattern remains for one reason and it is not
#: belt-and-braces: a job that parked BEFORE that field existed has a note and no number, and its
#: escalation must keep working. It reads notes the platform wrote in English and must not be
#: extended — matching our own emitted sentences is what coupled this module to its own wording
#: and made a translation card into a silent-disarm risk.
#:
#: The pt-BR alternative is deliberately GONE: it matched `remedy_for`'s own output ("já tentei N
#: tentativas e o problema continua"), so the module recognised its own voice as evidence.
_EXHAUSTED_LEGACY = re.compile(
    r"still .{0,24}after \d+ auto-resumes?|after \d+ (?:auto-)?(?:resumes?|retries|attempts)",
    re.I)


@dataclass(frozen=True)
class Verdict:
    cause: str = UNKNOWN
    stage: str = UNPLACED
    #: what matched, in the terms of the taxonomy — for the message a human reads
    detail: str = ""
    #: seconds the failure ITSELF asked us to wait, when it said so
    retry_after: int | None = None
    #: the note this verdict was read FROM. `remedy_for` needs it to see an exhaustion the note
    #: states in prose and no counter carries — kept on the verdict rather than passed separately
    #: so the two can never be given different strings.
    detail_source: str = ""

    @property
    def costly(self) -> bool:
        """Whether retrying pays for an agent pass again. A setup failure has burned nothing."""
        return self.stage == AGENT


#: The two commands every human-facing refusal ends with. ONE string, so an escalation cannot be
#: written without them — the alternative is what the audit found: five different classes, five
#: sentences, and no way for the reader to act on any of them.
# `_WAYS_OUT` moved to `techlead/voice.py::WAYS_OUT` (#124): the two verbs a channel
# reply may carry are prose now, per language, and a guard feeds every rendered
# sentence's backticked verbs to the real parser.


@dataclass(frozen=True)
class Remedy:
    """What to do about it — and, when the answer is a person, why nothing else was tried."""

    action: str                      # "retry" | "rotate" | "escalate" | "product"
    wait_seconds: int = 0
    attempts_left: int = 0
    reason: str = ""
    say: str = ""                    # what to tell the channel while doing it
    #: Whether `say` ALREADY tells the reader which verbs to type, so a caller does not append the
    #: generic line and say them twice.
    #:
    #: A FLAG, BECAUSE THE CALLER WAS MATCHING THE PROSE (#124). `workflow.py` decided this with
    #: `"resume" not in steer and "skip" not in steer` — a substring test against the very sentence
    #: a translation card was about to rewrite. In Portuguese it happened to work; the first
    #: rendering of `say` in any other language would have started printing the verbs twice, or
    #: dropping them entirely, depending on which way the wording fell. What the sentence CONTAINS
    #: is knowledge its author has and nobody downstream should have to infer.
    teaches_the_verbs: bool = False
    notes: list[str] = field(default_factory=list)


_STAGE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (AGENT, re.compile(r"agent stopped|agent errored|ci-repair agent|no result event", re.I)),
    (SETUP, re.compile(r"box failed|could not clone|clone:|checkout|setup", re.I)),
)


def _stage_of(text: str) -> str:
    for stage, pattern in _STAGE_RULES:
        if pattern.search(text or ""):
            return stage
    return UNPLACED


_RETRY_AFTER = re.compile(r"retry[- ]after[:= ]+(\d+)", re.I)


#: The ENGINE died under the job — a worker restart (a deploy), an OOM kill, an infrastructure
#: reap. Measured on the pilot (#159): a rebuild SIGTERMed the worker fifteen seconds into
#: `implementing`, the activity heartbeat timed out, and the park read "I could not identify the
#: cause" — while the tech-lead's own diagnosis, minutes later, identified it precisely and
#: recommended resume. Nothing is wrong with the ticket or the code; one retry is what a dev does.
_ENGINE_RE = re.compile(r"activity task timed out|heartbeat timed? ?out", re.I)


def classify(note: str, *, state: str = "", engine: bool = True) -> Verdict:
    """What this failure is. Pure, and never raises: it reads a string.

    Order matters — the first rule that matches wins, and they are ordered so that a message
    carrying both a credential word and a throttling word is read as throttling. A throttled call
    mentioning "token" is common; a revoked token that also says "rate limit exceeded" is not.

    `engine` gates the engine-death rule (#159), and exists for REPLAY, not for taste: this is
    called from inside a workflow, and a job parked under the old classification replays this
    very call — a different verdict there is a different command sequence, which is TMPRL1100.
    The workflow passes `workflow.patched(...)`; every other caller takes the default."""
    text = note or ""
    stage = _stage_of(text)
    after = _RETRY_AFTER.search(text)
    retry_after = int(after.group(1)) if after else None

    if engine and _ENGINE_RE.search(text):
        return Verdict(cause=TRANSIENT, stage=stage, detail="engine-interrupted",
                       retry_after=retry_after, detail_source=text)

    for cause, pattern, detail in _RULES:
        if pattern.search(text):
            return Verdict(cause=cause, stage=stage, detail=detail, retry_after=retry_after,
                           detail_source=text)

    # A state the pipeline itself chose tells us more than an unmatched string.
    if (state or "").lower() in ("needs_refinement", "blocked"):
        return Verdict(cause=REQUIREMENT, stage=stage, detail="the-ticket",
                       detail_source=text)
    return Verdict(cause=UNKNOWN, stage=stage, detail="", retry_after=retry_after,
                   detail_source=text)


def remedy_for(verdict: Verdict, *, already_tried: int = 0, already_spent: int = 0,
               language: str | None = None) -> Remedy:
    """What the factory should do — and `escalate` whenever that is the honest answer.

    `already_tried` is how many times this SAME ticket has been remedied for this cause, so an
    exhausted budget escalates instead of quietly resetting.

    `already_spent` is what SOMEBODY ELSE already burned before the park — the pause ladder's own
    auto-resumes. It arrives as a number (`RunResult.attempts_spent`) rather than being recovered
    from the note's wording, which is what it was until #124: the platform wrote "still
    rate-limited after 3 auto-resumes" and this module read the count back out with a regex, so
    the escalation depended on nobody rewording either sentence.

    `language` is the PROJECT's — this function only ever speaks first, so it never has a question
    whose language to follow (#124). Absent, it renders English: a caller that does not know the
    project is better served by a sentence it can read than by one in a language it did not
    choose."""
    cause = verdict.cause

    if cause == REQUIREMENT:
        # "MANDEI PARA O PRODUTO" WAS A CLAIM OF AN ACTION NOBODY PERFORMS (pilot, 2026-08-16).
        # `action="product"` is produced here and consumed NOWHERE — every reader of `.action`
        # tests it against `"retry"` — so the ticket went to no module, no queue and no person,
        # while the channel said, in the first person and the past tense, that it had been sent.
        # The pilot read it and answered "não entendi", which is the only honest reaction: he was
        # told a thing had happened and there was nothing to look at.
        #
        # This module already learned this once, on the retry path: *"SAYS WHAT HAPPENED, NOT WHAT
        # IT MEANT TO DO … once somebody learns the messages are aspirational, they stop trusting
        # all of them."* Routing a re-scope to the product role is a real feature and it does not
        # exist yet; until it does, the sentence describes the SITUATION and names who must act.
        return Remedy(action="product",
                      reason=voice.say(voice.REMEDY, "requirement.reason", language),
                      say=voice.say(voice.REMEDY, "requirement.say", language),
                      teaches_the_verbs=True)

    if cause == POLICY:
        # THE RULE IS RIGHT AND THE MESSAGE SAYS SO. The one wrong escalation here is "grant the
        # bot the permission" — the guardrail exists because CI/CD is human-only by design
        # (ADR: never-grant-bot-workflows). The executable way out is to take the refused files
        # out of the change's scope and hand THAT part to a person.
        return Remedy(
            action="escalate",
            reason=voice.say(voice.REMEDY, "policy.reason", language),
            say=voice.say(voice.REMEDY, "policy.say", language), teaches_the_verbs=True,
            # `notes` reaches no channel — nothing consumes `Remedy.notes` (measured #124) — so
            # it stays an English note to whoever reads this code, not a message to translate.
            notes=["the policy is the guardrail working; permission is never the answer"])

    if cause == PROJECT:
        # THE FIX LIVES IN THE CLIENT'S REPO. Saying "unknown" here sent people into THIS
        # codebase to discover the failing command was theirs all along — the exact "requires
        # someone who knows this codebase" failure C-27 exists to end. The note already carries
        # the command and its exit (the setup ground fix), so the sentence points there.
        return Remedy(
            action="escalate",
            reason=voice.say(voice.REMEDY, "project.reason", language),
            say=voice.say(voice.REMEDY, "project.say", language,
                          manifest=namespace.MANIFEST), teaches_the_verbs=True)

    if cause in (CODE, ENVIRONMENT, UNKNOWN):
        why = voice.say(voice.REMEDY, f"why.{cause}", language)
        # EVERY ESCALATION CARRIES A WAY OUT. Measured on this platform's own incident log
        # (C-27, 2026-08-05): these three classes covered six of ten real park notes and their
        # sentence was "Preciso de vocês: <why>." — true, and a dead end. Somebody who does not
        # know this codebase reads it and has no next move, which is precisely the gap C-27
        # exists to close: an escalation without an executable option is a silent wait with a
        # paragraph attached.
        return Remedy(action="escalate", reason=why,
                      say=voice.say(voice.REMEDY, "escalate.say", language, why=why,
                                    ways_out=voice.pick(voice.WAYS_OUT, language)),
                      teaches_the_verbs=True)

    # THE NOTE MAY ALREADY SAY THE RETRIES ARE SPENT. `already_tried` counts what THIS workflow
    # remedied, and a park can arrive carrying somebody else's exhaustion: "still rate-limited
    # after 3 auto-resumes" is the pause ladder giving up, and it matched the throttling rule and
    # came back `retry` — the platform proposing the very thing whose failure the sentence
    # describes. Measured on the real incident log (C-27, 2026-08-05).
    if already_spent > 0 or _EXHAUSTED_LEGACY.search(verdict.detail_source or ""):
        return Remedy(
            action="escalate", attempts_left=0,
            reason=voice.say(voice.REMEDY, "exhausted.reason", language),
            say=voice.say(voice.REMEDY, "exhausted.say", language,
                          ways_out=voice.pick(voice.WAYS_OUT, language)),
            teaches_the_verbs=True)

    cap = (_ATTEMPTS_IF_COSTLY if verdict.costly else _ATTEMPTS).get(cause, 0)
    left = cap - already_tried
    if left <= 0:
        spent = (voice.say(voice.ATTEMPTS, "one", language) if cap == 1
                 else voice.say(voice.ATTEMPTS, "many", language, n=cap))
        return Remedy(
            action="escalate", attempts_left=0,
            reason=voice.say(voice.REMEDY, "spent.reason", language, spent=spent),
            say=voice.say(voice.REMEDY, "spent.say", language, spent=spent))

    if cause == CREDENTIAL:
        # The adapter already laps the pool WITHIN a run, so reaching here means every credential
        # failed once. Waiting is still worth one attempt: a subscription limit resets, and a
        # revoked token that was rotated by an operator in the meantime now works.
        wait = verdict.retry_after or _BACKOFF_SECONDS[0]
        return Remedy(action="retry", wait_seconds=wait, attempts_left=left,
                      reason=voice.say(voice.REMEDY, "credential.reason", language),
                      say=voice.say(voice.REMEDY, "credential.say", language,
                                    minutes=wait // 60))

    wait = verdict.retry_after or _BACKOFF_SECONDS[min(already_tried, len(_BACKOFF_SECONDS) - 1)]
    what = voice.say(voice.DETAIL, verdict.detail, language)
    return Remedy(
        action="retry", wait_seconds=wait, attempts_left=left,
        reason=voice.say(voice.REMEDY, "transient.reason", language, detail=what),
        say=voice.say(voice.REMEDY, "transient.say", language, detail=what,
                      minutes=wait // 60))
