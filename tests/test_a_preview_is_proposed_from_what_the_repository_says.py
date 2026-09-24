"""A repository that cannot say how it runs gets that said FOR it — as a draft that restates only
what was read, tiered, proposed on a pull request of its own, never built or run before a person
merges it (#265 slice 4; ADR-0050 D12; the design's §4).

What these tests hold, in the order it protects something:

- NOTHING RUNS ON THE MACHINE THAT ASKED. The drafter reads files. The verb clones, writes and
  pushes — and builds nothing, even with a Dockerfile whose `RUN` would touch the disk; `--prove`
  is the deployment's runtime, refused where there is none.
- A SECRET'S VALUE IS NEVER IN A DRAFT. A literal that looks like a credential is flagged by name
  and `file:line`; a secret an application reads is listed for the registry; no excerpt, row,
  file or body carries the value.
- THE TIERS DECIDE WHAT IS WRITTEN. Observed always, inferred with `--accept`, unknown never — a
  port nobody stated keeps the whole block out and is the pull request's first line.
- A DOCKERFILE IS DRAFTED ONLY WHEN ITS START IS ANCHORED to a file that was read.
- THE MANIFEST KEEPS ITS COMMENTS, and a dotted `--set` answers a field.
- EVERY SCENARIO IS BYTE FOR BYTE WHAT ITS GOLDEN SAYS (S2, S3, S4, S5, S8, S9 —
  `tests/fixtures/preview/propose/README.md`), and every draft is read back by the preview's own
  reader and admitted with no refusal, on the canonical form the pinned compose CLI wrote for it.
- NO JOB OPENS ONE. Opening a proposal is a person's verb; a card only asks whether one is open,
  when it is read.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

from openfactory import preview
from openfactory.contracts.manifest import Manifest, PreviewConfig
from openfactory.contracts.project import Project
from openfactory.onboarding import preview_propose
from openfactory.onboarding.infer import INFERRED, OBSERVED, UNKNOWN, infer
from openfactory.onboarding.preview_infer import (
    DRAFT_COMPOSE,
    credential,
    infer_preview,
)
from openfactory.onboarding.preview_propose import (
    BRANCH,
    Shape,
    card_sentence,
    dotted,
    draft,
    merge_field,
    offer_facts,
    open_proposal,
    pr_body,
    proposal_said,
    propose_preview,
)
from openfactory.preview.admit import admit
from openfactory.preview.assemble import assemble, url_var
from openfactory.preview.plan import Layout, PreviewPlan, Tree, Unit
from openfactory.preview.read import Shape as ReadShape
from openfactory.preview.read import shape

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "preview" / "propose"
#: scenario → (project, repository, proposed with --accept)
SCENARIOS = {
    "s2": ("acme-api", "acme/api", True),
    "s3": ("acme-api", "acme/api", True),
    "s4": ("acme-shop", "acme/shop", True),
    "s5": ("acme-shop", "acme/shop", True),
    "s8": ("acme-orders", "acme/orders", False),
    "s9": ("acme-api", "acme/api", True),
}
MANIFEST = "# the team's own words\nversion: 1\n"


@pytest.fixture(autouse=True)
def _no_domain(monkeypatch):
    monkeypatch.delenv("OPENFACTORY_PREVIEW_DOMAIN", raising=False)
    monkeypatch.setattr(preview_propose, "_ASKED", {})


def _repo(tmp_path: Path, scenario: str) -> Path:
    root = Path(os.path.realpath(tmp_path)) / "app"
    shutil.copytree(FIXTURES / scenario / "tree", root)
    return root


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def _expected(scenario: str) -> dict[str, str]:
    base = FIXTURES / scenario / "expected"
    return {str(p.relative_to(base)): p.read_text() for p in sorted(base.rglob("*"))
            if p.is_file() and p.name != "pull-request.md"}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


# ── 1. every scenario, byte for byte ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_every_scenario_drafts_byte_for_byte_what_its_golden_says(scenario, tmp_path):
    name, repo, accept = SCENARIOS[scenario]
    root = _repo(tmp_path, scenario)
    out = propose_preview(Project(name=name, repo_path=str(root)), repo=repo, accept=accept)
    assert out.ok, out.detail
    expected = _expected(scenario)
    assert sorted(out.wrote) == sorted(expected)
    for rel, text in expected.items():
        assert (root / rel).read_text() == text, rel
    assert out.body == (FIXTURES / scenario / "expected" / "pull-request.md").read_text()


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_every_draft_means_what_its_commented_lines_say(scenario):
    """The files are written by hand so each line can cite its source; they must still PARSE to
    exactly the document the draft intends, and the manifest must load."""
    name, repo, accept = SCENARIOS[scenario]
    found = infer_preview(FIXTURES / scenario / "tree", name=repo.rsplit("/", 1)[-1])
    out = draft(found, accept=accept)
    compose = yaml.safe_load(out.files[DRAFT_COMPOSE])
    assert list(compose["services"]) == out.written
    assert yaml.safe_load(out.block_text) == {"preview": out.block}
    Manifest.model_validate(yaml.safe_load(_expected(scenario)[".openfactory/project.yaml"]))


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_every_draft_round_trips_through_the_reader_and_admission_with_no_refusal(scenario,
                                                                                  tmp_path):
    """The block names the files; the preview's own reader pre-scans them and hands them to the
    compose CLI (here, its recorded answer on the pinned v2.32.4); admission judges the result key
    by key. A draft that admission refused would be a proposal nobody could ever preview."""
    wd = Path(os.path.realpath(tmp_path)) / "openfactory-pv-acme-0"
    base = wd / "base" / "app"
    shutil.copytree(FIXTURES / scenario / "tree", base)
    for rel, text in _expected(scenario).items():
        _write(base, {rel: text})
    cfg = PreviewConfig.model_validate(
        yaml.safe_load((base / ".openfactory/project.yaml").read_text())["preview"])
    layout = Layout(workdir=str(wd), trees={"app": Tree(repo="acme/app", dir="app",
                                                         base_branch="main",
                                                         base_commit="b" * 40)})
    recorded = (FIXTURES / scenario / "canonical.json").read_text().replace('"/pv/', f'"{wd}/')
    asked: list[list[str]] = []

    def run(argv, **kw):
        asked.append([argv[i + 1] for i, a in enumerate(argv) if a == "-f"])
        return subprocess.CompletedProcess(argv, 0, recorded, "")

    found = shape(layout, cfg, tree="app", run=run)
    assert isinstance(found, ReadShape), getattr(found, "reasons", found)
    assert asked == [[f"{base}/{f}" for f in cfg.compose]]
    urls = {f"OPENFACTORY_PREVIEW_URL_{url_var(s)}": "" for s in cfg.expose}
    internal = {f"OPENFACTORY_PREVIEW_INTERNAL_URL_{url_var(s)}": "" for s in cfg.expose}
    admitted = admit(found.doc, allow_names={"*": {**urls, **internal}},
                     build_names={"*": dict(urls)}, trees=[str(base)], exclude=cfg.exclude,
                     project="acme")
    assert admitted.refused == []
    assert not [n for n in admitted.notes if "OPENFACTORY_PREVIEW_" in n], admitted.notes
    planned = assemble(found.doc, cfg=cfg, layout=layout, prove=True, expires_at=1_900_000_000,
                       unit=Unit(project="acme", kind="card", id="the base product", token="0"),
                       domain="preview.example.com")
    assert isinstance(planned, PreviewPlan), getattr(planned, "reasons", planned)
    assert set(cfg.expose) <= set(planned.doc["services"])


# ── 2. what each shape of repository gets ────────────────────────────────────────────────────────


def test_s2_the_override_builds_the_image_only_service_from_the_repository_root():
    found = infer_preview(FIXTURES / "s2" / "tree", name="api")
    api = next(s for s in found.services if s.name == "api")
    # measured on v2.32.4: an override's paths resolve against the FIRST file's directory
    assert (api.kind, api.context, api.dockerfile, api.tier) == ("patch", ".", "Dockerfile",
                                                                INFERRED)
    assert {e.locator for e in api.evidence} >= {"Dockerfile:4", "compose.yaml:13"}
    assert found.compose.value == ["compose.yaml", DRAFT_COMPOSE]
    assert {k: (p.value, p.confidence) for k, p in found.expose.items()} == {
        "web": (3000, INFERRED), "api": (8000, INFERRED)}, "a store is never proposed to open"
    assert found.data["api"].confidence == UNKNOWN


def test_s2_two_image_only_services_and_nothing_to_tie_a_dockerfile_to_either_is_asked(tmp_path):
    root = _write(tmp_path / "app", {
        "compose.yaml": "services:\n  web:\n    image: ghcr.io/acme/web\n  api:\n"
                        "    image: ghcr.io/acme/api\n",
        "Dockerfile": "FROM busybox\nCMD [\"true\"]\n"})
    found = infer_preview(root, name="app")
    assert found.services == []
    assert any(q.startswith("which service does `Dockerfile` build: `web` or `api`?")
               for q in found.questions)


def test_s9_a_managed_database_gets_a_fresh_stand_in_and_the_operators_way_is_said():
    found = infer_preview(FIXTURES / "s9" / "tree", name="api")
    db = next(s for s in found.services if s.name == "db")
    api = next(s for s in found.services if s.name == "api")
    assert (db.kind, db.image, db.healthcheck[0]) == ("store", "postgres:16", "CMD-SHELL")
    assert [(e.name, e.value) for e in api.environment] == [
        ("DATABASE_URL", "postgres://app:app@db:5432/app")]
    assert api.depends_on == ["db"]
    note = next(n for n in found.notes if "db.prod.example.com" in n)
    assert "--network <network>" in note and "NON-PRODUCTION" in note
    assert any(q.startswith("which service stands in for `search.internal.example.com`")
               for q in found.questions)
    assert not any("localhost" in q or "`web`" in q.split("?")[0] for q in found.questions)


def test_s4_one_service_per_directory_and_the_rest_is_asked():
    found = infer_preview(FIXTURES / "s4" / "tree", name="shop")
    assert [s.name for s in found.services] == ["api", "web", "db", "redis"]
    asked = " ".join(found.questions)
    assert "`worker/Dockerfile` or `worker/Dockerfile.dev`" in asked, "two in one directory"
    assert "`tools/loadtest/Dockerfile` is deeper than one directory" in asked
    assert "worker" not in {s.name for s in found.services}


def test_s4_every_store_is_healthchecked_and_waited_for():
    found = infer_preview(FIXTURES / "s4" / "tree", name="shop")
    stores = {s.name: s for s in found.services if s.kind == "store"}
    assert {n: s.healthcheck for n, s in stores.items()} == {
        "db": ["CMD-SHELL", "pg_isready -U app -d app"], "redis": ["CMD", "redis-cli", "ping"]}
    api = next(s for s in found.services if s.name == "api")
    assert api.depends_on == ["db", "redis"]
    compose = yaml.safe_load(draft(found, accept=True).files[DRAFT_COMPOSE])
    assert compose["services"]["api"]["depends_on"] == {
        "db": {"condition": "service_healthy"}, "redis": {"condition": "service_healthy"}}


def test_s4_the_browser_and_the_server_each_get_their_own_address_of_the_api(tmp_path):
    found = infer_preview(FIXTURES / "s4" / "tree", name="shop")
    web = yaml.safe_load(draft(found, accept=True).files[DRAFT_COMPOSE])["services"]["web"]
    assert web["environment"] == {
        "NEXT_PUBLIC_API_URL": "${OPENFACTORY_PREVIEW_URL_API}",
        "API_INTERNAL_URL": "${OPENFACTORY_PREVIEW_INTERNAL_URL_API}"}
    assert web["build"]["args"] == {"NEXT_PUBLIC_API_URL": "${OPENFACTORY_PREVIEW_URL_API}"}
    # without a file saying it renders on its server, the second name is asked, never guessed
    root = _repo(tmp_path, "s4")
    (root / "web" / "next.config.js").unlink()
    again = infer_preview(root, name="shop")
    web = next(s for s in again.services if s.name == "web")
    assert [e.name for e in web.environment] == ["NEXT_PUBLIC_API_URL"]
    assert any(q.startswith("does `web` call `api` at `API_INTERNAL_URL`")
               for q in again.questions)


def test_s8_a_chart_is_noted_and_never_read_and_every_line_is_observed():
    found = infer_preview(FIXTURES / "s8" / "tree", name="orders")
    assert any(n.startswith("`chart/` exists; the core reads no chart") for n in found.notes)
    assert "chart/Chart.yaml" not in found.read
    out = draft(found, accept=False)
    assert out.block == {"compose": [DRAFT_COMPOSE], "expose": {"orders": 8080}}
    assert out.left_out == [], "one merge, no --accept: nothing was inferred"


def test_a_repository_that_declares_its_preview_is_not_proposed_again(tmp_path):
    root = _repo(tmp_path, "s3")
    manifest = root / ".openfactory/project.yaml"
    manifest.write_text(manifest.read_text() + "preview:\n  compose: [c.yml]\n  expose: {a: 1}\n")
    found = infer_preview(root, name="api")
    assert (found.case, found.declared) == ("declared", {"compose": ["c.yml"],
                                                         "expose": {"a": 1}})
    out = propose_preview(Project(name="acme-api", repo_path=str(root)), repo="acme/api")
    assert not out.ok and "already declares `preview:`" in out.detail


# ── 3. the tiers decide what is written ─────────────────────────────────────────────────────────


def test_a_port_nobody_stated_is_never_written_and_is_the_first_line(tmp_path):
    root = _write(tmp_path / "api", {"Dockerfile": "FROM python:3.12-slim\nCMD [\"python\"]\n",
                                     ".openfactory/project.yaml": MANIFEST})
    found = infer_preview(root)
    assert (found.expose["api"].value, found.expose["api"].confidence) == (None, UNKNOWN)
    out = draft(found, accept=True)
    assert out.block is None and out.first.startswith("which port does `api` listen on")
    assert "expose" not in out.files[DRAFT_COMPOSE]
    body = pr_body(found, out, project="acme", repo="acme/api")
    assert body.splitlines()[0] == f"**Before this can be previewed:** {out.first}"
    answered = draft(found, accept=True, answers=dotted(["preview.expose.api=8000"]))
    assert answered.block == {"compose": [DRAFT_COMPOSE], "expose": {"api": 8000}}
    assert "api: 8000   # answered · `--set`" in answered.block_text


def test_an_inferred_line_waits_for_accept_and_is_said_when_it_does():
    found = infer_preview(FIXTURES / "s3" / "tree", name="api")
    out = draft(found, accept=False)
    compose = yaml.safe_load(out.files[DRAFT_COMPOSE])
    assert list(compose["services"]) == ["api"]
    assert compose["services"]["api"]["environment"] == {"LOG_LEVEL": "info"}
    assert "depends_on" not in compose["services"]["api"]
    assert any(line.startswith("`db` (inferred · requirements.txt:3) — `--accept` writes it")
               for line in out.left_out)
    assert any("`DATABASE_URL`" in line for line in out.left_out)
    assert out.block == {"compose": [DRAFT_COMPOSE], "expose": {"api": 8000}}


def test_a_draft_that_is_all_inferred_writes_nothing_without_accept(tmp_path):
    root = _repo(tmp_path, "s5")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    out = propose_preview(Project(name="acme-shop", repo_path=str(root)), repo="acme/shop")
    assert out.ok and out.nothing and "`--accept`" in out.detail
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_an_answer_naming_a_service_the_draft_does_not_run_is_refused():
    found = infer_preview(FIXTURES / "s3" / "tree", name="api")
    out = draft(found, accept=True, answers=dotted(["preview.expose.apii=8000"]))
    assert "`apii`, which this proposal does not run" in out.refusal
    assert draft(found, answers={"validate": {"test": "x"}}).refusal.startswith(
        "`--set` writes the `preview:` block and nothing else")


# ── 4. a Dockerfile only when its start is anchored ──────────────────────────────────────────────


def test_nothing_is_drafted_when_nothing_anchors_a_start_command(tmp_path):
    root = _write(tmp_path / "svc", {
        "requirements.txt": "flask==3.0.0\n", "app.py": "print('hi')\n",
        ".python-version": "3.12\n",
        ".openfactory/project.yaml": MANIFEST + "setup:\n  - pip install -r requirements.txt\n"})
    found = infer_preview(root)
    assert (found.case, found.dockerfiles, found.services) == ("nothing", [], [])
    assert found.questions[0].startswith("how does `svc` start? Nothing here says")
    out = propose_preview(Project(name="svc", repo_path=str(root)), repo="acme/svc")
    assert out.ok and out.nothing and not (root / DRAFT_COMPOSE).exists()


@pytest.mark.parametrize("files,command,tier,port", [
    ({"Procfile": "web: gunicorn shop.wsgi --bind 0.0.0.0:8001\n"},
     "gunicorn shop.wsgi --bind 0.0.0.0:8001", OBSERVED, (8001, OBSERVED)),
    ({"package.json": '{"scripts": {"start": "node server.js"}, "engines": {"node": ">=20"}}'},
     ["npm", "start"], OBSERVED, (3000, INFERRED)),
    ({"Makefile": "run:\n\tuvicorn app:app --port 9000\n"},
     "uvicorn app:app --port 9000", OBSERVED, (9000, OBSERVED)),
    ({"manage.py": "print()\n"},
     ["python", "manage.py", "runserver", "0.0.0.0:8000"], INFERRED, (8000, INFERRED)),
])
def test_each_anchor_drafts_from_the_line_it_read(files, command, tier, port, tmp_path):
    root = _write(tmp_path / "svc", {
        **files, ".python-version": "3.12\n", "requirements.txt": "flask\n",
        ".openfactory/project.yaml": MANIFEST + "setup:\n  - pip install -r requirements.txt\n"})
    df, = infer_preview(root).dockerfiles
    assert (df.command, df.command_tier) == (command, tier)
    assert (df.port, df.port_tier) == port
    assert df.install == ["pip install -r requirements.txt"] and df.install_tier == OBSERVED


def test_the_drafted_image_copies_the_repositorys_roots_and_keeps_git_and_env_out():
    found = infer_preview(FIXTURES / "s5" / "tree", name="shop")
    out = draft(found, accept=True)
    dockerfile = out.files[".openfactory/preview/shop.Dockerfile"]
    assert "COPY . ." not in dockerfile.replace("`COPY . .`", "")
    assert "COPY manage.py requirements.txt ./\nCOPY shop ./shop\n" in dockerfile
    ignore = out.files[".openfactory/preview/shop.Dockerfile.dockerignore"]
    assert {".git", ".env*", "node_modules"} <= set(ignore.splitlines())


def test_no_version_marker_means_no_base_image_is_guessed(tmp_path):
    root = _write(tmp_path / "svc", {"manage.py": "print()\n", "requirements.txt": "django\n",
                                     ".openfactory/project.yaml":
                                         MANIFEST + "setup:\n  - pip install -r r.txt\n"})
    found = infer_preview(root)
    assert found.dockerfiles == []
    assert any("which python version `svc` runs on" in q for q in found.questions)


# ── 5. a secret's value is never in a draft ──────────────────────────────────────────────────────


@pytest.mark.parametrize("name,value,why", [
    ("DATABASE_URL", "postgres://app:hunter2@db:5432/app", "a password inside the address"),
    ("DATABASE_URL", "postgres://app:${DB_PASSWORD}@db:5432/app", ""),
    ("DATABASE_URL", "postgres://db:5432/app", ""),
    ("JWT_SECRET", "dev", "its name says it holds a secret"),
    ("SECRET_KEY_BASE", "x", "its name says it holds a secret"),
    ("POSTGRES_PASSWORD", "app", "its name says it holds a secret"),
    ("API_TOKEN", "${API_TOKEN}", ""),
    ("KEYBOARD_LAYOUT", "us", ""),
    ("LOG_LEVEL", "info", ""),
    ("SECRET_KEY", "", ""),
])
def test_what_looks_like_a_credential(name, value, why):
    assert credential(name, value) == why


def test_a_literal_credential_is_flagged_by_name_and_its_value_goes_nowhere(tmp_path):
    root = _write(tmp_path / "app", {
        "compose.yaml": "services:\n  api:\n    build: .\n    ports: ['8000:8000']\n"
                        "    environment:\n"
                        "      DATABASE_URL: postgres://app:PLANTED-pw-1@db:5432/app\n"
                        "      STRIPE_SECRET_KEY: PLANTED-sk-2\n"
                        "      SENTRY_DSN: ${SENTRY_DSN}\n"
                        "      LOG_LEVEL: info\n"
                        "    depends_on: [db]\n"
                        "  db:\n    image: postgres:16\n",
        "Dockerfile": "FROM busybox\nEXPOSE 8000\n",
        ".openfactory/project.yaml": MANIFEST})
    found = infer_preview(root)
    assert [(f.locator, f.service, f.name) for f in found.flags] == [
        ("compose.yaml:6", "api", "DATABASE_URL"), ("compose.yaml:7", "api", "STRIPE_SECRET_KEY")]
    out = propose_preview(Project(name="acme", repo_path=str(root)), repo="acme/app",
                          accept=True)
    assert out.ok, out.detail
    assert "gives `api` a literal `STRIPE_SECRET_KEY` (its name says it holds a secret)" in out.body
    assert "set-preview acme --env api=STRIPE_SECRET_KEY=<WORKER_NAME>" in out.body
    # the value stays in the team's own file, and only there
    for text in (out.body, json.dumps(found.model_dump()), json.dumps(infer(root).preview),
                 *((root / p).read_text() for p in out.wrote)):
        assert "PLANTED" not in text


def test_a_line_holding_a_secret_is_named_never_quoted_and_never_copied_into_a_draft(tmp_path):
    root = _write(tmp_path / "api", {
        "Dockerfile": "FROM python:3.12-slim\nEXPOSE 8000\n"
                      "CMD [\"serve\", \"--password=PLANTED-pw-5\"]\n",
        ".openfactory/project.yaml": MANIFEST})
    found = infer_preview(root)
    out = draft(found)
    body = pr_body(found, out, project="acme", repo="acme/api")
    assert "(not quoted: it carries what looks like a credential) — Dockerfile:3" in body
    assert "PLANTED" not in body and "PLANTED" not in json.dumps(found.model_dump())
    procfile = _write(tmp_path / "web", {
        "Procfile": "web: API_TOKEN=PLANTED-tok-6 gunicorn app:app --bind 0.0.0.0:8000\n",
        ".python-version": "3.12\n", "requirements.txt": "gunicorn\n",
        ".openfactory/project.yaml": MANIFEST + "setup:\n  - pip install -r requirements.txt\n"})
    found = infer_preview(procfile)
    assert found.dockerfiles == [] and "PLANTED" not in json.dumps(found.model_dump())
    assert any(q.startswith("the start command at Procfile:1 carries what looks like a "
                            "credential") for q in found.questions)


def test_a_secret_an_example_file_names_is_left_for_the_registry_and_never_copied(tmp_path):
    root = _write(tmp_path / "api", {
        "Dockerfile": "FROM python:3.12-slim\nEXPOSE 8000\n",
        "requirements.txt": "psycopg2-binary\n",
        ".env.example": "DATABASE_URL=postgres://u:PLANTED-pw-3@localhost:5432/x\n"
                        "API_TOKEN=PLANTED-tok-4\nLOG_LEVEL=debug\n",
        ".openfactory/project.yaml": MANIFEST})
    found = infer_preview(root)
    assert [(r.name, r.locator) for r in found.registry] == [("API_TOKEN", ".env.example:2")]
    out = draft(found, accept=True)
    env = yaml.safe_load(out.files[DRAFT_COMPOSE])["services"]["api"]["environment"]
    assert env == {"DATABASE_URL": "postgres://app:app@db:5432/app", "LOG_LEVEL": "debug"}
    body = pr_body(found, out, project="acme", repo="acme/api")
    assert "`API_TOKEN` (.env.example:2)" in body and "set-preview acme --env api=API_TOKEN=" in body
    for text in (body, json.dumps(found.model_dump()), *out.files.values()):
        assert "PLANTED" not in text


# ── 6. the manifest keeps its comments; `--set` is a dotted path ────────────────────────────────


def test_merge_field_keeps_every_comment_of_a_fixture_manifest():
    text = (FIXTURES / "s2" / "tree" / ".openfactory" / "project.yaml").read_text()
    block = {"compose": ["compose.yaml"], "expose": {"api": 8000}}
    merged = merge_field(text, "preview", block)
    assert merged.comments_kept and not merged.refusal
    assert merged.text.startswith(text), "every byte the team wrote is still there, in place"
    assert yaml.safe_load(merged.text) == {**yaml.safe_load(text), "preview": block}
    Manifest.model_validate(yaml.safe_load(merged.text))


@pytest.mark.parametrize("text", [
    "{version: 1, validate: {test: pytest}}\n",          # a flow mapping takes no append
    "# ours\nversion: 1\n...\n",                          # nor does a document that has ended
])
def test_merge_field_rewrites_the_file_only_when_an_append_cannot_mean_it_and_says_so(text):
    block = {"compose": ["compose.yaml"], "expose": {"api": 8000}}
    merged = merge_field(text, "preview", block)
    assert not merged.refusal and merged.comments_kept is False
    assert yaml.safe_load(merged.text) == {**yaml.safe_load(text), "preview": block}
    found = infer_preview(FIXTURES / "s8" / "tree", name="orders")
    body = pr_body(found, draft(found), project="p", repo="acme/orders", comments_kept=False)
    assert "lost its comments" in body


def test_merge_field_refuses_what_the_file_already_declares_and_what_would_not_load():
    declared = merge_field("version: 1\npreview: {compose: [a.yml], expose: {a: 1}}\n",
                           "preview", {"compose": ["b.yml"], "expose": {"b": 2}})
    assert declared.refusal.startswith("the manifest already declares `preview:`")
    invalid = merge_field(MANIFEST, "preview", {"compose": ["../x.yml"], "expose": {"a": 1}})
    assert invalid.refusal.startswith("`preview:` would not validate in the manifest")


def test_a_dotted_set_nests_parses_ports_and_round_trips_through_the_manifest():
    said = dotted(["preview.expose.app=8000", "preview.data.app=python manage.py migrate",
                   "preview.compose=compose.yaml,.openfactory/preview.compose.yml",
                   "preview.exclude=worker"])
    assert said == {"preview": {
        "expose": {"app": 8000}, "data": {"app": "python manage.py migrate"},
        "compose": ["compose.yaml", ".openfactory/preview.compose.yml"],
        "exclude": ["worker"]}}
    loaded = Manifest.model_validate({"version": 1, **said})
    assert loaded.preview.expose == {"app": 8000} and loaded.preview.exclude == ["worker"]


@pytest.mark.parametrize("bad", ["preview.expose.app", "=8000", "preview..app=1", ".x=1"])
def test_a_set_that_is_not_a_dotted_pair_is_refused_by_name(bad):
    with pytest.raises(ValueError, match=r"is not `<dotted.path>=<value>`"):
        dotted([bad])
    with pytest.raises(ValueError, match="an earlier `--set`"):
        dotted(["preview.expose=1", "preview.expose.app=2"])


# ── 7. nothing is built where the verb runs ─────────────────────────────────────────────────────


class _Forge:
    """The forge port, at the methods a proposal uses."""

    def __init__(self, *, existing: str | None = "", remote: Path | None = None):
        self._existing = existing
        self.remote = remote
        self.opened: list[dict] = []

    def clone_url(self, repo, *, token=None):
        return str(self.remote)

    def pr_for_head(self, head, *, repo=""):
        if self._existing is None:
            raise RuntimeError("the forge could not be reached")
        return self._existing

    def pr_status(self, *, pr, repo=""):
        return "open"

    def list_branches(self, repo="", *, prefix=""):
        return []

    def open_pr(self, *, head, base, title, body, repo=""):
        self.opened.append({"head": head, "base": base, "title": title, "body": body,
                            "repo": repo})
        return f"https://forge.example/{repo}/pull/7"


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    """`acme-api`, registered by URL, whose forge is doubled and whose clone is a real bare
    repository seeded with a scenario's tree — the git side stays production code."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))

    def _make(scenario: str, extra: dict[str, str] | None = None, *, existing: str | None = ""):
        from openfactory.adapters.forge import registry as forge_registry

        remote = tmp_path / "origin.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True,
                       capture_output=True)
        seed = _repo(tmp_path / "seed", scenario)
        _write(seed, extra or {})
        ident = ["-c", "user.email=t@example.com", "-c", "user.name=t"]
        for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                     [*ident, "commit", "-qm", "seed"], ["push", "-q", str(remote), "main"]):
            subprocess.run(["git", *args], cwd=seed, check=True, capture_output=True)
        forge = _Forge(existing=existing, remote=remote)
        monkeypatch.setattr(forge_registry, "build_forge", lambda *a, **kw: forge)
        monkeypatch.setattr(forge_registry, "clone_url_for", lambda *a, **kw: str(remote))
        out = CliRunner().invoke(_cli(), ["project", "add", "acme-api",
                                          "https://github.com/acme/api.git"])
        assert out.exit_code == 0, out.output
        return forge, remote

    return _make


