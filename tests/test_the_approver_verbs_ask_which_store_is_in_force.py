"""The approver verbs ask which store this deployment reads, and the store answers (#202).

    # OPENFACTORY_APPROVERS='{"ana": "…"}', OPENFACTORY_APPROVERS_FILE=<a temp file>
    $ openfactory approver add bia
    password for bia: ****
    approver 'bia' saved. Add them to a project's `prod_approvers` to allow.
    $ openfactory approver list
    ana

`approvals._load` reads `OPENFACTORY_APPROVERS` first, and while that variable is set the file is
not consulted at all. `add_approver` always wrote the FILE, and the verb above it printed `saved`
without asking which of the two was in force — so `bia` went to a file nothing reads, and her first
production approval was refused for a password the deployment had never heard of, at the moment a
release was waiting on it. The mirror of what #189 fixed for `approver remove`.

ONE QUESTION, ASKED BY EVERYBODY. `approvals.source()` is the read `_load` makes — the variable, or
the file at a path — and `add`, `remove`, `list` and the release gate's own "nobody can approve
here" all ask IT. Each case below drives the real typer app or the real approve route, and reads
the FILE afterwards rather than the sentence.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from openfactory import approvals
from openfactory.cli import app

VARIABLE = "OPENFACTORY_APPROVERS"

#: What the variable can hold that is not `{login: hash}`. Each is "set", so each is in force —
#: the file is NOT a fallback for a typo in a secret — and each yields nobody.
UNREADABLE = {
    "not JSON": "{ana: nope",
    "a JSON array": '["ana"]',
    "a JSON string": '"ana"',
}


@pytest.fixture
def file_store(tmp_path, monkeypatch):
    """A file store holding `ana`, written while the FILE is in force."""
    path = tmp_path / "approvers.json"
    monkeypatch.setenv("OPENFACTORY_APPROVERS_FILE", str(path))
    monkeypatch.delenv(VARIABLE, raising=False)
    approvals.add_approver("ana", "a-password")
    return path


@pytest.fixture
def variable(file_store, monkeypatch):
    """The variable in force, naming `carla` — over a file that names `ana`."""
    monkeypatch.setenv(VARIABLE, json.dumps({"carla": approvals.hash_password("c-password")}))
    return file_store


def _file(path) -> list[str]:
    """What the FILE holds — parsed, not the store's own word for it."""
    return sorted(json.loads(path.read_text())) if path.exists() else []


# ── the question ────────────────────────────────────────────────────────────────────────────────

def test_with_no_variable_the_file_is_the_source(file_store):
    src = approvals.source()
    assert src.variable is False
    assert src.path == file_store
    assert sorted(src.logins) == ["ana"]
    assert src.problem == ""


def test_with_the_variable_set_the_variable_is_the_source_and_the_file_is_not_read(variable):
    src = approvals.source()
    assert src.variable is True
    assert sorted(src.logins) == ["carla"]
    # the file is still NAMED — a refusal has to say which file it did not write
    assert src.path == variable


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_variable_set_to_nothing_is_not_in_force(file_store, monkeypatch, blank):
    """The remedy's own spelling: `OPENFACTORY_APPROVERS= openfactory approver add …` reaches the
    file even where a `.env` would otherwise fill the variable in (`load_dotenv` never overwrites
    a name the environment already holds)."""
    monkeypatch.setenv(VARIABLE, blank)
    assert approvals.source().variable is False
    assert approvals.list_approvers() == ["ana"]


@pytest.mark.parametrize("what", sorted(UNREADABLE))
def test_a_variable_that_cannot_be_read_is_in_force_and_says_why(file_store, monkeypatch, what):
    monkeypatch.setenv(VARIABLE, UNREADABLE[what])
    src = approvals.source()
    assert src.variable is True
    assert src.logins == {}
    assert src.problem, "a variable that yields nobody for a reason must carry the reason"
    # …and the reason never repeats the value: it is where the hashes live
    assert "ana" not in src.problem


def test_the_two_unreadable_shapes_are_told_apart(file_store, monkeypatch):
    monkeypatch.setenv(VARIABLE, UNREADABLE["not JSON"])
    not_json = approvals.source().problem
    monkeypatch.setenv(VARIABLE, UNREADABLE["a JSON array"])
    an_array = approvals.source().problem
    assert "not JSON" in not_json
    assert "array" in an_array and an_array != not_json


@pytest.mark.parametrize("value", [None, json.dumps({"carla": "x"}), *UNREADABLE.values()])
def test_every_reader_gets_what_the_question_got(file_store, monkeypatch, value):
    """`_load` IS the question's read, not a second spelling of it."""
    if value is not None:
        monkeypatch.setenv(VARIABLE, value)
    assert approvals._load() == approvals.source().logins
    assert approvals.list_approvers() == sorted(approvals.source().logins)


