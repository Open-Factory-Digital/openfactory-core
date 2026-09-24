"""A preview's shape is read from the base branch, admitted key by key, and assembled for one change
(#265 slice 1; ADR-0050 D2–D4, D8; the design's §2.1, §3.2, §5.3).

What these tests hold, in the order it protects something:

- THE BASE, NEVER THE CHANGE. The compose files are read from `<workdir>/base/<dir>`; the change's
  own compose file — written by an agent — is never opened (S10).
- A WHITELIST. Every key a compose document can carry is passed, set, dropped or refused, and a key
  in no set is refused by name: the first assembler refused a list of dangerous keys and passed
  every other one unexamined.
- ON DISK. Every path is judged after its links are followed, so a git-tracked symlink to the
  docker socket in a mounted directory is refused, not mounted.
- NAMES, NEVER VALUES. A registry name reaches a container as `${WORKER_NAME}`, reaches a build
  only when the operator listed it for builds, and an unlisted `${X}` in the file resolves to its
  default or nothing — never to whatever the compose process's environment holds.
- WHAT CHANGED, DERIVED. A service is from the change when the change's diff touches what it is
  made of; a changed service never carries the client's image tag, an unchanged one pulls `always`;
  a change no service is made of is refused rather than previewed as production.

The scenario tests run on canonical documents RECORDED from the pinned compose plugin (v2.32.4,
`tests/fixtures/preview/README.md`), so nothing here needs Docker.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from openfactory import preview
from openfactory.contracts.manifest import PreviewConfig
from openfactory.contracts.project import PreviewPolicy
from openfactory.preview import plan as plan_models
from openfactory.preview.admit import (
    DROP_BUILD,
    DROP_SERVICE,
    PASS_SERVICE,
    REFUSE_BUILD,
    REFUSE_SERVICE,
    REFUSE_TOP,
    SET_SERVICE,
    admit,
    rewrite,
)
from openfactory.preview.assemble import (
    assemble,
    inputs,
    is_from_change,
    topology_changed,
)
from openfactory.preview.plan import (
    CardRef,
    Layout,
    PreviewPlan,
    Refused,
    Tree,
    TreePath,
    Unit,
)
from openfactory.preview.read import Shape, canonicalise, prescan, shape
from openfactory.preview.unit import unit_of
from tests.test_ports_are_serialisable import _serialisable

FIXTURES = Path(__file__).parent / "fixtures" / "preview"
BASE_SHA, CHANGE_SHA = "b" * 40, "c" * 40
DOMAIN = "preview.example.com"


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────


def _workdir(tmp_path: Path, scenario: str, *, change: bool = True) -> str:
    """A unit's work directory for one fixture: `base/app` is the tree; `change/app` the tree with
    the scenario's `change/` overlay on top. Real paths, so admission's `realpath` agrees."""
    wd = Path(os.path.realpath(tmp_path)) / "openfactory-pv-acme-12"
    shutil.copytree(FIXTURES / scenario / "tree", wd / "base" / "app")
    if change:
        shutil.copytree(FIXTURES / scenario / "tree", wd / "change" / "app")
        overlay = FIXTURES / scenario / "change"
        if overlay.is_dir():
            shutil.copytree(overlay, wd / "change" / "app", dirs_exist_ok=True)
    return str(wd)


def _canonical(scenario: str, wd: str, name: str = "canonical.json") -> dict:
    """The recorded canonical document, its `/pv` checkout moved to this test's work directory."""
    text = (FIXTURES / scenario / name).read_text()
    return json.loads(text.replace('"/pv/', f'"{wd}/'))


def _diff(scenario: str) -> tuple[str, ...]:
    return tuple(ln for ln in (FIXTURES / scenario / "diff.txt").read_text().splitlines() if ln)


def _layout(wd: str, diff: tuple[str, ...] = (), *, change: bool = True) -> Layout:
    return Layout(workdir=wd, trees={"app": Tree(
        repo="acme/shop", dir="app", base_branch="main", base_commit=BASE_SHA,
        merge_base=BASE_SHA if change else "", branch="openfactory/12" if change else "",
        change_commit=CHANGE_SHA if change else "",
        pr_url="https://forge.example/acme/shop/pull/12" if change else "",
        diff_paths=diff if change else ())})


UNIT = Unit(project="acme", kind="card", id="acme/shop#12",
            cards=(CardRef(ref="acme/shop#12", repo="acme/shop"),), token="12")

POLICY = PreviewPolicy(env={"api": {"DATABASE_URL": "ACME_PV_DATABASE_URL"}, "*": ["SENTRY_DSN"]},
                       build_args={"web": ["NPM_TOKEN"]})


def _plan(doc, cfg, layout, policy=POLICY, **kw) -> PreviewPlan | Refused:
    return assemble(doc, cfg=cfg, unit=UNIT, layout=layout, policy=policy, domain=DOMAIN,
                    expires_at=1_900_000_000, **kw)


def _ok(result) -> PreviewPlan:
    assert isinstance(result, PreviewPlan), getattr(result, "reasons", result)
    return result


def _one(svc: dict, *, tree: Path, top: dict | None = None, **kw):
    """Admit a document of one service `api` whose paths live in `tree`."""
    doc = {"name": "app", "services": {"api": {"image": "busybox", **svc}}, **(top or {})}
    kw.setdefault("allow_names", {})
    return admit(doc, trees=[str(tree)], **kw)


@pytest.fixture
def tree(tmp_path) -> Path:
    root = Path(os.path.realpath(tmp_path)) / "base" / "app"
    (root / "api").mkdir(parents=True)
    (root / "api" / "Dockerfile").write_text("FROM busybox\n")
    (root / "data").mkdir()
    return root


# ── the models ───────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("model", [plan_models.CardRef, plan_models.Unit, plan_models.Tree,
                                   plan_models.Layout, plan_models.TreePath,
                                   plan_models.PreviewPlan, plan_models.PreviewUp,
                                   plan_models.RunningPreview, plan_models.Refused])
def test_every_model_of_a_preview_is_frozen_and_travels(model):
    """A plan crosses processes (worker → runtime row, possibly an add-on's on another machine),
    so every field is data the serialisability guard admits; and it is frozen, so no step after
    admission edits what was admitted."""
    assert model.model_config.get("frozen") is True
    bad = {n: f.annotation for n, f in model.model_fields.items() if not _serialisable(f.annotation)}
    assert not bad, bad


