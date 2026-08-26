"""ONE verdict on whether a ticket would actually run — composed from the checks that exist (#99).

THE MEASURED PROBLEM. Three commands, three notions of "ready", and on the same project at the
same instant they disagree:

    openfactory doctor <p>                 "OK — <p> can run a ticket"     (8 prerequisite reads)
    box_prove.gate_reason(p, …)     "the box has never been proven" (THIS is what holds pickup)
    openfactory conformance <p>            "NOT runnable — floor unmet"

The command we ask a client to run is the one that knows least, and a person cannot be expected to
run three and reconcile them. That reconciliation is the platform's job, and it is this module.

WHAT IS ACTUALLY NEW HERE, because "we already have three commands" is a fair objection:

  * **the pickup gate is consulted.** `gate_reason` is called on the poller's tick
    (`runtime/temporal/activities.py::scan_todo`) and by nothing a human can run. It is the single
    condition that decides whether a card in TO-DO is ever looked at, and no diagnostic asked it.
  * **a verdict that cannot contradict the factory.** `READY` is emitted only when nothing that
    holds work is holding it. Everything else is `MISSING <n>` or `HELD: <reason>`, and `exit_code`
    is non-zero for both — so "doctor says OK" and "a ticket would run" stop being two sentences.
  * **five checks nobody makes:** `roles`, `route`, `env_names`, `enabled`, `registry_parity`
    (`quality_floor` and `box_gate` are composed rather than re-implemented; see below).
  * **provenance on every line.** See the next section.

WHERE IT RAN IS PART OF THE ANSWER. `doctor` measures the machine typing the command: `docker
info`, `shutil.which`, `os.environ`. The registry, the toolbox and the proofs a JOB reads live
wherever the deployment runs. A verdict about a laptop, delivered with the authority of a verdict
about the factory, is how a client gets blamed for a Docker daemon that was never in question. So
every `Finding` carries `measured_on`, and `Readiness.header()` names both the value and the
registry file that answered.

`measured_on` has two values and they are MEASURED, not guessed:

    worker   this process reads the deployment's live registry
             (`/var/lib/openfactory/registry.yaml` —
             `registry.py::LIVE_REGISTRY_PATH`, set by `docker/worker.Dockerfile` and by both
             compose services)
    local    it does not, so this is somebody's machine and the environment below is theirs

The card asks for a third value, `panel`, and it is NOT derivable, so it is not invented: the panel
runs the SAME image as the worker (`infra/terraform/panel_apprunner.tf` points at
`aws_ecr_repository.worker`) and therefore inherits the same `OPENFACTORY_REGISTRY`. There is no
fact this
process can read that separates them. Printing a guess in the field whose entire purpose is
provenance would be the disease with a better interface — so the header prints the registry PATH
beside the label, and a reader can always see which file answered.

THREE STATES, NEVER TWO. `ok` alone cannot carry "I could not answer that here". A registry parity
check on a laptop with no `/var/lib/openfactory` is neither pass nor fail, and both readings are
damaging:
`ok` makes absence read as compliance (this codebase's most expensive defect class), `not ok` makes
every local run report a failure nobody can act on, which trains people to ignore the tool. So a
`Finding` also carries `answered`, an unanswered check renders as `----` and never as `ok`, and the
verdict line reports how many there were.

WHAT COUNTS AS A HOLD, measured at its call site rather than assumed — in the order the pipeline
hits them:

    enabled        `activities.py::scan_projects` skips a project with `enabled: false`. It is
                   never polled; nothing else in this report can matter
    box_gate       `activities.py::scan_todo` calls `gate_reason` and returns `[]` when it speaks
    quality_floor  `orchestrator/machine.py` holds the job (`ON_HOLD`) when `_enforce_floor()` is
                   on and `floor_reason` is not None — after pickup, before any agent pass

THE FLOOR IS ASKED ONCE, HERE, and the card's claim about it is out of date. #99 says "`floor` —
passa no próprio piso? (medido: `doctor` não pergunta)". Measured today against HEAD:
`doctor.diagnose` DOES ask it (`doctor._floor`, reached from `diagnose`). So the question is not
whether to add
it but which of two readers the report shows — and the answer has to be the one the VERDICT used,
or the report can contradict itself. It did: see `assess`, where the first version of this module
printed READY over an unmet floor because it kept `doctor`'s finding and computed the verdict from
its own. `doctor`'s copy is now dropped, and what is emitted in its place says what `doctor` cannot
— that an unmet floor is a HOLD, not a paragraph of advice.

WHY `box_gate` AND `box_proof` ARE TWO CHECKS. On a cloud deployment `default_sandbox()`
returns the remote box it DECLARES (`OPENFACTORY_SANDBOX=fargate` — nothing is inferred from a
cluster variable), and `gate_reason` returns None for any box whose
`box_traits().honours_image` is False. So the gate is INERT there: it cannot hold pickup, and a
report that only asked the gate would print a confident `READY` over a project whose box has never
been proven. Trading three honest disagreements for one confident falsehood is worse than the state
this replaces. So `box_gate` answers *is pickup held right now* (and says out loud when it is
structurally unable to hold anything), and `box_proof` answers *does a valid proof exist* — which
on a fargate deployment is the only one of the two that can speak.

That case yields `MISSING 1`, not `HELD`, and the word is deliberate: on fargate nothing IS holding
pickup — a ticket would run, in a box nobody proved. `HELD: <reason>` names a live block, and
inventing one to look strict would be a failure wearing an answer's clothes, which is the shape
this whole module exists to remove. What the card actually requires is that such a project never
reads `READY` and never exits 0, and both hold.

PROBES ARE INJECTED, exactly as in `doctor.py` and `box_prove.py`, so every branch is reachable in
a test without Docker, a network, a registry or a GitHub App. A readiness check that could only be
exercised on a healthy deployment is a readiness check nobody can show reports illness.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

log = logging.getLogger("openfactory.onboarding.readiness")

#: This process reads the deployment's live registry — the same file a job reads.
WORKER = "worker"
#: It does not. Every environmental fact below is this machine's, not the factory's.
LOCAL = "local"

#: The roles whose instructions the platform ships and reads at run time.
#:
#: A LITERAL ON PURPOSE, AND THIS IS THE WHOLE POINT OF THE CHECK. The obvious implementation is
#: `glob("org_defaults/roles/*.md")` — and the defect being hunted is precisely that those files do
#: not reach an installed wheel, so the glob would return nothing and the check would report "0
#: roles, all present". Absence reading as compliance, in the guard written to catch absence.
#:
#: Sourced from the call sites, all of which pass a literal: `adapters/agent/claude_code.py`
#: (planner, sizer, coordinator, techlead, recovery, executor), `adapters/agent/techlead.py`
#: (sizer, coordinator, techlead) and `product/role.py` (product). A test walks the tree and
#: asserts this tuple still covers every literal any of them passes, so it cannot drift quietly.
#:
#: SHIPPED PROMPTS ONLY, on purpose. A role installed as an add-on (`role.<name>` entry point)
#: carries its prompt in its own `RoleSpec`, which refuses an empty one at construction — so an
#: add-on's missing instructions are refused where they are declared and the role never resolves,
#: rather than surfacing here as "1 of 8 role prompts is empty" against a remedy about OUR files.
#: `known_roles()` is the list of roles; this is the list of files.
ROLE_PROMPTS: tuple[str, ...] = (
    "coordinator", "executor", "planner", "product", "recovery", "sizer", "techlead",
)

#: Registry keys whose value is EXPECTED to differ between a laptop and the deployment, so a
#: difference in one of them alone is not a parity failure. Exactly one member, and it is a
#: measurement rather than a preference — see `_registry_parity`, which prints the two values on
#: either branch so nothing is hidden by the exemption.
_EXPECTED_TO_DIFFER: frozenset[str] = frozenset({"repo_path"})


class RegistryUnreachable(RuntimeError):
    """The worker's registry could not be READ from here — which is not "the project is absent".

    The third state, given its own channel for the reason `doctor.BoardUnreadable` spells out at
    length: two values cannot carry three meanings, and collapsing "could not look" into either of
    the other two is how a diagnostic reports a permissions failure as a clean bill of health. Here
    the collapse would be worse in both directions — into "absent" it accuses a correctly
    configured deployment of not knowing its own project; into "present" it certifies a registry
    nobody read."""


@dataclass
class Finding:
    """`doctor.Finding`'s shape, plus the two fields a composed verdict cannot do without."""

    check: str
    ok: bool
    message: str
    #: What to do about it. REQUIRED whenever `ok` is False — and made structurally required by
    #: `_fail()` below, which is the only way this module builds a failing finding.
    remedy: str = ""
    #: Which machine this answered for: `worker` or `local`. A finding with no provenance is a
    #: finding about the wrong computer, told with a straight face.
    measured_on: str = ""
    #: Whether the question could be answered AT ALL here.
    #:
    #: False is NOT a failure and NOT a pass: it is "no answer exists on this machine". It never
    #: counts toward `MISSING`, it renders as `----` rather than `ok`, and the verdict line carries
    #: the count so a green report can never quietly be a report that asked nothing.
    #:
    #: A check that RAISED is a different thing and stays `answered=True, ok=False` with a remedy —
    #: following `doctor._guarded`: a broken check is a defect to report, not an absence.
    answered: bool = True


