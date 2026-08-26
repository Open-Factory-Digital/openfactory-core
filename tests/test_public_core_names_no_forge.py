"""The public core names no forge: the budget is a question on the tracker port, the credential
is a question on the credential registry, and the reference harnesses stand on their own.

Three findings measured on 2026-08-24, each reproduced before a line moved:

  1. `floor._budget`, the poller's `github_budget` activity, `GET /api/github/ratelimit` and the
     doctor's probe each imported `github_project.github_rate` by name and ran it whatever the
     deployment tracked on. A Jira-only deployment spawned `gh api rate_limit` on every floor
     read and every poll tick; the doctor handed that deployment's JIRA token to `gh` as
     `GH_TOKEN`; and a `None` from the probe rendered as ok — "the vendor does not report an API
     budget" — for a failed read and an absent budget alike.
  2. `actions/catalog.py`, `api/app.py` and `factory.py` resolved the forge credential through
     the reference vendor's App mint for ANY forge kind, overriding a project's own `token_env`;
     a third-party `forge.gitlab` add-on received the deployment's GitHub token as `token=` and
     the App minter as `token_provider`, because the vendor-default table was a closed dict in
     core and nothing let the add-on add a row.
  3. `codex.py`, `kimi.py` and `opencode.py` imported the wall-clock helper from `claude_code.py`
     and the ticket brief from `codex.py`, so blocking one vendor's module broke the other three
     at import time, and three brief builders disagreed about whether the card's Context reaches
     the agent at all.

Every guard below drives the behaviour; the two AST walks carry planted twins.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import logging
import pathlib
import subprocess
import sys
import types

import pytest

from openfactory import plugins
from openfactory.contracts.project import Project, ProviderRef

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "openfactory"


# ── 1. no core module reaches the reference tracker's modules by name ───────────────────────────

#: The reference vendor's tracker-side modules. A core module that imports one has decided the
#: deployment's tracker for it — which is what four of them had done.
_REFERENCE_TRACKER_MODULES = (
    "openfactory.adapters.tracker.github_project",
    "openfactory.adapters.tracker.github_board_setup",
    "openfactory.adapters.tracker.github",
)


def _imports_of(path: pathlib.Path) -> set[str]:
    """Every absolute module a file imports, FUNCTION-LEVEL INCLUDED — the four offenders all
    imported inside a function body, which a top-of-file scan never sees."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found |= {f"{node.module}.{alias.name}" for alias in node.names}
    return found


def _is_core(rel: pathlib.Path) -> bool:
    """Everything outside `adapters/` except the composition root, which may know every adapter."""
    parts = rel.parts
    return parts[0] != "adapters" and rel.as_posix() != "factory.py"


def _offenders(package: pathlib.Path = PKG) -> list[str]:
    out: list[str] = []
    for path in sorted(package.rglob("*.py")):
        rel = path.relative_to(package)
        if not _is_core(rel):
            continue
        hits = {m for m in _imports_of(path)
                if any(m == v or m.startswith(v + ".") for v in _REFERENCE_TRACKER_MODULES)}
        if hits:
            out.append(f"{rel.as_posix()}: {sorted(hits)}")
    return out


def test_no_core_module_imports_the_reference_trackers_modules_by_name():
    assert _offenders() == [], (
        "a core module reaches the reference tracker by name — ask the port "
        "(`build_tracker(project).budget()`, `board_setup.registry.board_creator(kind)`) instead")


def test_and_the_walk_can_SEE_a_function_level_import(tmp_path):
    """The positive twin: a planted core module importing the vendor inside a function is found,
    and the same import inside `adapters/` or `factory.py` is not."""
    pkg = tmp_path / "openfactory"
    (pkg / "floor").mkdir(parents=True)
    (pkg / "floor" / "reading.py").write_text(
        "def _budget():\n    from openfactory.adapters.tracker.github_project import github_rate\n"
        "    return github_rate()\n")
    (pkg / "adapters" / "board").mkdir(parents=True)
    (pkg / "adapters" / "board" / "factory.py").write_text(
        "from openfactory.adapters.tracker.github_project import GitHubProjectBoard\n")
    (pkg / "factory.py").write_text(
        "def f():\n    from openfactory.adapters.tracker.github import GitHubIssuesTracker\n")

    assert _offenders(pkg) == ["floor/reading.py: ['openfactory.adapters.tracker.github_project', "
                               "'openfactory.adapters.tracker.github_project.github_rate']"]


# ── 2. the port has three answers, and every shipped tracker gives one of them ──────────────────

def _jira() -> Project:
    return Project(name="fx-jira", repo_path="/nowhere",
                   tracker=ProviderRef(kind="jira", repo="FX",
                                       options={"site": "acme.atlassian.net", "project_key": "FX",
                                                "email": "a@b.c"}),
                   forge=ProviderRef(kind="github", repo="acme/fx"))


def _ado() -> Project:
    ref = ProviderRef(kind="azure_devops", repo="fx", options={"organization": "c", "project": "P"})
    return Project(name="fx-ado", repo_path="/nowhere", tracker=ref, forge=ref)