def _cli():
    from openfactory.cli import app

    return app


class _Processes:
    """Every process the verb starts, recorded; anything but git refused before it runs."""

    def __init__(self, monkeypatch):
        self.argv: list[list[str]] = []
        real = subprocess.run

        def run(argv, *a, **kw):
            argv = [str(x) for x in argv]
            self.argv.append(argv)
            if Path(argv[0]).name != "git":
                return subprocess.CompletedProcess(argv, 127, "", f"{argv[0]}: refused here")
            return real(argv, *a, **kw)

        monkeypatch.setattr(subprocess, "run", run)

    def ran(self, name: str) -> list[list[str]]:
        return [a for a in self.argv if Path(a[0]).name == name]


def test_no_build_runs_on_the_machine_that_proposes(hosted, tmp_path, monkeypatch):
    """A `RUN` that touches the disk, in the repository's own Dockerfile, on a deployment that
    names a real runtime: proposing builds nothing, runs no docker, and leaves the disk alone."""
    touched = Path(os.path.realpath(tmp_path)) / "touched-by-a-build"
    forge, _ = hosted("s3", {"Dockerfile": "FROM python:3.12-slim\n"
                                           f"RUN touch {touched}\nEXPOSE 8000\n"})
    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", "compose")
    processes = _Processes(monkeypatch)
    out = CliRunner().invoke(_cli(), ["preview", "propose", "acme-api", "--accept", "--yes"])
    assert out.exit_code == 0, out.output
    assert forge.opened, out.output
    assert processes.ran("docker") == [], "a proposal never runs docker where it is asked"
    assert {Path(a[0]).name for a in processes.argv} == {"git"}
    assert not touched.exists()
    assert "**Not built.**" in forge.opened[0]["body"]


