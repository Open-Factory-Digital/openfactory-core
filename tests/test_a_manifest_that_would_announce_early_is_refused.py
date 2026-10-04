"""A manifest whose stages nothing would observe is refused when it loads, and a pending deploy
is not a reached stage (#501) — nor is one nothing read (#518).

THREE SHAPES ANNOUNCED A DELIVERY BEFORE THE STAGE THEY DECLARE WAS OBSERVED, and two of them are
closed here (the third — `--promote` on a deploy-only manifest — is the workflow's, and lives with
the deploy watch):

  (a) ENVIRONMENTS THE DERIVED CHAIN DOES NOT WALK. With no `promote:`, `promotion_chain()` knows
      two names — `staging` observed, `prod` gated — so a manifest declaring only `qa` gave the
      tail an empty chain: DONE right after the merge, and the delivery announced then. REFUSED
      when the manifest loads, naming the two fixes.

  (b) A STAGE WITH NOTHING TO OBSERVE. `_verify` answered "reached" for an environment with no
      `deploy_ref` and no `health_url`, so the stage counted as reached the moment the walk
      arrived. REFUSED when the manifest loads — for a stage the chain WALKS, production
      included. An environment the chain does not walk is the other case and stays the
      unwatched-environment WARNING it always was: nothing is announced on its behalf.

  …AND A PENDING DEPLOY. Only `failure` stopped the walk, so a deploy still running — what a
      deploy is right after its merge — passed as green. It is waited for now, like the deploy
      watch waits for its run, inside one window for the whole walk; still pending when the
      window closes, the stage is held as NOT REACHED, and said so in words that are not "red".

  …AND WHAT NOTHING READ (#518). A stage counts as reached ONLY on an observation: a deploy of
      this ref that finished green, or a `health_url` that answered healthy. `unknown` (nothing
      recorded for this ref there) and `none` (what the `ci: none` observer answers for every
      ref) go to `health_url` when there is one and are NOT REACHED when there is not — held, in
      a sentence of their own. On a project whose CI reads no deploy, a chain stage with no
      `health_url` is refused when the manifest loads: its `deploy_ref` is read by nobody.
"""

from __future__ import annotations

import logging
import pathlib
import re

import pytest
import yaml
from pydantic import ValidationError

from openfactory import namespace
from openfactory.contracts import Environment, JobState, Manifest
from openfactory.loader import load_manifest
from openfactory.orchestrator.promotion import PromotionRunner

ROOT = pathlib.Path(__file__).resolve().parents[1]
FLOOR = {"version": 1, "base_branch": "main", "validate": {"test": "pytest -q", "security": "true"}}


class _Project:
    name = "acme"
    manifest_path = namespace.MANIFEST


def _write(tmp_path: pathlib.Path, **keys) -> pathlib.Path:
    (tmp_path / namespace.DIR).mkdir(parents=True, exist_ok=True)
    (tmp_path / namespace.MANIFEST).write_text(yaml.safe_dump({**FLOOR, **keys}))
    return tmp_path


# ── (a) a derived chain that walks nothing ──────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["qa", "homologacao", "dev"])
def test_environments_the_derived_chain_does_not_walk_are_REFUSED_naming_the_reason_and_the_fix(
        name):
    with pytest.raises(ValidationError) as caught:
        Manifest.model_validate({**FLOOR, "environments": {name: {"deploy_ref": name}}})

    said = str(caught.value)
    assert name in said, "the refusal does not name the environment it is about"
    assert "announced at the merge" in said, "the refusal does not say WHY"
    assert "Declare promote:" in said and "staging/prod" in said, (
        f"the refusal does not name the two fixes: {said}")


def test_the_refusal_reaches_the_operator_through_the_loader_with_the_file_named(tmp_path):
    repo = _write(tmp_path, environments={"qa": {"deploy_ref": "qa"}})

    with pytest.raises(ValueError, match=r"(?s)project\.yaml.*announced at the merge"):
        load_manifest(_Project(), repo_root=repo)