def _github() -> Project:
    return Project(name="books", repo_path="/nowhere",
                   tracker=ProviderRef(kind="github", repo="acme/books"))


def test_every_shipped_tracker_implements_budget_in_its_OWN_class():
    """`isinstance` against the runtime_checkable Protocol is satisfied by inheriting the `...`
    body, which returns `None` — the exact fourth answer this port was written to forbid. So the
    name has to be defined on the vendor's own class."""
    from openfactory.adapters.tracker.azure_devops import AzureBoardsTracker
    from openfactory.adapters.tracker.github import GitHubIssuesTracker
    from openfactory.adapters.tracker.jira import JiraTracker
    from openfactory.adapters.tracker.registry import TRACKERS

    by_kind = {"github": GitHubIssuesTracker, "jira": JiraTracker,
               "azure_devops": AzureBoardsTracker}
    assert set(by_kind) == set(TRACKERS), "a shipped tracker is missing from this table"
    for kind, cls in by_kind.items():
        assert "budget" in vars(cls), f"the {kind} tracker inherits budget() from the Protocol"


def test_the_vendors_with_NO_budget_declare_it_rather_than_answering_None(monkeypatch):
    from openfactory.adapters.tracker.base import NOT_REPORTED
    from openfactory.adapters.tracker.registry import build_tracker

    monkeypatch.setenv("JIRA_API_TOKEN", "j")
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "p")
    for project in (_jira(), _ado()):
        answer = build_tracker(project).budget()
        assert answer == NOT_REPORTED and answer is not None, (
            f"{project.tracker.kind} answered {answer!r} — a declared sentinel, never None")


def test_the_reference_vendor_RAISES_when_its_probe_fails(monkeypatch):
    """The third answer. `None` here used to mean this AND "no budget", and the doctor rendered
    both as ok."""
    from openfactory.adapters.tracker import github_project as gp
    from openfactory.adapters.tracker.base import BudgetUnreadable
    from openfactory.adapters.tracker.registry import build_tracker

    def _boom(args, token=None):
        raise RuntimeError("gh is not installed")

    monkeypatch.setattr(gp, "_gh_json", _boom)
    with pytest.raises(BudgetUnreadable):
        build_tracker(_github(), token="t").budget()


def test_and_a_reported_budget_is_LOW_by_the_adapters_own_floor(monkeypatch):
    """`floor` travels on the value: the poller and the doctor both judge by the number the
    ADAPTER wrote there, so neither keeps a threshold of its own."""
    from openfactory.adapters.tracker import github_project as gp
    from openfactory.adapters.tracker.registry import build_tracker

    monkeypatch.setattr(gp, "_gh_json", lambda args, token=None: {"resources": {
        "graphql": {"remaining": gp.BUDGET_FLOOR - 1, "limit": 5000, "reset": 1},
        "core": {"remaining": 4000, "limit": 5000, "reset": 2}}})
    got = build_tracker(_github(), token="t").budget()
    assert got.low and got.floor == gp.BUDGET_FLOOR and got.vendor == "GitHub"
    monkeypatch.setattr(gp, "_gh_json", lambda args, token=None: {"resources": {
        "graphql": {"remaining": gp.BUDGET_FLOOR, "limit": 5000, "reset": 1}}})
    assert not build_tracker(_github(), token="t").budget().low


# ── 3. a Jira-only deployment spawns no `gh`, anywhere the budget is read ───────────────────────

class _Spy:
    """`subprocess.run`, recording every argv and REFUSING the reference vendor's CLI."""

    def __init__(self, answer: str | None = None) -> None:
        self.argv: list[list[str]] = []
        self.answer = answer

    def __call__(self, args, *a, **kw):
        self.argv.append(list(args))
        if list(args)[:1] == ["gh"] and self.answer is None:
            raise AssertionError(f"the reference vendor's CLI was spawned: {args}")
        return subprocess.CompletedProcess(list(args), 0, stdout=self.answer or "", stderr="")


def _deployment(monkeypatch, tmp_path, *projects: Project):
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    for name in ("OPENFACTORY_BOT_TOKEN", "OPENFACTORY_TRACKER_TOKEN", "OPENFACTORY_FORGE_TOKEN",
                 "GH_TOKEN", "OPENFACTORY_GH_APP_ID", "OPENFACTORY_GH_APP_INSTALLATION_ID",
                 "OPENFACTORY_GH_APP_KEY", "OPENFACTORY_GH_APP_KEY_CONTENT"):
        monkeypatch.delenv(name, raising=False)
    reg = ProjectRegistry()
    for p in projects:
        reg.add(p)
    from openfactory.floor import reading

    monkeypatch.setattr(reading, "_budget_memo", None)


@pytest.fixture
def jira_only(monkeypatch, tmp_path) -> _Spy:
    _deployment(monkeypatch, tmp_path, _jira())
    monkeypatch.setenv("JIRA_API_TOKEN", "JIRA-SECRET-xyz")
    spy = _Spy()
    monkeypatch.setattr(subprocess, "run", spy)
    return spy


