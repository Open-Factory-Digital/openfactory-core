"""The outcome aggregates: what a deployment's factory did over a window, read from its journals and
its metrics store — counts and medians, each one `None` with its reason when it cannot be read
(#356, `observability/query.outcomes`).

THE THREE RULES, each held below on a deployment built on disk: a temporary registry, journals
under `OPENFACTORY_LOG_DIR`, and a `SqliteMetricsSink` in a temporary file, read back through the
same configured-sink door every other reader uses.

    THE ENDING IS READ, NEVER INFERRED   a job ended where the journal's ending line says
                                         (`record_outcome`, #131) — never at the box's last state
    UNMEASURED IS NULL, NEVER ZERO       no store, an unreadable store, no journal, nothing in the
                                         window to take a median of: `None`, and the reason
    COUNTS AND MEDIANS ONLY              never a ref, a title or a note anybody wrote

And `certify deployment` fills its pack's `outcomes` from this one function, and the pack still
names nobody.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from openfactory.lifecycle import record
from openfactory.observability import query
from openfactory.observability.metrics import MetricRecord
from openfactory.observability.sqlite_metrics import SqliteMetricsSink

UNTIL = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
SINCE = UNTIL - timedelta(days=90)
ROOT = Path(__file__).resolve().parent.parent


def at(days: float = 0, *, hours: float = 0) -> datetime:
    """A moment `days` before the window's end."""
    return UNTIL - timedelta(days=days, hours=hours)


class Deployment:
    """A registry, its journals and its store, all under one temporary directory."""

    def __init__(self, root: Path, monkeypatch, projects=("acme", "beta"), *,
                 journals: bool = True) -> None:
        self.root = root
        registry = {"projects": {name: {"name": name, "repo_path": str(root / name),
                                        "tracker": {"kind": "github", "repo": f"o/{name}"}}
                                 for name in projects}}
        (root / "registry.yaml").write_text(yaml.safe_dump(registry))
        monkeypatch.setenv("OPENFACTORY_REGISTRY", str(root / "registry.yaml"))
        monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(root / "logs"))
        monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
        monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(root / "metrics.db"))
        self.sink = SqliteMetricsSink(root / "metrics.db")
        self._seq: dict[tuple[str, str], int] = {}
        for name in projects if journals else ():
            # THE JOURNALS ARE WHERE THIS READS: a directory, empty until a job writes. Without
            # one for any project, the journals are unread, not empty (`query._journals`).
            (root / "logs" / name).mkdir(parents=True, exist_ok=True)

    # ── the journal, line by line, in the shapes its writers write ──────────────────────────────

    def journal(self, project: str, ref: str, *lines: dict) -> Path:
        path = self.root / "logs" / project / f"{ref}-events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            for line in lines:
                fh.write(json.dumps({"job_id": f"#{ref}", "ticket_id": f"#{ref}", **line}) + "\n")
        return path

    @staticmethod
    def box(state: str, when: datetime, reason: str | None = None) -> dict:
        """The box's own progress line (`machine._set_state`): a reason, never a `by`."""
        return {"ts": when.isoformat(), "kind": "state", "message": state,
                "data": {"reason": reason}}

    @staticmethod
    def ending(state: str, when: datetime, by: str = "the workflow",
               reason: str = "the job's own words about castello-tributos") -> dict:
        """`record_outcome`'s line (#131), or a stop's (#413) when `by` is a person."""
        return {"ts": when.isoformat(), "kind": "state", "message": state,
                "data": {"reason": reason, "by": by}}

    @staticmethod
    def review(decision: str, when: datetime) -> dict:
        return {"ts": when.isoformat(), "kind": "review", "message": f"{decision} (score 3)",
                "data": {"findings": 2}}

    # ── the store ───────────────────────────────────────────────────────────────────────────────

    def run(self, project: str, ref: str, role: str, when: datetime, cost=0.5) -> None:
        self.sink.record(MetricRecord(project=project, ticket=ref, ts=when.isoformat(),
                                      kind="agent_run", role=role, cost_usd=cost))

    def job_row(self, project: str, ref: str, when: datetime, stamp: dict | None = None) -> None:
        self.sink.record(MetricRecord(project=project, ticket=ref, ts=when.isoformat(),
                                      kind="job", role="_job_", state="merged",
                                      extra={"platform": stamp} if stamp is not None else {}))

    def move(self, project: str, card: str, event: str, after: str, when: datetime,
             **facts) -> None:
        seq = self._seq.get((project, card), 0) + 1
        self._seq[(project, card)] = seq
        assert record.write(self.sink, project, record.Row(
            card=card, seq=seq, event_id=f"{card}-{seq}", event=event, by="the workflow",
            after=after, facts=facts, ts=when.isoformat()))

    def outcomes(self, projects=("acme",), **kw) -> dict:
        return query.outcomes(list(projects), SINCE, UNTIL, **kw)


