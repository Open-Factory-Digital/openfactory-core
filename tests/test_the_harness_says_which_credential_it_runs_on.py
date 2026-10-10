"""The harness says which of a deployment's settings it authenticates with, and every probe asks it
(#582).

A deployment can keep its agent credentials only in the token pool, `OPENFACTORY_AGENT_TOKENS`, as
`docs/rotation-and-retention.md` describes. The agent adapter runs on it — it reads the pool first.
The doctor passed it: three names. The preflight, which the installer runs on every upgrade,
failed it: two names, "neither CLAUDE_CODE_OAUTH_TOKEN nor ANTHROPIC_API_KEY is set", and a remedy
to replace a token that worked. Three lists of one fact, compared by nothing.

Now the adapter answers (`claude_code.credential_in`, through `registry.harness_credential`) from
the code that reads them, and the doctor and the preflight ask it. The table below holds the three
answers to one another for every shape of settings the adapter takes — the adapter's own fallback
INCLUDED, so the probes cannot agree with each other and not with what runs.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from openfactory import doctor, preflight
from openfactory.adapters.agent import claude_code
from openfactory.adapters.agent.claude_code import CREDENTIALS, POOL
from openfactory.contracts.project import Project

ROOT = pathlib.Path(__file__).resolve().parent.parent
GOOD_POOL = '[{"id": "a", "token": "sk-ant-oat01-a"}, {"id": "b", "token": "sk-ant-oat01-b"}]'

#: Every shape of settings, and whether the harness runs on it.
SHAPES = {
    "the pool alone": ({POOL: GOOD_POOL}, True),
    "a subscription token alone": ({"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-x"}, True),
    "an API key alone": ({"ANTHROPIC_API_KEY": "sk-ant-api03-x"}, True),
    "a broken pool beside a token": ({POOL: "[{oops", "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-x"},
                                     True),
    "a broken pool alone": ({POOL: "[{oops"}, False),
    "a pool with no token in it, alone": ({POOL: '[{"id": "a"}]'}, False),
    "nothing": ({}, False),
}


@pytest.fixture
def bare(monkeypatch, tmp_path):
    """No credential and no harness choice in the environment; this test's own directory."""
    for name in (*CREDENTIALS, "OPENFACTORY_HARNESS_EXECUTOR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _in_the_file(where: pathlib.Path, rows: dict[str, str]) -> None:
    """The installer's case: the settings in `.env.compose`, none in the environment."""
    (where / ".env.compose").write_text("".join(f"{k}={v}\n" for k, v in rows.items()))


def _in_the_environment(monkeypatch, rows: dict[str, str]) -> None:
    for name, value in rows.items():
        monkeypatch.setenv(name, value)


def _doctor_probe(where: pathlib.Path):
    return doctor.probes_for(Project(name="acme", repo_path=str(where))).agent_credential


def test_the_table_covers_every_credential_the_harness_reads():
    """A GUARD THAT ASSERTS ITS OWN SCOPE: each name the adapter reads is a shape that runs alone."""
    alone = {next(iter(rows)) for rows, runs in SHAPES.values() if runs and len(rows) == 1}
    assert alone == set(CREDENTIALS)


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_the_adapter_the_doctor_and_the_preflight_give_one_answer(bare, monkeypatch, shape):
    rows, runs = SHAPES[shape]

    _in_the_file(bare, rows)
    preflight_says = preflight.probes_for_this_machine().agent_credential()
    (bare / ".env.compose").unlink()
    _in_the_environment(monkeypatch, rows)
    adapter_runs = bool(claude_code._load_agent_token_pool())
    doctor_says = _doctor_probe(bare)()

    assert adapter_runs is runs, "the table no longer says what the adapter does"
    assert preflight_says[0] is runs, preflight_says
    assert doctor_says[0] is runs, doctor_says


def test_a_deployment_on_the_pool_alone_passes_the_installers_preflight(bare):
    """TODAY'S DEFECT: an upgrade of a pool-only deployment was told no credential was visible."""
    _in_the_file(bare, {POOL: GOOD_POOL})

    report = preflight.check(preflight.probes_for_this_machine())

    [line] = [f for f in report.findings if f.check == "agent_credential"]
    assert line.ok, line
    assert f"{POOL} is set in .env.compose — a pool of 2" in line.message


def test_a_broken_pool_beside_a_token_runs_and_says_there_is_no_failover(bare, monkeypatch):
    rows, _runs = SHAPES["a broken pool beside a token"]
    _in_the_environment(monkeypatch, rows)

    ok, said = _doctor_probe(bare)()

    assert ok and said.startswith("CLAUDE_CODE_OAUTH_TOKEN is present")
    assert f"{POOL} is set and it could not be read" in said and "no failover" in said


def test_a_broken_pool_alone_fails_saying_why_not_that_nothing_is_set(bare):
    _in_the_file(bare, {POOL: "[{oops"})

    report = preflight.check(preflight.probes_for_this_machine())

    [line] = [f for f in report.findings if f.check == "agent_credential"]
    assert not line.ok
    assert f"{POOL} is set and it could not be read" in line.message, line.message


def test_a_pool_with_no_token_in_it_is_said_as_one(bare):
    """It parses, so no typo is reported — and it holds nothing to run on: the same lost failover,
    which fell back to a single token without a word."""
    _in_the_file(bare, {POOL: '[{"id": "a"}]'})

    ok, said = preflight.probes_for_this_machine().agent_credential()

    assert not ok and said == f"{POOL} is set and it holds no entry with a token"


@pytest.mark.parametrize("where", ["file", "environment"])
def test_a_harness_that_signs_in_by_its_own_login_is_not_failed_for_a_variable(bare, monkeypatch,
                                                                               where):
    """`codex login` and the like are no setting: there is no presence to read, and no variable
    to demand. Asked of the harness the deployment names, in the file or the environment — the
    doctor runs in the worker, whose environment holds the file's rows, so it reads that one."""
    if where == "file":
        _in_the_file(bare, {"OPENFACTORY_HARNESS_EXECUTOR": "codex"})
    else:
        monkeypatch.setenv("OPENFACTORY_HARNESS_EXECUTOR", "codex")

    ok, said = preflight.probes_for_this_machine().agent_credential()

    assert ok and "codex signs in through its own login" in said
    if where == "environment":
        doctor_ok, doctor_said = _doctor_probe(bare)()
        assert doctor_ok and "not checkable for 'codex'" in doctor_said


def test_every_harness_that_reads_a_credential_is_a_harness():
    from openfactory.adapters.agent.registry import HARNESS_CREDENTIALS, HARNESSES

    assert HARNESS_CREDENTIALS and set(HARNESS_CREDENTIALS) <= set(HARNESSES)


@pytest.mark.parametrize("module", ["openfactory/doctor.py", "openfactory/preflight.py"])
def test_no_probe_keeps_a_list_of_credentials_of_its_own(module):
    """A GUARD on the shape of the defect: a tuple, list or set holding a credential's name, or a
    credential read straight from the environment. A remedy may NAME one in a sentence."""
    names = set(CREDENTIALS)
    tree = ast.parse((ROOT / module).read_text())
    kept = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Tuple | ast.List | ast.Set) and any(
                isinstance(e, ast.Constant) and e.value in names for e in node.elts):
            kept.append(f"line {node.lineno}: a list of credential names")
        if (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "get"
                and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in names):
            kept.append(f"line {node.lineno}: {node.args[0].value} read directly")
    assert not kept, f"{module} decides what an agent credential is by itself again: {kept}"
