"""GitHubActionsObserver — read CI/deploy status via the GitHub API (read-only)."""

from __future__ import annotations

import json
import subprocess

import httpx

from openfactory.adapters.environment.base import CheckStatus, EnvironmentObserver, Status

_CONCLUSION: dict[str, Status] = {
    "success": "success", "failure": "failure", "cancelled": "failure",
    "timed_out": "failure", "startup_failure": "failure",
}


class GitHubActionsObserver(EnvironmentObserver):
    def __init__(self, repo: str, *, token: str | None = None) -> None:
        self.repo = repo  # "owner/name"
        self.token = token

    def _api(self, path: str) -> object:
        import os

        env = dict(os.environ)
        if self.token:
            env["GH_TOKEN"] = self.token
        p = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=30, env=env)
        if p.returncode != 0:
            raise RuntimeError(f"gh api {path} failed: {p.stderr}")
        return json.loads(p.stdout)

    def ci_status(self, *, repo: str, ref: str) -> list[CheckStatus]:
        """The check runs on `ref`, in the repository the CALLER named.

        THE PARAMETER WAS ACCEPTED AND DISCARDED. This read `self.repo` — the one repository this
        observer was constructed for — so on a multi-repo project (which this platform supports,
        and which is the whole reason the port lets a caller name one) asking about the front-end's
        ref answered with the back-end's checks, confidently and with no error anywhere. The Azure
        twin honours it and says so in its own docstring; found by the guard written for the same
        defect one method down, which is why that guard walks the whole port rather than one
        method.

        `self.repo` remains the default, so a caller that has nothing to say about the repository
        gets what it always got."""
        data = self._api(f"repos/{repo or self.repo}/commits/{ref}/check-runs")
        runs = data.get("check_runs", []) if isinstance(data, dict) else []
        out = []
        for r in runs:
            status: Status = (
                "pending" if r.get("status") != "completed"
                else _CONCLUSION.get(r.get("conclusion"), "unknown")
            )
            out.append(CheckStatus(name=r.get("name", "?"), status=status, url=r.get("html_url")))
        return out

    def deploy_status(self, *, env: str, ref: str) -> Status:
        """Whether `ref` reached the GitHub environment `env`.

        THE REF WAS TAKEN AND THROWN AWAY, and this gate decides whether a production approval is
        offered to a human. The read was "the newest Deployment to this environment, whoever made
        it and from wherever" — so a colleague deploying a different branch to staging made the
        platform report the ticket's change as verified, and post *"✅ staging verified"* on it.

        The Azure observer's own docstring names this exact failure and correlates the record to
        the ref to avoid it; the twin on the vendor we develop against did not, which is the shape
        the second-vendor lesson keeps producing in this repository. `ref` is a branch here (the
        promotion tail passes `manifest.base_branch`), and GitHub's Deployment carries its own, so
        the filter is the API's — no correlation to build by hand.

        Four values, each meaning something different, matching the Azure twin:
            unknown   no such environment, or one nothing has ever deployed to
            pending   the environment receives deployments, but not yet from this ref
            success   the newest deployment OF THIS REF finished green
            failure   it did not
        """
        deps = self._api(
            f"repos/{self.repo}/deployments?environment={env}&ref={ref}&per_page=1")
        if not isinstance(deps, list) or not deps:
            # NOT-YET IS NOT NEVER. Without this second read both answers were "unknown", and the
            # caller cannot tell "this environment does not exist" (a configuration mistake worth
            # reporting) from "your change has not been deployed there yet" (wait).
            any_dep = self._api(f"repos/{self.repo}/deployments?environment={env}&per_page=1")
            return "pending" if isinstance(any_dep, list) and any_dep else "unknown"
        statuses = self._api(f"repos/{self.repo}/deployments/{deps[0]['id']}/statuses?per_page=1")
        if not isinstance(statuses, list) or not statuses:
            return "pending"
        state = statuses[0].get("state", "")
        return {"success": "success", "failure": "failure", "error": "failure",
                "in_progress": "pending", "queued": "pending"}.get(state, "unknown")

    def health(self, *, url: str, timeout: int = 10) -> bool:
        try:
            return httpx.get(url, timeout=timeout).is_success
        except httpx.HTTPError:
            return False
