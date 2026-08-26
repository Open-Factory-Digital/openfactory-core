"""`env apply --pr`: the factory proposes the manifest itself, with no checkout anywhere.

The pilot operator, reading that §3 wanted a checkout: *"how could this have the option of running 100% in the cloud if there is a dependency on my
laptop?"* — and then, when offered the choice of
building it now or after the pilot: *"nós estamos no teste real, tem que ser real"* (2026-08-12).

The factory's work never needed a personal machine. Authoring `.openfactory/project.yaml` did,
because `env apply` wrote a file into a checkout and a URL-registered project has none here.
Writing into the worker's cache clone would be worse than refusing — nobody reviews that tree
and the next fetch replaces it — so the manifest is proposed the way the product module already
proposes requirements: a branch, a commit, a PULL REQUEST a human reads before it is true.

What these guards hold, in the order they matter:

  1. a URL-registered project with `--pr` gets a pull request, and the manifest is IN it;
  2. without `--pr` the refusal still stands AND now names both ways forward;
  3. the two idempotency arms the product module paid for in incidents: an existing proposal is
     not proposed twice, and a branch pushed with no PR on it is FINISHED rather than re-pushed
     (a second `push -u` is rejected as non-fast-forward and the verb wedges for ever);
  4. "could not ask" is never read as "there is none" — the arm that files the duplicate;
  5. a local checkout still writes a file, unchanged.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfactory.cli import app

_ANSWER = ["--set", "validate.test=pytest -q"]


class _Forge:
    """The forge port, doubled at the four methods this path uses."""

    def __init__(self, *, existing_pr: str | None = "", branches: list[str] | None = None):
        self._existing = existing_pr
        self._branches = branches or []
        self.opened: list[dict] = []

    def clone_url(self, repo, *, token=None):
        return f"https://x-access-token:{token}@github.com/{repo}.git"

    def pr_for_head(self, head, *, repo=""):
        if self._existing is None:
            raise RuntimeError("the forge could not be reached")
        return self._existing

    def list_branches(self, repo="", *, prefix=""):
        return list(self._branches)

    def open_pr(self, *, head, base, title, body, repo=""):
        self.opened.append({"head": head, "base": base, "title": title, "body": body,
                            "repo": repo})
        return f"https://github.com/{repo}/pull/9"


@pytest.fixture
def remote(tmp_path):
    """A real git repository to clone from — the git side stays production code."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True,
                   capture_output=True)
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "pyproject.toml").write_text('[project]\nname = "podbeam"\nversion = "0.1.0"\n')
    for args in (["init", "-b", "main"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "seed"],
                 ["remote", "add", "origin", str(origin)], ["push", "-u", "origin", "main"]):
        subprocess.run(["git", *args], cwd=seed, check=True, capture_output=True)
    return origin


@pytest.fixture
def wired(tmp_path, monkeypatch, remote):
    """A project registered by URL, with the forge doubled and the clone pointed at `remote`."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(
        app, ["project", "add", "podbeam", "https://github.com/solo-dev/podbeam.git"]
    ).exit_code == 0

    def _wire(forge: _Forge):
        from openfactory.adapters.forge import registry as forge_registry

        monkeypatch.setattr(forge_registry, "build_forge", lambda *a, **kw: forge)
        # the only seam that would leave this machine: the URL git is handed
        monkeypatch.setattr(_Forge, "clone_url", lambda self, repo, *, token=None: str(remote))
        return forge

    return _wire


def _apply(*args):
    return CliRunner().invoke(app, ["env", "apply", "podbeam", "--yes", *_ANSWER, *args])


def test_with_pr_the_factory_clones_writes_and_opens_the_pull_request(wired):
    forge = wired(_Forge())

    result = _apply("--pr")

    assert result.exit_code == 0, result.output
    assert forge.opened, f"no pull request was opened: {result.output}"
    opened = forge.opened[0]
    assert opened["head"] == "openfactory/manifest"
    assert opened["base"] == "main"
    assert "pull/9" in result.output


def test_the_manifest_is_actually_IN_the_branch_that_was_pushed(wired, remote):
    """The half that makes the write real: without the commit+push this whole path would be an
    elaborate no-op in a temporary directory nobody will ever look at."""
    wired(_Forge())

    assert _apply("--pr").exit_code == 0

    shown = subprocess.run(
        ["git", "show", "openfactory/manifest:.openfactory/project.yaml"],
        cwd=remote, capture_output=True, text=True, check=False)
    assert shown.returncode == 0, shown.stderr
    assert "pytest -q" in shown.stdout


def test_without_pr_the_refusal_names_BOTH_ways_forward(wired):
    wired(_Forge())

    result = _apply()

    assert result.exit_code != 0
    assert "no checkout" in result.output
    assert "--pr" in result.output, "the server-side way forward must be named"
    assert "path-to-your-checkout" in result.output, "the local way forward must be named too"


def test_an_existing_proposal_is_not_proposed_twice(wired):
    forge = wired(_Forge(existing_pr="https://github.com/solo-dev/podbeam/pull/3"))

    result = _apply("--pr")

    assert result.exit_code == 0, result.output
    assert forge.opened == [], "a second pull request was opened for work already proposed"
    assert "pull/3" in result.output


def test_a_pushed_branch_with_no_pull_request_is_FINISHED_not_re_pushed(wired):
    """The window a rate limit or a dying worker lands in. Re-pushing is rejected as
    non-fast-forward, so without this arm every later attempt fails on a healthy repository."""
    forge = wired(_Forge(existing_pr="", branches=["openfactory/manifest"]))

    result = _apply("--pr")

    assert result.exit_code == 0, result.output
    assert len(forge.opened) == 1
    assert "already" in result.output.lower()


def test_a_forge_that_cannot_be_ASKED_writes_nothing(wired):
    """`pr_for_head` raising means "I could not tell", and a caller reading that as "there is
    none" files the duplicate on a transient failure — the arm the product module paid for."""
    forge = wired(_Forge(existing_pr=None))

    result = _apply("--pr")

    assert result.exit_code != 0
    assert forge.opened == []
    assert "already proposed" in result.output


