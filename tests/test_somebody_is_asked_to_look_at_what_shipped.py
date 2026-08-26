"""A green stage sends a person somewhere, and never somewhere nobody named (#122).

The pilot, the evening before his first merge:

    *"when the merge is done a deploy to staging happens — I have not seen anywhere that picks up
    the staging domain so the tech-lead (or the PO) can ask for validation. This project HAS a
    staging environment, that is the flow, but other companies may have another one, and I have
    not seen anywhere this would work."*

He was right on both halves.

THE ADDRESS HAD NO HOME. `ProductConfig.staging_url` was the only human-visitable deployed address
in the product: one string, on the DEPLOYMENT's registry rather than the client's manifest, with no
command that writes it, mentioned in no document, and read in exactly one line. It cannot express
`dev` + `qa` + `producao` — which is precisely the shape #109 taught the promotion chain to accept
— so a company with a real chain had one address for three places to look.

THE ASK WAS GATED ON THE WRONG THING. It fired for jobs parked at `AWAITING_PROD_APPROVAL`, so a
shop whose flow ENDS at staging — no production declared, which this platform explicitly supports
as an ordinary state — was never asked to validate anything at all. The one validation loop that
existed was reachable only by the projects that needed it least.

AND A THIRD DEFECT FELL OUT OF FIXING IT. That same shop's promotion returns `DONE`, and the
workflow's tail treated everything that was not `AWAITING_PROD_APPROVAL` as a failure — so every
staging-only project was announced with *"staging did not verify (done)"*. The one flow this card
exists to serve was being told its green deploy had gone wrong.
"""

from __future__ import annotations

import inspect

import pytest

from openfactory.contracts import JobState
from openfactory.contracts.manifest import Environment, Manifest


def _manifest(**kw) -> Manifest:
    return Manifest.model_validate(kw)


CHAIN = _manifest(
    environments={
        "dev": Environment(deploy_ref="dev", url="https://dev.acme.com"),
        "qa": Environment(deploy_ref="qa", health_url="https://qa.acme.com/health",
                          url="https://qa.acme.com"),
        "producao": Environment(deploy_ref="producao"),
    },
    promote=["dev", "qa", "producao"],
)


# ── 1. the declaration: one address per stage ───────────────────────────────────────────────────

def test_every_stage_can_name_its_own_place_to_look():
    """The shape a single deployment-wide `staging_url` could not express."""
    assert CHAIN.where_a_person_looks("dev") == "https://dev.acme.com"
    assert CHAIN.where_a_person_looks("qa") == "https://qa.acme.com"
    assert CHAIN.where_a_person_looks("producao") == ""


def test_the_probe_target_is_never_offered_to_a_PERSON():
    """`health_url` is where a machine sends a GET and reads a status code. Sending somebody to
    `/api/v1/health` to confirm a feature is sending them to the wrong page — and both exist on
    the pilot's own staging deploy, as different strings."""
    only_health = _manifest(
        environments={"qa": Environment(health_url="https://qa/health"), "prod": Environment()},
        promote=["qa", "prod"])
    assert only_health.where_a_person_looks("qa") == ""


def test_the_deploy_WATCH_can_carry_it_for_the_repositories_that_have_no_stages():
    """Observing an `Environment` needs the provider to RECORD a deployment; a repository that
    just deploys from a workflow records none. Offering the address only where the chain lives
    would hand it exclusively to the shops that need it least."""
    watched = _manifest(post_merge_deploy={"workflow": "deploy.yml", "env": "staging",
                                           "url": "https://stg.acme.com"})
    assert watched.where_a_person_looks("staging") == "https://stg.acme.com"
    assert watched.where_a_person_looks("qa") == "", "a watch answers only for its own stage"


def test_the_stage_a_person_confirms_is_DERIVED_when_nobody_declared_one():
    """`validate_with:` is the escape hatch, not the mechanism. The default is the last stage
    before production, which is what every shop means by "the test environment" — and it has to
    be a default, because the projects that would never think to declare it are exactly the ones
    that were never asked anything."""
    assert CHAIN.stage_a_person_confirms() == "qa"


def test_a_stage_can_CLAIM_the_confirmation():
    declared = _manifest(
        environments={"dev": Environment(url="https://dev", validate_with="product"),
                      "qa": Environment(url="https://qa"),
                      "prod": Environment()},
        promote=["dev", "qa", "prod"])
    assert declared.stage_a_person_confirms() == "dev"


def test_the_CHAIN_wins_over_the_order_things_were_declared_in():
    """The two rules agree on most manifests, which is why a mutation removing the chain rule
    survived the first pass here. They part company on an environment that is DECLARED and left
    out of `promote:` — a spare, a sandbox, somebody's branch deploy. The chain is what the
    platform walks, so the chain is what somebody is asked about."""
    with_a_spare = _manifest(
        environments={"dev": Environment(url="https://dev"),
                      "qa": Environment(url="https://qa"),
                      "sandbox": Environment(url="https://sandbox"),
                      "producao": Environment()},
        promote=["dev", "qa", "producao"])
    assert with_a_spare.stage_a_person_confirms() == "qa", (
        "somebody is being sent to an environment that is not even in the promotion chain")