def _ok(check: str, message: str, *, on: str) -> Finding:
    return Finding(check=check, ok=True, message=message, measured_on=on)


def _fail(check: str, message: str, remedy: str, *, on: str) -> Finding:
    """A failing finding, and `remedy` is positional and required.

    The rule "a finding with no remedy is a symptom handed to the one person who does not yet know
    the system" is written in two modules and enforced by neither. Here it is enforced by the only
    constructor this module uses: you cannot build a failure without saying what to do about it,
    because the signature will not let you."""
    return Finding(check=check, ok=False, message=message, remedy=remedy, measured_on=on)


def _unanswered(check: str, message: str, *, on: str) -> Finding:
    """No answer exists here. `ok` is True because it blocks nothing; `answered` is False so it can
    never be counted, rendered or read as a pass."""
    return Finding(check=check, ok=True, message=message, measured_on=on, answered=False)


@dataclass
class Report:
    """Everything measured, plus the reasons work is being held.

    `verdict` is a PROPERTY rather than a stored string on purpose: a verdict computed once and
    carried alongside the findings can drift from them, and the one thing this object exists to
    guarantee is that its sentence and its evidence are the same fact."""

    project: str
    measured_on: str
    registry_path: str
    findings: list[Finding] = field(default_factory=list)
    #: Why work is being held right now, most upstream first. Each entry is a *live block*, phrased
    #: as the blocking component phrases it — `gate_reason`'s own string, verbatim, where it is the
    #: gate.
    holds: list[str] = field(default_factory=list)

    @property
    def missing(self) -> list[Finding]:
        """Answered checks that are not met. An unanswered check is never one of these."""
        return [f for f in self.findings if f.answered and not f.ok]

    @property
    def unanswered(self) -> list[Finding]:
        return [f for f in self.findings if not f.answered]

    @property
    def verdict(self) -> str:
        """`READY` | `MISSING <n>` | `HELD: <reason>` — one sentence, in that precedence.

        HELD outranks MISSING because they are different questions and only one of them is urgent:
        a held project has work sitting still RIGHT NOW, whatever else is also unmet."""
        if self.holds:
            return f"HELD: {self.holds[0]}"
        count = len(self.missing)
        return "READY" if count == 0 else f"MISSING {count}"

    @property
    def ready(self) -> bool:
        return self.verdict == "READY"

    @property
    def exit_code(self) -> int:
        """0 only when nothing is missing and nothing is held.

        The point of the card: a command that printed OK while the poller refused to pick anything
        up is how an operator spends an afternoon looking at the wrong thing."""
        return 0 if self.ready else 1

    def header(self) -> list[str]:
        """Provenance FIRST, before any finding, because it changes what every one of them means."""
        lines = [f"{self.project} — measured on: {self.measured_on} ({self.registry_path})"]
        if self.measured_on != WORKER:
            lines.append(
                "  this is NOT the machine that runs your tickets: the docker daemon, the PATH, "
                "the environment variables and the proof directory read below are this one's."
            )
        return lines

    def render(self) -> list[str]:
        """The whole report as lines, ready for `typer.echo`.

        THREE MARKERS, NOT TWO. `----` is what an unanswered check gets, and it is deliberately not
        a shade of `ok`: the reader has to be unable to mistake "nothing here could answer that"
        for "that is fine"."""
        lines = [*self.header(), ""]
        for f in self.findings:
            marker = "ok  " if f.ok else "FAIL"
            if not f.answered:
                marker = "----"
            body = f.message.splitlines() or [""]
            lines.append(f"  {marker}  {f.check:<16} {body[0]}")
            lines.extend(f"  {'':<6}{'':<16}  {extra}" for extra in body[1:])
            if not f.ok and f.remedy:
                lines.append(f"  {'':<6}{'':<16}→ {f.remedy}")
        lines.append("")
        note = ""
        if self.unanswered:
            note = (f" ({len(self.unanswered)} check(s) could not be answered on this machine — "
                    f"they are not counted either way)")
        lines.append(self.verdict + note)
        for extra in self.holds[1:]:
            lines.append(f"  also holding: {extra}")
        return lines


