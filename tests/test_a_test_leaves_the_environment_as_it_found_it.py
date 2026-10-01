"""Every test leaves `os.environ` as it found it, whatever the code under test wrote (#426).

The fixture is driven directly here, because the property is about what happens BETWEEN tests,
and which test runs next is decided by the plugin that randomises the order."""

from __future__ import annotations

import os

from tests import conftest


def _run_one_test(body) -> None:
    fixture = conftest._the_environment_is_restored_after_every_test.__wrapped__()
    next(fixture)
    body()
    for _ in fixture:
        pass


def test_a_variable_the_code_wrote_is_gone_after_the_test(monkeypatch):
    monkeypatch.delenv("OPENFACTORY_TEST_LEAK_PROBE", raising=False)

    _run_one_test(lambda: os.environ.__setitem__("OPENFACTORY_TEST_LEAK_PROBE", "written"))

    assert "OPENFACTORY_TEST_LEAK_PROBE" not in os.environ


def test_a_variable_the_code_changed_or_removed_is_put_back(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_TEST_LEAK_KEPT", "before")
    monkeypatch.setenv("OPENFACTORY_TEST_LEAK_GONE", "before")

    def body():
        os.environ["OPENFACTORY_TEST_LEAK_KEPT"] = "changed"
        del os.environ["OPENFACTORY_TEST_LEAK_GONE"]

    _run_one_test(body)

    assert os.environ["OPENFACTORY_TEST_LEAK_KEPT"] == "before"
    assert os.environ["OPENFACTORY_TEST_LEAK_GONE"] == "before"


def test_the_load_environment_test_no_longer_leaks_the_panel_address(tmp_path, monkeypatch):
    """The measured case: `cli._load_environment()` writes the panel address from a deployment's
    env file; after the test the variable is absent again."""
    from openfactory import cli

    home = tmp_path / "home"
    (home / ".openfactory").mkdir(parents=True)
    (home / ".openfactory" / "env").write_text("OPENFACTORY_PANEL_URL=http://localhost:8787\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENFACTORY_PANEL_URL", raising=False)

    _run_one_test(cli._load_environment)

    assert "OPENFACTORY_PANEL_URL" not in os.environ
