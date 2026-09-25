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


def test_the_version_marker_is_read_from_git_never_shelled_out(tmp_path: Path, monkeypatch):
    """The marker names the revision of an OPERATOR-configured directory, so it is READ from
    `.git`, never obtained by running `git` inside a directory named from outside — a `.git/config`
    there could drive execution (aliases, `core.fsmonitor`). Proven by forbidding subprocess and
    requiring the marker to still resolve, and to match the real HEAD."""
    (tmp_path / "security.md").write_text("rules")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed"]):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    full = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    def _boom(*a, **k):  # any process spawn is a regression of the security fix
        raise AssertionError("operator_guidelines must not spawn a subprocess to read a revision")

    monkeypatch.setattr(subprocess, "run", _boom)
    tier = og.gather(env={og.ENV_VAR: str(tmp_path)})

    assert tier.version and full.startswith(tier.version)


def test_a_symlinked_reference_subtree_leading_out_is_ignored_with_a_warning(
        tmp_path: Path, caplog):
    """The `reference/` walk resolves every file too, so a symlink pointing a whole subtree out of
    the configured directory is contained the same way a top-level one is: the escaping file is
    named in a warning and never indexed, while a real reference doc beside it still is."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("do not index me")
    guidelines = tmp_path / "guidelines"
    ref = guidelines / "reference"
    ref.mkdir(parents=True)
    (ref / "real.md").write_text("# Legitimate reference")
    (ref / "escape").symlink_to(outside)

    with caplog.at_level("WARNING"):
        tier = og.gather(env={og.ENV_VAR: str(guidelines)})

    assert [p.name for p in tier.reference_docs] == ["real.md"]
    assert "escape" in caplog.text and "resolves outside" in caplog.text


def test_a_symlinked_reference_subtree_pointing_INSIDE_is_named_rather_than_silently_skipped(
        tmp_path: Path, caplog):
    """A link that stays inside the configured directory is still not descended — and says so.

    `os.walk(followlinks=False)` is the containment posture and it is right: the walk may not be
    steered by a link, in bounds or out. But an operator who links `reference/rules -> ../rules`
    inside their own directory used to get an index missing those documents with NOTHING saying
    why — a rule they wrote down and no job reads, which is the exact failure this module was
    written to end (review of #328). The link is refused as before; the refusal is now audible.
    """
    guidelines = tmp_path / "guidelines"
    real = guidelines / "standards"
    real.mkdir(parents=True)
    (real / "linked.md").write_text("# Reachable only through the link")
    ref = guidelines / "reference"
    ref.mkdir()
    (ref / "real.md").write_text("# Legitimate reference")
    (ref / "linked").symlink_to(real)

    with caplog.at_level("WARNING"):
        tier = og.gather(env={og.ENV_VAR: str(guidelines)})

    # the posture is unchanged: the linked subtree is NOT indexed…
    assert [p.name for p in tier.reference_docs] == ["real.md"]
    # …and it is not silent about it, naming the link and the setting that would fix it
    assert "reference/linked" in caplog.text.replace(str(guidelines) + "/", "")
    assert "not indexed" in caplog.text and og.ENV_VAR in caplog.text
    # an in-bounds link is NOT reported as an escape — that would send the operator hunting
    assert "resolves outside" not in caplog.text


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