def test_the_floor_read_spawns_no_gh_and_reports_NOT_REPORTED(jira_only):
    from openfactory import floor
    from openfactory.floor import reading

    assert reading._budget() == {"kind": "jira", "state": "not_reported"}
    got = asyncio.run(floor.gather(want=("budget",)))
    assert got.budget["state"] == "not_reported"
    assert floor.state(got, "").word != "Waiting on a clock"
    assert not any(a[:1] == ["gh"] for a in jira_only.argv)


def test_the_poller_activity_spawns_no_gh(jira_only):
    from openfactory.runtime.temporal.activities import tracker_budgets

    rows = asyncio.run(tracker_budgets())
    assert rows == [{"kind": "jira", "projects": ["fx-jira"], "state": "not_reported"}]


def test_the_doctor_probe_spawns_no_gh_and_hands_the_jira_token_to_NOBODY(jira_only):
    """The worst of the four: the probe resolved the project's TRACKER credential and exported a
    Jira token as `GH_TOKEN` for a process that talks to github.com."""
    from openfactory.adapters.tracker.base import NOT_REPORTED
    from openfactory.doctor import diagnose, probes_for
    from openfactory.registry import ProjectRegistry

    probes = probes_for(ProjectRegistry().get("fx-jira"))
    assert probes.api_budget() == NOT_REPORTED
    finding = {f.check: f for f in diagnose(probes).findings}["api_budget"]
    assert finding.ok and "no budget on this vendor" in finding.message
    assert not any("JIRA-SECRET-xyz" in " ".join(a) for a in jira_only.argv)


def test_GET_api_budget_spawns_no_gh_and_says_NOT_REPORTED_as_a_state(jira_only):
    from fastapi.testclient import TestClient

    from openfactory.api.app import app

    r = TestClient(app).get("/api/budget")
    assert r.status_code == 200
    assert r.json()["summary"]["state"] == "not_reported"
    assert r.json()["rows"][0]["kind"] == "jira"
    assert TestClient(app).get("/api/github/ratelimit").status_code == 404, (
        "the vendor-named route is still served — a dead surface under a neutral twin")


def test_and_on_a_GITHUB_project_the_budget_still_ARRIVES_through_the_same_reads(monkeypatch,
                                                                                tmp_path):
    """The positive twin of the whole section: the spy answers `gh api rate_limit`, and the
    floor, the activity and the route all carry the number and the adapter's verdict."""
    from fastapi.testclient import TestClient

    from openfactory.api.app import app
    from openfactory.floor import reading
    from openfactory.runtime.temporal.activities import tracker_budgets

    _deployment(monkeypatch, tmp_path, _github())
    monkeypatch.setenv("OPENFACTORY_TRACKER_TOKEN", "ghp_x")
    spy = _Spy(answer='{"resources": {"graphql": {"remaining": 12, "limit": 5000, "reset": 0},'
                      '"core": {"remaining": 4000, "limit": 5000, "reset": 0}}}')
    monkeypatch.setattr(subprocess, "run", spy)

    rows = asyncio.run(tracker_budgets())
    assert rows[0]["state"] == "low" and rows[0]["remaining"] == 12
    assert rows[0]["projects"] == ["books"] and rows[0]["vendor"] == "GitHub"
    assert reading._budget()["state"] == "low"
    assert TestClient(app).get("/api/budget").json()["summary"]["remaining"] == 12
    assert ["gh", "api", "rate_limit"] in spy.argv, "the reference probe was never reached"


def test_an_UNREADABLE_budget_is_unread_on_the_floor_and_NOT_ok_in_the_doctor(monkeypatch,
                                                                             tmp_path):
    """`None` ≠ `NOT_REPORTED`. A GitHub deployment with a broken `gh` used to pass the doctor's
    check with the sentence "the vendor does not report an API budget"."""
    from openfactory.adapters.tracker.base import NOT_REPORTED
    from openfactory.doctor import diagnose
    from openfactory.floor import reading
    from tests.test_doctor import _probes

    _deployment(monkeypatch, tmp_path, _github())
    monkeypatch.setenv("OPENFACTORY_TRACKER_TOKEN", "ghp_x")

    def _no_gh(args, *a, **kw):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(subprocess, "run", _no_gh)
    assert reading._budget()["state"] == "unread"

    unread = {f.check: f for f in diagnose(_probes(api_budget=lambda: None)).findings}
    assert not unread["api_budget"].ok, "a failed probe read as compliance"
    declared = {f.check: f for f in diagnose(_probes(api_budget=lambda: NOT_REPORTED)).findings}
    assert declared["api_budget"].ok and "no budget on this vendor" in declared["api_budget"].message


#: The four answers, worst first. The guard walks every pair IN BOTH ORDERS, because the first
#: version asserted `[ok, unread]` and `[not_reported, low]` only, and the cut `"unread": 0`
#: walked through it: `[unread, low]` answered `unread`, so a mixed deployment whose first row's
#: probe had failed and whose second vendor was exhausted rendered "Armed" while the poller was
#: parking that vendor's projects (found by the branch's own review, 2026-08-26).
_WORST_FIRST = ("low", "unread", "ok", "not_reported")


