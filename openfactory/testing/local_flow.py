"""Local flow harness — run the REAL poller → pre-flight → split loop offline.

The cloud loop (Temporal schedule → PollWorkflow → JobWorkflow → _preflight → split) is slow
and heavy to test against: a big repo, a real board, Fargate spin-ups, 3-minute ticks. This
harness drives the SAME `_do_preflight` / `_do_split` code against an in-memory tracker and a
throwaway tiny git repo, with a SCRIPTED sizer (no LLM) — so a full flow runs in well under a
second. It catches emergent bugs the unit tests miss, like the split CASCADE (pre-flight
re-sizing its own children into ever-smaller tickets): here that shows up instantly as the
ticket count exploding, and `run_flow` flags it.

    from openfactory.testing.local_flow import run_flow, always_split
    run = run_flow(seed_title="Plan 92 — big bundle", sizer=always_split(4))
    run.print_trace()          # what the poller did, tick by tick
    assert not run.cascaded    # the split-child guard held

Swap `sizer` for your own `(number, title, body) -> verdict-dict` to model any sizing decision.
"""

from __future__ import annotations

import subprocess
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import mkdtemp
from unittest import mock

from openfactory import namespace
from openfactory.contracts import AcceptanceCriterion, AgentRunResult, JobState, Ticket

# a full run should terminate quickly; blow past this and something is recursing (cascade)
_CASCADE_LIMIT = 40


class InMemoryTracker:
    """A faithful, in-memory TrackerAdapter — no GitHub. Tickets, board columns, and native
    parent/child links all live in dicts, so the split flow runs with zero network."""

    def __init__(self) -> None:
        self._tickets: dict[str, dict] = {}   # bare number -> {title, body, open, column}
        self._links: dict[str, list[str]] = {}  # parent bare -> [child refs '#N']
        self._n = 100
        self.comments: list[tuple[str, str]] = []

    # -- helpers ------------------------------------------------------------------------
    @staticmethod
    def _bare(ref: str) -> str:
        return str(ref).lstrip("#")

    def create(self, title: str, body: str = "", column: str = "Backlog") -> str:
        self._n += 1
        num = str(self._n)
        self._tickets[num] = {"title": title, "body": body, "open": True, "column": column}
        return f"#{num}"

    def all_open(self) -> list[str]:
        return [n for n, t in self._tickets.items() if t["open"]]

    # -- TrackerAdapter port ------------------------------------------------------------
    def get_ticket(self, ref: str) -> Ticket:
        t = self._tickets[self._bare(ref)]
        return Ticket(id=f"#{self._bare(ref)}", title=t["title"], repo="testbed/app",
                      objective=t["body"] or "x",
                      acceptance_criteria=[AcceptanceCriterion(text="c")], labels=[])

    def set_state(self, ref: str, state: JobState, reason: str | None = None) -> None:
        col = {JobState.TODO: "TO-DO"}.get(state, state.value)
        self._tickets[self._bare(ref)]["column"] = col
        if reason:
            self.comments.append((ref, f"[{state.value}] {reason}"))

    def comment(self, ref: str, body: str) -> None:
        self.comments.append((ref, body))

    def assignees(self, ref: str) -> list[str]:
        return []

    def set_assignees(self, ref: str, logins: list[str]) -> None:
        pass

    def create_ticket(self, *, title: str, body: str) -> str:
        return self.create(title, body, column="Backlog")

    def find_ticket(self, *, title: str) -> str | None:
        for num, t in self._tickets.items():
            if t["open"] and t["title"].strip() == title.strip():
                return f"#{num}"
        return None

    def close_ticket(self, ref: str, reason: str) -> None:
        t = self._tickets[self._bare(ref)]
        t["open"], t["column"] = False, "Done"
        self.comments.append((ref, reason))

    def link_child(self, parent_ref: str, child_ref: str) -> None:
        self._links.setdefault(self._bare(parent_ref), [])
        if child_ref not in self._links[self._bare(parent_ref)]:
            self._links[self._bare(parent_ref)].append(child_ref)

    def children_of(self, parent_ref: str) -> list[str]:
        return list(self._links.get(self._bare(parent_ref), []))

    def grandchildren(self) -> list[str]:
        """The INVARIANT check: a parent may have children, never grandchildren (depth-1).
        Returns any ref that is BOTH someone's child AND has children of its own — i.e., a
        split that recursed one level too far. Must always be empty."""
        is_a_child = {self._bare(c) for kids in self._links.values() for c in kids}
        return [f"#{p}" for p, kids in self._links.items() if p in is_a_child and kids]

    # -- board scan (what the poller's scan_todo reads) ---------------------------------
    def items_in_status(self, status: str) -> list[str]:
        return [n for n, t in self._tickets.items() if t["open"] and t["column"] == status]


