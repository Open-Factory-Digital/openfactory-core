"""Autonomy is a number read from the card's record, and it never claims more than the record holds
(#85, hole 4).

Every pass a job makes is an `agent_run` row tagged with its role, and every card's life is a
record of transitions (ADR-0055). Nothing read the two together, so "how often does a card land
with nobody stepping in?" had no answer but twenty job pages. `observability/autonomy.py` reads
them; this file holds it to the definitions, against a REAL SQLite store in a temp directory, rows
written by the real writers (`lifecycle/record.write`, `observability/job_record.record_job`):

  · a card is MEASURED only when its record holds `promoted` before its first `merged` — the rest
    are BEFORE THE RECORD, named, and never in a rate;
  · first-pass is no repair-role pass and no `parked` / `resumed` / `adjusted` between the
    promotion and the merge — and only those: a question or an acceptance is a designed gate;
  · the yield is `None`, never 0, with nothing measured; rework counts only code-writing passes;
  · an effect's outcome row is not a transition, the record beats the job's row, and a ref that is
    not a number joins its passes all the same;
  · a park nobody can classify is `unknown`, never `transient`;
  · the CLI and the dashboard's block are one answer, in the project's language, and a store that
    will not answer is said as that — exit 2 — never read as an empty record.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from openfactory.lifecycle import record
from openfactory.observability.autonomy import REPAIR_ROLES, autonomy
from openfactory.observability.job_record import record_job

#: The cards' day: each transition a minute after the one before it.
DAY = "2026-10-05"


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A deployment whose metrics store is a real SQLite file, with an English project (`acme`)
    and a Portuguese one (`loja`) registered."""
    from openfactory.contracts.project import Project
    from openfactory.observability.sqlite_metrics import SqliteMetricsSink
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    for env in ("OPENFACTORY_PANEL_TOKEN", "OPENFACTORY_PANEL_TOKENS",
                "OPENFACTORY_PRODUCT_TOKENS", "OPENFACTORY_METRICS_TABLE"):
        monkeypatch.delenv(env, raising=False)
    reg = ProjectRegistry()
    reg.add(Project(name="acme", repo_path=str(tmp_path / "acme")))
    reg.add(Project(name="loja", repo_path=str(tmp_path / "loja"), language="pt-BR"))
    return SqliteMetricsSink(tmp_path / "metrics.db")


def life(sink, card: str, *events, project: str = "acme", day: str = DAY) -> list[record.Row]:
    """`card`'s record, one transition per event — a name, or `(name, facts)`."""
    rows = []
    for seq, event in enumerate(events, 1):
        name, facts = event if isinstance(event, tuple) else (event, {})
        row = record.Row(card=card, seq=seq, event_id=f"{card}-{seq}", event=name, by="test",
                         facts=facts, ts=f"{day}T10:{seq:02d}:00+00:00")
        assert record.write(sink, project, row)
        rows.append(row)
    return rows


def passes(card: str, *roles: str, project: str = "acme", state: str = "pr_open",
           ts: str = f"{DAY}T11:00:00+00:00") -> None:
    """One job's rows for `card`, as the job writes them when it ends: a pass per role."""
    record_job(project=project, issue=card, ts=ts, state=state,
               agent_runs=[{"role": role} for role in roles])


def measure(project: str = "acme", **kw) -> dict:
    from openfactory.api.metrics_view import scan_all_or_raise

    return autonomy(scan_all_or_raise(), project, **kw)


def four_cards(sink) -> None:
    """The issue's four: A clean, B with one CI repair, C parked then resumed, D never promoted."""
    life(sink, "A", "promoted", "pr_opened", "merged")
    passes("A", "planner", "executor", "review")
    life(sink, "B", "promoted", "pr_opened", "merged")
    passes("B", "executor", "ci_repair")
    life(sink, "C", "promoted",
         ("parked", {"job_state": "on_hold", "note": "API rate limit exceeded"}),
         "resumed", "pr_opened", "merged")
    passes("C", "executor", ts=f"{DAY}T10:30:00+00:00")
    passes("C", "executor")
    life(sink, "D", "pr_opened", "merged")
    passes("D", "executor", "repair", "repair")