@pytest.fixture()
def d(tmp_path, monkeypatch) -> Deployment:
    return Deployment(tmp_path, monkeypatch)


def _one_job(d: Deployment, ref: str, ended_at: datetime, state: str = "merged", *,
             project: str = "acme", took: float = 2.0, pr_open: bool = True) -> None:
    """A durable job: the box's progress, the pull request, and the workflow's ending."""
    start = ended_at - timedelta(hours=took)
    lines = [d.box("spec_validation", start), d.box("implementing", start + timedelta(minutes=5))]
    if pr_open:
        lines.append(d.box("pr_open", start + timedelta(hours=took / 2)))
    d.journal(project, ref, *lines, d.ending(state, ended_at))


# ── the ending is read, never inferred ──────────────────────────────────────────────────────────

def test_a_jobs_ending_is_the_line_the_workflow_wrote_never_its_last_progress_mark(d):
    """`#89`'s journal, the shape #131 was written for: the box got to `pr_open`, and the workflow
    parked the job. The job ended `on_hold`. A journal with progress and no ending line — the
    attended driver writes none — is a job WITHOUT a recorded ending, never a `pr_open` one."""
    _one_job(d, "89", at(3), "on_hold")
    d.journal("acme", "90", d.box("implementing", at(2)), d.box("pr_open", at(1)))

    out = d.outcomes()

    assert out["jobs"] == 1
    assert out["ended"] == {"merged": 0, "done": 0, "on_hold": 1, "skipped": 0, "failed": 0}
    assert out["past_the_merge"] == 0
    assert out["without_a_recorded_ending"] == 1


def test_the_deploy_watchs_later_ending_is_not_another_job(d):
    """When the deploy is the card's last stage the watch records the card's ending AFTER the
    job's own `merged` (`_the_last_stage`). That is one job, which ended `merged`; the next job on
    the same card is the one whose progress follows."""
    _one_job(d, "7", at(10), "merged")
    d.journal("acme", "7", d.ending("done", at(9)))
    d.journal("acme", "7", d.box("implementing", at(5)), d.ending("failed", at(4)))

    out = d.outcomes()

    assert out["jobs"] == 2
    assert out["ended"]["merged"] == 1 and out["ended"]["done"] == 0
    assert out["ended"]["failed"] == 1
    assert out["past_the_merge"] == 1


def test_a_stop_is_an_ending_and_an_ending_nobody_defined_names_no_word_of_its_own(d):
    d.journal("acme", "3", d.box("implementing", at(6)), d.ending("skipped", at(5), by="ana"))
    d.journal("acme", "4", d.box("implementing", at(6)),
              d.ending("castello was here", at(5)))

    out = d.outcomes()

    assert out["ended"]["skipped"] == 1
    assert out["ended"]["unrecognised"] == 1 and "castello was here" not in json.dumps(out)


def test_a_job_is_in_the_window_where_it_ended(d):
    _one_job(d, "1", SINCE - timedelta(days=1))                  # ended before the window
    _one_job(d, "2", SINCE + timedelta(hours=1), took=5)         # began before, ended inside
    _one_job(d, "3", UNTIL + timedelta(days=1))                  # ended after it

    assert d.outcomes()["jobs"] == 1


def test_several_projects_read_as_one_deployment(d):
    _one_job(d, "1", at(4))
    _one_job(d, "1", at(3), "failed", project="beta")

    out = d.outcomes(projects=("acme", "beta"))

    assert out["projects"] == 2 and out["jobs"] == 2
    assert out["ended"]["merged"] == 1 and out["ended"]["failed"] == 1


# ── unmeasured is null, never zero ──────────────────────────────────────────────────────────────