def test_a_frozen_plan_refuses_an_edit():
    ref = CardRef(ref="acme/shop#12", repo="acme/shop")
    with pytest.raises(ValidationError):
        ref.ref = "acme/shop#13"


def test_the_health_of_a_preview_is_never_called_readiness():
    """`readiness` is the `env check` action's marker (tests/test_the_action_layer.py): a front end
    that reads a preview must not borrow the word."""
    assert "readiness" not in plan_models.PreviewUp.model_fields
    assert "health" in plan_models.PreviewUp.model_fields


# ── the unit ─────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("body,kind,token", [
    ("## Objective\n\nx\n\n## Source\n\nExecutes **REQ-0012** in `acme/docs` — `r.md`.",
     "requirement", "req0012"),
    ("## Objective\n\nThis follows REQ-0012 loosely.\n", "card", "13"),
    ("", "card", "13"),
])
def test_a_card_is_previewed_as_the_requirement_its_source_cites(body, kind, token):
    """Only `## Source` makes a card part of a requirement — the reader the orphan repair uses,
    not a second regex; a number in the objective is prose."""
    unit = unit_of("acme", CardRef(ref="acme/api#13", repo="acme/api"), body)
    assert (unit.kind, unit.token) == (kind, token)
    assert preview.UNIT_RE.fullmatch(unit.token)


def test_a_card_with_no_number_is_no_unit():
    assert unit_of("acme", CardRef(ref="acme/api#draft", repo="acme/api"), "") is None


# ── the pre-scan ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text,said", [
    ("include:\n  - other.yml\nservices: {}\n", "includes other files (`include:`)"),
    ("services:\n  llm:\n    provider:\n      type: model\n", "is run by a provider"),
    ("services:\n  a:\n    extends:\n      file: /etc/compose.yml\n      service: b\n",
     "is absolute"),
    ("services:\n  a:\n    extends:\n      file: ~/compose.yml\n      service: b\n",
     "under a home directory"),
    ("services:\n  a:\n    extends:\n      file: ${HOME}/c.yml\n      service: b\n",
     "names a variable in a path"),
    ("services:\n  a:\n    extends:\n      file: ../../c.yml\n      service: b\n",
     "outside every repository"),
    ("services:\n  a:\n    extends:\n      service: b\n      file: ''\n", "extends a file it does not name"),
    ("services:\n  a:\n    build: /srv/app\n", "is absolute"),
    ("services:\n  a:\n    build:\n      context: .\n      dockerfile: /etc/Dockerfile\n",
     "builds with `/etc/Dockerfile`"),
    ("services:\n  a:\n    image: x\n    volumes:\n      - /var/run/docker.sock:/s\n",
     "mounts `/var/run/docker.sock`"),
    ("services:\n  a:\n    image: x\n    volumes:\n      - ~/.ssh:/root/.ssh\n",
     "under a home directory"),
    ("services:\n  a:\n    image: x\n    volumes:\n      - ${PWD}:/app\n", "names a variable"),
    ("services:\n  a:\n    image: x\n    volumes:\n      - type: bind\n        source: /etc\n"
     "        target: /e\n", "mounts `/etc`"),
    ("services:\n  a:\n    image: x\n    env_file: /etc/environment\n", "reads `/etc/environment`"),
    ("services:\n  a:\n    image: x\n    env_file:\n      - path: ~/.env\n", "reads `~/.env`"),
    ("services:\n  a:\n    build: ..\n", "outside every repository"),
    ("services:\n  a:\n    build: ../frontend\n", "`frontend` is not a repository of this preview"),
    ("services:\n  a:\n    image: !!python/object:os.system x\n", "could not be read"),
    ("services:\n  a:\n    image: !vault x\n", "could not be read"),
    ("- a list\n", "is not a compose file"),
])
def test_the_prescan_refuses_what_the_cli_would_act_on_first(text, said):
    found = prescan({"app/docker-compose.yml": text}, layout_dirs=["app"])
    assert any(said in r for r in found.refused), found.refused


def test_the_prescan_reads_the_compose_tags_records_siblings_profiles_and_extends():
    """`!reset`/`!override` remove or replace during the CLI's merge — they are read as what they
    carry; `../web` names the sibling the layout must check out; a profiled service is recorded."""
    text = ("services:\n"
            "  api:\n    build: ../api\n    ports: !reset []\n"
            "    environment: !override\n      A: b\n"
            "    extends:\n      file: common.yml\n      service: base\n"
            "  debug:\n    image: busybox\n    profiles: [debug]\n")
    found = prescan({"web/docker-compose.yml": text}, layout_dirs=["web", "api"])
    assert found.refused == ()
    assert found.dirs == ("api", "web")
    assert found.profiled == ("debug",)
    assert found.extends == ("web/common.yml",)


def test_relative_paths_in_every_file_resolve_against_the_first_files_directory():
    """Measured on the pinned plugin: an override under `.openfactory/` that says `context: ..`
    means the directory ABOVE the repository — so the pre-scan says so rather than agreeing."""
    found = prescan({"app/compose.yaml": "services: {}\n",
                     "app/.openfactory/preview.compose.yml":
                         "services:\n  api:\n    build:\n      context: ..\n"},
                    layout_dirs=["app"])
    assert any("outside every repository" in r for r in found.refused), found.refused
    ok = prescan({"app/compose.yaml": "services: {}\n",
                  "app/.openfactory/preview.compose.yml":
                      "services:\n  api:\n    build:\n      context: .\n"}, layout_dirs=["app"])
    assert ok.refused == ()


# ── canonicalise ─────────────────────────────────────────────────────────────────────────────────


class _Run:
    def __init__(self, stdout="{}", returncode=0, stderr=""):
        self.calls: list[tuple[list[str], dict]] = []
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


def test_canonicalise_runs_the_reference_cli_on_the_base_under_a_reduced_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-the-factorys-own")
    monkeypatch.setenv("COMPOSE_PROFILES", "debug")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOCKER_CONFIG", "/state/docker")
    run = _Run(stdout='{"name": "app", "services": {}}')
    doc = canonicalise("/w/base/app", ["compose.yaml", ".openfactory/preview.compose.yml"], run=run)
    assert doc == {"name": "app", "services": {}}
    (argv, kw), = run.calls
    assert argv == ["docker", "compose", "-f", "/w/base/app/compose.yaml",
                    "-f", "/w/base/app/.openfactory/preview.compose.yml",
                    "--project-directory", "/w/base/app", "--env-file", os.devnull,
                    "config", "--no-interpolate", "--format", "json"]
    assert "--no-env-resolution" not in argv  # the pinned plugin refuses it (measured)
    assert set(kw["env"]) <= {"PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG"}
    assert kw["env"]["DOCKER_CONFIG"] == "/state/docker"
    assert "sk-the-factorys-own" not in json.dumps(kw["env"])