@pytest.mark.parametrize("keys", [
    pytest.param({"environments": {"qa": {"deploy_ref": "qa"}}, "promote": ["qa"]},
                 id="the-same-qa-named-in-promote"),
    pytest.param({"environments": {"staging": {"deploy_ref": "staging"}}}, id="staging-alone"),
    pytest.param({"environments": {"prod": {"deploy_ref": "prod"}}}, id="prod-alone"),
    pytest.param({"environments": {"qa": {"url": "https://qa"},
                                   "prod": {"health_url": "https://p/h"}}},
                 id="qa-beside-a-gated-prod"),
    pytest.param({}, id="no-environments-at-all"),
])
def test_a_chain_that_walks_something_still_loads(keys, tmp_path):
    m = load_manifest(_Project(), repo_root=_write(tmp_path, **keys))
    stages, production = m.promotion_chain()
    assert stages or production or not m.environments


# ── (b) a stage with nothing to observe ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("keys,blind", [
    pytest.param({"environments": {"staging": {"url": "https://stg"}}}, "staging",
                 id="a-derived-staging-with-only-an-address"),
    pytest.param({"environments": {"staging": {"health_url": "https://s/h"}, "prod": {}}}, "prod",
                 id="a-derived-production-with-nothing"),
    pytest.param({"environments": {"dev": {"deploy_ref": "dev"}, "qa": {"url": "https://qa"},
                                   "prod": {"deploy_ref": "prod"}},
                  "promote": ["dev", "qa", "prod"]}, "qa",
                 id="a-declared-middle-stage"),
    pytest.param({"environments": {"dev": {"deploy_ref": "dev"}, "producao": {}},
                  "promote": ["dev", "producao"]}, "producao",
                 id="a-declared-production"),
])
def test_a_stage_of_the_chain_with_neither_deploy_ref_nor_health_url_is_REFUSED(keys, blind):
    with pytest.raises(ValidationError) as caught:
        Manifest.model_validate({**FLOOR, **keys})

    said = str(caught.value)
    assert f"'{blind}'" in said, f"the refusal does not name the stage: {said}"
    assert "neither deploy_ref nor health_url" in said and "announced" in said, said
    assert "Declare deploy_ref" in said and "health_url" in said, "the fix is not named"


@pytest.mark.parametrize("probe", [{"deploy_ref": "staging"}, {"health_url": "https://s/h"}],
                         ids=["deploy_ref-alone", "health_url-alone"])
def test_either_probe_alone_is_enough(probe):
    m = Manifest.model_validate({**FLOOR, "environments": {"staging": probe}})
    assert m.promotion_chain() == (["staging"], None)


def test_an_environment_the_chain_does_NOT_walk_is_still_only_WARNED_about(tmp_path, caplog):
    """The distinction this keeps (the inert-environment case, #109): nothing is announced on
    behalf of an environment the chain does not walk, so an address-only spare loads — and the
    log names it as unwatched, exactly as before."""
    repo = _write(tmp_path, environments={"staging": {"health_url": "https://s/h"},
                                          "prod": {"deploy_ref": "prod"},
                                          "sandbox": {"url": "https://sandbox"}})

    with caplog.at_level(logging.WARNING, logger="openfactory.loader"):
        m = load_manifest(_Project(), repo_root=repo)

    assert m.environments["sandbox"].url == "https://sandbox"
    assert "OPENFACTORY_MANIFEST_INERT" in caplog.text and "`sandbox`" in caplog.text, caplog.text


# ── the examples a reader copies still load, and say the rule ───────────────────────────────────