def test_prove_is_refused_where_the_deployment_names_no_runtime(hosted, monkeypatch):
    forge, _ = hosted("s3")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", "none")
    processes = _Processes(monkeypatch)
    out = CliRunner().invoke(_cli(), ["preview", "propose", "acme-api", "--prove", "--yes"])
    assert out.exit_code == 2
    assert "no proof" in out.output and "nothing was proposed" in out.output
    assert processes.argv == [] and forge.opened == []


def test_prove_hands_the_draft_to_the_deployments_runtime_and_the_body_says_what_it_did(
        hosted, monkeypatch):
    from openfactory import cli
    from openfactory.onboarding.preview_propose import proof_sentence
    from openfactory.preview.plan import PreviewUp

    forge, _ = hosted("s3")
    proved: list[tuple] = []

    def prover(project, files, block):
        proved.append((project.name, dict(files), block))
        return proof_sentence(PreviewUp(ok=True, health={"api": "started"}), 100)

    monkeypatch.setattr(cli, "_preview_prover", lambda kind: (prover, ""))
    out = CliRunner().invoke(_cli(), ["preview", "propose", "acme-api", "--accept", "--prove",
                                      "--yes"])
    assert out.exit_code == 0, out.output
    (name, files, block), = proved
    assert name == "acme-api" and set(files) == {DRAFT_COMPOSE}
    assert block == {"compose": [DRAFT_COMPOSE], "expose": {"api": 8000}}
    assert ("**Proved on the deployment:** the base branch with this draft applied was built, "
            "came up and was taken down again in 1m40s — api: started, not health-checked."
            ) in forge.opened[0]["body"]


