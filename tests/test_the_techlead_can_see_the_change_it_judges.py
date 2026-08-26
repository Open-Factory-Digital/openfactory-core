"""It is asked whether to merge a change it has never seen (#171).

`ForgeAdapter` could read a pull request's STATE, its checks, its failing logs and its merge SHA,
and had no diff read anywhere. The checkout it reasons from is `git clone --depth 1` of the
DEFAULT branch, so the branch under review is not in it either.

Everything it could say about a pull request therefore came from a stored review verdict written
by a different pass at a different time — which is exactly why #153 happened: it quoted a
two-hour-old rejection and recommended discarding the work that had already fixed it. A human
tech-lead re-reads the diff and checks whether the finding still applies.

THE OPTION TYPE CARRIES THE MEANING, and it is this port's own rule: `None` is "could not look",
`""` is "looked, and there is nothing there". A `.patch` file is precisely where those two would
quietly become one.
"""

from __future__ import annotations

import inspect

import pytest

# ── 1. the contract, walked rather than listed ──────────────────────────────────────────────────

def test_every_registered_forge_implements_the_read():
    """WALKED FROM THE REGISTRY, not from a list of vendors: a fifth forge added without `pr_diff`
    must fail the suite rather than degrade silently on somebody's deployment."""
    import importlib
    import re as _re

    from openfactory.adapters.forge.registry import FORGES

    missing = []
    for kind, builder in FORGES.items():
        # The factory names the adapter class it constructs. Resolving it from the factory means
        # a new registry row is walked automatically — a list of vendors here would go stale the
        # day somebody adds one, which is the failure this guard exists to prevent.
        src = inspect.getsource(builder)
        found = _re.search(r"from (openfactory\.adapters\.forge\.\w+) import (\w+)", src)
        assert found, f"cannot tell which adapter the {kind!r} row builds"
        cls = getattr(importlib.import_module(found.group(1)), found.group(2))
        if not callable(getattr(cls, "pr_diff", None)):
            missing.append(kind)

    assert not missing, f"these forges cannot read a pull request's changes: {missing}"


def test_the_neutral_contract_declares_it_beside_the_other_pr_reads():
    from openfactory.adapters.forge.base import ForgeAdapter

    assert hasattr(ForgeAdapter, "pr_diff")
    doc = inspect.getdoc(ForgeAdapter.pr_diff) or ""
    assert "None" in doc and '""' in doc, (
        "the option type is the whole meaning here and the contract does not state it")


# ── 2. could-not-look and nothing-there stay different answers ──────────────────────────────────

class _Gh:
    """Stands in for `gh`, which is how the GitHub adapter reads everything."""

    def __init__(self, rc: int, out: str = "", err: str = ""):
        self.rc, self.out, self.err = rc, out, err

    def __call__(self, args, timeout=120):
        return type("P", (), {"returncode": self.rc, "stdout": self.out, "stderr": self.err})()


def _forge(monkeypatch, gh):
    from openfactory.adapters.forge.github import GitHubForge

    box = GitHubForge("acme/app", token="ghs_test")
    monkeypatch.setattr(box, "_gh", gh)
    return box


def test_a_refused_read_is_NONE(monkeypatch):
    box = _forge(monkeypatch, _Gh(1, err="could not resolve to a Repository"))

    assert box.pr_diff(pr="https://x/pr/9") is None


def test_a_pull_request_that_changes_nothing_is_EMPTY_not_none(monkeypatch):
    """`gh` exits ZERO with empty output for a pull request that genuinely changes nothing.
    Reporting that as a failed read — or the reverse — is the whole defect this guards."""
    box = _forge(monkeypatch, _Gh(0, out=""))

    assert box.pr_diff(pr="https://x/pr/9") == ""


def test_a_real_diff_comes_back(monkeypatch):
    box = _forge(monkeypatch, _Gh(0, out="diff --git a/x b/x\n+one line\n"))

    assert "+one line" in box.pr_diff(pr="https://x/pr/9")