@pytest.mark.parametrize("run,said", [
    (_Run(returncode=15, stderr="validating compose.yaml: services.api.gpus must be a list\n"),
     "the compose CLI refused `compose.yaml`: validating compose.yaml: services.api.gpus must be"),
    (_Run(stdout="not json"), "wrote something that is not JSON"),
    (_Run(stdout="[]"), "wrote no document"),
])
def test_a_cli_refusal_is_a_refusal_with_the_clis_sentence(run, said):
    result = canonicalise("/w/base/app", ["compose.yaml"], run=run)
    assert isinstance(result, Refused)
    assert said in result.reasons[0], result.reasons


# ── shape: the base, never the change ────────────────────────────────────────────────────────────


def test_the_shape_is_read_from_the_base_and_the_changes_compose_is_never_opened(tmp_path):
    """S10. The change's compose file — an agent's — adds a privileged service; the base's is
    what is read, pre-scanned and canonicalised."""
    wd = _workdir(tmp_path, "s10")
    Path(wd, "change", "app", "compose.yaml").write_text(
        "include:\n  - /etc/evil.yml\nservices: {}\n")  # would be refused if it were read
    base_doc = json.dumps(_canonical("s10", wd))
    run = _Run(stdout=base_doc)
    found = shape(_layout(wd, _diff("s10")), PreviewConfig(compose=["compose.yaml"],
                                                           expose={"api": 8000}),
                  tree="app", run=run)
    assert isinstance(found, Shape), getattr(found, "reasons", found)
    (argv, _), = run.calls
    assert argv[argv.index("-f") + 1] == f"{wd}/base/app/compose.yaml"
    assert found.files == ("app/compose.yaml",)


def test_a_compose_file_the_base_does_not_have_is_refused_by_name(tmp_path):
    wd = _workdir(tmp_path, "s10")
    found = shape(_layout(wd), PreviewConfig(compose=["docker-compose.yml"], expose={"api": 1}),
                  tree="app", run=_Run())
    assert isinstance(found, Refused)
    assert "`docker-compose.yml` is not a file of `acme/shop`'s base branch" in found.reasons[0]


def test_a_compose_file_that_is_a_link_out_of_the_checkout_is_not_read(tmp_path):
    wd = _workdir(tmp_path, "s10")
    outside = Path(os.path.realpath(tmp_path)) / "elsewhere.yml"
    outside.write_text("services: {}\n")
    link = Path(wd, "base", "app", "compose.yaml")
    link.unlink()
    link.symlink_to(outside)
    found = shape(_layout(wd), PreviewConfig(compose=["compose.yaml"], expose={"api": 1}),
                  tree="app", run=_Run())
    assert isinstance(found, Refused)


def test_an_extended_file_is_read_from_the_base_and_scanned_from_its_own_directory(tmp_path):
    wd = _workdir(tmp_path, "s10")
    Path(wd, "base", "app", "compose.yaml").write_text(
        "services:\n  api:\n    extends:\n      file: ops/common.yml\n      service: base\n")
    (Path(wd, "base", "app", "ops")).mkdir()
    Path(wd, "base", "app", "ops", "common.yml").write_text(
        "services:\n  base:\n    image: x\n    volumes:\n      - /var/run/docker.sock:/s\n")
    found = shape(_layout(wd), PreviewConfig(compose=["compose.yaml"], expose={"api": 1}),
                  tree="app", run=_Run())
    assert isinstance(found, Refused)
    assert any("mounts `/var/run/docker.sock`" in r for r in found.reasons), found.reasons


# ── admission: every key has one outcome ─────────────────────────────────────────────────────────


_PATH_OR_SHAPED = {"build", "volumes", "env_file", "environment", "depends_on", "tmpfs"}


@pytest.mark.parametrize("key", sorted(PASS_SERVICE - _PATH_OR_SHAPED))
def test_a_passed_key_reaches_the_runtime_verbatim(key, tree):
    result = _one({key: "value"}, tree=tree)
    assert result.refused == [], result.refused
    assert result.doc["services"]["api"][key] == "value"


@pytest.mark.parametrize("key", sorted(SET_SERVICE))
def test_a_client_value_of_a_key_the_preview_sets_is_dropped_and_said(key, tree):
    value = {"custom": None} if key == "networks" else "value"
    result = _one({key: value}, tree=tree)
    assert result.refused == []
    assert key not in result.doc["services"]["api"]
    assert any(f"`{key}:` of `api` is not used" in n for n in result.notes), result.notes


@pytest.mark.parametrize("key", sorted(DROP_SERVICE - {"profiles"}))
def test_a_dropped_key_is_dropped_and_said(key, tree):
    result = _one({key: "value"}, tree=tree)
    assert result.refused == []
    assert key not in result.doc["services"]["api"]
    assert any(f"`{key}:` of `api` is not used in a preview" in n for n in result.notes)


@pytest.mark.parametrize("key", sorted(REFUSE_SERVICE))
def test_a_refused_key_refuses_the_preview_by_name(key, tree):
    result = _one({key: True}, tree=tree)
    assert f"`api` asks for `{key}:`, which a preview never grants" in " ".join(result.refused)


@pytest.mark.parametrize("key", ["use_api_socket", "label_file", "models", "gpu"])
def test_a_key_in_no_set_is_refused_by_name(key, tree):
    result = _one({key: "x"}, tree=tree)
    assert f"`{key}` is not a key a preview reads (service `api`)." in result.refused


@pytest.mark.parametrize("key", sorted(REFUSE_BUILD))
def test_a_refused_build_key_refuses_by_name(key, tree):
    result = _one({"build": {"context": str(tree / "api"), key: "x"}}, tree=tree)
    assert f"`api` builds with `{key}:`" in " ".join(result.refused)


@pytest.mark.parametrize("key", sorted(DROP_BUILD))
def test_a_dropped_build_key_is_dropped_and_said(key, tree):
    result = _one({"build": {"context": str(tree / "api"), key: ["x"]}}, tree=tree)
    assert result.refused == []
    assert key not in result.doc["services"]["api"]["build"]
    assert any(f"`build.{key}:` of `api`" in n for n in result.notes)