def test_a_proof_writes_the_draft_into_a_fresh_base_checkout_and_plans_nothing_else(
        tmp_path, monkeypatch):
    from openfactory.adapters.preview import compose
    from openfactory.preview.plan import PreviewUp

    wd = Path(os.path.realpath(tmp_path)) / "openfactory-pv-acme-0"
    (wd / "base" / "app").mkdir(parents=True)
    layout = Layout(workdir=str(wd), trees={"app": Tree(repo="acme/app", dir="app")})
    monkeypatch.setattr(compose, "materialise", lambda unit, project: layout)
    monkeypatch.setattr(compose, "_remove_workdir", lambda w: [])
    planned: list = []

    def plan(layout, unit, project, *, cfg=None, now=None, prove=False):
        planned.append((cfg, prove, (wd / "base/app/.openfactory/preview.compose.yml").read_text()))
        return compose.Refused(reasons=("stop here",))

    monkeypatch.setattr(compose, "plan", plan)
    runtime = SimpleNamespace(prove=lambda p: PreviewUp(ok=True))
    cfg = PreviewConfig(compose=[DRAFT_COMPOSE], expose={"api": 8000})
    up = compose.prove_project(SimpleNamespace(name="acme"), runtime, cfg=cfg,
                               draft={DRAFT_COMPOSE: "services: {}\n"})
    assert (up.ok, up.why) == (False, "stop here")
    assert planned == [(cfg, True, "services: {}\n")]
    out = compose.prove_project(SimpleNamespace(name="acme"), runtime, cfg=cfg,
                                draft={"../../escape.yml": "x"})
    assert not out.ok and "not a path inside the repository" in out.why
    assert not (wd / "escape.yml").exists() and not (wd.parent / "escape.yml").exists()


