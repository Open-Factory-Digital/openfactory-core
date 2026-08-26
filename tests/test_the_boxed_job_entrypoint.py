"""The in-task Fargate entrypoint: env config, clone URL, redaction, result contract.

Pure helpers are unit-tested here; the full clone→run integration is proven live on
Fargate later. run_boxed is exercised against a LOCAL git repo with the job's adapters
monkeypatched, so it needs no GitHub and no AWS.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory import namespace
from openfactory.runtime import boxed_job as ep


# --- pure helpers ---
def test_clone_url_embeds_token_or_stays_plain():
    """Unchanged behaviour for the GitHub box, now reached through the forge port (#162): the URL
    is the adapter's, and this asserts the port answers what the weld used to spell."""
    cfg = ep.BoxConfig(project="p", issue="1", repo="o/r")

    assert ep.clone_url(cfg, token="tok") == "https://x-access-token:tok@github.com/o/r.git"
    assert ep.clone_url(cfg, token=None) == "https://github.com/o/r.git"


def test_redact_hides_token_in_urls():
    msg = "fatal: could not read https://x-access-token:secret@github.com/o/r.git"
    assert "secret" not in ep.redact(msg)
    assert "***@github.com" in ep.redact(msg)


def test_config_from_env_reads_and_defaults():
    cfg = ep.config_from_env(
        {"OPENFACTORY_PROJECT": "books", "OPENFACTORY_ISSUE": "189", "OPENFACTORY_REPO": "o/r"}
    )
    assert (cfg.project, cfg.issue, cfg.repo) == ("books", "189", "o/r")
    assert cfg.review is True and cfg.board_owner is None
    assert cfg.resume_handle is None  # C2: a plain job starts cold


def test_config_from_env_reads_resume_handle():
    # C2: the durable resume delivers the opaque handle via env; the box must read it back.
    cfg = ep.config_from_env({
        "OPENFACTORY_PROJECT": "p", "OPENFACTORY_ISSUE": "1", "OPENFACTORY_REPO": "o/r",
        "OPENFACTORY_RESUME_HANDLE": "opaque-token",
    })
    assert cfg.resume_handle == "opaque-token"


def test_config_from_env_review_toggle_and_board():
    cfg = ep.config_from_env({
        "OPENFACTORY_PROJECT": "p", "OPENFACTORY_ISSUE": "1", "OPENFACTORY_REPO": "o/r",
        "OPENFACTORY_REVIEW": "false", "OPENFACTORY_BOARD_OWNER": "Org", "OPENFACTORY_BOARD_NUMBER": "6",
    })
    assert cfg.review is False
    assert (cfg.board_owner, cfg.board_number) == ("Org", "6")


def test_config_from_env_requires_core_fields():
    with pytest.raises(KeyError):
        ep.config_from_env({"OPENFACTORY_PROJECT": "p"})  # missing ISSUE + REPO


def test_materialize_app_key_writes_content_and_sets_path(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENFACTORY_GH_APP_KEY", raising=False)
    path = ep.materialize_app_key(
        {"OPENFACTORY_GH_APP_KEY_CONTENT": "-----BEGIN KEY-----\nx\n"}, dest_dir=tmp_path
    )
    assert path is not None
    assert Path(path).read_text().startswith("-----BEGIN KEY-----")
    import os as _os

    assert _os.environ["OPENFACTORY_GH_APP_KEY"] == path


def test_main_always_emits_a_redacted_failure_result_on_crash(monkeypatch, capsys):
    monkeypatch.setenv("OPENFACTORY_PROJECT", "p")
    monkeypatch.setenv("OPENFACTORY_ISSUE", "5")
    monkeypatch.setenv("OPENFACTORY_REPO", "o/r")
    monkeypatch.delenv("OPENFACTORY_BOT_TOKEN", raising=False)

    def boom(*a, **k):
        raise RuntimeError("push failed https://x-access-token:SECRET@github.com/o/r.git")

    monkeypatch.setattr(ep, "run_boxed", boom)
    rc = ep.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert ep.RESULT_PREFIX in out  # a contract line is ALWAYS emitted, never a bare crash
    assert '"state":"failed"' in out.replace(" ", "")
    assert "SECRET" not in out  # the token in the error is redacted


def test_materialize_app_key_noop_when_path_already_set(tmp_path):
    out = ep.materialize_app_key(
        {"OPENFACTORY_GH_APP_KEY_CONTENT": "x", "OPENFACTORY_GH_APP_KEY": "/already/there"},
        dest_dir=tmp_path,
    )
    assert out is None  # respects an explicit path, writes nothing


# --- run_boxed against a local repo (no GitHub, no AWS) ---
def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_clone_strips_bot_token_from_origin(tmp_path: Path, monkeypatch):
    # after cloning with the authenticated URL, origin must carry NO token, so the
    # sandboxed agent cannot `git push` with the bot's creds (the framework pushes via its
    # own explicit remote). #232 pushed a stray branch because origin kept the token.
    remote = tmp_path / "remote"
    remote.mkdir()
    _git(remote, "init", "-q", "-b", "main")
    _git(remote, "config", "user.email", "t@t")
    _git(remote, "config", "user.name", "t")
    (remote / "README.md").write_text("hi\n")
    _git(remote, "add", "-A")
    _git(remote, "commit", "-qm", "init")

    # clone over the local path (token form), deauth to a plain github URL (None form)
    monkeypatch.setattr(
        ep, "clone_url",
        lambda repo, token: str(remote) if token else "https://github.com/o/r.git",
    )
    dest = tmp_path / "clone"
    ep._clone("o/r", dest, token="bot-secret-tok")

    got = subprocess.run(
        ["git", "-C", str(dest), "remote", "get-url", "origin"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert "bot-secret-tok" not in got, "bot token leaked into origin — agent could push"
    assert got == "https://github.com/o/r.git"


def test_run_boxed_clones_registers_and_runs(tmp_path: Path, monkeypatch):
    # a local "remote" repo with a manifest, served over file:// via clone_url override
    remote = tmp_path / "remote"
    remote.mkdir()
    _git(remote, "init", "-q", "-b", "main")
    _git(remote, "config", "user.email", "t@t")
    _git(remote, "config", "user.name", "t")
    (remote / namespace.DIR).mkdir()
    (remote / namespace.MANIFEST).write_text("version: 1\nbase_branch: main\n")
    (remote / "README.md").write_text("hi\n")
    _git(remote, "add", "-A")
    _git(remote, "commit", "-qm", "init")

    # clone via a plain local path instead of github.com
    monkeypatch.setattr(ep, "clone_url", lambda repo, token: str(remote))

    captured = {}

    class _Result:
        def __init__(self):
            self.state = type("S", (), {"value": "pr_open"})()

        def model_dump_json(self):
            return '{"state":"pr_open"}'

    def fake_build_runner(project, issue, *, sandbox, image, review, events=None):
        captured.update(project=project.name, repo_path=project.repo_path, sandbox=sandbox)

        class _R:
            def run(self, ref, resume_handle=None, spent_turns=0, decision=""):
                captured["ran"] = ref
                captured["resume_handle"] = resume_handle
                captured["decision"] = decision
                return _Result()

            def knowledge_arm(self) -> str:
                return "off"  # the real JobRunner reports the A/B arm (ADR-0017)

        return _R()

    import openfactory.factory as factory

    monkeypatch.setattr(factory, "build_runner", fake_build_runner)

    cfg = ep.config_from_env({"OPENFACTORY_PROJECT": "demo", "OPENFACTORY_ISSUE": "5", "OPENFACTORY_REPO": "o/r",
                              "OPENFACTORY_RESUME_HANDLE": "opaque-token"})
    result = ep.run_boxed(cfg, workdir=tmp_path / "box", token=None)

    assert (tmp_path / "box" / "repo" / namespace.MANIFEST).exists()  # cloned
    assert captured["project"] == "demo" and captured["sandbox"] == "worktree"
    assert captured["ran"] == "5"
    assert captured["resume_handle"] == "opaque-token"  # C2: box → runner.run(resume_handle=…)
    assert result.state.value == "pr_open"
