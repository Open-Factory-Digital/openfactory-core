"""Rerun the failed CI jobs before an agent edits code for a red CI.

A red CI is not always a defect in the diff. A shared dev environment fails jobs that no
changed file touches, and an agent pass on those has nothing to fix. This module gives the CI
repair path two moves:

1. The failing logs name no changed file: rerun the failed jobs and skip the agent.
2. The agent pass changed nothing: rerun the failed jobs.

Every rerun leaves a PR comment that names the failed jobs and the reason. The workflow's own
attempt cap still bounds the loop.
"""
from __future__ import annotations

import json
import logging
import re
import time

log = logging.getLogger(__name__)

WAIT_SECONDS = 3 * 60 * 60
POLL_SECONDS = 60

_DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.M)
_CODE_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".py", ".java", ".kt", ".go", ".rb", ".cs")


def changed_paths(diff: str | None) -> list[str]:
    return sorted({m.group(2) for m in _DIFF_FILE.finditer(diff or "")})


def _keys(path: str) -> list[str]:
    name = path.rsplit("/", 1)[-1]
    keys = [path, name]
    for ext in _CODE_EXT:
        if name.endswith(ext):
            keys.append(name[: -len(ext)])
            break
    return keys


def unrelated_to_diff(paths: list[str], ci_log: str | None) -> bool:
    """True only when a log was read and nothing in it names a changed file."""
    if not ci_log or not paths:
        return False
    return not any(key in ci_log for path in paths for key in _keys(path))


def _read(forge, args: list[str]):
    got = forge._gh(args)
    if got.returncode != 0 or not (got.stdout or "").strip():
        return None
    try:
        return json.loads(got.stdout)
    except ValueError:
        return None


def _runs_for_head(forge, pr: str) -> list[dict] | None:
    head = _read(forge, ["pr", "view", pr, "--repo", forge.repo, "--json",
                         "headRefName,headRefOid"])
    if not isinstance(head, dict) or not head.get("headRefName"):
        return None
    runs = _read(forge, ["run", "list", "--repo", forge.repo, "--branch", head["headRefName"],
                         "--json", "databaseId,status,conclusion,headSha", "--limit", "30"])
    if not isinstance(runs, list):
        return None
    return [r for r in runs if r.get("headSha") == head.get("headRefOid")]


def _settled_runs(forge, pr: str, wait_seconds: int) -> list[dict] | None:
    """The runs for the PR head once none is still going, or None when the wait ran out."""
    deadline = time.monotonic() + wait_seconds
    while True:
        runs = _runs_for_head(forge, pr)
        if runs is None:
            return None
        if runs and all(r.get("status") == "completed" for r in runs):
            return runs
        if time.monotonic() >= deadline:
            return None
        time.sleep(POLL_SECONDS)


def _failed_jobs(forge, pr: str) -> list[str]:
    return [c["name"] for c in forge.pr_checks(pr=pr)
            if c.get("bucket") == "fail" and c.get("name")]


def _rerun(forge, runs: list[dict]) -> list[int]:
    done = []
    for run in runs:
        if (run.get("conclusion") or "").lower() != "failure":
            continue
        got = forge._gh(["run", "rerun", str(run["databaseId"]), "--repo", forge.repo, "--failed"])
        if got.returncode == 0:
            done.append(run["databaseId"])
        else:
            log.warning("could not rerun %s (%s)", run["databaseId"],
                        (got.stderr or "").strip()[:160])
    return done


def _comment(forge, pr: str, body: str) -> None:
    got = forge._gh(["pr", "comment", pr, "--repo", forge.repo, "--body", body])
    if got.returncode != 0:
        log.warning("could not comment on %s (%s)", pr, (got.stderr or "").strip()[:160])


def rerun_unrelated(forge, pr: str, attempt: int, *, dry_run: bool = False,
                    wait_seconds: int = WAIT_SECONDS) -> str | None:
    """Rerun the failed jobs when no changed file appears in their logs.

    Returns the note to record when it acted, or None to let the agent repair. Unreadable input
    returns None, so an unknown never skips the repair.

    GITHUB CLI ONLY (`forge._gh`, `forge.repo`) — every forge answers `pr_checks`/`failed_ci_logs`,
    but a rerun is GitHub Actions' own concept, and Azure Pipelines has no equivalent seam here yet.
    A forge without it is unreadable in exactly the sense above, not a crash."""
    if not hasattr(forge, "_gh"):
        return None
    runs = _settled_runs(forge, pr, wait_seconds)
    if not runs:
        return None
    paths = changed_paths(forge.pr_diff(pr=pr))
    if not unrelated_to_diff(paths, forge.failed_ci_logs(pr=pr, max_chars=400000)):
        return None
    failed = _failed_jobs(forge, pr)
    shown = ", ".join(failed) or "none named"
    note = (f"CI failed in jobs that no changed file appears in ({shown}). "
            f"Failed jobs rerun instead of editing code (attempt {attempt}).")
    if dry_run:
        return "DRY RUN: " + note
    if not _rerun(forge, runs):
        return None
    _comment(forge, pr, "CI note: " + note + " Changed files: " + ", ".join(paths) + ".")
    return note


def rerun_after_no_fix(forge, pr: str, attempt: int) -> str | None:
    """Rerun the failed jobs after a repair pass that pushed nothing.

    GITHUB CLI ONLY — see `rerun_unrelated`."""
    if not hasattr(forge, "_gh"):
        return None
    runs = _settled_runs(forge, pr, WAIT_SECONDS)
    if not runs:
        return None
    failed = _failed_jobs(forge, pr)
    if not _rerun(forge, runs):
        return None
    named = ", ".join(failed) or "none named"
    note = (f"The repair pass changed no code for the failing jobs ({named}). "
            f"Failed jobs rerun (attempt {attempt}).")
    _comment(forge, pr, "CI note: " + note)
    return note