@dataclass
class Probes:
    """Everything `assess` needs to know about the world, as callables it can be handed."""

    project_name: str
    #: `worker` or `local` — see the module docstring. A probe, not a read, because a test has to
    #: be able to exercise both without moving the file the answer is derived from.
    measured_on: Callable[[], str]
    #: The registry file that answered, printed beside the label so no reader is ever left
    #: guessing which of several registries a laptop happens to have.
    registry_path: Callable[[], str]
    #: `doctor.diagnose(doctor.probes_for(project))` — composed whole, never re-implemented.
    doctor_report: Callable[[], object]
    #: Which box this deployment runs jobs in (`runtime/temporal/io.py::default_sandbox`).
    sandbox: Callable[[], str]
    #: Whether that box is gated by a proof at all (`box_traits(kind).honours_image`). False makes
    #: `gate_reason` structurally incapable of holding pickup, which is a fact about the report,
    #: not a detail — see the module docstring.
    box_honours_image: Callable[[str], bool]
    #: `box_prove.gate_reason(project, sandbox=…)` — the string the poller acts on, or None.
    gate_reason: Callable[[], str | None]
    #: `box_prove.load(name)` — the recorded proof, or None when there is none.
    proof: Callable[[], object | None]
    #: Where a proof would be recorded, for a remedy that names the actual path.
    proof_dir: Callable[[], str]
    #: `policy.conformance.floor_reason(manifest)` — the same question the runner asks with money
    #: on the line.
    floor_reason: Callable[[], str | None]
    #: `doctor.floor_is_enforced` — whether an unmet floor is a hold or only advice. Constant True
    #: since `OPENFACTORY_ENFORCE_FLOOR` was removed; still a probe, because reporting one as the
    #: other is
    #: its own silent stall and a test has to be able to show this module saying either.
    floor_enforced: Callable[[], bool]
    #: `adapters.agent.roles.role_prompt`.
    role_prompt: Callable[[str], str]
    #: `routes.declared_route(project)` — what the REGISTRY determines. `""` = it cannot say.
    declared_route: Callable[[], str]
    #: `routes.resolve_route(project)` — what THIS PROCESS's environment resolves. An `AuthRoute`.
    resolved_route: Callable[[], object]
    #: `adapters.agent.registry.harness_kind(project, "executor")`. Not a route — the thing that
    #: tells `_route` whether the two route functions are even speaking the same vocabulary. See
    #: `_route`, where an `AuthRoute` whose name IS this string is `resolve_route` falling through
    #: rather than naming a provider.
    harness_kind: Callable[[], str]
    #: `project.box.env` — the NAMES this project asks the box to receive.
    box_env_names: Callable[[], list[str]]
    #: The environment those names are checked against. A probe rather than `os.environ` so a test
    #: can present an environment without mutating the process's — and so the report can never
    #: silently be about a different one than `measured_on` claims.
    environ: Callable[[], Mapping[str, str]]
    #: `project.enabled`. False and the poller never looks at this project at all.
    enabled: Callable[[], bool]
    #: This project as the registry we were handed holds it, and as the WORKER's registry holds it.
    #: The worker side returns None when the file was read and the project is not in it, and raises
    #: `RegistryUnreachable` when the file could not be read — see that class.
    registry_entry: Callable[[], dict]
    worker_registry_entry: Callable[[], dict | None]
    #: Whether this project has the product role turned on (`product:` present and `enabled`).
    #: CONFIG ONLY, no network — `doctor`'s `product_link` already pays for the checkout that says
    #: whether the corpus agrees, and asking twice would clone a client's documentation repo twice
    #: to answer a question about a registry field.
    product_enabled: Callable[[], bool]
    #: `product.admins` — who may make the product role WRITE. Empty means nobody, and nothing
    #: else in this report or in `doctor` reads it.
    product_admins: Callable[[], list[str]]