def _commented_environments(text: str) -> dict:
    """The `# environments:` … `# promote:` block of `project.yaml.example`, uncommented."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("# environments:"))
    block = []
    for line in lines[start:]:
        block.append(line[2:])
        if line.startswith("# promote:"):
            break
    return yaml.safe_load("\n".join(block))


def _markdown_environment_blocks() -> list[tuple[str, dict]]:
    found = []
    for path in sorted((ROOT / "docs").rglob("*.md")):
        if "adr" in path.parts:
            continue
        for chunk in re.findall(r"^```yaml\n(.*?)^```", path.read_text(), re.M | re.S):
            try:
                data = yaml.safe_load(chunk)
            except yaml.YAMLError:
                continue
            if isinstance(data, dict) and data.get("environments"):
                found.append((str(path.relative_to(ROOT)),
                              {k: data[k] for k in ("environments", "promote") if k in data}))
    return found


def test_every_environments_example_in_the_docs_loads():
    example = _commented_environments((ROOT / "docs" / "project.yaml.example").read_text())
    blocks = [("docs/project.yaml.example", example), *_markdown_environment_blocks()]
    assert len(blocks) >= 2, f"the walk found too few examples to mean anything: {blocks}"
    for where, keys in blocks:
        try:
            Manifest.model_validate({**FLOOR, **keys})
        except ValidationError as exc:  # pragma: no cover — the failure message is the point
            pytest.fail(f"{where} teaches a manifest this build refuses: {exc}")


def test_no_document_still_promises_that_a_stage_passes_through_unchecked():
    for rel in ("docs/project.yaml.example", "docs/ONBOARDING.md", "docs/autonomous-flow.md"):
        flat = " ".join((ROOT / rel).read_text().replace("#", " ").split())
        assert "passed through unchecked" not in flat and "passes through unchecked" not in flat, (
            f"{rel} still teaches the shape #501 refuses")
        assert "#501" in (ROOT / rel).read_text(), f"{rel} does not say the new rule"


# ── a pending deploy is not a reached stage ─────────────────────────────────────────────────────

class _Tracker:
    def __init__(self):
        self.states, self.comments, self.reasons = [], [], []

    def set_state(self, ref, state, reason=None, *, needs_person=None):
        self.states.append(state)
        self.reasons.append(reason)

    def comment(self, ref, body):
        self.comments.append(body)


class _Forge:
    def create_tag(self, *, tag, ref):
        pass


class _Notifier:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def notify(self, *, message, level="info"):
        self.sent.append((level, message))


class _Deploys:
    """Each deploy_ref answers from its own script; the last answer repeats for ever. Every
    health_url answers healthy unless it is in `sick`, and every probe is recorded."""

    def __init__(self, *, sick: frozenset[str] = frozenset(), **scripts: list[str]):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.reads: list[str] = []
        self.sick, self.probed = sick, []

    def deploy_status(self, *, env, ref):
        self.reads.append(env)
        script = self.scripts[env]
        return script.pop(0) if len(script) > 1 else script[0]

    def health(self, *, url, timeout=10):
        self.probed.append(url)
        return url not in self.sick


class _Clock:
    """Time that moves only when the runner sleeps."""

    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _runner(deploys, environments, promote, *, window=600, poll=60):
    clock = _Clock()
    runner = PromotionRunner(
        tracker=_Tracker(), forge=_Forge(), observer=deploys, notifier=_Notifier(),
        manifest=Manifest(environments=environments, promote=promote, prod_approvers=["alice"]),
        reach_window=window, reach_poll=poll, sleep=clock.sleep, clock=clock)
    return runner, clock


_CHAIN = {"staging": Environment(deploy_ref="staging"), "prod": Environment(deploy_ref="prod")}


def test_a_deploy_still_pending_when_the_window_closes_is_NOT_REACHED_and_held():
    deploys = _Deploys(staging=["pending"], prod=["success"])
    runner, clock = _runner(deploys, _CHAIN, ["staging", "prod"], window=300)

    result = runner.promote("#7")

    assert result.state is JobState.ON_HOLD and result.note == "staging not reached", result
    assert JobState.AWAITING_PROD_APPROVAL not in runner.tracker.states
    assert JobState.DONE not in runner.tracker.states
    said = " ".join(runner.tracker.comments)
    assert "staging verified" not in said, f"a stage nothing reached was called verified: {said}"
    assert "not reached" in said and "pending" in said and "failed" not in said, (
        f"a deploy still running was reported as a failure, or not at all: {said}")
    assert sum(clock.slept) == 300, "it did not wait out the window before holding"


def test_a_pending_deploy_is_WAITED_FOR_and_a_green_one_then_reaches_the_stage():
    deploys = _Deploys(staging=["pending", "pending", "success"], prod=["success"])
    runner, clock = _runner(deploys, _CHAIN, ["staging", "prod"])

    result = runner.promote("#7")

    assert result.state is JobState.AWAITING_PROD_APPROVAL, result
    assert deploys.reads.count("staging") == 3 and clock.slept == [60, 60], (deploys.reads,
                                                                            clock.slept)
    assert any("staging verified" in c for c in runner.tracker.comments)


def test_the_window_is_shared_by_the_WHOLE_walk_so_it_cannot_outlive_its_box():
    """The walk runs in one box launched with a 30-minute timeout; a window per stage on a long
    chain would keep waiting after the box that waits was gone."""
    envs = {"dev": Environment(deploy_ref="dev"), "qa": Environment(deploy_ref="qa"),
            "prod": Environment(deploy_ref="prod")}
    deploys = _Deploys(dev=["pending", "pending", "success"], qa=["pending"], prod=["success"])
    runner, clock = _runner(deploys, envs, ["dev", "qa", "prod"], window=180)

    result = runner.promote("#7")

    assert result.note == "qa not reached", result
    assert sum(clock.slept) == 180, f"the walk waited {sum(clock.slept)}s on a 180s window"


def test_a_FAILED_deploy_is_still_red_and_never_waited_for():
    deploys = _Deploys(staging=["failure"], prod=["success"])
    runner, clock = _runner(deploys, _CHAIN, ["staging", "prod"])

    result = runner.promote("#7")

    assert result.note == "staging red" and clock.slept == [], (result, clock.slept)


def test_a_production_deploy_still_pending_is_held_NOT_LIVE_and_NOT_ROLLED_BACK():
    """Rolling back a release nobody has seen fail would be acting on a guess."""
    deploys = _Deploys(staging=["success"], prod=["pending"])
    runner, _clock = _runner(deploys, _CHAIN, ["staging", "prod"], window=120)

    result = runner.release_prod("#7", version="1.0.0", approver="alice")

    assert result.state is JobState.ON_HOLD and result.note == "prod not reached", result
    assert JobState.DONE not in runner.tracker.states
    assert JobState.ROLLING_BACK not in runner.tracker.states, "a pending release was rolled back"
    assert not any("live in production" in m for _l, m in runner.notifier.sent)


def test_the_not_reached_sentence_is_said_in_the_projects_language():
    deploys = _Deploys(staging=["pending"], prod=["success"])
    runner, _clock = _runner(deploys, _CHAIN, ["staging", "prod"], window=60)
    runner.language = "pt-BR"

    runner.promote("#7")

    assert any("não alcançado" in c for c in runner.tracker.comments), runner.tracker.comments


# ── #518: a stage counts as reached only on what was observed ───────────────────────────────────

def _staging(**declared) -> dict[str, Environment]:
    return {"staging": Environment(**declared), "prod": Environment(deploy_ref="prod")}


@pytest.mark.parametrize("answer", ["unknown", "none"])
def test_a_deploy_nothing_read_with_NO_health_url_is_NOT_REACHED_and_held(answer):
    """`unknown` is nothing recorded for this ref there; `none` is the `ci: none` observer's
    answer for every ref. Neither is a deploy anybody saw, and there is no page to probe."""
    deploys = _Deploys(staging=[answer], prod=["success"])
    runner, clock = _runner(deploys, _staging(deploy_ref="staging"), ["staging", "prod"])

    result = runner.promote("#7")

    assert result.state is JobState.ON_HOLD and result.note == "staging not reached", result
    assert JobState.AWAITING_PROD_APPROVAL not in runner.tracker.states
    assert JobState.DONE not in runner.tracker.states
    said = " ".join(runner.tracker.comments)
    assert "staging verified" not in said, f"a stage nothing read was called verified: {said}"
    assert "not reached" in said and "health_url" in said, said
    assert "pending" not in said and "failed" not in said, (
        f"a deploy nothing read was reported as still running, or as a failure: {said}")
    assert clock.slept == [], "an answer that is not `pending` was waited for"


@pytest.mark.parametrize("answer", ["unknown", "none"])
def test_a_deploy_nothing_read_WITH_a_health_url_is_reached_only_when_the_probe_answers_HEALTHY(
        answer):
    deploys = _Deploys(staging=[answer], prod=["success"])
    runner, _clock = _runner(deploys, _staging(deploy_ref="staging", health_url="https://s/h"),
                             ["staging", "prod"])

    result = runner.promote("#7")

    assert deploys.probed == ["https://s/h"], "the probe did not decide"
    assert result.state is JobState.AWAITING_PROD_APPROVAL, result
    assert any("staging verified" in c for c in runner.tracker.comments)


@pytest.mark.parametrize("answer", ["unknown", "none"])
def test_a_deploy_nothing_read_whose_health_url_answers_UNHEALTHY_is_not_reached(answer):
    deploys = _Deploys(staging=[answer], prod=["success"], sick=frozenset({"https://s/h"}))
    runner, _clock = _runner(deploys, _staging(deploy_ref="staging", health_url="https://s/h"),
                             ["staging", "prod"])

    result = runner.promote("#7")

    assert result.state is JobState.ON_HOLD and result.note == "staging red", result
    assert JobState.AWAITING_PROD_APPROVAL not in runner.tracker.states
    assert not any("staging verified" in c for c in runner.tracker.comments)


def test_a_GREEN_deploy_with_no_health_url_is_still_reached():
    """The other observation. Without it the rule would hold every deploy-only stage."""
    deploys = _Deploys(staging=["success"], prod=["success"])
    runner, _clock = _runner(deploys, _staging(deploy_ref="staging"), ["staging", "prod"])

    assert runner.promote("#7").state is JobState.AWAITING_PROD_APPROVAL


def test_a_production_release_nothing_read_is_held_NOT_LIVE_and_NOT_ROLLED_BACK():
    deploys = _Deploys(staging=["success"], prod=["unknown"])
    runner, _clock = _runner(deploys, _CHAIN, ["staging", "prod"])

    result = runner.release_prod("#7", version="1.0.0", approver="alice")

    assert result.state is JobState.ON_HOLD and result.note == "prod not reached", result
    assert JobState.DONE not in runner.tracker.states
    assert JobState.ROLLING_BACK not in runner.tracker.states, "a release nobody read was undone"
    assert not any("live in production" in m for _l, m in runner.notifier.sent)


def test_the_nothing_read_sentence_is_said_in_the_projects_language():
    deploys = _Deploys(staging=["unknown"], prod=["success"])
    runner, _clock = _runner(deploys, _staging(deploy_ref="staging"), ["staging", "prod"])
    runner.language = "pt-BR"

    runner.promote("#7")

    assert any("não alcançado" in c and "nenhum deploy" in c for c in runner.tracker.comments), (
        runner.tracker.comments)


def test_on_ci_none_the_health_url_DECIDES_through_the_real_observer(monkeypatch):
    """The `none` row used to answer False without probing, so on a project with no CI the one
    observation it has could never come back healthy. No packet leaves: `httpx.get` answers here."""
    import httpx

    from openfactory.adapters.environment.none import NoObserver

    monkeypatch.setattr(httpx, "get",
                        lambda url, timeout: httpx.Response(200 if "up" in url else 503))
    for url, state in (("https://up/h", JobState.AWAITING_PROD_APPROVAL),
                       ("https://sick/h", JobState.ON_HOLD)):
        runner, _clock = _runner(NoObserver(), _staging(deploy_ref="staging", health_url=url),
                                 ["staging", "prod"])
        assert runner.promote("#7").state is state, url


# ── #518: a project whose CI reads no deploy, refused when the manifest loads ────────────────────

def _watched_by(forge: str, ci: str = ""):
    """A registry row: the forge's kind, and the CI it names (`forge.options.ci`), if any."""
    project = _Project()
    project.forge = type("F", (), {"kind": forge, "options": {"ci": ci} if ci else {}})()
    project.tracker = type("T", (), {"kind": forge, "options": {}})()
    return project