def test_an_unknown_build_key_is_refused_by_name(tree):
    result = _one({"build": {"context": str(tree / "api"), "entitlements": ["x"]}}, tree=tree)
    assert "`build.entitlements` is not a key a preview reads (service `api`)." in result.refused


@pytest.mark.parametrize("key", sorted(REFUSE_TOP))
def test_a_refused_top_level_key_refuses_by_name(key, tree):
    result = _one({}, tree=tree, top={key: {"x": {}}})
    assert any(r.startswith(f"`{key}:` at the top of the compose file") for r in result.refused)


def test_top_level_keys_in_no_set_are_refused_and_extension_fields_are_said(tree):
    result = _one({}, tree=tree, top={"x-common": {"a": 1}, "volumes2": {}, "version": "3.8",
                                      "networks": {"default": {"name": "app_default"},
                                                   "front": {}}})
    assert "`volumes2` is not a key a preview reads." in result.refused
    assert set(result.doc) == {"services"}
    assert any("`x-common` (an extension field)" in n for n in result.notes)
    assert any("the file's own networks (`front`)" in n for n in result.notes)


def test_compose_bookkeeping_is_not_said():
    """The CLI writes `name`, a `default` network and `networks: {default: null}` into every
    document; a note about them on every card would bury the ones that matter."""
    result = admit({"name": "app", "networks": {"default": {"name": "app_default"}},
                    "services": {"api": {"image": "x", "networks": {"default": None}}}},
                   allow_names={}, trees=[])
    assert result.notes == [] and result.refused == []


@pytest.mark.parametrize("spec,said", [
    ({"name": "openfactory_openfactory_state"}, "volume `data` is named "
                                                "`openfactory_openfactory_state`"),
    ({"name": "openfactory-pv-acme-13_dbdata"}, "a preview's volumes are its own"),
    ({"external": True}, "volume `data` is external"),
    ({"driver": "local"}, "volume `data` sets `driver:`"),
    ({"driver_opts": {"device": "/"}}, "volume `data` sets `driver_opts:`"),
    ({"x-backup": True}, "volume `data` sets `x-backup:`"),
    ({"size": "1g"}, "`size` on volume `data` is not a key a preview reads."),
])
def test_a_top_level_volume_is_the_previews_own_or_refused(spec, said, tree):
    result = _one({}, tree=tree, top={"volumes": {"data": spec}})
    assert any(said in r for r in result.refused), result.refused


def test_compose_own_name_for_a_volume_is_not_a_client_name(tree):
    result = _one({}, tree=tree, top={"volumes": {"data": {"name": "app_data",
                                                            "labels": {"k": "v"}}}})
    assert result.refused == []
    assert result.doc["volumes"] == {"data": {"labels": {"k": "v"}}}


# ── admission: the rules beyond the sets ─────────────────────────────────────────────────────────


def test_environment_and_build_args_are_normalised_from_either_form(tree):
    result = _one({"environment": ["A=1", "B=x=y"],
                   "build": {"context": str(tree / "api"), "args": ["V=3", "W=4"]}}, tree=tree)
    svc = result.doc["services"]["api"]
    assert svc["environment"] == {"A": "1", "B": "x=y"}
    assert svc["build"]["args"] == {"V": "3", "W": "4"}


@pytest.mark.parametrize("text,allowed,expected,unlisted", [
    ("${X}", {}, "", ["X"]),
    ("$X/y", {}, "/y", ["X"]),
    ("${X:-dev}", {}, "dev", ["X"]),
    ("${X-dev}", {}, "dev", ["X"]),
    ("${X:+set}", {}, "", ["X"]),
    ("${X:-${Y:-z}}", {}, "z", ["Y", "X"]),
    ("$$HOME and $${X}", {}, "$$HOME and $${X}", []),
    ("${DB}", {"DB": "ACME_PV_DB"}, "${ACME_PV_DB}", []),
    ("${DB:-x}", {"DB": "ACME_PV_DB"}, "${ACME_PV_DB:-x}", []),
    ("$DB", {"DB": "ACME_PV_DB"}, "${ACME_PV_DB}", []),
    ("${HOME}/${ANTHROPIC_API_KEY}", {}, "/", ["HOME", "ANTHROPIC_API_KEY"]),
    ("price: $5", {}, "price: $5", []),
])
def test_interpolation_is_resolved_by_admission_not_by_the_process_environment(
        text, allowed, expected, unlisted):
    out, names, required = rewrite(text, allowed)
    assert (out, names, required) == (expected, unlisted, [])


def test_a_required_name_nobody_listed_refuses_with_the_remedy(tree):
    result = _one({"environment": {"S": "${APP_SECRET:?set it}"}}, tree=tree, project="acme")
    assert ("`api` requires `APP_SECRET` (`${APP_SECRET:?…}`), which the registry does not name "
            "for its previews — name it with `openfactory project set-preview acme --env "
            "api=APP_SECRET`, or give it a default in the compose file.") in result.refused


def test_a_required_name_the_registry_lists_is_kept_for_the_runtime(tree):
    result = _one({"environment": {"S": "${APP_SECRET:?set it}"}}, tree=tree,
                  allow_names={"api": {"APP_SECRET": "ACME_PV_APP_SECRET"}})
    assert result.refused == []
    assert result.doc["services"]["api"]["environment"]["S"] == "${ACME_PV_APP_SECRET:?set it}"


def test_an_unlisted_name_becomes_its_default_or_nothing_and_is_said(tree):
    result = _one({"environment": {"A": "${SENTRY_DSN}", "B": "${MODE:-dev}", "C": None,
                                   "D": None}, "image": "acme/api:${TAG:-latest}"},
                  tree=tree, allow_names={"*": {"D": "ACME_D"}}, project="acme")
    svc = result.doc["services"]["api"]
    assert svc["environment"] == {"A": "", "B": "dev", "D": "${ACME_D}"}
    assert svc["image"] == "acme/api:latest"
    note = next(n for n in result.notes if n.startswith("`api` reads"))
    for name in ("SENTRY_DSN", "MODE", "C", "TAG"):
        assert f"`{name}`" in note
    assert "`openfactory project set-preview acme --env api=NAME`" in note


