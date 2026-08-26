"""ADR-0013 D2/D3/D6 — the pre-flight sizing gate, the splitter's naming, and the repo cache.

The gate must only ever HELP: every failure path (cache, agent, parsing, activity) degrades
to running the job exactly as before. These tests pin the degrade ladder and the pieces'
contracts; the workflow-level routing is proven in test_temporal_workflow.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import add_ons
import pytest

from openfactory import namespace
from openfactory.contracts import JobState
from openfactory.runtime.repo_cache import RepoCache
from openfactory.runtime.temporal import activities as acts
from openfactory.runtime.temporal.activities import (
    _child_body,
    _child_title,
    _do_split,
    _parse_verdict,
)
from openfactory.runtime.temporal.io import SplitInput


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _make_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(["init", "-b", "main"], origin)
    _git(["config", "user.email", "t@t"], origin)
    _git(["config", "user.name", "t"], origin)
    (origin / "app.py").write_text("x = 1\n")
    _git(["add", "-A"], origin)
    _git(["commit", "-m", "init"], origin)
    return origin


# ---- RepoCache (D6) --------------------------------------------------------------------


def test_cache_clones_once_then_resets(tmp_path):
    origin = _make_origin(tmp_path)
    cache = RepoCache(root=tmp_path / "cache")

    p1 = cache.sync("proj", str(origin), "main")
    assert p1 is not None and (p1 / "app.py").read_text() == "x = 1\n"

    # origin advances; a local scribble dirties the cache — sync must RESET to origin/main
    (origin / "app.py").write_text("x = 2\n")
    _git(["commit", "-am", "bump"], origin)
    (p1 / "junk.txt").write_text("dirt\n")
    p2 = cache.sync("proj", str(origin), "main")
    assert p2 == p1
    assert (p2 / "app.py").read_text() == "x = 2\n"  # fresh
    assert not (p2 / "junk.txt").exists()  # cleaned — identical to origin, never merged into


def test_cache_recovers_from_corruption(tmp_path):
    origin = _make_origin(tmp_path)
    cache = RepoCache(root=tmp_path / "cache")
    p1 = cache.sync("proj", str(origin), "main")
    import shutil
    shutil.rmtree(p1 / ".git")  # corrupt it
    p2 = cache.sync("proj", str(origin), "main")
    assert p2 is not None and (p2 / "app.py").exists()  # recloned


def test_cache_unreachable_returns_none_never_raises(tmp_path):
    cache = RepoCache(root=tmp_path / "cache")
    assert cache.sync("proj", str(tmp_path / "nope"), "main") is None  # caller degrades


# ---- verdict parsing (D2) --------------------------------------------------------------


def test_parse_verdict_fit_split_unclear():
    fit = _parse_verdict('bla\n```json\n{"verdict": "fit", "estimated_files": 3, '
                         '"reasons": "one small change", "children": [], "questions": []}\n```')
    assert fit and fit.verdict == "fit" and fit.estimated_files == 3

    split = _parse_verdict(
        'analysis...\n```json\n{"verdict": "split", "reasons": "two features", '
        '"children": [{"title": "harden guest surface", "objective": "o", "criteria": ["c"]},'
        '{"title": "rate limits", "objective": "o2", "criteria": ["c2"]}]}\n```')
    assert split and split.verdict == "split" and len(split.children) == 2

    unclear = _parse_verdict('```json\n{"verdict": "unclear", "questions": ["what is X?"]}\n```')
    assert unclear and unclear.questions == ["what is X?"]


def test_parse_verdict_garbage_degrades_to_none():
    # None → the activity returns fit+degraded — the gate never blocks on a bad LLM answer.
    assert _parse_verdict("no json here at all") is None
    assert _parse_verdict('```json\n{"verdict": "banana"}\n```') is None
    assert _parse_verdict('```json\n{not json..}\n```') is None


def test_parse_verdict_takes_the_last_block():
    # sizers think out loud; only the FINAL block is the verdict
    text = ('```json\n{"verdict": "split", "children": []}\n```\n…on reflection…\n'
            '```json\n{"verdict": "fit"}\n```')
    v = _parse_verdict(text)
    assert v and v.verdict == "fit"


def test_sizer_result_text_recovers_full_text_past_the_summary_cap():
    # Regression: res.summary is capped ~1000 chars and the sizer writes its verdict block
    # LAST, so the cap chops the JSON off ("unparseable verdict" that ran #37 straight to code).
    # _sizer_result_text must recover the complete text from the raw stream-json result event.
    import json

    from openfactory.contracts import AgentRunResult
    from openfactory.runtime.temporal.activities import _sizer_result_text

    full = ("A" * 2000 + '\n```json\n{"verdict": "split", "children": ['
            '{"title": "child a", "objective": "o", "criteria": ["c"]}]}\n```')
    raw = "\n".join([
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({"type": "result", "result": full, "num_turns": 4}),
    ])
    res = AgentRunResult(ok=True, summary=full[:1000], raw_output=raw)

    assert _parse_verdict(res.summary) is None          # truncated → unparseable
    recovered = _sizer_result_text(res)
    assert recovered == full                             # full text recovered
    v = _parse_verdict(recovered)
    assert v and v.verdict == "split" and len(v.children) == 1


def test_sizer_result_text_falls_back_to_summary_without_stream():
    from openfactory.contracts import AgentRunResult
    from openfactory.runtime.temporal.activities import _sizer_result_text

    res = AgentRunResult(ok=True, summary="just a summary", raw_output="")
    assert _sizer_result_text(res) == "just a summary"


# ---- pre-flight live streaming (worker-side visibility, closes the silent-card gap) --------


def test_pf_emit_tags_the_event_with_the_job_id():
    from openfactory.observability import InMemoryEventSink
    from openfactory.runtime.temporal.activities import _pf_emit

    mem = InMemoryEventSink()
    _pf_emit(mem, "books", "37", "state", "sizing", note="judging INVEST")
    e = mem.events[0]
    # job_id must be the unique workflow id so the panel can filter the worker log group for it
    assert e.job_id == "openfactory-books-37" and e.ticket_id == "37"
    assert e.kind == "state" and e.message == "sizing" and e.data["note"] == "judging INVEST"


def test_pf_emit_stdout_line_round_trips_through_events_from_logs():
    # the sizer runs on the worker → its events reach the panel only as OPENFACTORY_EVENT: stdout
    # lines that events_from_logs must parse back (and be greppable by job id in CloudWatch).
    import contextlib
    import io

    from openfactory.observability import StdoutEventSink
    from openfactory.runtime.temporal.activities import _pf_emit

    events_from_logs = add_ons.module("openfactory.runtime.fargate.launcher").events_from_logs

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _pf_emit(StdoutEventSink(), "books", "37", "note", "verdict: SPLIT into 2")
    line = buf.getvalue().strip()
    assert line.startswith("OPENFACTORY_EVENT:") and "openfactory-books-37" in line  # greppable
    parsed = events_from_logs(line)
    assert [(e.job_id, e.kind, e.message) for e in parsed] == [
        ("openfactory-books-37", "note", "verdict: SPLIT into 2")]


def test_pf_emit_never_raises_on_a_bad_sink():
    # telemetry must never break sizing — a throwing sink is swallowed
    from openfactory.runtime.temporal.activities import _pf_emit

    class _Boom:
        def emit(self, _):
            raise RuntimeError("sink down")

    _pf_emit(_Boom(), "books", "37", "state", "sizing")  # must not raise


# ---- GitHub rate-limit budget (flow resilience + panel visibility) -------------------------


def test_github_rate_reports_the_most_constrained_resource(monkeypatch):
    import openfactory.adapters.tracker.github_project as gp

    monkeypatch.setattr(gp, "_gh_json", lambda args, token=None: {"resources": {
        "graphql": {"remaining": 80, "limit": 5000, "reset": 111},
        "core": {"remaining": 4000, "limit": 5000, "reset": 222}}})
    r = gp.github_rate("tok")
    # graphql is the tighter budget → that's what the poller/panel must react to; the floor is
    # the ADAPTER's own number, carried on the value so no core module keeps a copy
    assert (r.resource, r.remaining, r.limit, r.reset_epoch) == ("graphql", 80, 5000, 111)
    assert r.floor == gp.BUDGET_FLOOR and r.vendor == "GitHub"


def test_github_rate_RAISES_on_error_so_unreadable_is_never_absent(monkeypatch):
    """It used to return `None` — the same answer a vendor with no budget gives — and the doctor
    rendered both as ok. The port's third answer is a raised `BudgetUnreadable`; the callers that
    fail open (the poller) catch it and say `unread`, which is the honest word."""
    import openfactory.adapters.tracker.github_project as gp
    from openfactory.adapters.tracker.base import BudgetUnreadable

    def _boom(args, token=None):
        raise RuntimeError("gh down")

    monkeypatch.setattr(gp, "_gh_json", _boom)
    with pytest.raises(BudgetUnreadable, match="gh down"):
        gp.github_rate("tok")


# ---- splitter naming (D3) --------------------------------------------------------------


def test_child_title_is_deterministic_and_parent_linked():
    # 'Plan 92 — X' → 'Plan 92a — X [auto-split of #37]' (house convention + parent link)
    t0 = _child_title("Plan 92 — Guest hardening + rate limits", 0, "#37")
    t1 = _child_title("Plan 92 — Guest hardening + rate limits", 1, "#37")
    assert t0 == "Plan 92a — Guest hardening + rate limits [auto-split of #37]"
    assert t1 == "Plan 92b — Guest hardening + rate limits [auto-split of #37]"
    # no plan number → suffix fallback, never crashes, still linked + marked
    assert _child_title("Fix the widget", 0, "#9") == "Fix the widget (a) [auto-split of #9]"


def test_child_title_strips_a_prior_auto_split_tag_no_stacking():
    # a (defensive) split of a child must NOT stack '[auto-split of #37] [auto-split of #385]'
    child_title = "Plan 92a — Guest hardening [auto-split of #37]"
    t = _child_title(child_title, 0, "#385")
    assert t == "Plan 92a — Guest hardening [auto-split of #385]"
    assert t.count("[auto-split of") == 1  # exactly one tag, never stacked


def test_child_title_ignores_the_llm_text_so_re_runs_dont_duplicate():
    # the title must depend ONLY on (parent, index, parent_ref) — NEVER the LLM's per-child
    # wording — else a re-size with reworded children spawns a fresh duplicate set (the bug
    # that produced 30 near-identical 'Plan 92x' issues). Same inputs → byte-identical title.
    a = _child_title("Plan 92 — Guest hardening", 0, "#37")
    b = _child_title("Plan 92 — Guest hardening", 0, "#37")
    assert a == b  # deterministic
    assert "[auto-split of #37]" in a  # marks it generated + links the parent


def test_child_body_carries_the_llm_focus_and_stays_a_complete_ticket():
    body = _child_body({"title": "harden guest", "objective": "Harden the guest surface.",
                        "criteria": ["auth rejects bad tokens", "audit log written"]},
                       "#37", 1, 2)
    assert "**Focus:** harden guest" in body  # the LLM framing lives in the body now
    assert "## Objective" in body and "## Acceptance criteria" in body
    assert "- auth rejects bad tokens" in body
    assert "part 1/2" in body  # ordering is explicit
    assert "#37" in body  # traceability to the parent


# ---- splitter sends children to TO-DO in order (D3, owner decision) ---------------------


class _FakeTracker:
    def __init__(self):
        self.created = []       # (title, body) in creation order
        self.states = []        # (ref, state) in call order
        self.closed = None
        self.linked = []        # (parent_ref, child_ref) native links
        self._children = []     # native children of the parent (decision idempotency)

    def get_ticket(self, ref):
        from openfactory.contracts import Ticket
        return Ticket(id=ref, title="Plan 92 — hardening + rate limits",
                      objective="x", repo="o/app")

    def find_ticket(self, *, title):
        return None  # nothing pre-exists → always create

    def create_ticket(self, *, title, body):
        self.created.append((title, body))
        return f"#{100 + len(self.created)}"  # #101, #102, …

    def set_state(self, ref, state, reason=None, *, needs_person=None):
        self.states.append((ref, state))

    def close_ticket(self, ref, reason, *, delivered=True):
        self.closed = (ref, reason)

    def link_child(self, parent_ref, child_ref):
        self.linked.append((parent_ref, child_ref))

    def children_of(self, parent_ref):
        return list(self._children)


def _patch_split(monkeypatch, to_todo=True):
    fake = _FakeTracker()
    monkeypatch.setattr(acts, "_tracker_for", lambda project: fake)
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: object())
    import openfactory.loader
    monkeypatch.setattr(openfactory.loader, "load_manifest",
                        lambda project: type("M", (), {"split_to_todo": to_todo})())
    return fake


def test_split_sends_children_to_todo_in_order(monkeypatch):
    fake = _patch_split(monkeypatch, to_todo=True)
    out = _do_split(SplitInput(project="p", issue="37", reasons="two features", children=[
        {"title": "harden guest surface", "objective": "o", "criteria": ["c1"]},
        {"title": "rate limits", "objective": "o2", "criteria": ["c2"]},
    ]))
    # two children, Plan 92a / 92b naming
    assert [t.split(" — ")[0] for t, _ in fake.created] == ["Plan 92a", "Plan 92b"]
    # BOTH moved to TO-DO, in creation order (#101 before #102) → poller picks 92a first
    assert fake.states == [("#101", JobState.TODO), ("#102", JobState.TODO)]
    # each child is NATIVELY linked to the parent (traceability + decision idempotency)
    assert fake.linked == [("#37", "#101"), ("#37", "#102")]
    assert fake.closed[0] == "#37" and "TO-DO" in fake.closed[1]
    assert "split into #101, #102" == out


def test_split_short_circuits_when_parent_already_has_native_children(monkeypatch):
    # DECISION idempotency: children_of() already reports linked children → the split was
    # taken before, so reuse them and create/close NOTHING (no duplicate set, no 2nd comment).
    fake = _patch_split(monkeypatch, to_todo=True)
    fake._children = ["#101", "#102"]
    out = _do_split(SplitInput(project="p", issue="37", reasons="r", children=[
        {"title": "x", "objective": "o", "criteria": ["c"]},
        {"title": "y", "objective": "o2", "criteria": ["c2"]}]))
    assert fake.created == [] and fake.closed is None  # nothing created, parent not re-closed
    assert out == "already split into #101, #102"


def test_split_is_idempotent_when_children_already_exist(monkeypatch):
    # a re-run (re-drop / workflow retry) must REUSE the existing children — deterministic
    # titles make find_ticket match, so no duplicate set is created (the 30-dupes bug).
    fake = _patch_split(monkeypatch, to_todo=True)
    children = [{"title": "reworded on the second pass!", "objective": "o", "criteria": ["c1"]},
                {"title": "also different wording", "objective": "o2", "criteria": ["c2"]}]
    # first pass creates #101, #102
    _do_split(SplitInput(project="p", issue="37", reasons="r", children=children))
    existing = {t: f"#{100 + i + 1}" for i, (t, _) in enumerate(fake.created)}
    fake.created.clear()
    fake.find_ticket = lambda *, title: existing.get(title)  # now they pre-exist
    # second pass with DIFFERENT llm wording must create nothing new
    out = _do_split(SplitInput(project="p", issue="37", reasons="r", children=[
        {"title": "totally new phrasing", "objective": "o", "criteria": ["c1"]},
        {"title": "yet another rewording", "objective": "o2", "criteria": ["c2"]}]))
    assert fake.created == []                 # zero duplicates
    assert out == "split into #101, #102"     # reused the originals


def test_split_to_backlog_when_flag_off(monkeypatch):
    fake = _patch_split(monkeypatch, to_todo=False)
    _do_split(SplitInput(project="p", issue="37", reasons="r", children=[
        {"title": "a", "objective": "o", "criteria": ["c"]},
    ]))
    assert fake.states == []  # no TO-DO move → stays in Backlog
    assert "Backlog" in fake.closed[1]


# ---- _do_preflight: manifest must load from the WORKER's cache, never a registry-only
# path (live bug — project.repo_path names no real directory on the worker) -------------


class _PreflightTracker:
    def __init__(self, ticket):
        self._ticket = ticket
        self.comments = []

    def get_ticket(self, ref):
        return self._ticket

    def comment(self, ref, body):
        self.comments.append((ref, body))


class _FakeSizerAdapter:
    """Stands in for a HARNESS. The sizer is no longer a hand-written method per adapter — every
    judging role runs through the single read-only `ask()` primitive (agent/roles.py), so a fake
    harness implements one method and serves them all."""

    def __init__(self, verdict_json):
        self._verdict_json = verdict_json

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        from openfactory.contracts import AgentRunResult
        return AgentRunResult(ok=True, summary=f"```json\n{self._verdict_json}\n```")


def test_preflight_loads_manifest_from_the_cache_not_registry_path(tmp_path, monkeypatch):
    # The registry's repo_path is a BOGUS path (as it is on the real worker — it only
    # resolves inside the ephemeral Fargate container). If _do_preflight ever tries
    # load_manifest() against THAT path again, this must fail loudly (regression guard).
    from openfactory.contracts import AcceptanceCriterion, Ticket
    from openfactory.runtime.temporal.io import PreflightInput

    origin = _make_origin(tmp_path)
    (origin / namespace.DIR).mkdir()
    (origin / namespace.MANIFEST).write_text(
        "version: 1\nbase_branch: main\npreflight:\n  enabled: true\n  code_check: true\n")
    import subprocess as sp
    sp.run(["git", "add", "-A"], cwd=origin, check=True, capture_output=True)
    sp.run(["git", "commit", "-m", "add manifest"], cwd=origin, check=True, capture_output=True)

    from openfactory.contracts.project import Project, ProviderRef

    ticket = Ticket(id="#37", title="Plan 92 — hardening + rate limits", repo="o/app",
                    objective="x", acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = _PreflightTracker(ticket)
    monkeypatch.setattr(acts, "_tracker_for", lambda project: tracker)

    # a REAL Project, with repo_path set to a path that NEVER exists on the worker (exactly
    # today's registry.yaml shape — a Fargate-only path) — proves _do_preflight doesn't
    # depend on it being real, and still loads the manifest from the synced cache.
    bogus_project = Project(name="books", repo_path="/work/books",
                            tracker=ProviderRef(kind="github", repo="o/app"))
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: bogus_project)
    import openfactory.credentials as bot_mod
    import openfactory.factory as factory_mod
    from openfactory.adapters.forge import registry as forge_registry

    monkeypatch.setattr(forge_registry, "clone_url_for",
                        lambda project, repo="", *, token=None: str(origin))
    monkeypatch.setattr(bot_mod, "forge_token", lambda: None)
    monkeypatch.setattr(factory_mod, "github_app_token_from_env", lambda: None)

    verdict = '{"verdict": "split", "reasons": "two features", "children": ' \
              '[{"title": "a", "objective": "o", "criteria": ["c"]}, ' \
              '{"title": "b", "objective": "o2", "criteria": ["c2"]}]}'
    from openfactory.adapters.agent import registry as harnesses
    # inject through the harness TABLE (the real resolution path), not a concrete class
    monkeypatch.setitem(harnesses.HARNESSES, "claude_code",
                        lambda **kw: _FakeSizerAdapter(verdict))

    result = acts._do_preflight(PreflightInput(project="books", issue="37"))

    assert result.verdict == "split"  # sizing ACTUALLY ran (proves the cache/manifest fix)
    assert result.degraded is None
    # the "too large" split comment IS expected; the "did not run" DEGRADE warning must NOT be
    assert not any("did **not** run" in body for _, body in tracker.comments)


def test_preflight_never_resizes_a_split_child(tmp_path, monkeypatch):
    # A ticket that is ITSELF a split child (its title carries the auto-split marker) must go
    # straight to fit WITHOUT sizing — re-sizing recurses into a runaway cascade of
    # ever-smaller Plan 92x tickets (the live incident). The sizer must NOT even be called.
    from openfactory.contracts import AcceptanceCriterion, Ticket
    from openfactory.runtime.temporal.io import PreflightInput

    origin = _make_origin(tmp_path)
    (origin / namespace.DIR).mkdir()
    (origin / namespace.MANIFEST).write_text(
        "version: 1\nbase_branch: main\npreflight:\n  enabled: true\n  code_check: true\n")
    import subprocess as sp
    sp.run(["git", "add", "-A"], cwd=origin, check=True, capture_output=True)
    sp.run(["git", "commit", "-m", "m"], cwd=origin, check=True, capture_output=True)

    from openfactory.contracts.project import Project, ProviderRef

    child = Ticket(id="#385", repo="o/app", objective="x",
                   title="Plan 92a — Guest hardening [auto-split of #37]",
                   acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = _PreflightTracker(child)
    monkeypatch.setattr(acts, "_tracker_for", lambda project: tracker)
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: Project(
        name="books", repo_path="/work/books",
        tracker=ProviderRef(kind="github", repo="o/app")))
    import openfactory.credentials as bot_mod
    import openfactory.factory as factory_mod
    from openfactory.adapters.agent import registry as harnesses
    from openfactory.adapters.forge import registry as forge_registry

    monkeypatch.setattr(forge_registry, "clone_url_for",
                        lambda project, repo="", *, token=None: str(origin))
    monkeypatch.setattr(bot_mod, "forge_token", lambda: None)
    monkeypatch.setattr(factory_mod, "github_app_token_from_env", lambda: None)

    def _boom():  # the sizer must never be constructed/called for a split child
        raise AssertionError("sizer was called on a split child — should have skipped")
    monkeypatch.setitem(harnesses.HARNESSES, "claude_code", lambda **kw: _boom())

    result = acts._do_preflight(PreflightInput(project="books", issue="385"))
    assert result.verdict == "fit" and result.degraded is None  # scoped already → straight to code


def test_preflight_degrades_visibly_when_the_repo_is_unreachable(monkeypatch):
    from openfactory.contracts import AcceptanceCriterion, Ticket
    from openfactory.runtime.temporal.io import PreflightInput

    ticket = Ticket(id="#5", title="x", repo="o/app", objective="x",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = _PreflightTracker(ticket)
    monkeypatch.setattr(acts, "_tracker_for", lambda project: tracker)
    bogus_project = type("P", (), {
        "name": "p", "repo_path": "/nonexistent",
        # `kind` and `options` because the real `ProviderRef` carries them — a double missing a
        # field the contract has proves the double, not the code.
        "forge": type("F", (), {"repo": "o/app", "kind": "github", "options": {}})(),
        "tracker": type("T", (), {"repo": "o/app", "kind": "github", "options": {}})(),
    })()
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: bogus_project)
    import openfactory.credentials as bot_mod
    import openfactory.factory as factory_mod
    import openfactory.runtime.boxed_job as ep_mod
    monkeypatch.setattr(ep_mod, "clone_url", lambda repo, token: "/definitely/does/not/exist")
    monkeypatch.setattr(bot_mod, "forge_token", lambda: None)
    monkeypatch.setattr(factory_mod, "github_app_token_from_env", lambda: None)

    result = acts._do_preflight(PreflightInput(project="p", issue="5"))

    assert result.verdict == "fit"  # degrades to fit → the ticket still runs
    assert result.degraded and "clone" in result.degraded
    assert tracker.comments and "did **not** run" in tracker.comments[0][1]  # LOUD, not silent
