"""PromotionRunner — carry a merged change along the promotion chain (ADR-0001 D-12, #109).

The chain is the CLIENT's when declared (`promote: [dev, qa, prod]` — every stage before the last
observed in order, the last human-gated whatever it is called) and the two fixed names otherwise.

The framework *triggers* transitions (merge/tag) and *observes*; the project's
pipeline executes the deploy with its own secrets. Prod is human-gated by default.
Reactions on a red environment: report + notify + stop (a red prod triggers a
rollback flag). This is the post-merge half of the lifecycle; `run` produces the PR.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from openfactory.adapters.environment.base import EnvironmentObserver
from openfactory.adapters.forge.base import ForgeAdapter
from openfactory.adapters.notify.base import Level, NullNotifier
from openfactory.adapters.notify.base import Notifier as NotifierT
from openfactory.adapters.tracker.base import TrackerAdapter
from openfactory.contracts import Environment, JobState, Manifest, RunResult
from openfactory.observability import EventKind, EventSink, JobEvent, NullEventSink, now_iso
from openfactory.techlead import voice as tl_voice

log = logging.getLogger("openfactory.promotion")

#: What observing one stage can come back with (#501). THREE, because "not green" was two facts
#: wearing one value: a stage that is RED, and a stage whose deploy has not finished yet. The
#: second used to pass as green, and the first is not what it is.
Reach = Literal["reached", "red", "not reached"]
#: WHY a stage was not reached (#518) — two causes of one outcome, both held, said apart:
#: `pending`, its deploy still running when the window closed (somebody watches the pipeline);
#: `unread`, no deploy of this ref read there — `unknown`, or the `none` CI's "none" — and no
#: `health_url` to probe instead (somebody fixes the stage's declaration). "" when it was reached,
#: or red.
Why = Literal["", "pending", "unread"]

#: How long ONE WALK waits for deploys still `pending` before the stage counts as not reached
#: (#501). Shared by every stage of the walk rather than given to each, because the walk runs in
#: one box launched with a 30-minute timeout (`activities._run_promotion`, under the activity's
#: 40): a per-stage window on a three-stage chain would outlive the box that waits.
REACH_WINDOW_SECONDS = 20 * 60
#: Between two reads of a pending deploy — the deploy watch's own pace (`_DEPLOY_POLL`): a deploy
#: is minutes, and every read is a request against the credential every running job shares.
REACH_POLL_SECONDS = 60


@dataclass
class PromotionRunner:
    tracker: TrackerAdapter
    forge: ForgeAdapter
    observer: EnvironmentObserver
    manifest: Manifest
    notifier: NotifierT = field(default_factory=NullNotifier)
    events: EventSink = field(default_factory=NullEventSink)
    #: Which language this project's UNPROMPTED messages are written in (#160). EVERY sentence
    #: this runner produces is one: nobody asks for a promotion narration, and it lands on the
    #: ticket — the one surface a project has whether or not a channel is configured. Empty means
    #: English, which is the answer a deployment that never configured anything would want.
    #:
    #: A FIELD RATHER THAN A REGISTRY READ: the orchestrator layer knows nothing about registries
    #: (it is handed adapters, a manifest and a path), and giving it one to hold would be the
    #: dependency this package is shaped to avoid. Whoever builds the runner has the row.
    language: str = ""
    #: The pending-deploy wait (#501), and the two seams a test drives it through without waiting.
    reach_window: float = REACH_WINDOW_SECONDS
    reach_poll: float = REACH_POLL_SECONDS
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)

    def _say(self, key: str, **params: object) -> str:
        """One catalogue entry, in this project's language."""
        return tl_voice.say(tl_voice.NARRATION, key, self.language, **params)

    def promote(self, ticket_ref: str) -> RunResult:
        """Observe every pre-production stage of the chain, in order; if all green, STOP and
        await a human's approval for the last. Production is never automatic — it needs a
        deliberate, authenticated human action (D-12), whatever the client named it.

        A PROJECT CAN BE BORN WITHOUT PRODUCTION, and that is an ordinary state, not a
        misconfiguration: something under construction has nowhere to release to yet. The product
        owner named it on 2026-07-31 about a production client, whose manifest declares no
        environments at all.

        Until this, such a project got three claims that were each false. `_verify` read "nothing
        declared" as "verified", so the ticket said "✅ staging verified" about a check that never
        ran. It then parked at AWAITING_PROD_APPROVAL waiting for permission to reach a production
        that does not exist, held the gate for the whole approval window, and finally went ON_HOLD
        with "prod approval window elapsed" — a stall with no way out, which is the one failure this
        platform exists to make impossible. And the staging bridge would have asked the client to
        approve putting it "no ar" for users there are none of.

        So each step is now taken only when there is something for it to be about. Nothing is lost
        by finishing here: the work merged, and the client is still asked whether it is right — by
        the delivery/acceptance loop, which runs off the board and not off an environment.
        """
        ref = self.manifest.base_branch
        # The chain the CLIENT declared (`promote: [dev, qa, prod]` — #109), or the two fixed
        # names the tail always walked. Every stage before production is observed IN ORDER, each
        # by its own name; production is human-gated whatever the client calls it, which is what
        # lets a regulated manifest agree with the change-management document it answers to.
        stages, production = self.manifest.promotion_chain()
        deadline = self.clock() + self.reach_window
        self._state(ticket_ref, JobState.MERGED)
        for name in stages:
            # ENTERED ONLY WHEN THERE IS SOMETHING TO OBSERVE. The state means "observe
            # smoke/health"; passing through it with nothing declared records an observation that
            # never happened, in the log a person reads to find out what the platform checked.
            # One JobState for every pre-production stage — the enum cannot hold a client's
            # naming — so the stage's own NAME rides on the events and the ticket instead.
            self._state(ticket_ref, JobState.STAGING_VERIFYING)
            self._emit(ticket_ref, "note", f"verifying {name}")
            seen, why = self._verify(ref, self.manifest.environments.get(name),
                                     deadline=deadline)
            if seen != "reached":
                return self._failed_env(ticket_ref, name, seen, why)

        verified = ", ".join(stages)
        # WHERE A PERSON LOOKS, AND WHETHER ANYBODY IS ASKED TO (#122). Both come from the
        # manifest, so a chain of `dev, qa, producao` names a different place for each stage
        # instead of the single deployment-wide `staging_url` that could express one.
        stage = self.manifest.stage_a_person_confirms()
        look_at = self.manifest.where_a_person_looks(stage) if stage else ""

        if production is None:
            # No production to promote to. Say so rather than parking on a gate nobody can open —
            # an approval that cannot be given is not a human in the loop, it is a queue slot held
            # until a deadline expires.
            #
            # BUT IT IS STILL AN ASK, and that is this card's behavioural change. The old sentence
            # ended "nothing is waiting on an approval", which is true about the pipeline and was
            # read by the one shop that most needs a person to look as "nobody has to do
            # anything". A flow that ENDS at staging has no gate, so the confirmation is the whole
            # of its quality bar; it was the only flow the platform never asked.
            self._notify(ticket_ref, self._ask_to_confirm(stage, look_at, gated=False),
                         "action_required" if stage else "info")
            self._say_on_ticket(
                ticket_ref,
                self._say("promo.merged")
                + (self._say("promo.verified", stages=verified) if stages else "")
                + self._say("promo.no-production")
                + self._where_line(stage, look_at))
            self._state(ticket_ref, JobState.DONE)
            return RunResult(ticket_id=ticket_ref, state=JobState.DONE,
                             look_stage=stage, look_at=look_at)

        self._notify(
            ticket_ref,
            (self._say("promo.awaiting-head", stages=verified) if stages
             else self._say("promo.awaiting-head-none"))
            + self._say("promo.awaiting", production=production)
            + (f". {self._ask_to_confirm(stage, look_at, gated=True)}" if stage else ""),
            "action_required",
        )
        self._say_on_ticket(
            ticket_ref,
            (self._say("promo.merged")
             + (self._say("promo.verified", stages=verified) if stages else "")) + " "
            + self._say("promo.awaiting-ticket", production=production)
            + self._where_line(stage, look_at))
        self._state(ticket_ref, JobState.AWAITING_PROD_APPROVAL)
        return RunResult(ticket_id=ticket_ref, state=JobState.AWAITING_PROD_APPROVAL,
                         look_stage=stage, look_at=look_at)

    def _ask_to_confirm(self, stage: str, look_at: str, *, gated: bool) -> str:
        """The one line that asks somebody to check the change is right.

        AN EMPTY ADDRESS NEVER IMPLIES ONE. Telling a person to "go and take a look" without
        saying where is the failure this card names in its own acceptance criteria — they open the
        message, find no link, and conclude the platform is broken rather than that their project
        never declared where to look. So the sentence changes shape: with an address it sends them
        somewhere, without one it says the stage is green and that nothing declares where to see
        it, and names the field that would."""
        if not stage:
            return self._say("promo.confirm.no-stage")
        if look_at:
            return self._say("promo.confirm.at", stage=stage, where=look_at)
        return self._say("promo.confirm.no-url", stage=stage,
                         tail="" if gated else self._say("promo.confirm.only-check"))

    def _where_line(self, stage: str, look_at: str) -> str:
        """What the TICKET says about where to look — the channel-free half, so a deployment with
        no product channel still gets the address in the one place every project has."""
        if not stage:
            return ""
        if look_at:
            return self._say("promo.where.confirm", stage=stage, where=look_at)
        return self._say("promo.where.no-url", stage=stage)

    def release_prod(
        self, ticket_ref: str, *, version: str, approver: str, comment: str = ""
    ) -> RunResult:
        """Tag → prod, ON an authenticated human approval (from the panel). Records who
        approved, the version, and any comment, then observes prod."""
        ref = self.manifest.base_branch
        tag = f"{self.manifest.prod_tag_prefix}{version}"
        extra = f": {comment}" if comment else ""
        self._say_on_ticket(ticket_ref,
                            self._say("promo.release-approved", approver=approver, tag=tag,
                                      extra=extra))
        self._emit(ticket_ref, "note", f"prod approved by {approver} ({tag})")
        self._state(ticket_ref, JobState.PROD_RELEASING)
        self.forge.create_tag(tag=tag, ref=ref)
        self._state(ticket_ref, JobState.PROD_VERIFYING)
        # production is the chain's LAST stage, whatever the client calls it (#109)
        _, production = self.manifest.promotion_chain()
        seen, why = self._verify(ref, self.manifest.environments.get(production or "prod"),
                                 deadline=self.clock() + self.reach_window)
        if seen == "reached":
            self._notify(ticket_ref, self._say("promo.live"), "info")
            self._state(ticket_ref, JobState.DONE)
            return RunResult(ticket_id=ticket_ref, state=JobState.DONE)
        if seen == "not reached":
            # NOT LIVE, AND NOT RED EITHER (#501). A production deploy still running when the
            # window closed is held with that said — rolling back a release nobody has seen fail
            # would be acting on a guess, in the one environment where a guess costs the most.
            # The same for a release nothing could read and nothing probed (#518).
            return self._failed_env(ticket_ref, production or "prod", seen, why)
        # red prod → rollback (a defined, safe pipeline action) + report
        self._state(ticket_ref, JobState.ROLLING_BACK)
        self._notify(ticket_ref, self._say("promo.verify-failed"), "error")
        self._say_on_ticket(ticket_ref, self._say("promo.rollback-ticket"))
        self._state(ticket_ref, JobState.ON_HOLD, reason="prod rollback")
        return RunResult(ticket_id=ticket_ref, state=JobState.ON_HOLD, note="prod rollback")

    # -- internals --

    def _verify(self, ref: str, env: Environment | None, *,
                deadline: float) -> tuple[Reach, Why]:
        """Whether the declared environment was reached, and why not when it was not.
        "reached" FOR AN UNDECLARED ONE, and the callers are what make that honest.

        "Nothing declared" and "checked and green" are the same value here and must never be the
        same SENTENCE. This answering yes is how "✅ staging verified" was posted about a project
        with no environments at all — the value was right and the claim built on it was not. Every
        caller now asks whether the environment exists before saying anything about it. A stage
        of the chain that declares neither `deploy_ref` nor `health_url` never gets here: the
        manifest refuses it when it loads (#501).

        A PENDING DEPLOY IS NOT A REACHED STAGE (#501). Only `failure` used to stop the walk, so a
        deploy still running — which is what a deploy is, read right after its merge — passed as
        green, and the delivery was announced about a version that was not there yet. It is
        waited for now, the way the deploy watch waits for its run: read again every
        `reach_poll` seconds until it settles or `deadline` passes. Still pending at the deadline
        is "not reached", and the caller holds the stage saying exactly that.

        A STAGE IS REACHED ONLY ON AN OBSERVATION (#518): a deploy of this ref that finished
        green, or a `health_url` that answered healthy — and when both are declared, both. Two
        answers used to pass without either: `unknown` (nothing recorded for this ref in that
        environment) and `none` (what the `ci: none` observer answers for every ref, because it
        reads no deploy at all) were handed to `health_url` when there was one and counted as
        reached when there was not, and the delivery waiting on the stage was announced with
        nothing seen. Both still go to `health_url` when there is one, which must answer healthy;
        with none, the stage is "not reached" and held like a deploy still pending, in a
        sentence of its own ("unread"). On a `ci: none` project the
        manifest is refused when it loads instead (`Manifest._a_stage_no_ci_reads_is_probed`),
        so the hold is what is left for a `deploy_ref` that names an environment nothing has
        recorded."""
        if env is None:
            return "reached", ""  # nothing declared to verify
        status = ""
        if env.deploy_ref:
            status = self.observer.deploy_status(env=env.deploy_ref, ref=ref)
            while status == "pending" and self.clock() < deadline:
                self.sleep(max(0.0, min(self.reach_poll, deadline - self.clock())))
                status = self.observer.deploy_status(env=env.deploy_ref, ref=ref)
            if status == "failure":
                return "red", ""
            if status == "pending":
                log.warning("OPENFACTORY_STAGE_NOT_REACHED deploy_ref=%s ref=%s — its deploy was "
                            "still pending when the %ds window closed; the stage is held, not "
                            "passed", env.deploy_ref, ref, int(self.reach_window))
                return "not reached", "pending"
        if env.health_url:
            return ("reached" if self.observer.health(url=env.health_url) else "red"), ""
        if status == "success":
            return "reached", ""
        # NOTHING WAS OBSERVED (#518): `unknown`, or the `none` CI's "none" — an answer, and not
        # a deploy anybody saw — with no `health_url` to look instead.
        log.warning("OPENFACTORY_STAGE_NOT_REACHED deploy_ref=%s ref=%s status=%s — no deploy of "
                    "this ref was read there and the stage declares no health_url to probe; the "
                    "stage is held, not passed", env.deploy_ref, ref, status or "unread")
        return "not reached", "unread"

    def _failed_env(self, ticket_ref: str, env: str, seen: Reach = "red",
                    why: Why = "") -> RunResult:
        """Hold the walk at `env`, saying which it was: red, not reached in time, or not reached
        because nothing could be read there (#518)."""
        if seen == "not reached" and why == "unread":
            self._notify(ticket_ref, self._say("promo.env-unread", env=env), "error")
            self._say_on_ticket(ticket_ref, self._say("promo.env-unread-ticket", env=env))
        elif seen == "not reached":
            window = max(1, round(self.reach_window / 60))
            self._notify(ticket_ref, self._say("promo.env-not-reached", env=env, minutes=window),
                         "error")
            self._say_on_ticket(ticket_ref, self._say("promo.env-not-reached-ticket", env=env,
                                                      minutes=window))
        else:
            self._notify(ticket_ref, self._say("promo.env-failed", env=env), "error")
            self._say_on_ticket(ticket_ref, self._say("promo.env-failed-ticket", env=env))
        self._state(ticket_ref, JobState.ON_HOLD, reason=f"{env} {seen}")
        return RunResult(ticket_id=ticket_ref, state=JobState.ON_HOLD, note=f"{env} {seen}")

    def _state(self, ticket_ref: str, state: JobState, reason: str | None = None) -> None:
        self.tracker.set_state(ticket_ref, state, reason=reason)
        self._emit(ticket_ref, "state", state.value)

    def _say_on_ticket(self, ticket_ref: str, body: str) -> None:
        """Record on the ticket what this runner just did — and never let the record undo the act.

        Same rule as the job machine's helper of this name, and it arrived the same way: the tracker
        learned to raise on a refused write (correctly — a write that did not happen must not look
        like one that did), and every bare `comment` on this path became able to abort what it was
        describing. Here that is worse than usual: `promote` comments AFTER staging is verified and
        BEFORE parking at AWAITING_PROD_APPROVAL, so a refused comment would have skipped the park —
        and the release would sit waiting for an approval signal the workflow never armed.

        The act stands; the loss of the record is an ERROR with a greppable marker, because an
        audit trail that quietly stopped being written looks exactly like a quiet month.
        """
        try:
            self.tracker.comment(ticket_ref, body)
        except Exception as exc:  # noqa: BLE001 — the act stands; only the telling failed
            log.error("OPENFACTORY_TICKET_COMMENT_LOST ticket=%s (%s) — the tracker refused the "
                      "comment; "
                      "what it described still happened, and the ticket does not say so: %s",
                      ticket_ref, str(exc)[:160], body[:160])

    def _notify(self, ticket_ref: str, message: str, level: Level) -> None:
        self.notifier.notify(message=f"{ticket_ref}: {message}", level=level)
        self._emit(ticket_ref, "warning" if level in ("error", "warning") else "note", message)

    def _emit(self, ticket_ref: str, kind: EventKind, message: str) -> None:
        self.events.emit(
            JobEvent(
                ts=now_iso(), job_id=ticket_ref, ticket_id=ticket_ref, kind=kind, message=message
            )
        )
