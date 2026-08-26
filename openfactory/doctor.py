"""`openfactory doctor` — say which prerequisite is missing, before the first ticket (C-15).

This platform's headline invariant is *never a silent hang: every stall either self-heals or asks a
human with executable options*. It covers the running factory and stops at its door. Before the
first ticket there is no invariant at all — a board column named wrongly, an App without Projects
permission, a harness not on PATH: each produces the same symptom, which is nothing happening.

So the bar is not "reports a problem". It is that **each distinct cause produces a distinct,
actionable line**, and that a healthy setup says so out loud. Onboarding is not tedious because it
has many steps; it is tedious when it fails without saying why.

AND ONE CHECK IS NOT ABOUT THE MACHINE AT ALL. `.openfactory/project.yaml` has thirty-one fields
and no
required ones, so an empty file loads — and this tool answered ".sdlc/project.yaml loads", which a
client reads as "the manifest is fine". It is the failure-looks-like-an-answer shape in its purest
form: the file that decides what the platform will verify, reported as healthy while declaring
nothing to verify. `_manifest` now says what the file DECLARED, and `_floor` asks
`policy/conformance.py::floor_reason` — the same question the job path asks in
`orchestrator/machine.py:325`, at the moment it is about to spend money — before the first ticket
instead of after the first invoice (#102).

ONE CHECK IS NOT A PREREQUISITE BUT A CONTRADICTION, and it is the one an enterprise hits:
`merge_policy: auto` against a repository whose branch protection requires a human review. Both
settings are individually valid, and together they mean the factory can never merge. Today that is
discovered by a timeout — the merge loop reads `blocked`, treats it as a pending check, waits, and
parks. Nobody is told the two policies disagree.

WHY PROBES ARE INJECTED. Every environmental fact arrives as a callable, so each branch is
reachable in a test without Docker, a network, or a GitHub App. A doctor that could only be
exercised on a healthy machine would be a doctor nobody could prove reports illness — which is the
same defect it exists to prevent.
"""

from __future__ import annotations

import logging
import os
import pathlib
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from openfactory import namespace

log = logging.getLogger("openfactory.doctor")

#: The LAST-RESORT name for the column the poller picks work up from, used only when the board
#: cannot say. Its exact name is what a client's existing board most often gets wrong, and the
#: failure is total silence — which is why the board is asked first (`BoardAdapter.pickup_column`)
#: and this constant is no longer the question.
PICKUP_COLUMN = "TO-DO"


class BoardUnreadable(RuntimeError):
    """The project HAS a board and this process could not read it.

    A third state, and it needs its own channel because two cannot carry three meanings. The probe
    returns `None` for *no board configured* — a legitimate setup the port documents — and a list
    when it read one. Collapsing "could not read" into either is how the first run of this tool
    inside the compose worker reported a permissions failure as **"no board configured — tickets
    are named directly"**, cheerfully, as a PASS. The client is told their setup is fine, and the
    poller then picks up nothing for ever.

    That is precisely the confusion `adapters/board/base.py` warns about in capitals, committed by
    the person who had just re-read the warning in order to write `column_names()`. The lesson is
    not "be careful": it is that the shape of the return value has to make the mistake impossible.

    Carries the board's coordinates as its message, because the remedy is almost always a
    credential and the first question is *which* board could not be read.

    AND IT CARRIES ITS OWN REMEDY, because only the raiser knows the vendor. `diagnose` runs on
    injected probes and cannot know one — so the remedy it wrote named `OPENFACTORY_BOT_TOKEN` and
    `OPENFACTORY_GH_APP_*` to every reader, and the coordinates were formatted from `board_owner`
    and
    `board_number`, which are GitHub option names that Jira and Azure DevOps do not have. Run
    against a real Azure project it read: *"the board ?/? is configured but could not be read →
    check that OPENFACTORY_BOT_TOKEN … is set"*. Both halves were false, and the second sends
    the one
    person who does not yet know the system to set a variable that cannot help them."""

    #: What to do about it, in the vendor's own vocabulary. Empty falls back to the generic line.
    remedy: str = ""

    def __init__(self, message: str, *, remedy: str = "") -> None:
        super().__init__(message)
        self.remedy = remedy


@dataclass
class Finding:
    check: str
    ok: bool
    message: str
    #: What to do about it. Required whenever `ok` is False — a finding with no remedy is a symptom
    #: delivered to the one person who does not yet know the system.
    remedy: str = ""
    #: The SEQUENCE's next step when this finding is what stands in the way, for the closing
    #: verdict to quote. It lives here rather than in the caller because only the check knows
    #: what it measured: the CLI's own version had to hedge ("if onboard already proposed it,
    #: merging that PR is the step") about a fact this module had just looked up — a conditional
    #: written one screen away from the answer (pilot, 2026-08-14).
    next_step: str = ""
    #: Something TRUE about a healthy check that the verdict must still say out loud. A pass is
    #: not always the end of the sentence: "no product module configured" is a legitimate setup
    #: AND the client-facing half being off, and an operator reading "OK — can run a ticket"
    #: cannot see the second half (the operator, 2026-08-14). Only ever on `ok` findings; a
    #: failing one has a remedy instead.
    note: str = ""
    #: The check this one is DOWNSTREAM of: it went red because that one did, and it clears when
    #: that one clears.
    #:
    #: A FIELD BECAUSE A CALLER DECIDES ON IT. `cli.py` distinguishes "NOT ready because something
    #: is broken" from "NOT ready because a later step has not run yet", and it did so from a
    #: hand-written list of check NAMES — so the first manifest-derived check added after it
    #: (`post_merge`, 2026-08-16) dropped out of the list and turned an operator's §2 report into
    #: "fix the FAIL lines above", the exact sentence that branch exists to prevent. Two checks
    #: also said "I am waiting on the manifest" in two different sentences, so matching on the
    #: remedy text would have missed one of them. The dependency is a fact about the finding; it
    #: belongs here, once.
    awaiting: str = ""
    #: The check whose STEP has not been taken yet, when this red line describes a guarantee that
    #: nothing needs until it is.
    #:
    #: NOT `awaiting`, AND THE DIFFERENCE IS WHY BOTH EXIST. `awaiting` means DOWNSTREAM: the line
    #: went red *because* that check did, and it clears when that one clears. This one went red
    #: for its own reason and will still be red after the step is taken — what the step changes is
    #: whether anybody is exposed by it. Collapsing the two into one field would put two facts in
    #: one value, and the caller reading it cannot tell "fix that other line and this goes away"
    #: from "this is true and nothing needs it yet".
    #:
    #: `api_budget` is the case that named it (2026-08-24). An unreadable quota is a missing
    #: safety net around the POLLER's board scan — and `activities.py::scan_todo` returns before
    #: it reads the board while the box gate holds pickup. At ONBOARDING §2, where nothing has
    #: been proven by construction, there is no scan for the net to be missing from, and telling
    #: a stranger to "fix the FAIL lines above" about it is the exact confusion the EXPECTED
    #: verdict was built to end.
    not_yet: str = ""


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.findings)