# ── 8. its own pull request, on its own branch ───────────────────────────────────────────────────


def test_the_proposal_is_its_own_pull_request_carrying_the_golden_files(hosted):
    forge, remote = hosted("s2")
    out = CliRunner().invoke(_cli(), ["preview", "propose", "acme-api", "--accept", "--yes"])
    assert out.exit_code == 0, out.output
    opened, = forge.opened
    assert (opened["head"], opened["base"], opened["title"]) == (
        BRANCH, "main", "OpenFactory: a preview of acme/api")
    assert opened["body"] == (FIXTURES / "s2" / "expected" / "pull-request.md").read_text()
    for rel, text in _expected("s2").items():
        assert _git(remote, "show", f"{BRANCH}:{rel}") == text, rel
    message = _git(remote, "log", "-1", "--format=%B", BRANCH)
    assert message.startswith("chore: propose how OpenFactory previews acme-api")
    assert "pull/7" in out.output


@pytest.mark.parametrize("existing,said", [
    ("https://forge.example/acme/api/pull/3", "already proposed at"),
    (None, "could not ask"),
])
def test_an_open_proposal_is_named_and_could_not_ask_proposes_nothing(existing, said, hosted):
    forge, remote = hosted("s3", existing=existing)
    out = CliRunner().invoke(_cli(), ["preview", "propose", "acme-api", "--yes"])
    assert said in out.output and forge.opened == []
    assert BRANCH not in _git(remote, "branch", "--list")