def _guarded(check: str, on: str, fn: Callable[[], tuple[Finding, str]]) -> tuple[Finding, str]:
    """Run one check without letting it become the ninth broken thing (`doctor._guarded`'s rule).

    This is what somebody runs when nothing works. A traceback from the diagnostic tells them
    nothing about their setup and quite a lot about ours."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — a failed check is a finding, not a crash
        return _fail(check, f"could not check {check}: {exc}",
                     "this is a fault in the check itself, not necessarily in your setup — run "
                     "the underlying command by hand to see the raw error",
                     on=on), ""


def assess(p: Probes) -> Report:
    """Every check, every time, then one verdict.

    Stopping at the first failure turns one session into six — the same reason `doctor.diagnose`
    runs all of its own. The order below is the order the pipeline hits these facts, so the first
    hold reported is the most upstream one and fixing it is never wasted.

    THE DE-DUPLICATION RUNS THE OTHER WAY ROUND, AND THAT IS A BUG FIX, NOT A PREFERENCE. The first
    version of this ran `doctor` first and dropped its OWN `quality_floor` finding whenever
    `doctor`'s report already carried one. A test handed it the world where `doctor` says the floor
    is fine and `floor_reason` says it is not, and the report printed **READY** — because the
    surviving finding was `doctor`'s pass while the verdict logic had asked `floor_reason` and got
    a string. The two halves of one report disagreeing, with the confident half winning: exactly
    the failure this module was written to remove, reproduced inside it.

    So the answer this report USES is the answer this report SHOWS. The checks below run first, and
    `doctor`'s findings are appended only for the names they did not answer. `Report.verdict` is a
    property over these same findings for the same reason — a verdict computed from one source and
    displayed beside another is a contradiction waiting for a world that separates them."""
    on = p.measured_on()
    holds: list[str] = []

    # THIS LIST'S ORDER IS THE PIPELINE'S ORDER, AND THE FIRST HOLD IS THE HEADLINE. It was not:
    # `quality_floor` sat first, so a DISABLED project whose floor was also unmet and enforced
    # reported `HELD: the quality floor is unmet … so every ticket this project picks up is held
    # for a human` — a sentence about tickets it will never pick up, because `scan_projects` skips
    # it before any board is read. The most upstream fact has to win, or the headline sends
    # somebody to add a `security:` gate for a project nothing will ever look at.
    #
    # `test_the_most_upstream_hold_is_the_one_reported` could not see it: its world has a met
    # floor, so the misordered entry never produced a hold to outrank the others. The regression
    # test for this is `test_a_disabled_project_reports_disabled_before_an_enforced_floor`, which
    # turns BOTH dials at once — the positive twin the ordering guard was missing.
    checks: list[tuple[str, Callable[[], tuple[Finding, str]]]] = [
        ("enabled", lambda: _enabled(p, on)),
        ("box_gate", lambda: _box_gate(p, on)),
        ("box_proof", lambda: _box_proof(p, on)),
        # `quality_floor` is answered here rather than taken from `doctor` because only this side
        # knows what it MEANS: an unmet floor is a HOLD, and `doctor` has no way to express one —
        # it reports findings and remedies, not blockers. It comes AFTER the two above because the
        # floor is enforced in `orchestrator/machine.py` — after pickup, which the two above decide.
        ("quality_floor", lambda: _floor(p, on)),
        ("roles", lambda: _roles(p, on)),
        ("route", lambda: _route(p, on)),
        ("env_names", lambda: _env_names(p, on)),
        ("registry_parity", lambda: _registry_parity(p, on)),
        # LAST, AND IT NEVER HOLDS. Everything above decides whether a ticket moves; this decides
        # whether the client can ask for one. Both belong in the round — setup is setup — but a
        # product role nobody can reach does not stop the floor, and ordering it among the holds
        # would let it outrank a fact that does.
        ("product_role", lambda: _product_role(p, on)),
    ]
    mine: list[Finding] = []
    for name, fn in checks:
        finding, hold = _guarded(name, on, fn)
        mine.append(finding)
        if hold:
            holds.append(hold)

    answered_here = {f.check for f in mine}
    # `doctor`'s list FIRST in the rendering, because it is the one a reader already knows by
    # heart — but only the parts of it nothing above has already answered.
    findings = [f for f in _from_doctor(p, on) if f.check not in answered_here] + mine

    report = Report(project=p.project_name, measured_on=on, registry_path=p.registry_path(),
                    findings=findings, holds=holds)
    _self_check(report)
    return report


def _self_check(report: Report) -> None:
    """Assert the invariants this report's own readers depend on, and say so rather than crash.

    VERIFY YOUR VERIFIER. Two properties make every sentence above meaningful, and both are the
    kind that break silently: a failure with no remedy is a symptom handed to a stranger, and an
    unanswered check that is also `not ok` would be counted as MISSING — which is the "could not
    read" collapsing into "failed" that this module exists to stop doing. Tests assert both; this
    is the runtime twin, because the tests only see the cases somebody thought to write."""
    for f in report.findings:
        if not f.ok and not f.remedy:
            log.warning("OPENFACTORY_READINESS_NO_REMEDY %s: check %r failed with no remedy — the "
                        "reader "
                        "is being handed a symptom", report.project, f.check)
        if not f.answered and not f.ok:
            log.warning("OPENFACTORY_READINESS_UNANSWERED_FAIL %s: check %r is marked unanswered "
                        "AND "
                        "failing; an absence is being counted as a failure", report.project,
                        f.check)
        if not f.measured_on:
            log.warning("OPENFACTORY_READINESS_NO_PROVENANCE %s: check %r carries no `measured_on` "
                        "— the "
                        "reader cannot tell which machine it answered for", report.project,
                        f.check)


def _product_role(p: Probes, on: str) -> tuple[Finding, str]:
    """Is the client's half of this deployment standing — and can anyone reach it?

    NOT A SECOND OPINION ON `product_link`. `doctor` resolves the corpus: does the documentation
    repo exist, does it describe this product, does it count this source repo as a member. This
    answers the two questions that resolution never asks, and that nothing else in either report
    asks either — `admins` appears nowhere in `config.py` or `doctor.py`, so an enabled product
    role whose approver list is empty passes every check this platform has and fails at the client's
    first request.

    NEITHER ARM IS A HOLD. The floor keeps running: tickets are picked up, agents work, releases
    happen. What is broken is the client's ability to ASK for any of it, which is a different
    surface with a different remedy — and reporting it as a hold would send an operator hunting for
    a stalled queue that is moving perfectly well.

    THE ROUND OWNS THIS, which is why it belongs here rather than in `doctor`: *"a rodada já
    configura o PO sim, querer usar é outra coisa — o cliente pode querer criar seus tickets, mas
    setup é setup, sai com tudo."* Configuring and adopting are different questions, so a project
    with no product role at all is reported as fine — nobody enabled it, and that is a choice, not
    an unfinished install."""
    if not p.product_enabled():
        return _ok("product_role", "no product role is configured for this project", on=on), ""

    admins = p.product_admins() or []
    if not admins:
        return _fail(
            "product_role",
            "the product role is on and its approver list is empty, so every write it is asked "
            "for — a requirement, an issue, a release — is refused. Reading is not gated, which is "
            "what makes this expensive: the client can talk to it, and finds out at the moment "
            "they try to agree to something",
            f"list the people who may approve in `product.admins` on {p.project_name}'s registry "
            f"entry, spelled the way the identity provider spells them, then run this again. An "
            f"empty list is nobody, never everybody", on=on), ""

    env = p.environ()

    def _set(*names: str) -> bool:
        return any(str(env.get(n, "") or "").strip() for n in names)

    # THE DOOR'S OWN VARIABLES, imported rather than spelled, because a report that checked
    # `OPENFACTORY_PRODUCT_TOKEN*` by literal would keep saying "issued" for a day after somebody
    # renamed
    # the variable the gate actually reads.
    from openfactory.identity.local import (
        PEOPLE_ENV,
        PRODUCT_PEOPLE_ENV,
        PRODUCT_SHARED_ENV,
        SHARED_ENV,
    )

    has_product = _set(PRODUCT_PEOPLE_ENV, PRODUCT_SHARED_ENV)
    # `open_to_everyone`'s condition, asked of THIS report's environment. When nothing at all is
    # configured the deployment is in its local-development default and every request is permitted
    # — there is no credential to issue, so demanding one would be a failure about a world where
    # the client already has access.
    door_is_closed = has_product or _set(PEOPLE_ENV, SHARED_ENV)
    if door_is_closed and not has_product:
        return _fail(
            "product_role",
            "the product role is configured and no product credential is issued, so the only way "
            "in is a floor credential — which opens the whole panel. There is nothing to hand the "
            "client that lets them reach their own surface and nothing else",
            f"set `{PRODUCT_PEOPLE_ENV}` where the deployment runs (`id:token` per person, comma "
            f"separated) and give the client theirs; `{PRODUCT_SHARED_ENV}` is the one-password "
            f"version and records no name. Either one scopes its holder to `/product/"
            f"{p.project_name}` and refuses the floor", on=on), ""

    named = ", ".join(str(a) for a in admins[:3])
    more = f" (+{len(admins) - 3})" if len(admins) > 3 else ""
    credential = "a product credential is issued" if has_product else (
        "no credential is configured at all, so the panel is open to everyone — the local "
        "development default")
    return _ok("product_role",
               f"the product role is on, {len(admins)} approver(s) may write ({named}{more}), and "
               f"{credential}", on=on), ""


# ── composed: what already exists, run whole ────────────────────────────────────────────────────

def _from_doctor(p: Probes, on: str) -> list[Finding]:
    """`doctor`'s findings, re-stamped with provenance. Never re-implemented, never re-worded.

    The remedy is carried VERBATIM, including when it is empty. Substituting a generic line for a
    missing one would make the "every failure has a remedy" guard pass by construction — a guard
    that cannot go red is decoration, and this one is protecting the sentence a stranger reads."""
    try:
        report = p.doctor_report()
    except Exception as exc:  # noqa: BLE001 — a broken composition is a finding, not a crash
        return [_fail("doctor", f"the prerequisite checks could not be run: {exc}",
                      "run `openfactory doctor " + p.project_name
                      + "` on its own to see the raw error",
                      on=on)]
    out: list[Finding] = []
    for f in getattr(report, "findings", []) or []:
        out.append(Finding(check=getattr(f, "check", "?"), ok=bool(getattr(f, "ok", False)),
                           message=str(getattr(f, "message", "")),
                           remedy=str(getattr(f, "remedy", "")), measured_on=on))
    return out


def _floor(p: Probes, on: str) -> tuple[Finding, str]:
    """Does this project pass its own quality floor — and is that a HOLD?

    It is: the floor refuses, always (`orchestrator/machine.py`). This used to be two sentences
    from one fact, because `OPENFACTORY_ENFORCE_FLOOR` decided which — jobs running with the gate
    missing,
    or every ticket held before any agent runs — and reporting either as the other is a stall of
    its own. The variable is gone, so the arm below is one answer.

    ONLY THIS MODULE CALLS IT A HOLD. `doctor` reports the same fact as a failing finding with a
    remedy; this composes the readiness verdict, and a verdict that did not name the blocker would
    send a client to a screen that says everything is fine and a queue that never moves."""
    reason = p.floor_reason()
    if reason is None:
        return _ok("quality_floor", "the manifest declares every validation the platform's floor "
                                    "requires", on=on), ""
    if p.floor_enforced():
        hold = ("the quality floor is unmet, so every ticket this project picks up is held for a "
                "human before any agent runs")
        return _fail("quality_floor", reason,
                     "this is not advice: add the gate the message names — `advisory: true` is "
                     "enough, it never blocks a merge — and the next tick proceeds", on=on), hold
    return _fail("quality_floor", reason,
                 "nothing is being refused on this deployment, so jobs still RUN with that gate "
                 "missing, and a run whose gates are empty reports green having proven nothing. "
                 "Add the gate the message names; `advisory: true` is enough, so it never blocks "
                 "a merge", on=on), ""


# ── the checks nobody makes today ───────────────────────────────────────────────────────────────

def _enabled(p: Probes, on: str) -> tuple[Finding, str]:
    """The most upstream hold there is, and the least visible.

    `activities.py::scan_projects` skips a project whose `enabled` is False before anything else
    happens — no board read, no gate, no ticket (`if not p.enabled: continue`, inside that
    function). And `ProjectRegistry.set_enabled` exists precisely
    so a freshly onboarded project stays off until its board is prioritised, which means the
    ONBOARDING case is the likeliest one to be sitting in this state. Everything else in this
    report can be green while nothing will ever happen.

    THE REMEDY NAMES A COMMAND THAT EXISTS, and the first draft did not: it said `openfactory
    project
    enable <name>`, which is not a command — `project` has `add`, `list`, `remove`, `init` and
    `forget-conversations`, and nothing else. Printing an unexecutable remedy is precisely the
    defect #99 §3 opens with (`floor_reason` recommending `stack: security-oss`, which the schema
    rejects), committed inside the module written to end it. What does exist is the `enable` action
    (`actions/catalog.py`, `required=("project",)`), reachable from the CLI as `openfactory act
    enable`
    and from the panel as `POST /api/projects/<name>/enabled`."""
    if p.enabled():
        return _ok("enabled", "the poller includes this project", on=on), ""
    hold = ("the project is disabled in the registry, so the poller skips it entirely — no board "
            "is read and no card is ever picked up")
    return _fail("enabled", hold,
                 f"`openfactory act enable -p {p.project_name}` where the deployment runs (the "
                 f"panel's toggle does the same thing), or set `enabled: true` on its registry "
                 f"entry. "
                 f"Nothing else in this report can make work start until then", on=on), hold


def _box_gate(p: Probes, on: str) -> tuple[Finding, str]:
    """Is `gate_reason` holding pickup RIGHT NOW — and CAN it hold anything at all?

    The second half is what keeps this honest. `gate_reason` returns None for any box whose
    `box_traits().honours_image` is False, and `default_sandbox()` answers the remote box a cloud
    deployment declares (`OPENFACTORY_SANDBOX=fargate`). A check that reported
    `ok`
    there would be reporting the ABSENCE of a gate as a passing gate: vacuously true, confidently
    printed, and worse than the disagreement it replaces. So the inert case says it is inert, in
    those words, and `box_proof` below carries the question instead."""
    sandbox = p.sandbox()
    if not p.box_honours_image(sandbox):
        return _ok("box_gate",
                   f"not gated: a {sandbox!r} box does not honour a per-project image "
                   f"(box_traits.honours_image is False), so `gate_reason` returns None for this "
                   f"project whatever the proof says — see `box_proof` below, which is the only "
                   f"one of the two that can answer here", on=on), ""
    reason = p.gate_reason()
    if reason is None:
        return _ok("box_gate", f"pickup is not held: the box proof is current for this "
                               f"{sandbox!r} box", on=on), ""
    # THE GATE'S OWN WORDS, VERBATIM, and the same string the poller announces. Paraphrasing it
    # would give an operator two different sentences for one condition and make the announcement
    # in the channel and the report on their screen look like two problems.
    return _fail("box_gate", reason,
                 f"this is what `scan_todo` acts on: while it says this, every card in TO-DO is "
                 f"left where it is. Run `openfactory box prove {p.project_name}` where the "
                 f"deployment runs", on=on), reason


def _box_proof(p: Probes, on: str) -> tuple[Finding, str]:
    """Does a recorded proof exist at all — asked even where the gate cannot ask it.

    NOT A DUPLICATE OF `box_gate`, and the difference is the whole reason this module exists. On a
    `container` deployment the two agree and the second line is a confirmation. On `fargate` the
    gate is inert and this is the ONLY line that can say the box has never been proven — which is
    exactly the deployment a client runs on. Never a hold: on a box that is not gated, nothing is
    holding pickup, and saying `HELD` to look strict would be a false statement in the other
    direction."""
    proof = p.proof()
    gated = p.box_honours_image(p.sandbox())
    where = p.proof_dir()
    if proof is None:
        note = "" if gated else (
            " — and nothing is holding pickup, because this deployment's box is not gated by a "
            "proof, so a ticket WOULD run in a box nobody has proven"
        )
        # "no READABLE record", not "no record". `box_prove.load` returns None for a file that is
        # not there AND for one that is there and will not parse (it logs and treats it as absent).
        # Asserting the file does not exist is a claim this module cannot see, and the reader who
        # runs `ls` and finds it stops believing the rest of the report.
        return _fail("box_proof",
                     f"the box has never been proven: no readable record at "
                     f"{where}/{p.project_name}.json"
                     + note,
                     f"run `openfactory box prove {p.project_name}` ON THE DEPLOYMENT — the "
                     f"proof is recorded beside the registry, so one taken on a laptop is not "
                     f"the one the poller reads", on=on), ""
    if not getattr(proof, "ok", False):
        return _fail("box_proof",
                     f"the last box proof FAILED (recorded {getattr(proof, 'at', '?')} on "
                     f"{getattr(proof, 'image', '?')})",
                     f"run `openfactory box prove {p.project_name}` and fix the FAIL lines it "
                     f"prints — they name the image, the toolbox, your `setup:` or your gates",
                     on=on), ""
    return _ok("box_proof",
               f"proven {getattr(proof, 'at', '?')} on {getattr(proof, 'image', '?')}", on=on), ""


def _roles(p: Probes, on: str) -> tuple[Finding, str]:
    """Does `role_prompt()` return "" for any role — a broken install, silent by design.

    `roles.py` degrades to "" so a missing file does not crash a job, and that degrade is right.
    What it produces is an agent running with none of the platform's instructions in it, writing
    code that looks like an agent's code because it IS an agent's code, just without the opinion
    anyone was paying for.

    IT ASSERTS THE PROPERTY, IT DOES NOT DIAGNOSE A KNOWN BUG — and the first draft of this
    docstring got that wrong in a way worth recording. It stated as fact that `pyproject.toml`'s
    one-level glob over `org_defaults/` drops the seven role prompts from the wheel. That is #99's
    §2, and it has since been MEASURED AND REFUSED: `pyproject.toml` now carries
    `org_defaults/**/*.md`, its comment records that building the wheel BOTH ways shipped all seven
    either way (`include-package-data` defaults to true under pyproject.toml), and
    `tests/test_the_wheel_ships_what_the_platform_needs.py` builds a wheel and reads inside it.
    Repeating a disproved finding inside a diagnostic is how a stranger is sent to fix a file that
    was never wrong — the same damage as a missing check, with more confidence.

    So this asserts what it can see and nothing more: `role_prompt(r)` returns text, for each of
    the seven, ON THIS INSTALLATION. That is the runtime twin of the wheel test rather than a
    duplicate of it — the wheel test proves what a build ships, and this proves what the process
    about to run a job actually reads, which is a different fact whenever a `PYTHONPATH`, a
    WORKDIR, a stale editable install or a half-copied volume sits between the two."""
    empty = [role for role in ROLE_PROMPTS if not (p.role_prompt(role) or "").strip()]
    if not empty:
        return _ok("roles", f"all {len(ROLE_PROMPTS)} role prompts load on this installation "
                            f"({on})", on=on), ""
    return _fail("roles",
                 f"{len(empty)} of {len(ROLE_PROMPTS)} role prompts are EMPTY on this "
                 f"installation ({', '.join(empty)}) — those roles run on the caller's generic "
                 f"prompt alone, with none of the platform's instructions in them, and nothing "
                 f"else reports it",
                 "the files ship with the package (`openfactory/org_defaults/roles/*.md`), so an "
                 "empty "
                 "one means this INSTALLATION is incomplete rather than misconfigured: check what "
                 "`python -c \"import openfactory, pathlib; "
                 "print(pathlib.Path(openfactory.__file__).parent)\"` "
                 "prints and whether that tree carries the files — a wheel test cannot see a "
                 "stale editable install or a half-copied volume, and this is where they show up",
                 on=on), ""


def _route(p: Probes, on: str) -> tuple[Finding, str]:
    """Do `declared_route` and `resolve_route` agree — the registry's answer and the environment's?

    They answer the same question from two places that are allowed to differ, and when they do the
    consequence is exact: `resolve_route` reads THIS PROCESS's variables, `declared_route` reads
    what `box.env` NAMES, and `container.py::_passthrough_env` carries only the named ones into the
    box. So a worker correctly configured for Bedrock, whose project does not name
    `CLAUDE_CODE_USE_BEDROCK` in `box.env`, resolves `bedrock` here and hands the harness nothing
    in there. Everything looks configured; the first agent call is the first symptom.

    THE REMEDY NAMES BOTH OPTIONS, AND THAT IS A CORRECTION MADE BY A REAL RUN. The first version
    printed `AuthRoute.remedy` alone, on the grounds that the route already knows its own variables
    and a second copy of that table would go stale. Run against `fx-dsk-flows` (real .NET 8 repo,
    `box.env: [CLAUDE_CODE_USE_BEDROCK, AWS_REGION, NUGET_FEED_TOKEN]`) it printed:

        → the box passes these two through by default; if neither is set on the worker the
          harness has no credential at all

    which is the ANTHROPIC route's remedy — correct advice about the route this environment
    happened to resolve, and useless to somebody whose registry declares Bedrock. The disagreement
    has two directions and only one of them is the route's own fault, so the remedy carries the two
    executable options (the house rule: a human decides, the factory acts) and keeps the route's
    words for the half they belong to.

    AND THE TWO SIDES MUST BE SPEAKING THE SAME VOCABULARY, which for one whole class of
    deployments they are not. `resolve_route` names a PROVIDER only for `claude_code`
    (declared/gateway/bedrock/vertex/anthropic) and `opencode` (`opencode/<provider>`); its last
    branch is `AuthRoute(name=kind, …)` — the HARNESS's own name. `declared_route`, meanwhile, has
    no such branch: for anything that is not `opencode` it concludes `anthropic` from what
    `box.env` names. So a project carrying the registry's own documented example — `harness: codex`
    (`contracts/project.py`) — made this print, on every machine, for ever:

        FAIL route  the registry determines the 'anthropic' route for this project, and this
                    environment (local) resolves 'codex' — … the credentials this process holds
                    for 'codex' do not arrive where the harness runs

    Measured, on a real repository with `harness: codex`. Every clause of it is false: `codex` is
    not a route, nothing was misconfigured, and the remedy it printed was the fallback's
    not-a-remedy about `OPENFACTORY_HARNESS_ENDPOINT`. A confident FAIL over a correct deployment is
    worse
    than no check at all — it is the `unknown` tier's whole reason for existing, spent.

    The discriminator is exact rather than a table that will drift: `resolve_route` returns the
    harness kind as the route name in precisely the cases where it could not name a provider
    (`claude_code` never yields "claude_code"; `opencode` yields bare "opencode" only for a model
    prefix it does not recognise). So `name == harness_kind` IS "this environment has no provider
    to compare", and that is the third state, not a failure."""
    resolved = p.resolved_route()
    name = str(getattr(resolved, "name", "") or "")
    declared = (p.declared_route() or "").strip()

    if name == "declared":
        # `OPENFACTORY_HARNESS_ENDPOINT` is the operator's escape hatch for a route no table can
        # name.
        # There is nothing to disagree with, and pretending otherwise would refuse a deployment
        # that is configured exactly as documented.
        return _ok("route",
                   f"OPENFACTORY_HARNESS_ENDPOINT names the endpoint explicitly "
                   f"({getattr(resolved, 'endpoint', '') or 'unset'}), so no route is inferred",
                   on=on), ""
    if not declared:
        return _unanswered("route",
                           f"the registry cannot say which route this project takes, so it cannot "
                           f"be compared with what this environment resolves ({name or 'unknown'})"
                           f" — for `opencode` the provider is `model:`'s prefix, and an "
                           f"unrecognised or missing prefix leaves it unknown", on=on), ""
    kind = (p.harness_kind() or "").strip()
    if kind and name == kind:
        # See the docstring: `resolve_route` fell through to its last branch and named the HARNESS,
        # not a provider. Comparing that with `declared_route`'s provider name is a category error,
        # and the answer it produced was a permanent FAIL on a correctly configured deployment.
        return _unanswered("route",
                           f"this environment cannot name a provider route for harness {kind!r} — "
                           f"`resolve_route` knows the providers of `claude_code` and `opencode` "
                           f"and falls through to the harness's own name for anything else, so "
                           f"there is nothing to compare with the registry's {declared!r}. Set "
                           f"OPENFACTORY_HARNESS_ENDPOINT to the host that harness talks to and "
                           f"this "
                           f"becomes answerable (and reachability provable) instead of assumed",
                           on=on), ""
    # `opencode/bedrock` and `bedrock` are the same provider reached by two harnesses; the prefix
    # is the harness, not the route, and comparing it would report a disagreement that is not one.
    normalised = name.split("/", 1)[-1]
    if normalised == declared:
        return _ok("route", f"the registry and this environment agree on the {declared!r} route",
                   on=on), ""
    own = str(getattr(resolved, "remedy", "") or "")
    return _fail("route",
                 f"the registry determines the {declared!r} route for this project, and this "
                 f"environment ({on}) resolves {name!r} — only what `box.env` NAMES reaches the "
                 f"box, so the credentials this process holds for {name!r} do not arrive where "
                 f"the harness runs",
                 f"one of two things is true and only a person can say which. Either this "
                 f"environment is right and `box.env` has to name what {name!r} needs — "
                 + (own or "name that route's variables there") +
                 f" — or the registry is right and the {declared!r} route's variables have to be "
                 f"set where the WORKER runs, in which case `env_names` below names the ones that "
                 f"are missing", on=on), ""


