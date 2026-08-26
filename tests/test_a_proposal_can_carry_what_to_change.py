"""The tech-lead could propose throwing work away, and not what to change (#170).

`proposable(admin)` yielded five rows — resume, skip, merge, discard, stop — one parameter each.
`adjust`, the one verb that carries a repair instruction, was excluded by ONE filter, and that
filter was honest about its cause: `[[SUGGEST adjust #87]]` had nowhere to put a sentence.

So a senior engineer's most ordinary move — *"this is wrong, change X"* — was the one thing the
role could not offer. It could offer `discard` (throw the branch away) and `resume` (run it again,
blind), which is the shape of an assistant that can only say yes or no to work somebody else
scoped.

THE HIGHEST-AUTHORITY STEP IN THE PLAN, and the mitigations are structural rather than hopeful:
the instruction is VISIBLE on the button a person presses, the verb set is still the asker's own
`proposable(by)`, and nothing is performed by the model — it stages, a human approves, and
`run_staged` re-applies scope-then-admin to the credential that ACCEPTED.
"""

from __future__ import annotations

import json

import pytest

import openfactory.actions as actions
from openfactory.actions.base import Actor
from openfactory.memory import messages

# ── 1. exactly one row joined, and it is the right one ──────────────────────────────────────────

def test_relaxing_the_filter_admits_EXACTLY_adjust():
    """The blast radius, computed rather than assumed. Filter (2) — what a human could have typed
    — is a closed set, so widening what a proposal may CARRY cannot reach past it."""
    from openfactory.actions.floor_intents import FLOOR_ROWS
    from openfactory.contracts.commands import ACTION_OF

    typeable = set(ACTION_OF.values()) | set(FLOOR_ROWS.values())
    offered = set(actions.proposable(Actor(id="a", display="a", admin=True)))

    assert offered == {"resume", "skip", "merge", "adjust", "discard", "stop", "review"}, offered
    assert offered <= typeable, "a row outside the typed grammar became proposable"


@pytest.mark.parametrize("row", ["approve_prod", "promote", "product_release", "start", "diagnose"])
def test_and_nothing_that_spends_or_ships_came_with_it(row):
    """`approve_prod` and `promote` were never held out by ADDRESSABILITY — they are out because
    they are not in the floor grammar. Relaxing the wrong filter would have been the way to admit
    them by accident, so this asserts they are still gone."""
    assert row not in actions.proposable(Actor(id="a", display="a", admin=True))


def test_a_product_scoped_credential_is_offered_no_floor_row_at_all():
    """Filter (1) is the authority and it did not move: a credential that cannot press the button
    must not be told to ask for it."""
    who = Actor(id="p", display="p", admin=True, scopes=frozenset({"product"}))

    assert actions.proposable(who) == ()


# ── 2. the instruction survives the whole path ──────────────────────────────────────────────────

def test_a_payload_carrying_an_instruction_reads_back_with_it():
    msg = messages.Message(
        kind=messages.SAID, text="I'd send it back", ts="2026-08-20T00:00:00+00:00",
        token=messages.suggestion_token("adjust", "87"),
        payload=json.dumps({"suggestion": ["adjust", "87"],
                            "params": {"instruction": "tie finish_reason to the episode"}}))

    assert messages.read_suggestion(msg) == (
        "adjust", "87", {"instruction": "tie finish_reason to the episode"})


def test_a_proposal_staged_BEFORE_this_shipped_still_presses():
    """An old row has no `params` key at all. It must deserialise into an empty mapping, or every
    button staged before this change becomes an unreadable payload on somebody's screen."""
    msg = messages.Message(
        kind=messages.SAID, text="I'd resume it", ts="2026-08-20T00:00:00+00:00",
        token=messages.suggestion_token("resume", "87"),
        payload=json.dumps({"suggestion": ["resume", "87"]}))

    assert messages.read_suggestion(msg) == ("resume", "87", {})


