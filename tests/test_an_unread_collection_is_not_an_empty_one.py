"""An Azure answer with no collection in it is never read as an empty collection (#249).

THE DEFECT. `AzureDevOpsClient.values()` ended

    out = got.get("value")
    return out if isinstance(out, list) else []

and `call()` documents that it *"returns the parsed body ({} when the server sends none)"*. So a
200 or 204 carrying no body at all — and any answer whose `value` is missing or is not a list —
arrived as an EMPTY COLLECTION, which every caller in this tree reads as "I looked and there is
nothing there".

WHERE THAT ENDS, traced on `main` at `525560e`:

    _evaluations ─────────────► values("policy/evaluations") ─► []
    _ci_status_from_evaluations([]) ─► "none"   ("no policy gates this merge", its own words)
    mergeable_state ──────────► "clean"
    workflow.py ──────────────► force_merge_pr ─► `bypassPolicy` with a reason

and the workflow states the premise that collapse breaks, in its own comment: *"A direct admin
merge == a plain merge on a clean PR — nothing to bypass (required checks / up-to-date / reviews
are already satisfied, else the state would be blocked/behind/dirty, not clean/unstable)."* That
premise is false whenever the policy answer was UNREADABLE rather than absent. An unread gate
became an absent gate, and the machine merged past the policies with the bypass flag set.

WHAT IS HELD HERE, by driving the REAL client and the REAL forge over the REAL HTTP seam
(`urllib.request.urlopen`), never a stand-in for either:

    the client    tells "the server sent no collection" from "the collection is empty", by name
    the merge     reports `unknown` for an unreadable policy answer, and never `clean`
    the absence   still works: a project with no branch policy is still `none`, still `clean`
                  (#184's case, which is the DEFAULT on Azure Repos, not an edge)
    the branches  answer `None` for the same shapes — the check `list_branches` used to make by
                  hand, because it alone knew about the hole, now belongs to the client

`list_branches` is the reason this is one issue and not two: its docstring already carried the
whole analysis — *"a port whose two providers disagree about which answer means 'unreadable' is
not a port"* — and paid for it alone, in one method, while `_evaluations` next door did not.
"""

from __future__ import annotations

import urllib.request

import pytest

from openfactory.adapters.azure_devops import AzureDevOpsClient, AzureDevOpsError
from openfactory.adapters.forge.azure_devops import AzureReposForge
from tests.test_the_ado_forge import PR_MERGED

#: Every raw body a server can send that is NOT a collection, with the name of the case it is.
#: The first two are what a real 204 and a real empty 200 look like on the wire; `call()` turns
#: both into `{}` by its own documented contract, which is where they become indistinguishable
#: from an answer that was read.
NOT_A_COLLECTION = [
    pytest.param("", id="no body at all (204, or a 200 that sent nothing)"),
    pytest.param("{}", id="an empty JSON object"),
    pytest.param('{"count": 0}', id="a count and no collection"),
    pytest.param('{"value": {"id": 1}}', id="a `value` that is not a list"),
    pytest.param('{"value": "none"}', id="a `value` that is a string"),
]


class _Answer:
    """What `urllib.request.urlopen` hands back — a context manager whose `read()` is bytes."""

    def __init__(self, raw: str) -> None:
        self._raw = raw.encode()

    def __enter__(self) -> _Answer:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._raw


def _server(monkeypatch, bodies: dict[str, str]) -> list[str]:
    """Answer each URL fragment with a RAW body, so the shape under test is the one the server
    actually sent rather than one a double decided to represent. Returns the urls asked."""
    asked: list[str] = []

    def urlopen(req, timeout=None):     # noqa: ARG001 — the real signature
        url = req.full_url
        asked.append(url)
        for fragment, raw in bodies.items():
            if fragment in url:
                return _Answer(raw)
        raise AssertionError(f"the adapter called an unrouted Azure DevOps url: {url}")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return asked


def _client() -> AzureDevOpsClient:
    return AzureDevOpsClient(organization="acme-ai", project="factory", token="x" * 52)


