"""#184 — `doctor` names the repository's merge gates that no change to the code settles.

WHAT IT COST TO LEARN THIS FROM A CARD. A repository policy a team never satisfies — linking a
work item, on the deployment that reported it — is rejected on every pull request. The first card
discovered it, by burning two repair passes on an empty log and parking `CI still failing`. The
merge watch now asks a person instead; this is the same fact said BEFORE any card runs, with who
has to act.

Through a ROW CAPABILITY, not a vendor branch in the doctor: a forge that can list its gates ahead
of a pull request answers `merge_gates(base=...)` with the rows `pr_checks` already types, and a
forge that cannot says nothing — which the doctor reports as "not listed here", never as "none".

    each forge     its own listing mapped into the rows: Azure DevOps (policy configurations),
                   GitHub (the branch's ruleset rules), the local forge, and a stranger
    the doctor     the finding, for every answer the probe can give, under both merge policies
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openfactory import doctor
from openfactory.adapters.azure_devops import AzureDevOpsError
from openfactory.adapters.forge.base import merge_gates_of
from openfactory.adapters.forge.github import GitHubForge
from openfactory.adapters.forge.local import LocalForge
from tests.pinned_probes import GREEN_ANSWERS, a_fully_pinned_probe_set
from tests.test_the_ado_forge import FX_ADO_REPO, REPO_ID
from tests.test_the_ado_forge import forge as ado_forge

ROOT = Path(__file__).resolve().parents[1]

# ═══ Azure DevOps: policy configurations ════════════════════════════════════════════════════════

BUILD = ("0609b952-1397-4640-95ec-e00a01b2c241", "Build")
WORK_ITEMS = ("40e92b44-2fe1-4dd6-b3d8-74a9c21d0c6e", "Work item linking")
COMMENTS = ("c6a1889d-b943-4856-b76f-9e46bb6b0df2", "Comment requirements")
OTHER_REPO = "6866361a-36cf-44ce-a547-5b330a251e47"


def _config(policy, *, blocking, repo=REPO_ID, ref="refs/heads/main", match="Exact",
            enabled=True, deleted=False, name=""):
    """One `policy/configurations` record, in the shape Azure DevOps documents for it."""
    type_id, shown = policy
    settings = {"scope": [{"repositoryId": repo, "refName": ref, "matchKind": match}]}
    if name:
        settings["displayName"] = name
    return {"isEnabled": enabled, "isDeleted": deleted, "isBlocking": blocking,
            "type": {"id": type_id, "displayName": shown}, "settings": settings}


def _ado(configs):
    return ado_forge({"GET policy/configurations": {"value": configs},
                      "GET git/repositories/fx-ado": FX_ADO_REPO})


def test_ado_lists_this_branchs_policies_typed_the_way_the_watch_will_meet_them():
    f = _ado([_config(WORK_ITEMS, blocking=True),
              _config(COMMENTS, blocking=False),
              _config(BUILD, blocking=True, name="fx-ado-ci")])

    rows = {r["name"]: r for r in merge_gates_of(f, "main")}

    assert rows["Work item linking"]["blocking"] is True
    assert rows["Work item linking"]["kind"] == "process"
    assert "Link a work item" in rows["Work item linking"]["remedy"]
    assert rows["Comment requirements"]["blocking"] is False
    assert rows["fx-ado-ci"]["kind"] == "code" and "remedy" not in rows["fx-ado-ci"]


def test_ado_leaves_out_what_gates_nothing_here():
    """A sibling repository's policy (the project holds them all — C-18), another branch's, a
    disabled one and a deleted one. A folder of branches (`Prefix`) that contains this one is in."""
    f = _ado([_config(WORK_ITEMS, blocking=True, repo=OTHER_REPO, name="theirs"),
              _config(WORK_ITEMS, blocking=True, ref="refs/heads/release", name="another branch"),
              _config(WORK_ITEMS, blocking=True, enabled=False, name="switched off"),
              _config(WORK_ITEMS, blocking=True, deleted=True, name="deleted"),
              _config(COMMENTS, blocking=True, ref="refs/heads/", match="Prefix", name="folder"),
              _config(COMMENTS, blocking=True, repo=None, ref=None, name="project-wide")])

    assert [r["name"] for r in merge_gates_of(f, "main")] == ["folder", "project-wide"]


def test_ado_an_unreadable_listing_is_not_an_empty_one():
    f = ado_forge({}, raises={"GET policy/configurations": AzureDevOpsError("GET … → 403")})
    assert merge_gates_of(f, "main") is None


# ═══ GitHub: the branch's ruleset rules ═════════════════════════════════════════════════════════

#: Recorded from `gh api repos/<owner>/<repo>/rules/branches/main` on a live repository,
#: 2026-09-19 — with a required status check added, in the shape GitHub documents for that rule.
RULES = [
    {"type": "deletion", "parameters": {}},
    {"type": "non_fast_forward", "parameters": {}},
    {"type": "required_linear_history", "parameters": {}},
    {"type": "pull_request", "parameters": {"require_code_owner_review": False,
                                            "required_approving_review_count": 1,
                                            "required_review_thread_resolution": True}},
    {"type": "required_status_checks",
     "parameters": {"required_status_checks": [{"context": "test"}]}},
]


def _github(monkeypatch, *, stdout="", returncode=0):
    f = GitHubForge("acme/x")
    asked: list[list[str]] = []

    def gh_read(args, what):
        asked.append(args)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(f, "_gh_read", gh_read)
    f.asked = asked
    return f


def test_github_lists_the_rules_about_the_pull_request_and_only_those(monkeypatch):
    f = _github(monkeypatch, stdout=json.dumps(RULES))

    rows = merge_gates_of(f, "main")

    assert f.asked == [["api", "repos/acme/x/rules/branches/main"]]
    assert [(r["name"], r["kind"]) for r in rows] == [
        ("Required approving reviews (1)", "process"),
        ("Conversation resolution", "process"),
        ("test", "unknown"),
    ], "a rule about the branch or the merge method was listed as a gate, or a gate was missed"
    assert all(r["blocking"] is True for r in rows)
    assert "approve" in rows[0]["remedy"]


def test_github_an_unreadable_listing_is_not_an_empty_one(monkeypatch):
    assert merge_gates_of(_github(monkeypatch, returncode=1), "main") is None
    assert merge_gates_of(_github(monkeypatch, stdout="<html>"), "main") is None
    assert merge_gates_of(_github(monkeypatch, stdout="[]"), "main") == []


# ═══ the local forge, a stranger, a double ══════════════════════════════════════════════════════

def test_the_local_forge_was_asked_and_has_none(tmp_path):
    f = LocalForge("p", str(tmp_path), db_path=tmp_path / "board.db")
    assert merge_gates_of(f, "main") == []


def test_a_forge_that_cannot_list_its_gates_says_nothing__and_a_double_is_not_an_answer():
    assert merge_gates_of(object(), "main") is None
    assert merge_gates_of(MagicMock(), "main") is None, "a mock's answer was taken for a listing"

    class Raises:
        def merge_gates(self, *, base):
            raise RuntimeError("503")

    assert merge_gates_of(Raises(), "main") is None


# ═══ the doctor ═════════════════════════════════════════════════════════════════════════════════

WORK_ITEM_GATE = {"name": "Work item linking", "blocking": True, "kind": "process",
                  "remedy": "Link a work item to the pull request."}


def _finding(**over) -> doctor.Finding:
    report = doctor.diagnose(a_fully_pinned_probe_set(**over))
    return next(f for f in report.findings if f.check == "merge_gates")


def _auto_manifest():
    return GREEN_ANSWERS["manifest"]().model_copy(update={"merge_policy": "auto"})


def test_a_gate_only_a_person_settles_is_named_with_what_that_person_does():
    """ACCEPTANCE 5. Under `merge_policy: human` somebody is already at the merge, so it passes —
    with the gate named in the message AND in the note the closing verdict repeats."""
    got = _finding(merge_gates=lambda: [WORK_ITEM_GATE,
                                        {"name": "build", "blocking": True, "kind": "code"}])
    assert got.ok is True
    assert "'Work item linking'" in got.message
    assert "Link a work item to the pull request." in got.message
    assert "never sends an agent" in got.message and "'build'" not in got.message
    assert "'Work item linking'" in got.note


def test_under_auto_merge_it_is_a_failure_and_says_who_has_to_act():
    got = _finding(merge_gates=lambda: [WORK_ITEM_GATE], manifest=_auto_manifest)
    assert got.ok is False and "'Work item linking'" in got.message
    assert "administers this repository's branch policies" in got.remedy
    assert "merge_policy: human" in got.remedy


def test_an_unreadable_manifest_does_not_take_the_gate_check_down_with_it(caplog):
    """A missing manifest is its own finding, reported once. This check still names the gate —
    judged as `human`, the policy under which nothing is claimed about the factory landing it
    alone — and leaves a trace of having done so (`test_no_silent_failures` found the first
    version of this handler saying nothing at all)."""
    def unreadable():
        raise FileNotFoundError("no manifest at .openfactory/project.yaml")

    with caplog.at_level("DEBUG", logger=doctor.log.name):
        report = doctor.diagnose(a_fully_pinned_probe_set(
            merge_gates=lambda: [WORK_ITEM_GATE], manifest=unreadable))
    got = next(f for f in report.findings if f.check == "merge_gates")

    assert got.ok is True and "'Work item linking'" in got.message
    assert "judging the merge gates" in caplog.text


@pytest.mark.parametrize("rows", [
    [],
    [{**WORK_ITEM_GATE, "blocking": False}],                       # optional: the case seen
    [{"name": "build", "blocking": True, "kind": "code"}],         # a change to the code settles it
    [{"name": "license/cla", "blocking": True, "kind": "unknown"}],
    [{**WORK_ITEM_GATE, "blocking": "yes"}],                       # a row that did not SAY
])
def test_what_is_not_a_blocking_process_gate_is_not_named(rows):
    got = _finding(merge_gates=lambda: rows, manifest=_auto_manifest)
    assert got.ok is True and "no gate on this repository needs a person" in got.message


@pytest.mark.parametrize("unlisted", [None, MagicMock(), "none"])
def test_a_listing_that_could_not_be_made_is_said_so__never_read_as_no_gates(unlisted):
    got = _finding(merge_gates=lambda: unlisted)
    assert got.ok is True and "could not be listed ahead of a pull request" in got.message
    assert "no gate" not in got.message


def test_an_older_probe_set_gets_no_finding_rather_than_an_invented_one():
    report = doctor.diagnose(a_fully_pinned_probe_set(merge_gates=None))
    assert "merge_gates" not in [f.check for f in report.findings]


def test_the_doctor_names_no_vendor_about_gates():
    """Parsed, not grepped: string constants in the check's and the probe's CODE, docstrings
    excluded (they tell the incident)."""
    tree = ast.parse((ROOT / "openfactory/doctor.py").read_text())
    said = []
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name in ("_merge_gates", "_merge_gates_probe"):
            doc = fn.body[0].value if isinstance(fn.body[0], ast.Expr) else None
            said += [n.value for n in ast.walk(fn)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str) and n is not doc]
    assert len(said) > 5, "the two functions were not found — this guard guards nothing"
    for vendor in ("github", "azure", "gitlab", "work item", "ruleset"):
        assert vendor not in " ".join(said).lower(), f"the doctor's gate check says {vendor!r}"


def test_the_deployments_probe_asks_the_row_and_mints_nothing(monkeypatch, tmp_path):
    """The real `probes_for`: the probe builds the forge with the static token only, asks through
    `merge_gates_of` for the manifest's base branch, and hands back the row's answer."""
    from openfactory.contracts.project import Project, ProviderRef

    built: list[dict] = []

    class Row:
        def merge_gates(self, *, base):
            return [{**WORK_ITEM_GATE, "name": f"gate on {base}"}]

    def build(project, **kw):
        built.append(kw)
        return Row()

    monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge", build)
    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda _p: "static")
    monkeypatch.setattr(doctor, "load_manifest_quietly",
                        lambda _p: SimpleNamespace(base_branch="develop"))
    project = Project(name="demo", repo_path=str(tmp_path),
                      tracker=ProviderRef(kind="github", repo="acme/demo"))

    rows = doctor.probes_for(project).merge_gates()

    assert [r["name"] for r in rows] == ["gate on develop"]
    assert built == [{"token": "static"}], f"the probe built its forge with {built}"