def test_nothing_to_read_is_null_with_a_reason_for_every_measure(tmp_path, monkeypatch):
    """No journal directory and no readable store: not one measure is a number, and every one
    says why — a pack of zeros reads as a deployment that did nothing."""
    Deployment(tmp_path, monkeypatch, journals=False)
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "null")

    out = query.outcomes(["acme"], SINCE, UNTIL)

    assert out["status"] == "not_measured"
    assert all(out[m] is None for m in query.MEASURES), out
    assert set(out["not_measured"]) == set(query.MEASURES)
    assert all(reason.strip() for reason in out["not_measured"].values())
    assert "journal directory" in out["not_measured"]["jobs"]
    assert "no readable metrics store" in out["not_measured"]["parks"]


def test_an_unreadable_store_is_not_an_empty_one(d, monkeypatch):
    _one_job(d, "1", at(2))
    (d.root / "not-a-db").mkdir()
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(d.root / "not-a-db"))

    out = d.outcomes()

    assert out["jobs"] == 1, "the journals still answer what they can"
    for m in ("parks", "cost_per_merged_ticket_usd", "repair_passes", "needs_action",
              "versions", "reproofs"):
        assert out[m] is None and out["not_measured"][m] == query._UNREADABLE, m


def test_an_unreadable_journal_is_not_an_empty_one(d):
    _one_job(d, "1", at(2))
    (d.root / "logs" / "acme" / "2-events.jsonl").mkdir()

    out = d.outcomes()

    assert out["jobs"] is None and out["ended"] is None
    assert "could not be read" in out["not_measured"]["jobs"]


def test_a_median_of_nothing_is_null_not_zero(d):
    _one_job(d, "1", at(2), "on_hold", pr_open=False)

    out = d.outcomes()

    assert out["pickup_to_pr_open_seconds"] is None
    assert "opened a pull request" in out["not_measured"]["pickup_to_pr_open_seconds"]
    assert out["cost_per_merged_ticket_usd"] is None
    assert out["not_measured"]["cost_per_merged_ticket_usd"] == "no ticket merged in the window"


def test_proof_expiries_are_never_counted_because_nothing_records_one(d):
    out = d.outcomes()

    assert out["proof_expiries"] is None
    assert "never recorded" in out["not_measured"]["proof_expiries"]


# ── counts and medians ──────────────────────────────────────────────────────────────────────────

def test_a_merged_tickets_cost_is_every_pass_on_its_card_and_an_unpriced_pass_is_unknown(d):
    _one_job(d, "1", at(9))
    d.run("acme", "1", "executor", at(9, hours=1), cost=1.0)
    d.run("acme", "#1", "repair", at(30), cost=0.5)       # an earlier job's pass: still its card's
    _one_job(d, "2", at(8), "done")
    d.run("acme", "2", "executor", at(8, hours=1), cost=3.0)
    _one_job(d, "3", at(7))
    d.run("acme", "3", "executor", at(7, hours=1), cost=2.0)
    d.run("acme", "3", "review", at(7, hours=1), cost=None)   # no price: unknown, never free
    _one_job(d, "4", at(6), "failed")
    d.run("acme", "4", "executor", at(6, hours=1), cost=50.0)  # not merged
    d.run("beta", "1", "executor", at(9, hours=1), cost=90.0)  # another project's #1

    # BOTH PROJECTS READ AS ONE DEPLOYMENT, so `beta`'s #1 is in the rows — and is not `acme`'s
    cost = d.outcomes(projects=("acme", "beta"))["cost_per_merged_ticket_usd"]

    assert cost == {"median": 2.25, "p90": 3.0, "tickets": 2, "unpriced": 1}


def test_the_p90_is_a_cost_somebody_paid(d):
    for n in range(1, 11):
        _one_job(d, str(n), at(n))
        d.run("acme", str(n), "executor", at(n, hours=1), cost=float(n))

    cost = d.outcomes()["cost_per_merged_ticket_usd"]

    assert cost["p90"] == 9.0, "the 90th percentile was interpolated between two tickets"
    assert cost["median"] == 5.5


def test_pickup_to_pull_request_is_the_jobs_first_line_to_its_pr_open(d):
    _one_job(d, "1", at(5), took=2)                  # pr_open one hour after pickup
    _one_job(d, "2", at(4), took=6)                  # three hours
    _one_job(d, "3", at(3), "on_hold", pr_open=False)

    assert d.outcomes()["pickup_to_pr_open_seconds"] == {"median": 7200.0, "jobs": 2}