@dataclass
class Probes:
    """Everything `diagnose` needs to know about the world, as callables it can be handed."""

    #: `(ok, detail)`, and the detail is not decoration. A stopped daemon and a MISSING `docker`
    #: CLI both make `docker info` fail, and the remedies are opposite: one is "start Docker", the
    #: other is "your image has no docker client". The compose worker hit the second and was told
    #: the first, while Docker was serving the container printing the message. `forge_reachable`
    #: below already carried a detail for the same reason; this probe was the odd one out.
    docker_running: Callable[[], tuple[bool, str]]
    harness_on_path: Callable[[str], bool]
    manifest: Callable[[], object]
    forge_reachable: Callable[[], tuple[bool, str]]
    #: The board's column names, or None when the project has no board — which is not an error:
    #: `openfactory run` names the ticket itself, and reporting its absence would send somebody to
    #: fix a
    #: setup that is already correct.
    board_columns: Callable[[], list[str] | None]
    #: What THIS board calls the column the poller picks up from. A PROBE and not a constant,
    #: because only the provider knows: the module-level `PICKUP_COLUMN` was checked against every
    #: board, so an Azure project whose columns are exactly right was told to "rename a column to
    #: exactly 'TO-DO'" — the platform demanding the pre-C-14 world back from a client who had
    #: already done everything correctly.
    pickup_column: Callable[[], str]
    requires_review: Callable[[], bool]
    #: Whether a floor violation is a refusal. Constant True since `OPENFACTORY_ENFORCE_FLOOR` was
    #: removed — the floor is not a deployment's preference, and a switch that was off by default
    #: meant the guarantee did not exist wherever nobody knew its name.
    #:
    #: STILL A PROBE, and deliberately. It changes what the floor finding MEANS rather than merely
    #: decorating it — unmet-and-enforced is "every job holds", unmet-and-not is "jobs run with
    #: that gate missing" — so a test has to be able to show doctor saying either, and a hardcoded
    #: `True` at the call site could only ever demonstrate one of them.
    floor_enforced: Callable[[], bool]
    harness_kind: Callable[[], str]
    #: The product module's verdict (`resolve_product_link`). Reached only by the product role
    #: until now, so a misconfigured context repository surfaced hours later as an agent going
    #: quiet — the silent stall this platform exists to prevent (C-17).
    product_link: Callable[[], object]
    #: `(present, detail)` for the AGENT's credential — the one ONBOARDING §1 calls the only
    #: prerequisite you cannot postpone, and the one check doctor never made: a fresh install
    #: with zero credentials read "OK — can run a ticket" and failed at the first paid job.
    #: None = an older Probes; the check is skipped rather than invented.
    agent_credential: Callable[[], tuple[bool, str]] | None = None
    #: What the project's OWN CI runs, as `{key: (command, "path:line")}` — or None when this
    #: deployment cannot look (no checkout, no reader). #176.
    #:
    #: THREE ANSWERS, and the middle one is the point, as with `disabled_ci_paths` one port over:
    #: `None` = "I could not read the pipeline", `{}` = "I read it and it declares nothing". A
    #: check that collapses them tells a client with no CI at all that their CI matches, which is
    #: the reassurance this finding exists to stop giving.
    ci_checks: Callable[[], dict[str, tuple[str, str]] | None] | None = None
    #: Why pickup is held, or None — `box_prove.gate_reason`, THE question the poller asks
    #: before it takes a card. Doctor asked eight questions and not this one, so a deployment
    #: whose box proof had failed (or expired, or never run) was told "OK — can run a ticket"
    #: while every card sat in TO-DO. Found on the pilot the moment the board went green and
    #: the only thing left between it and a ticket was a proof taken before the image shipped
    #: `uv` (2026-08-14). Asking the SAME function the gate asks is the point: two answers to
    #: one question is how the two drift.
    #: None = an older Probes; the check is skipped rather than invented.
    box_gate: Callable[[], str | None] | None = None
    #: The port's answer for the API budget this project's reads spend: a
    #: `tracker.base.Budget`, the `NOT_REPORTED` sentinel (the vendor has none), or — when the
    #: vendor has one and the read FAILED — the `BudgetUnreadable` the port raised, carrying the
    #: vendor's own reason (`None` for a failure with no reason to give). Three answers on
    #: purpose, and the third one says why it is the third; the tuple-or-None
    #: shape before it rendered a failed probe as ok. The factory can STOP TAKING CARDS for an
    #: hour to protect a quota — and the operator met that wall from the other side, through an
    #: unrelated command, having been told nothing (2026-08-14). What a diagnostic owes here is
    #: the number and whose it is.
    api_budget: Callable[[], object] | None = None
    #: The URL of an OPEN proposal carrying this project's manifest, or `""`. Asked of the forge
    #: only when the manifest is missing, so a healthy project pays nothing.
    #:
    #: WHY IT IS A PROBE AND NOT A SENTENCE. The remedy used to read "IF `openfactory onboard`
    #: already opened a pull request, this is that PR waiting to be merged" — a conditional
    #: about a fact the platform can simply LOOK UP, printed to somebody who cannot tell whether
    #: it applies to them and is given no link if it does. The pilot operator merged only
    #: because I told him to in chat, and said the thing that matters (2026-08-14): *"não pode
    #: be true only because you are telling me here; in a normal installation nobody will have your
    #: assistência."*
    open_proposal: Callable[[], str] | None = None
    #: Whether any FOREIGN repository of this project has a proof recorded
    #: (`box_prove.foreign_proofs_recorded`) — the POLLER's second question, and the half that
    #: decides whether a held gate really means nothing is scanning. `scan_todo` holds the
    #: default repo's cards on its gate and STILL READS THE BOARD when another repo of the same
    #: project is proven, because a proven foreign repo must not wait on the default's
    #: paperwork. Without it, "pickup is held, so nothing is spending that quota" would be a
    #: sentence that is false on exactly the deployments C-18 exists for.
    #: None = an older Probes; unknown reads as "it may well be scanning", never as safe.
    foreign_proofs: Callable[[], bool] | None = None


#: The remedy every check inherits when it could not run because the manifest is not written yet.
#:
#: A CONSTANT BECAUSE A CALLER READS IT. `cli.py` decides whether "NOT ready" means "broken" or
#: "not written yet", and it used to decide from a hand-written list of check NAMES — so the first
#: manifest-derived check added after it (`post_merge`, 2026-08-16) silently flipped an operator's
#: §2 report from *"EXPECTED at this point"* to *"fix the FAIL lines above"*, which is precisely the
#: confusion that sentence exists to end. Attribution belongs to the finding, not to a list
#: somebody has to remember to update.
WAITING_ON_THE_MANIFEST = ("this is the manifest finding above, seen from another check — fix that "
                           "one and this clears with it")


def _guarded(check: str, fn: Callable[[], Finding]) -> Finding:
    """Run one check without letting it become the ninth broken thing.

    Doctor is what somebody runs when nothing works. A traceback from the diagnostic tells them
    nothing about their setup and quite a lot about ours."""
    try:
        return fn()
    except FileNotFoundError:
        # THE MANIFEST IS THE ONE CAUSE THAT MAKES SEVERAL CHECKS FAIL AT ONCE, and each of them
        # repeating the whole thing with "re-run the underlying tool by hand" sends somebody to
        # debug a tool when the answer is one line above (pilot, 2026-08-14: three FAILs, one
        # cause, one useful remedy between them).
        #
        # AND THE EXCEPTION'S TEXT IS DROPPED ON PURPOSE. It names the commands that WRITE a
        # manifest, which contradicts `_manifest` outright when a proposal is already open and
        # that finding is saying "merge it, nothing needs proposing again". One cause, one
        # instruction, and the instruction belongs to the check that measured it.
        return Finding(check, False, f"could not check {check}: the manifest has not loaded",
                       WAITING_ON_THE_MANIFEST, awaiting="manifest")
    except Exception as exc:  # noqa: BLE001 — a failed probe is a finding, not a crash
        return Finding(check, False, f"could not check {check}: {exc}",
                       "re-run with the underlying tool by hand to see the raw error")


def diagnose(probes: Probes) -> Report:
    """Every check, every time. Stopping at the first failure turns one session into six.

    ONE CHECK READS ANOTHER'S ANSWER, and it is handed over rather than asked again. `api_budget`
    means something different depending on whether pickup is held (see `Finding.not_yet`), and
    the only honest source for that is the gate's own finding: `p.box_gate()` resolves a checkout
    and asks docker for a digest — the poller bounds it at sixty seconds — so asking it a second
    time would double the cost of the diagnostic AND put a second answer beside a question that
    already has one, which is the shape `_box_proof` was written to avoid.
    """
    findings = [
        _guarded("docker", lambda: _docker(probes)),
        _guarded("harness", lambda: _harness(probes)),
    ]
    if probes.agent_credential:
        findings.append(_guarded("agent_credential", lambda: _agent_cred(probes)))
    findings.append(_guarded("manifest", lambda: _manifest(probes)))
    findings.append(_guarded("quality_floor", lambda: _floor(probes)))
    if probes.ci_checks:
        findings.append(_guarded("ci_declared", lambda: _ci_declared(probes)))
    gate = _guarded("box_proof", lambda: _box_proof(probes)) if probes.box_gate else None
    if gate is not None:
        findings.append(gate)
    if probes.api_budget:
        findings.append(_guarded(
            "api_budget", lambda: _api_budget(probes, pickup_held=_pickup_is_held(probes, gate))))
    findings.extend([
        _guarded("forge_access", lambda: _forge(probes)),
        _guarded("board_columns", lambda: _board(probes)),
        _guarded("merge_policy", lambda: _merge_policy(probes)),
        _guarded("post_merge", lambda: _post_merge(probes)),
        _guarded("product_link", lambda: _product(probes)),
    ])
    return Report(findings)


def _pickup_is_held(p: Probes, gate: Finding | None) -> bool:
    """Is this project's board going unread right now — the POLLER's own condition, both halves.

    `activities.py::scan_todo` returns before it reads the board when the default repo's gate
    holds AND no foreign repo of the project has a proof recorded; with one recorded, the board
    IS read (C-18: a proven foreign repo does not wait on the default's paperwork). Only both
    halves together mean "nothing is spending this quota".

    THE GATE ARRIVES AS ITS FINDING, not as a second call: `box_gate` resolves a checkout and
    asks docker for a digest, and a diagnostic that asked twice would pay twice for a question it
    has already had answered. UNKNOWN IS NEVER SAFE: a probe set that cannot answer either half
    (an older `Probes`) gets `False`, so the check speaks as if the poller were scanning — which
    it may well be.
    """
    if gate is None or gate.ok or p.foreign_proofs is None:
        return False
    return not p.foreign_proofs()