def test_the_summary_is_the_WORST_vendor_whichever_row_comes_FIRST():
    from openfactory.floor import reading

    assert set(reading._STATE_RANK) == set(_WORST_FIRST), "a fifth state, or a missing one"
    for i, worse in enumerate(_WORST_FIRST):
        for better in _WORST_FIRST[i + 1:]:
            for rows in ([{"state": worse}, {"state": better}],
                         [{"state": better}, {"state": worse}]):
                assert reading.budget_summary(rows)["state"] == worse, (
                    f"{[r['state'] for r in rows]} summarised as "
                    f"{reading.budget_summary(rows)['state']!r}, not {worse!r}")
    assert reading.budget_summary([]) == {"state": "not_reported"}


def _more(name: str, **options) -> Project:
    return Project(name=name, repo_path="/nowhere",
                   tracker=ProviderRef(kind="github", repo=f"acme/{name}", options=options))


def _probe_count(spy: _Spy) -> int:
    return sum(1 for a in spy.argv if a[:2] == ["gh", "api"])


def test_a_SHARED_static_credential_is_asked_ONCE(monkeypatch, tmp_path):
    """Two projects on one credential cost ONE probe — the budget is the credential's, and N
    subprocesses to learn one number is what the poller's tick used to be made of."""
    from openfactory.floor import reading

    _deployment(monkeypatch, tmp_path, _github(), _more("films"))
    monkeypatch.setenv("OPENFACTORY_TRACKER_TOKEN", "ghp_shared")
    spy = _Spy(answer='{"resources": {"graphql": {"remaining": 900, "limit": 5000, "reset": 0}}}')
    monkeypatch.setattr(subprocess, "run", spy)
    rows = reading.budgets()
    assert [r["projects"] for r in rows] == [["books", "films"]]
    assert _probe_count(spy) == 1, spy.argv


def test_a_MINTED_credential_is_asked_ONCE_and_MINTED_once(monkeypatch, tmp_path):
    """The guard above passed for the wrong reason: it shared a static variable, and the rows
    were keyed by the token's VALUE — which the App mint renews on every call. On the one
    deployment shape the App exists for (N projects, no static token) three projects cost three
    mints and three probes (measured 2026-08-26). The key is the credential's IDENTITY."""
    from openfactory.floor import reading

    _deployment(monkeypatch, tmp_path, _github(), _more("films"), _more("games"))
    minted: list[str] = []

    def _fresh_every_call() -> str:
        minted.append(f"ghs_{len(minted)}")
        return minted[-1]

    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", _fresh_every_call)
    spy = _Spy(answer='{"resources": {"graphql": {"remaining": 900, "limit": 5000, "reset": 0}}}')
    monkeypatch.setattr(subprocess, "run", spy)
    rows = reading.budgets()
    assert [r["projects"] for r in rows] == [["books", "films", "games"]]
    assert _probe_count(spy) == 1, spy.argv
    assert len(minted) == 1, f"the mint was paid per project, not per credential: {minted}"


def test_and_two_DISTINCT_credentials_are_two_rows(monkeypatch, tmp_path):
    """The positive twin the dedup was missing: `key = (kind, "")` collapsed every credential of
    a kind into one probe and survived the whole suite. A project with its own `token_env` is
    its own row, probed with its own credential."""
    from openfactory.credentials import tracker_credential_source
    from openfactory.floor import reading

    _deployment(monkeypatch, tmp_path, _github(), _more("films", token_env="FILMS_PAT"))
    monkeypatch.setenv("OPENFACTORY_TRACKER_TOKEN", "ghp_books")
    monkeypatch.setenv("FILMS_PAT", "ghp_films")
    spy = _Spy(answer='{"resources": {"graphql": {"remaining": 900, "limit": 5000, "reset": 0}}}')
    monkeypatch.setattr(subprocess, "run", spy)
    rows = reading.budgets()
    assert [r["projects"] for r in rows] == [["books"], ["films"]]
    assert _probe_count(spy) == 2, spy.argv
    assert tracker_credential_source(_github()) == "generic:tracker"
    assert tracker_credential_source(_more("films", token_env="FILMS_PAT")) == "env:FILMS_PAT"


def test_the_credentials_source_is_its_NAME_and_agrees_with_its_value(monkeypatch):
    """`tracker_credential_source` answers WHERE the credential comes from — a variable's name
    or the deployment's row for the kind — and it is non-empty exactly when
    `tracker_token_for(p) or deployment_tracker_token(p)` is: an identity for a credential that
    does not exist, or none for one that does, would merge or split the rows above."""
    from openfactory.credentials import (
        deployment_tracker_token,
        tracker_credential_source,
        tracker_token_for,
    )

    _no_ambient(monkeypatch)
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_MINTED")
    cases = [
        (_more("own", token_env="OWN_PAT"), {"OWN_PAT": "x"}, "env:OWN_PAT"),
        (_jira(), {"JIRA_API_TOKEN": "j"}, "env:JIRA_API_TOKEN"),
        # the generic pair is ONE credential per process whichever variable holds it
        (_github(), {"OPENFACTORY_TRACKER_TOKEN": "t"}, "generic:tracker"),
        (_github(), {"OPENFACTORY_BOT_TOKEN": "b"}, "generic:tracker"),
        (_github(), {}, "deployment:github"),
        (_jira(), {}, ""),
        # a named variable that is EMPTY falls through, in the source as in the value
        (_more("own", token_env="OWN_PAT"), {"OPENFACTORY_BOT_TOKEN": "b"}, "generic:tracker"),
    ]
    for project, env, expected in cases:
        with pytest.MonkeyPatch.context() as m:
            for k, v in env.items():
                m.setenv(k, v)
            source = tracker_credential_source(project)
            value = tracker_token_for(project) or deployment_tracker_token(project)
            assert source == expected, (project.name, env, source)
            assert bool(source) == bool(value), (
                f"{project.name} with {env}: source {source!r} but value {value!r}")
            assert "ghs_MINTED" not in source, "the source carries the value"