def test_review_rejections_and_repair_passes_are_counted_per_job(d):
    start = at(5)
    d.journal("acme", "1", d.box("implementing", start), d.review("rejected", start + timedelta(
        hours=1)), d.review("approved", start + timedelta(hours=2)),
        d.ending("merged", start + timedelta(hours=3)))
    for role in ("executor", "repair", "review_repair", "review"):
        d.run("acme", "1", role, start + timedelta(hours=2, minutes=50))
    d.run("acme", "1", "repair", start - timedelta(days=1))          # an earlier job's repair
    _one_job(d, "2", at(3))
    d.run("acme", "2", "executor", at(3, hours=1))
    _one_job(d, "3", at(2))                                             # no pass recorded at all

    out = d.outcomes()

    assert out["review_rejections"] == {"total": 1, "median_per_job": 0.0, "jobs": 3}
    assert out["repair_passes"] == {"total": 2, "median_per_job": 1.0, "jobs": 2,
                                    "unrecorded": 1}


def test_parks_are_read_into_the_tech_leads_classes_from_the_card_record(d):
    d.move("acme", "1", "filed", "backlog", SINCE - timedelta(days=5))
    d.move("acme", "1", "parked", "waiting_on_a_person", at(20), note="API rate limit exceeded")
    d.move("acme", "1", "resumed", "running", at(19))
    d.move("acme", "1", "parked", "waiting_on_a_person", at(18), note="zzz qqq")
    d.move("acme", "1", "resumed", "running", at(17))
    d.move("acme", "2", "parked", "waiting_on_a_person", SINCE - timedelta(days=1),
           note="Bad credentials")                                   # before the window

    parks = d.outcomes()["parks"]

    assert parks["transient"] == 1 and parks["unknown"] == 1 and parks["credential"] == 0
    assert set(parks) == set(query.PARK_CLASSES)


def test_parks_are_null_where_the_card_record_began_after_a_job_in_the_window(d):
    """The record exists since #414. A job that ran before it began parked without a row, and
    counting the record's parks would say that deployment parked less than it did."""
    _one_job(d, "1", at(40), "on_hold", took=5)
    d.move("acme", "2", "filed", "backlog", at(30))

    out = d.outcomes()

    assert out["parks"] is None and out["needs_action"] is None
    assert "began inside the window" in out["not_measured"]["parks"]


def test_a_card_record_that_began_before_the_window_covers_it(d):
    """Even for a job that started before the record began: the window's parks are all after it."""
    d.move("acme", "2", "filed", "backlog", SINCE - timedelta(days=1))
    _one_job(d, "1", SINCE + timedelta(days=1), "on_hold", took=72)

    out = d.outcomes()

    assert out["jobs"] == 1 and out["parks"] is not None and out["needs_action"] is not None


def test_needs_action_is_the_oldest_wait_at_the_windows_end(d):
    """Aged from the move that began the wait: a question asked of a parked card does not restart
    its clock. A card that was resumed is not waiting."""
    d.move("acme", "1", "filed", "backlog", SINCE - timedelta(days=1))
    d.move("acme", "1", "parked", "waiting_on_a_person", at(10))
    d.move("acme", "1", "question_asked", "waiting_on_a_person", at(2))
    d.move("acme", "2", "parked", "waiting_on_a_person", at(30))
    d.move("acme", "2", "resumed", "running", at(29))
    d.move("acme", "3", "parked", "waiting_on_a_person", at(4))
    d.move("acme", "3", "promised", "", at(1))

    assert d.outcomes()["needs_action"] == {"cards": 2, "oldest_days": 10.0}


def test_the_versions_seen_are_the_job_rows_stamps_and_an_old_row_is_unstamped(d):
    d.job_row("acme", "1", at(5), {"version": "0.6.0", "build": "abc123"})
    d.job_row("acme", "2", at(4), {"version": "0.6.0", "build": "abc123"})
    d.job_row("acme", "3", at(3), {"version": "0.6.1", "build": ""})
    d.job_row("acme", "4", at(2))
    d.job_row("acme", "5", at(1), {"version": "castello tributos", "build": "x"})

    versions = d.outcomes()["versions"]

    assert versions == {"seen": [{"version": "0.6.0", "build": "abc123", "attempts": 2},
                                 {"version": "0.6.1", "build": "", "attempts": 1}],
                        "unstamped": 2}