def _api_budget(p: Probes, *, pickup_held: bool = False) -> Finding:
    """How much API budget is left, and — the half that changes what an operator does — WHOSE.

    On a personal-account GitHub deployment the board can only be read with the operator's own
    classic PAT (an App token cannot drive a user-owned Projects v2), so every poll spends THEIR
    hourly quota while the factory's App budget sits untouched. Nothing said so until the pilot
    ran out of it (2026-08-14).

    AND AN UNREADABLE ONE IS NOT ALWAYS A FINDING ABOUT THIS PROJECT. What it describes is a
    safety net around the poller's board scan, and `activities.py::scan_todo` returns before it
    reads the board while the box gate holds pickup. So on a project that has not been released
    to pick up work — which is EVERY project at ONBOARDING §2, by construction — an unreadable
    budget is a fact about a step the operator has not reached, and a stranger following the
    document was being told "NOT ready — fix the FAIL lines above" with a line he cannot act on
    at that point (2026-08-24). It is still printed, in its own words, because it becomes a real
    finding the moment §5 releases pickup; what changes is the verdict it drives (`not_yet`)."""
    from openfactory.adapters.tracker.base import NOT_REPORTED, Budget, BudgetUnreadable

    budget = p.api_budget() if p.api_budget else None
    # THREE ANSWERS, THREE FINDINGS. The probe used to answer `None` for BOTH a vendor with no
    # budget and a read that failed, and this rendered both as ok — a broken `gh` on a GitHub
    # deployment passed the check with the sentence "the vendor does not report an API budget".
    # A declared `NOT_REPORTED` is a fact and passes as itself; an unreadable one is a safety net
    # that is missing, and says what broke.
    if budget == NOT_REPORTED:
        return Finding("api_budget", True, "no budget on this vendor — it does not report one, "
                                           "so pickup is never paused for a quota here")
    if not isinstance(budget, Budget):
        # WHAT BROKE, WHEN THE PORT SAID IT. `BudgetUnreadable` carries the vendor's own reason
        # ("could not read the GitHub rate limit (gh: command not found)"), which `floor/reading`
        # keeps as `error=` and this check used to drop on the floor — leaving the one person who
        # does not yet know the system with "could not be read" and a remedy asking him to re-run
        # by hand the call the platform had just made.
        why = f" ({budget})" if isinstance(budget, BudgetUnreadable) else ""
        if pickup_held:
            return Finding(
                "api_budget", False,
                f"the API budget could not be read{why} — and nothing is spending it yet: "
                "pickup is held by the box proof above, and the poller does not read the board "
                "until that clears",
                "nothing here is yours to fix at this point in the sequence: prove the box "
                "(ONBOARDING §5), which is what releases pickup, and run this command again. If "
                "this line is still here afterwards, the credential the poller reads the board "
                "with cannot reach the vendor's quota endpoint — and by then it matters",
                not_yet="box_proof")
        return Finding(
            "api_budget", False,
            f"the API budget could not be read{why} — the poller keeps scanning without that "
            "safety net, so an exhausted quota will surface as failed reads instead of a pause",
            "run the tracker's own CLI/API call with this project's credential to see what it "
            "answers (a missing CLI, a refused token, no network); the floor and the panel show "
            "the same read as `unread`")
    when = (time.strftime("%H:%M", time.localtime(budget.reset_epoch)) if budget.reset_epoch
            else "soon")
    share = f"{budget.remaining}/{budget.limit}" if budget.limit else str(budget.remaining)
    resource = budget.resource or "API"
    # THE ADAPTER'S OWN FLOOR, the same number the poller pauses on. This used to compute
    # `max(200, limit // 10)` here — a second threshold beside the poller's — so the doctor could
    # say "nearly gone" at a level the poller was still scanning through.
    if budget.low:
        return Finding(
            "api_budget", False,
            f"the {resource} budget these reads spend is nearly gone ({share}, refills at "
            f"{when}) — pickup pauses on its own until it does",
            "nothing is broken and nothing needs restarting; if it empties every hour the reads "
            "cost more than they should — a personal-account board is read with YOUR token "
            "(docs/setup/github.md §6), so that quota is yours, not the App's")
    return Finding("api_budget", True,
                   f"{resource} budget {share} (refills at {when})")


def _box_proof(p: Probes) -> Finding:
    """The gate's own verdict, rendered as a finding — not a second opinion about it.

    `gate_reason` already answers in the operator's vocabulary AND names its own remedy (it has
    to: it is what the poller announces when it holds a card). So this passes the sentence
    through rather than composing a rival one, which is the difference between one answer and
    two that will disagree by next month."""
    held = p.box_gate() if p.box_gate else None
    if not held:
        return Finding("box_proof", True,
                       "the box is proven — this project can be picked up")
    return Finding("box_proof", False, held,
                   "the sentence above is the poller's own: until it clears, cards stay in the "
                   "pickup column and nothing runs",
                   next_step="clear the line above — it is what the poller checks before it "
                             "takes a card (ONBOARDING §5)")


def _agent_cred(p: Probes) -> Finding:
    """The ONE credential ONBOARDING §1 says cannot be postponed — presence, checked at last.

    Presence only, deliberately: verifying it WORKS costs a model call, and that spend belongs to
    `box prove`, which the pickup gate already requires. What this closes is the opposite lie —
    a fresh install with zero credentials reading "OK — can run a ticket" and failing at the
    first paid job, one layer from the cause."""
    assert p.agent_credential is not None
    present, detail = p.agent_credential()
    if present:
        return Finding("agent_credential", True,
                       detail or "an agent credential is present (box prove verifies it works)")
    return Finding(
        "agent_credential", False,
        "no agent credential — the coding agent cannot authenticate, so no job can run",
        "set CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`) or ANTHROPIC_API_KEY in the "
        "environment the worker reads — for compose: .env.compose, then restart with --env-file",
    )


def _docker(p: Probes) -> Finding:
    ok, detail = p.docker_running()
    if ok:
        return Finding("docker", True, "docker is running")
    if detail:  # a distinguishable cause — say THAT, not the generic one
        return Finding(
            "docker", False,
            f"the sandbox cannot start, so no job can run: {detail}",
            "install the docker CLI in this image (the daemon itself stays on the host, reached "
            "through the mounted /var/run/docker.sock)",
        )
    return Finding(
        "docker", False,
        "docker is not running — the sandbox cannot start, so no job can run",
        "start Docker Desktop (or the daemon), then re-run `openfactory doctor`",
    )


def _harness(p: Probes) -> Finding:
    kind = p.harness_kind()
    if p.harness_on_path(kind):
        return Finding("harness", True, f"harness {kind!r} is on PATH")
    return Finding(
        "harness", False,
        f"the harness {kind!r} is not on PATH — the agent has nothing to run the ticket with",
        # THE REGISTRY, NOT THE MANIFEST, AND THE OLD ADVICE MADE THINGS WORSE. `harness` is a
        # deployment decision — it names the BINARY the agent runs, so a repository the agent
        # edits may not choose it — and `Manifest` forbids unknown keys, so an operator who
        # followed this line to the letter turned "the harness is not installed" into "the
        # manifest no longer loads at all" (2026-08-15).
        f"install the {kind!r} CLI and authenticate it, or point this project at one that is: "
        f"`openfactory project add {{name}} --harness <kind>` writes it to the deployment's "
        "registry (it is not a manifest field — the repository the agent edits does not choose "
        "which binary runs it)",
    )


def _declared(manifest: object) -> tuple[str, ...] | None:
    """The keys this manifest's file set, or **None when this object cannot say**.

    The three-state rule this module already learned the expensive way on `board_columns`: `()` is
    *read it, nothing there*, `None` is *could not read*, and one value cannot carry both. A probe
    may hand back any object at all — the port types it `object` — so an empty tuple is claimed
    only when a real `Manifest` reported an empty `model_fields_set`, never when the attribute was
    absent. Absence reading as compliance would be bad; absence reading as an EMPTY manifest would
    be worse, because it fails a healthy project loudly."""
    keys = getattr(manifest, "declared_keys", None)
    return tuple(keys()) if callable(keys) else None


def _settings_total(manifest: object) -> int | None:
    """How many settings the schema offers, so "declares 3" has a denominator. None when unknown —
    the sentence simply drops the ratio rather than inventing one."""
    fields = getattr(type(manifest), "model_fields", None)
    return len(fields) if isinstance(fields, dict) else None