_READS_NO_DEPLOY = [pytest.param("github", "none", id="ci-none-named-on-a-github-forge"),
                    pytest.param("local", "", id="a-local-forge-which-maps-to-none")]


@pytest.mark.parametrize("forge,ci", _READS_NO_DEPLOY)
@pytest.mark.parametrize("keys,unprobed", [
    pytest.param({"environments": {"staging": {"deploy_ref": "staging", "url": "https://s"}}},
                 "staging", id="a-derived-staging-watched-only-by-its-deploy"),
    pytest.param({"environments": {"dev": {"health_url": "https://d/h"},
                                   "producao": {"deploy_ref": "producao"}},
                  "promote": ["dev", "producao"]}, "producao", id="production-included"),
])
def test_on_a_project_whose_CI_reads_no_deploy_a_stage_without_health_url_is_REFUSED_at_load(
        forge, ci, keys, unprobed, tmp_path):
    with pytest.raises(ValueError) as caught:
        load_manifest(_watched_by(forge, ci), repo_root=_write(tmp_path, **keys))

    said = str(caught.value)
    assert "project.yaml" in said, "the refusal does not name the file"
    assert f"'{unprobed}'" in said, f"the refusal does not name the stage: {said}"
    assert "reads no deploy" in said and "announced" in said, f"the reason is not named: {said}"
    assert "Declare health_url" in said and "forge.options.ci" in said, (
        f"the two fixes are not named: {said}")


