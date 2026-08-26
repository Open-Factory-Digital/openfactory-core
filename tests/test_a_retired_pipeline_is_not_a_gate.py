"""A command read from a switched-off pipeline is not this client's gate (#117).

Found live on the pilot (2026-08-14). The proposed manifest carried

    uv run bandit -c pyproject.toml -r src

read verbatim from `.github/workflows/ci.yml`, a workflow whose forge state is
`disabled_manually`. The provenance said *"observed from ci.yml"* with full confidence, and the
box proof then failed on a gate the client had deliberately turned off — four Low bandit findings
accumulated since nobody ran it. The failure was at least loud, and it was loud about the wrong
sentence: *"these are YOUR gates"*. This one was not, any more.

ON DISK A RETIRED WORKFLOW IS BYTE-IDENTICAL TO A LIVING ONE, so this is not a bug in `infer`,
which is offline and vendor-neutral on purpose. The state is the FORGE's, and `onboard` has a
forge. The next deployment makes it worse rather than better: an enterprise arrives with years of
retired Azure Pipelines beside the living ones, same directory, same extension.

THE THREE RULES, and the third carries the weight:

    re-point   a field whose evidence is all dead, with a live candidate, takes the live one;
    demote     one with no live alternative becomes a QUESTION naming the file and the state —
               never a silent drop, because a client who disabled a workflow may want it back and
               that is their decision;
    abstain    a forge that CANNOT SAY changes nothing. `None` means "I could not find out", and
               reading it as "nothing is disabled" would be this codebase's most expensive
               recurring shape applied to the one decision that removes a client's real gate.
"""

from __future__ import annotations

import pytest

from openfactory.onboarding.infer import (
    INFERRED,
    OBSERVED,
    UNKNOWN,
    Candidate,
    Evidence,
    ManifestProposal,
    Proposal,
)
from openfactory.onboarding.live_ci import _norm, ask_the_forge, demote_disabled

DEAD = ".github/workflows/ci.yml"
LIVE = "Makefile"


def _proposal(**candidates_by_field) -> ManifestProposal:
    """`field=[(value, path), …]` — best first, exactly as `infer` ranks them."""
    fields = {}
    for name, found in candidates_by_field.items():
        key = name.replace("__", ".")
        cands = [Candidate(value=v, confidence=OBSERVED, evidence=[Evidence(path=p, line=1)])
                 for v, p in found]
        fields[key] = Proposal(
            field=key, value=cands[0].value if cands else None,
            confidence=OBSERVED if cands else UNKNOWN,
            evidence=list(cands[0].evidence) if cands else [], candidates=cands)
    return ManifestProposal(repo="/tmp/x", fields=fields)


# ── 1. the pilot's own case ─────────────────────────────────────────────────────────────────────

def test_a_command_found_ONLY_in_a_disabled_workflow_is_not_proposed():
    p = _proposal(validate__lint=[("uv run bandit -c pyproject.toml -r src", DEAD)])

    demote_disabled(p, [DEAD])

    field = p.fields["validate.lint"]
    assert field.value is None and field.confidence == UNKNOWN, (
        "a gate the client switched off is still being proposed as theirs")
    assert not field.known, "it would still be written into the manifest"


def test_the_question_NAMES_the_file_and_the_state():
    """"We ignored this" is not an answer somebody can act on, and the whole reason the pilot lost
    a day is that nothing said which file or why."""
    p = _proposal(validate__lint=[("uv run bandit -r src", DEAD)])
    demote_disabled(p, [DEAD])

    (question,) = [q for q in p.questions if "validate.lint" in q]
    assert DEAD in question, f"the client cannot tell which file this is about: {question}"
    assert "DISABLED" in question
    assert p.fields["validate.lint"].note == question, (
        "`onboard` reads an unknown field's `note` into the pull request — a question written "
        "anywhere else is lost")


def test_the_question_does_not_DECIDE_for_the_client():
    """They disabled it. Re-enabling it may be exactly right and is not ours to do."""
    p = _proposal(validate__lint=[("uv run bandit -r src", DEAD)])
    demote_disabled(p, [DEAD])
    said = " ".join(p.questions).lower()
    assert "re-enable it if" in said or "if the disabled one" in said
    for bossy in ("you should", "you must", "we removed", "we deleted"):
        assert bossy not in said, f"the report is telling the client what to decide: {bossy!r}"


