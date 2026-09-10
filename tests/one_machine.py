"""One machine, one card, through the real doors — the fixture the proof drives.

NOT A TEST FILE, and not a set of doubles either. Everything here is the platform's own: the
registering door (`project init`), the two card actions, `poll`, the local rows built by kind
through the registries, the worktree box, a real `git init` repository with real commits. The ONE
thing that is scripted is the harness — the model is the axis the proof deliberately does not
exercise, since the whole point is that nothing leaves this machine.

IT LIVES BESIDE THE PROOF RATHER THAN INSIDE IT because the proof runs in a SUBPROCESS: pytest
fixtures cannot cross that boundary, and a copy of the setup written into the probe's source string
would be the copy that stops matching the real doors (`tests/pinned_probes.py` is here for the same
reason, one seam over).
"""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import subprocess

#: What the scripted harness writes, and what the card asks for — one fact, so the gate the
#: manifest declares is a REAL check of the agent's work rather than a `true` that proves nothing.
FEATURE = "feature.py"
VALUE = "VALUE = 42"

CARD_BODY = (
    "## Objective\nAdd a feature module the rest of the app can import.\n\n"
    "## Acceptance criteria\n"
    f"- `{FEATURE}` exists at the repository root\n"
    f"- it defines {VALUE}\n"
)


def git(repo, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=False)