def test_the_pause_is_announced_ONLY_to_the_projects_on_the_exhausted_vendor(monkeypatch,
                                                                            tmp_path):
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import RatePauseInput

    _deployment(monkeypatch, tmp_path, _github(), _jira())
    monkeypatch.setattr(acts, "PROOF_DIR", tmp_path / "proofs", raising=False)
    monkeypatch.setattr("openfactory.box_prove.PROOF_DIR", tmp_path / "proofs")
    told: list[str] = []

    class _Notifier:
        def __init__(self, name):
            self.name = name

        def notify(self, *, message, level="info"):
            told.append(self.name)

    monkeypatch.setattr("openfactory.factory.notifier_for_project",
                        lambda p: _Notifier(p.name))
    said = asyncio.run(acts.announce_rate_pause(RatePauseInput(
        resource="graphql", remaining=3, reset_epoch=12345, vendor="GitHub", projects=["books"])))
    assert said is True
    assert told == ["books"], f"the pause reached a project that is still being scanned: {told}"


def test_two_vendors_spent_in_ONE_reset_window_are_TWO_announcements(monkeypatch, tmp_path):
    """The once-per-window marker was `rate-pause-<epoch>.said` — one file for every vendor, so
    the second vendor exhausted in the same window (or, like every vendor that reports no reset,
    at epoch 0) found the first one's marker and stayed silent. Keyed by (kind, epoch) now; the
    positive twin of the dedup — the SAME vendor in the same window speaks once — stays."""
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import RatePauseInput

    _deployment(monkeypatch, tmp_path, _github(), _jira())
    monkeypatch.setattr("openfactory.box_prove.PROOF_DIR", tmp_path / "proofs")
    told: list[str] = []

    class _Notifier:
        def __init__(self, name):
            self.name = name

        def notify(self, *, message, level="info"):
            told.append(self.name)

    monkeypatch.setattr("openfactory.factory.notifier_for_project",
                        lambda p: _Notifier(p.name))

    def _pause(kind: str, vendor: str, project: str) -> bool:
        return asyncio.run(acts.announce_rate_pause(RatePauseInput(
            resource="API", remaining=0, reset_epoch=0, vendor=vendor, kind=kind,
            projects=[project])))

    assert _pause("github", "GitHub", "books") is True
    assert _pause("jira", "Jira", "fx-jira") is True, "the second vendor found the first's marker"
    assert told == ["books", "fx-jira"]
    assert _pause("github", "GitHub", "books") is False, "the same window spoke twice"
    assert told == ["books", "fx-jira"]
    # the marker is a file name a stranger's kind cannot steer, and the pre-per-vendor shape
    # (no kind) keeps the name it had, so a marker written before the deploy still counts
    assert "/" not in acts.rate_pause_marker("../x/y", 7) and ".." not in acts.rate_pause_marker(
        "../x/y", 7)
    assert acts.rate_pause_marker("", 7) == "rate-pause-7.said"


# ── 4. the credential is the vendor's row, and a stranger's row is honoured ─────────────────────

class _Point:
    def __init__(self, name, value):
        self.name, self._value = name, value

    def load(self):
        return self._value


@pytest.fixture
def installs(monkeypatch):
    def _install(*points):
        plugins.reset_cache()
        monkeypatch.setattr("importlib.metadata.entry_points",
                            lambda group=None: list(points) if group == plugins.GROUP else [])
        plugins.reset_cache()
    yield _install
    plugins.reset_cache()


def _gitlab() -> Project:
    return Project(name="gl", repo_path="/nowhere",
                   tracker=ProviderRef(kind="jira", repo="GL", options={"site": "s", "email": "e"}),
                   forge=ProviderRef(kind="gitlab", repo="acme/gl"))