def test_a_build_reads_only_the_names_listed_for_builds(tree):
    """A registry name for RUN time is not a name for the BUILD: an unmerged Dockerfile with
    internet access can read a build argument, and it lands in the image's history."""
    result = _one({"build": {"context": str(tree / "api"),
                             "args": {"DB": "${DATABASE_URL}", "TOKEN": None, "PUB": None}},
                   "environment": {"DB": "${DATABASE_URL}"}},
                  tree=tree, allow_names={"api": {"DATABASE_URL": "W_DB", "TOKEN": "W_TOKEN"}},
                  build_names={"api": {"PUB": "W_PUB"}})
    svc = result.doc["services"]["api"]
    assert svc["build"]["args"] == {"DB": "", "PUB": "${W_PUB}"}
    assert svc["environment"] == {"DB": "${W_DB}"}


@pytest.mark.parametrize("make,said", [
    (lambda t: {"volumes": [{"type": "bind", "source": "/etc", "target": "/e"}]},
     "`api` mounts `/etc`, which leads outside this preview's checkouts"),
    (lambda t: {"volumes": [{"type": "bind", "source": "relative/x", "target": "/e"}]},
     "`api` mounts `relative/x`, which is not a directory of this preview's checkouts"),
    (lambda t: {"volumes": [{"type": "bind", "source": str(t / "${X}"), "target": "/e"}]},
     "which names a variable — a preview's paths are its checkouts', never an environment's"),
    (lambda t: {"build": {"context": str(t / "api"), "dockerfile": "${DOCKERFILE:-Dockerfile}"}},
     "`api` builds with `${DOCKERFILE:-Dockerfile}`, which names a variable"),
    (lambda t: {"build": {"context": "https://github.com/acme/x.git"}},
     "`api` builds from `https://github.com/acme/x.git`, which is not a directory"),
    (lambda t: {"build": {"context": str(t / "api"), "dockerfile": "Dockerfile.missing"}},
     "`api` builds with `api/Dockerfile.missing`, which is not in the checkout"),
    (lambda t: {"env_file": [{"path": "/etc/environment", "required": True}]},
     "`api` reads `/etc/environment`, which leads outside"),
    (lambda t: {"volumes": [{"type": "volume", "source": "openfactory_state", "target": "/s"}]},
     "`api` mounts the volume `openfactory_state`, which the compose file does not declare"),
    (lambda t: {"volumes": [{"type": "npipe", "source": "x", "target": "/s"}]},
     "`api` asks for a `npipe` mount"),
    (lambda t: {"volumes": [{"type": "image", "source": "x", "target": "/s"}]},
     "`api` asks for a `image` mount"),
    (lambda t: {"volumes": [{"type": "bind", "source": str(t / "data"), "target": "/d",
                             "bind": {"propagation": "rshared"}}]},
     "with `bind.propagation:`"),
    (lambda t: {"volumes": [{"type": "volume", "source": "db", "target": "/d",
                             "volume": {"labels": {"a": "b"}}}]},
     "with `volume.labels:`"),
    (lambda t: {"volumes": [{"type": "tmpfs", "target": "/t", "tmpfs": {"uid": 0}}]},
     "with `tmpfs.uid:`"),
    (lambda t: {"volumes": [{"type": "bind", "source": str(t / "data"), "target": "/d",
                             "cap": 1}]},
     "`api` mounts with `cap:`"),
    (lambda t: {"volumes": ["./data:/d"]}, "not in the form the compose CLI writes"),
])
def test_every_path_and_mount_refusal_is_a_sentence(make, said, tree):
    result = _one(make(tree), tree=tree, top={"volumes": {"db": {}}})
    assert any(said in r for r in result.refused), result.refused


def test_a_link_out_of_the_checkout_is_refused_whatever_its_name_says(tree):
    """A git-tracked `data -> /var/run/docker.sock` in a mounted directory: the string is inside
    the tree, the file is not. Judged by `realpath`, on disk."""
    (tree / "sock").symlink_to("/var/run")
    (tree / "api" / "outside").symlink_to("/etc")
    for svc in ({"volumes": [{"type": "bind", "source": str(tree / "sock"), "target": "/s"}]},
                {"build": {"context": str(tree / "api" / "outside")}},
                {"env_file": [{"path": str(tree / "api" / "outside" / "hosts")}]}):
        result = _one(svc, tree=tree)
        assert any("leads outside this preview's checkouts once its links are followed" in r
                   for r in result.refused), (svc, result.refused)


def test_a_bind_mount_inside_the_checkout_passes_without_create_host_path(tree):
    result = _one({"volumes": [{"type": "bind", "source": str(tree / "data"), "target": "/d",
                                "bind": {"create_host_path": True}}]}, tree=tree)
    assert result.refused == []
    assert result.doc["services"]["api"]["volumes"] == [
        {"type": "bind", "source": str(tree / "data"), "target": "/d"}]


def test_a_bind_source_the_repository_does_not_have_is_not_mounted_and_said(tree):
    result = _one({"volumes": [{"type": "bind", "source": str(tree / "pgdata"), "target": "/d",
                                "bind": {"create_host_path": True}}]}, tree=tree)
    assert result.refused == []
    assert result.doc["services"]["api"]["volumes"] == []
    assert any("`api` mounts `pgdata`, which is not in the repository — not mounted" in n
               for n in result.notes)


def test_an_env_file_the_repository_does_not_have_is_optional_and_said(tree):
    (tree / ".env.shared").write_text("A=1\n")
    result = _one({"env_file": [{"path": str(tree / ".env"), "required": True},
                                {"path": str(tree / ".env.shared"), "required": True}]},
                  tree=tree)
    assert result.refused == []
    assert result.doc["services"]["api"]["env_file"] == [
        {"path": str(tree / ".env"), "required": False},
        {"path": str(tree / ".env.shared"), "required": True}]
    assert ("`api` reads `.env`, which is not in the repository; its names come only from the "
            "registry's `preview.env`.") in result.notes


def test_every_tmpfs_gets_a_size(tree):
    result = _one({"tmpfs": ["/run", "/cache:mode=1777", "/big:size=1g"],
                   "volumes": [{"type": "tmpfs", "target": "/t"}]}, tree=tree,
                  tmpfs_size="64m")
    svc = result.doc["services"]["api"]
    assert svc["tmpfs"] == ["/run:size=64m", "/cache:mode=1777,size=64m", "/big:size=1g"]
    assert svc["volumes"] == [{"type": "tmpfs", "target": "/t", "tmpfs": {"size": "64m"}}]


