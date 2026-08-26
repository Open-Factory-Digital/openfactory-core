"""What a failure is, and therefore who acts on it (ADR-0020).

Written against failures this factory actually produced. The one that prompted all of it: on
2026-07-26 GitHub throttled the App installation, #478 parked, the single-line floor was held for
eighteen hours, nothing else ran, and nobody was told — for a failure whose entire remedy is to wait.
"""

from __future__ import annotations

import pytest

from openfactory.techlead import (
    CODE,
    CREDENTIAL,
    ENVIRONMENT,
    REQUIREMENT,
    TRANSIENT,
    UNKNOWN,
    classify,
    remedy_for,
)

#: verbatim, from the panel
THROTTLED = ("box failed: gh project field-list 6 --owner AcmeCorp --format json failed: "
             "GraphQL: API rate limit exceeded for installation ID 146152259.")


def test_THE_failure_that_cost_a_night_is_the_factorys_own():
    v = classify(THROTTLED)
    assert v.cause == TRANSIENT
    r = remedy_for(v)
    assert r.action == "retry"
    assert r.wait_seconds > 0
    # THE SENTENCE IS RENDERED PER LANGUAGE NOW (#124), so the claim is pinned in BOTH — which
    # also catches a phrasebook entry that exists in one and not the other.
    assert "passes on its own" in r.say
    assert "passa sozinho" in remedy_for(v, language="pt-BR").say


@pytest.mark.parametrize("note", [
    "You have exceeded a secondary rate limit",
    "429 Too Many Requests",
    "was submitted too quickly",
    "connection reset by peer",
    "503 Service Unavailable",
    "TLS handshake timeout",
    "CapacityProviderException: insufficient capacity",
])
def test_everything_that_time_alone_fixes_is_transient(note):
    assert classify(note).cause == TRANSIENT


@pytest.mark.parametrize("note", [
    "Bad credentials",
    "401 Unauthorized",
    "Invalid API key",
    "Your organization has disabled Claude subscription access",
    "your credit balance is too low",
])
def test_a_credential_failure_WAITS_before_it_escalates(note):
    """Rotation has already happened by the time we get here.

    The adapter laps the whole pool WITHIN a single run, so a job that parked on a credential has
    already tried every token once. There is no "next one" left to reach for — which is why the
    remedy is not rotation but a bounded wait: a subscription limit resets, and a token an operator
    replaced in the meantime starts working. Escalating immediately would ask a person to fix
    something that often fixes itself; retrying forever would hide a genuinely revoked pool."""
    v = classify(note)
    assert v.cause == CREDENTIAL

    first = remedy_for(v)
    assert first.action == "retry"
    assert first.wait_seconds > 0
    assert "credentials failed" in first.say
    assert "credenciais falharam" in remedy_for(
        classify(note, state="paused"), language="pt-BR").say

    # …and it does not wait forever
    assert remedy_for(v, already_tried=9).action == "escalate"


@pytest.mark.parametrize("note", [
    "Resource not accessible by integration",
    "permission denied",
    "pull access denied for the image",
    "no space left on device",
])
def test_infrastructure_that_no_retry_changes_goes_to_a_person(note):
    assert classify(note).cause == ENVIRONMENT
    assert remedy_for(classify(note)).action == "escalate"


def test_a_ticket_problem_belongs_to_the_PRODUCT_role_not_a_human():
    assert classify("ticket too large").cause == REQUIREMENT
    """ADR-0019 §6. Today this parks for a person, who then rewrites a criterion by hand — which is
    precisely the work the product role exists to do."""
    assert remedy_for(classify("ticket too large — split it")).action == "product"
    assert remedy_for(classify("x", state="needs_refinement")).action == "product"


def test_a_wrong_change_is_never_retried():
    assert classify("e2e suite is RED — https://x").cause == CODE
    assert remedy_for(classify("gate-suppression(s) added")).action == "escalate"


# ── the asymmetry that keeps this safe ──────────────────────────────────────────────────────────

def test_an_unrecognised_failure_ESCALATES_it_does_not_retry():
    """Retrying what nobody understood is how a token pool burns on something structurally broken
    and a loop looks like progress."""
    v = classify("something nobody has seen before")
    assert v.cause == UNKNOWN
    r = remedy_for(v)
    assert r.action == "escalate"
    assert "could not identify" in r.reason
    assert "não consegui identificar" in remedy_for(v, language="pt-BR").reason


def test_throttling_wins_over_a_credential_word_in_the_same_message():
    """A throttled call mentioning "token" is common. A revoked token that also says "rate limit
    exceeded" is not — so the order of the rules is a decision, not an accident."""
    assert classify("token request failed: API rate limit exceeded").cause == TRANSIENT


# ── waiting is free, re-running an agent is not ─────────────────────────────────────────────────