def _no_ambient(monkeypatch):
    for name in ("JIRA_API_TOKEN", "AZURE_DEVOPS_PAT", "GITLAB_TOKEN", "OPENFACTORY_TRACKER_TOKEN",
                 "OPENFACTORY_BOT_TOKEN", "OPENFACTORY_FORGE_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def test_the_vendor_default_table_is_DERIVED_from_the_rows():
    from openfactory import credentials

    assert not hasattr(credentials, "_VENDOR_DEFAULT_ENV"), "the closed dict is back"
    assert credentials.vendor_default_env(types.SimpleNamespace(kind="jira")) == "JIRA_API_TOKEN"
    assert credentials.vendor_default_env(types.SimpleNamespace(kind="azure_devops")) == \
        "AZURE_DEVOPS_PAT"
    assert credentials.vendor_default_env(types.SimpleNamespace(kind="github")) == ""


def test_an_addon_row_that_is_NOT_a_row_declares_nothing_and_is_NAMED(installs, monkeypatch,
                                                                       caplog):
    """`credential_row`'s promise — a non-`CredentialRow` answer is "logged and read as no
    declaration" — was written as care, not asserted: the cut `if False:` survived the suite
    (found by the branch's own review, 2026-08-26). A dict from the add-on reaches nobody as a
    row, the warning names the kind, and the projects fall through to the generic pair."""
    from openfactory.adapters.credential.registry import credential_row
    from openfactory.credentials import forge_token_for

    _no_ambient(monkeypatch)
    installs(_Point("credential.gitlab", lambda: {"env": "GITLAB_TOKEN"}))
    monkeypatch.setenv("GITLAB_TOKEN", "glpat_own")
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "ghp_generic")
    with caplog.at_level(logging.WARNING, logger="openfactory.credential"):
        assert credential_row("gitlab") is None
    assert any("gitlab" in r.getMessage() and "CredentialRow" in r.getMessage()
               for r in caplog.records), [r.getMessage() for r in caplog.records]
    assert forge_token_for(_gitlab()) == "ghp_generic", "a dict was read as a row"


def test_a_strangers_forge_names_its_OWN_variable_and_it_beats_the_generic_pair(installs,
                                                                                 monkeypatch):
    from openfactory.adapters.credential.registry import CredentialRow
    from openfactory.credentials import forge_token_for

    _no_ambient(monkeypatch)
    installs(_Point("credential.gitlab", lambda: CredentialRow(env="GITLAB_TOKEN")))
    monkeypatch.setenv("GITLAB_TOKEN", "glpat_own")
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "ghp_DEPLOYMENT_GITHUB")

    assert forge_token_for(_gitlab()) == "glpat_own", (
        "the add-on's projects were handed the deployment's GitHub credential")


def test_a_vendor_that_declares_no_mint_gets_NO_deployment_token_and_NO_provider(installs,
                                                                                  monkeypatch):
    from openfactory.adapters.credential.registry import CredentialRow
    from openfactory.credentials import (
        deployment_forge_provider,
        deployment_forge_token,
        deployment_tracker_provider,
        deployment_tracker_token,
    )

    _no_ambient(monkeypatch)
    installs(_Point("credential.gitlab", lambda: CredentialRow(env="GITLAB_TOKEN")))
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_MINTED")
    monkeypatch.setattr("openfactory.factory._bot_token_provider", lambda: (lambda: "ghs_MINTED"))

    gl = _gitlab()
    assert deployment_forge_token(gl) is None and deployment_forge_provider(gl) is None
    assert deployment_tracker_token(gl) is None and deployment_tracker_provider(gl) is None
    # …and the reference vendor still gets both, so "nothing is offered" is not the whole story
    gh = _github()
    assert deployment_tracker_token(gh) == "ghs_MINTED"
    assert deployment_tracker_provider(gh)() == "ghs_MINTED"


def test_build_runner_hands_a_plugin_forge_NO_minter_and_the_reference_forge_ITS_OWN(
        installs, monkeypatch, tmp_path):
    """The door the mint came in by after the `token=` door was closed. Driven through the real
    `build_runner` with every neighbour stubbed, asserting the exact kwargs each axis received."""
    from openfactory import factory
    from openfactory.adapters.credential.registry import CredentialRow

    _no_ambient(monkeypatch)
    installs(_Point("credential.gitlab", lambda: CredentialRow(env="GITLAB_TOKEN")),
             _Point("forge.gitlab", lambda p, **kw: ("gitlab-forge", kw)))
    minter = lambda: "ghs_MINTED"  # noqa: E731 — the object identity is the assertion
    monkeypatch.setattr(factory, "_bot_token_provider", lambda: minter)
    monkeypatch.setenv("JIRA_API_TOKEN", "jira_real")
    seen: dict[str, dict] = {}
    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                        lambda p, **kw: seen.setdefault("tracker", kw))
    monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge",
                        lambda p, **kw: seen.setdefault("forge", kw))
    monkeypatch.setattr(factory, "resolve_repo_path", lambda p, **kw: tmp_path)
    monkeypatch.setattr("openfactory.adapters.sandbox.registry.build_sandbox",
                        lambda *a, **kw: object())
    monkeypatch.setattr("openfactory.adapters.agent.build_executor", lambda *a, **kw: object())
    monkeypatch.setattr("openfactory.loader.load_manifest", lambda *a, **kw: object())
    monkeypatch.setattr("openfactory.observability.registry.journal_for", lambda *a, **kw: None)
    monkeypatch.setattr(factory, "notifier_for_project", lambda p: object())
    monkeypatch.setattr("openfactory.orchestrator.JobRunner", lambda **kw: kw)

    factory.build_runner(_gitlab(), "1", sandbox="worktree", image="img", review=False)
    assert seen["forge"] == {"token": None, "token_provider": None}, (
        f"the add-on forge received the reference vendor's minter: {seen['forge']}")
    assert seen["tracker"]["token"] == "jira_real" and seen["tracker"]["token_provider"] is None

    seen.clear()
    factory.build_runner(_github(), "1", sandbox="worktree", image="img", review=False)
    assert seen["forge"]["token_provider"] is minter and seen["tracker"]["token_provider"] is minter