# ── the store refuses a write the deployment would not read ─────────────────────────────────────

def test_the_store_refuses_to_add_to_a_file_the_deployment_does_not_read(variable):
    with pytest.raises(approvals.NotTheStoreInForce) as refusal:
        approvals.add_approver("bia", "b-password")
    assert VARIABLE in str(refusal.value)
    assert _file(variable) == ["ana"]


def test_the_store_refuses_to_remove_from_a_file_the_deployment_does_not_read(variable):
    with pytest.raises(approvals.NotTheStoreInForce):
        approvals.remove_approver("ana")
    assert _file(variable) == ["ana"]


# ── approver add ────────────────────────────────────────────────────────────────────────────────

def test_add_refuses_while_the_variable_is_in_force(variable):
    out = CliRunner().invoke(app, ["approver", "add", "bia"], input="b-password\nb-password\n")
    assert out.exit_code != 0, out.output
    assert "saved" not in out.output.replace("was not saved", "")
    assert VARIABLE in out.output and "'bia'" in out.output
    assert _file(variable) == ["ana"]
    assert approvals.list_approvers() == ["carla"]


def test_add_refuses_before_it_asks_for_a_password(variable):
    """A person should not type a secret into a command that is about to refuse."""
    out = CliRunner().invoke(app, ["approver", "add", "bia"])       # no input at all
    assert out.exit_code != 0, out.output
    assert "password" not in out.output.lower().replace("openfactory_approvers", "")
    assert "Aborted" not in out.output          # what a prompt with nothing to read prints
    assert VARIABLE in out.output


def test_the_refusal_names_the_file_it_did_not_write_and_the_way_to_mint_the_entry(variable):
    out = CliRunner().invoke(app, ["approver", "add", "bia"])
    flat = " ".join(out.output.split())
    assert str(variable) in flat
    assert f"{VARIABLE}= openfactory approver add bia" in flat


def test_the_way_to_mint_the_entry_works(variable):
    """The refusal's own remedy, run: the blank variable reaches the file, `saved` is true."""
    out = CliRunner().invoke(app, ["approver", "add", "bia"], env={VARIABLE: ""},
                             input="b-password\nb-password\n")
    assert out.exit_code == 0, out.output
    assert _file(variable) == ["ana", "bia"]


def test_add_still_saves_when_the_file_is_in_force(file_store):
    out = CliRunner().invoke(app, ["approver", "add", "bia"], input="b-password\nb-password\n")
    assert out.exit_code == 0, out.output
    assert "saved" in out.output and str(file_store) in " ".join(out.output.split())
    assert _file(file_store) == ["ana", "bia"]
    assert approvals.verify_approver("bia", "b-password", ["bia"])


@pytest.mark.parametrize("what", sorted(UNREADABLE))
def test_add_is_honest_about_a_variable_it_cannot_read(file_store, monkeypatch, what):
    """Not "add the login to the variable" over a variable nothing can parse: the sentence says
    the variable is what is read AND that it cannot be read as it stands."""
    monkeypatch.setenv(VARIABLE, UNREADABLE[what])
    out = CliRunner().invoke(app, ["approver", "add", "bia"])
    assert out.exit_code != 0, out.output
    assert approvals.source().problem in " ".join(out.output.split())
    assert _file(file_store) == ["ana"]


def test_no_refusal_is_a_traceback(variable):
    for argv in (["approver", "add", "bia"], ["approver", "remove", "ana"],
                 ["approver", "remove", "carla"], ["approver", "list"]):
        out = CliRunner().invoke(app, argv)
        assert out.exception is None or isinstance(out.exception, SystemExit), repr(out.exception)
        assert "Traceback" not in out.output


# ── approver list ───────────────────────────────────────────────────────────────────────────────

def test_list_says_it_is_reading_the_variable(variable):
    out = CliRunner().invoke(app, ["approver", "list"])
    assert out.exit_code == 0, out.output
    assert out.stdout.split() == ["carla"]
    assert VARIABLE in out.stderr


def test_list_says_it_is_reading_the_file_and_which(file_store):
    out = CliRunner().invoke(app, ["approver", "list"])
    assert out.exit_code == 0, out.output
    assert out.stdout.split() == ["ana"]
    assert str(file_store) in " ".join(out.stderr.split())
    assert VARIABLE not in out.stderr


def test_the_logins_stay_alone_on_stdout(variable):
    """`for a in $(openfactory approver list)` was one login per line before this, and still is:
    the source is said on stderr, where a person reads it and a pipe does not."""
    out = CliRunner().invoke(app, ["approver", "list"])
    assert out.stdout == "carla\n"


