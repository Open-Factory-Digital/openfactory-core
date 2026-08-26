"""Nothing recursively deletes a directory this platform did not create (2026-08-21).

WHAT HAPPENED. `techlead/conversation.py::_answer` and `techlead/diagnosis.py::diagnose` both end
with `finally: shutil.rmtree(tmp, ignore_errors=True)`, where `tmp` arrives from a seam —
`clone_repo` / `_checkout` — documented as handing over a directory the caller now owns. The
product side was right: both always return a `tempfile.mkdtemp(...)`. The CONTRACT was the defect,
because "delete whatever I am given" has no floor.

Three tests stubbed that seam with the literal string `"/tmp"`. So the suite called
`shutil.rmtree("/tmp")` — three times per run, for as long as those tests existed.

WHY NOBODY SAW IT. pytest keeps its temp files under `/private/var/folders/…` on macOS and under
`/tmp` on Linux. On the author's machine the delete destroyed nothing anybody looked at. On CI it
deleted pytest's own basetemp mid-run, and 898 later tests failed at `tmp_path` setup with
`FileNotFoundError: '/tmp/pytest-of-runner/pytest-0'` — a cascade that looked nothing like its
cause and buried five unrelated real failures underneath it. It cost a full day and was found by
naming the culprit with a teardown probe inside a Linux container, not by reading.

`ignore_errors=True` is why it was silent: a recursive delete of the wrong tree cannot fail.

THE PROPERTY, stated so it outlives these two call sites: a recursive delete is allowed only on a
path whose NAME says this platform made it. Everything else is refused, logged, and leaked — one
stray temp directory is a rounding error next to somebody's `/tmp`.
"""

from __future__ import annotations

import ast
import inspect
import tempfile
from pathlib import Path

import pytest

from openfactory.util import scratch

ROOT = Path(__file__).resolve().parent.parent


# ── 1. what counts as ours ──────────────────────────────────────────────────────────────────────

def test_a_directory_we_made_is_ours():
    made = scratch.make("probe")
    try:
        assert scratch.is_ours(made)
        assert made.name.startswith(scratch.PREFIX)
    finally:
        scratch.discard(made)


@pytest.mark.parametrize("hostile", [
    "/tmp",                    # THE one that did the damage
    "/",
    "/var",
    "/Users",
    "/home/runner",
])
def test_a_shared_directory_is_never_ours(hostile):
    assert not scratch.is_ours(hostile), f"{hostile} would be recursively deleted"


def test_the_temp_ROOT_itself_is_refused_even_though_it_is_inside_the_temp_root():
    """The exact shape of the defect. `/tmp` IS the temp directory on Linux, so "is it under the
    temp root" alone answers yes — the prefix is what makes the question meaningful."""
    assert not scratch.is_ours(tempfile.gettempdir())


def test_a_SIBLING_temp_directory_is_not_ours():
    """Somebody else's scratch space is not ours to remove, even next door to ours."""
    other = Path(tempfile.mkdtemp(prefix="somebody-elses-"))
    try:
        assert not scratch.is_ours(other)
    finally:
        import shutil
        shutil.rmtree(other, ignore_errors=True)


def test_the_repository_itself_is_not_ours():
    assert not scratch.is_ours(ROOT), "a checkout must never be deletable by this path"


def test_a_path_that_ESCAPES_upward_is_refused():
    """`<tmp>/openfactory-x/../..` resolves to the temp root. A prefix check on the raw string
    would accept it; the check resolves first, then looks at the top component.

    BUILT FROM THE RESOLVED DIRECTORY ON PURPOSE, and a mutation is why. On macOS
    `tempfile.gettempdir()` answers `/var/folders/…` while `.resolve()` answers
    `/private/var/folders/…`, so a path built from the unresolved one is not lexically under the
    root at all — every cut aimed at the resolve() came back green here for a reason that has
    nothing to do with the property. Starting from the resolved path removes that accident, and
    the guard then measures what it claims on both platforms."""
    made = scratch.make("escape").resolve()
    try:
        assert not scratch.is_ours(made / ".." / "..")
        assert not scratch.is_ours(made / ".." / made.name / ".." / "..")
    finally:
        scratch.discard(made)


# ── 2. what discard actually does ───────────────────────────────────────────────────────────────

def test_discard_removes_a_scratch_directory_and_says_so():
    made = scratch.make("removable")
    (made / "a-file").write_text("x")

    assert scratch.discard(made) is True
    assert not made.exists()


def test_discard_REFUSES_a_shared_directory_and_leaves_it_standing(tmp_path, caplog):
    """The positive twin of the whole file: refusing must be observable, and must not raise —
    these calls live in a `finally` where an exception replaces a real answer with a crash."""
    victim = tmp_path / "not-ours"
    victim.mkdir()
    (victim / "precious").write_text("still here")

    assert scratch.discard(victim) is False
    assert (victim / "precious").read_text() == "still here"
    assert any("refusing to delete" in r.message for r in caplog.records), (
        "it refused in silence — the leak needs to be findable")


def test_discard_of_None_is_not_an_error():
    assert scratch.discard(None) is False


# ── 3. and the two call sites actually use it ───────────────────────────────────────────────────

def test_NO_recursive_delete_in_the_techlead_takes_a_path_from_a_seam():
    """Reachability, read as code. Both functions could import `scratch` and keep the bare rmtree
    beside it — this asserts the rmtree is gone from the functions that receive `tmp` from a seam,
    which is the only place the defect can return."""
    from openfactory.techlead import conversation, diagnosis

    for fn in (conversation._answer, diagnosis.diagnose):
        tree = ast.parse(inspect.getsource(fn).lstrip())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("rmtree")]

        assert not calls, (
            f"{fn.__qualname__} still deletes recursively without asking whose directory it is: "
            f"{[ast.unparse(c) for c in calls]}")

        discards = [n for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("scratch.discard")]
        assert discards, f"{fn.__qualname__} no longer cleans up at all — the leak is back"


def test_and_NO_TEST_hands_a_shared_directory_to_that_seam():
    """The three stubs that caused it, forbidden by name. A test that fakes `clone_repo` decides
    what the product will delete, so the fake has to be a directory the fake owns."""
    offenders = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.split("#")[0]
            if "clone_repo" not in stripped and "_checkout" not in stripped:
                continue
            if '"/tmp"' in stripped or "'/tmp'" in stripped:
                offenders.append(f"{path.name}:{number}")

    assert not offenders, (
        "a test hands the shared /tmp to a seam whose caller deletes it recursively — this is "
        f"exactly the 2026-08-21 defect: {offenders}")
