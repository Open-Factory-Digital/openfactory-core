"""#206 — on GitHub, the doctor never says "no gate needs a person" about gates it could not see.

GitHub has TWO mechanisms that gate a merge, and #184's listing read one. `rules/branches/<b>`
answers the active RULESETS to anybody with read access. Classic branch protection —
`branches/<b>/protection`, still what most existing repositories use — is shown only to a
repository administrator, which the factory's credential should not be. So a repository gated by
classic protection answered `[]`, and the doctor said *"no gate on this repository needs a person
on every pull request (0 gate(s) read)"* about a branch that requires two approvals: absence read
as compliance, in the one finding written to stop the first card from meeting a gate the hard way.

WHAT WAS MEASURED, 2026-09-19, read-only, with a `repo`-scoped OAuth token (`gh` 2.83.2):

    branches/<b>              readable by anybody who can read the repository. `protected` is
                              true for a RULESET too; `protection.enabled` is what says CLASSIC
                              (false on a branch gated only by a ruleset). It carries the classic
                              required status checks and nothing else — not the required reviews.
    branches/<b>/protection   as a non-admin: 404 "Not Found", on every public repository tried.
                              As an ADMIN of a branch with no classic protection: 404 "Branch
                              not protected".
    rules/branches/<b>        `[]` for a branch that does not exist; `branches/<b>` then 404s.

WHAT COMES FROM GITHUB'S DOCUMENTATION, not from a live answer — no repository this credential
administers uses classic protection, and no fine-grained or installation token was at hand: the
READABLE protection document (the REST description's own example, its lists of people trimmed) and
the two 403 refusals ("Resource not accessible by personal access token" / "… by integration").

Every case drives the real row through its `_gh_read` seam, one recorded answer PER ROUTE — a fake
that answers every path alike is how the first version of this listing came to be believed — and
reads the finding from the real `diagnose`.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from openfactory import doctor
from openfactory.adapters.forge.base import merge_gates_of
from openfactory.adapters.forge.github import GitHubForge
from tests.pinned_probes import GREEN_ANSWERS, a_fully_pinned_probe_set
from tests.test_the_doctor_names_the_gates_only_a_person_settles import RULES

DOCS = "https://docs.github.com/rest/branches/branch-protection#get-branch-protection"

# ═══ the recorded answers ═══════════════════════════════════════════════════════════════════════

#: LIVE — `branches/main` of the repository #184's `RULES` were recorded from: gated by a ruleset,
#: no classic protection. `protected` is TRUE here, which is why it cannot be the discriminator.
BRANCH_UNDER_A_RULESET = {"name": "main", "protected": True, "protection": {
    "enabled": False,
    "required_status_checks": {"checks": [], "contexts": [], "enforcement_level": "off"}}}

#: LIVE — a topic branch of the same repository.
BRANCH_UNPROTECTED = {"name": "topic", "protected": False, "protection": {
    "enabled": False,
    "required_status_checks": {"checks": [], "contexts": [], "enforcement_level": "off"}}}

#: LIVE — `cli/cli@trunk`, read as a non-admin: what classic protection shows to everybody.
BRANCH_UNDER_CLASSIC_PROTECTION = {"name": "trunk", "protected": True, "protection": {
    "enabled": True,
    "required_status_checks": {
        "checks": [{"app_id": None, "context": "build (macos-latest)"},
                   {"app_id": None, "context": "build (ubuntu-latest)"}],
        "contexts": ["build (macos-latest)", "build (ubuntu-latest)"],
        "enforcement_level": "non_admins"}}}

#: LIVE — `cli/cli@trunk` also has a ruleset, and it holds no gate about the pull request.
RULES_THAT_GATE_NOTHING = [
    {"type": "copilot_code_review", "ruleset_source_type": "Repository",
     "ruleset_source": "cli/cli", "ruleset_id": 4898070,
     "parameters": {"review_on_push": False, "review_draft_pull_requests": True}}]

#: DOCUMENTED — the example GitHub's REST description gives for a readable protection, its lists
#: of users, teams and apps trimmed, and `required_signatures` added as its schema spells it.
PROTECTION = {
    "url": "https://api.github.com/repos/octocat/Hello-World/branches/master/protection",
    "required_status_checks": {
        "contexts": ["continuous-integration/travis-ci"],
        "enforcement_level": "non_admins"},
    "enforce_admins": {"enabled": True},
    "required_pull_request_reviews": {
        "dismiss_stale_reviews": True, "require_code_owner_reviews": True,
        "required_approving_review_count": 2, "require_last_push_approval": True},
    "required_linear_history": {"enabled": True},
    "allow_force_pushes": {"enabled": True},
    "allow_deletions": {"enabled": True},
    "required_conversation_resolution": {"enabled": True},
    "required_signatures": {"enabled": True},
    "lock_branch": {"enabled": False},
    "allow_fork_syncing": {"enabled": True},
}


def _answer(body, *, returncode=0, stderr=""):
    return SimpleNamespace(returncode=returncode, stderr=stderr,
                           stdout=body if isinstance(body, str) else json.dumps(body))


def _refusal(message: str, status: int):
    """What `gh api` hands back for an HTTP error: the JSON body on stdout, the sentence on
    stderr, exit status 1. LIVE for the two 404s; the 403s are the documented messages."""
    return _answer({"message": message, "documentation_url": DOCS, "status": str(status)},
                   returncode=1, stderr=f"gh: {message} (HTTP {status})")


NOT_FOUND = _refusal("Not Found", 404)                                    # live: a non-admin
NOT_PROTECTED = _refusal("Branch not protected", 404)                     # live: an admin
FINE_GRAINED = _refusal("Resource not accessible by personal access token", 403)   # documented
INSTALLATION = _refusal("Resource not accessible by integration", 403)             # documented
BRANCH_NOT_FOUND = _refusal("Branch not found", 404)                      # live


def _github(monkeypatch, *, rules, branch, protection=None, base="main"):
    """The real row, its `_gh_read` answered PER ROUTE. A route nobody recorded fails the case:
    a read this listing was not expected to make is a finding, not a default."""
    f = GitHubForge("acme/x")
    routes = {f"repos/acme/x/rules/branches/{base}": rules,
              f"repos/acme/x/branches/{base}": branch,
              f"repos/acme/x/branches/{base}/protection": protection}
    asked: list[str] = []

    def gh_read(args, what):
        # `pytest.fail`, NOT `assert`: the port turns an `Exception` from a row into "could not be
        # listed", which is what half these cases expect — an AssertionError would pass them.
        if args[0] != "api" or len(args) != 2:
            pytest.fail(f"not a plain read: {args}")
        asked.append(args[1].removeprefix("repos/acme/x/"))
        got = routes.get(args[1])
        if got is None:
            pytest.fail(f"the listing read {args[1]}, which this case did not expect")
        return got if isinstance(got, SimpleNamespace) else _answer(got)

    monkeypatch.setattr(f, "_gh_read", gh_read)
    f.asked = asked
    return f


def _finding(forge, *, base="main", **over) -> doctor.Finding:
    """The finding the REAL `diagnose` writes from the real row's answer, through the port."""
    report = doctor.diagnose(a_fully_pinned_probe_set(
        merge_gates=lambda: merge_gates_of(forge, base), **over))
    return next(f for f in report.findings if f.check == "merge_gates")


