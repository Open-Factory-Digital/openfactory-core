"""`merge_policy: auto` is judged from the gates the forge's row listed — by one finding, once.

THE CHECK THAT COULD NOT FAIL. The doctor's oldest contradiction check, `merge_policy`, failed
`auto` when the forge answered `requires_review()`. No forge row ever defined that method: the
probe read it with `getattr`, found nothing, and answered False on every deployment. The two cases
that showed it failing did so through `requires_review=lambda: True` — a fake standing in for a row
that does not exist — so the suite was green over a check no repository could turn red.

And what it printed was a claim: *"merge_policy 'auto' is consistent with the repository's branch
protection"*, about protection nobody had read. Once the doctor began listing the gates (#184,
#206) the two lines sat one above the other, the first vouching for what the second failed
(measured 2026-09-19 with the real probe, the real GitHub row and a recorded ruleset that requires
one approval).

A required review is a blocking `process` gate in `merge_gates` on every row that can list one, so
the question is answered THERE, and only there:

    the class      no capability is asked of a forge row, by name, that no shipped row declares
    each forge     its own document requiring a review, through the real row and the real port
    the doctor     `auto` fails against a review that was read, is said to be UNCHECKED where
                   nothing was read, is consistent only with gates that were listed — and no
                   second finding speaks for the policy

The Azure DevOps shapes are Microsoft's documented ones (#184): no live organisation was read.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory import doctor
from openfactory.adapters.forge.azure_devops import AzureReposForge
from openfactory.adapters.forge.base import GatesNotListed, merge_gates_of
from openfactory.adapters.forge.github import GitHubForge
from openfactory.adapters.forge.local import LocalForge
from openfactory.contracts.project import Project, ProviderRef
from tests.pinned_probes import GREEN_ANSWERS, a_fully_pinned_probe_set
from tests.test_the_doctor_names_the_gates_only_a_person_settles import (
    BRANCH,
    RULES,
    _ado,
    _config,
)
from tests.test_the_doctor_never_says_no_gate_about_a_branch_it_could_not_read import (
    BRANCH_UNDER_CLASSIC_PROTECTION,
    NOT_FOUND,
    PROTECTION,
    RULES_THAT_GATE_NOTHING,
    _github,
)

ROOT = Path(__file__).resolve().parents[1]

# ═══ the class: a question nobody answers ═══════════════════════════════════════════════════════

SHIPPED_ROWS = (GitHubForge, AzureReposForge, LocalForge)


def _capabilities_asked_of_a_forge() -> dict[str, list[str]]:
    """Every `getattr(<something called forge>, "<name>", …)` in the package, PARSED: the name,
    and where it is asked. The subject is matched by what the code calls it, which is how the
    codebase spells a row capability (`base.py::merge_gates_of`, `display_name`, `checks.py`)."""
    asked: dict[str, list[str]] = {}
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr" and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and "forge" in ast.unparse(node.args[0]).lower()):
                asked.setdefault(node.args[1].value, []).append(
                    f"{path.relative_to(ROOT)}:{node.lineno}")
    return asked


def test_no_capability_is_asked_of_a_forge_row_that_no_shipped_row_declares():
    """An optional capability is asked with `getattr` so that a row which never heard of it keeps
    working. The price of that courtesy is that NOTHING fails when no row has heard of it: the
    caller's fallback becomes the only answer, and the branch behind a real one is reachable from
    a test double alone. `requires_review` lived that way from the first commit.

    A name is answered when a shipped row declares it, or when it is a field of the project's
    forge REFERENCE — the config object the same code also calls `forge`."""
    asked = _capabilities_asked_of_a_forge()
    assert {"merge_gates", "checks_are_typed", "closing_keyword"} <= set(asked), (
        "the scan no longer finds the capabilities it is known to hold — it guards nothing")

    orphans = {name: where for name, where in asked.items()
               if not any(hasattr(row, name) for row in SHIPPED_ROWS)
               and name not in ProviderRef.model_fields}

    assert not orphans, (
        f"asked of a forge row, and declared by none of {[r.__name__ for r in SHIPPED_ROWS]}: "
        f"{orphans} — whatever reads the answer can only ever read its own fallback")


def test_the_doctor_holds_no_probe_about_a_required_review_beside_the_gates():
    """ONE SOURCE. A probe of its own for the review would be a second read of the same rules,
    free to drift from the listing the merge watch is typed by."""
    names = {f.name for f in dataclasses.fields(doctor.Probes)}
    assert "merge_gates" in names
    assert not {n for n in names if "review" in n}, "a second probe answers for the review"


# ═══ each forge: a required review, read through the real row ═══════════════════════════════════

MIN_REVIEWERS = ("fa4e907d-c16b-4a4c-9dfa-4906e5d171dd", "Minimum number of reviewers")
REQUIRED_REVIEWERS = ("fd2167ab-b0be-447a-8ec8-39368250530e", "Required reviewers")


def _auto():
    return GREEN_ANSWERS["manifest"]().model_copy(update={"merge_policy": "auto"})


def _rows_requiring_a_review(monkeypatch, forge: str):
    if forge == "github-ruleset":
        return merge_gates_of(_github(monkeypatch, rules=RULES, branch=BRANCH), "main")
    if forge == "github-classic":
        return merge_gates_of(_github(monkeypatch, rules=[],
                                      branch=BRANCH_UNDER_CLASSIC_PROTECTION | {"name": "main"},
                                      protection=PROTECTION), "main")
    policy = MIN_REVIEWERS if forge == "azure-minimum-reviewers" else REQUIRED_REVIEWERS
    return merge_gates_of(_ado([_config(policy, blocking=True)]), "main")


FORGES_WITH_A_REVIEW = ["github-ruleset", "github-classic", "azure-minimum-reviewers",
                        "azure-required-reviewers"]


@pytest.mark.parametrize("forge", FORGES_WITH_A_REVIEW)
def test_auto_merge_against_a_required_review_fails__once__and_nothing_vouches_for_it(
        monkeypatch, forge):
    """THE CONTRADICTION THE OLD CHECK WAS WRITTEN FOR, from a document instead of a lambda."""
    rows = _rows_requiring_a_review(monkeypatch, forge)
    assert isinstance(rows, list) and rows, f"the {forge} fixture lists no gate"

    report = doctor.diagnose(a_fully_pinned_probe_set(manifest=_auto, merge_gates=lambda: rows))

    red = [f for f in report.findings if not f.ok]
    assert [f.check for f in red] == ["merge_gates"], [(f.check, f.message) for f in red]
    assert "review" in red[0].message.lower() and "merge_policy is 'auto'" in red[0].message
    assert "merge_policy: human" in red[0].remedy
    vouching = [f.message for f in report.findings
                if f.ok and ("consistent" in f.message or f.check == "merge_policy")]
    assert not vouching, f"a passing line vouches for the policy the line beside it fails: {vouching}"


@pytest.mark.parametrize("forge", FORGES_WITH_A_REVIEW)
def test_the_same_repository_under_human_merge_is_the_correct_setup(monkeypatch, forge):
    """The bot opens the pull request and a person approves and merges it. Flagging that would
    train people to ignore the doctor; it passes, and says who every pull request waits for."""
    rows = _rows_requiring_a_review(monkeypatch, forge)

    report = doctor.diagnose(a_fully_pinned_probe_set(merge_gates=lambda: rows))

    assert report.ok, [f.message for f in report.findings if not f.ok]
    got = next(f for f in report.findings if f.check == "merge_gates")
    assert "review" in got.note.lower() and "auto" not in got.message


def test_the_deployments_own_probes_fail_auto_merge_on_a_ruleset_that_requires_a_review(
        monkeypatch, tmp_path):
    """END TO END THROUGH `probes_for`: the registry builds the real row, the row reads the
    recorded ruleset, and the finding is red. This is the path on which the old check's probe
    answered False — it is what "no forge answers it" looked like from the inside."""
    def gh_read(self, args, what):
        body = BRANCH if args[1] == "repos/acme/x/branches/main" else RULES
        return SimpleNamespace(returncode=0, stdout=json.dumps(body), stderr="")

    monkeypatch.setattr(GitHubForge, "_gh_read", gh_read)
    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda _p: "static")
    monkeypatch.setattr(doctor, "load_manifest_quietly",
                        lambda _p: SimpleNamespace(base_branch="main"))
    real = doctor.probes_for(Project(name="demo", repo_path=str(tmp_path),
                                     tracker=ProviderRef(kind="github", repo="acme/x")))
    about_merging = {f.name: getattr(real, f.name) for f in dataclasses.fields(doctor.Probes)
                     if f.name in ("merge_gates", "requires_review")}

    report = doctor.diagnose(a_fully_pinned_probe_set(manifest=_auto, **about_merging))

    said = {f.check: f for f in report.findings if f.check.startswith("merge_")}
    assert list(said) == ["merge_gates"], f"more than one finding speaks of merging: {list(said)}"
    assert said["merge_gates"].ok is False
    assert "'Required approving reviews (1)'" in said["merge_gates"].message


# ═══ the doctor: what `auto` is told when nothing, or nothing in the way, was read ══════════════

def _finding(**over) -> doctor.Finding:
    report = doctor.diagnose(a_fully_pinned_probe_set(**over))
    return next(f for f in report.findings if f.check == "merge_gates")


def _refused(monkeypatch):
    return merge_gates_of(_github(monkeypatch, rules=RULES_THAT_GATE_NOTHING,
                                  branch=BRANCH_UNDER_CLASSIC_PROTECTION | {"name": "main"},
                                  protection=NOT_FOUND), "main")


@pytest.mark.parametrize("unlisted", ["none", "a-row-that-says-why", "github-classic-refused"])
def test_auto_merge_against_gates_nobody_could_read_is_said_to_be_unchecked(monkeypatch, unlisted):
    """NOT RED: nothing is known against the policy. NOT "CONSISTENT" EITHER — that is the one
    sentence an unread listing cannot carry, and it is the sentence the old check printed."""
    answer = {"none": lambda: None,
              "a-row-that-says-why": lambda: GatesNotListed("the policy service is switched off"),
              "github-classic-refused": lambda: _refused(monkeypatch)}[unlisted]()
    assert not isinstance(answer, list)

    report = doctor.diagnose(a_fully_pinned_probe_set(manifest=_auto, merge_gates=lambda: answer))
    got = next(f for f in report.findings if f.check == "merge_gates")

    assert got.ok is True and "could not be listed ahead of a pull request" in got.message
    assert "merge_policy is 'auto'" in got.message and "NOT checked" in got.message
    assert "not checked" in got.note and "'auto'" in got.note, "the closing verdict will not say it"
    assert not [f.message for f in report.findings if "consistent" in f.message]


def test_under_human_merge_an_unread_listing_says_what_it_said_and_nothing_about_auto():
    got = _finding(merge_gates=lambda: None)
    assert got.ok is True and got.note == ""
    assert got.message.endswith("will be asked about on the first card instead of named here")


def test_an_unreadable_manifest_beside_an_unread_listing_is_judged_as_human__with_a_trace(caplog):
    """The policy is read on EVERY path now. A missing manifest is its own finding; this one must
    not turn it into a sentence about `auto`, and must not swallow it either."""
    def unreadable():
        raise FileNotFoundError("no manifest at .openfactory/project.yaml")

    with caplog.at_level("DEBUG", logger=doctor.log.name):
        got = _finding(merge_gates=lambda: None, manifest=unreadable)

    assert got.ok is True and "auto" not in got.message and got.note == ""
    assert "judging the merge gates" in caplog.text


@pytest.mark.parametrize("listed", ["local", "github-no-gate-about-the-pull-request"])
def test_auto_merge_is_consistent_only_with_gates_that_were_listed(monkeypatch, tmp_path, listed):
    """The half of the old sentence that can be TRUE, built from a read: the row listed its gates
    and none of them needs a person."""
    rows = (merge_gates_of(LocalForge("p", str(tmp_path), db_path=tmp_path / "board.db"), "main")
            if listed == "local" else
            merge_gates_of(_github(monkeypatch, rules=RULES_THAT_GATE_NOTHING, branch=BRANCH),
                           "main"))
    assert rows == []

    auto, human = (_finding(merge_gates=lambda: rows, manifest=_auto),
                   _finding(merge_gates=lambda: rows))

    assert auto.ok is True and "(0 gate(s) read) — merge_policy 'auto' is consistent with them" \
        in auto.message
    assert human.ok is True and "merge_policy" not in human.message