def test_the_release_path_builds_a_plugin_forge_WITHOUT_the_reference_mint(installs, monkeypatch):
    from openfactory.actions import catalog

    _no_ambient(monkeypatch)
    installs(_Point("forge.gitlab", lambda p, **kw: ("gitlab-forge", kw.get("token"))))
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_MINTED")
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "ghp_DEPLOYMENT_GITHUB")
    monkeypatch.setattr("openfactory.registry.ProjectRegistry.get", lambda self, name: _gitlab())
    monkeypatch.setattr("openfactory.loader.load_manifest", lambda p: object())

    _, _, forge = catalog._forge_and_manifest("gl")
    assert forge == ("gitlab-forge", "ghp_DEPLOYMENT_GITHUB") or forge[1] is None
    # The generic pair is what an UNDECLARED vendor has always had; what must never happen is the
    # App mint reaching it. With a declared row the generic pair stops too.
    assert "ghs_" not in str(forge[1])


def test_a_project_that_names_its_OWN_forge_token_is_built_with_it(monkeypatch):
    """`_forge_and_manifest` built a GitHub project's forge with `OPENFACTORY_BOT_TOKEN` even
    when the project named `forge.options.token_env` — the multi-project override #162 fixed for
    the tracker one line below."""
    from openfactory.actions import catalog

    _no_ambient(monkeypatch)
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "ghp_DEPLOYMENT")
    monkeypatch.setenv("ACME_PAT", "ghp_PROJECTS_OWN")
    own = Project(name="own", repo_path="/nowhere",
                  tracker=ProviderRef(kind="github", repo="acme/own"),
                  forge=ProviderRef(kind="github", repo="acme/own", options={"token_env": "ACME_PAT"}))
    monkeypatch.setattr("openfactory.registry.ProjectRegistry.get", lambda self, name: own)
    monkeypatch.setattr("openfactory.loader.load_manifest", lambda p: object())
    monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge",
                        lambda p, **kw: kw.get("token"))

    assert catalog._forge_and_manifest("own")[2] == "ghp_PROJECTS_OWN"


def test_the_login_is_discovered_through_the_forges_row_and_absent_elsewhere(monkeypatch):
    from openfactory import cli, credentials

    monkeypatch.setattr("openfactory.adapters.forge.github.discover_token", lambda: "ghp_me")
    assert credentials.discover_forge_token("github") == "ghp_me"
    assert credentials.discover_forge_token("jira") is None
    assert credentials.discover_forge_token("azure_devops") is None
    assert not hasattr(cli, "_gh_token_if_logged_in"), "the CLI spawns the vendor's CLI itself again"


def test_the_board_to_create_is_the_trackers_declaration(installs):
    from openfactory.adapters.board_setup.registry import board_creator
    from openfactory.adapters.tracker.github_board_setup import create_board

    assert board_creator("github") is create_board
    assert board_creator("jira") is None and board_creator("azure_devops") is None
    acme = lambda *, owner, title, token: ("1", "https://acme/1")  # noqa: E731
    installs(_Point("board_setup.acme", lambda: acme))
    assert board_creator("acme") is acme


def test_project_init_asks_the_registry_which_board_to_create(monkeypatch, tmp_path):
    """Driven through the CLI: a tracker with no act is told so and the reference vendor's act
    is called with the credential the TRACKER axis resolved."""
    from typer.testing import CliRunner

    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    for name in ("OPENFACTORY_TRACKER_TOKEN", "OPENFACTORY_BOT_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    calls: list[str] = []
    monkeypatch.setattr("openfactory.adapters.board_setup.registry.board_creator",
                        lambda kind: calls.append(kind) or None)
    monkeypatch.chdir(tmp_path)
    added = CliRunner().invoke(app, ["project", "add", "demo", "https://github.com/acme/demo.git"])
    assert added.exit_code == 0, added.output
    result = CliRunner().invoke(app, ["project", "init", "demo"])
    assert result.exit_code == 0, result.output
    assert calls == ["github"], "init decided by the vendor's name instead of asking the registry"
    assert "brings its own" in result.output


# ── 5. the reference harnesses stand on their own ───────────────────────────────────────────────

def _harness_modules() -> dict[str, str]:
    """kind → the module its builder imports, READ OFF `registry.HARNESSES` — a hand list would
    miss a fifth harness and read it as compliant."""
    from openfactory.adapters.agent.registry import HARNESSES

    out: dict[str, str] = {}
    for kind, builder in HARNESSES.items():
        for node in ast.walk(ast.parse(inspect.getsource(builder).strip())):
            if isinstance(node, ast.ImportFrom) and node.module:
                out[kind] = node.module
    return out


def test_the_derivation_sees_every_shipped_harness():
    mods = _harness_modules()
    assert {"claude_code", "codex", "kimi", "opencode"} <= set(mods), mods
    assert all(m.startswith("openfactory.adapters.agent.") for m in mods.values()), mods


@pytest.mark.parametrize("blocked", sorted(_harness_modules()))
def test_blocking_ONE_harness_module_leaves_every_other_importable(blocked, monkeypatch):
    """The measurement, not an AST reading: with one vendor's module made unimportable, each of
    the others imports. Before the move, blocking `claude_code` broke all three."""
    mods = _harness_modules()
    for name in mods.values():
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, mods[blocked], None)
    for kind, name in mods.items():
        if kind == blocked:
            continue
        importlib.import_module(name)
    # and the base the survivors share carries the two shapes they used to take from a sibling
    from openfactory.adapters.agent import base
    from openfactory.adapters.sandbox import timeouts

    assert callable(base.wall_result) and callable(base.ticket_brief)
    assert base.wall_result is not timeouts.timeout_result


