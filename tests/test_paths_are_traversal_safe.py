"""A ticket ref can never escape the journal directory (C-06a).

`events_file` interpolates a ref straight into a filename, and the only thing standing between
that and a path traversal is a regex at the API door whose docstring says so out loud:

    _ISSUE_RE = re.compile(r"^#?\\d+$")
    "reject anything else so it can never become a path component / traversal"

That guard is load-bearing, and C-06 exists to REMOVE it — a Jira ref is `CONT-412`, which the
regex refuses. Relaxing the door before hardening the floor would turn a documented defence into a
directory-traversal regression on an authenticated-but-internet-reachable endpoint. So the floor
goes first, and this file is the reason the door can move afterwards.

TWO PROPERTIES, and the second is the one that is easy to lose while fixing the first:

    it cannot escape        no input produces a path outside the project's log directory
    it stays injective      two different refs never collide onto one journal

A sanitiser that maps every unsafe character to `_` satisfies the first and quietly breaks the
second: `a/b` and `a_b` become the same file, and one job starts reading another's events.
"""

from __future__ import annotations

import pytest

from openfactory.contracts.project import Project
from openfactory.paths import events_file, project_log_dir


def _project(tmp_path) -> Project:
    (tmp_path / "repo").mkdir(exist_ok=True)
    return Project(name="demo", repo_path=str(tmp_path / "repo"))


# ── backward compatibility comes first: journals already on disk must keep their names ──────────

@pytest.mark.parametrize("ref,expected", [
    ("412", "412-events.jsonl"),
    ("#412", "412-events.jsonl"),        # the '#' has always been stripped
    ("CONT-412", "CONT-412-events.jsonl"),  # a Jira ref is already safe and must pass through
    ("1234", "1234-events.jsonl"),        # an Azure DevOps work item
])
def test_a_wholesome_ref_keeps_the_name_it_always_had(tmp_path, ref, expected):
    """Every journal on disk today is `<number>-events.jsonl`. A sanitiser that renamed those
    would orphan the panel's history for every job ever run."""
    assert events_file(_project(tmp_path), ref).name == expected


# ── it cannot escape ────────────────────────────────────────────────────────────────────────────

ESCAPES = [
    "../../../etc/passwd",
    "..",
    ".",
    "../",
    "a/../../b",
    "/etc/passwd",
    "//etc/passwd",
    "\\..\\..\\windows",
    "C:\\windows\\system32",
    "sub/dir",
    "~",
    "~/.ssh/id_rsa",
    "\x00",
    "foo\x00.jsonl",
    "....//....//etc",
    " ",
    "",
    "#",
    "\n../x",
    "%2e%2e%2fetc",   # already url-decoded by the time it reaches here; must still be inert
]


@pytest.mark.parametrize("ref", ESCAPES)
def test_no_ref_can_point_outside_the_projects_log_directory(tmp_path, ref):
    project = _project(tmp_path)
    root = project_log_dir(project).resolve()
    path = events_file(project, ref).resolve()
    assert path.parent == root, f"{ref!r} escaped to {path}"


@pytest.mark.parametrize("ref", ESCAPES)
def test_no_ref_produces_a_path_component(tmp_path, ref):
    """One directory up is the obvious attack; one directory DOWN is the quiet one — it still
    escapes the flat namespace the reader assumes, and it fails as a mkdir error much later."""
    name = events_file(_project(tmp_path), ref).name
    assert "/" not in name and "\\" not in name
    assert not name.startswith(".")  # `.hidden` and `..` both start here


@pytest.mark.parametrize("ref", ESCAPES)
def test_every_ref_still_produces_a_usable_journal_name(tmp_path, ref):
    """Refusing is not an option at this layer: `events_file` has no way to report one, and a
    job whose journal path raised would die for a filename. It must always produce something
    safe."""
    name = events_file(_project(tmp_path), ref).name
    assert name.endswith("-events.jsonl")
    assert len(name) > len("-events.jsonl")
    assert "\x00" not in name


def test_a_sanitised_ref_can_actually_be_written(tmp_path):
    project = _project(tmp_path)
    path = events_file(project, "../../../etc/passwd")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n")
    assert path.read_text() == "{}\n"


# ── it stays injective ──────────────────────────────────────────────────────────────────────────

def test_two_different_refs_never_share_a_journal(tmp_path):
    """The trap in every naive sanitiser. `a/b` -> `a_b` and `a_b` -> `a_b` is a collision, and a
    collision here means one job reads another job's events with nothing anywhere reporting it."""
    project = _project(tmp_path)
    refs = ["a/b", "a_b", "a\\b", "a b", "../b", "a/../b", "A/B", "a:b", "a|b"]
    names = [events_file(project, r).name for r in refs]
    assert len(set(names)) == len(names), sorted(names)


def test_the_same_ref_always_maps_to_the_same_journal(tmp_path):
    """Stability is not decorative: the writer is the box and the reader is the panel, in
    different processes and often different machines. A name derived from anything but the ref
    would leave the panel tailing a file nobody writes."""
    project = _project(tmp_path)
    assert events_file(project, "CONT-1").name == events_file(project, "CONT-1").name
    assert events_file(project, "../x").name == events_file(project, "../x").name


def test_case_is_preserved_because_a_provider_may_be_case_sensitive(tmp_path):
    project = _project(tmp_path)
    assert events_file(project, "conT-1").name != events_file(project, "CONT-1").name


# ── the filesystem has limits of its own ────────────────────────────────────────────────────────

def test_an_absurdly_long_ref_still_fits_a_filename(tmp_path):
    """255 bytes is the common limit. A ref longer than that is not an attack, it is a bug
    upstream — but it must fail as a truncated name, not as an OSError halfway through a job."""
    project = _project(tmp_path)
    path = events_file(project, "X" * 5000)
    assert len(path.name.encode()) <= 255
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ok")


def test_two_absurdly_long_refs_do_not_collide_after_truncation(tmp_path):
    project = _project(tmp_path)
    a = events_file(project, "X" * 5000 + "a").name
    b = events_file(project, "X" * 5000 + "b").name
    assert a != b
