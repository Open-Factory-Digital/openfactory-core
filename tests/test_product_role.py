"""The product role over `ask()` — what reaches the harness, and what comes back.

The recording harness only implements `ask()`, which is all a judging role needs, and it records
the prompts so the tests can assert that the ROLE FILE and the requirements INDEX actually reach the
model. A prompt that silently lost its role file would still produce plausible answers — which is
exactly why it needs asserting rather than eyeballing.
"""

from __future__ import annotations

import json

import pytest

from openfactory.contracts import AgentRunResult
from openfactory.product.corpus import Corpus, Requirement
from openfactory.product.role import ProductRole, requirement_index


class _Harness:
    name = "recording"

    def __init__(self, answer: str = "ok") -> None:
        self.prompts: list[str] = []
        self.phases: list[str] = []
        self.answer = answer

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append(prompt)
        self.phases.append(phase)
        return AgentRunResult(ok=True, summary=self.answer)


class _Sandbox:
    def run(self, **kw):
        return 0, ""


def _ws():
    from openfactory.adapters.sandbox.base import Workspace

    return Workspace(path="/tmp", branch="main", base_branch="main")


def _req(n, title="a thing", status="accepted", **kw):
    return Requirement(number=n, slug="x", path=f"{n:04d}-x.md", title=title, status=status, **kw)


def _corpus(*reqs):
    return Corpus(requirements=list(reqs))


def _role(answer="ok", corpus=None):
    h = _Harness(answer)
    return ProductRole(h, corpus=corpus or _corpus(_req(1))), h


def _call(role, what, **kw):
    return getattr(role, what)(sandbox=_Sandbox(), workspace=_ws(), **kw)


# ── the index ───────────────────────────────────────────────────────────────────────────────────

def test_the_index_says_where_to_look_not_what_the_documents_say():
    """Dumping the corpus into every prompt would cost more with every requirement ever written —
    the opposite of what this platform sells. The index carries the FILE so the agent can open it."""
    body = "the entire text of the requirement, which must not be inlined"
    idx = requirement_index(_corpus(_req(1, "Immutable statements", body=body)))
    assert "REQ-0001" in idx and "Immutable statements" in idx
    assert "`0001-x.md`" in idx
    assert body not in idx


def test_superseded_requirements_are_kept_out_of_the_index_by_default():
    """History must never be handed to an agent as current truth."""
    idx = requirement_index(_corpus(_req(1), _req(2, "Old", status="superseded", superseded_by=1)))
    assert "REQ-0002" not in idx
    assert "REQ-0002" in requirement_index(
        _corpus(_req(1), _req(2, "Old", status="superseded", superseded_by=1)),
        include_superseded=True)


def test_an_empty_corpus_says_so_rather_than_rendering_a_blank_table():
    assert "no requirements written down yet" in requirement_index(Corpus())


# ── what reaches the harness ─────────────────────────────────────────────────────────────────────

def test_the_role_file_and_the_index_both_reach_the_model():
    role, h = _role(corpus=_corpus(_req(7, "Reconciliation is immutable")))
    _call(role, "answer", question="how do rules work?")
    prompt = h.prompts[0]
    assert "product owner" in prompt.lower()
    assert "cite" in prompt.lower()          # the rule that matters most
    assert "REQ-0007" in prompt              # the index
    assert "how do rules work?" in prompt


def test_each_operation_is_journalled_under_its_own_phase():
    """Cost telemetry is per-invocation; three operations sharing one phase name would be
    indistinguishable on the dashboard."""
    role, h = _role(answer='{"title":"t","must_be_true":["x"]}')
    _call(role, "answer", question="q")
    _call(role, "draft", request="r")
    assert h.phases == ["product_answer", "product_draft"]


# ── answering ───────────────────────────────────────────────────────────────────────────────────

def test_an_answer_comes_back_as_prose():
    role, _ = _role(answer="Rules are immutable once reconciled (REQ-0007).")
    res = _call(role, "answer", question="are rules immutable?")
    assert res.ok and "REQ-0007" in res.text


def test_a_silent_harness_is_a_failure_not_an_empty_answer():
    role, _ = _role(answer="   ")
    res = _call(role, "answer", question="q")
    assert res.ok is False and "returned nothing" in res.error


# ── drafting: conflicts are the point ───────────────────────────────────────────────────────────

