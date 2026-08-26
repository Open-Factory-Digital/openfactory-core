"""Arriving at a project that already exists.

The property every test here defends: **a reading of the code never becomes a promise on its own.**
Get that wrong and the factory starts defending bugs, because an accepted requirement is exactly
what it is built to defend.
"""

from __future__ import annotations

import json

import pytest

from openfactory.contracts import AgentRunResult
from openfactory.product.brownfield import (
    ASKED,
    CODE,
    TESTED,
    Baseline,
    Observation,
    milestone_files,
    render_candidate,
    render_inventory,
)
from openfactory.product.corpus import ACCEPTED, OBSERVED, load_corpus
from openfactory.product.role import ProductRole


@pytest.fixture(autouse=True)
def _this_file_speaks_portuguese(monkeypatch):
    """The premise, once: these guards assert the platform's pt-BR sentences.

    They used to inherit pt-BR from the module default. When the product's default became
    English (2026-08-14 — a default IS the product, and this one ships to clients who do not
    speak Portuguese) they went red while nothing had broken. `voice.py` resolves its language
    at CALL time (`language or DEFAULT_LANGUAGE`), so declaring it here reaches every call in
    the file without threading a keyword through each one."""
    import openfactory.product.voice as _voice

    monkeypatch.setattr(_voice, "DEFAULT_LANGUAGE", "pt-BR")



def _obs(title="Statements lock on reconcile", tier=CODE, **kw):
    kw.setdefault("behaviour", "a reconciled statement rejects further edits")
    kw.setdefault("citations", ["app/rules.py:88"])
    return Observation(title=title, evidence=tier, **kw)


def _baseline(**kw):
    kw.setdefault("observations", [_obs()])
    kw.setdefault("covered", ["reconciliation"])
    kw.setdefault("commit", "abc1234")
    return Baseline(**kw)


# ── a reading is never a promise ────────────────────────────────────────────────────────────────

def test_a_candidate_is_written_as_OBSERVED_never_accepted(tmp_path):
    """The single most important line in this module. `accepted` means the factory defends it."""
    (tmp_path / "0001-x.md").write_text(render_candidate(_obs(), number=1))
    req = load_corpus(tmp_path).by_number(1)
    assert req.status == OBSERVED
    assert req.status != ACCEPTED
    assert req.is_promise is False


def test_a_candidate_says_out_loud_that_it_is_not_a_commitment():
    body = render_candidate(_obs(), number=1)
    assert "not a commitment" in body
    assert "a bug read off the code looks exactly like a feature" in body


def test_a_candidate_records_that_nobody_asked_for_it(tmp_path):
    """"asked by: the code" is not provenance, and pretending otherwise is how an accident acquires
    authority."""
    (tmp_path / "0001-x.md").write_text(render_candidate(_obs(), number=1))
    assert "nobody" in load_corpus(tmp_path).by_number(1).asked_by


def test_what_we_write_in_a_brownfield_pass_is_readable_by_the_parser(tmp_path):
    """Same round trip the authored path has: a candidate full of parse findings would look fine to
    a human reading the markdown."""
    (tmp_path / "0007-statements-lock-on-reconcile.md").write_text(
        render_candidate(_obs(citations=["app/rules.py:88", "tests/test_rules.py::test_lock"]),
                         number=7, commit="abc1234", date="2026-07-26"))
    corpus = load_corpus(tmp_path)
    req = corpus.by_number(7)
    assert req is not None and req.status == OBSERVED
    assert req.affects == ["app/rules.py:88", "tests/test_rules.py::test_lock"]
    assert corpus.errors == []


def test_observed_entries_are_not_nagged_for_write_back(tmp_path):
    """Nothing has been executed against a reading of the code, so the rot detector must stay
    quiet — a validator that cries wolf on every candidate is one nobody reads."""
    (tmp_path / "0001-x.md").write_text(render_candidate(_obs(), number=1))
    assert not any(f.code == "no-write-back" for f in load_corpus(tmp_path).findings)


