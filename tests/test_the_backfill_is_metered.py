"""The backfill's agent passes are metered — one `agent_run` row each, through the deployment's
one sink, and a sentence at the end that says what was spent.

THE FIRST LIVE ONBOARDING RAN SIX AGENT PASSES AND RECORDED NONE (2026-09-06). One
citation-checked pass wrote the five documents, five more wrote the budgeted concepts, each a
harness run on a client's repository with a cost the harness reported — and `context.agent_ask`
returned the text and dropped the `AgentRunResult` that carried it. `records_of_kind("agent_run")`
for that day: nothing. The cost dashboard is the one instrument every other decision here is
measured on, and the onboarding — the single most expensive thing the platform does on a
legacy repository — was invisible to it.

What this file holds:
  1. `agent_ask` hands every result to `on_run` before handing on its text — and a recorder
     that raises is logged and does not fail the pass;
  2. `Spend.note` writes one `agent_run` row per pass, with the cost, model, harness and tokens
     the harness reported, under one role and a ticket naming the repository;
  3. the sentence: passes and dollars, and "cost not reported" said rather than zeroed;
  4. `semantic_pass_for` binds the recorder — so the backfill, the renewal and the gate's
     authoring, which all reach the harness there, are metered by the same line;
  5. the backfill's outcome names the spend.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.contracts.run import AgentRunResult
from openfactory.onboarding import context as ctx
from openfactory.onboarding import onboard as ob
from openfactory.onboarding.spend import BACKFILL_ROLE, Spend

ENVELOPE = '{"does": [], "vocabulary": [], "entities": [], "invariants": [], "questions": []}'
RESULT = AgentRunResult(ok=True, summary=ENVELOPE, cost_usd=0.5, model="opus", harness="fake",
                        num_turns=3, input_tokens=100, output_tokens=20)
UNPRICED = AgentRunResult(ok=True, summary=ENVELOPE)


class _Sink:
    def __init__(self):
        self.rows = []

    def record(self, row):
        self.rows.append(row)


class _Agent:
    def __init__(self, result=RESULT):
        self.result = result
        self.prompts: list[str] = []

    def ask(self, *, sandbox, workspace, prompt, phase):
        self.prompts.append(prompt)
        return self.result


@pytest.fixture
def sink(monkeypatch) -> _Sink:
    s = _Sink()
    monkeypatch.setattr("openfactory.observability.registry.deployment_metrics_sink", lambda: s)
    return s


def _project() -> Project:
    return Project(name="dsk", repo_path="https://github.com/acme/api.git",
                   tracker=ProviderRef(kind="github", repo="acme/api"),
                   forge=ProviderRef(kind="github", repo="acme/api"),
                   product=ProductConfig(docs_repo="acme/dsk-context"))


# 1. agent_ask -------------------------------------------------------------------------------

def test_agent_ask_hands_every_result_to_on_run_before_handing_on_its_text():
    seen: list[object] = []
    agent = _Agent()

    ask = ctx.agent_ask(agent, sandbox=None, workspace=None, on_run=seen.append)
    text = ask("what does it do?")

    assert seen == [RESULT], "the result — with its cost — was dropped before the recorder saw it"
    assert '"does"' in text, "the text the caller relied on must still come back"
    assert agent.prompts == ["what does it do?"]


def test_a_recorder_that_raises_is_logged_and_the_pass_is_kept(caplog):
    def _boom(result):
        raise RuntimeError("the sink is down")

    ask = ctx.agent_ask(_Agent(), sandbox=None, workspace=None, on_run=_boom)
    with caplog.at_level(logging.WARNING, logger="openfactory.onboarding.context"):
        text = ask("p")

    assert '"does"' in text, "telemetry must never cost the client the document"
    assert "recorder failed" in caplog.text and "the sink is down" in caplog.text, (
        "a recorder that fails must be logged with its trace, not swallowed")


# 2. the row -------------------------------------------------------------------------------

def test_one_agent_run_row_per_pass_with_what_the_harness_reported(sink):
    spend = Spend("dsk", "acme/api")

    spend.note(RESULT)
    spend.note(RESULT)

    assert len(sink.rows) == 2, "one row per pass, not one per backfill"
    row = sink.rows[0]
    assert row.kind == "agent_run" and row.role == BACKFILL_ROLE
    assert row.project == "dsk" and row.ticket == "backfill:acme/api"
    assert row.cost_usd == 0.5 and row.model == "opus" and row.harness == "fake"
    assert row.num_turns == 3 and row.input_tokens == 100 and row.output_tokens == 20
    assert row.ts, "the row needs its time — it is the sort key"


def test_a_pass_with_no_reported_cost_records_none_never_zero(sink):
    Spend("dsk", "acme/api").note(UNPRICED)

    assert sink.rows[0].cost_usd is None, "None is 'not measured'; 0.0 would average as free"


# 3. the sentence --------------------------------------------------------------------------

def test_the_summary_says_passes_and_dollars(sink):
    spend = Spend("dsk", "acme/api")
    assert spend.summary() == "" and spend.said("semantic") == "semantic"

    spend.note(RESULT)
    assert spend.summary() == "1 agent pass, US$ 0.50"
    spend.note(RESULT)
    assert spend.summary() == "2 agent passes, US$ 1.00"
    assert spend.said("semantic") == "semantic — 2 agent passes, US$ 1.00"


def test_a_harness_that_reports_no_cost_is_said_not_zeroed(sink):
    spend = Spend("dsk", "acme/api")
    spend.note(UNPRICED)
    assert spend.summary() == "1 agent pass, cost not reported by the harness"

    spend.note(RESULT)
    assert spend.summary() == "2 agent passes, US$ 0.50 for the 1 that reported a cost"


# 4. the seam ------------------------------------------------------------------------------

def _harness_present(monkeypatch, agent: _Agent) -> None:
    import shutil

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(shutil, "which", lambda b: "/usr/local/bin/" + b)
    monkeypatch.setattr("openfactory.adapters.agent.build_asker", lambda p: agent)
    monkeypatch.setattr("openfactory.adapters.sandbox.registry.judging_worktree",
                        lambda *a, **k: object())


def test_semantic_pass_for_binds_the_recorder_so_every_trigger_is_metered(
        tmp_path, monkeypatch, sink):
    """The renewal (`renew.py`) and the gate's authoring (`concepts.author_for_paths`) call this
    same function; a recorder bound here meters them without either knowing."""
    _harness_present(monkeypatch, _Agent())

    ask_fn, mode = ob.semantic_pass_for(_project(), tmp_path)

    assert ask_fn is not None and mode.startswith("semantic"), mode
    ask_fn("p")
    runs = [r for r in sink.rows if r.kind == "agent_run"]
    assert len(runs) == 1 and runs[0].role == BACKFILL_ROLE, (
        "a pass made through semantic_pass_for left no row")


def test_the_caller_s_own_spend_is_the_one_bound(tmp_path, monkeypatch, sink):
    _harness_present(monkeypatch, _Agent())
    spend = Spend("dsk", "acme/api")

    ask_fn, _ = ob.semantic_pass_for(_project(), tmp_path, spend=spend)
    ask_fn("p")
    ask_fn("p")

    assert spend.runs == 2 and len(sink.rows) == 2


# 5. the outcome ---------------------------------------------------------------------------

def _bare(tmp_path: Path, name: str, *, seed: dict[str, str] | None = None) -> Path:
    bare = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True,
                   capture_output=True)
    if seed:
        work = tmp_path / f"seed-{name}"
        work.mkdir()
        for rel, body in seed.items():
            target = work / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        for args in (["init", "-b", "main"], ["add", "-A"],
                     ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "seed"],
                     ["remote", "add", "origin", str(bare)], ["push", "-u", "origin", "main"]):
            subprocess.run(["git", *args], cwd=work, check=True, capture_output=True)
    return bare


class _Forge:
    def pr_for_head(self, head, *, repo=""):
        return ""

    def list_branches(self, repo="", *, prefix=""):
        return []

    def open_pr(self, *, head, base, title, body, repo=""):
        return f"https://github.com/{repo}/pull/2"

    def push_remote(self):
        return None


def test_the_backfill_outcome_says_what_it_spent(tmp_path, monkeypatch, sink):
    origins = {
        "acme/api": _bare(tmp_path, "api", seed={"pkg/app.py": "def main():\n    return 1\n"}),
        "acme/dsk-context": _bare(tmp_path, "ctx"),
    }
    monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge",
                        lambda *a, **kw: _Forge())
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda view, repo, token=None: str(origins[repo]))
    agent = _Agent()
    _harness_present(monkeypatch, agent)

    out = ob.onboard_product_context(_project(), sources=["acme/api"])

    assert out.ok, out.detail
    assert re.search(r"\d+ agent pass(es)?, US\$ \d+\.\d\d$", out.backfill), (
        f"the operator is not told what the backfill spent: {out.backfill!r}")
    # the open questions the backfill carries go through the same sink as `agent_loop` rows;
    # the passes are the `agent_run` ones
    runs = [r for r in sink.rows if r.kind == "agent_run"]
    assert len(runs) == len(agent.prompts) >= 1, (
        f"{len(agent.prompts)} passes made, {len(runs)} recorded")
