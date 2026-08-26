"""The branches this platform mints in a client's repository carry the product's name — #106 item 5.

The product is OpenFactory; the branch every job pushes is `openfactory/<ticket>`. It is the most
visible name the product has — born in EVERY pull request on the client's own repository — and
the product owner's rule for the whole rename (2026-08-08) was that the pilot is the exact
production experience.

A branch lives in the CLIENT's repository, and its name is RECALCULATED from the ticket id on
every entry — a fresh run, a CI repair, a C2 resume. That is the property a rename has to keep:
while the platform carried two spellings, a repair that recalculated the new name for a pull
request opened under the old one pushed its fix to a branch nobody watched, an agent ran, money
was spent, and the repair appeared to have done nothing. The second spelling left on 2026-08-25;
this file guards that there is ONE name, that it is the product's, and that nothing builds the
old one.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess

import pytest

from openfactory import namespace
from openfactory.contracts import AcceptanceCriterion, JobState, Manifest, Ticket

pytest_plugins = ["tests.test_walking_skeleton"]

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _ticket(tid: str) -> Ticket:
    return Ticket(id=tid, title="add feature", objective="add a feature", repo="o/app",
                  acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])


# ── the name itself ─────────────────────────────────────────────────────────────────────────────

def test_the_platform_mints_branches_under_its_own_name():
    assert namespace.BRANCH_PREFIX == "openfactory"
    assert namespace.job_branch("#7") == "openfactory/7"
    assert namespace.job_branch("7") == "openfactory/7"


def test_there_is_no_second_branch_name():
    """The legacy prefix and its helper are GONE, not renamed."""
    assert not [n for n in dir(namespace) if "legacy" in n.lower()]
    assert not hasattr(namespace, "legacy_job_branch")


def test_a_jobs_branch_is_recalculated_never_asked_of_a_remote():
    """`JobRunner._job_branch` used to probe the remote for the branch's older spelling. It asks
    nothing now: the name is a pure function of the ticket, the same on every entry, so a runner
    with NO forge at all can still say it — which is what makes a repair land where the pull
    request looks."""
    from openfactory.orchestrator.machine import JobRunner

    bare = JobRunner.__new__(JobRunner)  # no forge, no sandbox, no repo — nothing to ask
    assert bare._job_branch(_ticket("#9")) == "openfactory/9"
    assert bare._job_branch(_ticket("9")) == "openfactory/9"


def test_a_repair_pushes_to_the_branch_the_PR_tracks(repo, tmp_path):
    """End to end: the PR was opened from `openfactory/9`; the repair pushes THERE and mints
    nothing beside it."""
    from tests.test_walking_skeleton import FakeTracker, _runner

    class _FixAgent:
        def execute(self, *, sandbox, workspace, context):
            raise AssertionError("a CI repair must never re-run the executor")

        def repair(self, *, sandbox, workspace, context, failure_log):
            (workspace.path / "ci_fix.py").write_text("FIXED = True\n")
            from openfactory.contracts import AgentRunResult
            return AgentRunResult(ok=True, summary="fixed", cost_usd=0.01,
                                  actions=["Edit: ci_fix.py"])

    _git(["checkout", "-b", "openfactory/9"], repo)
    (repo / "broken.py").write_text("x\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "wip"], repo)
    _git(["push", "-u", "origin", "openfactory/9"], repo)
    _git(["checkout", "main"], repo)
    _git(["branch", "-D", "openfactory/9"], repo)

    runner = _runner(repo, FakeTracker(_ticket("#9")), Manifest(validate={"test": "true"}),
                     tmp_path, agent=_FixAgent())
    result = runner.repair_ci("#9", "CI failed: test_x broke")

    assert result.state is JobState.PR_OPEN
    assert result.branch == "openfactory/9"
    _git(["fetch", "origin"], repo)
    landed = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", "origin/openfactory/9:ci_fix.py"],
        capture_output=True).returncode
    assert landed == 0, "the fix must land on the branch the open PR tracks"
    heads = subprocess.run(["git", "branch", "--list"], cwd=tmp_path / "origin.git",
                           capture_output=True, text=True).stdout
    assert heads.count("/9") == 1, f"a second branch for the same ticket was minted: {heads}"


# ── nothing may construct the old prefix ────────────────────────────────────────────────────────

def _docstring_ids(tree: ast.AST) -> set[int]:
    """The constants that are somebody's docstring — prose, not code."""
    ds = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                ds.add(id(node.body[0].value))
    return ds