def test_a_non_string_parameter_is_dropped_at_the_boundary():
    """Whatever comes back is spread into `perform(**params)`. A nested structure arriving from a
    store is a shape nobody wrote a reader for, and this is the one place it could enter."""
    msg = messages.Message(
        kind=messages.SAID, text="p", ts="2026-08-20T00:00:00+00:00",
        token=messages.suggestion_token("adjust", "87"),
        payload=json.dumps({"suggestion": ["adjust", "87"],
                            "params": {"instruction": {"nested": 1}, "keep": "text"}}))

    assert messages.read_suggestion(msg) == ("adjust", "87", {"keep": "text"})


async def test_pressing_an_adjust_reaches_perform_WITH_its_instruction(monkeypatch):
    """The reachability half. A staged `adjust` whose instruction is dropped is `perform` refusing
    a required parameter — an approval that does nothing, which is the one failure a button must
    never have."""
    from openfactory.actions import catalog
    from openfactory.memory import messages as channel

    token = channel.suggestion_token("adjust", "87")
    msg = channel.Message(kind=channel.SAID, text="p", ts="2026-08-20T00:00:00+00:00",
                          token=token,
                          payload=json.dumps({"suggestion": ["adjust", "87"],
                                              "params": {"instruction": "add the migration"}}))
    seen: dict[str, object] = {}

    async def _spy(name, *, by, **params):
        seen.update({"name": name, **params})
        return catalog.done("sent back")

    monkeypatch.setattr(channel, "staged", lambda p, **k: (msg, ""))
    monkeypatch.setattr(channel, "answer", lambda *a, **k: True)
    monkeypatch.setattr(channel, "say", lambda *a, **k: True)
    monkeypatch.setattr(actions, "perform", _spy)

    out = await catalog.run_staged(project="demo", by=actions.SYSTEM, token=token)

    assert seen == {"name": "adjust", "project": "demo", "issue": "87",
                    "instruction": "add the migration"}, seen
    assert out.ok and out.data["params"] == {"instruction": "add the migration"}


# ── 3. a human sees what they are approving ─────────────────────────────────────────────────────

def test_the_panel_paints_the_instruction_above_the_button():
    """Approving `adjust #87` without seeing the instruction is approving a blank cheque — and the
    instruction is free text composed inside a loop that has read the client's ticket comments."""
    import inspect
    import re
    from pathlib import Path

    from openfactory import api

    page = (Path(inspect.getfile(api)).parent / "panel.html").read_text()
    code = "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in page.splitlines())

    block = code[code.index("data-act=\"approveSuggestion\"") - 900:
                 code.index("data-act=\"approveSuggestion\"") + 200]
    assert "_staged.params" in block, (
        "the button is painted without what it will do — a person presses a verb and a number")
    assert "${detail}" in block, "the params are computed and never rendered"


def test_the_page_decides_nothing_about_them():
    """The server sends `params`; the page paints them. A page that filtered or reworded them
    would be a second opinion about what was proposed."""
    import inspect
    import re
    from pathlib import Path

    from openfactory import api

    page = (Path(inspect.getfile(api)).parent / "panel.html").read_text()
    code = "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in page.splitlines())
    block = code[code.index("const detail="):code.index("const detail=") + 400]

    for judging in ("instruction", "adjust", "length", "slice"):
        assert judging not in block, (
            f"the page reasons about {judging!r} instead of painting what the server sent")


# ── 4. a malformed multi-line tag is swept, not posted ──────────────────────────────────────────

def test_a_tag_carrying_a_newline_is_swept_rather_than_shown():
    """`[^\\n]` made the sweeper single-line BY CONSTRUCTION, which was fine while a tag was one
    verb and one ticket. A tag can carry a sentence now, and a sentence with a newline produced a
    tag the parser refused AND the sweeper could not see — so raw `[[SUGGEST …]]` plumbing went to
    a human as prose."""
    from openfactory.techlead.conversation import _ANY_TAG_RE

    text = "Here is what I'd do. [[SUGGEST adjust #87 tie finish_reason\nto the episode]] Thanks."

    assert "[[" not in _ANY_TAG_RE.sub("", text)