def test_a_LIVING_alternative_is_taken_and_the_swap_is_stated():
    p = _proposal(validate__lint=[("uv run bandit -r src", DEAD), ("make lint", LIVE)])

    demote_disabled(p, [DEAD])

    field = p.fields["validate.lint"]
    assert field.value == "make lint", "a live command was available and was not used"
    assert field.known, "the field was demoted even though this repository has a working answer"
    assert [e.path for e in field.evidence] == [LIVE], (
        "it cites the dead file for a command that came from the living one")
    said = " ".join(p.questions)
    assert "make lint" in said and DEAD in said, (
        "the swap happened silently — the reviewer cannot see that a stronger reading was dropped")


# ── 2. what must NOT be touched ─────────────────────────────────────────────────────────────────

def test_a_forge_that_CANNOT_SAY_changes_nothing():
    """THE LOAD-BEARING RULE. `None` is "I could not find out", and treating it as "nothing is
    disabled" would remove a client's real gate on the strength of a failed API call."""
    p = _proposal(validate__lint=[("uv run bandit -r src", DEAD)])

    demote_disabled(p, None)

    assert p.fields["validate.lint"].value == "uv run bandit -r src"
    assert p.questions == []


def test_a_forge_that_says_NOTHING_IS_DISABLED_changes_nothing_either():
    """The other half of the three-answer split: `[]` is knowledge, and the knowledge is that
    every pipeline is live."""
    p = _proposal(validate__lint=[("uv run bandit -r src", DEAD)])
    demote_disabled(p, [])
    assert p.fields["validate.lint"].value == "uv run bandit -r src"


def test_a_command_corroborated_by_a_LIVE_file_survives():
    """ALL, not ANY. A command witnessed by a live Makefile and a dead ci.yml is still a command
    this repository runs — demoting it because one witness retired takes a working gate away."""
    p = ManifestProposal(repo="/tmp/x", fields={"validate.test": Proposal(
        field="validate.test", value="pytest -q", confidence=OBSERVED,
        evidence=[Evidence(path=DEAD, line=3), Evidence(path=LIVE, line=9)],
        candidates=[Candidate(value="pytest -q", confidence=OBSERVED,
                              evidence=[Evidence(path=DEAD, line=3),
                                        Evidence(path=LIVE, line=9)])])})

    demote_disabled(p, [DEAD])

    assert p.fields["validate.test"].value == "pytest -q"
    assert p.questions == []


def test_a_field_that_never_cited_CI_is_untouched():
    p = _proposal(base_branch=[("main", ".git/HEAD")])
    demote_disabled(p, [DEAD])
    assert p.fields["base_branch"].value == "main"


def test_an_already_UNKNOWN_field_is_not_re_questioned():
    p = ManifestProposal(repo="/tmp/x", fields={"validate.lint": Proposal(
        field="validate.lint", confidence=UNKNOWN, note="nothing found")})
    demote_disabled(p, [DEAD])
    assert p.questions == [], "a field nobody proposed is being explained away twice"


def test_an_INFERRED_value_from_a_dead_file_is_demoted_too():
    """The confidence tier is about how much we made up; it says nothing about whether the file
    still runs. Both tiers reach the manifest, so both have to be checked."""
    p = ManifestProposal(repo="/tmp/x", fields={"validate.lint": Proposal(
        field="validate.lint", value="ruff check .", confidence=INFERRED,
        evidence=[Evidence(path=DEAD, line=4)],
        candidates=[Candidate(value="ruff check .", confidence=INFERRED,
                              evidence=[Evidence(path=DEAD, line=4)])])})
    demote_disabled(p, [DEAD])
    assert p.fields["validate.lint"].value is None


# ── 3. the path the client reads ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("given,want", [
    (".github/workflows/ci.yml", ".github/workflows/ci.yml"),
    ("./.github/workflows/ci.yml", ".github/workflows/ci.yml"),
    ("/azure-pipelines.yml", "azure-pipelines.yml"),
    ("build\\ci.yml", "build/ci.yml"),
])
def test_a_path_is_normalised_without_being_MUTILATED(given, want):
    """`lstrip("./")` was the first thing written here, and `lstrip` takes a SET of characters —
    so `.github/workflows/ci.yml` came back as `github/workflows/ci.yml`, a file the client does
    not have, printed to them in a question about their own repository. Matching still worked,
    because both sides were corrupted identically, which is exactly why it would have survived
    every test that did not read the sentence."""
    assert _norm(given) == want