def test_observed_entries_are_counted_apart_from_decisions(tmp_path):
    """"we have 40 requirements" must not quietly mean "40 readings of the code and no decisions"."""
    (tmp_path / "0001-x.md").write_text(render_candidate(_obs(), number=1))
    summary = load_corpus(tmp_path).summary()
    assert "0 accepted" in summary and "1 observed (unconfirmed)" in summary


# ── evidence tiers ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tier,phrase", [
    (ASKED, "a person asked"),
    (TESTED, "made it a promise on purpose"),
    (CODE, "possibly accidental"),
])
def test_each_tier_says_what_it_is_worth(tier, phrase):
    assert phrase in render_candidate(_obs(tier=tier), number=1)


@pytest.mark.parametrize("junk", ["", "strong", "asked-ish", None])
def test_an_unknown_tier_degrades_DOWNWARD(junk):
    """A mislabelled reading that claimed `asked` would borrow provenance it does not have."""
    obs = Observation(title="t", evidence=junk) if junk is not None else Observation(title="t")
    assert obs.normalised().evidence == CODE


def test_the_inventory_groups_by_tier_strongest_first():
    base = _baseline(observations=[_obs("c", CODE), _obs("a", ASKED), _obs("t", TESTED)])
    text = render_inventory(base, product="books")
    assert text.index("Evidence: asked") < text.index("Evidence: tested") < text.index(
        "Evidence: code")


# ── the inventory is a reading, and says so ─────────────────────────────────────────────────────

def test_the_inventory_states_it_is_not_a_set_of_requirements():
    text = render_inventory(_baseline(), product="books", date="2026-07-26")
    assert "not a set of requirements" in text
    assert "abc1234" in text  # anchored to the commit it was read from


def test_coverage_is_declared_including_what_was_skipped():
    """A document implying completeness it does not have grants confidence exactly where none is
    warranted."""
    text = render_inventory(_baseline(covered=["billing"], not_covered=["imports", "reports"]),
                            product="books")
    assert "covered: `billing`" in text
    assert "**not** covered: `imports`" in text


def test_silence_about_coverage_is_called_out_rather_than_read_as_completeness():
    text = render_inventory(_baseline(not_covered=[]), product="books")
    assert "unverified rather than as full coverage" in text


def test_the_questions_are_presented_as_the_point_not_an_appendix():
    text = render_inventory(_baseline(questions=["is the 30-day window deliberate?"]),
                            product="books")
    assert "could not answer" in text and "need a person" in text
    assert "30-day window" in text


# ── one milestone ───────────────────────────────────────────────────────────────────────────────

def test_a_pass_produces_ONE_set_of_files_numbered_from_the_corpus():
    """A team asked to review forty requirement pull requests reviews none of them."""
    files = milestone_files(
        _baseline(observations=[_obs("first"), _obs("second"), _obs("third")]),
        product="books", first_number=8, date="2026-07-26")
    assert "baseline/inventory.md" in files
    assert "requirements/0008-first.md" in files
    assert "requirements/0009-second.md" in files
    assert "requirements/0010-third.md" in files


def test_the_milestone_parses_as_a_corpus_with_no_errors(tmp_path):
    """The end-to-end version: a whole first pass, written to disk, loads cleanly."""
    files = milestone_files(_baseline(observations=[_obs("first"), _obs("second", TESTED)]),
                            product="books", first_number=1, date="2026-07-26")
    for rel, body in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)

    corpus = load_corpus(tmp_path / "requirements")
    assert [r.number for r in corpus.requirements] == [1, 2]
    assert all(r.status == OBSERVED for r in corpus.requirements)
    assert corpus.errors == []
    assert corpus.promises() == []


def test_a_custom_layout_is_honoured():
    files = milestone_files(_baseline(), product="p", first_number=1,
                            requirements_dir="specs", baseline_dir="survey")
    assert "survey/inventory.md" in files
    assert any(k.startswith("specs/") for k in files)