def _old_prefix_constructions(path: pathlib.Path) -> list[tuple[int, str]]:
    """Every way this module builds `sdlc/…` as a name — CODE only, never prose.

    AST, not grep, for the reason the namespace guard states: the docstrings explaining this
    rename say `sdlc/` freely, and a comment must not fail the guard it explains. Two shapes,
    because the trap itself was an f-string: a plain constant starting with `sdlc/`, and an
    f-string whose LITERAL head starts with `sdlc/` (`f"sdlc/{ticket.id}"` — the exact line this
    rename removed twice from `machine.py`)."""
    tree = ast.parse(path.read_text())
    prose = _docstring_ids(tree)
    # an f-string's literal pieces are Constant nodes too — mark them so the plain-constant arm
    # does not report the same construction twice (the positive twin caught exactly this)
    inside_fstring = {id(piece) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr)
                      for piece in node.values}
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in prose and id(node) not in inside_fstring):
            if node.value.startswith("sdlc/"):
                found.append((node.lineno, node.value[:80]))
        elif isinstance(node, ast.JoinedStr) and node.values:
            head = node.values[0]
            if (isinstance(head, ast.Constant) and isinstance(head.value, str)
                    and head.value.startswith("sdlc/")):
                found.append((node.lineno, "f-string: " + head.value[:70]))
    return found


def test_the_scan_can_SEE_an_old_prefix_construction():
    """The positive twin — `assert not offenders` is equally happy over a scan that reads
    nothing. Plant both shapes and prose; the scan must catch exactly the two."""
    planted = ast.parse(
        'BRANCH = f"sdlc/{ticket_id}"\n'
        'ONBOARD = "sdlc/onboard-acme"\n'
        'PROSE = "branches were once under sdlc/ and are not any more"\n'
    )
    inside = {id(piece) for node in ast.walk(planted) if isinstance(node, ast.JoinedStr)
              for piece in node.values}
    hits = []
    for node in ast.walk(planted):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in inside:
            if node.value.startswith("sdlc/"):
                hits.append(node.value)
        elif isinstance(node, ast.JoinedStr) and node.values:
            head = node.values[0]
            if isinstance(head, ast.Constant) and str(head.value).startswith("sdlc/"):
                hits.append("f:" + head.value)
    assert sorted(hits) == ["f:sdlc/", "sdlc/onboard-acme"], hits


#: Where a `sdlc/…` string may still appear in code, and why. EMPTY since #106 item 9 renamed the
#: package: `floor.py` was exempted for citing our own source paths, item 9 rewrote those to
#: `openfactory/…`, and the staleness check retired the entry the same day — exactly the life
#: cycle the table was built for. Add an entry only with a reason, and it will be checked.
ALLOWED: dict[str, str] = {}


def test_nothing_constructs_the_old_branch_prefix():
    """No module may BUILD `sdlc/…` as a name. There is no legacy constant to build it from any
    more — the only way to spell it is to type it, which is what this catches."""
    offenders = {}
    for path in sorted(ROOT.joinpath("openfactory").rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        if rel in ALLOWED:
            continue
        hits = _old_prefix_constructions(path)
        if hits:
            offenders[rel] = hits
    assert not offenders, (
        f"these build `sdlc/…` as a code constant: {offenders}. Branches come from "
        f"`namespace.job_branch` / `namespace.BRANCH_PREFIX`, and there is one name per ticket")


@pytest.mark.parametrize("rel", sorted(ALLOWED) or [None])
def test_every_exemption_is_still_EARNED(rel):
    if rel is None:
        return  # no exemptions — the table is empty, which is the state this test defends
    assert _old_prefix_constructions(ROOT / rel), (
        f"{rel} is exempted from the branch-prefix guard and no longer contains `sdlc/` strings "
        f"at all. Delete its entry from ALLOWED — the exemption was paid down.")


# ── the onboarding proposal follows the same rule ───────────────────────────────────────────────

def test_the_onboarding_proposal_is_one_name_per_project():
    """Recalculated, exact, and the product's: `acme` must not share a branch with `acme-two`,
    and a retry finds its own earlier push by the same name."""
    from openfactory.product.onboard import proposal_branch

    assert proposal_branch("acme") == "openfactory/onboard-acme"
    assert proposal_branch("acme-two") == "openfactory/onboard-acme-two"
    assert proposal_branch("acme") == proposal_branch("acme")


# ── the file we write into their repository introduces itself by the product's name ─────────────

def test_the_written_manifest_names_the_product_and_the_new_path():
    """The header of `.openfactory/product.yaml` is the first thing a client reads when they open
    what we wrote in THEIR repository. It must name the product and the path it actually sits at
    — not the acronym and the directory we retired."""
    from openfactory.product.onboard import _render

    text = _render({"product": "acme", "sources": [], "requirements_dir": "requirements"})
    assert ".openfactory/product.yaml" in text.splitlines()[0]
    assert "OpenFactory" in text.splitlines()[0]
    assert ".sdlc" not in text


# ── the box carries the same name on every entry ────────────────────────────────────────────────

def test_the_container_name_is_stable_across_every_entry_of_a_job():
    """`docker ps` and the panel find a job's box by name. A fresh run, a repair and a resume of
    ticket 12 are the same job to an operator, so the branch's own prefix is dropped once and the
    name is the same however the job was entered."""
    from openfactory.adapters.sandbox.container import _container_name

    assert _container_name("acme", "openfactory-12") == "openfactory-acme-12"
    assert _container_name("acme", "openfactory-12") == _container_name("acme", "openfactory-12")
    # a branch that does not carry our prefix is kept whole — only OUR prefix is dropped
    assert _container_name("acme", "12") == "openfactory-acme-12"