def test_the_dot_survives_end_to_end():
    p = _proposal(validate__lint=[("bandit -r src", "./.github/workflows/ci.yml")])
    demote_disabled(p, [".github/workflows/ci.yml"])
    assert p.fields["validate.lint"].value is None, "the two spellings did not match"
    assert ".github/workflows/ci.yml" in p.questions[0]


# ── 4. asking the forge ─────────────────────────────────────────────────────────────────────────

class _Forge:
    def __init__(self, answer):
        self.answer = answer
        self.asked: list[str] = []

    def disabled_ci_paths(self, repo=""):
        self.asked.append(repo)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_the_forge_is_asked_about_THIS_repository():
    forge = _Forge([DEAD])
    assert ask_the_forge(forge, "owner/name") == [DEAD]
    assert forge.asked == ["owner/name"], (
        "a multi-repo project would be told about a sibling's disabled pipelines")


def test_a_forge_without_the_capability_answers_HONESTLY():
    assert ask_the_forge(object(), "owner/name") is None


def test_a_forge_that_RAISES_never_stops_the_onboarding():
    """A capability that exists to improve a proposal must not be able to kill the onboarding
    that carries it."""
    assert ask_the_forge(_Forge(RuntimeError("403")), "owner/name") is None


def test_the_two_real_adapters_implement_it():
    from openfactory.adapters.forge.azure_devops import AzureReposForge
    from openfactory.adapters.forge.github import GitHubForge

    for kind in (GitHubForge, AzureReposForge):
        assert callable(getattr(kind, "disabled_ci_paths", None)), (
            f"{kind.__name__} cannot say which pipelines are switched off, so every one of its "
            f"deployments is back to proposing retired gates")


@pytest.mark.parametrize("state,dead", [
    ("disabled_manually", True), ("disabled_inactivity", True), ("disabled_fork", True),
    ("active", False), ("something_github_added_later", False),
])
def test_github_reads_the_state_and_keeps_an_UNKNOWN_one_live(state, dead, monkeypatch):
    """Listed rather than inverted (`!= "active"`). A state GitHub adds later must not silently
    demote a working gate — that is the expensive direction of this whole change."""
    from openfactory.adapters.forge.github import GitHubForge

    class Run:
        returncode = 0
        stdout = f"{state}\t.github/workflows/ci.yml\n"
        stderr = ""

    forge = GitHubForge.__new__(GitHubForge)
    object.__setattr__(forge, "repo", "o/r")
    monkeypatch.setattr(GitHubForge, "_gh_read", lambda self, args, what: Run())
    assert forge.disabled_ci_paths() == ([".github/workflows/ci.yml"] if dead else [])


def test_github_answers_NONE_when_the_api_will_not_talk(monkeypatch):
    from openfactory.adapters.forge.github import GitHubForge

    forge = GitHubForge.__new__(GitHubForge)
    object.__setattr__(forge, "repo", "o/r")
    monkeypatch.setattr(GitHubForge, "_gh_read", lambda self, args, what: None)
    assert forge.disabled_ci_paths() is None, (
        "an unreadable workflow list reads as 'nothing is disabled' — every gate is trusted again "
        "on the strength of a failed call")


# ── 5. it is actually wired in ──────────────────────────────────────────────────────────────────

def test_the_ONBOARDING_asks_before_it_writes_the_manifest():
    """The whole capability is worth nothing if the proposal is written first. Asserted on the
    ORDER, because that is the failure this would take: a demotion applied after the YAML was
    already produced changes a report and not a file."""
    import ast
    import inspect

    from openfactory.onboarding import onboard as mod

    src = inspect.getsource(mod._one_repo) if hasattr(mod, "_one_repo") else inspect.getsource(mod)
    tree = ast.parse(inspect.cleandoc("\n" + src))
    order = [n.func.id for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id in ("infer", "ask_the_forge", "demote_disabled", "to_manifest_dict")]
    assert order.index("infer") < order.index("demote_disabled") < order.index("to_manifest_dict"), (
        f"the demotion does not sit between reading the repo and writing the manifest: {order}")
    assert "ask_the_forge" in order