def _manifest(p: Probes) -> Finding:
    """Did the file load — and, once it has, did anybody FILL IT IN?

    ".sdlc/project.yaml loads" was the whole answer, and it is true of a file containing `{}`.
    Thirty-one fields, none required, so the empty manifest is a legal manifest: `validate:` is
    `{}`, every gate the platform would run is absent, and the client has been told by the command
    we ask them to run that their setup is fine. Misspelling a key is NOT this failure — that is
    caught, because `extra="forbid"` makes an unknown key a load error and it arrives below as a
    ValueError. The one that got through is the file nobody wrote anything in."""
    try:
        manifest = p.manifest()
    except namespace.RetiredNamespace as exc:
        # A REPOSITORY STILL ON THE DIRECTORY'S RETIRED NAME. The loader's sentence already
        # says what to rename; the remedy must say NOTHING ELSE. The missing-manifest arm
        # below sends the reader to `openfactory onboard`, which reads a repository and
        # proposes a manifest for it — for THIS repository that is a second manifest beside
        # the one it has (review, 2026-08-25: two doors, two contradictory remedies for one
        # repository). Onboarding refuses it by the same sentence; the doctor points at the
        # rename and at nothing that infers or writes.
        return Finding(
            "manifest", False, str(exc),
            f"rename the directory `{namespace.RETIRED_DIR}/` to `{namespace.DIR}/` in that "
            f"repository and re-run this check. Nothing needs proposing: the manifest is "
            f"there, under the platform's former name, and nothing under "
            f"`{namespace.RETIRED_DIR}/` is read",
            next_step=f"rename `{namespace.RETIRED_DIR}/` to `{namespace.DIR}/` in the "
                      f"repository — the file itself is right where it is; only the directory "
                      f"carries the former name")
    except FileNotFoundError as exc:
        # The message from the loader already names the command that fits THIS project's
        # registration (a checkout writes a file; a clone URL proposes a pull request), so the
        # remedy adds what it cannot know: that this is a session with the people who know the
        # repository, not a file to invent.
        # ALREADY PROPOSED IS THE COMMON CASE HERE, not a fresh start: `openfactory onboard`
        # opens a pull request carrying this exact file, and the manifest stays missing until a
        # HUMAN merges it — deliberately, because a declaration of what the factory will run
        # against somebody's repository should be read before it is true. So the state is LOOKED
        # UP and named with its link, rather than described as a possibility the reader has to
        # match against their own memory.
        proposed = p.open_proposal() if p.open_proposal else ""
        if proposed:
            return Finding(
                "manifest", False,
                f"{namespace.MANIFEST} is missing here because it is still PROPOSED, not "
                f"merged: {proposed}",
                "review that pull request and merge it — ONBOARDING §3, 'Then YOUR step'. It "
                "is yours on purpose: the factory never merges its own declaration of what it "
                "will run against your repository. Nothing needs proposing again — re-running "
                "`openfactory onboard` is safe (it finds this pull request instead of opening a "
                "second one, and re-proves the box on the way), but the merge is what this "
                "check is waiting for",
                next_step=f"review and merge {proposed} — ONBOARDING §3's 'Then YOUR step'. "
                          f"The declaration is proposed and waiting for a human, which is the "
                          f"one step this platform will never take for you")
        return Finding("manifest", False, f"{namespace.MANIFEST} is missing — {exc}",
                       "the environment session named above reads your repository and PROPOSES "
                       "the file for a human to correct and merge (ONBOARDING §3); "
                       "`openfactory onboard <project> --yes` is the same step done where the "
                       "factory lives. Reference: docs/project.yaml.example",
                       next_step="the manifest gets written — ONBOARDING §3, or "
                                 "`openfactory onboard <project> --yes` where the factory lives")
    except ValueError as exc:
        return Finding("manifest", False, f"{namespace.MANIFEST} is invalid — {exc}",
                       "fix the file the message names; `version:` must be one this build supports")

    declared = _declared(manifest)
    if declared is None:
        # This object cannot say what its file set. NOT "it set nothing" — see `_declared`.
        #
        # AND IT MUST NOT SAY ONLY "the manifest loads" EITHER, which is the sentence this
        # whole check exists to stop being the answer. `ok` stays True on purpose: the file loaded,
        # and failing a project because OUR introspection came up empty would be the loud-false-
        # negative the docstring above rejects. But a reader has to be able to tell "filled in" from
        # "I could not tell", so the message says which of the two it is and the ratio is absent
        # rather than invented.
        return Finding(
            "manifest", True,
            f"{namespace.MANIFEST} loads; this build cannot say which settings it declares "
            f"({type(manifest).__name__} does not answer `declared_keys()`), so read nothing here "
            "as 'the manifest is filled in'",
        )
    total = _settings_total(manifest)
    if not declared:
        return Finding(
            "manifest", False,
            f"{namespace.MANIFEST} parses and declares nothing — "
            f"{'all ' + str(total) if total else 'every one'} of its settings are the framework's "
            "defaults, `validate:` among them, so this project has no gates at all and a run with "
            "no gates reports green having proven nothing",
            "the file is empty or entirely commented out: run `openfactory project init <name>`, "
            "which writes a starter declaring a `test` gate and an advisory `security` one, then "
            "replace the commands with this repo's own",
        )
    ratio = f"{len(declared)} of {total}" if total else str(len(declared))
    return Finding("manifest", True,
                   f"{namespace.MANIFEST} loads and declares {ratio} settings "
                   f"({', '.join(declared)}); everything else is a framework default")


def _normalised(command: str) -> str:
    """A command with its whitespace collapsed, for comparing two spellings of one line.

    TEXT AGAINST TEXT, and the check says so out loud to whoever reads it. The platform does not
    know what any of these commands DO — that is the whole reason it can work for a .NET shop and
    a dbt shop without being taught either.
    """
    return " ".join((command or "").split())


def _same_command(a: str, b: str) -> bool:
    """Whether two commands are plausibly the same instruction.

    CONTAINMENT EITHER WAY, because a manifest routinely carries a narrower spelling of what the
    pipeline runs — `uv run pytest tests/unit` declared against `uv run pytest tests/unit -q
    --no-cov` in CI. Reporting that pair as a gap would make the check noise on its first run,
    and a check nobody believes is worse than no check.
    """
    left, right = _normalised(a), _normalised(b)
    if not left or not right:
        return False
    return left in right or right in left


def _ci_declared(p: Probes) -> Finding:
    """What the project's own CI runs, against what its manifest declares (#176).

    THE READING USED TO HAPPEN ONCE. `onboarding/infer.py` proposes a manifest in a room, on a
    day, and nothing ever compared the two again — so podbeam was onboarded with three
    validations, its CI later grew a fourth (a gate the client wrote BECAUSE the defect it catches
    is invisible to local tests), and the factory went on running three. A pull request then went
    out carrying exactly that defect.

    Both directions, because both are drift: a check the pipeline runs and the manifest does not
    declare, and a validation the manifest declares that the pipeline no longer runs. A check that
    only ever grows the list is one that cannot see a client retiring something.

    ADVISORY, NEVER A GATE. Some CI steps must not run in a box — a deploy, anything holding a
    secret, a matrix setup — and deciding which is guessing the client's stack, which the floor
    rule forbids. So a difference is a QUESTION carried on a passing finding, in the shape
    `box_proof` and the missing-tool remedy already use. What the client may not do is fail to
    know.
    """
    found = p.ci_checks() if p.ci_checks else None
    if found is None:
        return Finding(
            "ci_declared", True,
            "could not read this project's CI, so nothing was compared against the manifest",
            note="a pipeline this deployment cannot read is not a pipeline that agrees with the "
                 "manifest — it is one nobody looked at",
        )
    try:
        declared = dict(p.manifest().validation or {})
    except FileNotFoundError:
        return Finding(
            "ci_declared", False,
            "the manifest has not loaded, so its validations cannot be compared with the CI",
            "fix the manifest finding above", awaiting="manifest")
    declared_commands = [c if isinstance(c, str) else getattr(c, "run", "") or ""
                         for c in declared.values()]
    missing = [(key, cmd, where) for key, (cmd, where) in sorted(found.items())
               if not any(_same_command(cmd, d) for d in declared_commands)]
    retired = sorted(
        name for name, cmd in declared.items()
        if (text := cmd if isinstance(cmd, str) else getattr(cmd, "run", "") or "")
        and not any(_same_command(text, c) for c, _w in found.values()))
    if not found:
        return Finding("ci_declared", True,
                       f"this project declares {len(declared)} validations and no CI was found "
                       f"to compare them with")
    if not missing and not retired:
        return Finding("ci_declared", True,
                       f"every check this project's CI runs is declared "
                       f"({len(declared)} validations)")
    parts = []
    if missing:
        # THE LOCATION IS ALWAYS IN THE SENTENCE, and only once. The probe already appends it to
        # the key when two steps share a name, so adding it unconditionally printed it twice.
        listed = "; ".join(key if where in key else f"{key} ({where})"
                           for key, _cmd, where in missing[:4])
        parts.append(f"your CI runs {len(found)} checks and this project declares "
                     f"{len(declared)} — the factory will not run: {listed}")
    if retired:
        parts.append(f"declared but run by no pipeline any more: {', '.join(retired[:4])}")
    return Finding(
        "ci_declared", True, "; ".join(parts),
        note="compared as text, so a command your pipeline spells differently reads as a "
             "difference. Add what a change must pass to `validate:` in "
             "`.openfactory/project.yaml`; leave out anything that belongs to a deploy or needs "
             "a secret the box does not carry.",
    )