def _forge() -> AzureReposForge:
    return AzureReposForge("fx-ado", organization="acme-ai", project="factory", token="x" * 52)


# ═══ the client: a collection that is not there is not an empty collection ══════════════════════

@pytest.mark.parametrize("raw", NOT_A_COLLECTION)
def test_an_answer_with_no_collection_in_it_is_refused_by_name(monkeypatch, raw):
    """THE DEFECT, at the seam every Azure axis in this tree reads collections through."""
    _server(monkeypatch, {"policy/evaluations": raw})

    with pytest.raises(AzureDevOpsError) as refused:
        _client().values("policy/evaluations")

    said = str(refused.value)
    assert "policy/evaluations" in said, f"the refusal does not name what was asked: {said}"


@pytest.mark.parametrize("raw", ['{"value": [], "count": 0}', '{"value": []}'])
def test_a_collection_that_really_is_empty_is_still_empty(monkeypatch, raw):
    """The answer this must not spoil: on Azure Repos an empty collection is the ordinary case,
    not a rarity, and turning it into a refusal would hang every healthy deployment."""
    _server(monkeypatch, {"policy/evaluations": raw})

    assert _client().values("policy/evaluations") == []


def test_a_collection_that_is_there_is_handed_over_untouched(monkeypatch):
    _server(monkeypatch, {"git/repositories": '{"value": [{"name": "a"}, {"name": "b"}]}'})

    assert _client().values("git/repositories") == [{"name": "a"}, {"name": "b"}]


# ═══ the merge: an unread policy answer is not a clean pull request ═════════════════════════════

@pytest.mark.parametrize("raw", NOT_A_COLLECTION)
def test_an_unread_policy_answer_never_reads_as_a_clean_merge(monkeypatch, raw):
    """THE CONSEQUENCE. `clean` is what `workflow.py` acts on with `force_merge_pr`, whose
    completion carries `bypassPolicy` — so this is the one word that must never be said about a
    pull request whose policies nobody could read."""
    _server(monkeypatch, {"git/pullrequests/1": _json(PR_MERGED), "policy/evaluations": raw})

    assert _forge().mergeable_state(pr="1") == "unknown"


def test_a_project_with_no_branch_policy_is_still_clean(monkeypatch):
    """#184's case, and on Azure Repos it is the DEFAULT: a pipeline gates a pull request only by
    being named in a build-validation policy, so a project that configured none really does have
    no policy gating the merge. Refusing that would hang the watch on a healthy repository."""
    _server(monkeypatch, {"git/pullrequests/1": _json(PR_MERGED),
                          "policy/evaluations": '{"value": [], "count": 0}'})

    forge = _forge()
    assert forge.pr_ci_status(pr="1") == "none"
    assert forge.mergeable_state(pr="1") == "clean"


# ═══ the branches: the check `list_branches` made alone now belongs to the client ═══════════════

@pytest.mark.parametrize("raw", NOT_A_COLLECTION)
def test_an_unread_ref_list_is_still_an_unreadable_repository(monkeypatch, caplog, raw):
    """The behaviour `list_branches` bought with its own shape check is kept — a caller that
    believes an empty answer mints a requirement number a live `req/*` branch already claims."""
    _server(monkeypatch, {"/refs": raw})

    with caplog.at_level("WARNING"):
        assert _forge().list_branches() is None

    assert "could not list the branches" in caplog.text or "unreadable" in caplog.text


def test_a_repository_with_no_matching_branch_is_still_an_empty_list(monkeypatch):
    """The other half of that method's docstring: an unmatched prefix is an empty COLLECTION and
    a repository that does not exist is `404 TF401019`, so the two are already kept apart by the
    server — and the port must keep answering `[]` for the first."""
    _server(monkeypatch, {"/refs": '{"value": [], "count": 0}'})

    assert _forge().list_branches(prefix="req/") == []


def _json(obj: object) -> str:
    import json

    return json.dumps(obj)
