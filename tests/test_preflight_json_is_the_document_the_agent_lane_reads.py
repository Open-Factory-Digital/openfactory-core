"""`preflight --json` is a public contract, and its shape is pinned here rather than remembered.

WHAT THIS DOCUMENT IS FOR. The installer has two lanes and one truth: the deterministic lane emits
a state document, and the agent lane consumes it. That is what keeps the LLM a reader, an explainer
and a repairer rather than an authority — **it cannot surface a problem the deterministic lane did
not name, so it cannot invent a step**. `install.md` instructs an agent to run
`openfactory preflight --json` and work from the result rather than from its own inspection of the
machine, which means this document's shape is a published interface the moment `install.md` is
served from a domain.

WHY A VERSION FIELD FROM THE FIRST COMMIT. A reader that cannot tell version 1 from version 2 fails
in the least useful way available: by half-understanding a document it believes it understands. The
schema string is cheap now and impossible to add later, because "later" means after readers exist.

WHY EVERY FINDING IS IN IT, INCLUDING THE PASSES. "What is already fine" is half of what stops an
explainer proposing a step that has been taken — and the three-state distinction has to survive
serialisation, because a JSON document that collapses `answered=False` into `ok=True` hands the
agent lane a clean bill of health for a question nobody could ask. That is the defect
`doctor.BoardUnreadable` exists to prevent, one serialisation boundary further out.
"""

from __future__ import annotations

import json

from openfactory import preflight

#: The keys the document promises. EQUALITY, NOT CONTAINMENT: a key silently added is a key some
#: reader starts depending on before anybody decided it was part of the contract, and a key removed
#: breaks every reader at once. Either is a schema change, and a schema change moves `SCHEMA`.
DOCUMENT_KEYS = {"schema", "verdict", "ok", "measured_on", "findings"}
FINDING_KEYS = {"check", "ok", "answered", "message", "remedy", "measured_on"}


def _probes(**overrides) -> preflight.Probes:
    healthy = dict(
        compose=lambda: (True, "v2.29.1"),
        daemon=lambda: (True, "linux/arm64"),
        host_arch=lambda: "arm64",
        port_free=lambda port: True,
        free_disk=lambda: 200 * 1024 ** 3,
        work_dir=lambda: "/home/ana/.local/share/openfactory/work",
        writable_without_root=lambda where: (True, "created and written as this user"),
        image_present=lambda image: True,
        sandbox_image=lambda: "ghcr.io/open-factory-digital/openfactory-sandbox:v1.0.0",
        env_file=lambda: (True, 0o600),
        agent_credential=lambda: (True, "CLAUDE_CODE_OAUTH_TOKEN is set"),
        ports=lambda: (("panel", 8787), ("engine UI", 8080), ("engine", 7233)),
    )
    return preflight.Probes(**{**healthy, **overrides})


def _document(**overrides) -> dict:
    return json.loads(preflight.as_json(preflight.check(_probes(**overrides))))


def test_the_document_is_valid_json_and_carries_exactly_the_promised_keys():
    document = _document()

    assert set(document) == DOCUMENT_KEYS, (
        f"the document's keys are {sorted(document)}; the contract is {sorted(DOCUMENT_KEYS)}. "
        f"Either way this is a schema change and `preflight.SCHEMA` has to move with it.")


def test_it_says_which_version_of_itself_it_is():
    """The field that lets a reader refuse a document it does not understand, instead of
    half-understanding it."""
    document = _document()

    assert document["schema"] == preflight.SCHEMA
    assert document["schema"].endswith("/1"), (
        f"{document['schema']!r} carries no version — a reader cannot tell it from the next one")


def test_every_finding_carries_exactly_the_promised_fields():
    document = _document(env_file=lambda: (False, None))

    assert document["findings"], "no findings in the document — the contract has no subject"
    for finding in document["findings"]:
        assert set(finding) == FINDING_KEYS, (
            f"{finding.get('check')!r} serialises {sorted(finding)}; the contract is "
            f"{sorted(FINDING_KEYS)}")


def test_the_passes_are_in_it_too_and_not_only_the_failures():
    """A document of failures alone would let the agent lane propose a step that has been taken —
    it cannot see that Docker is already running, so "start Docker" stays plausible for ever."""
    document = _document(env_file=lambda: (False, None))
    checks = {f["check"]: f["ok"] for f in document["findings"]}

    assert any(checks.values()) and not all(checks.values()), checks


def test_the_three_states_survive_serialisation():
    """`answered=False` is NOT `ok=True`, and a JSON document that lost the distinction would hand
    the agent lane a clean bill of health for a question nobody was able to ask. Two booleans carry
    three meanings only while both are present."""
    document = _document(image_present=lambda image: None)
    box = next(f for f in document["findings"] if f["check"] == "box_image")

    assert box["answered"] is False, box
    assert box["ok"] is True, "an unanswered check must not serialise as a failure either"
    assert document["ok"] is True, "an unanswered check was counted against the whole report"
    assert "could not be answered" in document["verdict"], document["verdict"]


def test_a_failing_document_carries_the_remedy_the_agent_lane_is_supposed_to_explain():
    """The agent lane's whole job is explaining and repairing what the deterministic lane named. A
    document that carried the failure and dropped the remedy would force the LLM to invent one,
    which is precisely the authority it must not have."""
    document = _document(agent_credential=lambda: (False, "neither variable is set"))
    finding = next(f for f in document["findings"] if f["check"] == "agent_credential")

    assert finding["ok"] is False
    assert finding["remedy"].strip(), "a failing finding reached the document with no remedy"


def test_the_verdict_and_the_ok_flag_agree_with_the_findings():
    """A verdict computed once and carried alongside its evidence can drift from it. Both readers
    of this document — a human and an agent — would then be told two different things by the same
    file, and the shorter one wins every time."""
    for overrides in ({}, {"env_file": lambda: (False, None)},
                      {"image_present": lambda image: None}):
        document = _document(**overrides)
        failed = [f for f in document["findings"] if f["answered"] and not f["ok"]]

        assert document["ok"] == (not failed), document
        assert (document["verdict"].startswith("MISSING")) == bool(failed), document["verdict"]
        if failed:
            assert str(len(failed)) in document["verdict"], document["verdict"]


def test_the_keys_are_stable_between_two_runs_of_the_same_machine():
    """A document a person diffs between two runs must not move its keys for reasons that are not
    about their machine — and an agent that caches one is comparing text."""
    first, second = preflight.as_json(preflight.check(_probes())), \
        preflight.as_json(preflight.check(_probes()))

    assert first == second
    assert first.index('"findings"') < first.index('"measured_on"'), (
        "the keys are not sorted — key order is part of what makes two runs comparable")


def test_a_reader_that_only_knows_this_schema_can_still_be_written():
    """VERIFY THE VERIFIER, by being the reader. Everything the agent lane is told to do — decide
    whether to act, name what is wrong, quote the remedy — has to be possible from this document
    alone, with no access to the machine. If that ever stops being true, the LLM has to inspect the
    machine itself, and the moment it does it can name a problem preflight did not."""
    document = _document(agent_credential=lambda: (False, "neither variable is set"),
                         port_free=lambda port: port != 8787)

    if document["ok"]:
        raise AssertionError("nothing to explain — the fixture stopped being broken")
    problems = [(f["check"], f["remedy"]) for f in document["findings"]
                if f["answered"] and not f["ok"]]

    assert len(problems) == 2, problems
    assert all(remedy for _, remedy in problems)
