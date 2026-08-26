"""A model cites a BLOCK, and the checker has to read that (pilot, 2026-08-14).

The semantic backfill's whole design is that a sentence survives only if its `file:line`
resolves — trust replaced by verification. The parser behind it accepted exactly one shape,
`file.py:52`, and a range (`file.py:139-186`) fell through as a PATH: the repository was then
searched for a file literally named `…/content.py:139-186`, did not have one, and the claim was
demoted with the sentence *"cited X, which this repository does not contain"*.

Measured on the pilot's first real backfill of a 13k-line repository: every ranged citation was
rejected and the single one-line citation survived, so a pass that had read the code correctly
produced a document of sixteen "is this true?" questions and exactly one invariant. The tokens
were spent; the verdict was the parser's. The client would have read that as the platform being
unable to understand their codebase.

  1. a range anchors at its START — the line the claim is about;
  2. a single line still works, unchanged;
  3. a range whose start is past the end of the file is still rejected, with the count;
  4. a rejection says WHICH of the three it is — missing file, a directory, or a locator this
     parser could not read — because "the repository does not contain it" sent a reviewer
     looking for a deletion that never happened;
  5. a nonsense tail is not silently read as a line (`namespace:name`, `C:\\src`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openfactory.onboarding.context import _Anchorer, _split_citation


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src" / "models").mkdir(parents=True)
    (tmp_path / "src" / "models" / "content.py").write_text(
        "\n".join(f"line {i}" for i in range(1, 400)))
    (tmp_path / "src" / "workers").mkdir(parents=True)
    (tmp_path / "README.md").write_text("\n".join(f"r{i}" for i in range(1, 40)))
    return tmp_path


def test_a_range_anchors_at_its_start(repo):
    kept, rejected = _Anchorer(repo).anchor(["src/models/content.py:139-186"])

    assert not rejected, rejected
    assert kept and kept[0].path == "src/models/content.py" and kept[0].line == 139
    assert kept[0].excerpt == "line 139", "the anchored line is not the one that was cited"


def test_a_single_line_is_unchanged(repo):
    kept, rejected = _Anchorer(repo).anchor(["README.md:12"])

    assert not rejected and kept[0].line == 12


def test_a_range_past_the_end_of_the_file_is_still_refused(repo):
    """The check the whole mechanism exists for must survive the fix: a real file and an
    impossible location is the tell that separates reading from reciting."""
    kept, rejected = _Anchorer(repo).anchor(["src/models/content.py:9000-9100"])

    assert not kept
    assert "399 line(s)" in rejected[0], rejected


def test_a_rejection_says_which_of_the_three_it_is(repo):
    anchorer = _Anchorer(repo)

    _, missing = anchorer.anchor(["src/nowhere.py:10"])
    _, directory = anchorer.anchor(["src/workers"])
    _, unreadable = anchorer.anchor(["README.md:not-a-line"])

    assert "directory" not in missing[0] and "line locator" not in missing[0], (
        "a genuinely absent file must read as absent")
    assert "directory" in directory[0], (
        "a citation naming a directory was reported as a file the repository does not contain")
    assert "the file is there" in unreadable[0], (
        "an unreadable locator was reported as a missing file — the reviewer goes looking for a "
        "deletion that never happened")


@pytest.mark.parametrize("raw, expected", [
    ("openfactory/box_prove.py:52", ("openfactory/box_prove.py", 52)),
    ("file.py:139-186", ("file.py", 139)),
    ("file.py:186-139", ("file.py:186-139", None)),   # backwards is not a range
    ("file.py:1-", ("file.py:1-", None)),
    ("namespace:name", ("namespace:name", None)),
    (r"C:\src", (r"C:\src", None)),
    ("plain/path.md", ("plain/path.md", None)),
])
def test_the_parser_reads_only_what_it_can_defend(raw, expected):
    assert _split_citation(raw) == expected