def test_an_anonymous_volume_and_a_declared_one_pass(tree):
    result = _one({"volumes": [{"type": "volume", "target": "/app/node_modules", "volume": {}},
                               {"type": "volume", "source": "db", "target": "/d",
                                "volume": {"nocopy": True, "subpath": "x"}}]},
                  tree=tree, top={"volumes": {"db": {}}})
    assert result.refused == []


def test_a_profiled_service_is_skipped_and_said_and_a_dependency_on_it_refused(tree):
    doc = {"name": "app", "services": {
        "api": {"image": "x", "depends_on": {"debug": {"condition": "service_started"}}},
        "debug": {"image": "busybox", "profiles": ["debug"]}}}
    result = admit(doc, allow_names={}, trees=[str(tree)])
    assert "debug" not in result.doc["services"]
    assert "`debug` runs only under a profile (`debug`); a preview runs none." in result.notes
    assert any("`api` depends on `debug`, which runs only under a profile" in r
               for r in result.refused)


def test_a_dependency_on_an_excluded_service_is_refused_with_both_names(tree):
    doc = {"name": "app", "services": {
        "api": {"image": "x", "depends_on": {"worker": {"condition": "service_started",
                                                        "required": True}}},
        "worker": {"image": "x"}}}
    result = admit(doc, allow_names={}, trees=[str(tree)], exclude=["worker"])
    assert ("`api` depends on `worker`, which `preview.exclude` leaves out — run both, or "
            "neither.") in result.refused
    ok = admit({**doc, "services": {**doc["services"], "api": {"image": "x"}}},
               allow_names={}, trees=[str(tree)], exclude=["worker"])
    assert ok.refused == [] and set(ok.doc["services"]) == {"api"}


# ── inputs, from the change, the shape ───────────────────────────────────────────────────────────


def test_a_service_is_made_of_its_build_context_its_binds_and_an_outside_dockerfile(tmp_path):
    wd = str(tmp_path)
    layout = _layout(wd, ("docker/api.Dockerfile",))
    svc = {"build": {"context": f"{wd}/base/app/api", "dockerfile": "../docker/api.Dockerfile"},
           "volumes": [{"type": "bind", "source": f"{wd}/base/app/shared", "target": "/s"},
                       {"type": "volume", "source": "db", "target": "/d"},
                       {"type": "bind", "source": "/etc", "target": "/e"}]}
    assert inputs(svc, layout) == (TreePath(tree="app", side="base", rel="api"),
                                   TreePath(tree="app", side="base", rel="docker/api.Dockerfile"),
                                   TreePath(tree="app", side="base", rel="shared"))
    assert is_from_change(svc, layout)
    assert inputs({"image": "x"}, layout) == ()


@pytest.mark.parametrize("diff,changed", [
    (("api/views.py",), True),
    (("api",), True),
    (("apiary/views.py",), False),
    (("web/index.js",), False),
    ((), False),
])
def test_from_the_change_is_a_prefix_of_the_changes_own_diff(tmp_path, diff, changed):
    wd = str(tmp_path)
    svc = {"build": {"context": f"{wd}/base/app/api", "dockerfile": "Dockerfile"}}
    assert is_from_change(svc, _layout(wd, diff)) is changed
    assert is_from_change(svc, _layout(wd, diff, change=False)) is False


@pytest.mark.parametrize("diff,changed", [
    (("docker-compose.yml",), True),
    ((".openfactory/preview.compose.yml",), True),
    ((".openfactory/preview/api.Dockerfile",), True),
    ((".openfactory/project.yaml",), True),
    ((".openfactory/product.yaml",), True),
    (("compose.yaml",), False),     # not the file this project's block names
    (("api/Dockerfile",), False),   # a build input, not the shape
])
def test_the_topology_is_changed_by_the_shape_files_only(diff, changed):
    cfg = PreviewConfig(compose=["docker-compose.yml"], expose={"api": 8000})
    assert topology_changed(diff, cfg, ".openfactory/project.yaml") is changed


# ── the scenarios, through prescan → the recorded canonical form → admit → assemble ─────────────


S1_CFG = PreviewConfig(compose=["docker-compose.yml"], expose={"web": 3000, "api": 8000},
                       data={"api": "python manage.py loaddata demo"})


@pytest.mark.parametrize("scenario,files", [
    ("s1", ["docker-compose.yml"]),
    ("s2", ["compose.yaml"]),
    ("s2", ["compose.yaml", ".openfactory/preview.compose.yml"]),
    ("s9", ["docker-compose.yml"]),
    ("s10", ["compose.yaml"]),
])
def test_every_fixture_passes_the_prescan(scenario, files):
    texts = {f"app/{f}": (FIXTURES / scenario / "tree" / f).read_text() for f in files}
    found = prescan(texts, layout_dirs=["app"])
    assert (found.refused, found.profiled) == ((), ()) and set(found.dirs) <= {"app"}


@pytest.fixture
def s1(tmp_path, monkeypatch):
    monkeypatch.setenv("ACME_PV_DATABASE_URL", "postgres://admin:hunter2@db.prod:5432/shop")
    wd = _workdir(tmp_path, "s1")
    return wd, _ok(_plan(_canonical("s1", wd), S1_CFG, _layout(wd, _diff("s1"))))


def test_s1_the_services_the_change_touched_run_from_the_change_and_the_rest_from_base(s1):
    wd, plan = s1
    assert plan.from_change == {"web": False, "api": True, "migrate": True, "db": False}
    svc = plan.doc["services"]
    assert svc["api"]["build"]["context"] == f"{wd}/change/app/api"
    assert svc["api"]["volumes"][0]["source"] == f"{wd}/change/app/api"
    assert svc["migrate"]["build"]["context"] == f"{wd}/change/app/api"
    assert svc["web"]["build"]["context"] == f"{wd}/base/app/web"
    assert svc["web"]["volumes"][0]["source"] == f"{wd}/base/app/web/src"
    assert TreePath(tree="app", side="change", rel="api") in plan.paths["api"]
    assert TreePath(tree="app", side="base", rel="web/src") in plan.paths["web"]
    assert plan.commits == {"acme/shop": CHANGE_SHA}
    assert plan.pr_urls == ("https://forge.example/acme/shop/pull/12",)


