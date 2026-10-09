"""`doctor --json` is a public contract, and its shape is pinned here rather than remembered (#356).

WHO READS IT. `openfactory certify deployment` puts this document into an evidence pack that a bot
validates offline, and an operator's own scripts read it to decide whether a project can run a
ticket. Both readers exist the moment it ships — so, like `preflight --json` before it
(`test_preflight_json_is_the_document_the_agent_lane_reads.py`, the guard this one is modelled
on), it carries its version from the first commit and its keys are pinned by EQUALITY.

WHAT MUST SURVIVE SERIALISATION, and it is the doctor's whole vocabulary: a red line that a step
AHEAD answers (`awaiting`, `not_yet`) is not a broken deployment, and the closing verdict says
which one this is. A document that dropped either distinction would tell its reader "broken" about
a project at ONBOARDING §2 — the exact sentence the EXPECTED verdict was written to stop.

AND ONE RULE, NOT TWO. The verdict was decided inline in `cli.py`; it now lives in
`doctor.verdict`, and the text report and the document both read it. The guards at the bottom run
the SAME probe set through both and require them to agree, line for line.
"""

from __future__ import annotations

import json

import pytest

from openfactory import doctor
from tests.pinned_probes import a_fully_pinned_probe_set

#: The keys the document promises. EQUALITY, NOT CONTAINMENT: a key silently added is a key some
#: reader starts depending on before anybody decided it was part of the contract, and a key removed
#: breaks every reader at once. Either is a schema change, and a schema change moves `SCHEMA`.
DOCUMENT_KEYS = {"schema", "project", "ok", "verdict", "next_step", "build", "checks"}
CHECK_KEYS = {"id", "result", "detail", "remedy", "next_step", "note", "awaiting", "not_yet"}

NEVER_PROVEN = "the box has never been proven — run `openfactory box prove demo`"


def _no_manifest():
    raise FileNotFoundError("no manifest here")


def _document(**over) -> dict:
    report = doctor.diagnose(a_fully_pinned_probe_set(**over))
    return json.loads(doctor.as_json(doctor.as_document(report, project="demo")))


