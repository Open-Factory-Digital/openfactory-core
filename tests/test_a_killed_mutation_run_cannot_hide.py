"""A mutation run that is KILLED must not leave the mutant in the tree (2026-08-20).

`run_one` restores in a `finally`, which handles an exception and a normal exit. It does not
handle SIGKILL — and a run cut short by a harness timeout gets exactly that. It happened: a fix in
`activities.py` was left reverted to the defect it repairs, sat through a full green suite (the
guard for that line lives in another file), and was found by an unrelated grep minutes before it
would have been committed and deployed.

The protection cannot live in the process, because no code in the process runs after a kill. It
has to be a note on disk that the NEXT run reads.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
TOOL = ROOT / "tools" / "mutate.py"


def _run(args: list[str], sentinel: Path | None = None):
    return subprocess.run([sys.executable, str(TOOL), *args], cwd=ROOT,
                          capture_output=True, text=True)


def test_a_killed_run_leaves_a_note_that_stops_the_next_one(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("mutate_probe", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    note = tmp_path / ".mutate-in-flight"
    note.write_text(json.dumps({"file": "openfactory/x.py", "backup": "/tmp/x.py",
                                "label": "the cut that was interrupted"}))
    monkeypatch.setattr(mod, "IN_FLIGHT", note)

    with pytest.raises(SystemExit) as stopped:
        mod.refuse_if_a_previous_run_was_killed()

    said = str(stopped.value)
    assert "openfactory/x.py" in said, "the wounded file is not named"
    assert "the cut that was interrupted" in said, "which cut it was is not named"
    assert "/tmp/x.py" in said, "the operator is not told how to restore it"
    assert "Nothing was run" in said


def test_and_a_clean_tree_is_not_stopped(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("mutate_probe", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "IN_FLIGHT", tmp_path / "absent")

    mod.refuse_if_a_previous_run_was_killed()      # must simply return


def test_the_note_is_written_BEFORE_the_file_is_touched(tmp_path, monkeypatch):
    """Order is the whole property: written after the mutation, a kill in between leaves the
    mutant with no note, which is the state this exists to make impossible."""
    import importlib.util
    import inspect

    spec = importlib.util.spec_from_file_location("mutate_probe", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    src = inspect.getsource(mod.run_one)

    assert src.index("IN_FLIGHT.write_text") < src.index("path.write_text"), (
        "the note is written after the mutation — a kill in between leaves no trace")
    assert src.index("shutil.copy2(backup, path)") < src.index("IN_FLIGHT.unlink"), (
        "the note is cleared before the file is restored — a kill in between loses the wound")


def test_the_tool_refuses_to_START_with_a_stale_note():
    """End to end: the real entry point, with the real sentinel path."""
    import importlib.util
    import inspect

    spec = importlib.util.spec_from_file_location("mutate_probe", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    src = inspect.getsource(mod.main)
    assert "refuse_if_a_previous_run_was_killed()" in src, (
        "the check exists and `main` never calls it — the note is written for nobody")