def _floor(p: Probes) -> Finding:
    """The question `orchestrator/machine.py:325` asks with an agent pass on the line, asked here
    for free.

    THE FLOOR HAD NO READER BEFORE THE MONEY. `floor_reason` is consulted inside `JobRunner.run`,
    at the one point where the manifest is genuinely in hand — which is correct for enforcement and
    far too late for onboarding: the client learns their quality floor is empty from a warning on a
    ticket they have already paid to start. Doctor holds the same manifest, before the first
    ticket, and was not asking.

    UNMET IS A FAILURE HERE AND A HOLD THERE, which is now the same answer said twice rather than
    two different ones. It was not always: while `OPENFACTORY_ENFORCE_FLOOR` existed, the same
    violation
    meant "jobs run and prove nothing" on one deployment and "every job holds" on another, and this
    finding had to carry the switch's state or it would be a failure wearing an answer's clothes.
    The variable is gone (`orchestrator/machine.py`), so the remedy below says one thing.

    THE DIFFERENCE THAT REMAINS IS COST, not verdict. Doctor spends nothing and blocks nothing: it
    is a human-invoked report whose whole job is to say what is not right yet, BEFORE a ticket is
    picked up — the runner asks the same question at the one point where the manifest is in hand,
    which is correct for enforcement and far too late to learn it from."""
    from openfactory.policy.conformance import floor_reason
    from openfactory.policy.floor import REQUIRED_VALIDATION_ROLES

    try:
        manifest = p.manifest()
    except FileNotFoundError:
        # THE CAUSE IS ONE LINE UP, AND REPEATING ITS TEXT CONTRADICTED IT. The loader's message
        # names the commands that WRITE a manifest ("`env apply … --pr` proposes it as a pull
        # request"), which is right in general and wrong here: when a proposal is already open,
        # `_manifest` says "merge it, nothing needs proposing again" and this line said the
        # opposite, on the same screen, four lines below (pilot, 2026-08-14).
        return Finding(
            "quality_floor", False,
            "the floor could not be checked: the manifest has not loaded",
            "fix the manifest finding above — the floor is a property of that file and there is "
            "nothing to check until it loads",
            awaiting="manifest",
        )
    except Exception as exc:  # noqa: BLE001 — reported in full by `_manifest`; not repeated here
        # UNKNOWN, AND UNKNOWN MUST NOT READ AS PASS. The floor is a property of a file that could
        # not be read, so there is no answer to give — and "no answer" is not "satisfied".
        return Finding(
            "quality_floor", False,
            f"the floor could not be checked: the manifest could not be read ({exc})",
            "fix the manifest finding above — the floor is a property of that file and there is "
            "nothing to check until it loads",
            awaiting="manifest",
        )

    reason = floor_reason(manifest)
    if reason is None:
        roles = ", ".join(f"`{r}`" for r in sorted(REQUIRED_VALIDATION_ROLES))
        return Finding("quality_floor", True,
                       f"the manifest declares every validation the platform's floor requires "
                       f"({roles})")
    # THE REMEDY OPENS BY RESOLVING THE MESSAGE'S TENSE, and that is not a stylistic choice. The
    # floor's sentence is written from the refusal site and says "Nothing was run" — true where the
    # runner prints it, and read here, at setup, before any ticket exists, it is a claim about a
    # job nobody started. Found by running the command rather than by reading the string.
    #
    # `floor_enforced()` IS STILL ASKED rather than assumed, and the arm below it is not dead code
    # waiting to be tidied: a probe is what a test replaces, and a doctor that hardcoded "this
    # holds" could never be shown reporting a deployment where it does not. The constant lives in
    # ONE place (`floor_is_enforced`), which is what makes the removal a single edit.
    if p.floor_enforced():
        return Finding(
            "quality_floor", False, reason,
            "and this is not advice: every ticket this project picks up will be held for a human "
            "BEFORE any agent runs, so nothing is spent discovering it. Add the gate the message "
            "names — `advisory: true` is enough, it never blocks a merge — and the next tick "
            "proceeds.",
        )
    return Finding(
        "quality_floor", False, reason,
        "and on this deployment that is not being refused, so jobs RUN with that gate missing and "
        "a run whose gates are empty reports green having proven nothing. Add the gate the message "
        "names; `advisory: true` is enough, so it never blocks a merge.",
    )


def _forge(p: Probes) -> Finding:
    reachable, detail = p.forge_reachable()
    if reachable:
        return Finding("forge_access", True, "the forge is reachable with the configured token")
    if "no forge credential" in detail:
        # THE REMEDY NAMES THE PROJECT'S OWN VENDOR. This always answered with the GitHub pair,
        # so an Azure DevOps deployment missing its PAT was told to create a GitHub App — a
        # remedy that cannot fix it, on the check whose whole point is the remedy (funnel
        # review, 2026-08-09). The probe says which vendor it looked for; trust it.
        if "azure_devops" in detail:
            remedy = ("set AZURE_DEVOPS_PAT (or the variable this project names in "
                      "`forge.options.token_env`) in the environment the worker reads — a PAT "
                      "from dev.azure.com → User settings → Personal access tokens; "
                      "docs/setup/azure-devops.md is the whole recipe")
        else:
            remedy = ("set OPENFACTORY_BOT_TOKEN (a PAT, to try things out) or the GitHub App "
                      "trio (OPENFACTORY_GH_APP_ID / _KEY or _KEY_CONTENT / _INSTALLATION_ID) "
                      "in the environment the worker reads — docs/setup/github.md is the "
                      "whole recipe")
        return Finding(
            "forge_access", False,
            "no forge credential is configured — the factory cannot push a branch or open a PR",
            remedy,
        )
    return Finding(
        "forge_access", False,
        f"the forge refused the configured credentials — {detail}",
        "a GitHub App: grant it access to this repository (Contents / Issues / Pull requests / "
        "Projects). A PAT: check its scopes and that it has not expired. The coordinates the "
        "probe used are the project's registry entry",
    )


def _board(p: Probes) -> Finding:
    try:
        columns = p.board_columns()
    except BoardUnreadable as exc:
        return Finding(
            "board_columns", False,
            f"the board {exc} is configured but could not be read, so nothing can say whether the "
            "poller will ever pick anything up",
            exc.remedy or
            "this is almost always the tracker credential rather than the board: check that the "
            "variable this project names in `tracker.options.token_env` is set for THIS process, "
            "and that it grants read access to the board's organisation",
        )
    if columns is None:
        return Finding("board_columns", True,
                       "no board configured — tickets are named directly (`openfactory run`)")
    wanted = p.pickup_column() or PICKUP_COLUMN
    if wanted in columns:
        return Finding("board_columns", True, f"the board has a {wanted!r} column")
    return Finding(
        "board_columns", False,
        f"the board has no {wanted!r} column, so the poller will never pick anything up "
        f"and nothing will say why (found: {', '.join(columns) or 'none'})",
        # NOT "rename your column". C-14 settled that the names belong to the client, and this
        # line was still asking them to rename a board the platform itself had just created.
        "declare the mapping in the project's tracker options — "
        '`columns: {"todo": "<your column>"}` — or set `pickup_status` to name it directly. '
        "Renaming the board is the last resort, not the first.",
    )


def _post_merge(p: Probes) -> Finding:
    """What happens after a merge — stated, never assumed.

    NOT A FAILURE, EVER. A project that deploys nothing, or deploys by hand, is an ordinary
    project; failing it for that would be the platform's opinion wearing a diagnostic's clothes.
    But SILENCE is what cost the pilot a day (2026-08-16): his repository has a `Deploy to staging`
    workflow that runs on every push to main, and OpenFactory watched none of it, said nothing
    about not watching it, and left him asking where the staging validation had gone. The whole
    post-merge half of this platform is switched on by two manifest keys that no report mentioned
    and no reader would guess.

    So this check says which of the three worlds a project is in, and the remedy names the key.
    """
    manifest = p.manifest()
    watch = getattr(manifest, "post_merge_deploy", None)
    envs = list(getattr(manifest, "environments", {}) or {})
    # WHETHER ANYBODY CAN BE SENT ANYWHERE (#122). A watched deploy with no address reports that a
    # pipeline was green, which tells a reviewer nothing about whether the product is right — and
    # the whole reason the operator raised this was that a green staging deploy asked nobody to
    # look at it. A pass that omitted this would be reporting the half that works.
    stage = manifest.stage_a_person_confirms() if hasattr(manifest, "stage_a_person_confirms") \
        else ""
    where = manifest.where_a_person_looks(stage) if stage else ""
    if stage and not where:
        # NAME THE LEVER THIS PROJECT ACTUALLY HAS. A repository that only watches its own deploy
        # run has no `environments:` block, and telling it to add a key under one is a remedy that
        # does not fit the file it is about — the `conformance` mistake this platform has made
        # before, where the suggested fix was one the schema itself would refuse.
        lever = (f"`environments.{stage}`" if envs else "`post_merge_deploy:`")
        other = ("`post_merge_deploy:`" if envs else f"`environments.{stage}:`")
        dark = (f" — but nobody can be asked to validate {stage}: no `url:` is declared for it, "
                f"so a green deploy is reported and no person is sent anywhere. Add `url:` under "
                f"{lever} in {namespace.MANIFEST} (or under {other} if you declare one) — it is "
                f"where a PERSON looks, which is NOT `health_url`. docs/ONBOARDING.md §13")
    elif stage:
        dark = f" — and when {stage} is green somebody is asked to confirm it at {where}"
    else:
        dark = ""
    if watch is not None:
        env = getattr(watch, "env", "") or "dev"
        chain = f", then promotes through {', '.join(envs)}" if envs else ""
        return Finding("post_merge", True,
                       f"after a merge: the {getattr(watch, 'workflow', '?')} run on the merge "
                       f"commit is watched and its {env} outcome reported{chain}",
                       note=dark.lstrip(" —"))
    if envs:
        return Finding("post_merge", True,
                       f"after a merge: the promotion chain observes {', '.join(envs)} "
                       f"(no deploy WATCH is configured, so the run itself is not followed)",
                       note=dark.lstrip(" —"))
    return Finding(
        "post_merge", True,
        "after a merge: nothing. No deploy is watched and nobody is asked to validate one — "
        "whatever your pipeline does after the merge, the factory is not looking",
        "if that is not what you want, declare `post_merge_deploy:` (watch your own deploy run "
        "and report it) or `environments:` + `promote:` (walk your stages, gate production) in "
        f"{namespace.MANIFEST} — docs/ONBOARDING.md §13 has both, with the YAML",
    )


