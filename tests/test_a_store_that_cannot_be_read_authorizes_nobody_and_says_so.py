"""An approver store that cannot be read authorizes NOBODY, and says so by name.

    $ openfactory approver list                      # ~/.openfactory/approvers.json lost its last brace
    Traceback (most recent call last):
      …
    json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 16

    POST /api/temporal/approve/p/5                   # the same file, from the approval dialog
    500 {"detail": "could not approve_prod: Expecting property name enclosed in double quotes: …"}

#211 made `approvals.source()` the one answer to "where do this deployment's approvers come from"
and taught it to say, by name, that `OPENFACTORY_APPROVERS` cannot be read. The FILE half kept
`json.loads(path.read_text())` with nothing around it, so every reader and both writers answered a
corrupt file with Python's own exception — and a JSON array was LISTED as a roster. One level down,
no store checked its entries: a login mapped to `5` was a 500 in the dialog, one mapped to `null`
was "bad password" for ever, and `approver list` called both of them approvers.

THE DIRECTION OF FAILURE IS THE CONTRACT, so each case below states it: nobody is authorized from
what cannot be read; no write replaces a file it could not read; one malformed entry costs only
itself; and no sentence anywhere repeats a value, because the values are the hashes.

Real files under a temp HOME (the store's DEFAULT path, not the override), the real typer app, the
real `verify_approver`, the real routes under `TestClient`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from openfactory import approvals
from openfactory.cli import app

VARIABLE = "OPENFACTORY_APPROVERS"

ANA = approvals.hash_password("a-password")
BIA = approvals.hash_password("b-password")
GOOD = json.dumps({"ana": ANA, "bia": BIA}, indent=2, sort_keys=True)

#: Every piece of hash material a case plants. None of it may reach a terminal, a log line or the
#: approval dialog — checked by `_no_hash_in`, over whole outputs rather than chosen sentences.
_MATERIAL = [part for stored in (ANA, BIA) for part in stored.split("$")[1:]]


def _no_hash_in(*texts: str) -> None:
    for text in texts:
        for part in _MATERIAL:
            assert part not in text and part[:24] not in text, "hash material reached an output"


# ── what a FILE can be that is not `{login: hash}` ──────────────────────────────────────────────

def _cut_short(path):          # a good store that lost its tail — the hashes are still in it
    path.write_text(GOOD[:-20])


def _empty(path):              # what a `write_text` cut short leaves behind
    path.write_text("")


def _an_array(path):
    path.write_text(json.dumps(["ana", "bia"]))


def _null(path):
    path.write_text("null")


def _mode_000(path):
    path.write_text(GOOD)
    path.chmod(0)


def _not_text(path):
    path.write_bytes(b"\xff\xfe" + GOOD.encode("utf-16-le"))


CORRUPT = {"cut short": _cut_short, "empty": _empty, "a JSON array": _an_array,
           "JSON null": _null, "mode 000": _mode_000, "not UTF-8": _not_text}

#: What one ENTRY can be that is not a hash. `bia`, beside it, is always good.
MALFORMED = {
    "null": None,
    "a number": 5,
    "zero": 0,
    "true": True,
    "an object holding a real hash": {"hash": ANA},
    "an array holding a real hash": [ANA],
    "a scrypt string cut after the salt": "scrypt$abcd",
    "a scrypt string whose salt is not hex": "scrypt$zz$" + "0" * 64,
    "a scrypt string whose hash lost its tail": ANA[:-10],
    "a scrypt string with a fourth field": ANA + "$",
    "a non-ASCII string": "señal",
    "an empty string": "",
    "an upper-case digest, which no compare can match":
        hashlib.sha256(b"a-password").hexdigest().upper(),
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    """The store's DEFAULT path under a temp HOME: `~/.openfactory/approvers.json`."""
    if os.geteuid() == 0:  # root reads a mode-000 file, so half of this file would prove nothing
        pytest.skip("root is not refused by file permissions")
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in (VARIABLE, "OPENFACTORY_APPROVERS_FILE", "OPENFACTORY_PROD_APPROVERS",
                 "OPENFACTORY_PANEL_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".openfactory" / "approvers.json"
    path.parent.mkdir()
    assert approvals.source().path == path, "the guard must drive the real default path"
    yield path
    if path.exists():
        path.chmod(0o600)


@pytest.fixture(params=sorted(CORRUPT))
def corrupt(request, store):
    CORRUPT[request.param](store)
    return store


def _bytes(path) -> tuple[bytes, int]:
    """The file's content AND its mode — a refused write changes neither."""
    mode = path.stat().st_mode
    path.chmod(0o600)
    try:
        return path.read_bytes(), mode
    finally:
        path.chmod(mode & 0o7777)


@pytest.fixture(params=["file", "variable"])
def entries(request, store, monkeypatch):
    """`put({...})` writes the entries into the store in force — the file, or the variable."""
    def put(mapping: dict) -> str:
        if request.param == "file":
            store.write_text(json.dumps(mapping))
        else:
            monkeypatch.setenv(VARIABLE, json.dumps(mapping))
        return request.param
    return put


def _cli(*argv: str, input: str | None = None):
    out = CliRunner().invoke(app, ["approver", *argv], input=input)
    assert out.exception is None or isinstance(out.exception, SystemExit), repr(out.exception)
    assert "Traceback" not in out.output
    return out


def _flat(text: str) -> str:
    return " ".join(text.split())


# ── the question: the file answers the way the variable already does ────────────────────────────

def test_a_file_that_cannot_be_read_is_in_force_names_nobody_and_says_why(corrupt):
    src = approvals.source()
    assert src.variable is False and src.path == corrupt
    assert src.logins == {}
    assert src.problem, "a store that yields nobody for a reason must carry the reason"
    assert str(corrupt) in src.unreadable
    _no_hash_in(src.problem, src.unreadable, repr(src))


def test_each_way_a_file_cannot_be_read_is_told_apart(store):
    said = {}
    for what, write in CORRUPT.items():
        if store.exists():
            store.chmod(0o600)
            store.unlink()
        write(store)
        said[what] = approvals.source().problem
    assert len(set(said.values())) == len(CORRUPT), said
    assert "not JSON" in said["cut short"] and "line" in said["cut short"]
    assert "empty" in said["empty"]
    assert "array" in said["a JSON array"] and "null" in said["JSON null"]
    assert "Permission denied" in said["mode 000"]
    assert "UTF-8" in said["not UTF-8"]


def test_no_file_at_all_is_an_empty_store_not_a_broken_one(store):
    src = approvals.source()
    assert (src.logins, src.problem, src.malformed) == ({}, "", {})
    out = _cli("list")
    assert out.exit_code == 0 and "openfactory approver add" in out.stderr


def test_a_directory_nobody_may_enter_is_not_taken_for_an_empty_store(store):
    """`path.exists()` answers False for a file it may not look at, and an unreadable store read
    as "nobody yet" is the quiet version of the defect."""
    store.write_text(GOOD)
    store.parent.chmod(0)
    try:
        src = approvals.source()
        assert src.logins == {} and "Permission denied" in src.problem
    finally:
        store.parent.chmod(0o700)


def test_the_answer_does_not_print_its_hashes(store):
    store.write_text(json.dumps({"ana": ANA, "bia": {"hash": BIA}}))
    _no_hash_in(repr(approvals.source()), str(approvals.source()))


# ── nobody is authorized from what cannot be read ───────────────────────────────────────────────

def test_a_file_that_cannot_be_read_authorizes_nobody(corrupt):
    assert approvals.verify_approver("ana", "a-password", ["ana", "bia"]) is False
    assert approvals.list_approvers() == []


@pytest.mark.parametrize("what", sorted(MALFORMED))
def test_a_malformed_entry_never_verifies_and_costs_only_itself(entries, what):
    value = MALFORMED[what]
    entries({"ana": value, "bia": BIA})
    for guess in ("a-password", "", str(value), json.dumps(value)):
        assert approvals.verify_approver("ana", guess, ["ana", "bia"]) is False
    assert approvals.verify_approver("bia", "b-password", ["ana", "bia"]) is True
    assert approvals.list_approvers() == ["bia"]


@pytest.mark.parametrize("what", sorted(MALFORMED))
def test_the_compare_itself_refuses_what_is_not_a_hash(what):
    """`identity/people.py` hands it `person.password_hash`: the second caller gets the rule too."""
    assert approvals._password_matches("a-password", MALFORMED[what]) is False


def test_what_the_store_writes_and_the_legacy_digest_still_verify(entries):
    legacy = hashlib.sha256(b"old-password").hexdigest()
    entries({"ana": ANA, "old": legacy})
    assert approvals.source().malformed == {}
    assert approvals.verify_approver("ana", "a-password", ["ana", "old"]) is True
    assert approvals.verify_approver("old", "old-password", ["ana", "old"]) is True
    assert approvals.verify_approver("old", "a-password", ["ana", "old"]) is False


@pytest.mark.parametrize("what", sorted(MALFORMED))
def test_a_malformed_entry_is_named_by_login_and_kind_never_by_value(entries, what):
    value = MALFORMED[what]
    entries({"ana": value, "bia": BIA})
    src = approvals.source()
    assert sorted(src.malformed) == ["ana"] and sorted(src.logins) == ["bia"]
    assert src.problem == "", "one bad entry is not an unreadable store"
    assert "`ana`" in src.unusable and "bia" not in src.unusable
    if isinstance(value, str) and value:
        assert value not in src.unusable and value not in src.malformed["ana"]
    _no_hash_in(src.unusable, src.malformed["ana"], repr(src))


def test_the_kinds_are_told_apart(entries):
    entries({"a": None, "b": 5, "c": {"hash": ANA}, "d": "scrypt$abcd", "e": "hunter2"})
    kinds = approvals.source().malformed
    assert len(set(kinds.values())) == 5, kinds
    assert "null" in kinds["a"] and "number" in kinds["b"] and "object" in kinds["c"]
    assert "scrypt$" in kinds["d"]


def test_a_login_that_is_itself_a_hash_is_not_printed(entries):
    """Keys and values swapped by hand: the LOGIN is now where the hash lives."""
    entries({ANA: "ana", "bia": BIA})
    src = approvals.source()
    assert list(src.malformed) == [ANA]
    out = _cli("list")
    assert out.stdout == "bia\n"
    _no_hash_in(src.unusable, out.output)


# ── approver list ───────────────────────────────────────────────────────────────────────────────

def test_list_says_the_file_cannot_be_read_instead_of_a_traceback_or_a_roster(corrupt):
    out = _cli("list")
    assert out.exit_code == 2, out.output
    assert out.stdout == "", "a JSON array was listed as a roster"
    said = _flat(out.stderr)
    assert str(corrupt) in said and approvals.source().problem in said
    assert "NO approvers" in said and "openfactory approver add" in said
    _no_hash_in(out.output)


@pytest.mark.parametrize("what", sorted(MALFORMED))
def test_list_names_the_entry_that_cannot_be_used_and_does_not_list_it(entries, what):
    where = entries({"ana": MALFORMED[what], "bia": BIA})
    out = _cli("list")
    assert out.exit_code == 0, out.output
    assert out.stdout == "bia\n"
    said = _flat(out.stderr)
    assert "`ana`" in said and approvals.source().malformed["ana"] in said
    assert ("openfactory approver add" in said) if where == "file" else (VARIABLE in said)
    _no_hash_in(out.output)


def test_a_roster_with_nobody_usable_in_it_does_not_exit_0(entries):
    entries({"ana": None, "bia": 5})
    out = _cli("list")
    assert out.exit_code == 2, out.output
    assert out.stdout == ""
    assert "`ana`" in out.stderr and "`bia`" in out.stderr


# ── approver add / remove: a write never replaces a file it could not read ──────────────────────

def test_add_refuses_a_file_it_cannot_read_before_any_prompt_and_leaves_it_as_it_was(corrupt):
    before = _bytes(corrupt)
    out = _cli("add", "carla")                           # no input: a prompt would abort
    assert out.exit_code == 2, out.output
    said = _flat(out.output)
    assert "password for" not in said and "Aborted" not in said
    assert "'carla' was not saved" in said
    assert str(corrupt) in said and approvals.source().problem in said
    assert _bytes(corrupt) == before
    assert sorted(p.name for p in corrupt.parent.iterdir()) == ["approvers.json"]
    _no_hash_in(out.output)


def test_remove_refuses_a_file_it_cannot_read_and_leaves_it_as_it_was(corrupt):
    before = _bytes(corrupt)
    out = _cli("remove", "ana")
    assert out.exit_code == 2, out.output
    said = _flat(out.output)
    assert "was not removed" in said and str(corrupt) in said
    assert approvals.source().problem in said
    assert _bytes(corrupt) == before
    _no_hash_in(out.output)


def test_the_store_itself_refuses_both_writes_for_the_caller_that_is_not_the_cli(corrupt):
    before = _bytes(corrupt)
    with pytest.raises(approvals.StoreCannotBeRead) as refusal:
        approvals.add_approver("carla", "c-password")
    assert str(corrupt) in str(refusal.value)
    with pytest.raises(approvals.StoreCannotBeRead):
        approvals.remove_approver("ana")
    assert _bytes(corrupt) == before


def test_the_way_to_start_the_store_over_is_the_one_the_refusal_prints(store):
    """The remedy, RUN: the move the sentence spells, then the verb it names."""
    _cut_short(store)
    before = store.read_bytes()
    said = _flat(_cli("add", "carla").output)
    move = re.search(r"`mv (\S+) (\S+)`", said)
    assert move and move.group(1) == str(store), said
    os.rename(move.group(1), move.group(2))
    out = _cli("add", "carla", input="c-password\nc-password\n")
    assert out.exit_code == 0, out.output
    assert approvals.verify_approver("carla", "c-password", ["carla"]) is True
    assert open(move.group(2), "rb").read() == before, "the broken file is kept, not repaired over"


def test_adding_somebody_else_leaves_a_malformed_entry_exactly_as_stored(store):
    """A write changes the one login it names. `{"hash": "scrypt$…"}` is a thing a person can
    still repair by hand — unless adding `carla` has thrown it away."""
    stored = {"ana": {"hash": ANA}, "bia": BIA, "dan": None}
    store.write_text(json.dumps(stored))
    out = _cli("add", "carla", input="c-password\nc-password\n")
    assert out.exit_code == 0, out.output
    after = json.loads(store.read_text())
    assert {k: after[k] for k in stored} == stored and sorted(after) == ["ana", "bia", "carla", "dan"]
    assert "`ana`" in out.stderr and "`dan`" in out.stderr, "saved, and two are still unusable"
    _no_hash_in(out.output)


def test_adding_the_login_again_is_the_cure_for_its_entry(store):
    store.write_text(json.dumps({"ana": "scrypt$abcd", "bia": BIA}))
    out = _cli("add", "ana", input="new-password\nnew-password\n")
    assert out.exit_code == 0, out.output
    assert approvals.source().malformed == {}
    assert approvals.verify_approver("ana", "new-password", ["ana"]) is True
    assert "cannot be used" not in out.stderr


def test_a_malformed_entry_can_be_removed_and_the_rest_stay(store):
    store.write_text(json.dumps({"ana": 5, "bia": BIA, "dan": None}))
    out = _cli("remove", "ana")
    assert out.exit_code == 0, out.output
    assert json.loads(store.read_text()) == {"bia": BIA, "dan": None}


def test_a_malformed_entry_the_variable_holds_is_still_named_by_the_variable(store, monkeypatch):
    monkeypatch.setenv(VARIABLE, json.dumps({"ana": 5, "bia": BIA}))
    out = _cli("remove", "ana")
    assert out.exit_code == 2, out.output
    assert "names them" in out.output and "no approver named" not in out.output


# ── the release gate and the dialog's prefetch ──────────────────────────────────────────────────

@pytest.fixture
def panel(store, tmp_path, monkeypatch):
    """The real routes over a registered project with no checkout (the deployed shape, where the
    store's own logins are the allowlist), an engine that records the signal instead of dialing,
    and a forge that answers the one thing the prefetch asks of it."""
    import openfactory.adapters.forge.registry as forge_registry
    from openfactory.api import app as app_module
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import view as tv

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    ProjectRegistry().add(Project(name="p", repo_path=str(tmp_path / "no-checkout"),
                                  tracker=ProviderRef(kind="github", repo="o/p")))
    signals: list[str] = []

    async def connect():
        return object()

    async def approve_job(client, project, issue, **kw):
        signals.append(kw["approver"])

    class _Forge:
        def latest_tag(self):
            return "v1.4.0"

    monkeypatch.setattr(tv, "connect", connect)
    monkeypatch.setattr(tv, "approve_job", approve_job)
    monkeypatch.setattr(forge_registry, "build_forge", lambda p, token=None: _Forge())
    client = TestClient(app_module.app, raise_server_exceptions=False)

    class Panel:
        signalled = signals

        @staticmethod
        def approve(login: str, password: str):
            return client.post("/api/temporal/approve/p/5",
                               json={"approver": login, "password": password, "version": "1.2.0"})

        @staticmethod
        def prefetch():
            return client.get("/api/promote/p/5")
    return Panel


def test_the_gate_answers_a_file_it_cannot_read_with_503_and_the_reason(corrupt, panel, caplog):
    r = panel.approve("ana", "a-password")
    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert str(corrupt) in detail and approvals.source().problem in detail
    assert "could not approve_prod" not in detail
    assert "OPENFACTORY_APPROVER_STORE_MISSING" in caplog.text
    assert "openfactory approver add" in _flat(caplog.text), "the log line carries the remedy"
    assert "Traceback" not in caplog.text
    assert panel.signalled == []
    _no_hash_in(r.text, caplog.text)


def test_the_gate_does_not_call_a_file_it_cannot_read_a_missing_secret(corrupt, panel):
    detail = panel.approve("ana", "a-password").json()["detail"]
    assert "until the OPENFACTORY_APPROVERS secret is provisioned" not in detail


def test_the_dialog_still_opens_over_a_file_that_cannot_be_read(corrupt, panel):
    r = panel.prefetch()
    assert r.status_code == 200, r.text
    assert r.json()["approvers"] == [] and r.json()["latest_tag"] == "v1.4.0"


@pytest.mark.parametrize("what", sorted(MALFORMED))
def test_the_gate_tells_the_person_whose_entry_is_malformed_that_no_password_can_work(
        entries, panel, caplog, what):
    """It was a 500 carrying `'int' object has no attribute 'startswith'`, or — for `null`, `0`,
    `""` and a hash that lost its tail — a 403 "bad password", whatever she typed, for ever."""
    value = MALFORMED[what]
    entries({"ana": value, "bia": BIA})
    r = panel.approve("ana", "a-password")
    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert "'ana'" in detail and approvals.source().malformed["ana"] in detail
    assert "bad password" not in detail and "could not approve_prod" not in detail
    assert "OPENFACTORY_APPROVER_ENTRY_MALFORMED" in caplog.text
    if isinstance(value, str) and value:
        assert value not in r.text and value not in caplog.text
    assert panel.signalled == []
    _no_hash_in(r.text, caplog.text)


def test_the_other_logins_keep_approving_beside_a_malformed_entry(entries, panel):
    entries({"ana": {"hash": ANA}, "bia": BIA})
    assert panel.approve("bia", "wrong").status_code == 403       # a typo is still a typo
    assert panel.signalled == []
    assert panel.approve("bia", "b-password").status_code == 200
    assert panel.signalled == ["bia"]
    assert panel.prefetch().json()["approvers"] == ["bia"]


def test_a_store_whose_every_entry_is_malformed_is_not_called_missing(entries, panel, caplog):
    where = entries({"ana": None, "bia": 5})
    r = panel.approve("carla", "c-password")
    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert "`ana`" in detail and "`bia`" in detail
    assert "secret is provisioned" not in detail and "names nobody," not in detail
    assert "OPENFACTORY_APPROVER_STORE_MISSING" in caplog.text
    assert (VARIABLE in detail) if where == "variable" else (VARIABLE not in detail)


def test_the_synchronous_release_asks_the_same_question(store, monkeypatch):
    """`promote` is the gate's other door (the local path, no engine): same refusal, by name."""
    import asyncio

    from openfactory import actions
    from openfactory.actions import catalog

    class _Manifest:
        prod_approvers = ["ana"]

    store.write_text(json.dumps({"ana": "scrypt$abcd", "bia": BIA}))
    monkeypatch.setattr(catalog, "_forge_and_manifest", lambda name: (object(), _Manifest(), object()))
    out = asyncio.run(actions.perform("promote", by=actions.SYSTEM, project="p", issue="5",
                                      version="1.2.0", approver="ana", password="a-password"))
    assert out.code == actions.UNAVAILABLE, out
    assert "'ana'" in out.message and "scrypt$abcd" not in out.message