def _auto_manifest():
    return GREEN_ANSWERS["manifest"]().model_copy(update={"merge_policy": "auto"})


def _named(rows):
    return [(r["name"], r["kind"]) for r in rows]


NO_GATE = "no gate on this repository needs a person"
NOT_LISTED = "could not be listed ahead of a pull request"


# ═══ classic protection only, and this credential may not read it — the defect ══════════════════

@pytest.mark.parametrize("refusal", [NOT_FOUND, FINE_GRAINED, INSTALLATION],
                         ids=["404-oauth-or-classic-token", "403-fine-grained", "403-installation"])
def test_a_branch_protected_by_rules_it_may_not_read_is_never_called_ungated(monkeypatch, refusal):
    f = _github(monkeypatch, rules=[], branch=BRANCH_UNDER_CLASSIC_PROTECTION, protection=refusal)

    answer = merge_gates_of(f, "main")
    got = _finding(f, manifest=_auto_manifest)

    assert not isinstance(answer, list), f"gates nobody could read were listed as {answer}"
    assert got.ok is True and NOT_LISTED in got.message
    assert NO_GATE not in got.message
    assert "first card" in got.message


def test_the_person_is_told_why__in_the_rows_words_not_in_a_log(monkeypatch):
    """"The read failed" sends somebody to look for a failure. Nothing failed: GitHub shows
    classic protection to administrators only, and the way to have the gates named is to move
    them where read access can see them — which only the row can know."""
    f = _github(monkeypatch, rules=[], branch=BRANCH_UNDER_CLASSIC_PROTECTION,
                protection=NOT_FOUND)

    got = _finding(f)

    assert "classic branch protection" in got.message
    assert "administrator" in got.message and "ruleset" in got.message
    assert "Not Found (HTTP 404)" in got.message, "what GitHub answered is not in the finding"
    assert "this forge has no way to list them" not in got.message, \
        "the row said why, and the finding still guesses"
    assert got.message.count("..") == 0 and " ." not in got.message