class _ScriptedSizer:
    """Stands in for ClaudeCodeAdapter. `verdict_fn(number, title, body) -> dict` decides the
    sizing verdict with no LLM — its fenced-JSON form is what the REAL _parse_verdict reads."""

    def __init__(self, tracker: InMemoryTracker, verdict_fn) -> None:
        self._tracker = tracker
        self._verdict_fn = verdict_fn
        self.calls: list[str] = []  # titles the sizer was actually asked to judge

    def ask(self, *, sandbox, workspace, prompt, phase="ask") -> AgentRunResult:
        import json
        import re

        # the sizer's prompt carries the ticket header the fake keys off — every judging role
        # now flows through the one read-only primitive, so the fake reads what it was asked
        m = re.search(r"# Ticket #?(\S+): (.+)", prompt)
        num, title = (m.group(1).lstrip("#"), m.group(2).strip()) if m else ("", "")
        self.calls.append(title)
        body = self._tracker._tickets.get(num, {}).get("body", "")
        verdict = self._verdict_fn(num, title, body)
        text = "Assessment.\n```json\n" + json.dumps(verdict) + "\n```"
        return AgentRunResult(ok=True, summary=text, raw_output="")


# ---- ready-made sizer scripts ---------------------------------------------------------
def always_split(n: int = 4):
    """A sizer that judges EVERY ticket too large and splits it into n children — the worst
    case for the cascade guard: without the split-child skip this recurses forever."""
    def _fn(number, title, body):
        return {"verdict": "split", "reasons": "bundles several outcomes",
                "children": [{"title": f"part {i + 1}", "objective": "o", "criteria": ["c"]}
                             for i in range(n)]}
    return _fn


def split_once_then_fit(n: int = 4):
    """Split only the seed 'Plan' parent; judge everything else fit — the intended shape."""
    def _fn(number, title, body):
        if "[auto-split of #" in title:  # already a child
            return {"verdict": "fit", "reasons": "one change"}
        return {"verdict": "split", "reasons": "bundles several outcomes",
                "children": [{"title": f"part {i + 1}", "objective": "o", "criteria": ["c"]}
                             for i in range(n)]}
    return _fn


@dataclass
class FlowRun:
    tracker: InMemoryTracker
    trace: list[tuple] = field(default_factory=list)   # (tick, issue, verdict, detail)
    cascaded: bool = False
    sizer_calls: list[str] = field(default_factory=list)

    def print_trace(self) -> None:
        print(f"\n=== local flow ({len(self.trace)} ticks) ===")
        for tick, issue, verdict, detail in self.trace:
            print(f"  tick {tick:>2} · #{issue:<4} → {verdict:<8} {detail}")
        open_tickets = self.tracker.all_open()
        print(f"--- open tickets: {len(open_tickets)} {['#'+n for n in open_tickets]}")
        print(f"--- sizer was called {len(self.sizer_calls)} time(s)")
        gk = self.tracker.grandchildren()
        print(f"--- grandchildren (must be none): {gk or 'none ✓ — depth-1 enforced'}")
        if self.cascaded:
            print("  ⚠️  CASCADE DETECTED — ticket count exploded (a child was re-split)")
        else:
            print("  ✓ no cascade — the flow converged")