def test_PRODUCTION_is_never_the_place_somebody_is_asked_to_validate():
    """It has its own human gate, and it is nobody's test environment. Reached only on the
    derived path — with no `promote:` the chain observes nothing it recognises, so the fallback
    runs and must still exclude production."""
    derived = _manifest(environments={"qa": Environment(url="https://qa"),
                                      "prod": Environment(url="https://prod")})
    assert derived.stage_a_person_confirms() == "qa"


def test_a_project_with_no_stages_asks_for_nothing():
    assert _manifest().stage_a_person_confirms() == ""
    assert _manifest().where_a_person_looks("") == ""


# ── 2. the ask reaches a person, with no channel required ───────────────────────────────────────

class _Tracker:
    def __init__(self):
        self.comments: list[str] = []
        self.states: list = []

    def set_state(self, ref, state, reason=None, *, needs_person=None):
        self.states.append(state)

    def comment(self, ref, body):
        self.comments.append(body)


class _Notifier:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def notify(self, *, message, level="info"):
        self.sent.append((level, message))
        return True


class _Observer:
    def deploy_status(self, *, env, ref):
        return "success"

    def health(self, *, url):
        return True


def _run(manifest):
    from openfactory.orchestrator.promotion import PromotionRunner

    tracker, notifier = _Tracker(), _Notifier()
    runner = PromotionRunner(tracker=tracker, forge=object(), observer=_Observer(),
                             manifest=manifest, notifier=notifier)
    return runner.promote("42"), tracker, notifier


def test_a_flow_that_ENDS_AT_STAGING_is_asked_to_validate_it():
    """THE CARD. No production stage means no gate, so a person confirming the change is right is
    the whole of what is left — and it was the one flow that was never asked."""
    # NO `promote:` AND A NAME OF THEIR OWN. The derived chain knows `staging` and `prod`, so
    # this shop yields no observed stages at all — and asking off the chain alone would leave them
    # exactly where the card found them: a real test environment nobody is ever sent to.
    ends_at_qa = _manifest(
        environments={"qa": Environment(deploy_ref="qa", url="https://qa.acme.com")})

    result, tracker, notifier = _run(ends_at_qa)

    assert result.state == JobState.DONE
    assert result.look_stage == "qa" and result.look_at == "https://qa.acme.com"
    said = " ".join(tracker.comments)
    assert "https://qa.acme.com" in said, "the ticket does not say where to look"
    assert "confirm" in said.lower()
    assert any(level == "action_required" for level, _m in notifier.sent), (
        "a stage nobody is gating is reported as news rather than as something to do")


def test_the_PRODUCTION_gate_carries_the_address_too():
    result, tracker, notifier = _run(CHAIN)

    assert result.state == JobState.AWAITING_PROD_APPROVAL
    assert result.look_stage == "qa" and result.look_at == "https://qa.acme.com"
    assert "https://qa.acme.com" in " ".join(tracker.comments)


def test_a_project_with_NO_product_channel_still_gets_the_address():
    """AC3. The ticket and the notifier are what every deployment has; the client channel is
    additive. Nothing in this test constructs a channel, a product module or a client."""
    _result, tracker, notifier = _run(CHAIN)
    assert any("https://qa.acme.com" in c for c in tracker.comments)
    assert notifier.sent


def test_an_EMPTY_address_never_produces_a_message_that_implies_one():
    """AC4, and the failure mode is specific: a person opens the message, looks for a link, finds
    none, and concludes the platform is broken rather than that their project never said where."""
    nowhere = _manifest(environments={"qa": Environment(deploy_ref="qa")})

    result, tracker, notifier = _run(nowhere)

    assert result.look_stage == "qa" and result.look_at == ""
    said = " ".join(tracker.comments) + " ".join(m for _l, m in notifier.sent)
    assert "url:" in said, "it does not name the field that would fix this"
    assert "http" not in said.replace("https://", "").replace("http://", ""), (
        "an address was invented")
    for implies in ("take a look at ", "confirm it is right: "):
        assert implies not in said, f"it still sends somebody somewhere: {implies!r}"


def test_a_project_with_NOTHING_declared_asks_nobody_anything():
    """The negative twin. Turning "no environments" into an ask would put a chore on every project
    that deploys by hand — and this platform's own rule is that a project deploying nothing is an
    ordinary project, not a misconfigured one."""
    result, tracker, notifier = _run(_manifest())
    assert result.look_stage == "" and result.look_at == ""
    assert not any(level == "action_required" for level, _m in notifier.sent)
    assert "confirm" not in " ".join(tracker.comments).lower()


# ── 3. the address travels back out of the box ──────────────────────────────────────────────────