@pytest.mark.parametrize("forge_state, why", [
    ({}, "the happy path"),
    ({"existing_pr": None}, "a refusal between the clone and the push"),
])
def test_the_temporary_clone_is_REMOVED_however_this_ends(wired, monkeypatch, forge_state, why):
    """The growth guard is static: it accepts a table entry naming the caller that releases the
    directory. That entry is prose, and prose is not a release — this asserts the property in
    both directions, because the refusals BETWEEN the clone and the push are exactly where a
    `finally` earns its place (and where a mutation of it would otherwise pass unnoticed)."""
    wired(_Forge(**forge_state))

    from openfactory.onboarding import propose_manifest as pm

    made: list[Path] = []
    real = pm.clone_for_proposal

    def _remember(**kw):
        path, err = real(**kw)
        if path is not None:
            made.append(path)
        return path, err

    monkeypatch.setattr("openfactory.onboarding.propose_manifest.clone_for_proposal", _remember)

    _apply("--pr")

    assert made, f"nothing was cloned, so this proves nothing ({why})"
    assert not made[0].exists(), f"the temporary clone survived {why}: {made[0]}"


def test_out_and_pr_together_are_refused_instead_of_one_winning_silently(wired):
    wired(_Forge())

    result = _apply("--pr", "--out", "/tmp/somewhere.yaml")

    assert result.exit_code != 0
    assert "pick one" in result.output


def test_a_local_checkout_still_writes_a_file(tmp_path, monkeypatch):
    """The path that has always worked must not have changed shape."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    checkout = tmp_path / "local"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.1.0"\n')

    result = CliRunner().invoke(app, ["env", "apply", str(checkout), "--yes", *_ANSWER])

    assert result.exit_code == 0, result.output
    assert (checkout / ".openfactory" / "project.yaml").is_file()
    assert Path(str(result.output)).name  # the message names where it wrote


def test_the_clone_carries_no_credential_in_its_origin(tmp_path, remote, monkeypatch):
    """The checkout goes on to host agents and to the box proof — the tokened URL must leave
    `.git/config` the moment the clone lands (adversarial review, 2026-08-13). Pinned by
    asserting origin equals the SCRUBBED URL exactly: if the scrub is ever deleted, origin
    keeps the clone argument and this fails."""
    from openfactory.onboarding import propose_manifest as pm

    tokened = "https://x-access-token:ghs_LIVE_SECRET@github.com/acme/api.git"
    real_git = pm._git

    def _git(args, cwd=None):
        # only the network-reaching CLONE is rerouted locally; every other call runs real
        return real_git([str(remote) if a == tokened else a for a in args], cwd=cwd)

    monkeypatch.setattr(pm, "_git", _git)
    checkout, why = pm.clone_for_proposal(clone_url=tokened)

    assert checkout is not None, why
    try:
        url = subprocess.run(["git", "-C", str(checkout), "config", "remote.origin.url"],
                             capture_output=True, text=True).stdout.strip()
        assert url == "https://github.com/acme/api.git", (
            f"origin still carries what the clone was given: {url}")
    finally:
        import shutil

        shutil.rmtree(checkout, ignore_errors=True)


def test_a_merged_proposals_leftover_branch_falls_through_to_a_fresh_one(wired):
    """After the first proposal MERGES, its ref stays behind and no PR is open on it. The old
    wedge arm tried to 'finish' it, the forge refused the zero-diff PR, and the verb wedged
    for ever on every repository where it had already worked once (adversarial review,
    2026-08-13). A refused finish now falls through: fresh commit, force-push over the
    platform's own leftover ref, new pull request."""

    class _MergedLeftover(_Forge):
        def __init__(self):
            super().__init__(existing_pr="", branches=["openfactory/manifest"])
            self.attempts = 0

        def open_pr(self, *, head, base, title, body, repo=""):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("No commits between main and openfactory/manifest")
            return super().open_pr(head=head, base=base, title=title, body=body, repo=repo)

    forge = wired(_MergedLeftover())

    result = _apply("--pr")

    assert result.exit_code == 0, result.output
    assert forge.attempts == 2, "the refused finish did not fall through to a fresh proposal"
    assert forge.opened and "pull/9" in result.output