def test_a_setup_failure_may_be_retried_more_than_an_agent_failure():
    """A box that died during setup burned no agent tokens. One that died mid-execution did, and
    re-running it pays again — so three "helpful" retries is how a bill triples quietly."""
    cheap = remedy_for(classify("box failed: API rate limit exceeded"))
    costly = remedy_for(classify("agent stopped: API rate limit exceeded"))
    assert cheap.attempts_left > costly.attempts_left


def test_an_exhausted_budget_ESCALATES_rather_than_resetting():
    v = classify(THROTTLED)
    spent = remedy_for(v, already_tried=3)
    assert spent.action == "escalate"
    assert "already tried" in spent.say
    assert "Já tentei" in remedy_for(v, already_tried=99, language="pt-BR").say


def test_the_wait_grows_between_attempts():
    """A first attempt well inside GitHub's hourly window is a wasted one."""
    v = classify(THROTTLED)
    first = remedy_for(v, already_tried=0).wait_seconds
    second = remedy_for(v, already_tried=1).wait_seconds
    assert second > first


def test_a_failure_that_says_when_to_come_back_is_BELIEVED():
    """Guessing a backoff when the service told us the answer is how a retry lands early and burns
    the next window too."""
    v = classify("rate limited; Retry-After: 900")
    assert v.retry_after == 900
    assert remedy_for(v).wait_seconds == 900


# ── every remedy explains itself ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("note,state", [
    (THROTTLED, ""),
    ("Bad credentials", ""),
    ("permission denied", ""),
    ("e2e suite is RED", ""),
    ("ticket too large", ""),
    ("who knows", ""),
])
def test_a_remedy_always_says_what_it_is_doing_and_why(note, state):
    """A channel that shows an action without its reason teaches people to stop reading it — and an
    escalation without one is just a shrug with a ticket number."""
    r = remedy_for(classify(note, state=state))
    assert r.reason, note
    assert r.say, note


# ── C-27: the two classes a human used to resolve by hand, both previously "unknown" ─────────────

class TestPolicyIsNamedNotUnknown:
    """The org refusing a write it is DESIGNED to refuse (CI/CD is human-only). Reading this as
    'unknown' sent a person into this codebase; reading it as 'environment' sent them to fix a
    rule that was working. The escalation must carry the way AROUND the rule — never a request
    to grant the bot the permission."""

    REJECTIONS = (
        "! [remote rejected] sdlc/12 -> sdlc/12 (refusing to allow a GitHub App to create or "
        "update workflow `.github/workflows/deploy.yml` without `workflows` permission)",
        "push declined due to repository rule violations",
        "protected branch hook declined",
        "the change to .github/workflows/ci.yml was rejected by the organization",
    )

    def test_every_real_rejection_string_lands_on_policy(self):
        from openfactory.techlead.classify import POLICY, classify

        for note in self.REJECTIONS:
            assert classify(note).cause == POLICY, note

    def test_the_workflow_rejection_never_reads_as_environment(self):
        """It also says 'permission' — the environment rule's own word. Order in _RULES is what
        keeps a working guardrail from being escalated as broken infrastructure."""
        from openfactory.techlead.classify import ENVIRONMENT, classify

        v = classify(self.REJECTIONS[0])
        assert v.cause != ENVIRONMENT

    def test_the_remedy_teaches_the_way_around_never_the_permission(self):
        from openfactory.techlead.classify import classify, remedy_for

        r = remedy_for(classify(self.REJECTIONS[0]))
        assert r.action == "escalate"
        assert "resume" in r.say and ".github/workflows" in r.say
        assert "permiss" in r.say.lower(), "the sentence must SAY the permission is not the path"


class TestProjectConfigPointsAtTheClientsRepo:
    """`setup:`/`validate:` are the client's commands and the manifest is their file. These
    landed as 'não consegui identificar a causa' — false, and it routed the person into THIS
    codebase when the fix was never here."""

    NOTES = (
        "box failed: setup: `npm ci` exited 127 (sh: npm: command not found)",
        "no manifest at /work/fx-mono/.sdlc/project.yaml",
        "manifest: .sdlc/project.yaml is not valid YAML: mapping values are not allowed here",
    )

    def test_every_client_config_failure_lands_on_project(self):
        from openfactory.techlead.classify import PROJECT, classify

        for note in self.NOTES:
            assert classify(note).cause == PROJECT, note

    def test_the_remedy_says_the_fix_lives_in_their_repo(self):
        from openfactory.techlead.classify import classify, remedy_for

        r = remedy_for(classify(self.NOTES[0]))
        assert r.action == "escalate"
        assert "resume" in r.say
        assert "project.yaml" in r.say or "repositório do projeto" in r.say

    def test_dockers_manifest_unknown_is_still_infrastructure(self):
        """The docker registry's 'manifest unknown' shares a word with the client's manifest —
        it must stay ENVIRONMENT (the box image is the deployment's, not the client's)."""
        from openfactory.techlead.classify import ENVIRONMENT, classify

        assert classify("pull access denied / manifest unknown").cause == ENVIRONMENT


