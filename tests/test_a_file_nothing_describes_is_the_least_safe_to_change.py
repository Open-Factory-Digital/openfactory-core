"""The knowledge gate (ADR-0046): a file nothing describes is the least safe to change.

The bundle held three mechanical answers about any file — what it is (the inventory), whether its
kind was excused from description (the coverage table), whether what describes it still holds
(the checker) — and nothing read them together. The job pipeline opened every pull request in the
same words whether the change touched a file three concepts describe or a file nothing has ever
said a word about. `risk.py` already refuses to read "no component, no objection"; this is the
same stance one level down, and the reference gate's sentence is the one to keep: reading the gate
as "no concept, no objection" inverts it.

Verdicts per file, the change's stance, three modes the project declares (`advise` by default —
every project is dark before its first backfill), a section in the pull request every reader
sees, and under `enforce` a dark change parked with the question asked.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory.contracts.manifest import Manifest
from openfactory.contracts.run import RunResult, ValidationResult
from openfactory.contracts.state import JobState
from openfactory.contracts.ticket import AcceptanceCriterion, Ticket
from openfactory.knowledge.contracts import Concept, ConceptSource, OkfManifest
from openfactory.knowledge.gate import (
    AMBER,
    CLEAR,
    DARK,
    EXEMPT,
    GAP_BLOCKED,
    GREEN,
    NEW_FILE,
    NO_BUNDLE,
    NO_CONCEPT,
    STALE,
    FileVerdict,
    GateReport,
    changed_paths,
    judge,
    render_gate_lines,
)
from openfactory.knowledge.inventory import (
    coverage_by_kind,
    inventory_gaps,
    take_inventory,
    write_inventory,
)
from openfactory.knowledge.okf import write_okf
from openfactory.orchestrator.merge_policy import should_auto_merge

ROOT = Path(__file__).resolve().parents[1]


def _source(tmp_path: Path) -> Path:
    repo = tmp_path / "src"
    for rel, body in {
        "billing/rules.py": "def charge():\n    return 1\n",
        "billing/tax.py": "RATE = 0.2\n",
        "tests/test_rules.py": "def test():\n    pass\n",
        "settings.py": 'PASSWORD = "hunter2hunter2"\n',
        "example.env": 'TOKEN="${TOKEN}"\n',
        "odd.xyz": "?",
    }.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return repo


def _concept(path: str, fingerprint: str, title: str = "Billing rules") -> Concept:
    return Concept(type="policy", title=title, description="d", what_it_does="w",
                   sources=[ConceptSource(repo="r", path=path, commit="c1",
                                          fingerprint=fingerprint, lines="1-2")])


def _bundle(tmp_path: Path, repo: Path, *, concepts: list[Concept] | None = None,
            inventory: bool = True, rows: bool = True) -> Path:
    """A published bundle for `repo` — under a parent the machine may discard (the fetch's temp
    checkout is deleted through its parent, so the bundle sits one level down on purpose)."""
    bundle = tmp_path / "fetched" / "bundle"
    taken = take_inventory(repo, commit="c1")
    fps = {r.path: r.fingerprint for r in taken.files}
    concepts = (concepts if concepts is not None
                else [_concept("billing/rules.py", fps["billing/rules.py"])])
    manifest = OkfManifest(source_commit="c1",
                           coverage=coverage_by_kind(taken, concepts) if rows else [],
                           gaps=inventory_gaps(taken))
    write_okf(bundle, manifest=manifest, concepts=concepts)
    if inventory:
        write_inventory(bundle, taken)
    return bundle


def _verdict(tmp_path: Path, path: str, **over) -> FileVerdict:
    repo = _source(tmp_path)
    bundle = _bundle(tmp_path, repo, **over)
    (row,) = judge(bundle, repo, [path]).files
    return row


# --- the verdicts ----------------------------------------------------------------------------

def test_a_described_file_whose_bytes_hold_is_clear(tmp_path):
    row = _verdict(tmp_path, "billing/rules.py")
    assert row.verdict == CLEAR and row.concepts == ("Billing rules",)
    assert "described by 'Billing rules'" in row.reason


def test_a_file_nothing_describes_is_no_concept_and_the_change_is_dark(tmp_path):
    """THE INVERSION THIS FILE IS NAMED FOR."""
    repo = _source(tmp_path)
    report = judge(_bundle(tmp_path, repo), repo, ["billing/tax.py"])
    (row,) = report.files
    assert row.verdict == NO_CONCEPT and "nothing describes this code" in row.reason
    assert report.stance() == DARK


def test_an_excused_kind_is_exempt(tmp_path):
    row = _verdict(tmp_path, "tests/test_rules.py")
    assert row.verdict == EXEMPT and row.reason.startswith("test — ")


def test_a_file_the_bundle_never_saw_is_new_and_never_blocks(tmp_path):
    repo = _source(tmp_path)
    report = judge(_bundle(tmp_path, repo), repo, ["billing/new.py"])
    assert report.files[0].verdict == NEW_FILE and report.stance() == GREEN


def test_a_described_file_whose_bytes_moved_is_stale_and_the_change_is_amber(tmp_path):
    repo = _source(tmp_path)
    bundle = _bundle(tmp_path, repo)
    (repo / "billing" / "rules.py").write_text("def charge():\n    return 2\n", encoding="utf-8")
    report = judge(bundle, repo, ["billing/rules.py"])
    (row,) = report.files
    assert row.verdict == STALE and "'Billing rules' read bytes" in row.reason
    assert report.stance() == AMBER


def test_a_high_credential_risk_blocks_and_a_low_one_is_listed(tmp_path):
    repo = _source(tmp_path)
    rows = {r.path: r for r in judge(_bundle(tmp_path, repo), repo,
                                     ["settings.py", "example.env"]).files}
    assert rows["settings.py"].verdict == GAP_BLOCKED
    assert "credential-risk" in rows["settings.py"].reason
    assert "hunter2" not in rows["settings.py"].reason, "the gate repeated the value"
    assert rows["example.env"].verdict == EXEMPT, "a placeholder in an example file blocked"


def test_an_unplaced_file_blocks(tmp_path):
    row = _verdict(tmp_path, "odd.xyz")
    assert row.verdict == GAP_BLOCKED and row.reason.startswith("unclassified:")


def test_a_recorded_unknown_outranks_a_description(tmp_path):
    repo = _source(tmp_path)
    taken = take_inventory(repo)
    fp = next(r.fingerprint for r in taken.files if r.path == "settings.py")
    bundle = _bundle(tmp_path, repo, concepts=[_concept("settings.py", fp, "Settings")])
    (row,) = judge(bundle, repo, ["settings.py"]).files
    assert row.verdict == GAP_BLOCKED and row.concepts == ("Settings",)


def test_nothing_published_is_dark_for_every_file(tmp_path):
    repo = _source(tmp_path)
    report = judge(None, repo, ["billing/rules.py", "tests/test_rules.py"])
    assert {f.verdict for f in report.files} == {NO_BUNDLE}
    assert report.stance() == DARK and "run the backfill" in report.question()


def test_an_empty_bundle_is_no_bundle(tmp_path):
    repo = _source(tmp_path)
    (tmp_path / "empty").mkdir()
    (row,) = judge(tmp_path / "empty", repo, ["billing/rules.py"]).files
    assert row.verdict == NO_BUNDLE


def test_a_bundle_from_before_the_inventory_classifies_by_name(tmp_path):
    repo = _source(tmp_path)
    bundle = _bundle(tmp_path, repo, inventory=False, rows=False)
    rows = {r.path: r.verdict for r in judge(bundle, repo, [
        "tests/test_rules.py", "billing/tax.py", "billing/rules.py"]).files}
    assert rows == {"tests/test_rules.py": EXEMPT, "billing/tax.py": NO_CONCEPT,
                    "billing/rules.py": CLEAR}


# --- the stance ------------------------------------------------------------------------------

def test_the_worst_file_decides_the_stance(tmp_path):
    repo = _source(tmp_path)
    bundle = _bundle(tmp_path, repo)
    assert judge(bundle, repo, ["billing/rules.py", "tests/test_rules.py"]).stance() == GREEN
    assert judge(bundle, repo, ["billing/rules.py", "billing/tax.py"]).stance() == DARK
    (repo / "billing" / "rules.py").write_text("x = 1\n", encoding="utf-8")
    assert judge(bundle, repo, ["billing/rules.py", "tests/test_rules.py"]).stance() == AMBER


def test_an_empty_change_is_green_and_asks_nothing(tmp_path):
    repo = _source(tmp_path)
    report = judge(_bundle(tmp_path, repo), repo, [])
    assert report.stance() == GREEN and report.question() == "" and report.files == ()


def test_the_question_names_the_files_and_both_ways_out(tmp_path):
    repo = _source(tmp_path)
    report = judge(_bundle(tmp_path, repo), repo, ["billing/tax.py", "odd.xyz",
                                                    "billing/rules.py"])
    q = report.question()
    assert "1 file(s) nothing describes (`billing/tax.py`)" in q
    assert "1 with a recorded unknown (`odd.xyz` — unclassified:" in q
    assert "run the backfill" in q and "okf_concept_budget" in q and "merge by hand" in q
    assert judge(_bundle(tmp_path, repo), repo, ["billing/rules.py"]).question() == ""


def test_the_question_caps_the_names():
    files = tuple(FileVerdict(f"m/{i}.py", NO_CONCEPT, "nothing") for i in range(8))
    q = GateReport(files).question()
    assert "`m/5.py`, and 2 more" in q and "`m/6.py`" not in q


def test_the_summary_counts(tmp_path):
    repo = _source(tmp_path)
    report = judge(_bundle(tmp_path, repo), repo, ["billing/rules.py", "tests/test_rules.py",
                                                    "billing/tax.py"])
    assert report.summary() == ("knowledge gate: dark — 3 file(s): 1 clear, 1 exempt, "
                                "1 no-concept — bundle at c1")


def test_the_render_marks_each_verdict_and_caps_the_list():
    rows = [FileVerdict(f"f{i}.py", v, "why") for i, v in enumerate(
        [CLEAR, STALE, NO_CONCEPT] + [EXEMPT] * 27)]
    lines = render_gate_lines(rows, stance=DARK, mode="advise", bundle_note="bundle at c1",
                              question="ask")
    assert lines[0] == "## Knowledge"
    assert "**dark**" in lines[1] and "`advise` — informs, blocks nothing" in lines[1]
    assert lines[2].startswith("- 🟢 `f0.py` — clear")
    assert lines[3].startswith("- 🟡 `f1.py` — stale")
    assert lines[4].startswith("- 🔴 `f2.py` — no-concept")
    assert "- … and 6 more" in lines and lines[-1] == "> ask"


# --- the change set ----------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_changed_paths_sees_staged_unstaged_and_untracked(tmp_path):
    """The reference gate's own warning: a `diff --name-only` pipe drops the staged and the
    untracked paths — most of what a change ADDS — so the gate exits clean having never seen the
    file it would have blocked."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t.dev"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "a.py").write_text("a = 1\n")
    (repo / "old.py").write_text("o = 1\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    (repo / "a.py").write_text("a = 2\n")            # unstaged
    (repo / "b.py").write_text("b = 1\n")            # untracked
    (repo / "c.py").write_text("c = 1\n")
    _git(["add", "c.py"], repo)                      # staged
    _git(["mv", "old.py", "new.py"], repo)           # renamed, reported under its new name
    assert changed_paths(repo) == ["a.py", "b.py", "c.py", "new.py"]


def test_a_repository_git_cannot_read_yields_nothing(tmp_path):
    assert changed_paths(tmp_path / "nowhere") == []


# --- the setting and the merge policy ---------------------------------------------------------

def test_the_gate_is_advise_by_default_and_refuses_a_mode_it_does_not_know():
    assert Manifest().okf_gate == "advise"
    assert Manifest(okf_gate="enforce").okf_gate == "enforce"
    with pytest.raises(ValueError):
        Manifest(okf_gate="block")


def _mergeable(stance: str) -> RunResult:
    return RunResult(ticket_id="1", state=JobState.VALIDATING, knowledge_stance=stance,
                     validations=[ValidationResult(name="test", command="pytest",
                                                   exit_code=0, passed=True)])


def test_enforce_sends_amber_and_dark_to_a_person_and_advise_moves_nothing():
    enforce = Manifest(merge_policy="auto", okf_gate="enforce")
    assert should_auto_merge(enforce, _mergeable(GREEN))
    assert not should_auto_merge(enforce, _mergeable(AMBER))
    assert not should_auto_merge(enforce, _mergeable(DARK))
    advise = Manifest(merge_policy="auto", okf_gate="advise")
    assert should_auto_merge(advise, _mergeable(DARK)), "advise blocked — that is enforce"


# --- the station -----------------------------------------------------------------------------

def _job_repo(tmp_path: Path) -> Path:
    """The walking skeleton's repository, with one code file nothing describes."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True,
                   capture_output=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t.dev"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["remote", "add", "origin", str(origin)], repo)
    (repo / "README.md").write_text("# app\n")
    (repo / "app.py").write_text("VALUE = 1\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "init"], repo)
    _git(["push", "-u", "origin", "main"], repo)
    return repo


class _EditsAppAgent:
    """An executor that changes a file the bundle has no concept for."""

    def execute(self, *, sandbox, workspace, context):
        from openfactory.contracts.run import AgentRunResult
        (workspace.path / "app.py").write_text("VALUE = 2\n")
        return AgentRunResult(ok=True, summary="bumped app.py", cost_usd=0.01,
                              actions=["Edit: app.py"])

    def repair(self, *, sandbox, workspace, context, failure_log):
        from openfactory.contracts.run import AgentRunResult
        return AgentRunResult(ok=True)


def _run(tmp_path: Path, monkeypatch, *, mode: str, bundle: Path | None | Exception):
    from openfactory.orchestrator.machine import JobRunner
    from tests.test_walking_skeleton import FakeForge, FakeTracker, _runner

    repo = _job_repo(tmp_path)

    def fetched(self):
        if isinstance(bundle, Exception):
            raise bundle
        return bundle

    monkeypatch.setattr(JobRunner, "_published_okf", fetched)
    ticket = Ticket(id="#7", title="bump", objective="bump the value", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="app.py bumped")])
    tracker = FakeTracker(ticket)
    forge = FakeForge()
    runner = _runner(repo, tracker, Manifest(validate={"test": "true", "security": "true"},
                                             okf_gate=mode), tmp_path,
                     agent=_EditsAppAgent(), forge=forge)
    return runner.run("#7"), tracker, forge, repo


def _bundle_for_job(tmp_path: Path, repo: Path) -> Path:
    """A bundle whose inventory saw `app.py` and whose one concept cites the README only — under
    a temp root shaped like the fetch's own (`openfactory-knowledge*`), the only ancestor
    `discard_fetched_bundle` will delete: "only rmtree OUR OWN"."""
    bundle = tmp_path / "openfactory-knowledge-test" / "bundle"
    taken = take_inventory(repo, commit="c1")
    fp = next(r.fingerprint for r in taken.files if r.path == "README.md")
    concepts = [_concept("README.md", fp, "The app")]
    write_okf(bundle, manifest=OkfManifest(source_commit="c1",
                                           coverage=coverage_by_kind(taken, concepts),
                                           gaps=inventory_gaps(taken)), concepts=concepts)
    write_inventory(bundle, taken)
    return bundle


def test_under_advise_the_pull_request_carries_the_stance_and_the_job_proceeds(tmp_path,
                                                                                monkeypatch):
    repo = _job_repo(tmp_path / "a")
    bundle = _bundle_for_job(tmp_path, repo)
    result, tracker, forge, _ = _run(tmp_path / "b", monkeypatch, mode="advise", bundle=bundle)
    assert result.state is JobState.PR_OPEN, result.note
    assert result.knowledge_stance == DARK
    body = forge.opened["body"]
    assert "## Knowledge" in body and "knowledge gate: **dark** (`advise`" in body
    assert "- 🔴 `app.py` — no-concept: nothing describes this entry-point" in body
    assert "> this change touches 1 file(s) nothing describes (`app.py`)" in body
    assert not bundle.exists(), "the fetched bundle's temp checkout was not discarded"


def test_under_enforce_a_dark_change_is_parked_with_the_question_and_the_pr_open(tmp_path,
                                                                                   monkeypatch):
    repo = _job_repo(tmp_path / "a")
    bundle = _bundle_for_job(tmp_path, repo)
    result, tracker, forge, _ = _run(tmp_path / "b", monkeypatch, mode="enforce", bundle=bundle)
    assert result.state is JobState.ON_HOLD, result.note
    assert result.pr_url == "https://forge/pr/1" and forge.opened, "the work was lost"
    assert "knowledge gate — this change touches 1 file(s) nothing describes (`app.py`)" in (
        result.note or "")
    assert any("`app.py`" in c and "merge by hand" in c for c in tracker.comments), (
        tracker.comments)
    assert tracker.states[-1] is JobState.ON_HOLD
    assert result.knowledge_verdicts and result.knowledge_verdicts[0].path == "app.py"


def test_under_enforce_a_green_change_proceeds(tmp_path, monkeypatch):
    repo = _job_repo(tmp_path / "a")
    taken = take_inventory(repo, commit="c1")
    fp = next(r.fingerprint for r in taken.files if r.path == "app.py")
    bundle = tmp_path / "openfactory-knowledge-test" / "bundle"
    concepts = [_concept("app.py", fp, "The value")]
    write_okf(bundle, manifest=OkfManifest(source_commit="c1",
                                           coverage=coverage_by_kind(taken, concepts)),
              concepts=concepts)
    write_inventory(bundle, taken)
    result, tracker, forge, _ = _run(tmp_path / "b", monkeypatch, mode="enforce", bundle=bundle)
    assert result.state is JobState.PR_OPEN and result.knowledge_stance == GREEN
    assert "- 🟢 `app.py` — clear: described by 'The value'" in forge.opened["body"]


def test_off_judges_nothing(tmp_path, monkeypatch):
    result, _, forge, _ = _run(tmp_path, monkeypatch, mode="off",
                               bundle=RuntimeError("must not be fetched"))
    assert result.state is JobState.PR_OPEN and result.knowledge_stance == ""
    assert "## Knowledge" not in forge.opened["body"]


def test_nothing_published_is_said_and_the_job_proceeds_under_advise(tmp_path, monkeypatch):
    result, _, forge, _ = _run(tmp_path, monkeypatch, mode="advise", bundle=None)
    assert result.state is JobState.PR_OPEN and result.knowledge_stance == DARK
    assert "no-bundle: nothing is published for this repository" in forge.opened["body"]


def test_a_gate_that_cannot_run_says_so_and_never_fails_the_job(tmp_path, monkeypatch):
    result, _, forge, _ = _run(tmp_path, monkeypatch, mode="enforce",
                               bundle=RuntimeError("the context repository timed out"))
    assert result.state is JobState.PR_OPEN and result.knowledge_stance == ""
    assert "knowledge gate: could not run (the context repository timed out)" in (
        forge.opened["body"])


def test_the_station_judges_the_final_diff_before_the_push():
    """After the review-repair loop and before `publish_branch`: the diff it judges must be the
    one the pull request carries, and its stance must be in the body the push precedes."""
    from openfactory.orchestrator import machine
    src = Path(machine.__file__).read_text(encoding="utf-8")
    run = src[src.index("    def run("):src.index("    def repair_ci(")]
    gate = run.index("self._knowledge_gate(ticket, ws, base, result)")
    assert run.rindex("self.reviewer.review(", 0, gate) > 0, "the gate runs before the re-review"
    assert run.index("self.sandbox.publish_branch(", gate) > gate, "judged after the push"


# --- the CLI ---------------------------------------------------------------------------------

def test_the_cli_answers_with_an_exit_code(tmp_path):
    from typer.testing import CliRunner

    from openfactory.cli import app

    repo = _source(tmp_path)
    bundle = _bundle(tmp_path, repo)
    dark = CliRunner().invoke(app, ["knowledge", "gate", str(bundle), str(repo),
                                    "billing/tax.py"])
    assert dark.exit_code == 2 and "no-concept" in dark.output, dark.output
    green = CliRunner().invoke(app, ["knowledge", "gate", str(bundle), str(repo),
                                     "billing/rules.py"])
    assert green.exit_code == 0 and "clear" in green.output, green.output
    (repo / "billing" / "rules.py").write_text("x = 1\n", encoding="utf-8")
    amber = CliRunner().invoke(app, ["knowledge", "gate", str(bundle), str(repo),
                                     "billing/rules.py"])
    assert amber.exit_code == 1, amber.output
    none = CliRunner().invoke(app, ["knowledge", "gate", str(tmp_path / "nope"), str(repo),
                                    "billing/rules.py"])
    assert none.exit_code == 2 and "no-bundle" in none.output


def test_the_cli_reads_the_change_from_git_status(tmp_path):
    from typer.testing import CliRunner

    from openfactory.cli import app

    repo = _source(tmp_path)
    bundle = _bundle(tmp_path, repo)
    _git(["init", "-q", "-b", "main"], repo)
    (repo / "billing" / "tax.py").write_text("RATE = 0.3\n", encoding="utf-8")  # untracked
    out = CliRunner().invoke(app, ["knowledge", "gate", str(bundle), str(repo), "--changed"])
    assert out.exit_code == 2 and "`billing/tax.py` — no-concept" in out.output, out.output