def test_the_answer_rides_on_the_RESULT_because_the_worker_has_no_checkout():
    """The manifest is in the CLIENT's repository, checked out in the box that runs the promotion
    and nowhere near the worker. A field with a default deserialises on a job that predates it."""
    from openfactory.contracts.run import RunResult

    r = RunResult(ticket_id="1", state=JobState.DONE)
    assert r.look_stage == "" and r.look_at == ""


def test_a_live_job_can_be_ASKED_where_a_person_should_look():
    """A query, so it is answerable while the job is parked at the gate — which is exactly when
    somebody is being asked — and replay-safe, because a query issues no command."""
    from openfactory.runtime.temporal.workflow import JobWorkflow

    assert getattr(JobWorkflow.where_to_look, "__temporal_query_definition", None) is not None
    src = inspect.getsource(JobWorkflow)
    assert "self._look = {" in src, "nothing ever fills it — the query answers None for ever"


def test_the_client_ask_reads_the_JOB_and_not_the_deployment(monkeypatch):
    """`staging_url` stays as a fallback for deployments that already set it, and the manifest
    wins. A guard on the source because this needs a live engine to execute."""
    from openfactory.product import release

    src = inspect.getsource(release.parked_for_release)
    assert '"where_to_look"' in src, (
        "the client is asked to try something and the address still comes from the deployment")


def test_the_deprecated_fallback_says_so_when_it_is_what_gets_used():
    """A value nobody can find is a value nobody can correct — and `staging_url` has no command
    that writes it, appears in no document, and lives on a per-deployment file."""
    from openfactory.runtime.temporal import activities

    src = inspect.getsource(activities._offer_the_release_to_the_client)
    assert "staging_url" in src
    # THE CONDITION, not the word. Checking only that "deprecated" appears somewhere left a
    # mutation that disabled the branch entirely sitting green — the sentence was still in the
    # source, in a block nothing could reach.
    assert "if not declared and fallback:" in src, (
        "the fallback is used without saying so, or is said unconditionally — a value nobody can "
        "find is a value nobody can correct")


# ── 4. the false alarm this card's own flow was getting ─────────────────────────────────────────

def test_finishing_at_the_last_stage_is_not_announced_as_a_FAILURE():
    """A promotion that ends with no production returns DONE, and the workflow's tail treated
    everything that was not AWAITING_PROD_APPROVAL as "staging did not verify". Every staging-only
    project — the exact shape this card is about — was told its green deploy had gone wrong."""
    from openfactory.runtime.temporal.workflow import JobWorkflow

    src = inspect.getsource(JobWorkflow)
    assert "staging.state == JobState.DONE" in src, (
        "the tail no longer tells a finished chain apart from a broken one")

    ask = JobWorkflow._confirm_the_stage
    assert "did not verify" not in inspect.getsource(ask)


@pytest.mark.parametrize("stage,url,expect,forbid", [
    ("qa", "https://qa.acme.com", "https://qa.acme.com", "did not verify"),
    ("qa", "", "url:", "http"),
    ("", "", "nothing further is waiting", "confirm"),
])
def test_what_a_finished_chain_actually_SAYS(stage, url, expect, forbid):
    from openfactory.contracts.run import RunResult
    from openfactory.runtime.temporal.io import JobParams
    from openfactory.runtime.temporal.workflow import JobWorkflow

    said = JobWorkflow._confirm_the_stage(
        JobWorkflow(), JobParams(project="acme", issue="42"),
        RunResult(ticket_id="42", state=JobState.DONE, look_stage=stage, look_at=url))

    assert expect in said
    assert forbid not in said


# ── 5. the doctor says when the half is dark ────────────────────────────────────────────────────

def _finding(manifest):
    from openfactory.doctor import _post_merge

    class P:
        def manifest(self):
            return manifest

    return _post_merge(P())


def test_the_doctor_reports_a_watched_deploy_NOBODY_can_be_sent_to():
    """AC5. A pass that said "your deploy run is watched" was reporting the half that works: the
    operator's whole question was where somebody goes to look at the result."""
    watched = _manifest(post_merge_deploy={"workflow": "deploy.yml", "env": "staging"},
                        environments={"staging": Environment(deploy_ref="staging")})
    found = _finding(watched)
    assert found.ok, "declaring no address is not a broken project"
    assert "url:" in found.note and "nobody can be asked" in found.note


def test_the_doctor_names_the_address_when_there_IS_one():
    watched = _manifest(post_merge_deploy={"workflow": "deploy.yml", "env": "staging",
                                           "url": "https://stg.acme.com"},
                        environments={"staging": Environment(deploy_ref="staging")})
    found = _finding(watched)
    assert "https://stg.acme.com" in found.note


def test_the_doctor_still_says_nothing_about_a_project_that_declares_nothing():
    found = _finding(_manifest())
    assert found.ok and "url:" not in (found.note or "")
