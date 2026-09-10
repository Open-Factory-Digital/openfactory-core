"""ADR-0049 slice 3e — the two `github.com` literals on the healing path retire, and the proof.

WHAT THEY WERE. Two call sites in `runtime/temporal/activities.py` — `_child_to_todo` (a split's
child card entering TO-DO) and `scan_todo`'s stale-pickup healer — asked the tracker for the
ticket's URL and, if it could not say, COMPOSED one: `https://github.com/{repo}/issues/{n}`. Each
carried a `# vendor-url-ok:` marker so the vendor-URL ratchet would let it stand. Slice 3e's
condition for retiring them was a test showing the GitHub row answers on every path the healer
takes, and this is it.

**AND THE LITERAL WAS NOT MERELY REDUNDANT.** It resolved a bare ref through `_ref_repo`, whose
default is the FORGE's repository first and the tracker's second. On a project whose issues live
in one repository and whose code lives in another — which is what those two fields being separate
MEANS — the fallback pointed at the code repository for an issue that is not there. The port
resolves the same ref through the tracker's own repo, which is where the issue is. So retiring the
literal is not a tidy-up; it closes a link that went to the wrong place, silently, on exactly the
deployments that took the trouble to configure both.

Every other consumer in the platform already asks the port directly (`actions/catalog.py`,
`product/module.py`, `adapters/tracker/github.py`). These two were the last composers.
"""

from __future__ import annotations

import inspect
import textwrap

import pytest

from openfactory.adapters.tracker.github import GitHubIssuesTracker
from openfactory.runtime.temporal import activities as act

# ── 1. the row answers every shape the two call sites hand it ───────────────────────────────────

@pytest.mark.parametrize("ref, expected", [
    ("12", "https://github.com/o/r/issues/12"),                  # bare, as the board reports it
    ("#12", "https://github.com/o/r/issues/12"),                 # the human decoration
    ("o/r#12", "https://github.com/o/r/issues/12"),              # qualified, same repo (C-18)
    ("other/web#3", "https://github.com/other/web/issues/3"),    # qualified, ANOTHER repo
])
def test_the_row_answers_every_ref_shape_the_healing_path_hands_it(ref, expected, monkeypatch):
    """`canonical_ref` and `split_repo_ref` between them produce exactly these four shapes, and a
    URL that is empty on any of them is a card the board cannot be asked to add."""
    monkeypatch.delenv("GH_HOST", raising=False)
    monkeypatch.delenv("GITHUB_HOST", raising=False)

    said = GitHubIssuesTracker("o/r").ticket_url(ref)

    assert said, f"the row said nothing for {ref!r} — the literal was covering for this"
    assert said == expected


def test_the_row_honours_the_HOST_the_literal_never_did(monkeypatch):
    """The reason this is not a matter of taste. A GitHub Enterprise deployment is not on
    github.com, and the composed literal said github.com unconditionally — where a same-named
    repository may belong to somebody else."""
    monkeypatch.setenv("GH_HOST", "github.acme.example")

    assert GitHubIssuesTracker("o/r").ticket_url("12") == (
        "https://github.acme.example/o/r/issues/12")


# ── 2. the finding: the literal named the wrong repository ──────────────────────────────────────

def test_the_literal_resolved_a_bare_ref_through_the_FORGE_and_the_issue_is_not_there():
    """`_ref_repo` — what the healer used to compose its fallback — defaults to the forge's
    repository, and only then the tracker's. That is right for a clone and wrong for an issue
    URL: the issue lives where the TRACKER says. The two answers differ exactly on a project
    that declares both, which is the multi-repo setup C-18 exists for."""
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.runtime.card_repo import _ref_repo

    project = Project(name="p", repo_path="/tmp/p",
                      tracker=ProviderRef(kind="github", repo="acme/issues"),
                      forge=ProviderRef(kind="github", repo="acme/code"))

    composed_repo, bare = _ref_repo(project, "12")
    assert (composed_repo, bare) == ("acme/code", "12"), (
        "the fallback's own resolution changed — the finding below is about this default")

    said = GitHubIssuesTracker("acme/issues").ticket_url("12")
    assert said == "https://github.com/acme/issues/issues/12", (
        "the port must answer the repository the ISSUE lives in")
    assert said != f"https://github.com/{composed_repo}/issues/{bare}", (
        "the composed literal and the port agree here, so this test proves nothing — check "
        "whether _ref_repo's precedence changed")


# NOTE: what the helper does when the port cannot say — nothing, and never an exception —
# is `test_the_card_moves_even_when_the_link_cannot_be_built.py`'s property, and it stays
# there. Two copies of one test is how a surface and its engine come to disagree.

# ── 3. the literals are gone, and stay gone ─────────────────────────────────────────────────────

@pytest.mark.parametrize("where", ["_child_to_todo", "scan_todo", "_ticket_url"])
def test_no_vendor_URL_is_composed_on_the_healing_path_any_more(where):
    """CODE, NOT PROSE. The paragraphs above and in the module explain the retirement by naming
    the host they removed, and a raw source scan is satisfied by a comment — the trap
    `conftest.code_only` exists for, whose docstring lists four earlier instances."""
    from tests.conftest import code_only

    src = code_only(textwrap.dedent(inspect.getsource(getattr(act, where))))

    assert "github.com" not in src, (
        f"{where} composes a github.com URL again — ask `TrackerAdapter.ticket_url`, which "
        f"answers for every vendor and honours the host")


def test_the_vendor_url_markers_left_with_the_literals_they_excused():
    """A marker that excuses nothing is prose claiming a rule was considered. Both were on the
    lines this slice deleted."""
    assert "vendor-url-ok" not in inspect.getsource(act), (
        "a `# vendor-url-ok` marker survives in the activities module with no literal under it")
