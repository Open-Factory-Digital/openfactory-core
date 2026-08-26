"""An environment a client declares is watched, or they are told it is not — #109.

`Manifest.environments` is a free dict: a client declares as many as they run. `PromotionRunner`
— the whole post-merge tail — then asks for exactly two, BY NAME:

    staging = self.manifest.environments.get("staging")     # promotion.py
    prod    = self.manifest.environments.get("prod")

Everything else loads, validates, and is read by nothing. And `loader._INERT` could not see it,
by construction: that table names whole manifest KEYS, and `environments` IS read — the silence
is one level down, inside a key that passes.

WHY THIS IS NOT AN EDGE CASE. Three environments is the corporate norm — dev/qa/prod, or
dev/homologação/produção — and in a regulated shop having the three separate with an approval
before the last is a change-management requirement written into a policy somebody audits. So the
client declares three, the tail observes two, and the third produces no line anywhere: the
deployment believes it is being watched and it is not.

WHAT THIS FILE DOES NOT CLAIM TO FIX. The tail still models two stages. Teaching it a chain the
client declares (`promote: [dev, qa, prod]`, human gate before the last) is the better product and
a change to the state machine — named in #109 and not half-built here. What is closed is the
SILENCE, which is the half that lets somebody find out from an auditor.
"""

from __future__ import annotations

import logging
import pathlib

import pytest
import yaml

from openfactory import namespace
from openfactory.loader import OBSERVED_ENVIRONMENTS, load_manifest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Project:
    name = "acme"
    manifest_path = namespace.MANIFEST


def _with_environments(tmp_path: pathlib.Path, envs: dict) -> pathlib.Path:
    (tmp_path / namespace.DIR).mkdir(parents=True, exist_ok=True)
    (tmp_path / namespace.MANIFEST).write_text(yaml.safe_dump({
        "version": 1, "base_branch": "main",
        "validate": {"test": "pytest -q", "security": "true"},
        "environments": envs,
    }))
    return tmp_path


# ── the list this guard rests on is the list the runner actually asks for ───────────────────────

def test_the_names_here_are_what_the_TAIL_walks_by_default():
    """The transcription became a DERIVATION the day the tail learned the declared chain (#109):
    `Manifest.promotion_chain()` is the one answer, and `OBSERVED_ENVIRONMENTS` mirrors its
    no-chain branch. So the two are checked BEHAVIOURALLY — the loader's default set must be
    exactly what the chain answers for a manifest that declares both fixed names and no chain."""
    from openfactory.contracts import Manifest

    m = Manifest(version=1, base_branch="main", validate={"test": "t", "security": "true"},
                 environments={"staging": {}, "prod": {}})
    stages, production = m.promotion_chain()

    assert tuple(stages) + ((production,) if production else ()) == OBSERVED_ENVIRONMENTS, (
        f"the tail derives {stages}+{production!r} and the loader assumes "
        f"{OBSERVED_ENVIRONMENTS} — one of them moved, and the warning is about the wrong set")


def test_a_DECLARED_chain_is_the_observed_set(tmp_path, caplog):
    """The corporate manifest, both halves of #109 at once: three environments plus the chain
    that names them all → nothing is inert, nothing warns. The same three without the chain is
    the silent-third case the warning below exists for."""
    (tmp_path / namespace.DIR).mkdir(parents=True, exist_ok=True)
    (tmp_path / namespace.MANIFEST).write_text(yaml.safe_dump({
        "version": 1, "base_branch": "main",
        "validate": {"test": "pytest -q", "security": "true"},
        "environments": {"dev": {}, "qa": {}, "prod": {}},
        "promote": ["dev", "qa", "prod"],
    }))

    with caplog.at_level(logging.WARNING, logger="openfactory.loader"):
        m = load_manifest(_Project(), repo_root=tmp_path)

    assert "OPENFACTORY_MANIFEST_INERT" not in caplog.text, caplog.text
    assert m.promotion_chain() == (["dev", "qa"], "prod")


