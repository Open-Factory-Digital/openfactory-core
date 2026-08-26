"""A ticket ref that is not a number gets through the door and back out again (C-06).

`api/app.py` refused anything but `^#?\\d+$`, which rejects `CONT-412` at the API and makes a Jira
deployment unusable from the panel. The regex was not arbitrary — its docstring says it exists so a
ref "can never become a path component / traversal" — so C-06a hardened `paths.py` first and this
card relaxes the door on top of that.

RELAXING THE DOOR IS HALF THE CARD. A ref also becomes part of a Temporal workflow id:

    job_id("demo", "CONT-412")  ->  "openfactory-demo-CONT-412"
    parse_job_id(...)           ->  rpartition("-")  ->  ("demo-CONT", "412")

Wrong, silently. The panel would show the job under a project that does not exist, the tech-lead
would not find it, and nothing would raise. Today it happens to work only because every ref is
numeric — the bug is latent, and accepting Jira refs is what fires it.

It works for `acme-books` by luck too: `rpartition` splits at the LAST hyphen, so a hyphenated
PROJECT is fine and a hyphenated REF is not. That is a coincidence, not a design, and the round-trip
property below is what replaces it.
"""

from __future__ import annotations

import pytest

from openfactory.runtime.temporal.view import job_id, parse_job_id

REFS = ["189", "#189", "CONT-412", "PROJ-1", "1234", "AB-9999", "a1"]
PROJECTS = ["demo", "acme-books", "a-b-c"]


@pytest.mark.parametrize("project", PROJECTS)
@pytest.mark.parametrize("ref", REFS)
def test_a_job_id_round_trips_whatever_the_provider_calls_a_ticket(project, ref):
    """The property that replaces the coincidence. Anything `job_id` builds, `parse_job_id` must
    take apart into exactly the same two pieces."""
    assert parse_job_id(job_id(project, ref), known_projects=PROJECTS) == (project, ref)


def test_a_jira_ref_no_longer_splits_the_project_name():
    """The specific regression, named so it cannot come back quietly."""
    assert parse_job_id("openfactory-demo-CONT-412", known_projects=["demo"]) == ("demo", "CONT-412")


def test_ids_minted_before_this_change_still_parse():
    """Every workflow id ever created is numeric-tailed and lives in Temporal's history. A parser
    that only understood the new shape would lose sight of every in-flight job on deploy."""
    assert parse_job_id("openfactory-books-189", known_projects=["books"]) == ("books", "189")


def test_an_unregistered_project_still_parses_as_it_always_did():
    """Degrade, never refuse: a job for a project since removed from the registry must still show
    up in the panel rather than vanish from it."""
    assert parse_job_id("openfactory-gone-189", known_projects=["demo"]) == ("gone", "189")


def test_the_longest_matching_project_wins():
    """`demo` and `demo-api` can both be registered. Matching the shorter one first would file
    every `demo-api` job under `demo` with a ref of `api-<n>`."""
    got = parse_job_id("openfactory-demo-api-7", known_projects=["demo", "demo-api"])
    assert got == ("demo-api", "7")


def test_a_foreign_workflow_id_is_not_ours():
    assert parse_job_id("poll-books", known_projects=PROJECTS) == (None, None)
    assert parse_job_id("", known_projects=PROJECTS) == (None, None)


def test_known_projects_defaults_to_the_registry(monkeypatch):
    """The caller should not have to know. A default that silently returned nothing would make
    every real caller fall back to the broken split."""
    from openfactory.runtime.temporal import view as temporal_view

    monkeypatch.setattr(temporal_view, "_registered_projects", lambda: ["demo"])
    assert parse_job_id("openfactory-demo-CONT-412") == ("demo", "CONT-412")


def test_a_broken_registry_does_not_break_job_listing(monkeypatch):
    """The panel lists jobs. If reading the registry raises, it must still parse ids the old way
    rather than 500 — the registry is a convenience here, not a dependency."""
    from openfactory.runtime.temporal import view as temporal_view

    def boom():
        raise OSError("registry unreadable")

    monkeypatch.setattr(temporal_view, "_registered_projects", boom)
    assert parse_job_id("openfactory-demo-189") == ("demo", "189")


# ── the door itself ─────────────────────────────────────────────────────────────────────────────
#
# THE DOOR MOVED. It used to be `api/app.py::_valid_issue`, reached only by the panel's two
# job-launch routes. C-23 (#51) put every ref-taking action through `openfactory.actions._clean_ref`
# instead — the panel, Slack and the CLI all pass through it now, which is the door this file
# means when it says "the API" (the action layer being the ONE api every transport calls). The
# grammar and the bound are unchanged; only where they are enforced moved, from one front end to
# the layer underneath all of them.

@pytest.mark.parametrize("ref", ["CONT-412", "189", "#189", "1234", "AB-1"])
def test_the_api_accepts_a_providers_own_ref(ref):
    from openfactory.actions import _clean_ref

    cleaned, problem = _clean_ref(ref)
    assert cleaned and not problem


@pytest.mark.parametrize("ref", [
    "",
    "   ",
    "../../etc/passwd",
    "a/b",
    "a\\b",
    "\x00",
    "with space",
    "x" * 300,
    "#",
])
def test_the_door_still_refuses_what_is_not_a_ref(ref):
    """Relaxed is not open. `paths.py` would now neutralise these, but the action layer is where
    there is somebody to tell — and a refusal naming the problem beats a job that runs against a
    ref no provider will recognise."""
    from openfactory.actions import _clean_ref

    cleaned, problem = _clean_ref(ref)
    assert not cleaned and problem


def test_the_hash_prefix_is_still_stripped():
    """Callers downstream compare refs; `#189` and `189` must not be two different tickets."""
    from openfactory.actions import _clean_ref

    assert _clean_ref("#189") == _clean_ref("189")


def test_a_bad_ref_reaches_the_panel_as_a_400():
    """The end-to-end version: the route itself, through an action that takes an `issue`."""
    from fastapi.testclient import TestClient

    from openfactory.api.app import app

    r = TestClient(app).post("/api/act/skip",
                             json={"params": {"project": "demo", "issue": "../../etc/passwd"}})
    assert r.status_code == 400