class _FakeSandbox:
    def __init__(self, out: str = "", code: int = 0) -> None:
        self.out, self.code, self.commands = out, code, []

    def harness_path(self, name: str) -> str:
        return name

    def run(self, *, workspace, command: str, timeout: int):  # noqa: ARG002
        self.commands.append(command)
        if command.startswith("cat "):
            return 0, ""
        return self.code, self.out


def _every_adapter():
    from openfactory.adapters.agent.registry import HARNESSES

    # `provider/model`, the one spelling every shipped harness accepts (opencode refuses a bare
    # name by design: without a provider it can reach no endpoint)
    return {kind: build(model="anthropic/claude-sonnet-4-5", log_dir=None, language=None,
                        role="executor")
            for kind, build in HARNESSES.items()}


def _context():
    from openfactory.adapters.agent.base import AgentContext
    from openfactory.contracts import Ticket

    return AgentContext(ticket=Ticket(id="#7", title="t", objective="o", repo="o/r",
                                      context="X-CTX-MARK", in_scope=["Y-SCOPE-MARK"]))


def _workspace():
    from openfactory.adapters.sandbox.base import Workspace

    return Workspace(path="/work", branch="b", base_branch="main")


def test_every_harness_hands_the_cards_CONTEXT_and_IN_SCOPE_to_its_cli(monkeypatch):
    """The positive twin of "one builder": driven through each adapter's real `execute`, the two
    fields three of four harnesses used to drop reach the argv of every one."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    for kind, adapter in _every_adapter().items():
        box = _FakeSandbox()
        adapter.execute(sandbox=box, workspace=_workspace(), context=_context())
        argv = " ".join(box.commands)
        assert "X-CTX-MARK" in argv, f"{kind} drops the card's Context"
        assert "Y-SCOPE-MARK" in argv, f"{kind} drops the card's In-scope list"


def test_the_reference_harness_reads_its_roles_from_the_ONE_home(monkeypatch):
    """`claude_code._role_prompt` was a silent duplicate of `roles.role_prompt` — the one that
    warns on a missing file. Driven: the planner's prompt carries what `roles` answers."""
    from openfactory.adapters.agent import claude_code

    assert not hasattr(claude_code, "_ROLES_DIR") and not hasattr(claude_code, "_role_prompt")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(claude_code, "role_prompt", lambda role: f"ROLE-MARK-{role}")
    box = _FakeSandbox()
    claude_code.ClaudeCodeAdapter().plan(sandbox=box, workspace=_workspace(), context=_context())
    assert "ROLE-MARK-planner" in " ".join(box.commands)


# ── 6. the panel renders the four states from the neutral route ────────────────────────────────

def _js_function(page: str, name: str) -> str:
    """The body of `function name(...) {...}`, by brace matching — scoped to the handler, not
    the whole page, so the words are asserted where they are executed."""
    start = page.index(f"function {name}(")
    open_brace = page.index("{", start)
    depth, i = 0, open_brace
    while i < len(page):
        depth += {"{": 1, "}": -1}.get(page[i], 0)
        if depth == 0:
            return page[open_brace:i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces after function {name}")


def test_the_panel_fetches_the_neutral_route_and_renders_all_four_states():
    import re

    raw = (PKG / "api" / "panel.html").read_text()
    # THE PROSE IS STRIPPED FIRST: the comment that explains the route's history names it.
    page = "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in raw.splitlines())
    assert "/api/github/ratelimit" not in page and "VOCAB.rate_floor" not in page
    poll = _js_function(page, "pollBudget")
    assert '"/api/budget"' in poll
    line = _js_function(page, "budgetLine")
    for state in ("not_reported", "unread", "low", "ok"):
        assert f'"{state}"' in line, f"budgetLine does not render {state}"
    paint = _js_function(page, "paintFloor")
    assert "budgetLine(_budget)" in paint, "the budget line is composed and reaches nothing"
