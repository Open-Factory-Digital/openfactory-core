"""A preview is declared by the project and decided by the operator (ADR-0050 D3, D8, D9; #265
slice 1).

The split is a security boundary, not a filing preference. The manifest is a file the agent edits,
so it may say only what the product IS — which compose files, what a person may open, how data is
seeded. Everything that grants something — which secret names reach a service, which reach a
build, egress, limits, whether a look is required before a merge — is the operator's, in the
registry, and a name the factory itself depends on never reaches a preview however it is written.

What these pin:

1. THE MANIFEST'S BLOCK: paths inside the repository, ports that exist, no service both opened
   and excluded.
2. THE OPERATOR'S POLICY: the factory's own credentials and every project's `token_env` refused —
   at the write and at the read — without making the registry unloadable; `bridge`/`host` refused
   as egress; the TTL clamped.
3. ONE SLUG, ONE PROJECT, refused where a person names the project.
4. THE SHAPE ON THE FLOOR: the compose spec's four names in every project, and a project's own
   declared compose files, are human-gated.
5. THE LOOK BEFORE THE MERGE: a project that requires one is never merged by the factory, and the
   pull request says why.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from openfactory.contracts import Manifest, RunResult, ValidationResult
from openfactory.contracts.project import PreviewPolicy, Project
from openfactory.orchestrator.merge_policy import should_auto_merge
from openfactory.policy import protected
from tests.test_walking_skeleton import repo  # noqa: F401 — the fixture

_PASS = [ValidationResult(name="test", command="pytest -q", exit_code=0, passed=True)]


# ── 1. the manifest's block ──────────────────────────────────────────────────────────────────────


def _preview(**kw) -> dict:
    return {"preview": {"compose": "docker-compose.yml", "expose": {"web": 3000}, **kw}}


def test_a_preview_block_names_compose_files_inside_the_repository():
    m = Manifest.model_validate(_preview(data={"api": ["manage.py", "migrate"]}))
    assert m.preview.compose == ["docker-compose.yml"], "one file is a list of one"
    for bad in ("../elsewhere.yml", "/etc/compose.yml", "~/c.yml", "${X}/c.yml"):
        with pytest.raises(ValueError, match="inside the repository"):
            Manifest.model_validate(_preview(compose=bad))


@pytest.mark.parametrize("bad,why", [
    ({"expose": {}}, "expose"),
    ({"expose": {"web": 70000}}, "1–65535"),
    ({"exclude": ["web"]}, "both name"),
    ({"exclude": ["api"], "data": {"api": "migrate"}}, "excluded"),
])
def test_a_preview_block_that_contradicts_itself_is_refused(bad, why):
    with pytest.raises(ValueError, match=why):
        Manifest.model_validate(_preview(**bad))


def test_no_block_no_preview():
    assert Manifest().preview is None


# ── 2. the operator's policy ─────────────────────────────────────────────────────────────────────


def test_the_factorys_own_credentials_never_reach_a_preview_and_nothing_else_breaks():
    p = PreviewPolicy(env={"*": ["APP_ENV"], "api": {"DATABASE_URL": "ACME_PV_DATABASE_URL"},
                           "web": ["ANTHROPIC_API_KEY", "OPENFACTORY_PANEL_TOKEN",
                                   "TEMPORAL_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "not a name"]},
                      build_args={"web": {"NPM_TOKEN": "OPENFACTORY_BOT_TOKEN"}})
    assert p.env["web"] == {}, "every one of the factory's names was refused"
    assert p.build_args["web"] == {}, "a refused WORKER name is refused as surely as a container one"
    assert p.names_for("api") == {"APP_ENV": "APP_ENV", "DATABASE_URL": "ACME_PV_DATABASE_URL"}
    assert p.names_for("api", build=True) == {}, "a run-time name never reaches a build"


def test_egress_is_an_operator_network_by_name_never_the_hosts():
    assert PreviewPolicy(network="host").network == ""
    assert PreviewPolicy(network="bridge").network == ""
    assert PreviewPolicy(network="openfactory-preview-egress").network == "openfactory-preview-egress"


def test_the_time_a_preview_lives_is_bounded_and_a_bad_value_is_not_an_outage():
    assert PreviewPolicy(hours=999).hours == 168
    assert PreviewPolicy(hours=0).hours == 1
    assert PreviewPolicy(hours="soon").hours == 24


@pytest.fixture
def registry(tmp_path, monkeypatch):
    path = tmp_path / "registry.yaml"
    path.write_text(
        "projects:\n"
        "  acme:\n    name: acme\n    repo_path: /tmp/acme\n"
        "    tracker: {kind: github, repo: o/acme, options: {token_env: ACME_PAT}}\n"
        "  shop:\n    name: shop\n    repo_path: /tmp/shop\n"
        "    tracker: {kind: jira, repo: o/shop, options: {token_env: SHOP_JIRA}}\n",
        encoding="utf-8")
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(path))
    from openfactory.registry import ProjectRegistry

    return ProjectRegistry(), path


def test_no_projects_token_env_reaches_a_preview_written_or_read(registry):
    reg, path = registry
    reg.set_preview("acme", {"env": {"web": ["ACME_PAT", "SHOP_JIRA", "APP_ENV"]}})
    import yaml

    written = yaml.safe_load(path.read_text())["projects"]["acme"]["preview"]
    assert "ACME_PAT" not in str(written) and "SHOP_JIRA" not in str(written), \
        "refused AT THE WRITE — a credential name is never in the file at all"
    assert reg.get("acme").preview.env == {"web": {"APP_ENV": "APP_ENV"}}
    # a registry edited by hand is refused at the READ, by every door that loads it
    text = path.read_text().replace("APP_ENV: APP_ENV", "SHOP_JIRA: SHOP_JIRA")
    path.write_text(text)
    assert reg.get("acme").preview.env == {"web": {}}
    assert next(p for p in reg.list() if p.name == "acme").preview.env == {"web": {}}


def test_the_operator_decides_from_the_cli_and_reads_it_back(registry):
    from openfactory.cli import app

    reg, _ = registry
    out = CliRunner().invoke(app, ["project", "set-preview", "acme", "--required", "--hours", "6",
                                   "--env", "api=DATABASE_URL=ACME_PV_DB", "--env", "web=ACME_PAT"])
    assert out.exit_code == 0, out.output
    assert "required before a merge" in out.output and "refused" in out.output
    saved = reg.get("acme").preview
    assert saved.required and saved.hours == 6
    assert saved.env == {"api": {"DATABASE_URL": "ACME_PV_DB"}, "web": {}}
    shown = CliRunner().invoke(app, ["project", "show", "acme"])
    assert shown.exit_code == 0 and "ACME_PV_DB" in shown.output
    assert CliRunner().invoke(app, ["project", "set-preview", "nobody"]).exit_code == 2


# ── 3. one slug, one project ─────────────────────────────────────────────────────────────────────


def test_a_project_whose_name_slugs_like_anothers_is_refused(registry):
    reg, _ = registry
    with pytest.raises(ValueError, match="short name 'acme'"):
        reg.add(Project(name="ACME", repo_path="/tmp/y"))
    reg.add(Project(name="acme-web", repo_path="/tmp/z"))


# ── 4. the shape on the floor ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["docker-compose.yml", "compose.yaml", "compose.yml",
                                  "docker-compose.yaml", ".openfactory/preview.compose.yml",
                                  ".openfactory/preview/app.Dockerfile"])
def test_the_products_shape_is_human_gated_in_every_project(path):
    assert protected.violations([path], Manifest()) == (path,)


def test_a_projects_own_compose_files_are_human_gated_where_it_keeps_them():
    m = Manifest.model_validate({"preview": {"compose": ["deploy/dev.yml"],
                                             "expose": {"web": 3000}}})
    assert protected.violations(["deploy/dev.yml", "src/app.py"], m) == ("deploy/dev.yml",)
    assert protected.violations(["deploy/dev.yml"], Manifest()) == ()


# ── 5. the look before the merge ─────────────────────────────────────────────────────────────────


def test_a_project_that_requires_a_look_is_never_merged_by_the_factory():
    manifest = Manifest(merge_policy="auto")
    clean = RunResult(ticket_id="#1", state="pr_open", validations=_PASS)
    assert should_auto_merge(manifest, clean)
    held = clean.model_copy(update={"preview_required": True})
    assert not should_auto_merge(manifest, held)


@pytest.mark.parametrize("required", [True, False])
def test_the_pull_request_says_a_look_is_required_only_when_it_is(required, tmp_path, repo):  # noqa: F811
    from openfactory.adapters.sandbox import WorktreeSandbox
    from openfactory.contracts import AcceptanceCriterion, JobState, Ticket
    from tests.test_walking_skeleton import FakeReviewer, FakeTracker
    from tests.test_walking_skeleton import _runner as skeleton_runner

    ticket = Ticket(id="#31", title="add feature", objective="add a feature", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    manifest = Manifest(merge_policy="auto", validate={"test": "true", "security": "true"})
    runner = skeleton_runner(repo, FakeTracker(ticket), manifest, tmp_path,
                             reviewer=FakeReviewer(), sandbox=WorktreeSandbox(root=tmp_path / "wt"))
    runner.project = Project(name="app", repo_path=str(repo),
                             preview=PreviewPolicy(required=required))

    result = runner.run("#31")

    assert result.preview_required is required
    assert ("look at a preview" in runner.forge.opened["body"]) is required
    assert (result.state is JobState.PR_OPEN) is required, "required → a person merges"


# ── 6. what the person merging a shape change is shown ──────────────────────────────────────────


def _shape(tmp_path, protected_hits, files: dict[str, str]):
    from types import SimpleNamespace

    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.orchestrator.machine import JobRunner

    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    holder = SimpleNamespace(_protected=tuple(protected_hits),
                             _SHAPE_NAMES=JobRunner._SHAPE_NAMES)
    ws = Workspace(path=tmp_path, host_path=tmp_path, branch="b", base_branch="main")
    return JobRunner._preview_shape(holder, ws)


def test_a_change_to_the_shape_shows_every_file_a_preview_would_read_with_its_hash(tmp_path):
    manifest = ("preview:\n  compose: [deploy/dev.yml, .openfactory/preview.compose.yml]\n"
                "  expose: {web: 3000}\n")
    shape = _shape(tmp_path, [".openfactory/project.yaml"], {
        ".openfactory/project.yaml": manifest,
        "deploy/dev.yml": "services: {web: {build: .}}\n",
        ".openfactory/preview.compose.yml": "services: {web: {build: ..}}\n",
        ".openfactory/preview/app.Dockerfile": "FROM python:3.12-slim\n",
    })
    names = [line.split()[0] for line in shape]
    assert names == ["deploy/dev.yml", ".openfactory/preview.compose.yml",
                     ".openfactory/preview/app.Dockerfile"]
    assert all(len(line.split()[1]) == 12 for line in shape), "each file carries its hash"


def test_a_shape_that_points_at_a_file_nobody_committed_says_so(tmp_path):
    shape = _shape(tmp_path, ["docker-compose.yml"], {
        ".openfactory/project.yaml": "preview:\n  compose: [missing.yml]\n  expose: {a: 1}\n"})
    assert shape == ["missing.yml absent"]


def test_a_change_that_leaves_the_shape_alone_shows_nothing(tmp_path):
    manifest = "preview:\n  compose: [docker-compose.yml]\n  expose: {web: 3000}\n"
    assert _shape(tmp_path, ["src/app.py"], {".openfactory/project.yaml": manifest,
                                             "docker-compose.yml": "services: {}\n"}) == []


def test_the_pull_request_body_carries_the_shape_where_the_person_decides():
    from tests.test_a_gate_that_holds_says_so_where_the_person_decides import _body

    body = _body({"preview_shape": ["deploy/dev.yml 3f9a1c2b4d5e"]})
    assert "What merging this lets the factory run" in body
    assert "`deploy/dev.yml 3f9a1c2b4d5e`" in body
    assert "What merging this lets the factory run" not in _body({})


def test_the_shape_never_reads_a_file_outside_the_repository(tmp_path):
    """The manifest in a change is agent-written and may be invalid on purpose; its lines are
    reported, never followed out of the tree."""
    (tmp_path / "secret.txt").write_text("not the repository's")
    root = tmp_path / "repo"
    shape = _shape(root, [".openfactory/project.yaml"], {
        ".openfactory/project.yaml": "preview:\n  compose: [../secret.txt]\n  expose: {a: 1}\n"})
    assert shape == ["../secret.txt absent"]


def test_a_job_whose_change_edits_the_shape_says_so_in_its_pull_request(tmp_path, repo):  # noqa: F811
    """Through the real job: the agent edits the compose file a preview reads, and the pull request
    the person merges lists it with its hash."""
    from openfactory.adapters.sandbox import WorktreeSandbox
    from openfactory.contracts import AcceptanceCriterion, AgentRunResult, Ticket
    from tests.test_walking_skeleton import FakeAgent, FakeReviewer, FakeTracker
    from tests.test_walking_skeleton import _runner as skeleton_runner

    class ShapeAgent(FakeAgent):
        def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
            (workspace.path / ".openfactory").mkdir(exist_ok=True)
            (workspace.path / ".openfactory" / "project.yaml").write_text(
                "preview:\n  compose: [docker-compose.yml]\n  expose: {web: 3000}\n")
            (workspace.path / "docker-compose.yml").write_text("services: {web: {build: .}}\n")
            return AgentRunResult(ok=True, cost_usd=0.01, actions=["Write: docker-compose.yml"])

    ticket = Ticket(id="#32", title="compose", objective="add a compose file", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="compose exists")])
    manifest = Manifest(validate={"test": "true", "security": "true"})
    runner = skeleton_runner(repo, FakeTracker(ticket), manifest, tmp_path, agent=ShapeAgent(),
                             reviewer=FakeReviewer(), sandbox=WorktreeSandbox(root=tmp_path / "wt"))

    result = runner.run("#32")

    assert [line.split()[0] for line in result.preview_shape] == ["docker-compose.yml"]
    assert "What merging this lets the factory run" in runner.forge.opened["body"]