def test_a_repository_with_no_manifest_is_refused_and_onboard_is_named(hosted, tmp_path):
    forge, _ = hosted("s3")
    seed = Path(os.path.realpath(tmp_path)) / "seed" / "app"
    _git(seed, "rm", "-q", ".openfactory/project.yaml")
    _git(seed, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "rm")
    _git(seed, "push", "-q", str(forge.remote), "main")
    out = CliRunner().invoke(_cli(), ["preview", "propose", "acme-api", "--yes"])
    assert out.exit_code == 1
    assert "declares no manifest" in out.output and "openfactory onboard acme-api" in out.output
    assert forge.opened == []


def test_without_yes_nothing_is_cloned_or_opened(hosted, monkeypatch):
    forge, _ = hosted("s3")
    processes = _Processes(monkeypatch)
    out = CliRunner().invoke(_cli(), ["preview", "propose", "acme-api"])
    assert out.exit_code == 2 and "re-run with --yes" in out.output
    assert processes.argv == [] and forge.opened == []


def test_as_card_files_the_questions_as_a_card_pickup_would_take(tmp_path):
    from openfactory.adapters.tracker.parse import parse_ticket_body
    from openfactory.orchestrator.machine import spec_verdict

    root = _write(tmp_path / "svc", {"requirements.txt": "flask\n", "app.py": "print()\n",
                                     ".openfactory/project.yaml": MANIFEST})
    filed: list[dict] = []
    tracker = SimpleNamespace(
        create_ticket=lambda *, title, body: filed.append({"title": title, "body": body}) or "#41",
        ticket_url=lambda ref: "https://forge.example/acme/svc/issues/41")
    import openfactory.adapters.tracker.registry as trackers

    original = trackers.build_tracker
    trackers.build_tracker = lambda *a, **kw: tracker
    try:
        out = propose_preview(Project(name="svc", repo_path=str(root)), repo="acme/svc",
                              as_card=True)
    finally:
        trackers.build_tracker = original
    assert out.ok and out.card == "#41" and out.url.endswith("/issues/41")
    card, = filed
    assert card["title"] == "Describe how acme/svc runs for a preview"
    assert "how does `svc` start? Nothing here says" in card["body"]
    ticket = parse_ticket_body(id="41", title=card["title"], body=card["body"], repo="acme/svc")
    assert spec_verdict(ticket) == "" and len(ticket.acceptance_criteria) == 3
    assert not (root / DRAFT_COMPOSE).exists()