def _env_names(p: Probes, on: str) -> tuple[Finding, str]:
    """Does every name in `box.env` exist in the environment — and is it non-empty?

    `container.py::_passthrough_env` passes a name only when `os.environ.get(name)` is truthy, and
    drops the rest without a word. So today a typo and a correctly-spelled-but-unset variable are
    indistinguishable: both produce a box that silently lacks the value, and the first report is an
    agent failing to authenticate a hundred turns later.

    THE EMPTY CASE IS ITS OWN BUCKET, because it fails in two different places. `FOO=""` is falsy
    and is DROPPED by `_passthrough_env`. `FOO="   "` is truthy, so it is passed — and then
    `AuthRoute.missing` strips it and reads the route as incomplete. Same symptom, two mechanisms,
    and an operator who has just run `env | grep FOO` and seen a line has no way to tell either
    from a working one.

    AND THIS IS THE CHECK WHERE PROVENANCE IS EVERYTHING. It reads the environment of THIS process.
    Run from a laptop, a green line here says only that the laptop has those variables."""
    names = [n for n in (p.box_env_names() or []) if str(n).strip()]
    if not names:
        return _ok("env_names",
                   "this project names no variables in `box.env`, so the box receives only the "
                   "harness defaults (`container.py::_AUTH_ENV_VARS`)", on=on), ""
    env = p.environ()
    absent = [n for n in names if env.get(n) is None]
    blank = [n for n in names if n not in absent and not str(env.get(n, "")).strip()]
    if not absent and not blank:
        return _ok("env_names",
                   f"all {len(names)} name(s) in `box.env` are set and non-empty in the {on} "
                   f"environment ({', '.join(names)})", on=on), ""
    parts = []
    if absent:
        parts.append(f"not set at all: {', '.join(absent)}")
    if blank:
        parts.append(f"set but empty: {', '.join(blank)}")
    return _fail("env_names",
                 f"`box.env` names {len(names)} variable(s) and {len(absent) + len(blank)} of them "
                 f"will not reach the box from the {on} environment — " + "; ".join(parts)
                 + ". An empty value is dropped by `container.py::_passthrough_env` exactly as a "
                   "misspelled name is, and a whitespace-only one is passed through and then read "
                   "as missing by `AuthRoute.missing`",
                 "the registry names variables and the environment holds their values: either set "
                 "them where the WORKER runs, or remove the names from `box.env` so nothing "
                 "depends on them. A name that is listed and unset is the shape that looks "
                 "configured and is not", on=on), ""