def test_a_policy_park_carries_its_own_way_out_in_the_watch():
    """The round used to say 'esperando uma decisão de vocês' — true and useless. The finding
    must carry the remedy's sentence, which names the rule and the scope change."""
    from openfactory.techlead.watch import FloorState, Parked, watch

    state = FloorState(parked=[Parked(
        ticket="12", hours=4.0,
        note="refusing to allow a GitHub App to update workflow `.github/workflows/ci.yml` "
             "without `workflows` permission")])

    findings = watch(state)

    assert findings, "a 4h park is worth a finding"
    assert ".github/workflows" in findings[0].action, (
        "the generic 'esperando uma decisão' threw the executable sentence away")


# ── C-27's done-when, made measurable ───────────────────────────────────────────────────────────
#
# "the impediment classes a human currently resolves by hand are either remediated automatically
# or escalated with an executable option, and none of them requires someone who knows this
# codebase". That is a claim about a POPULATION, so it is tested against one: the real park notes
# this platform produced during the F-01…F-05 fixture runs. Six of the first ten came back
# `unknown` with no way out, which is what the card was actually describing.

#: Verbatim from the incident log — do not tidy them. The value is that they are what the
#: platform really wrote, not what a test author would think to write.
REAL_PARK_NOTES = [
    "validations failed after 2 repair attempt(s)",
    "ticket has no acceptance criteria — in fact no sections at all. Add a `## Acceptance criteria`",
    "gh pr create failed: pull request create failed: GraphQL: No commits between main and sdlc/1",
    "job errored after retries: ApplicationError: RuntimeError: fetching the existing branch "
    "'sdlc/1' failed (128): fatal: couldn't find remote ref sdlc/1",
    "PR not merged within 14d (CI watch)",
    "box failed: setup: `dotnet restore` exited 1",
    "still rate-limited after 3 auto-resumes",
    "agent stopped: turn cap",
    "refusing to allow a GitHub App to update workflow `.github/workflows/ci.yml`",
    "some failure shape nobody has ever seen before",
]


def _has_an_executable_way_out(remedy) -> bool:
    """Either the factory acts, or the sentence tells a person exactly what to reply."""
    return remedy.action in ("retry", "product") or "resume" in remedy.say or "skip" in remedy.say


@pytest.mark.parametrize("note", REAL_PARK_NOTES)
def test_every_real_park_note_yields_an_executable_option(note):
    from openfactory.techlead.classify import classify, remedy_for

    remedy = remedy_for(classify(note))

    assert _has_an_executable_way_out(remedy), (
        f"this park escalates with no next move: {remedy.say!r}")


def test_even_a_failure_NOBODY_has_seen_carries_a_way_out():
    """`unknown` is the honest answer for a novel failure and it must still not be a dead end —
    the reader gets "I could not tell" AND the two commands, never just the first."""
    from openfactory.techlead.classify import UNKNOWN, classify, remedy_for

    verdict = classify("some failure shape nobody has ever seen before")
    remedy = remedy_for(verdict)

    assert verdict.cause == UNKNOWN
    assert "resume" in remedy.say and "skip" in remedy.say


def test_a_note_that_SAYS_the_retries_are_spent_is_not_retried():
    """`already_tried` counts only what THIS workflow remedied, so an exhaustion inherited from
    the pause ladder was invisible to it: "still rate-limited after 3 auto-resumes" matched the
    throttling rule and came back `retry` — the platform proposing the very thing whose failure
    the sentence describes."""
    from openfactory.techlead.classify import classify, remedy_for

    remedy = remedy_for(classify("still rate-limited after 3 auto-resumes"))

    assert remedy.action == "escalate", "it offered to retry what already ran out of retries"
    assert remedy.attempts_left == 0


def test_a_FRESH_throttle_is_still_retried_automatically():
    """The guard above must not cost the self-heal that ADR-0020 exists for — eighteen hours of
    held floor came from escalating exactly this."""
    from openfactory.techlead.classify import classify, remedy_for

    remedy = remedy_for(classify("API rate limit exceeded for installation"))

    assert remedy.action == "retry" and remedy.wait_seconds > 0


def test_an_empty_branch_goes_to_the_product_not_to_an_engineer():
    """"No commits between main and sdlc/N" means nothing was produced — the ticket may already
    be delivered. That is a question about the REQUIREMENT, not about infrastructure."""
    from openfactory.techlead.classify import REQUIREMENT, classify

    assert classify("GraphQL: No commits between main and sdlc/1").cause == REQUIREMENT


def test_a_missing_branch_or_credential_is_ENVIRONMENT_not_unknown():
    from openfactory.techlead.classify import ENVIRONMENT, classify

    for note in ("fatal: couldn't find remote ref sdlc/1",
                 "fatal: could not read Username for 'https://github.com'"):
        assert classify(note).cause == ENVIRONMENT, note