def _merge_policy(p: Probes) -> Finding:
    policy = getattr(p.manifest(), "merge_policy", "human")
    if policy != "auto" or not p.requires_review():
        return Finding("merge_policy", True, f"merge_policy {policy!r} is consistent with the "
                                             "repository's branch protection")
    return Finding(
        "merge_policy", False,
        "merge_policy is 'auto' but this repository's branch protection requires a human review — "
        "the bot will open PRs it can never merge, and the job will wait and then park",
        "either set `merge_policy: human` in .openfactory/project.yaml (the bot opens the PR, "
        "a person merges it), or drop the required review for the bot on this branch",
    )


def _product(p: Probes) -> Finding:
    """Ask the product link the same question the product role asks, at setup instead of at sweep.

    The four verdicts need four different people, and flattening them is how a misconfiguration
    survives: `off` is nobody's problem, `config` is the operator's, `conflict` belongs to whoever
    edited one of the two declarations."""
    link = p.product_link()
    kind = getattr(link, "kind", "off")
    reason = getattr(link, "reason", "")
    warnings = list(getattr(link, "warnings", []) or [])
    if kind == "off":
        # OFF IS A LEGITIMATE SETUP AND IT IS NOT A SILENT ONE. The coding agents read the SOURCE
        # repository's manifest (`docs.constraints`, `docs.architecture`, `docs.guidelines`), so
        # a ticket genuinely runs without a context repository — this must not become a FAIL, or
        # every deployment that never wanted the product role is told it is broken.
        #
        # But reporting it as a bare pass reads as "nothing to see", and the operator asked the
        # right question about the right screen (2026-08-14): *"o doctor não pode falar para
        # seguir com ticket sem o contexto, não concorda?"* What is switched off is the CLIENT's
        # half — the requirements corpus, the product role's answers, the "ready to try" bridge
        # and the yes that releases production. So the pass says what is off and how to turn it
        # on, and the closing verdict repeats it (`note`), because "OK — can run a ticket" on its
        # own is true about the code and silent about the product.
        return Finding(
            "product_link", True,
            "no product module configured — tickets run (the coding agents read this repo's own "
            "`docs:`), and the CLIENT-facing half is off: no requirements corpus, no product "
            "role, no 'ready to try' message, no client yes before production",
            note="the product module is OFF for this project. If you want the client-facing "
                 "half, `openfactory onboard <project> --yes` creates or uses the context "
                 "repository and proposes the backfill (ONBOARDING §4 and §9)")
    if getattr(link, "active", False):
        docs = getattr(link, "docs_repo", "")
        note = f" — note: {'; '.join(warnings)}" if warnings else ""
        return Finding("product_link", True, f"product module agrees with {docs}{note}")
    if kind == "conflict":
        return Finding(
            "product_link", False, f"the two declarations disagree — {reason}",
            f"fix whichever is wrong: `sources:` in the context repo's "
            f"{namespace.PRODUCT_MANIFEST}, or `docs_repo:` in this repo's {namespace.MANIFEST}. "
            f"The module stays OFF until they agree, because redirecting on a mismatch would let "
            f"a source repo point itself at any documentation repository",
        )
    return Finding(
        "product_link", False, f"the product module is enabled but unusable — {reason}",
        "check which repository is declared (`openfactory product declare <project> "
        "<owner/repo>` re-declares it) and that it is readable with the configured credentials",
    )


# ── the real probes ─────────────────────────────────────────────────────────────────────────────

def _resolve_link(project):
    """The product module's verdict for this project, built the way the product role builds it.

    LITERALLY the way the product role builds it — `module.py:352` calls this same function. The
    hand-assembled version this replaces imported `load_product_docs`, which does not exist and
    never did, so the probe raised ImportError into `_guarded` and the tool reported "could not
    check product_link": a broken check that reads as a failing one.

    Re-using `load_product_context` is not just shorter. It carries the no-network short circuit
    for a project with no `product:` section — the overwhelmingly common case — so the diagnostic
    does not clone a documentation repository to discover there isn't one.
    """
    from openfactory.product.loader import load_product_context

    # Minted only when there is something to authenticate FOR. `load_product_context` short
    # circuits on exactly this condition, so an eager mint would sign a JWT and call GitHub in
    # order to learn there is no documentation repository — in the diagnostic somebody runs
    # BECAUSE their machine is not working. Erring the other way (minting when unsure) costs one
    # call; erring toward None would break the checkout, so the condition matches the callee's.
    cfg = getattr(project, "product", None)
    enabled = cfg is not None and getattr(cfg, "enabled", True)
    claim = getattr(load_manifest_quietly(project), "docs_repo", None)
    return load_product_context(
        project, token=_forge_credential() if enabled else None, source_claim=claim
    ).link


def _forge_credential() -> str | None:
    """The token the FORGE authenticates with — static if the deployment set one, otherwise
    freshly minted from the App. Resolved at USE, never at wiring."""
    from openfactory.credentials import forge_token
    from openfactory.factory import github_app_token_from_env

    # github-only: this asks about the DEPLOYMENT's own credential and takes no project, so there
    # is no axis to ask. `_board_credential` below is the per-project question and it does ask.
    return forge_token() or github_app_token_from_env()


def _board_coordinates(project) -> str:
    """Which board could not be read, in ITS OWN vendor's coordinates.

    This was formatted from `board_owner`/`board_number` for every provider, so a Jira or Azure
    project — neither of which has those options, because there the status IS the column — got
    `?/?`. Not cosmetic: the first question a person asks is *which* board, and `?/?` answers it
    with a shrug while looking like the tool checked something."""
    tracker = getattr(project, "tracker", None)
    options = getattr(tracker, "options", None) or {}
    kind = (getattr(tracker, "kind", "") or "?").strip().lower()
    if kind == "github":
        return f"{options.get('board_owner', '?')}/{options.get('board_number', '?')}"
    if kind == "azure_devops":
        org = options.get("organization") or options.get("org") or "?"
        return f"{org}/{options.get('project') or getattr(tracker, 'repo', '') or '?'}"
    # Jira and anything new: the project IS the board, so its own coordinate is the honest answer
    return f"{options.get('site', '')}{' ' if options.get('site') else ''}" \
           f"{options.get('project_key') or getattr(tracker, 'repo', '') or '?'}".strip()


def _board_remedy(project) -> str:
    """The remedy in the vendor's vocabulary — see `BoardUnreadable`."""
    tracker = getattr(project, "tracker", None)
    options = getattr(tracker, "options", None) or {}
    kind = (getattr(tracker, "kind", "") or "").strip().lower()
    named = str(options.get("token_env") or "").strip()
    if kind == "github":
        return ("this is almost always the credential rather than the board: check that "
                "OPENFACTORY_BOT_TOKEN or the App's OPENFACTORY_GH_APP_ID/KEY/INSTALLATION_ID "
                "are set for THIS "
                "process, and that the installation covers the board's organisation")
    if kind == "azure_devops":
        return (f"check that {named or 'AZURE_DEVOPS_PAT'} is set for THIS process and grants "
                "read on Work Items — Azure DevOps answers a wrong credential with HTTP 200 and a "
                "sign-in PAGE rather than a 401, so this reads as an empty board. A GitHub token "
                "reaching this axis produces exactly that; the board takes the TRACKER's "
                "credential, never the forge's.")
    if kind == "jira":
        return (f"check that {named or 'the tracker token variable'} is set for THIS process and "
                "that the account can browse the project")
    return ""