def _registry_parity(p: Probes, on: str) -> tuple[Finding, str]:
    """Does the FACTORY know this project, with the values this report just used?

    Without this, every other line here can be true about a project the deployment has never heard
    of. The registry the worker drives is `/var/lib/openfactory/registry.yaml`; a laptop's is
    `~/.openfactory/registry.yaml`; they are connected by a rebuild and a deploy and by nothing
    else.

    THREE ANSWERS, and only one of them is a failure: the worker's registry does not have this
    project (a real, actionable defect); it has it with different values (likewise, and the keys
    are named); or it could not be read from here at all — which on a laptop is the ordinary case
    and is neither. Reporting the third as a failure would make every local run print a line
    nobody can act on, which is how a tool teaches people to skim it.

    `repo_path` IS NOT ONE OF THE DECISIVE VALUES, and treating it as one made this check cry wolf
    every single time it could speak. Measured against the shape of a real deployment registry
    (`deploy/registry.yaml`: `repo_path: /work/acme`, with the comment "repo_path is a
    placeholder — the Fargate job clones the repo fresh from the forge") against a laptop's
    `~/Projects/acme`, this printed:

        FAIL registry_parity  the worker's registry holds 'acme' with DIFFERENT values
                              (repo_path), so this report describes a configuration the factory is
                              not running
                            → reconcile the two … a rebuild and a deploy, not an edit here

    Nobody can follow that, because there is nothing to reconcile. `activities.py` says it in its
    own words above `RepoCache().sync`: *"`project.repo_path` is a REGISTRY value — on Fargate it's
    where the entrypoint clones to …; on the WORKER it names no real directory at all. So the
    worker must sync its OWN cached checkout FIRST and load the manifest from THAT."* The two
    values are each correct for their own machine, and a check whose only reachable failure is an
    expected one is a check people learn to skip — the same cost as the unanswered case being
    reported as a failure, argued two paragraphs up.

    IT IS STILL PRINTED, both values, never hidden. Absence reading as compliance is this
    codebase's most expensive defect class, and "quietly dropped from the comparison" is exactly
    that shape. It is reported as a fact on a passing line instead of as a failure on a line with
    an unexecutable remedy, and any OTHER differing key still fails."""
    if on == WORKER:
        return _ok("registry_parity",
                   f"this IS the deployment's registry ({p.registry_path()}), so there is nothing "
                   f"to compare it against", on=on), ""
    try:
        theirs = p.worker_registry_entry()
    except RegistryUnreachable as exc:
        return _unanswered("registry_parity",
                           f"not answered: the worker's registry could not be read from here "
                           f"({exc}), so nothing here can say whether the factory knows "
                           f"{p.project_name!r} at all", on=on), ""
    if theirs is None:
        return _fail("registry_parity",
                     f"the worker's registry was read and does not contain {p.project_name!r} — "
                     f"every other line in this report is about a project the factory has never "
                     f"heard of",
                     "add the project where the deployment reads it, or (if the registry is baked "
                     "into the worker image) restore `deploy/registry.yaml`, rebuild and deploy "
                     "before trusting anything above", on=on), ""
    mine = p.registry_entry()
    differing = sorted(k for k in set(mine) | set(theirs) if mine.get(k) != theirs.get(k))
    decisive = [k for k in differing if k not in _EXPECTED_TO_DIFFER]
    # Said on both branches below rather than only on the failing one: a reader must never have to
    # infer from silence that the paths happen to match.
    paths = ""
    if "repo_path" in differing:
        paths = (f" `repo_path` differs ({mine.get('repo_path')!r} here, "
                 f"{theirs.get('repo_path')!r} there) and that is expected — the worker checks the "
                 f"repository out itself and re-points the manifest at that checkout, so the "
                 f"registry's value names no directory it uses")
    if not decisive:
        # "the same values" would contradict the sentence after it whenever `repo_path` differs,
        # and a line that argues with itself is read as a bug in the tool.
        head = (f"the worker's registry holds {p.project_name!r} with the same values this "
                f"report used" if not paths else
                f"nothing the factory acts on differs — the worker's registry holds "
                f"{p.project_name!r} with the same values this report used, bar one.")
        return _ok("registry_parity", head + paths, on=on), ""
    return _fail("registry_parity",
                 f"the worker's registry holds {p.project_name!r} with DIFFERENT values "
                 f"({', '.join(decisive)}), so this report describes a configuration the factory "
                 f"is not running." + paths,
                 "reconcile the two — the deployment's registry is the one that decides, and on a "
                 "deployment that bakes it into the worker image that means a rebuild and a "
                 "deploy, not an edit here", on=on), ""


