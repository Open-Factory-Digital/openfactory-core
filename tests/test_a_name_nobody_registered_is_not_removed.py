"""A removal that removed nothing does not say `removed` (#138).

    $ openfactory project remove definitely-not-a-registered-project-xyz
    removed 'definitely-not-a-registered-project-xyz'
    $ echo $?
    0

`ProjectRegistry.remove()` was `raw.pop(name, None)` — a no-op for a name nobody registered — and
the verb printed its success line unconditionally. It was found the expensive way: a shell loop
whose quoting mistake handed the command ONE argument holding every name. Each call said
`removed …` and exited 0, the registry was unchanged, and the script reported complete success.

THE REGISTRY ANSWERS, NOT THE VERB. `attach_board`, `set_model` and `set_language` already raise
`KeyError` for a name that is not there; `remove` was the one write that swallowed it, so every
caller — this CLI today, a panel action tomorrow — inherited the lie. Each case below drives the
real registry file and the real typer app, and reads the FILE afterwards rather than the sentence.

`openfactory approver remove` had the same shape one table over (`store.pop(login, None)` and an
unconditional `removed …`), and there the cost is not cosmetic: a mistyped login reports success
while the person keeps their say over a production release.
"""

from __future__ import annotations

import json

import pytest
import yaml
from typer.testing import CliRunner

from openfactory import approvals
from openfactory.cli import app
from openfactory.contracts.project import Project, ProviderRef
from openfactory.registry import ProjectRegistry


def _p(name: str) -> Project:
    return Project(name=name, repo_path=f"/tmp/{name}",
                   tracker=ProviderRef(kind="local", repo=name))


@pytest.fixture
def registry(tmp_path, monkeypatch):
    path = tmp_path / "registry.yaml"
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(path))
    reg = ProjectRegistry(path)
    reg.add(_p("alpha"))
    reg.add(_p("beta"))
    return reg


def _names(reg: ProjectRegistry) -> list[str]:
    """What the FILE holds — parsed, not the registry's own word for it."""
    return sorted((yaml.safe_load(reg.path.read_text()) or {}).get("projects") or {})


# ── the registry ────────────────────────────────────────────────────────────────────────────────

def test_the_registry_refuses_a_name_it_does_not_hold(registry):
    with pytest.raises(KeyError):
        registry.remove("gamma")
    assert _names(registry) == ["alpha", "beta"]


def test_the_registry_still_removes_a_name_it_holds(registry):
    registry.remove("alpha")
    assert _names(registry) == ["beta"]


def test_a_second_removal_of_the_same_name_is_refused_too(registry):
    registry.remove("alpha")
    with pytest.raises(KeyError):
        registry.remove("alpha")


# ── the verb ────────────────────────────────────────────────────────────────────────────────────

def test_removing_an_unknown_project_says_so_and_exits_non_zero(registry):
    out = CliRunner().invoke(app, ["project", "remove", "gamma"])
    assert out.exit_code != 0, out.output
    assert "removed" not in out.output.replace("nothing was removed", "")
    assert "'gamma'" in out.output
    # the roster is the remedy: the name that WAS meant is on it
    assert "alpha" in out.output and "beta" in out.output
    assert _names(registry) == ["alpha", "beta"]


def test_the_quoting_mistake_that_found_this_is_refused(registry):
    """One argument holding every name — the loop that reported success over nothing."""
    out = CliRunner().invoke(app, ["project", "remove", "alpha beta"])
    assert out.exit_code != 0, out.output
    assert _names(registry) == ["alpha", "beta"]


def test_removing_a_registered_project_still_succeeds(registry):
    out = CliRunner().invoke(app, ["project", "remove", "alpha"])
    assert out.exit_code == 0, out.output
    assert "removed 'alpha'" in out.output
    assert _names(registry) == ["beta"]


def test_the_refusal_is_a_sentence_not_a_traceback(registry):
    out = CliRunner().invoke(app, ["project", "remove", "gamma"])
    assert out.exception is None or isinstance(out.exception, SystemExit), repr(out.exception)
    assert "Traceback" not in out.output


# ── the same shape, one table over: approvers ───────────────────────────────────────────────────

@pytest.fixture
def approvers(tmp_path, monkeypatch):
    path = tmp_path / "approvers.json"
    monkeypatch.setenv("OPENFACTORY_APPROVERS_FILE", str(path))
    monkeypatch.delenv("OPENFACTORY_APPROVERS", raising=False)
    approvals.add_approver("ana", "a-password")
    return path


def test_the_approver_store_says_whether_it_removed_anyone(approvers):
    assert approvals.remove_approver("anna") is False
    assert sorted(json.loads(approvers.read_text())) == ["ana"]
    assert approvals.remove_approver("ana") is True
    assert json.loads(approvers.read_text()) == {}


def test_removing_an_unknown_approver_says_so_and_exits_non_zero(approvers):
    out = CliRunner().invoke(app, ["approver", "remove", "anna"])
    assert out.exit_code != 0, out.output
    assert "'anna'" in out.output and "ana" in out.output
    assert sorted(json.loads(approvers.read_text())) == ["ana"]


def test_removing_a_known_approver_still_succeeds(approvers):
    out = CliRunner().invoke(app, ["approver", "remove", "ana"])
    assert out.exit_code == 0, out.output
    assert approvals.list_approvers() == []


def test_an_approver_the_environment_still_names_is_not_called_removed(approvers, monkeypatch):
    """`OPENFACTORY_APPROVERS` wins over the file on every read, so taking a login out of the
    file changes nothing a release gate will see — and the verb must not say otherwise."""
    monkeypatch.setenv("OPENFACTORY_APPROVERS", json.dumps({"ana": "x"}))
    out = CliRunner().invoke(app, ["approver", "remove", "ana"])
    assert out.exit_code != 0, out.output
    assert "OPENFACTORY_APPROVERS" in out.output