def _cli(*args: str):
    from openfactory.cli import app

    return CliRunner().invoke(app, ["autonomy", *args])


def _api(project: str) -> dict:
    from openfactory.api import app as api

    got = TestClient(api.app).get("/api/metrics", params={"project": project})
    assert got.status_code == 200, got.text
    return got.json()


# ── 1. the four cards ───────────────────────────────────────────────────────────────────────────

def test_the_four_cards_yield_one_in_three_and_the_unpromoted_one_is_named_apart(store):
    four_cards(store)

    got = measure()

    assert (got["measured"], got["first_pass"]) == (3, 1), got
    assert got["yield"] == pytest.approx(1 / 3, abs=1e-4)
    assert got["before_the_record"] == ["D"], "D's merge was measured without its start"
    assert got["code_passes"] == 5, "A 1 + B 2 + C 2 — D is not measured, and nothing else writes"
    assert got["rework_rate"] == pytest.approx(5 / 3, abs=1e-4)
    assert got["repair_depth"] == {"0": 2, "1": 1, "2": 0, "3+": 0}
    assert got["park_reasons"] == {"transient": 1} and got["parks"] == 1


@pytest.mark.parametrize("role", sorted(REPAIR_ROLES))
def test_each_repair_role_alone_costs_the_card_its_first_try(store, role):
    assert set(REPAIR_ROLES) == {"repair", "suppression_repair", "review_repair", "ci_repair",
                                 "recovery"}, "the roles `machine.py::_count` tags as repair"
    life(store, "12", "promoted", "pr_opened", "merged")
    passes("12", "executor", role)

    got = measure()

    assert (got["measured"], got["first_pass"]) == (1, 0), f"{role} did not count as a repair"
    assert got["repair_depth"]["1"] == 1 and got["code_passes"] == 2


@pytest.mark.parametrize("event", ["parked", "resumed", "adjusted"])
def test_each_intervention_alone_costs_the_card_its_first_try(store, event):
    life(store, "12", "promoted", event, "pr_opened", "merged")
    passes("12", "executor")

    assert measure()["first_pass"] == 0, f"{event} between promotion and merge was not seen"


@pytest.mark.parametrize("event", ["question_asked", "accepted"])
def test_a_designed_gate_is_not_somebody_stepping_in(store, event):
    life(store, "12", "promoted", event, "pr_opened", "merged")
    passes("12", "executor")

    assert measure()["first_pass"] == 1, f"{event} is a gate the design asks, not a rescue"


def test_what_happens_after_the_merge_is_not_the_road_to_it(store):
    """A deploy that parks the card after its merge is the stage's story, not the merge's."""
    life(store, "12", "promoted", "pr_opened", "merged",
         ("parked", {"job_state": "on_hold", "note": "staging deploy failed"}))
    passes("12", "executor")

    got = measure()

    assert got["first_pass"] == 1 and got["parks"] == 1


# ── 2. what is rework ───────────────────────────────────────────────────────────────────────────

def test_planner_and_review_passes_leave_the_rework_where_it_was(store):
    four_cards(store)
    before = measure()

    for card in ("A", "B", "C"):
        passes(card, "planner", "review", "review", ts=f"{DAY}T12:00:00+00:00")
    after = measure()

    assert (after["code_passes"], after["rework_rate"]) == \
        (before["code_passes"], before["rework_rate"]) == (5, round(5 / 3, 4))
    assert after["first_pass"] == before["first_pass"] == 1


# ── 3. what is a transition, and whose word wins ────────────────────────────────────────────────

def test_an_effects_outcome_is_never_a_transition(store):
    """Every transition's effects write outcome rows under its key (`card#E#…#effect#…`), one per
    try. Read as transitions they would be parks that never happened, or a merge erased."""
    rows = [record.Row(card="E", seq=seq, event_id=f"E-{seq}", event=event, by="test",
                       effects=("column", "comment"), facts=facts,
                       ts=f"{DAY}T10:{seq:02d}:00+00:00")
            for seq, (event, facts) in enumerate(
                [("promoted", {}),
                 ("parked", {"job_state": "on_hold", "note": "API rate limit exceeded"}),
                 ("resumed", {}), ("merged", {})], 1)]
    for row in rows:
        assert record.write(store, "acme", row)
    _, parked, _, merged = rows
    record.write_outcome(store, "acme", parked, 0, "failed: the board did not answer")
    record.write_outcome(store, "acme", parked, 0, "done")
    record.write_outcome(store, "acme", parked, 1, "done")
    record.write_outcome(store, "acme", merged, 0, "done")
    passes("E", "executor")
    assert any("#effect#" in str(r.get("sk")) for r in store.scan()), "no outcome row was planted"

    got = measure()

    assert got["parks"] == 1, got["park_reasons"]
    assert (got["measured"], got["first_pass"]) == (1, 0), got