# ── 9. the one-machine kind writes into the checkout ─────────────────────────────────────────────


def test_the_one_machine_kind_writes_into_the_checkout_and_says_commit_these(tmp_path,
                                                                            monkeypatch):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    root = _repo(tmp_path, "s8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "seed")
    head = _git(root, "rev-parse", "HEAD")
    assert CliRunner().invoke(_cli(), ["project", "add", "orders", str(root)]).exit_code == 0
    out = CliRunner().invoke(_cli(), ["preview", "propose", "orders", "--yes"])
    assert out.exit_code == 0, out.output
    assert "commit these on `main`" in out.output
    assert (root / DRAFT_COMPOSE).read_text() == _expected("s8")[DRAFT_COMPOSE]
    assert _git(root, "rev-parse", "HEAD") == head, "the person commits; the factory never does"


def test_a_proposal_never_overwrites_a_file_of_yours(tmp_path):
    root = _repo(tmp_path, "s3")
    (root / DRAFT_COMPOSE).write_text("# mine\n")
    manifest = (root / ".openfactory/project.yaml").read_text()
    out = propose_preview(Project(name="acme-api", repo_path=str(root)), repo="acme/api")
    assert not out.ok and "already exists" in out.detail and "never overwrites" in out.detail
    assert (root / DRAFT_COMPOSE).read_text() == "# mine\n"
    assert (root / ".openfactory/project.yaml").read_text() == manifest


# ── 10. read, and `env read` ─────────────────────────────────────────────────────────────────────


def test_preview_read_shows_every_line_tiered_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    root = _repo(tmp_path, "s4")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    out = CliRunner().invoke(_cli(), ["preview", "draft", str(root), "--accept"])
    assert out.exit_code == 0, out.output
    for said in ("OBSERVED", "INFERRED", "UNKNOWN", "preview.expose.api", "api/Dockerfile:6",
                 DRAFT_COMPOSE, "`preview:` in .openfactory/project.yaml",
                 "FOR THE REGISTRY, NEVER A FILE", "JWT_SECRET", "Nothing was written"):
        assert said in out.output, said
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_env_read_attempts_the_preview_and_shows_the_draft_beside_the_manifest(tmp_path,
                                                                              monkeypatch):
    from openfactory.actions.catalog import _proposed_rows

    root = _repo(tmp_path, "s3")   # checked out as `app/`: its root service is named after that
    proposal = infer(root)
    assert "preview" not in proposal.not_attempted
    assert proposal.preview["case"] == "dockerfiles"
    tiers = {r["name"]: r["confidence"] for r in proposal.preview["fields"]}
    assert tiers["preview.expose.app"] == OBSERVED and tiers["preview.service.db"] == INFERRED
    assert tiers["preview.data.app"] == UNKNOWN
    rows, _ = _proposed_rows(proposal)
    assert not [r for r in rows if r["name"].startswith("preview")], \
        "`env apply` writes `fields`, and a preview never rides on it"
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    out = CliRunner().invoke(_cli(), ["env", "read", str(root)])
    assert out.exit_code == 0, out.output
    assert "PREVIEW — how a preview of it would run" in out.output
    assert "preview.expose.app" in out.output and "Dockerfile:6" in out.output


def test_the_drafter_runs_nothing_and_opens_no_socket(monkeypatch):
    import socket

    def forbidden(*a, **kw):
        raise AssertionError("the drafter started a process or opened a socket")

    for target in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, target, forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    for scenario in SCENARIOS:
        found = infer_preview(FIXTURES / scenario / "tree")
        draft(found, accept=True)


# ── 11. the card, and no job ever opens one ──────────────────────────────────────────────────────


@pytest.mark.parametrize("shape_,url,said", [
    (Shape(case="dockerfiles", reads="Dockerfile, EXPOSE 8000", repo="acme/api"),
     "https://forge.example/acme/api/pull/7",
     "No preview of this change yet — `acme/api` declares no `preview:`. A compose file drafted "
     "from its Dockerfile and the block are proposed at https://forge.example/acme/api/pull/7; "
     "merge it (edit it first if it is wrong) and press start here."),
    (Shape(case="dockerfiles", reads="Dockerfile, EXPOSE 8000", repo="acme/api"), "",
     "No preview of this change yet — `acme/api` declares no `preview:`; run `openfactory "
     "preview propose acme-api` to have one drafted from what the repository says: Dockerfile, "
     "EXPOSE 8000."),
    (Shape(case="draft", reads="`Procfile` and `requirements.txt`", repo="acme/shop"), "",
     "No preview of this change yet — nothing on `main` says how it runs (no compose file, no "
     "Dockerfile). `openfactory preview propose acme-api` drafts both from `Procfile` and "
     "`requirements.txt`."),
    (Shape(case="nothing", repo="acme/shop", base="trunk"), "",
     "No preview of this change yet — nothing on `trunk` says how it runs (no compose file, no "
     "Dockerfile), and nothing there anchors a draft. `openfactory preview propose acme-api "
     "--as-card` files the question as a card."),
])
def test_the_card_says_what_would_give_this_change_a_preview(shape_, url, said):
    assert card_sentence(shape_, project="acme-api", proposal_url=url) == said


def test_offer_facts_reads_the_base_and_says_nothing_when_it_declares_a_shape(tmp_path):
    assert offer_facts(FIXTURES / "s3" / "tree", repo="acme/api") == Shape(
        case="dockerfiles", reads="Dockerfile, EXPOSE 8000", repo="acme/api")
    root = _repo(tmp_path, "s3")
    manifest = root / ".openfactory/project.yaml"
    manifest.write_text(manifest.read_text() + "preview:\n  compose: [c.yml]\n  expose: {a: 1}\n")
    assert offer_facts(root, repo="acme/api").case == ""


def test_which_proposal_is_open_is_asked_when_the_card_is_read_and_kept_a_minute():
    answers = iter(["", "https://forge.example/acme/api/pull/9"])
    forge = SimpleNamespace(pr_for_head=lambda head, *, repo="": next(answers),
                            pr_status=lambda *, pr, repo="": "open")
    project = SimpleNamespace(name="acme-api")
    record = preview.Preview(project="acme-api", unit="12", state=preview.OFFERED,
                             shape=Shape(case="dockerfiles", reads="Dockerfile",
                                         repo="acme/api").model_dump(),
                             proposal_url="https://stale.example/1")
    first = proposal_said(record, project, forge=forge, now=1000.0)
    assert first["proposal_url"] == "" and "run `openfactory preview propose" in first["why"]
    cached = proposal_said(record, project, forge=forge, now=1030.0)
    assert cached == first, "asked once a minute, not on every read"
    later = proposal_said(record, project, forge=forge, now=1061.0)
    assert later["proposal_url"] == "https://forge.example/acme/api/pull/9"
    assert "merge it (edit it first if it is wrong) and press start here" in later["why"]
    unreadable = SimpleNamespace(pr_for_head=lambda head, *, repo="": 1 / 0)
    preview_propose._ASKED.clear()
    assert open_proposal(project, "acme/api", forge=unreadable, now=2000.0) is None
    assert proposal_said(record, project, forge=unreadable, now=2000.0)["proposal_url"] == \
        "https://stale.example/1", "could not ask is never read as none open"
    assert proposal_said(preview.Preview(project="acme-api", unit="12", state="offered"),
                         project, forge=forge) == {}


def test_the_panel_computes_the_sentence_when_the_card_is_read(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from openfactory.api import app as api

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOMAIN", "preview.localhost")
    monkeypatch.setattr(api, "ProjectRegistry", lambda: SimpleNamespace(
        get=lambda name: SimpleNamespace(name=name), list=lambda: []))
    answers = iter(["", "https://forge.example/acme/api/pull/9"])
    forge = SimpleNamespace(pr_for_head=lambda head, *, repo="": next(answers),
                            pr_status=lambda *, pr, repo="": "open")
    from openfactory.adapters.forge import registry as forge_registry

    monkeypatch.setattr(forge_registry, "build_forge", lambda *a, **kw: forge)
    preview.record(preview.Preview(project="acme", unit="12", cards=("12",),
                                   state=preview.OFFERED,
                                   shape=Shape(case="dockerfiles", reads="Dockerfile",
                                               repo="acme/api").model_dump()))
    client = TestClient(api.app)
    before = client.get("/api/preview/acme/12").json()
    assert before["proposal_url"] == "" and "openfactory preview propose acme" in before["why"]
    preview_propose._ASKED.clear()
    after = client.get("/api/preview/acme/12").json()
    assert after["proposal_url"] == "https://forge.example/acme/api/pull/9"
    assert after["can_start"] is False


def _callers(name: str) -> set[str]:
    """Every module under `openfactory/` that CALLS `name`, by the syntax tree."""
    found = set()
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                called = fn.id if isinstance(fn, ast.Name) else (
                    fn.attr if isinstance(fn, ast.Attribute) else "")
                if called == name:
                    found.add(str(path.relative_to(ROOT)))
    return found


def test_no_job_opens_a_proposal_only_a_person_does():
    """Opening a proposal is `openfactory preview propose` and `onboard --with-preview`. A job,
    an activity, a workflow, the poller or the panel only ASK whether one is open."""
    assert _callers("propose_preview") == {"openfactory/cli.py"}
    assert _callers("_propose_hosted") | _callers("_propose_local") == {
        "openfactory/onboarding/preview_propose.py"}
    for module in ("openfactory/orchestrator", "openfactory/runtime", "openfactory/api"):
        for path in (ROOT / module).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "propose_preview" not in text and "_draft_into" not in text, path


# ── 12. onboarding and the product's context repository ─────────────────────────────────────────


def test_onboard_with_preview_proposes_through_the_same_function(monkeypatch, tmp_path):
    from openfactory import cli
    from openfactory.onboarding import onboard

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(_cli(), ["project", "add", "acme-api",
                                       "https://github.com/acme/api.git"]).exit_code == 0
    declared = SimpleNamespace(ok=True, detail="nothing to propose", pr="", proof="proven",
                               questions=[], manifest_already_there=True, repo="acme/api",
                               existed=False)
    monkeypatch.setattr(onboard, "onboard_source_repo", lambda *a, **kw: declared)
    asked: list[str] = []
    monkeypatch.setattr(preview_propose, "propose_preview",
                        lambda project, *, repo: asked.append(repo) or
                        preview_propose.Outcome(ok=True, url="https://forge.example/pull/8"))
    out = CliRunner().invoke(cli.app, ["onboard", "acme-api", "--skip-context", "--with-preview",
                                       "--yes"])
    assert asked == ["acme/api"] and "✓ preview: https://forge.example/pull/8" in out.output
    declared.manifest_already_there = False
    asked.clear()
    out = CliRunner().invoke(cli.app, ["onboard", "acme-api", "--skip-context", "--with-preview",
                                       "--yes"])
    assert asked == [], "the block goes into a manifest the base branch does not have yet"
    assert "proposed once the manifest merges" in out.output


def test_the_products_plan_adds_a_preview_only_when_the_file_has_none(tmp_path):
    from openfactory.product.onboard import plan

    project = SimpleNamespace(name="acme", product=SimpleNamespace(docs_repo="acme/ctx",
                                                                   requirements_dir=""))
    block = {"compose": {"paths": [DRAFT_COMPOSE]}, "expose": {"web": 3000}}
    fresh = plan(project, tmp_path, sources=["acme/web"], preview=block)
    assert yaml.safe_load(fresh.product_yaml.split("\n", 4)[-1])["preview"] == block
    assert not fresh.already_correct
    (tmp_path / ".openfactory").mkdir()
    (tmp_path / ".openfactory" / "product.yaml").write_text(
        "product: acme\nsources: [acme/web]\nrequirements_dir: requirements\n"
        "preview: {compose: {paths: [theirs.yml]}, expose: {web: 80}}\n")
    kept = plan(project, tmp_path, sources=["acme/web"], preview=block)
    assert yaml.safe_load(kept.product_yaml.split("\n", 4)[-1])["preview"]["expose"] == \
        {"web": 80}, "a block a person wrote is theirs"
    assert kept.already_correct


def test_the_record_carries_the_shape_and_old_records_still_load():
    old = preview.Preview.model_validate({"project": "a", "unit": "1", "state": "offered"})
    assert old.shape == {}
    new = preview.Preview(project="a", unit="1", state="offered",
                          shape=Shape(case="nothing", repo="a/b").model_dump())
    assert Shape.model_validate(new.shape).case == "nothing"