@pytest.mark.parametrize("forge,ci", _READS_NO_DEPLOY)
def test_on_that_project_a_chain_whose_every_stage_has_a_health_url_loads(forge, ci, tmp_path):
    keys = {"environments": {"staging": {"deploy_ref": "staging", "health_url": "https://s/h"},
                             "prod": {"health_url": "https://p/h"}}}
    m = load_manifest(_watched_by(forge, ci), repo_root=_write(tmp_path, **keys))
    assert m.promotion_chain() == (["staging"], "prod")


@pytest.mark.parametrize("forge,ci", [pytest.param("github", "", id="github-reads-its-deploys"),
                                      pytest.param("github", "azure_pipelines",
                                                   id="a-named-ci-that-reads-deploys")])
def test_the_same_deploy_only_stage_loads_where_the_CI_reads_deploys(forge, ci, tmp_path):
    keys = {"environments": {"staging": {"deploy_ref": "staging"}}}
    m = load_manifest(_watched_by(forge, ci), repo_root=_write(tmp_path, **keys))
    assert m.environments["staging"].deploy_ref == "staging"


def test_the_manifest_alone_cannot_see_its_CI_so_it_validates_without_the_rule():
    """Which CI watches a project is the registry's; only the loader holds both."""
    m = Manifest.model_validate({**FLOOR, "environments": {"staging": {"deploy_ref": "staging"}}})
    assert m.promotion_chain() == (["staging"], None)


def test_the_compatibility_rule_says_a_pre_1_0_minor_may_refuse_a_shape_that_did_the_wrong_thing():
    """#501 and #518 narrow what version 1 accepts without a bump. The rule above
    `SUPPORTED_MANIFEST_VERSIONS` says when that is allowed, so code and practice agree."""
    source = (ROOT / "openfactory" / "contracts" / "manifest.py").read_text()
    rule = source[source.index("THE COMPATIBILITY RULE"):source.index("SUPPORTED_MANIFEST_VERSIONS:")]
    flat = " ".join(rule.replace("#:", " ").split())
    assert "may refuse in a" in flat and "pre-1.0 minor" in flat, flat
    assert "the WRONG THING" in flat and "upgrade note" in flat and "#501" in flat, flat


def test_every_document_that_teaches_the_chain_says_the_518_rule():
    for rel in ("docs/project.yaml.example", "docs/ONBOARDING.md", "docs/autonomous-flow.md",
                "docs/reference/configuration.md"):
        text = (ROOT / rel).read_text()
        assert "#518" in text, f"{rel} does not say a stage counts only on what was observed"
        flat = " ".join(text.replace("#", " ").split())
        assert "ci: none" in flat, f"{rel} does not say what a project with no CI must declare"