@pytest.mark.parametrize("what", sorted(UNREADABLE))
def test_list_does_not_call_an_unreadable_variable_an_empty_roster(file_store, monkeypatch, what):
    monkeypatch.setenv(VARIABLE, UNREADABLE[what])
    out = CliRunner().invoke(app, ["approver", "list"])
    assert out.exit_code != 0, out.output
    assert out.stdout == ""
    assert approvals.source().problem in " ".join(out.stderr.split())


def test_an_empty_file_store_says_how_the_first_approver_is_added(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_APPROVERS_FILE", str(tmp_path / "nobody-yet.json"))
    monkeypatch.delenv(VARIABLE, raising=False)
    out = CliRunner().invoke(app, ["approver", "list"])
    assert out.exit_code == 0, out.output
    assert out.stdout == ""
    assert "openfactory approver add" in out.stderr


# ── approver remove: #189's check, moved onto the same question ─────────────────────────────────

def test_remove_leaves_the_file_alone_while_the_variable_names_the_login(variable, monkeypatch):
    monkeypatch.setenv(VARIABLE, json.dumps({"ana": "x"}))
    out = CliRunner().invoke(app, ["approver", "remove", "ana"])
    assert out.exit_code != 0, out.output
    assert VARIABLE in out.output
    # it used to take `ana` out of the file on its way to saying she was still an approver
    assert _file(variable) == ["ana"]


def test_remove_of_a_login_the_variable_does_not_name_lists_the_variables_own(variable):
    out = CliRunner().invoke(app, ["approver", "remove", "ana"])
    assert out.exit_code != 0, out.output
    assert "removed" not in out.output.replace("nothing was removed", "")
    assert "carla" in out.output and VARIABLE in out.output
    assert _file(variable) == ["ana"]


def test_remove_still_removes_when_the_file_is_in_force(file_store):
    out = CliRunner().invoke(app, ["approver", "remove", "ana"])
    assert out.exit_code == 0, out.output
    assert _file(file_store) == []


# ── the release gate: "nobody can approve here" does not send a person to a verb that refuses ───

@pytest.fixture
def approve(tmp_path, monkeypatch):
    """The real approve route over a registered project with no checkout (the deployed shape), an
    engine that records the signal instead of dialing, and no allowlist from the environment."""
    from openfactory.api import app as app_module
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import view as tv

    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_PROD_APPROVERS", raising=False)
    monkeypatch.setenv("OPENFACTORY_APPROVERS_FILE", str(tmp_path / "no-approvers.json"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    ProjectRegistry().add(Project(name="p", repo_path=str(tmp_path / "no-checkout"),
                                  tracker=ProviderRef(kind="github", repo="o/p")))
    signals: list[dict] = []

    async def connect():
        return object()

    async def approve_job(client, project, issue, **kw):
        signals.append(kw)

    monkeypatch.setattr(tv, "connect", connect)
    monkeypatch.setattr(tv, "approve_job", approve_job)
    client = TestClient(app_module.app)

    def post():
        r = client.post("/api/temporal/approve/p/5",
                        json={"approver": "alice", "password": "s3cret", "version": "1.2.0"})
        assert signals == []
        return r
    return post


@pytest.mark.parametrize("what", sorted(UNREADABLE))
def test_the_gate_says_the_variable_cannot_be_read_not_that_it_is_missing(
        approve, monkeypatch, caplog, what):
    """It said "no password can work until the OPENFACTORY_APPROVERS secret is provisioned" about
    a secret that WAS provisioned, and its log line sent the operator to `openfactory approver
    add` — which, with the variable set, is the verb that refuses."""
    monkeypatch.setenv(VARIABLE, UNREADABLE[what])
    r = approve()
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert approvals.source().problem in detail
    assert "until the OPENFACTORY_APPROVERS secret is provisioned" not in detail
    assert "OPENFACTORY_APPROVER_STORE_MISSING" in caplog.text
    assert "or run `openfactory approver add` where the panel runs" not in caplog.text


def test_the_gate_says_a_variable_that_names_nobody_names_nobody(approve, monkeypatch, caplog):
    monkeypatch.setenv(VARIABLE, "{}")
    r = approve()
    assert r.status_code == 503
    assert "names nobody" in r.json()["detail"]
    assert "or run `openfactory approver add` where the panel runs" not in caplog.text


def test_the_gate_still_sends_a_deployment_with_no_store_at_all_to_both_remedies(
        approve, monkeypatch, caplog):
    monkeypatch.delenv(VARIABLE, raising=False)
    r = approve()
    assert r.status_code == 503
    assert VARIABLE in r.json()["detail"]
    assert "openfactory approver add" in caplog.text