# ── the real probes ─────────────────────────────────────────────────────────────────────────────

def where_this_answers_for(registry_path=None) -> str:
    """`worker` when this process reads the deployment's live registry, else `local`.

    THE SIGNAL IS THE FILE, NOT A FLAG. `registry.py::LIVE_REGISTRY_PATH` is documented as "where a
    deployed worker keeps the registry it actually drives", `docker/worker.Dockerfile` sets
    `OPENFACTORY_REGISTRY` to exactly it, and both compose services do the same. A dedicated
    `OPENFACTORY_I_AM_THE_WORKER` variable would be a second thing to set and therefore a thing that
    will
    be unset on the first install that needed it — the knob-that-will-be-wrong argument
    `runtime/temporal/io.py::default_sandbox` already makes for its own inference."""
    from openfactory.registry import LIVE_REGISTRY_PATH, ProjectRegistry

    path = registry_path if registry_path is not None else ProjectRegistry().path
    return WORKER if str(path) == str(LIVE_REGISTRY_PATH) else LOCAL


def probes_for(project) -> Probes:
    """The live probes for a registered project. Each one answers narrowly and never raises past
    `_guarded` — except `worker_registry_entry`, whose `RegistryUnreachable` is a THIRD ANSWER its
    check reads deliberately."""
    from openfactory import box_prove, doctor
    from openfactory.adapters.agent.registry import harness_kind
    from openfactory.adapters.agent.roles import role_prompt
    from openfactory.adapters.agent.routes import declared_route, resolve_route
    from openfactory.adapters.sandbox.registry import box_traits
    from openfactory.registry import LIVE_REGISTRY_PATH, ProjectRegistry
    from openfactory.runtime.temporal.io import default_sandbox

    name = getattr(project, "name", "?")

    def _floor_reason() -> str | None:
        """The floor asked of the SAME manifest object the runner would hold. A missing manifest is
        already `doctor`'s `manifest` finding; here it is an unanswerable question, not a second
        copy of that failure — so it propagates into `_guarded` rather than being swallowed."""
        from openfactory.loader import load_manifest
        from openfactory.policy.conformance import floor_reason

        return floor_reason(load_manifest(project))

    def _honours(kind: str) -> bool:
        try:
            return bool(box_traits((kind or "").strip().lower()).honours_image)
        except ValueError:
            # An unknown box is the registry's error to report. Treating it as gated would refuse
            # a project over a typo in a variable this check does not own; `gate_reason` makes the
            # same choice for the same reason.
            return False

    def _worker_entry() -> dict | None:
        if not LIVE_REGISTRY_PATH.exists():
            raise RegistryUnreachable(f"no file at {LIVE_REGISTRY_PATH}")
        try:
            return ProjectRegistry(LIVE_REGISTRY_PATH).get(name).model_dump(mode="json")
        except KeyError:
            return None  # READ, and this project is not in it — a real answer, and a failing one
        except (OSError, ValueError) as exc:
            raise RegistryUnreachable(f"{LIVE_REGISTRY_PATH}: {exc}") from exc

    def _environ() -> Mapping[str, str]:
        import os

        return os.environ

    return Probes(
        project_name=name,
        measured_on=where_this_answers_for,
        registry_path=lambda: str(ProjectRegistry().path),
        doctor_report=lambda: doctor.diagnose(doctor.probes_for(project)),
        sandbox=default_sandbox,
        box_honours_image=_honours,
        gate_reason=lambda: box_prove.gate_reason(project, sandbox=default_sandbox()),
        proof=lambda: box_prove.load(name),
        proof_dir=lambda: str(box_prove.PROOF_DIR),
        floor_reason=_floor_reason,
        floor_enforced=doctor.floor_is_enforced,
        role_prompt=role_prompt,
        declared_route=lambda: declared_route(project),
        resolved_route=lambda: resolve_route(project),
        # `executor` because that is the role BOTH route functions resolve for — `declared_route`
        # and `resolve_route` each call `harness_kind(project, "executor")`, so asking a different
        # role here would compare a route with a harness that did not produce it.
        harness_kind=lambda: harness_kind(project, "executor"),
        box_env_names=lambda: list(getattr(getattr(project, "box", None), "env", None) or []),
        environ=_environ,
        enabled=lambda: bool(getattr(project, "enabled", True)),
        registry_entry=lambda: project.model_dump(mode="json"),
        worker_registry_entry=_worker_entry,
        product_enabled=lambda: bool(
            (cfg := getattr(project, "product", None)) is not None
            and getattr(cfg, "enabled", True)),
        product_admins=lambda: list(
            getattr(getattr(project, "product", None), "admins", None) or []),
    )


def readiness_for(project) -> Report:
    """The one call site a command needs: `readiness_for(ProjectRegistry().get(name))`.

    Exists so wiring `openfactory env check` is four lines — print `report.render()`, exit
    `report.exit_code` — rather than a second place where the composition can be assembled
    differently and drift."""
    return assess(probes_for(project))