def test_the_refused_read_leaves_a_trace(monkeypatch, caplog):
    f = _github(monkeypatch, rules=[], branch=BRANCH_UNDER_CLASSIC_PROTECTION,
                protection=FINE_GRAINED)
    with caplog.at_level("INFO", logger="openfactory.forge.github"):
        merge_gates_of(f, "main")
    assert "Resource not accessible by personal access token" in caplog.text
    assert "acme/x@main" in caplog.text


def test_a_ruleset_beside_unreadable_classic_rules_does_not_make_the_listing_whole(monkeypatch):
    """LIVE SHAPE (`cli/cli@trunk`): a ruleset that gates nothing about the pull request, beside
    classic protection. The ruleset answered, so the first read "worked" — and the gates are
    still unseen."""
    f = _github(monkeypatch, rules=RULES_THAT_GATE_NOTHING,
                branch=BRANCH_UNDER_CLASSIC_PROTECTION, protection=NOT_FOUND, base="trunk")

    got = _finding(f, base="trunk")

    assert not isinstance(merge_gates_of(f, "trunk"), list)
    assert NOT_LISTED in got.message and NO_GATE not in got.message


def test_a_gate_the_ruleset_already_names_is_still_named_beside_unreadable_classic_rules(
        monkeypatch):
    """The listing is known to be incomplete — and it already holds a gate only a person settles.
    Every sentence built from it stays true, and under auto-merge it is the failure it was before:
    answering "could not be listed" here would un-name a gate that was read."""
    f = _github(monkeypatch, rules=RULES, branch=BRANCH_UNDER_CLASSIC_PROTECTION,
                protection=NOT_FOUND)

    rows = merge_gates_of(f, "main")
    got = _finding(f, manifest=_auto_manifest)

    assert _named(rows) == [("Required approving reviews (1)", "process"),
                            ("Conversation resolution", "process"),
                            ("test", "unknown"),
                            ("build (macos-latest)", "unknown"),
                            ("build (ubuntu-latest)", "unknown")], \
        "what everybody may read of the classic rules — its required checks — was not listed"
    assert got.ok is False and "'Required approving reviews (1)'" in got.message


# ═══ classic protection, readable ═══════════════════════════════════════════════════════════════

def test_classic_protection_an_administrator_may_read_is_typed_like_the_rulesets(monkeypatch):
    f = _github(monkeypatch, rules=[], branch=BRANCH_UNDER_CLASSIC_PROTECTION,
                protection=PROTECTION)

    rows = merge_gates_of(f, "main")

    assert f.asked == ["rules/branches/main", "branches/main", "branches/main/protection"]
    assert _named(rows) == [
        ("Required approving reviews (2)", "process"),
        ("Code owner review", "process"),
        ("Conversation resolution", "process"),
        ("Signed commits", "process"),
        ("continuous-integration/travis-ci", "unknown"),
    ], "a rule about the merge method was listed as a gate, or a gate was missed"
    assert all(r["blocking"] is True for r in rows)
    assert all(r.get("remedy") for r in rows if r["kind"] == "process")
    assert all("remedy" not in r for r in rows if r["kind"] == "unknown")