def test_s1_what_a_laptop_needs_is_dropped_and_said(s1):
    _, plan = s1
    for name, svc in plan.doc["services"].items():
        assert "extra_hosts" not in svc and "ports" not in svc, name
        assert svc["restart"] == "no"
    notes = " ".join(plan.notes)
    assert "`ports:` of `api`, `db`, `web` is not used in a preview" in notes
    assert "`extra_hosts:` of `api` is not used in a preview" in notes
    assert "`restart:` of `api`, `web` is not used" in notes
    assert "`labels:` of `web` is not used" in notes
    assert ("`api` reads `.env`, which is not in the repository; its names come only from the "
            "registry's `preview.env`.") in plan.notes
    assert plan.doc["services"]["api"]["env_file"] == [
        {"path": f"{plan.workdir}/change/app/.env", "required": False}]


def test_s1_names_reach_a_container_never_a_value(s1):
    _, plan = s1
    api = plan.doc["services"]["api"]["environment"]
    assert api["DATABASE_URL"] == "${ACME_PV_DATABASE_URL}"   # the registry's, not the literal
    assert api["SENTRY_DSN"] == "${SENTRY_DSN}"                # "*" names it for every service
    assert api["SECRET_KEY"] == "dev-only"                     # unlisted: its default, said
    assert plan.env_names["api"] == {"SENTRY_DSN": "SENTRY_DSN",
                                     "DATABASE_URL": "ACME_PV_DATABASE_URL"}
    assert any(n.startswith("`api` reads `SECRET_KEY`") for n in plan.notes)
    assert "hunter2" not in json.dumps(plan.model_dump())
    web = plan.doc["services"]["web"]["environment"]
    assert web["NEXT_PUBLIC_API_URL"] == "${OPENFACTORY_PREVIEW_URL_API:-http://localhost:8000}"
    assert web["OPENFACTORY_PREVIEW_URL_API"] == "${OPENFACTORY_PREVIEW_URL_API}"
    assert web["OPENFACTORY_PREVIEW_INTERNAL_URL_API"] == "${OPENFACTORY_PREVIEW_INTERNAL_URL_API}"
    assert "DATABASE_URL" not in web


def test_s1_a_build_receives_only_the_names_listed_for_builds(s1):
    _, plan = s1
    svc = plan.doc["services"]
    urls = {"OPENFACTORY_PREVIEW_URL_WEB": "${OPENFACTORY_PREVIEW_URL_WEB}",
            "OPENFACTORY_PREVIEW_URL_API": "${OPENFACTORY_PREVIEW_URL_API}"}
    assert svc["api"]["build"]["args"] == {"PYTHON_VERSION": "3.12", **urls}
    assert svc["web"]["build"]["args"] == {**urls, "NPM_TOKEN": "${NPM_TOKEN}"}
    assert plan.build_arg_names == {"web": {"NPM_TOKEN": "NPM_TOKEN"}, "api": {}, "migrate": {}}


def test_s1_the_platforms_labels_only_the_networks_and_the_containment(s1):
    _, plan = s1
    compose_project = preview.compose_project("acme", "12")
    assert plan.compose_project == compose_project
    for name, svc in plan.doc["services"].items():
        assert set(svc["labels"]) == set(preview.LABELS), name
        assert svc["labels"][preview.LABEL_UNIT] == "12"
        assert svc["labels"][preview.LABEL_EXPOSED] == ("1" if name in ("web", "api") else "")
        assert svc["cap_drop"] == ["ALL"]
        assert svc["security_opt"] == ["no-new-privileges:true"]
        assert svc["cap_add"] == PreviewPolicy().caps
        assert (svc["cpus"], svc["mem_limit"], svc["pids_limit"]) == ("2", "2g", 512)
    assert plan.doc["services"]["api"]["networks"] == {
        "default": {}, "edge": {"aliases": [preview.host_label("acme", "12", "api")]}}
    assert plan.doc["services"]["db"]["networks"] == {"default": {}}
    assert plan.doc["networks"] == {
        "default": {"internal": True},
        "edge": {"name": preview.edge_network("acme", "12"), "external": True}}
    assert plan.doc["volumes"] == {"pgdata": {"name": f"{compose_project}_pgdata"}}
    db_tmpfs = plan.doc["services"]["db"]["volumes"][1]
    assert db_tmpfs == {"target": "/run/postgresql", "type": "tmpfs", "tmpfs": {"size": "256m"}}


def test_s1_what_is_built_and_pulled(s1):
    _, plan = s1
    svc = plan.doc["services"]
    assert {n: s["pull_policy"] for n, s in svc.items()} == {
        "web": "build", "api": "build", "migrate": "build", "db": "always"}
    assert svc["db"]["image"] == "postgres:16"
    assert plan.urls == {"web": f"https://{preview.host_label('acme', '12', 'web')}.{DOMAIN}/",
                         "api": f"https://{preview.host_label('acme', '12', 'api')}.{DOMAIN}/"}
    assert plan.internal_urls == {"web": "http://web:3000", "api": "http://api:8000"}
    assert plan.data == (("api", "python manage.py loaddata demo"),)
    assert plan.edge_network == preview.edge_network("acme", "12")


def test_an_unchanged_service_that_names_an_image_is_pulled_not_built(tmp_path):
    """Base is what the client's CI publishes TODAY: a service the change did not touch runs its
    image, pulled every time, even when the file can also build it."""
    wd = _workdir(tmp_path, "s1")
    doc = _canonical("s1", wd)
    doc["services"]["web"]["image"] = "ghcr.io/acme/web:latest"
    plan = _ok(_plan(doc, S1_CFG, _layout(wd, _diff("s1"))))
    web = plan.doc["services"]["web"]
    assert "build" not in web
    assert (web["image"], web["pull_policy"]) == ("ghcr.io/acme/web:latest", "always")
    assert plan.build_arg_names == {"api": {}, "migrate": {}}


def test_s2_an_image_only_file_is_refused_because_the_change_is_in_no_service(tmp_path):
    wd = _workdir(tmp_path, "s2")
    cfg = PreviewConfig(compose=["compose.yaml"], expose={"web": 3000, "api": 8000})
    result = _plan(_canonical("s2", wd), cfg, _layout(wd, _diff("s2")))
    assert isinstance(result, Refused)
    reason, = result.reasons
    assert reason.startswith("the change is in no service's inputs: it touches `app/main.py`")
    assert "`api` runs the image `ghcr.io/acme/api:latest`" in reason
    assert "Add a `build:` for the service this repository builds" in reason


