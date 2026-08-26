"""A verb was offered without saying what to put in it (#172).

`ActionSpec` declared `required=("project", "issue", "instruction")` — names, and nothing anywhere
saying what an `instruction` should contain. `adjust` shipped one card earlier as the verb that
lets the tech-lead ask for a CHANGE rather than only approve or discard, and the whole guidance it
came with was seven words of summary. A model told only the verb's English writes whatever reads
like a sentence, and it lands on a button a human presses.

And the other half of the same question was answered twice: `techlead/conversation._WHAT_IT_DOES`
carried a private map of when to choose each verb, beside the prompt rather than on the row. It
could disagree with the catalogue it described, and it did — `adjust` had no entry at all, so the
verb that most needed the judgment had the least of it.

Both now live on the catalogue row, which is the only thing that knows what an action needs.
"""

from __future__ import annotations

import inspect

import pytest

from openfactory import actions
from openfactory.actions.base import PARAMS, ActionSpec, Actor
from openfactory.techlead import conversation as conv

ADMIN = Actor(id="a", display="a", admin=True)


# ── 1. the hole this card was filed for ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("verb", sorted(actions.proposable(ADMIN)))
def test_every_verb_it_may_PROPOSE_says_what_to_put_in_every_parameter(verb):
    """THE GUARD THAT WOULD HAVE CAUGHT IT. A row a model is offered as a choice must state what
    each of its required parameters holds — `adjust` failed this the day it shipped."""
    spec = actions.CATALOG[verb]

    unexplained = [p for p in spec.required if not spec.prose_for(p)]

    assert not unexplained, (
        f"`{verb}` is offered to a proposer with nothing saying what to put in {unexplained} — it "
        f"will fill them in from the parameter's name")


@pytest.mark.parametrize("verb", sorted(actions.proposable(ADMIN)))
def test_and_says_when_to_choose_it_over_its_neighbours(verb):
    """`summary` says what a row does. Choosing between `adjust` and `discard` needs the other
    question answered, and answering it with the summary is how "discard" becomes a way to clear a
    queue."""
    assert actions.CATALOG[verb].choose_when, (
        f"`{verb}` is offered as a choice with no word on when it is the right one")


def test_the_two_questions_stay_different_questions():
    """A `choose_when` that merely restates the summary is the field being filled in rather than
    answered — and it would pass the guard above while telling a proposer nothing new."""
    for verb in actions.proposable(ADMIN):
        spec = actions.CATALOG[verb]
        assert spec.choose_when.strip().lower() != spec.summary.strip().lower(), (
            f"`{verb}`'s guidance is its summary again")


# ── 2. one home, not two ────────────────────────────────────────────────────────────────────────

def test_the_private_map_beside_the_prompt_is_GONE():
    """The reachability half. Leaving `_WHAT_IT_DOES` in place while adding `choose_when` would be
    the defect this card describes with one more copy of it."""
    assert not hasattr(conv, "_WHAT_IT_DOES"), (
        "the prompt still carries its own copy of what each verb is for")


def test_the_prompt_reads_the_ROW(monkeypatch):
    """Driven by CHANGING the catalogue and reading the prompt back, rather than by asserting the
    source says `CATALOG` — a guard that reads source is satisfied by an import nobody calls."""
    from openfactory.actions import catalog as table

    row = actions.CATALOG["skip"]
    # `actions.CATALOG` is a lazy VIEW over this dict, so the row is replaced where it lives.
    monkeypatch.setitem(table.CATALOG, "skip",
                        ActionSpec(name=row.name, summary=row.summary, run=row.run,
                                   required=row.required, optional=row.optional,
                                   choose_when="ONLY WHEN THE MOON IS FULL"))

    assert "ONLY WHEN THE MOON IS FULL" in conv._guidance(("skip",))


def test_a_required_parameter_is_NAMED_in_the_prompt():
    """The `adjust` hole itself, end to end: the proposer has to be told the verb takes an
    instruction and what an instruction is, or it composes the tag without one and the parse
    refuses a proposal a human was about to be offered."""
    text = conv._guidance(("adjust",))

    assert "instruction" in text
    assert PARAMS["instruction"][:40] in text, "the parameter is named and never explained"


@pytest.mark.parametrize("obvious", ["project", "issue"])
def test_and_the_two_it_already_knows_are_not(obvious):
    """`project` and `issue` are not a choice — this loop knows both. Listing them spends tokens
    inviting a proposal that restates what the prompt already established."""
    text = conv._guidance(("adjust",))

    assert f"needs {obvious}" not in text


# ── 3. the vocabulary is shared, and an override is a signal ────────────────────────────────────

def test_every_parameter_in_the_catalogue_has_a_word():
    """38 parameter names across 40 rows. A name with no prose is a form field a human is asked to
    fill in from its identifier."""
    missing = sorted({p for spec in actions.CATALOG.values()
                      for p in spec.parameters if not spec.prose_for(p)})

    assert not missing, f"nothing says what to put in {missing}"