def _board_credential(project):
    """The token THIS PROJECT'S BOARD authenticates with. A provider, resolved at use.

    THE BOARD IS A TRACKER OBJECT AND WAS BEING HANDED THE FORGE'S CREDENTIAL. That is invisible
    while one vendor fills both axes and immediate the moment one does not — and the failure is
    the expensive kind, because Azure DevOps answers a GitHub token with **HTTP 200 and a sign-in
    page**, not a 401. Found by running `openfactory doctor` against a real Azure project on a
    laptop
    whose `.env` carries `OPENFACTORY_GH_APP_*`: the App minted a token, the board presented it to
    dev.azure.com, and the check reported "the board is configured but could not be read".

    The docstring above this one used to say "the forge and the board", which is how the two came
    to share a resolver in the first place — a sentence describing a coupling instead of a
    decision. `cli.py::pickup` and `techlead/conversation.py` had the same bug and were fixed with
    the ADO pack; this site was the neighbour left behind, and only an end-to-end run found it."""
    from openfactory.credentials import deployment_tracker_token, tracker_token_for

    def resolve() -> str | None:
        return tracker_token_for(project) or deployment_tracker_token(project)

    return resolve


def floor_is_enforced() -> bool:
    """Whether THIS environment turns a floor violation into a refusal. It always does.

    THIS USED TO READ `OPENFACTORY_ENFORCE_FLOOR`, and the constant it returns now is the whole
    point of
    removing that variable: the floor is not a deployment's preference. `policy/floor.py` calls
    itself "the non-negotiable guarantees", `org_defaults/floor.yaml` says in writing that there is
    "deliberately no deployment-wide off switch", and the site copy promises the floor REFUSES a
    paid agent pass. A variable that was off by default made all three false wherever nobody knew
    its name — which, for an open-source install, is everywhere.

    KEPT AS A FUNCTION RATHER THAN INLINED, so the removal is one edit here if that decision is
    ever revisited, and so `Probes.floor_enforced` — which exists to be swapped in a test — keeps
    the shape every other probe on this object has."""
    return True


def load_manifest_quietly(project):
    """The manifest, or a blank stand-in. A missing manifest is already reported by its own check;
    reporting it twice would make two findings out of one problem."""
    from openfactory.loader import load_manifest

    try:
        return load_manifest(project)
    except Exception as exc:  # noqa: BLE001
        log.debug("manifest unreadable while resolving the product link (%s) — the manifest "
                  "check reports it; this one continues with no claim", exc)
        return type("_Blank", (), {"docs_repo": None, "merge_policy": "human"})()


def notifier_fallback_line(state=None) -> str:
    """ONE LINE saying where project-less speech goes — derived from the notifier registry and
    the rows installed on its axis; this module names no package's variable and no vendor.

    WHY A LINE HERE. The deployment-wide fallback is DECLARED (`OPENFACTORY_NOTIFIER_FALLBACK`)
    since 2026-08-26, and the old switch — a fallback row's own two variables, set — now does
    nothing: `build_notifier(None)` answers `NullNotifier` and the notify logger says nothing,
    because nothing is wrong from the registry's point of view. The deployment is READ here,
    so here is where that silence gets a sentence: the state as it stands and, when a notifier
    is installed and not declared, the exact line to add."""
    from openfactory import plugins
    from openfactory.adapters.notify.registry import AXIS, FALLBACK_ENV, NOTIFIERS, fallback_state

    s = state if state is not None else fallback_state()
    if s.declared and s.implemented and not s.cannot_post:
        return (f"notifier fallback: {s.declared} — project-less notifications, and a project "
                f"whose own channel cannot post, go there")
    if s.declared and s.implemented:
        return (f"notifier fallback: {s.declared} is declared but cannot post — missing "
                f"{s.cannot_post}; project-less notifications go nowhere until that is filled in")
    if s.declared:
        return (f"notifier fallback: {s.declared} is declared and no notifier row implements it "
                f"(known: {', '.join(plugins.known(AXIS, NOTIFIERS))})"
                f"{plugins.install_hint(AXIS, s.declared)}; project-less notifications go "
                f"nowhere until it is installed")
    line = "notifier fallback: none declared — project-less notifications go nowhere"
    if s.installed:
        kinds = ", ".join(s.installed)
        one = len(s.installed) == 1
        which = s.installed[0] if one else f"<one of {kinds}>"
        line += (f"; {kinds} {'is installed and is not' if one else 'are installed and none is'} "
                 f"the fallback; declare {FALLBACK_ENV}={which} to route project-less "
                 f"notifications there")
    # NOT OFFERED, BUT SAID: a row that answers a project field to a project-less caller can
    # never be the deployment-wide fallback — the remedy above must be executable, so it is
    # kept out of it, and the row is named here with what it would still need.
    for kind, need in s.unserviceable:
        line += (f"; {kind} is installed, and a project-less caller cannot use it — it would "
                 f"still need {need}")
    return line