def test_a_draft_carries_the_conflicts_it_found():
    """The single most valuable thing this role produces: "that contradicts REQ-0007"."""
    payload = json.dumps({
        "title": "Editable reconciled statements",
        "why": "accountants fix typos after the fact",
        "must_be_true": ["a reconciled statement can be edited by an admin"],
        "conflicts": [{"requirement": 7, "kind": "contradicts",
                       "explanation": "REQ-0007 says reconciled statements are immutable"}],
    })
    role, _ = _role(answer=f"Here you go:\n```json\n{payload}\n```")
    res = _call(role, "draft", request="let admins edit reconciled statements")
    assert res.ok
    assert res.draft.conflicts[0].requirement == 7
    assert res.draft.conflicts[0].kind == "contradicts"


def test_the_asker_is_carried_into_the_prompt():
    """A requirement nobody can trace back to a person is one nobody can question later."""
    role, h = _role(answer='{"title":"t","must_be_true":["x"]}')
    _call(role, "draft", request="r", asked_by="Alice")
    assert "Alice" in h.prompts[0]


@pytest.mark.parametrize("answer", [
    "I think we should probably allow editing, honestly",
    "",
    "```json\n{not json at all}\n```",
    '{"title": 5}',
])
def test_an_unreadable_draft_is_an_explicit_failure_never_an_empty_requirement(answer):
    """The reviewer's asymmetry: a confidently empty artefact that looks authored is far worse than
    a visible error. Nothing may be written from output nobody could read."""
    role, _ = _role(answer=answer)
    res = _call(role, "draft", request="r")
    assert res.ok is False and res.error
    assert res.raw == answer  # the raw text survives, so a human can see what happened


def test_a_draft_with_nothing_testable_is_refused():
    """Vagueness here becomes a job that parks hours later with nobody able to say whether it is
    done. Refusing it while the person who asked is still in the conversation is far cheaper."""
    role, _ = _role(answer=json.dumps({"title": "Make it better", "must_be_true": []}))
    res = _call(role, "draft", request="make it better")
    assert res.ok is False and "testable" in res.error
    assert res.draft is not None  # still returned, so the conversation can continue from it


# ── breaking a requirement into work ────────────────────────────────────────────────────────────

def _issues(*items):
    return json.dumps({"issues": list(items)})


def test_issues_are_produced_and_every_one_cites_its_requirement():
    """Nothing may appear in an issue that is not in a requirement — an issue citing nothing has
    drifted from the document it claims to execute."""
    role, _ = _role(answer=_issues(
        {"title": "Add the review queue", "objective": "o", "acceptance_criteria": ["c"],
         "target_repo": "AcmeCorp/acme-books"},
        {"title": "Badge the nav", "objective": "o", "acceptance_criteria": ["c"],
         "target_repo": "AcmeCorp/acme-front", "cites": 99},
    ))
    res = _call(role, "issues_for", requirement=_req(4), sources=["AcmeCorp/acme-books"])
    assert res.ok and len(res.issues) == 2
    assert [i.cites for i in res.issues] == [4, 4]  # the mis-cite was corrected, not trusted
    assert res.issues[1].target_repo == "AcmeCorp/acme-front"


def test_the_source_repos_reach_the_prompt_because_a_product_spans_N():
    role, h = _role(answer=_issues({"title": "t", "objective": "o", "acceptance_criteria": ["c"]}))
    _call(role, "issues_for", requirement=_req(4),
          sources=["AcmeCorp/acme-books", "AcmeCorp/acme-front"])
    assert "AcmeCorp/acme-front" in h.prompts[0]


def test_the_requirement_body_is_given_in_full_when_breaking_it_down():
    """The index is for locating; this operation is ABOUT one requirement, so it gets the text."""
    role, h = _role(answer=_issues({"title": "t", "objective": "o", "acceptance_criteria": ["c"]}))
    _call(role, "issues_for", requirement=_req(4, body="## What must be true\n- exactly this"),
          sources=[])
    assert "exactly this" in h.prompts[0]


@pytest.mark.parametrize("answer", ["not json", '{"issues": []}', '{"issues": [1, 2]}'])
def test_an_unreadable_or_empty_breakdown_files_nothing(answer):
    role, _ = _role(answer=answer)
    res = _call(role, "issues_for", requirement=_req(4), sources=[])
    assert res.ok is False and res.issues == []