def test_and_the_sweeper_does_not_swallow_the_prose_between_two_tags():
    """Unbounded `[\\s\\S]*` would eat everything between the first `[[` and the last `]]` — the
    answer itself, on a model that wrote two bracketed things for unrelated reasons."""
    from openfactory.techlead.conversation import _ANY_TAG_RE

    text = "a [[one]] and\n\nthe paragraph that matters, then [[two]] end"
    swept = _ANY_TAG_RE.sub("", text)

    assert "the paragraph that matters" in swept
    assert "[[" not in swept


# ── 5. the fences that were not being driven ────────────────────────────────────────────────────
#
# Four mutations survived the first round. Two were the same reachability hole (nothing drove the
# WRITE path or the endpoint), one needed a non-admin actor to be visible at all, and one was an
# inert cut I replaced with a claim I can defend: what a proposal may CARRY must never intersect
# what may never be carried.

def test_what_a_proposal_may_carry_can_never_include_a_SECRET():
    """The line the widened set now draws. `_ADDRESSABLE` grew to admit an instruction — prose a
    human reads on the button — and the thing it must never grow to admit is a credential, which
    would travel through a store and onto a screen."""
    from openfactory.actions import _ADDRESSABLE, _SECRET

    assert not (_ADDRESSABLE & _SECRET), (
        f"a proposal may now carry {sorted(_ADDRESSABLE & _SECRET)} — through the message store "
        f"and onto a button")


def test_a_NON_admin_credential_is_offered_nothing_that_changes_anything():
    """Filter (1) is two checks, and every test above uses an admin — so the admin half was never
    exercised. A credential that cannot press the button must not be told to ask for it."""
    reader = Actor(id="r", display="r", admin=False)

    offered = set(actions.proposable(reader))
    gated = {n for n, spec in actions.CATALOG.items() if spec.needs_admin}

    assert not (offered & gated), f"a read-only credential is offered {sorted(offered & gated)}"


def test_the_WRITER_puts_the_instruction_in_the_payload():
    """The write half, and it was the unguarded one: `read_suggestion` and `run_staged` were both
    driven above while nothing drove the code that PUTS the instruction in the payload. Driven end
    to end through the real writer and the real reader, because the two were guarded separately
    and the wire between them was not."""
    from openfactory.actions import catalog
    from openfactory.memory import messages as channel
    from openfactory.runtime.temporal import activities

    rows: list[dict] = []

    class _Sink:
        def record(self, rec):
            rows.append({"kind": rec.kind, "pk": rec.project, "ts": rec.ts,
                         "extra": dict(rec.extra)})
            return True

    # Patched at the SOURCE module, because `messages.write` imports it inside the function
    # ([[a-negative-guard-needs-a-positive-twin]], last corollary).
    real, activities._metrics_sink = activities._metrics_sink, _Sink
    try:
        catalog._remember("demo", "I'd send it back", factory=True,
                          suggestion=("adjust", "87"),
                          params={"instruction": "tie finish_reason to the episode"})
    finally:
        activities._metrics_sink = real

    back = channel.read("demo", scan=lambda: list(rows))
    assert back, "the proposal was never written"
    assert channel.read_suggestion(back[-1]) == (
        "adjust", "87", {"instruction": "tie finish_reason to the episode"}), (
        "the instruction the tech-lead composed did not survive into the payload a button reads")


def test_the_ASK_path_hands_the_instruction_to_the_writer():
    """And the hop above it: a three-element suggestion coming back from the agent has to reach
    `_remember` as `params`, or the write half never gets the chance."""
    import ast
    import inspect

    from openfactory.actions import catalog

    src = inspect.cleandoc("\n" + inspect.getsource(catalog._ask))
    call = next((n for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_remember"
                 and any(k.arg == "suggestion" for k in n.keywords)), None)

    assert call is not None, "`_ask` no longer stages a proposal — this guard measures nothing"
    assert "params" in {k.arg for k in call.keywords}, (
        "the agent's instruction is parsed and then dropped before the store")