def test_the_doctor_names_the_classic_gates__and_fails_under_auto_merge(monkeypatch):
    f = _github(monkeypatch, rules=[], branch=BRANCH_UNDER_CLASSIC_PROTECTION,
                protection=PROTECTION)

    human, auto = _finding(f), _finding(f, manifest=_auto_manifest)

    assert human.ok is True and "'Required approving reviews (2)'" in human.note
    assert "'Signed commits'" in human.message and "travis" not in human.message
    assert auto.ok is False and "4 gate(s)" in auto.message


def test_a_locked_branch_is_a_gate_only_a_person_lifts(monkeypatch):
    locked = {**PROTECTION, "required_pull_request_reviews": None,
              "required_conversation_resolution": {"enabled": False},
              "required_signatures": {"enabled": False}, "lock_branch": {"enabled": True}}
    f = _github(monkeypatch, rules=[], branch=BRANCH_UNDER_CLASSIC_PROTECTION, protection=locked)

    rows = merge_gates_of(f, "main")

    assert _named(rows) == [("Locked branch", "process"),
                            ("continuous-integration/travis-ci", "unknown")]
    assert "unlock" in rows[0]["remedy"].lower()


def test_classic_rules_that_require_no_person_are_read_as_no_gate__truthfully(monkeypatch):
    """"Require a pull request", zero approvals, and a status check: READ, and none needs a
    person. This is the one road by which a classically protected branch may hear "no gate".

    `checks` ALONE, where the documented example (`PROTECTION`) says `contexts` alone and a live
    answer says both: GitHub is closing `contexts` down, and a listing that read only the older
    list would lose every required check on the day it goes."""
    nobody = {"required_pull_request_reviews": {"required_approving_review_count": 0,
                                                "require_code_owner_reviews": False},
              "required_status_checks": {"checks": [{"context": "lint", "app_id": 15368}]},
              "required_conversation_resolution": {"enabled": False},
              "required_signatures": {"enabled": False}, "lock_branch": {"enabled": False}}
    f = _github(monkeypatch, rules=[], branch=BRANCH_UNDER_CLASSIC_PROTECTION, protection=nobody)

    assert _named(merge_gates_of(f, "main")) == [("lint", "unknown")]
    assert NO_GATE in _finding(f).message and "(1 gate(s) read)" in _finding(f).message


# ═══ both mechanisms, both readable ═════════════════════════════════════════════════════════════

def test_both_mechanisms_are_one_listing__and_a_gate_both_set_is_named_once(monkeypatch):
    same_review = {**PROTECTION, "required_pull_request_reviews": {
        "required_approving_review_count": 1, "require_code_owner_reviews": True}}
    f = _github(monkeypatch, rules=RULES, branch=BRANCH_UNDER_CLASSIC_PROTECTION,
                protection=same_review)

    assert _named(merge_gates_of(f, "main")) == [
        ("Required approving reviews (1)", "process"),          # the ruleset's, and classic's too
        ("Conversation resolution", "process"),                  # likewise
        ("test", "unknown"),
        ("Code owner review", "process"),                        # classic's alone
        ("Signed commits", "process"),
        ("continuous-integration/travis-ci", "unknown"),
    ]


# ═══ rulesets only, neither, unprotected ════════════════════════════════════════════════════════

def test_a_branch_under_a_ruleset_alone_is_listed_as_before__and_the_admin_read_is_not_made(
        monkeypatch):
    """LIVE SHAPE. `protected` is TRUE for a branch a ruleset gates, so reading it as "classic"
    would send every ruleset repository to an administrator's route to be refused."""
    f = _github(monkeypatch, rules=RULES, branch=BRANCH_UNDER_A_RULESET)

    rows = merge_gates_of(f, "main")

    assert f.asked == ["rules/branches/main", "branches/main"]
    assert _named(rows) == [("Required approving reviews (1)", "process"),
                            ("Conversation resolution", "process"), ("test", "unknown")]
    assert "'Required approving reviews (1)'" in _finding(f).message