def test_the_record_says_merged_where_the_jobs_row_says_pr_open(store):
    """A job writes its row once, when it ends — at the pull request, while a person merged it an
    hour later through the door."""
    life(store, "F", "promoted", "pr_opened", "merged")
    passes("F", "executor", state="pr_open")

    got = measure()

    assert (got["measured"], got["first_pass"], got["before_the_record"]) == (1, 1, [])


def test_a_merge_only_a_jobs_row_holds_is_before_the_record(store):
    passes("G", "executor", state="merged")
    life(store, "H", "promoted", "pr_opened")
    passes("H", "executor", state="done")

    got = measure()

    assert got["measured"] == 0 and got["before_the_record"] == ["G", "H"]


def test_a_ref_that_is_not_a_number_joins_its_passes_to_its_record(store):
    life(store, "DAR-12", "promoted", "pr_opened", "merged")
    passes("DAR-12", "executor", "ci_repair")
    life(store, "31", "promoted", "pr_opened", "merged")
    passes("#31", "executor", "review_repair")

    got = measure()

    assert (got["measured"], got["first_pass"], got["code_passes"]) == (2, 0, 4), got


# ── 4. nothing measured, and the window ─────────────────────────────────────────────────────────

def test_with_nothing_measured_the_yield_is_null_and_said_in_both_languages(store):
    life(store, "D", "pr_opened", "merged")

    en, pt = measure(), measure(language="pt-BR")

    assert en["yield"] is None and en["rework_rate"] is None, "a 0 here says every card failed"
    assert en["measured"] == 0 and en["before_the_record"] == ["D"]
    assert en["said"]["headline"].startswith("No card is measured yet")
    assert pt["said"]["headline"].startswith("Nenhum card medido ainda")
    assert "0.5.0" in en["said"]["scope"] and "0.5.0" in pt["said"]["scope"]


def test_the_window_keeps_the_cards_merged_in_it(store):
    life(store, "old", "promoted", "merged", day="2026-08-01")
    life(store, "new", "promoted", "merged")

    got = measure(since="2026-10-01T00:00:00+00:00")

    assert (got["measured"], got["since"]) == (1, "2026-10-01T00:00:00+00:00")
    assert measure()["measured"] == 2


# ── 5. why cards parked ─────────────────────────────────────────────────────────────────────────

def test_a_note_nobody_can_classify_is_unknown_never_transient(store):
    life(store, "P", "promoted",
         ("parked", {"job_state": "on_hold", "note": "the moon was in the wrong phase"}),
         ("parked", {"job_state": "on_hold", "note": ""}))

    got = measure()

    assert got["park_reasons"] == {"unknown": 2}, got["park_reasons"]
    assert "classified from the recorded note" in got["said"]["parks"]


# ── 6. the surfaces ─────────────────────────────────────────────────────────────────────────────

def test_the_dashboard_speaks_the_projects_language(store):
    life(store, "1", "promoted", "pr_opened", "merged", project="loja")
    passes("1", "executor", project="loja")
    life(store, "1", "promoted", "pr_opened", "merged")
    passes("1", "executor")

    pt, en = _api("loja")["autonomy"], _api("acme")["autonomy"]

    assert pt["said"]["headline"].startswith("1 de 1 cards medidos chegaram ao merge"), pt
    assert pt["said"]["labels"]["before"] == "antes do registro"
    assert en["said"]["headline"].startswith("1 of 1 measured cards reached their merge"), en
    assert (pt["yield"], en["yield"]) == (1.0, 1.0)