# ── the announcement ────────────────────────────────────────────────────────────────────────────

def test_the_first_contact_message_is_written_for_the_CLIENT():
    """It moved to voice.py, and that move was the point: "it all arrives as a single pull request"
    is a sentence that teaches a non-technical owner this tool is not for them."""
    from openfactory.product.voice import announcement, jargon_in

    text = announcement(product="Acme Books", agent_name="Nina")
    assert jargon_in(text) == []
    assert "meu nome é Nina" in text
    assert "observado" in text                       # the distinction is explained, not hidden
    assert "o que estiver errado" in text            # …including that we will defend mistakes
    assert "quem decide são vocês" in text


def test_the_arrival_ENDS_somewhere_a_person_can_act():
    """The first version closed with "tell me where you'd like me to start", which hands the work
    back to whoever was hoping to hand it over. It proposes now, read off the board."""
    from openfactory.product.queue import Readiness
    from openfactory.product.voice import announcement

    idle = announcement(product="p", agent_name="Nina",
                        readiness=Readiness(ready=[1, 2], needs_refinement=[3]))
    assert "O que eu faria primeiro" in idle
    assert "entra na fila" in idle           # there IS ready work: propose the queue

    blocked = announcement(product="p", agent_name="Nina",
                           readiness=Readiness(ready=[], needs_refinement=[3, 4]))
    assert "critérios" in blocked            # nothing ready: the criteria are hers to write

    empty = announcement(product="p", agent_name="Nina", readiness=Readiness())
    assert "percorrer o que o produto já faz" in empty


# ── the survey operation ────────────────────────────────────────────────────────────────────────

class _Harness:
    name = "recording"

    def __init__(self, answer):
        self.prompts: list[str] = []
        self.answer = answer

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append(prompt)
        return AgentRunResult(ok=True, summary=self.answer)


class _Sandbox:
    def run(self, **kw):
        return 0, ""


def _ws():
    from openfactory.adapters.sandbox.base import Workspace

    return Workspace(path="/tmp", branch="main", base_branch="main")


def _survey(answer, **kw):
    h = _Harness(answer)
    role = ProductRole(h)
    return role.survey(sandbox=_Sandbox(), workspace=_ws(),
                       areas=kw.pop("areas", ["reconciliation"]), **kw), h


_GOOD = json.dumps({
    "observations": [{"title": "Statements lock on reconcile",
                      "behaviour": "further edits are rejected",
                      "evidence": "tested", "citations": ["tests/test_rules.py::test_lock"]}],
    "covered": ["reconciliation"], "not_covered": ["imports"],
    "questions": ["is the 30-day window deliberate?"], "commit": "abc1234"})


def test_a_survey_returns_observations_with_their_coverage():
    res, _ = _survey(_GOOD)
    assert res.ok
    assert res.baseline.observations[0].evidence == TESTED
    assert res.baseline.not_covered == ["imports"]
    assert res.baseline.questions


def test_the_prompt_forbids_phrasing_a_reading_as_a_commitment():
    _, h = _survey(_GOOD)
    prompt = h.prompts[0]
    assert "observations, not" in prompt
    assert "accident or a bug" in prompt
    assert "asked" in prompt and "tested" in prompt


def test_the_workspace_layout_reaches_the_survey():
    """A brownfield pass reads code, so the agent must be told where the code is — and which repos
    it could NOT be given."""
    _, h = _survey(_GOOD, layout="- `src/acme-books/` — the source repository")
    assert "src/acme-books/" in h.prompts[0]


@pytest.mark.parametrize("answer", ["I had a look and it seems fine", "", '{"observations": []}'])
def test_an_unreadable_or_empty_survey_writes_nothing(answer):
    res, _ = _survey(answer)
    assert res.ok is False and res.baseline is None