def test_a_chain_step_with_no_environment_is_REFUSED():
    """A chain step that names nothing would be 'verified' vacuously green in the exact place a
    regulated client put a stage BECAUSE it must be checked — so it refuses, naming both sides."""
    from pydantic import ValidationError

    from openfactory.contracts import Manifest

    with pytest.raises(ValidationError, match="promote.*qa.*declares no such entry"):
        Manifest(version=1, base_branch="main", validate={"test": "t", "security": "true"},
                 environments={"prod": {}}, promote=["qa", "prod"])


def test_a_chain_that_repeats_a_stage_is_REFUSED():
    from pydantic import ValidationError

    from openfactory.contracts import Manifest

    with pytest.raises(ValidationError, match="more than once"):
        Manifest(version=1, base_branch="main", validate={"test": "t", "security": "true"},
                 environments={"qa": {}, "prod": {}}, promote=["qa", "qa", "prod"])


# ── the silence is closed ───────────────────────────────────────────────────────────────────────

def test_a_declared_environment_nobody_observes_says_so(tmp_path, caplog):
    """The defect. A client's own change-management policy asks for three; two are watched."""
    repo = _with_environments(tmp_path, {
        "dev": {"health_url": "https://dev.example/health"},
        "qa": {"health_url": "https://qa.example/health"},
        "prod": {"health_url": "https://example/health"},
    })

    with caplog.at_level(logging.WARNING, logger="openfactory.loader"):
        load_manifest(_Project(), repo_root=repo)

    assert "OPENFACTORY_MANIFEST_INERT" in caplog.text, caplog.text
    assert "`dev`" in caplog.text and "`qa`" in caplog.text, (
        f"the unobserved environments are not named, so nobody knows WHICH: {caplog.text}")
    assert "`prod`" not in caplog.text.split("declares environment(s)")[-1].split("—")[0], (
        "an environment that IS observed was reported as inert")


def test_a_manifest_the_tail_FULLY_observes_says_nothing(tmp_path, caplog):
    """The positive twin, and it is the one that decides whether the warning is worth reading. A
    line that fires on every project is a line everybody filters out — and then the real one is
    filtered out with it."""
    repo = _with_environments(tmp_path, {
        "staging": {"health_url": "https://staging.example/health"},
        "prod": {"health_url": "https://example/health"},
    })

    with caplog.at_level(logging.WARNING, logger="openfactory.loader"):
        load_manifest(_Project(), repo_root=repo)

    assert "environment" not in caplog.text, f"a fully observed manifest was warned about: {caplog.text}"


def test_declaring_NO_environments_is_not_a_complaint(tmp_path, caplog):
    """A project born without production is an ordinary state, not a misconfiguration — the tail's
    own docstring says so about a real client whose manifest declares none at all."""
    repo = _with_environments(tmp_path, {})

    with caplog.at_level(logging.WARNING, logger="openfactory.loader"):
        load_manifest(_Project(), repo_root=repo)

    assert "environment" not in caplog.text, caplog.text


def test_the_warning_says_what_to_DO(tmp_path, caplog):
    """"This is ignored" without "here is the fix" is a line somebody reads once and stops
    reading. The remedy is concrete for the common case — the stage before production is what
    `staging` means — and honest for the case the platform cannot yet express."""
    repo = _with_environments(tmp_path, {"qa": {"health_url": "https://qa/h"},
                                         "prod": {"health_url": "https://p/h"}})

    with caplog.at_level(logging.WARNING, logger="openfactory.loader"):
        load_manifest(_Project(), repo_root=repo)

    assert "Add them to `promote:`" in caplog.text, caplog.text
    assert "human gate before the last" in caplog.text, (
        "the remedy must say what the chain MEANS, not just its key")


@pytest.mark.parametrize("name", sorted(OBSERVED_ENVIRONMENTS))
def test_an_observed_environment_is_never_called_inert(name, tmp_path, caplog):
    """The other direction of the same rule: crying wolf about an environment the tail DOES watch
    would send somebody to rename a key that is already right."""
    repo = _with_environments(tmp_path, {name: {"health_url": "https://x/h"}})

    with caplog.at_level(logging.WARNING, logger="openfactory.loader"):
        load_manifest(_Project(), repo_root=repo)

    assert f"`{name}`" not in caplog.text.split("declares environment(s)")[-1][:200], caplog.text