def test_a_large_diff_is_cut_and_SAYS_SO(monkeypatch):
    """A diff that stops mid-hunk with nothing saying so reads as a change that ends there — a
    reader concludes the pull request does less than it does.

    THE HEAD IS KEPT, NOT THE TAIL, and the fixture is distinguishable so the guard can tell:
    this is the opposite of a log, where the end is the interesting part. The first hunks of a
    diff are the change; the tail is usually lockfiles and generated files."""
    body = "THE-CHANGE " + ("filler " * 800) + "THE-LOCKFILE"
    box = _forge(monkeypatch, _Gh(0, out=body))

    got = box.pr_diff(pr="https://x/pr/9", max_chars=200)

    assert len(got) < len(body)
    assert "THE-CHANGE" in got, "the head was dropped — the change went and the lockfiles stayed"
    assert "THE-LOCKFILE" not in got
    assert "NOT the whole change" in got and str(len(body)) in got


def test_the_truncation_marker_has_ONE_home():
    """Both vendors truncate; two markers would be two sentences a reader has to learn."""
    from openfactory.adapters.forge import azure_devops, base, github

    assert hasattr(base, "truncated")
    for mod in (github, azure_devops):
        src = inspect.getsource(mod)
        assert "NOT the whole change" not in src, (
            f"{mod.__name__} carries its own truncation sentence beside the shared one")


# ── 3. it is fetched where the question is asked, and nowhere else ──────────────────────────────

class _Forge:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def pr_diff(self, *, pr, repo="", max_chars=0):
        self.asked.append(pr)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _gathered(monkeypatch, jobs, forge):
    from openfactory.adapters.forge import registry
    from openfactory.techlead import conversation

    monkeypatch.setattr(registry, "build_forge", lambda p, **k: forge)
    conversation._attach_diffs(type("P", (), {"name": "demo"})(), jobs)
    return jobs


AT_GATE = {"issue": "87", "action": {"kind": "merge_wait", "pr_url": "https://x/pr/9"}}
CODING = {"issue": "88", "state": "implementing"}


def test_a_job_at_the_gate_gets_its_diff(monkeypatch):
    forge = _Forge("diff --git a/x b/x")
    jobs = _gathered(monkeypatch, [dict(AT_GATE)], forge)

    assert forge.asked == ["https://x/pr/9"]
    assert jobs[0]["diff"].startswith("diff --git")


def test_and_a_job_that_is_merely_WORKING_is_not_paid_for(monkeypatch):
    """One provider call per job per question, on a credential this deployment has exhausted
    before. The question this read exists for is asked at the gate."""
    forge = _Forge("x")
    _gathered(monkeypatch, [dict(CODING)], forge)

    assert forge.asked == []


def test_the_forge_is_built_WITH_THE_FORGE_AXIS_CREDENTIAL(monkeypatch):
    """Found on the pilot, and only because the option type refused to collapse: every read came
    back `None` — "could not look" — because this built a TOKENLESS adapter, and `gh` with no
    credential cannot see a private repository at all.

    The falsifiable claim is not "a token is passed" (a stub satisfies that); it is that the token
    comes from THE FORGE AXIS, the same resolution `tracker_for` does one function up. A
    deployment whose two axes authenticate differently — which is the whole reason
    `forge_token_for` exists — would otherwise read pull requests with the tracker's credential."""
    from openfactory.adapters.forge import registry
    from openfactory.techlead import conversation

    seen: dict = {}
    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda p: "ghs_forge_axis")
    monkeypatch.setattr("openfactory.credentials.tracker_token_for", lambda p: "ghs_tracker_axis")
    monkeypatch.setattr(registry, "build_forge",
                        lambda p, **kw: (seen.update(kw), _Forge("d"))[1])

    conversation._attach_diffs(type("P", (), {"name": "demo"})(), [dict(AT_GATE)])

    assert seen.get("token") == "ghs_forge_axis", (
        f"the pull request is read with {seen.get('token')!r} — a tokenless adapter cannot see a "
        f"private repository, and the tracker's credential is the wrong axis")