def test_the_cli_json_is_the_dashboards_block(store):
    four_cards(store)

    printed = _cli("acme", "--json")

    assert printed.exit_code == 0, printed.output
    assert json.loads(printed.stdout) == _api("acme")["autonomy"]


def test_the_cli_says_the_numbers_and_where_measurement_starts(store):
    four_cards(store)

    printed = _cli("acme")

    assert printed.exit_code == 0, printed.output
    assert "1 of 3 measured cards reached their merge" in printed.stdout
    assert "Measurement starts with cards promoted from 0.5.0 on" in printed.stdout
    assert "0.5.0" in _cli("--help").stdout, "the help must say where measurement starts"
    life(store, "1", "promoted", "pr_opened", "merged", project="loja")
    passes("1", "executor", project="loja")
    said = _cli("loja")
    assert said.exit_code == 0 and "1 de 1 cards medidos chegaram ao merge" in said.stdout, \
        said.output


def test_an_empty_store_is_an_answer(store):
    printed = _cli("acme")

    assert printed.exit_code == 0, printed.output
    assert "No card is measured yet" in printed.stdout


def test_a_corrupt_store_exits_2_with_its_cause_and_what_to_check(store, tmp_path):
    (tmp_path / "metrics.db").write_bytes(b"this is not a database, " * 200)

    printed = _cli("acme")

    assert printed.exit_code == 2, printed.output
    assert "could not read the metrics store" in printed.output, "the cause is not said"
    assert "OPENFACTORY_METRICS_SINK" in printed.output, "nothing says what to check"
    assert "No card is measured yet" not in printed.output


def test_a_store_that_cannot_be_built_exits_2_too(store, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "nonesuch")

    printed = _cli("acme")

    assert printed.exit_code == 2, printed.output
    assert "nonesuch" in printed.output


def test_the_dashboard_says_an_unreadable_store_rather_than_an_empty_record(store, tmp_path):
    """Asked of the payload's own function: through the panel, the same file is the people store
    the gate reads first, and the gate already refuses the request with a 503 that says so."""
    from openfactory.api.app import _project_language
    from openfactory.api.metrics_view import cost_dashboard

    (tmp_path / "metrics.db").write_bytes(b"this is not a database, " * 200)

    got = cost_dashboard(project="acme", language_of=_project_language)

    assert got["runs"] == [], "the spend still degrades to empty, as it always has"
    assert got["autonomy"]["readable"] is False and "yield" not in got["autonomy"]
    assert got["autonomy"]["said"]["headline"].startswith("The card record could not be read")


def test_an_unknown_project_is_refused_by_name(store):
    printed = _cli("nonesuch")

    assert printed.exit_code == 2 and "no project named 'nonesuch'" in printed.output


# ── 7. the words ────────────────────────────────────────────────────────────────────────────────

def test_every_sentence_exists_in_both_languages_and_none_says_first_pass():
    """"First pass" already means the brownfield read of a legacy codebase to a client."""
    from openfactory.techlead import voice

    missing = [k for k, e in voice.AUTONOMY.items() if not {"en", "pt-BR"} <= set(e)]
    assert not missing, missing
    said = " ".join(t.lower() for e in voice.AUTONOMY.values() for t in e.values())
    assert "first pass" not in said and "primeira passada" not in said


def test_the_panel_draws_the_servers_words():
    """The tiles' labels and the sentences arrive in the project's language; the page keeps no
    English of its own for them."""
    from pathlib import Path

    from openfactory.api import app as api

    page = (Path(api.__file__).parent / "panel.html").read_text()
    drawn = page[page.index("function _renderAutonomy("):]
    drawn = drawn[:drawn.index("\n}\n")]
    assert "_renderAutonomy(d.autonomy)" in page
    assert "a.readable===false" in drawn, "an unreadable store would draw as an empty record"
    for word in ("merged untouched", "before the record", "classified from the recorded note"):
        assert word not in drawn, f"{word!r} is welded into the page in one language"


def test_histories_is_cards_over_rows_already_read(store):
    life(store, "A", "promoted", "merged")
    life(store, "B", "promoted")

    assert record.histories(store.records_under("acme", "card#")) == record.cards(store, "acme")