def _registered(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(app, ["project", "add", "demo", str(tmp_path)]).exit_code == 0
    return CliRunner()


# ── the shape ───────────────────────────────────────────────────────────────────────────────────

def test_the_document_carries_exactly_the_promised_keys():
    document = _document()

    assert set(document) == DOCUMENT_KEYS, (
        f"the document's keys are {sorted(document)}; the contract is {sorted(DOCUMENT_KEYS)}. "
        f"Either way this is a schema change and `doctor.SCHEMA` has to move with it.")


def test_it_says_which_version_of_itself_it_is():
    document = _document()

    assert document["schema"] == doctor.SCHEMA == "openfactory.doctor/1"


def test_every_check_carries_exactly_the_promised_fields():
    document = _document(docker_running=lambda: (False, "the daemon did not answer"))

    assert document["checks"], "no checks in the document — the contract has no subject"
    for check in document["checks"]:
        assert set(check) == CHECK_KEYS, (
            f"{check.get('id')!r} serialises {sorted(check)}; the contract is {sorted(CHECK_KEYS)}")
        assert check["result"] in doctor.RESULTS, check


def test_the_passes_are_in_it_too_and_not_only_the_failures():
    """A document of failures alone lets its reader propose a step that has been taken."""
    document = _document(docker_running=lambda: (False, "the daemon did not answer"))
    results = {c["id"]: c["result"] for c in document["checks"]}

    assert "ok" in results.values() and "fail" in results.values(), results
    assert results["docker"] == "fail"


def test_a_failing_check_carries_the_remedy_its_reader_is_supposed_to_follow():
    document = _document(docker_running=lambda: (False, "the daemon did not answer"))
    docker = next(c for c in document["checks"] if c["id"] == "docker")

    assert docker["result"] == "fail"
    assert docker["remedy"].strip(), "a failing check reached the document with no remedy"


def test_a_line_a_later_step_answers_keeps_its_attribution():
    """`awaiting` and `not_yet` are what separate "broken" from "not written yet"; a document that
    dropped them would read every §2 project as a defect."""
    document = _document(manifest=_no_manifest, box_gate=lambda: NEVER_PROVEN)
    by_id = {c["id"]: c for c in document["checks"]}

    assert by_id["quality_floor"]["awaiting"] == "manifest", by_id["quality_floor"]
    assert document["verdict"] == "expected", document["verdict"]
    assert document["next_step"].strip(), "an EXPECTED verdict that names no next step"


def test_the_verdict_and_the_ok_flag_agree_with_the_checks():
    for over in ({}, {"docker_running": lambda: (False, "down")},
                 {"manifest": _no_manifest, "box_gate": lambda: NEVER_PROVEN}):
        document = _document(**over)
        failed = [c for c in document["checks"] if c["result"] == "fail"]

        assert document["ok"] == (not failed), document
        assert (document["verdict"] == "ok") == (not failed), document["verdict"]
        assert document["verdict"] in doctor.VERDICTS


def test_the_keys_are_stable_between_two_runs_of_the_same_deployment():
    first = doctor.as_json(doctor.as_document(doctor.diagnose(a_fully_pinned_probe_set()),
                                              project="demo"))
    second = doctor.as_json(doctor.as_document(doctor.diagnose(a_fully_pinned_probe_set()),
                                               project="demo"))

    assert first == second
    assert first.index('"checks"') < first.index('"verdict"'), "the keys are not sorted"


def test_the_build_is_null_outside_a_built_image_and_carried_inside_one():
    report = doctor.diagnose(a_fully_pinned_probe_set())

    assert doctor.as_document(report, project="demo")["build"] is None
    assert doctor.as_document(report, project="demo", build=("abc123", "2026-10-05"))["build"] \
        == {"code": "abc123", "built": "2026-10-05"}


# ── the command, and the one rule both renderings read ──────────────────────────────────────────

@pytest.mark.parametrize("over", [
    {},
    {"docker_running": lambda: (False, "the daemon did not answer")},
    {"manifest": _no_manifest, "box_gate": lambda: NEVER_PROVEN},
], ids=["green", "broken", "expected"])
def test_the_document_and_the_screen_say_the_same_thing(tmp_path, monkeypatch, over):
    """TWO RENDERINGS OF ONE REPORT. Every line the screen marks `ok`/`FAIL` is in the document
    with the same result, and the closing sentence is the verdict the document names — so a
    reader of either is told the same thing about the same deployment."""
    from openfactory.cli import app

    runner = _registered(tmp_path, monkeypatch)
    monkeypatch.setattr(doctor, "probes_for", lambda _p: a_fully_pinned_probe_set(**over))

    text = runner.invoke(app, ["doctor", "demo"])
    as_json = runner.invoke(app, ["doctor", "demo", "--json"])
    document = json.loads(as_json.stdout)

    assert as_json.exit_code == text.exit_code == (0 if document["ok"] else 1)
    for check in document["checks"]:
        mark = "  ok  " if check["result"] == "ok" else " FAIL "
        assert f"{mark} {check['id']:<14} {check['detail']}" in text.output, check["id"]
    sentence = {"ok": "\nOK — 'demo' can run a ticket",
                "expected": "that is EXPECTED",
                "not_ready": "\nNOT ready — fix the FAIL lines above"}[document["verdict"]]
    assert sentence in text.output, (document["verdict"], text.output[-400:])
    if document["verdict"] == "expected":
        assert f"Next: {document['next_step']}." in text.output


def test_json_mode_prints_the_document_and_nothing_else(tmp_path, monkeypatch):
    """A reader parses the WHOLE stream. One banner line above the document — the build, the
    notifier fallback, the gate key — is a document that does not parse."""
    from openfactory import namespace
    from openfactory.cli import app

    runner = _registered(tmp_path, monkeypatch)
    monkeypatch.setattr(doctor, "probes_for", lambda _p: a_fully_pinned_probe_set())
    monkeypatch.setattr(namespace, "build_stamp", lambda: ("abc123", "2026-10-05T10:00"))

    result = runner.invoke(app, ["doctor", "demo", "--json"])

    document = json.loads(result.stdout)
    assert document["build"] == {"code": "abc123", "built": "2026-10-05T10:00"}
    assert document["project"] == "demo"