def test_a_read_that_FAILED_is_recorded_as_unread_not_as_empty(monkeypatch):
    jobs = _gathered(monkeypatch, [dict(AT_GATE)], _Forge(None))

    assert jobs[0].get("diff_unread") is True
    assert "diff" not in jobs[0], "a failed read left a diff key a renderer would print as empty"


def test_a_forge_that_RAISES_costs_the_diff_and_not_the_answer(monkeypatch):
    jobs = _gathered(monkeypatch, [dict(AT_GATE)], _Forge(RuntimeError("rate limited")))

    assert jobs[0].get("diff_unread") is True


def test_no_forge_at_all_is_still_an_unread_rather_than_a_silence(monkeypatch):
    from openfactory.adapters.forge import registry
    from openfactory.techlead import conversation

    def _boom(project, **kw):
        raise RuntimeError("no forge configured")

    monkeypatch.setattr(registry, "build_forge", _boom)
    jobs = [dict(AT_GATE)]
    conversation._attach_diffs(type("P", (), {"name": "demo"})(), jobs)

    assert jobs[0].get("diff_unread") is True


# ── 4. the pack keeps the two answers apart ─────────────────────────────────────────────────────

def test_a_failed_diff_read_is_named_in_the_gaps():
    from openfactory.techlead.conversation import _gaps

    said = _gaps([{"issue": "87", "diff_unread": True}])

    assert any("could not be read" in g and "87" in g for g in said), said
    assert any("NOT 'no changes'" in g for g in said), (
        "the gap is listed and the reader is left to guess what it means")


def test_an_EMPTY_diff_gets_a_file_that_says_it_was_read():
    """A reader handed no file resolves it as "I was not shown the diff" — the opposite of what an
    empty diff means."""
    from openfactory.techlead.conversation import _diff_files

    got = _diff_files([{"issue": "87", "diff": ""}])

    assert "87" in got
    assert "changes NOTHING" in got["87"] and "not a diff nobody fetched" in got["87"]


def test_a_real_diff_becomes_its_own_file():
    from openfactory.techlead.conversation import _diff_files

    got = _diff_files([{"issue": "87", "diff": "diff --git a/x b/x\n+line"}])

    assert "+line" in got["87"]


@pytest.mark.parametrize("job", [{"issue": "87"}, {"issue": "87", "diff_unread": True}])
def test_and_a_job_with_no_diff_read_gets_no_file(job):
    """The third answer: never asked. A file for it would be a page saying nothing, which is a turn
    the model spends learning it wasted the turn."""
    from openfactory.techlead.conversation import _diff_files

    assert _diff_files([job]) == {}


def test_the_pack_writes_the_diffs_it_is_given(tmp_path):
    from openfactory.techlead import pack

    (tmp_path / ".git" / "info").mkdir(parents=True)
    into = pack.write_pack(tmp_path, floor="# Floor\nrunning", board="", thread="",
                           comments={}, verdicts={},
                           diffs={"87": "# The changes in 87\n\ndiff --git a/x b/x"}, gaps=[])

    assert (into / "diffs" / "87.md").exists()
    assert f"{into.name}/diffs/87.md" in (into / "README.md").read_text()


def test_gather_jobs_actually_FETCHES_them(monkeypatch):
    """Reachability. Every guard above drives `_attach_diffs` directly, so deleting the one line
    that CALLS it from `gather_jobs` left them all green — and the tech-lead would be back to
    judging a change it has never seen, with a full suite saying otherwise."""
    import ast

    from openfactory.techlead import conversation

    src = inspect.cleandoc("\n" + inspect.getsource(conversation.gather_jobs))
    called = {getattr(n.func, "id", "") for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.Call)}

    assert "_attach_diffs" in called, (
        "the diffs are never fetched — `_attach_diffs` is dead code the guards keep alive")
