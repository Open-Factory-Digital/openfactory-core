"""Preflight reads a deployment's settings where the deployment keeps them (#560).

An upgrade with `install.sh --force` printed `FAIL agent_credential — no agent credential is
visible to this deployment` and told the person to replace a token that was in `.env.compose` and
worked. The installer runs `preflight` in the CLI image with the installation's directory as its
working directory and none of `.env.compose` in its environment; the credential probe read the
environment alone, while the same run's `env_file` probe read the file. The ports probe read the
same way, so a deployment whose ports were moved had the defaults checked.

THE INSTALLER'S CASE, HERE: a working directory holding `.env.compose`, and an environment holding
none of it. Every probe of a deployment setting reads the file's rows under the environment —
what compose itself does.
"""

from __future__ import annotations

import pytest

from openfactory import preflight

CREDENTIALS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")


@pytest.fixture
def installation(tmp_path, monkeypatch):
    """The installer's run: `/out` with its `.env.compose`, and a bare environment."""
    for name in (*CREDENTIALS, *(variable for _w, variable, _d in preflight.PUBLISHED_PORTS)):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    def write(**rows: str) -> None:
        (tmp_path / ".env.compose").write_text(
            "# written by openfactory init\n" + "".join(f"{k}={v}\n" for k, v in rows.items()))
    return write


def test_an_upgrade_sees_the_credential_its_env_file_holds(installation):
    installation(CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-kept")

    seen = preflight.probes_for_this_machine().agent_credential()

    assert seen == (True, "CLAUDE_CODE_OAUTH_TOKEN is set in .env.compose")


def test_an_upgrade_checks_the_ports_it_moved(installation):
    (what, variable, default), *_ = preflight.PUBLISHED_PORTS
    installation(**{variable: str(default + 1000)})

    ports = dict(preflight.probes_for_this_machine().ports())

    assert ports[what] == default + 1000, ports


def test_the_environment_wins_over_the_file_as_it_does_for_compose(installation, monkeypatch):
    (what, variable, default), *_ = preflight.PUBLISHED_PORTS
    installation(**{variable: str(default + 1000)})
    monkeypatch.setenv(variable, str(default + 2000))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-env")

    probes = preflight.probes_for_this_machine()

    assert dict(probes.ports())[what] == default + 2000
    assert probes.agent_credential() == (True, "ANTHROPIC_API_KEY is set in the environment")


def test_a_first_install_has_no_file_and_no_credential(installation):
    """THE FAIL A FIRST INSTALL EXPECTS STAYS: nothing has been written yet (`run_preflight`)."""
    seen = preflight.probes_for_this_machine().agent_credential()

    assert seen == (False, "neither CLAUDE_CODE_OAUTH_TOKEN nor ANTHROPIC_API_KEY is set")


def test_the_whole_report_says_ok_where_the_installer_once_said_fail(installation):
    """The verdict a person reads, not only the probe: `agent_credential` is OK in the report the
    installer prints, on the run that used to FAIL it."""
    installation(CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-kept")
    real = preflight.probes_for_this_machine()

    report = preflight.check(real)

    [line] = [f for f in report.findings if f.check == "agent_credential"]
    assert line.ok, line