def test_the_shared_word_is_not_copied_onto_rows_that_agree_with_it():
    """`project` is required by nearly every row. The reason it is shared is that 40 copies is 39
    chances to drift; a row that repeats the shared sentence verbatim has taken one of them."""
    echoed = [(spec.name, p) for spec in actions.CATALOG.values()
              for p, said in spec.params.items() if said == PARAMS.get(p)]

    assert not echoed, f"these rows copy the shared word instead of using it: {echoed}"


def test_a_row_that_MEANS_something_else_can_say_so():
    spec = ActionSpec(name="x", summary="s", run=actions.CATALOG["skip"].run,
                      required=("issue",), params={"issue": "the UPSTREAM ticket, not this one"})

    assert spec.prose_for("issue") == "the UPSTREAM ticket, not this one"
    assert actions.CATALOG["skip"].prose_for("issue") == PARAMS["issue"], (
        "one row's override changed what the word means for every other row")


def test_a_parameter_nobody_described_is_EMPTY_rather_than_invented():
    spec = ActionSpec(name="x", summary="s", run=actions.CATALOG["skip"].run,
                      required=("wibble",))

    assert spec.prose_for("wibble") == ""
    assert spec.described == {"wibble": ""}, (
        "an undescribed parameter vanished from `described` — a front end reads that as a "
        "parameter the action does not take")


# ── 4. served, so a front end never has to invent one ───────────────────────────────────────────

def test_the_catalogue_endpoint_serves_both():
    from openfactory.api.app import list_actions

    row = next(r for r in list_actions() if r["name"] == "adjust")

    assert row["params"]["instruction"] == PARAMS["instruction"]
    assert row["choose_when"] == actions.CATALOG["adjust"].choose_when


def test_a_row_nobody_may_propose_serves_NULL_rather_than_a_guess():
    """Most of the catalogue is never offered as a choice, so most rows have no `choose_when`. That
    must reach a front end as "nobody said" and not as an empty string it prints under a heading."""
    from openfactory.api.app import list_actions

    rows = {r["name"]: r for r in list_actions()}

    assert rows["ack"]["choose_when"] is None
    assert rows["ack"]["params"]["issue"], "a row nobody proposes still has to say what it needs"


def test_an_OPTIONAL_parameter_is_described_too():
    """Survivor of the first mutation round, and a real hole: every guard here walked `required`,
    so cutting `described` down to the required ones changed nothing. `resume` takes an optional
    `choice` and `merge` an optional `comment` — a person is shown those fields on a form, and a
    field labelled `choice` with nothing beside it is one they fill in from the identifier."""
    row = actions.CATALOG["resume"]

    assert "choice" in row.optional, "this guard is measuring nothing — `resume` lost its option"
    assert row.described.get("choice"), "an optional parameter reaches a form with no label"
    assert set(row.described) == set(row.parameters)


def test_the_ENDPOINT_serves_the_labels_with_the_staged_proposal(monkeypatch):
    """Reachability, and the second survivor. Every guard below drives `_labels_for` directly, so
    deleting the line that puts it IN the payload left them green and the panel back to bare keys.
    Driven through `_staged_suggestion`, which is what the endpoint calls."""
    import json

    from openfactory.api import app as api
    from openfactory.memory import messages as channel

    msg = channel.Message(kind=channel.SAID, text="p", ts="2026-08-20T00:00:00+00:00",
                          token=channel.suggestion_token("adjust", "87"),
                          payload=json.dumps({"suggestion": ["adjust", "87"],
                                              "params": {"instruction": "add the migration"}}))
    monkeypatch.setattr(channel, "staged", lambda p, **k: (msg, ""))

    served = api._staged_suggestion("demo", channel)

    assert served["labels"]["instruction"] == PARAMS["instruction"], (
        "the panel is sent a proposal it can only render as bare keys")


def test_the_staged_proposal_carries_the_label_for_what_it_will_do():
    from openfactory.api.app import _labels_for

    assert _labels_for("adjust")["instruction"] == PARAMS["instruction"]


def test_and_a_verb_this_deployment_does_not_have_is_an_empty_MAPPING():
    """A staged row from a deployment that has since dropped the action. `{}` renders as the bare
    keys, which is the old behaviour; a raise here would take the whole panel down."""
    from openfactory.api.app import _labels_for

    assert _labels_for("no_such_action") == {}


def test_the_page_paints_the_label_and_decides_NOTHING_about_it():
    """The page may not grow a second opinion about what an `instruction` is — that is the copy
    this card removed, reappearing in JavaScript."""
    import re
    from pathlib import Path

    from openfactory import api

    page = (Path(inspect.getfile(api)).parent / "panel.html").read_text()
    code = "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in page.splitlines())
    block = code[code.index("const detail="):code.index("const detail=") + 400]

    assert "_staged.labels" in code, "the label the server sends is never read"
    assert "lbl[k]" in block, "the label is fetched and not painted"
    for judging in ("instruction", "adjust", "ticket", "registry"):
        assert judging not in block, (
            f"the page reasons about {judging!r} instead of painting what the server sent")