def a_repository(root: pathlib.Path) -> pathlib.Path:
    """A person's own repository: `main`, one commit, no remote anywhere."""
    repo = root / "myapp"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "person@example.invalid")
    git(repo, "config", "user.name", "A Person")
    (repo / "README.md").write_text("# myapp\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "first")
    return repo


def a_deployment(root: pathlib.Path, *, sandbox: str = "worktree", monkeypatch=None) -> None:
    """The environment a one-machine install has — and nothing else.

    No token of any kind: the harness is scripted, the forge is the person's own repository and
    the tracker is a file beside the registry. Anything left over from the machine running the
    suite is REMOVED rather than inherited, or the proof would quietly measure that machine.

    `monkeypatch` IS REQUIRED IN-PROCESS, and the reason is a defect this file caused. Inside the
    proof's subprocess these are the whole world and writing `os.environ` is right. A test that
    calls this in the PYTEST process without a monkeypatch leaves `OPENFACTORY_SANDBOX=worktree`
    set for everything that runs after it — and the action layer's own tests, which assert the
    deployment's box is the container, then fail in whatever order the suite happens to use. That
    is exactly what CI caught and eight local blocks did not (2026-09-10): a leak is invisible to
    a run that never puts the two files in the same process.
    """
    values = {
        "OPENFACTORY_REGISTRY": str(root / "registry.yaml"),
        "OPENFACTORY_BOARD_DB": str(root / "board.db"),
        "OPENFACTORY_SANDBOX": sandbox,
        "OPENFACTORY_STATE_DIR": str(root / "state"),
        "OPENFACTORY_REPOS_DIR": str(root / "repos"),
        "OPENFACTORY_HARNESS_EXECUTOR": "scripted",
        "OPENFACTORY_HARNESS_REVIEWER": "scripted",
    }
    leftovers = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "OPENFACTORY_AGENT_TOKENS",
                 "OPENFACTORY_BOT_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "TEMPORAL_ADDRESS")
    if monkeypatch is not None:
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        for leftover in leftovers:
            monkeypatch.delenv(leftover, raising=False)
        return
    os.environ.update(values)
    for leftover in leftovers:
        os.environ.pop(leftover, None)


class Scripted:
    """The harness, written by hand: what a coding agent would have done, without one.

    `pauses_first` is how the proof exercises ADR-0013's preserved work: the first pass reports a
    rate limit with real edits already on disk, exactly as a harness that ran out of quota
    mid-change does, and the next one finishes the job."""

    def __init__(self, *, marker: pathlib.Path | None = None, pauses_first: bool = False) -> None:
        self.marker = marker
        self.pauses_first = pauses_first

    def _paused_once(self) -> bool:
        if not self.pauses_first or self.marker is None:
            return False
        if self.marker.exists():
            return False
        self.marker.write_text("paused once\n")
        return True

    def execute(self, *, sandbox, workspace, context):
        from openfactory.contracts import AgentRunResult

        half = workspace.path / FEATURE
        if self._paused_once():
            # REAL WORK, THEN THE WALL. The half-written file is the whole point: what the box
            # does with it on a resume is what ADR-0013 D1 and slice 3b are about.
            half.write_text("# started, then the quota ran out\n")
            # THE RESET IS IN THE PAST, so the next poll really resumes it: `ready_to_resume`
            # asks whether the window has passed, and a proof that waited for a real one would
            # either sleep or prove nothing.
            return AgentRunResult(ok=False, summary="stopped at the usage limit",
                                  pause_reason="rate_limit", retry_at="2000-01-01T00:00:00+00:00",
                                  cost_usd=0.0)
        half.write_text(f"{VALUE}\n")
        return AgentRunResult(ok=True, summary=f"added {FEATURE}", cost_usd=0.0,
                              actions=[f"Edit: {FEATURE}"])

    def repair(self, *, sandbox, workspace, context, failure_log):
        from openfactory.contracts import AgentRunResult

        return AgentRunResult(ok=True, summary="nothing to repair", cost_usd=0.0)

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        """The read-only primitive every judging role is built on — so the review the card gets
        is the platform's SHARED `HarnessReviewer`, the one every non-Claude deployment uses."""
        from openfactory.contracts import AgentRunResult

        verdict = {"decision": "approved", "score": 92, "acceptance": [], "findings": [],
                   "summary": "the diff does what the card asked"}
        stream = json.dumps({"type": "result", "result": json.dumps(verdict)})
        return AgentRunResult(ok=True, summary="reviewed", cost_usd=0.0, raw_output=stream)


def register_the_harness(**kw) -> None:
    from openfactory.adapters.agent.registry import HARNESSES

    HARNESSES["scripted"] = lambda **_: Scripted(**kw)


def cli(*args) -> tuple[int, str]:
    """One command through the real CLI, as a person types it."""
    from typer.testing import CliRunner

    from openfactory.cli import app

    out = CliRunner().invoke(app, list(args))
    if out.exception and not isinstance(out.exception, SystemExit):
        raise AssertionError(f"`openfactory {' '.join(args)}` raised: {out.exception!r}\n"
                             f"{out.output}") from out.exception
    return out.exit_code, out.output


def plug_the_project_in(repo: pathlib.Path, *, merge_policy: str = "auto") -> None:
    """The manifest `project init` scaffolded, with gates that need no interpreter, committed on
    the base branch — which is what the pickup gate hashes."""
    manifest = repo / ".openfactory" / "project.yaml"
    text = manifest.read_text()
    import re

    text = re.sub(r"(?ms)^setup:.*?(?=^\w|\Z)", "setup: []\n\n", text)
    text = re.sub(r"(?ms)^validate:.*?(?=^\w|\Z)",
                  "validate:\n"
                  f"  test: \"test -f {FEATURE} && grep -q '{VALUE}' {FEATURE}\"\n"
                  "  security: \"true\"\n\n", text)
    text = text.replace("merge_policy: human", f"merge_policy: {merge_policy}")
    manifest.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "the plug into the platform")


def card_column(root: pathlib.Path, number: int = 1) -> str:
    """Which column the card is in, read from the file the board IS (D5)."""
    with sqlite3.connect(root / "board.db") as db:
        row = db.execute("SELECT column_key FROM cards WHERE ref = ?", (str(number),)).fetchone()
    return row[0] if row else ""


def pull_request(root: pathlib.Path, number: int = 1) -> dict:
    with sqlite3.connect(root / "board.db") as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM pull_requests WHERE number = ?", (number,)).fetchone()
    return dict(row) if row else {}


def what_the_card_was_told(root: pathlib.Path, number: int = 1) -> str:
    """Everything the factory said ON the card — the comments a person reads."""
    with sqlite3.connect(root / "board.db") as db:
        rows = db.execute("SELECT body FROM comments WHERE ref = ? ORDER BY seq",
                          (str(number),)).fetchall()
    return "\n".join(row[0] for row in rows)