def test_s2_with_the_override_api_is_built_from_the_change_without_the_clients_tag(tmp_path):
    wd = _workdir(tmp_path, "s2")
    cfg = PreviewConfig(compose=["compose.yaml", ".openfactory/preview.compose.yml"],
                        expose={"web": 3000, "api": 8000})
    plan = _ok(_plan(_canonical("s2", wd, "canonical.override.json"), cfg,
                     _layout(wd, _diff("s2"))))
    svc = plan.doc["services"]
    assert plan.from_change == {"web": False, "api": True, "db": False}
    assert "image" not in svc["api"]
    assert svc["api"]["build"]["context"] == f"{wd}/change/app"
    assert (svc["web"]["image"], svc["web"]["pull_policy"]) == ("ghcr.io/acme/web:latest",
                                                               "always")
    assert "build" not in svc["web"] and svc["db"]["pull_policy"] == "always"


def test_s9_a_host_outside_the_preview_is_said_on_the_card(tmp_path):
    wd = _workdir(tmp_path, "s9")
    cfg = PreviewConfig(compose=["docker-compose.yml"], expose={"api": 8000})
    plan = _ok(_plan(_canonical("s9", wd), cfg, _layout(wd, _diff("s9")),
                     policy=PreviewPolicy()))
    notes = " ".join(plan.notes)
    assert ("`api` is configured to reach `db.prod.example.com` and "
            "`search.internal.example.com`, which a preview cannot") in notes
    assert "`localhost`" not in notes and "reach `web`" not in notes
    assert "set-preview acme --env api=NAME=WORKER_NAME --network <network>" in notes
    assert plan.doc["services"]["api"]["environment"]["DATABASE_URL"] == \
        "postgres://app:@db.prod.example.com:5432/app"          # `${DB_PASSWORD}` named by nobody
    assert any(n.startswith("`api` reads `DB_PASSWORD`") for n in plan.notes)
    egress = _ok(_plan(_canonical("s9", wd), cfg, _layout(wd, _diff("s9")),
                       policy=PreviewPolicy(network="acme-egress")))
    assert any("only through the operator's network `acme-egress`" in n for n in egress.notes)
    assert egress.doc["networks"]["egress"] == {"name": "acme-egress", "external": True}
    assert egress.doc["services"]["web"]["networks"]["egress"] == {}


def test_s10_the_base_topology_runs_with_the_touched_service_built_from_the_change(tmp_path):
    wd = _workdir(tmp_path, "s10")
    cfg = PreviewConfig(compose=["compose.yaml"], expose={"web": 80, "api": 8000})
    layout = _layout(wd, _diff("s10"))

    def run(argv, **kw):
        files = [argv[i + 1] for i, a in enumerate(argv) if a == "-f"]
        # the base's recorded form for the base's file; anything else would be the change's
        doc = _canonical("s10", wd) if files == [f"{wd}/base/app/compose.yaml"] else {
            "name": "app", "services": {"worker": {"image": "x", "privileged": True}}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(doc), "")

    found = shape(layout, cfg, tree="app", run=run)
    assert isinstance(found, Shape), getattr(found, "reasons", found)
    plan = _ok(_plan(found.doc, cfg, layout))
    svc = plan.doc["services"]
    assert set(svc) == {"web", "api", "db"}                       # `worker` exists on no side
    assert plan.from_change == {"web": False, "api": True, "db": False}
    assert "image" not in svc["api"]                               # never ghcr.io/acme/api:latest
    assert svc["api"]["build"]["context"] == f"{wd}/change/app/api"
    assert "3.13" in Path(svc["api"]["build"]["context"], "Dockerfile").read_text()
    assert (svc["web"]["pull_policy"], svc["db"]["pull_policy"]) == ("always", "always")
    assert topology_changed(layout.trees["app"].diff_paths, cfg)
    assert ("this change edits `compose.yaml`; the preview runs the base branch's version, never "
            "the change's — merge, and the next preview runs the new shape.") in plan.notes


# ── what the plan refuses on its own ─────────────────────────────────────────────────────────────


def test_a_unit_with_no_open_pull_request_is_refused_unless_proving_the_base(tmp_path):
    wd = _workdir(tmp_path, "s1", change=False)
    layout = _layout(wd, change=False)
    result = _plan(_canonical("s1", wd), S1_CFG, layout)
    assert isinstance(result, Refused)
    assert ("this unit has no open pull request — a preview shows a change, and there is none "
            "to show yet.") in result.reasons
    proved = _ok(_plan(_canonical("s1", wd), S1_CFG, layout, prove=True))
    assert not any(proved.from_change.values())


def test_the_block_must_name_services_the_preview_runs(tmp_path):
    wd = _workdir(tmp_path, "s1")
    cfg = PreviewConfig(compose=["docker-compose.yml"], expose={"webb": 3000, "api": 8000},
                        data={"migrate": "true"}, exclude=["db", "ghost"])
    result = _plan(_canonical("s1", wd), cfg, _layout(wd, _diff("s1")))
    assert isinstance(result, Refused)
    assert any(r.startswith("`preview.expose` names `webb`, which the compose file does not "
                            "declare") for r in result.reasons), result.reasons
    assert ("`api` depends on `db`, which `preview.exclude` leaves out — run both, or "
            "neither.") in result.reasons
    assert "`preview.exclude` names `ghost`, which the compose file does not declare." in \
        result.notes


@pytest.mark.parametrize("policy,said", [
    (PreviewPolicy(max_services=3), "this preview would run 4 services, more than the 3"),
    (PreviewPolicy(memory="3g", memory_total="8g"),
     "this preview would reserve 4 × 3g of memory, more than the 8g"),
])
def test_the_budget_is_the_operators(tmp_path, policy, said):
    wd = _workdir(tmp_path, "s1")
    result = _plan(_canonical("s1", wd), S1_CFG, _layout(wd, _diff("s1")), policy=policy)
    assert isinstance(result, Refused)
    assert any(r.startswith(said) for r in result.reasons), result.reasons


def test_loopback_reach_publishes_exposed_services_on_127_0_0_1_only(tmp_path):
    wd = _workdir(tmp_path, "s1")
    plan = _ok(_plan(_canonical("s1", wd), S1_CFG, _layout(wd, _diff("s1")), reach="loopback",
                     loopback_range=(42000, 42999)))
    assert set(plan.loopback_ports) == {"web", "api"}
    for name, port in plan.loopback_ports.items():
        assert 42000 <= port <= 42999
        assert plan.doc["services"][name]["ports"] == [
            {"target": S1_CFG.expose[name], "published": str(port), "host_ip": "127.0.0.1",
             "protocol": "tcp"}]
    assert "ports" not in plan.doc["services"]["db"]
