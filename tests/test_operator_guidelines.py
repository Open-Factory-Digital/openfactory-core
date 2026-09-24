"""The DEPLOYMENT's central guidelines directory (#318) — read, contained, versioned.

These pin the low-level reader (`operator_guidelines.gather`); the cascade wiring
(ordering, indexing, waiver) is pinned end-to-end in `test_context.py`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from openfactory.orchestrator import operator_guidelines as og


def test_unset_contributes_nothing_and_says_nothing(tmp_path: Path):
    tier = og.gather(env={})
    assert not tier.configured and not tier.missing and not tier.empty
    assert tier.guideline_docs == [] and tier.reference_docs == []


def test_md_directly_in_the_dir_is_the_guideline_tier(tmp_path: Path):
    (tmp_path / "security.md").write_text("central security rules")
    (tmp_path / "style.md").write_text("central style rules")
    (tmp_path / "notes.txt").write_text("not markdown")

    tier = og.gather(env={og.ENV_VAR: str(tmp_path)})

    assert tier.configured and tier.dir_exists
    assert sorted(p.name for p in tier.guideline_docs) == ["security.md", "style.md"]


def test_reference_subdir_is_the_index_tier_not_the_guideline_tier(tmp_path: Path):
    (tmp_path / "top.md").write_text("inlined")
    ref = tmp_path / "reference"
    ref.mkdir()
    (ref / "long-standard.md").write_text("# Long standard\nlots of prose")
    (ref / "nested").mkdir()
    (ref / "nested" / "deep.md").write_text("# Deep\nmore")

    tier = og.gather(env={og.ENV_VAR: str(tmp_path)})

    assert [p.name for p in tier.guideline_docs] == ["top.md"]
    assert sorted(p.name for p in tier.reference_docs) == ["deep.md", "long-standard.md"]


def test_a_symlink_leading_out_of_the_dir_is_ignored_with_a_warning(tmp_path: Path, caplog):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text("do not read me into the prompt")
    guidelines = tmp_path / "guidelines"
    guidelines.mkdir()
    (guidelines / "real.md").write_text("legitimate")
    (guidelines / "escape.md").symlink_to(secret)

    with caplog.at_level("WARNING"):
        tier = og.gather(env={og.ENV_VAR: str(guidelines)})

    assert [p.name for p in tier.guideline_docs] == ["real.md"]
    assert "escape.md" in caplog.text  # the warning names the file
    assert "resolves outside" in caplog.text


def test_a_missing_directory_is_flagged_missing(tmp_path: Path):
    tier = og.gather(env={og.ENV_VAR: str(tmp_path / "does-not-exist")})
    assert tier.configured and tier.missing and not tier.empty


def test_an_empty_directory_is_flagged_empty(tmp_path: Path):
    (tmp_path / "readme.txt").write_text("no markdown here")
    tier = og.gather(env={og.ENV_VAR: str(tmp_path)})
    assert tier.configured and tier.empty and not tier.missing


def test_a_git_checkout_carries_a_version_marker(tmp_path: Path):
    (tmp_path / "security.md").write_text("rules")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed"]):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True,
                       capture_output=True)

    tier = og.gather(env={og.ENV_VAR: str(tmp_path)})
    assert tier.version and len(tier.version) >= 4


def test_a_plain_directory_has_no_version_marker(tmp_path: Path):
    (tmp_path / "security.md").write_text("rules")
    tier = og.gather(env={og.ENV_VAR: str(tmp_path)})
    assert tier.version is None


# ── the applied set, named where a reader of the change can see it (criterion 7) ──────────────────


def test_applied_note_is_none_when_unset():
    assert og.applied_note(env={}) is None


def test_applied_note_names_the_set_and_the_reference_tier(tmp_path: Path):
    (tmp_path / "security.md").write_text("rules")
    ref = tmp_path / "reference"
    ref.mkdir()
    (ref / "long.md").write_text("# Long")

    note = og.applied_note(env={og.ENV_VAR: str(tmp_path)})

    assert note is not None
    assert "security.md" in note
    assert "reference/long.md" in note and "read on demand" in note


def test_applied_note_marks_the_git_revision(tmp_path: Path):
    (tmp_path / "security.md").write_text("rules")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed"]):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    note = og.applied_note(env={og.ENV_VAR: str(tmp_path)})
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert note is not None and f"@ {head}" in note


def test_applied_note_reflects_a_profile_waiver(tmp_path: Path):
    from openfactory.contracts.profile import Profile
    from openfactory.policy.profiles import ResolvedProfile

    (tmp_path / "security.md").write_text("kept")
    (tmp_path / "legacy.md").write_text("dropped")
    profile = ResolvedProfile([Profile.model_validate(
        {"name": "poc", "guidelines": {"waive": ["legacy.md"]}})])

    note = og.applied_note(profile, env={og.ENV_VAR: str(tmp_path)})

    assert note is not None
    assert "security.md" in note
    assert "waived by profile: legacy.md" in note