def _tiny_repo() -> Path:
    """A throwaway git repo with a valid manifest — what RepoCache.sync clones from."""
    d = Path(mkdtemp(prefix="openfactory-localflow-"))

    def git(*a):
        subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (d / "app.py").write_text("def add(a, b):\n    return a + b\n")
    (d / namespace.DIR).mkdir()
    (d / namespace.MANIFEST).write_text(
        "version: 1\nbase_branch: main\npreflight:\n  enabled: true\n  code_check: true\n")
    git("add", "-A")
    git("commit", "-m", "init")
    return d


def run_flow(*, seed_title: str, sizer, seed_body: str = "A big bundle of work.",
             max_ticks: int = _CASCADE_LIMIT) -> FlowRun:
    """Drive the REAL pre-flight + split loop offline. Seeds one ticket in TO-DO, then, tick by
    tick (single-line: one ticket at a time in board order), runs `_do_preflight`; on `split`
    runs `_do_split`; on `fit`/degraded marks it coded (stub); on `unclear` parks it. Stops when
    TO-DO drains or a cascade is detected. Returns the full trace."""
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import PreflightInput, SplitInput

    origin = _tiny_repo()
    tracker = InMemoryTracker()
    sizer_adapter = _ScriptedSizer(tracker, sizer)
    tracker.create(seed_title, seed_body, column="TO-DO")  # the one seed ticket, in TO-DO
    run = FlowRun(tracker=tracker)

    import openfactory.credentials as bot_mod
    import openfactory.factory as factory_mod
    from openfactory.adapters.forge import registry as forge_registry

    project = Project(name="testbed", repo_path="/work/testbed",
                      tracker=ProviderRef(kind="github", repo="testbed/app"))
    with ExitStack() as st:
        st.enter_context(mock.patch.object(acts, "_tracker_for", lambda p: tracker))
        st.enter_context(mock.patch.object(acts.ProjectRegistry, "get",
                                           lambda self, name: project))
        # THE SEAM THE ACTIVITIES USE. This patched `entrypoint.clone_url`, and when the clone
        # URL became a forge question the patch went inert: the local flow started asking the real
        # registry for a real URL and every split silently produced zero children. A monkeypatch
        # that no longer intercepts anything does not fail — it quietly changes what the test
        # covers, which is how a green suite stops meaning anything.
        st.enter_context(mock.patch.object(forge_registry, "clone_url_for",
                                           lambda project, repo="", *, token=None: str(origin)))
        st.enter_context(mock.patch.object(bot_mod, "forge_token", lambda: None))
        st.enter_context(mock.patch.object(factory_mod, "github_app_token_from_env", lambda: None))
        # Patch where the class is DEFINED, not the package re-export: the harness resolver
        # imports it from `agent.claude_code` at call time, so a patch on the re-export would
        # silently miss and this local flow would run the real agent.
        st.enter_context(mock.patch.dict(
            "openfactory.adapters.agent.registry.HARNESSES",
            {"claude_code": lambda **kw: sizer_adapter}))

        for tick in range(max_ticks):
            todo = tracker.items_in_status("TO-DO")
            if not todo:
                break
            issue = todo[0]  # single-line strict: first in board order
            v = acts._do_preflight(PreflightInput(project="testbed", issue=issue))
            if v.degraded:
                tracker.set_state(issue, JobState.DONE)  # degraded → run as-is (stub: coded)
                run.trace.append((tick, issue, "degraded", v.degraded))
            elif v.verdict == "split" and v.children:
                acts._do_split(SplitInput(project="testbed", issue=issue,
                                          children=v.children, reasons=v.reasons))
                kids = tracker.children_of(f"#{issue}")
                run.trace.append((tick, issue, "split", f"→ {', '.join(kids)}"))
            elif v.verdict == "unclear":
                tracker.set_state(issue, JobState.NEEDS_REFINEMENT)
                run.trace.append((tick, issue, "unclear", "parked"))
            else:  # fit
                tracker.set_state(issue, JobState.DONE)  # stub the coding pipeline
                run.trace.append((tick, issue, "fit", "coded (stub)"))

            if len(tracker._tickets) > _CASCADE_LIMIT:
                run.cascaded = True
                break

    run.sizer_calls = sizer_adapter.calls
    return run