@pytest.mark.parametrize("rules, branch, read", [
    ([], BRANCH_UNPROTECTED, 0),
    (RULES_THAT_GATE_NOTHING, BRANCH_UNDER_A_RULESET, 0),
], ids=["unprotected", "a-ruleset-with-no-gate-in-it"])
def test_a_branch_with_no_classic_rules_and_no_gate_is_told_so__truthfully(
        monkeypatch, rules, branch, read):
    f = _github(monkeypatch, rules=rules, branch=branch)

    assert merge_gates_of(f, "main") == []
    assert f"{NO_GATE} on every pull request ({read} gate(s) read)" in _finding(f).message


def test_an_administrator_told_there_is_no_classic_protection_is_believed(monkeypatch):
    """A `branches/<b>` that does not say `protection.enabled` — GitHub's own documented example
    does not — leaves `protected: true` to mean either mechanism, so the protection is asked
    for. LIVE: an administrator of a branch without classic rules hears 404 "Branch not
    protected", which is an answer about the rules; "Not Found" is an answer about the asker."""
    unsaid = {"name": "main", "protected": True, "protection": {
        "required_status_checks": {"enforcement_level": "off", "contexts": []}}}

    admin = _github(monkeypatch, rules=[], branch=unsaid, protection=NOT_PROTECTED)
    other = _github(monkeypatch, rules=[], branch=unsaid, protection=NOT_FOUND)

    assert merge_gates_of(admin, "main") == []
    assert not isinstance(merge_gates_of(other, "main"), list)
    assert NO_GATE not in _finding(other).message


# ═══ a read that did not answer ═════════════════════════════════════════════════════════════════

def test_a_branch_that_could_not_be_read_is_not_a_branch_without_classic_rules(monkeypatch):
    """LIVE: `rules/branches/<b>` answers `[]` for a branch that does not exist, and
    `branches/<b>` 404s. "No gate" about a branch nobody found is the same absence read as
    compliance."""
    f = _github(monkeypatch, rules=[], branch=BRANCH_NOT_FOUND)

    got = _finding(f)

    assert not isinstance(merge_gates_of(f, "main"), list)
    assert NOT_LISTED in got.message and NO_GATE not in got.message
    assert "Branch not found (HTTP 404)" in got.message


@pytest.mark.parametrize("branch", ["<html>", "[]", '"main"', ""],
                         ids=["not-json", "a-list", "a-string", "nothing"])
def test_a_branch_answer_nobody_understands_is_not_an_unprotected_branch(monkeypatch, branch):
    f = _github(monkeypatch, rules=[], branch=_answer(branch))
    assert not isinstance(merge_gates_of(f, "main"), list)
    # SAID, not stumbled into: an AttributeError three lines later would also be "not a list".
    assert "(an answer that could not be understood)" in _finding(f).message


def test_a_protection_answer_nobody_understands_is_not_an_absence_of_rules(monkeypatch):
    f = _github(monkeypatch, rules=[], branch=BRANCH_UNDER_CLASSIC_PROTECTION,
                protection=_answer("[]"))
    assert not isinstance(merge_gates_of(f, "main"), list)
    assert NO_GATE not in _finding(f).message
    assert "(an answer that could not be understood)" in _finding(f).message


def test_unreadable_rulesets_are_still_not_an_empty_listing__and_nothing_else_is_asked(
        monkeypatch):
    f = _github(monkeypatch, rules=_refusal("Not Found", 404), branch=BRANCH_UNPROTECTED)

    assert merge_gates_of(f, "main") is None
    assert f.asked == ["rules/branches/main"]
    assert "this forge has no way to list them, or the read failed" in _finding(f).message


def test_a_gh_that_never_answered_the_protection_read_is_a_refusal_too(monkeypatch):
    """`_gh_read` folds a hung or missing `gh` into None (its docstring). For this read that is
    "could not see the rules", with the same consequence as a 404."""
    f = _github(monkeypatch, rules=[], branch=BRANCH_UNDER_CLASSIC_PROTECTION, protection=NOT_FOUND)
    routed = f._gh_read
    monkeypatch.setattr(f, "_gh_read", lambda args, what: (
        None if args[1].endswith("/protection") else routed(args, what)))

    assert not isinstance(merge_gates_of(f, "main"), list)
    assert NO_GATE not in _finding(f).message
    assert "(gh did not answer)" in _finding(f).message