def probes_for(project) -> Probes:
    """The live probes for a registered project. Each one answers narrowly and never raises past
    `_guarded`."""
    from openfactory.adapters.agent.registry import harness_kind
    from openfactory.loader import load_manifest

    def _docker_running() -> tuple[bool, str]:
        try:
            return subprocess.run(["docker", "info"], capture_output=True,
                                  timeout=10).returncode == 0, ""
        except FileNotFoundError:
            # NOT the same as a stopped daemon, and the difference is the whole remedy. The worker
            # image mounts the host socket and shipped no client to speak to it.
            return False, "the docker CLI is not installed in this environment"
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"`docker info` could not be run ({str(exc)[:120]})"

    def _on_path(kind: str) -> bool:
        # The registry owns kind → binary (agent/registry.py). This used to be a local three-entry
        # map under a comment promising it was not one, so `opencode` would have been reported
        # missing from PATH under the name `opencode` only by luck of the two matching.
        from openfactory.adapters.agent.registry import harness_binary

        return shutil.which(harness_binary(kind)) is not None

    def _agent_credential_probe() -> tuple[bool, str]:
        from openfactory.adapters.agent.registry import harness_kind as _hk

        kind = _hk(project, "executor")
        if kind != "claude_code":
            return True, (f"presence is not checkable for {kind!r} from here — "
                          f"`openfactory box prove` exercises the real call")
        if (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
                or os.environ.get("OPENFACTORY_AGENT_TOKENS")):
            return True, ""
        return False, "no agent credential in this environment"

    def _forge() -> tuple[bool, str]:
        from openfactory.adapters.forge.registry import build_forge
        from openfactory.credentials import forge_token_for

        token = forge_token_for(project)
        # PRESENCE first, reachability second. With no static token and no App variables the old
        # probe still "reached" the forge (a 404 on a public endpoint reads as allowed-to-ask) and
        # doctor printed ok about a configured token that did not exist — a green light over the
        # one gap that stops the first push (pre-pilot review, 2026-08-09). The App check reads
        # the VARIABLES, deliberately: minting a real token here would make a diagnostic spend.
        from openfactory.credentials import app_id, app_installation_id, app_private_key

        # through the ONE sanctioned reader per credential (one-process-one-installation guard) —
        # a second inline os.environ read is a second place precedence can disagree
        has_app = bool(app_id() and app_installation_id() and app_private_key())
        if token is None and not has_app:
            # THE KIND TRAVELS IN THE DETAIL so the Finding's remedy can name the right vendor's
            # variable — `forge_token_for` already resolves AZURE_DEVOPS_PAT for an azure axis,
            # so reaching here means that variable is genuinely absent too.
            kind = (getattr(getattr(project, "forge", None), "kind", "")
                    or getattr(getattr(project, "tracker", None), "kind", "") or "github")
            return False, f"no forge credential is configured for the {kind} forge"
        forge = build_forge(project, token=token)
        try:
            forge.pr_status(pr="1")  # any read; we only care whether we are allowed to make it
            return True, ""
        except Exception as exc:  # noqa: BLE001 — the message IS the finding
            text = str(exc)
            # THE STATUS, NOT THE DIGITS. This asked `"401" in text`, and Azure DevOps answers a
            # missing pull request with `TF401019: The Git repository ... does not exist` — an
            # ERROR CODE that contains 401. So a perfectly healthy Azure deployment was told its
            # forge had refused the credential, with a remedy about granting the GitHub App
            # permissions it does not have and does not need.
            #
            # THIRD TIME THIS EXACT SHAPE HAS BILLED THIS CODEBASE: `_RATE_RE` matched `429` inside
            # generated session ids and parked healthy jobs as rate-limited in three adapters, and
            # a substring guard tripped on the prose explaining its own rule. A bare number inside
            # a message is not a status; the status is the token after the arrow this adapter's
            # errors are formatted with, or a word.
            denied = re.search(r"→\s*(401|403)\b", text) or "not accessible" in text
            if denied:
                return False, text
            # Anything else — 404 included — means we were ALLOWED to ask. The probe is about
            # permission, and "there is no PR #1 in this project" is a fine answer to it.
            return True, ""

    def _columns() -> list[str] | None:
        """WHICH COLUMNS EXIST — not which ones have cards in them.

        This asked `columns()` and did `list(...)` over it. That is `{ticket: column}`, so on an
        empty board it produced `[]` ("the board has no 'TO-DO' column — found: none") and on a
        populated one a list of ticket NUMBERS. Every board is empty at onboarding, which made the
        first command a new client runs fail on the check that exists to reassure them.

        The credential is passed for the same reason `_forge` passes one: with an App-only
        deployment there is no ambient `gh` login, so an unauthenticated read returns nothing and
        looks exactly like a missing column. It works on a laptop with `gh auth login` and fails in
        the worker — the worst shape a setup check can have. It goes in as a PROVIDER so a project
        with no board pays nothing: `build_board` returns None before anything is resolved.
        """
        from openfactory.adapters.board.factory import build_board

        board = build_board(project, token_provider=_board_credential(project))
        if board is None:
            return None  # no board configured — a legitimate setup, and the ONLY meaning of None
        names = board.column_names()
        if names is None:  # the port's "could not read", which is not "does not exist"
            raise BoardUnreadable(_board_coordinates(project),
                                  remedy=_board_remedy(project))
        return names

    def _pickup_column() -> str:
        """Ask the board; `""` when there is none, so `_board` falls back to the platform default.

        Built here rather than closed over `_columns`' board because `build_board` holds no
        connection — it reads the registry row — so a second construction costs nothing and keeps
        the two probes independent, which is what lets a test exercise either alone."""
        from openfactory.adapters.board.factory import build_board

        board = build_board(project, token_provider=_board_credential(project))
        return board.pickup_column() if board is not None else ""

    def _requires_review() -> bool:
        from openfactory.adapters.forge.registry import build_forge

        forge = build_forge(project)
        checker = getattr(forge, "requires_review", None)
        return bool(checker()) if callable(checker) else False

    def _box_gate() -> str | None:
        """THE POLLER'S OWN QUESTION, asked here so the answer cannot differ."""
        from openfactory.box_prove import gate_reason
        from openfactory.runtime.temporal.io import default_sandbox

        return gate_reason(project, sandbox=default_sandbox())

    def _foreign_proofs() -> bool:
        """THE POLLER'S SECOND QUESTION, asked of the same function it asks (C-18)."""
        from openfactory.box_prove import foreign_proofs_recorded

        return foreign_proofs_recorded(str(getattr(project, "name", "") or ""))

    def _api_budget_probe():
        """The budget for the credential THIS project's tracker reads actually use — asked of
        the project's OWN tracker through the port. `Budget` | `NOT_REPORTED` | unreadable.

        It used to call `github_project.github_rate` by name with `_board_credential(project)`,
        whatever the tracker — so on a Jira project the JIRA token was exported as `GH_TOKEN`
        and presented to api.github.com, the cross-vendor class `_board_credential`'s own
        docstring was written to end. Anything that is not a `Budget` and not `NOT_REPORTED`
        means one thing only: the vendor reports a budget and the read FAILED. A vendor with
        none declares so, and is rendered so.

        UNREADABLE IS HANDED BACK WITH ITS REASON. The port raises `BudgetUnreadable` carrying
        the vendor's own words, and this returned a bare `None` — so the check above could only
        say "could not be read" while `floor/reading.py` printed the cause on the same
        deployment. The exception is a value here, not a raise: `_guarded` would otherwise turn
        one unreadable quota into "could not check api_budget", losing the check's own sentence.
        `None` stays possible (a builder that raised something else) and reads as unreadable
        without a reason, which is the honest rendering of not knowing why.
        """
        from openfactory.adapters.tracker.base import BudgetUnreadable
        from openfactory.adapters.tracker.registry import build_tracker

        try:
            return build_tracker(project, token_provider=_board_credential(project)).budget()
        except BudgetUnreadable as exc:
            log.info("could not read the API budget for %s (%s)",
                     getattr(project, "name", "?"), str(exc)[:120])
            return exc
        except Exception as exc:  # noqa: BLE001 — a diagnostic never breaks on a probe
            log.info("could not ask %s's tracker for its API budget (%s)",
                     getattr(project, "name", "?"), str(exc)[:120])
            return None

    def _open_proposal() -> str:
        """The open pull request carrying this project's manifest, or `""`.

        BOTH BRANCHES, because both verbs propose: `onboard` rides `openfactory/onboard` and
        `env apply --pr` rides `openfactory/manifest`. Asked through `already_proposed`, which
        answers `None` for "could not ask" — and an unreachable forge must read as "no
        information", never as "there is none", or this line would tell somebody to propose a
        second copy of what is already open."""
        from openfactory.adapters.forge.registry import build_forge, repo_of
        from openfactory.credentials import deployment_forge_token, forge_token_for
        from openfactory.onboarding.propose_manifest import already_proposed

        try:
            forge = build_forge(project, token=forge_token_for(project)
                                or deployment_forge_token(project))
            repo = repo_of(project)
        except Exception as exc:  # noqa: BLE001 — a diagnostic never breaks on a probe
            log.info("could not ask %s about open proposals (%s)",
                     getattr(project, "name", "?"), str(exc)[:120])
            return ""
        for branch in ("openfactory/onboard", "openfactory/manifest"):
            found = already_proposed(forge, repo, branch)
            if found:
                return found
        return ""

    def _ci_checks() -> dict[str, tuple[str, str]] | None:
        """What this project's own CI runs, read from the checkout — or None (#176).

        THROUGH `infer`, NOT A SECOND READER. That module already reads GitHub workflows, Azure
        pipelines, GitLab, CircleCI, Travis, buildspec, Jenkins, the Makefile and the Dockerfile,
        offline, without running anything and without touching the network — and since #175 it
        also proposes the checks that fill none of our roles. A second parser here would be the
        two-spellings defect committed by the very check written to catch it.
        """
        from openfactory.factory import resolve_repo_path
        from openfactory.onboarding.infer import infer

        try:
            root = resolve_repo_path(project)
        except Exception as exc:  # noqa: BLE001 — a diagnostic never breaks on a probe
            log.info("could not resolve %s's checkout to read its CI (%s)",
                     getattr(project, "name", "?"), str(exc)[:120])
            return None
        if not root or not pathlib.Path(root).is_dir():
            return None
        try:
            proposal = infer(root)
        except Exception as exc:  # noqa: BLE001
            log.info("could not read %s's CI (%s)", getattr(project, "name", "?"), str(exc)[:120])
            return None
        # THE VERBATIM READING, NOT THE PROPOSAL. `fields` carries the one command this pass
        # would RECOMMEND per role, normalised and ranked — `ruff check .` where the pipeline
        # says `uv run ruff check src tests`. Comparing a manifest against recommendations
        # reported three false gaps in EACH direction on the pilot at once.
        #
        # ONLY FROM A FILE THAT CARRIES THIS PROJECT'S CHECKS, the same discriminator #175
        # settled on: a pipeline that yields a test, a lint or a scanner is where the checks
        # live; one that yields none is a deploy, whatever it is called. Without it the client is
        # asked to declare `aws ssm send-command` as a validation.
        #
        # AND NOT `setup`, which the manifest declares in its own field. Reporting `npm ci` as an
        # undeclared validation sends somebody to fix a file that is already right.
        # ASKED OF THE COMMANDS THEMSELVES, not of the proposal's candidate lists. Those are
        # deduplicated by VALUE across the repository, so a command that appears in two pipelines
        # keeps only one occurrence — and the file it was dropped from then looks like a file
        # carrying no checks. Measured: `ci.yml`, which runs this project's ruff, mypy, bandit
        # and pytest, vanished from the comparison entirely, and its four declared validations
        # were then reported as "run by no pipeline any more".
        with_roles = set(proposal.ci_files_with_checks)
        out: dict[str, tuple[str, str]] = {}
        for candidate in proposal.ci_commands:
            evidence = (candidate.evidence or [None])[0]
            if not evidence or candidate.confidence != "observed":
                continue
            if evidence.path not in with_roles or candidate.why == "setup":
                continue
            where = f"{evidence.path}:{evidence.line or ''}".rstrip(":")
            out[f"{candidate.why or 'unnamed'} ({where})"] = (str(candidate.value), where)
        return out

    return Probes(
        docker_running=_docker_running,
        ci_checks=_ci_checks,
        harness_on_path=_on_path,
        manifest=lambda: load_manifest(project),
        box_gate=_box_gate,
        foreign_proofs=_foreign_proofs,
        api_budget=_api_budget_probe,
        open_proposal=_open_proposal,
        forge_reachable=_forge,
        board_columns=_columns,
        pickup_column=_pickup_column,
        requires_review=_requires_review,
        floor_enforced=floor_is_enforced,
        harness_kind=lambda: harness_kind(project, "executor"),
        product_link=lambda: _resolve_link(project),
        agent_credential=_agent_credential_probe,
    )
