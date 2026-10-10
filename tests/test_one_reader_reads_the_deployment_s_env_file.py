"""The deployment's env file is read by one set of rules, and an unreadable one is said as such
(#583).

Since #560 the preflight takes the agent credential and the published ports from `.env.compose`,
and it read the file with a parser of its own: `PANEL_PORT=8788  # moved` read
`8788  # moved`, failed as a number, and the DEFAULT port was checked; `export KEY=v` read as the
key `export KEY`. The preview assembler kept a second parser that disagreed with the first, and the
CLI loads the same kind of file through python-dotenv. And a file that was there and could not be
read — root-owned at 0600 after a `sudo` run, the installer running as the person's own uid — read
as no file at all, so the credential line said nothing was set.

Now `envfile.read` is the one reader, on `dotenv_values`, and every probe reads through it.
"""

from __future__ import annotations

import ast
import os
import pathlib

import pytest

from openfactory import envfile, preflight

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: A file as a person edits it by hand, and what each setting in it means.
BY_HAND = (
    "# edited by hand\n"
    "export ANTHROPIC_API_KEY=sk-ant-api03-exported\n"
    "PANEL_PORT=8788  # moved\n"
    "OPENFACTORY_PREVIEW_DOMAIN='preview.example.org'\n"
    'OPENFACTORY_PREVIEW_RUNTIME="compose"   # quoted, then a comment\n'
    "OPENFACTORY_PREVIEW_REACH=network#not-a-comment\n"
    "OPENFACTORY_PREVIEW_DOCKER_CONFIG=${NOT_SET_583}/docker\n"
    "A_NAME_WITH_NO_VALUE\n"
)
MEANT = {
    "ANTHROPIC_API_KEY": "sk-ant-api03-exported",
    "PANEL_PORT": "8788",
    "OPENFACTORY_PREVIEW_DOMAIN": "preview.example.org",
    "OPENFACTORY_PREVIEW_RUNTIME": "compose",
    "OPENFACTORY_PREVIEW_REACH": "network#not-a-comment",
    "OPENFACTORY_PREVIEW_DOCKER_CONFIG": "${NOT_SET_583}/docker",  # as written, never expanded
}


@pytest.fixture
def installation(tmp_path, monkeypatch):
    """The installer's run: `.env.compose` in the working directory, none of it in the
    environment."""
    for name in (*MEANT, "CLAUDE_CODE_OAUTH_TOKEN", "OPENFACTORY_AGENT_TOKENS",
                 *(variable for _w, variable, _d in preflight.PUBLISHED_PORTS)):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_a_file_edited_by_hand_reads_as_it_was_meant(tmp_path):
    (tmp_path / ".env.compose").write_text(BY_HAND)

    read = envfile.read(tmp_path / ".env.compose")

    assert read.exists and not read.unreadable
    assert read.rows == MEANT


def test_it_reads_as_the_cli_loads_the_same_file(tmp_path):
    """THE RULES ARE THE CLI'S: `cli._load_environment` loads these files through python-dotenv,
    and this reader may not drift from it on any row a person writes."""
    from dotenv import dotenv_values

    (tmp_path / "env").write_text(BY_HAND)

    loaded = {k: v for k, v in dotenv_values(tmp_path / "env", interpolate=False).items()
              if v is not None}
    assert envfile.read(tmp_path / "env").rows == loaded


def test_the_installers_preflight_checks_the_port_the_file_moved(installation):
    """TODAY'S DEFECT: the moved port, with a comment after it, read as no number at all."""
    (installation / ".env.compose").write_text(BY_HAND)

    [what] = [w for w, variable, _d in preflight.PUBLISHED_PORTS
              if variable == "PANEL_PORT"]

    ports = dict(preflight.probes_for_this_machine().ports())

    assert ports[what] == 8788, ports


def test_an_exported_credential_in_the_file_is_seen(installation):
    (installation / ".env.compose").write_text(BY_HAND)

    seen = preflight.probes_for_this_machine().agent_credential()

    assert seen == (True, "ANTHROPIC_API_KEY is set in .env.compose")


def test_every_probe_of_a_setting_reads_the_same_rows(installation):
    (installation / ".env.compose").write_text(BY_HAND)

    rows = preflight.probes_for_this_machine().preview_rows()

    assert rows["OPENFACTORY_PREVIEW_DOMAIN"] == "preview.example.org"
    assert rows["OPENFACTORY_PREVIEW_RUNTIME"] == "compose"


@pytest.fixture
def unreadable(installation):
    if os.geteuid() == 0:
        pytest.skip("root reads a file whatever its mode")
    path = installation / ".env.compose"
    path.write_text("CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-kept\n")
    path.chmod(0o000)
    yield path
    path.chmod(0o600)


def test_a_file_that_is_there_and_cannot_be_read_is_not_an_absent_one(unreadable):
    read = envfile.read(unreadable)

    assert read.exists and read.unreadable == "permission denied" and read.rows == {}
    assert envfile.read(unreadable.parent / "nothing-here") == envfile.EnvFile()


def test_the_preflight_says_the_file_could_not_be_read_and_not_that_nothing_is_set(unreadable):
    report = preflight.check(preflight.probes_for_this_machine())

    lines = {f.check: f for f in report.findings}
    assert not lines["env_file"].ok
    assert "is there but could not be read (permission denied)" in lines["env_file"].message
    assert "chown" in lines["env_file"].remedy
    assert not lines["agent_credential"].ok
    seen = preflight.probes_for_this_machine().agent_credential()
    assert seen[1].endswith(".env.compose is there but could not be read (permission denied)"), seen


def test_the_preview_reads_a_products_env_file_by_the_same_rules(tmp_path):
    from openfactory.preview import assemble

    (tmp_path / "app.env").write_text(BY_HAND)

    values = dict(assemble._env_values({"env_file": [str(tmp_path / "app.env")]}))

    assert {k: values[k] for k in MEANT} == MEANT


def _hand_written_parsers(package: pathlib.Path = ROOT / "openfactory") -> list[str]:
    """Functions that read `KEY=value` lines past `#` comments — an env file's parser."""
    found = []
    for path in sorted(package.rglob("*.py")):
        for fn in ast.walk(ast.parse(path.read_text())):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            calls = [(n.func.attr, n.args[0].value) for n in ast.walk(fn)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.args
                     and isinstance(n.args[0], ast.Constant)]
            if ("startswith", "#") in calls and (("partition", "=") in calls
                                                  or ("split", "=") in calls):
                found.append(f"{path.relative_to(package.parent)}:{fn.lineno} {fn.name}")
    return found


def test_no_env_file_is_parsed_by_hand():
    """A GUARD on the shape of the defect: a function that skips `#` lines and splits on `=`.
    `envfile` is the one reader; a fourth would drift from it the way the second and third did."""
    assert _hand_written_parsers() == []


def test_the_guard_sees_a_parser_written_by_hand(tmp_path):
    """THE GUARD CALLS ITS OWN RULE: the parser this replaced, put back, is found — planted in a
    package of the test's own, never in the tree the rest of the suite is reading."""
    package = tmp_path / "openfactory"
    package.mkdir()
    (package / "settings.py").write_text(
        "def rows(text):\n"
        "    out = {}\n"
        "    for line in text.splitlines():\n"
        "        if line.startswith('#'):\n"
        "            continue\n"
        "        key, _, value = line.partition('=')\n"
        "        out[key] = value\n"
        "    return out\n")

    assert _hand_written_parsers(package) == ["openfactory/settings.py:1 rows"]