def test_every_job_row_carries_the_platform_that_ran_it(d):
    from openfactory import __version__
    from openfactory.observability.job_record import record_job

    record_job(project="acme", issue="9", ts=at(1).isoformat(), state="merged")

    out = d.outcomes()

    assert out["versions"]["seen"] == [{"version": __version__, "build": "", "attempts": 1}]


def test_reproofs_are_the_prove_passes_in_the_window(d):
    d.run("acme", "prove:acme", "prove", at(3))
    d.run("acme", "prove:acme", "prove", at(2))
    d.run("acme", "prove:acme", "prove", SINCE - timedelta(days=1))

    assert d.outcomes()["reproofs"] == 2


def test_a_measured_block_carries_no_ref_and_no_word_anybody_wrote(d):
    _one_job(d, "CASTELLO-12", at(2))
    d.run("acme", "CASTELLO-12", "executor", at(2, hours=1), cost=1.0)
    d.move("acme", "CASTELLO-12", "parked", "waiting_on_a_person", at(1),
           note="castello-tributos refused")

    said = json.dumps(d.outcomes()).lower()

    assert "castello" not in said and "12" not in said.replace("0.12", "")


# ── the definitions shared with the autonomy reading (#85) ──────────────────────────────────────

def _roles_the_orchestrator_counts() -> set[str]:
    tree = ast.parse((ROOT / "openfactory/orchestrator/machine.py").read_text())
    return {node.args[1].value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "_count"
            and len(node.args) == 2 and isinstance(node.args[1], ast.Constant)}


def test_the_shared_definitions_are_the_codes_own_vocabulary():
    """Matched to #85's autonomy reading, and held here to what the code actually records: every
    repair role is a role the orchestrator counts a pass under, every park class is a class the
    tech-lead's classifier can answer, every state past the merge is a job state."""
    import importlib

    from openfactory.contracts.state import JobState

    classify = importlib.import_module("openfactory.techlead.classify")
    assert query.REPAIR_ROLES <= _roles_the_orchestrator_counts()
    assert set(query.PARK_CLASSES) == set(classify._DECLARED)
    assert query.PAST_THE_MERGE <= {s.value for s in JobState}
    assert set(query.ENDINGS) <= {s.value for s in JobState}


# ── certify deployment reads it ─────────────────────────────────────────────────────────────────

def test_certify_deployment_fills_its_outcomes_from_the_journals_and_the_store(tmp_path,
                                                                               monkeypatch):
    from typer.testing import CliRunner

    from openfactory.certify.schema import validate
    from openfactory.cli import app
    from tests import certify_bed as bed

    bed.build(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    d = Deployment.__new__(Deployment)
    d.root, d.sink, d._seq = tmp_path, SqliteMetricsSink(tmp_path / "metrics.db"), {}
    now = datetime.now(UTC)
    d.move(bed.PROJECT, "12", "filed", "backlog", now - timedelta(days=100))
    d.journal(bed.PROJECT, "12", d.box("implementing", now - timedelta(days=2)),
              d.box("pr_open", now - timedelta(days=2) + timedelta(hours=1)),
              d.ending("merged", now - timedelta(days=1), reason=f"merged {bed.FOLHA}"))
    d.run(bed.PROJECT, "12", "executor", now - timedelta(days=1, hours=1), cost=1.25)

    result = CliRunner().invoke(app, ["certify", "deployment", "--partner", "altiva",
                                      "--profile", "standard", "--practitioner",
                                      bed.PRACTITIONER, "--dry-run"])

    assert result.exit_code == 0, result.output
    files = bed.files_of(result.output)
    document = bed.pack_json(files)
    assert validate(document) == []
    outcomes = document["outcomes"]
    assert outcomes["status"] == "measured" and outcomes["projects"] == 2
    assert outcomes["jobs"] == 1 and outcomes["ended"]["merged"] == 1
    assert outcomes["cost_per_merged_ticket_usd"]["median"] == 1.25
    assert "## Outcomes over the window" in files["summary.md"]
    everything = "\n".join(files.values()).lower()
    assert not [w for w in bed.FORBIDDEN if w.lower() in everything]
