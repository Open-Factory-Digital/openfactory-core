"""What a pass DID, kept as a number instead of computed and thrown away.

THE GAP THESE CLOSE. `stream.pulses_of` already turns a harness stream into one pulse per tool
call, with the tool's name, its target, a clock where the harness stamps one, and a `key` built to
answer *"what makes two calls THE SAME call"*. `techlead/watch.read_harness` consumes those and
asks a PATHOLOGY question — is this run stuck — which is used live and then discarded.
`AgentRunMetric` keeps cost, turns and tokens.

So the per-call detail is parsed on every pass and kept by nobody, and the two questions an
operator asks about a factory — is it fast, is it cheap — have no instrument while their raw
material is already being computed.

WHAT THESE GUARD:

  * intent is read from a TABLE, not from the literal vendor name. `Pulse.name` is unnormalised by
    design and every harness spells its tools differently; a measure keyed on `"Edit"` would work
    on Claude Code and report a confident ZERO on codex, opencode and kimi — wrong in the quiet
    direction, for exactly the harnesses the agnosticism claim rests on.
  * a name the table does not know is counted AND NAMED, so "this agent did no editing" is
    distinguishable from "this harness calls it something we have not met".
  * `None` pulses (no reader) is not a row of zeros. `[]` is a measurement; `None` is not.
  * `repeated` never silently means "and the rest were distinct" — the calls whose repetition could
    not be judged are counted separately and excluded from the ratio.
"""

from __future__ import annotations

import json

import pytest

from openfactory.adapters.agent.stream import pulses_of
from openfactory.observability.trajectory import (
    EDIT,
    FIND,
    INTENTS,
    OTHER,
    READ,
    RUN,
    Trajectory,
    intent_of,
    trajectory_of,
)


class _P:
    """A pulse-shaped object. `trajectory_of` duck-types, exactly as `read_harness` does, so the
    observability layer does not import the agent adapter — and these build the shapes a real
    stream cannot conveniently produce (an unkeyed call, a clock)."""

    def __init__(self, kind, name="", target="", at=None, cost_usd=None, key=None):
        self.kind, self.name, self.target = kind, name, target
        self.at, self.cost_usd = at, cost_usd
        self._key = f"{name}:{target}" if key is None else key

    @property
    def key(self):
        return self._key


def _claude_stream(*calls: tuple[str, dict]) -> str:
    """A real Claude Code stream, so the control is not testing a fixture's idea of one."""
    lines = [json.dumps({"type": "assistant",
                         "message": {"content": [{"type": "tool_use", "name": n, "input": i}]}})
             for n, i in calls]
    lines.append(json.dumps({"type": "result", "subtype": "success", "total_cost_usd": 0.5}))
    return "\n".join(lines)


# ── the control ──────────────────────────────────────────────────────────────────────────────────

def test_control_a_real_stream_becomes_a_populated_trajectory() -> None:
    """Built from a real harness stream through the real reader. If this goes red, read it first."""
    out = _claude_stream(("Read", {"file_path": "a.py"}), ("Grep", {"pattern": "x"}),
                         ("Read", {"file_path": "a.py"}), ("Edit", {"file_path": "a.py"}))

    t = trajectory_of(pulses_of("claude_code", out))

    assert t.readable
    assert t.tool_calls == 4
    assert t.by_intent[READ] == 2 and t.by_intent[FIND] == 1 and t.by_intent[EDIT] == 1
    assert t.turns_to_first_edit is not None


# ── intent is a table, because names are the vendor's ────────────────────────────────────────────

@pytest.mark.parametrize(("name", "intent"), [
    ("Edit", EDIT), ("Write", EDIT), ("str_replace", EDIT), ("apply_patch", EDIT),
    ("Update", EDIT), ("Multi-Edit", EDIT),          # codex spells a change `kind.capitalize()`
    ("Read", READ), ("read", READ), ("notebook_read", READ),
    ("Bash", RUN), ("shell", RUN),
    ("Grep", FIND), ("codebase_search", FIND),
])
def test_a_tool_name_is_classified_whatever_the_harness_calls_it(name: str, intent: str) -> None:
    """Four harnesses, four vocabularies, one unnormalised `Pulse.name`. Keying on one vendor's
    spelling would report zero editing on the other three — silently."""
    assert intent_of(name) == intent


def test_the_table_and_the_lookup_cannot_disagree() -> None:
    """THIS IS A REGRESSION, not a hypothetical. The first version normalised only the lookup, so
    `str_replace`, `apply_patch` and `codebase_search` sat in the table with underscores the lookup
    had already stripped — three tools that could never match, reported as unclassified for ever."""
    from openfactory.observability.trajectory import _INTENT_OF, _RAW_INTENTS

    assert len(_INTENT_OF) == len(_RAW_INTENTS), "a normalisation collision ate an entry"
    for raw in _RAW_INTENTS:
        assert intent_of(raw) == _RAW_INTENTS[raw], f"{raw} is in the table and does not match"


def test_a_name_the_table_does_not_know_is_counted_and_NAMED() -> None:
    """"This agent did no editing" and "this harness calls it something we have not met" are
    different facts about different things, and only the second is a defect in this module."""
    t = trajectory_of([_P("tool", "Wibble", "x"), _P("tool", "Read", "a.py")])

    assert t.by_intent[OTHER] == 1
    assert t.unclassified_names == ("Wibble",)
    assert "Wibble" in t.note


def test_a_fully_classified_run_names_nothing() -> None:
    """The positive twin: without it, a module that named every call would pass the guard above."""
    t = trajectory_of([_P("tool", "Read", "a.py"), _P("tool", "Edit", "a.py")])

    assert t.unclassified_names == ()
    assert t.by_intent[OTHER] == 0


def test_every_intent_is_present_even_at_zero() -> None:
    """A zero must be visible. A missing key renders as nothing and reads as "not measured"."""
    t = trajectory_of([_P("tool", "Read", "a.py")])

    assert set(t.by_intent) == set(INTENTS)
    assert t.by_intent[EDIT] == 0


# ── the three states ─────────────────────────────────────────────────────────────────────────────

def test_no_reader_for_this_harness_is_not_a_row_of_zeros() -> None:
    """`pulses_of` answers None when no reader exists and `[]` when the stream held nothing — the
    distinction is that module's whole point, and collapsing it here would undo it one layer up."""
    t = trajectory_of(None)

    assert t.readable is False
    assert "could not be read" in t.note


def test_an_empty_stream_IS_a_measurement() -> None:
    """The other side. A pass that did nothing is a finding about the pass; a harness nobody can
    read is a finding about the platform."""
    t = trajectory_of([])

    assert t.readable is True
    assert t.tool_calls == 0
    assert "did no work" in t.note


def test_the_note_is_never_empty() -> None:
    """A measurement that says nothing when it measured nothing is indistinguishable from one that
    never ran — the rule `HarnessReading.note` already keeps."""
    for t in (trajectory_of(None), trajectory_of([]), trajectory_of([_P("tool", "Read", "a")])):
        assert t.note.strip()


# ── repetition, and what cannot be judged ────────────────────────────────────────────────────────

def test_the_same_call_twice_is_counted_once_as_a_repeat() -> None:
    t = trajectory_of([_P("tool", "Read", "a.py"), _P("tool", "Read", "a.py"),
                       _P("tool", "Read", "b.py")])

    assert t.tool_calls == 3
    assert t.repeated == 1


def test_a_call_the_stream_did_not_describe_is_not_counted_as_distinct(monkeypatch) -> None:
    """An empty key means repetition CANNOT be judged for that call — `stream.py` says so itself:
    "bash recorded without its command line looks identical to the next bash". Counting it as
    distinct would report a run the stream described poorly as a run that repeated nothing."""
    t = trajectory_of([_P("tool", "Bash", key=""), _P("tool", "Bash", key=""),
                       _P("tool", "Read", "a.py")])

    assert t.unkeyed == 2
    assert t.repeated == 0
    assert t.repeat_ratio == 0.0          # judged on the ONE call that could be judged


def test_the_ratio_excludes_what_could_not_be_judged() -> None:
    """Dividing by every call would dilute the number with calls nobody could assess, and the
    dilution is invisible in the result."""
    t = trajectory_of([_P("tool", "Read", "a.py"), _P("tool", "Read", "a.py"),
                       _P("tool", "Bash", key=""), _P("tool", "Bash", key="")])

    assert t.repeat_ratio == 0.5          # 1 repeat of 2 judged, not 1 of 4


def test_a_run_where_nothing_could_be_judged_reports_no_ratio() -> None:
    """None, not 0.0. Zero would read as "it repeated nothing", which was never measured."""
    assert trajectory_of([_P("tool", "Bash", key="")]).repeat_ratio is None


# ── the two numbers the operator actually wants ──────────────────────────────────────────────────

def test_turns_before_the_first_edit_are_counted() -> None:
    """"How many model steps before it started changing anything" — the exploration tax, and the
    number that separates a harness that reads three files from one that reads thirty.

    THE FIXTURE BATCHES TWO CALLS INTO ONE TURN ON PURPOSE. With one call per turn the turn count
    and the call index are the same number, so a version counting calls instead of turns would
    return the same answer and the guard would prove nothing — and a harness that batches its tool
    calls is exactly where the two diverge in the field."""
    t = trajectory_of([_P("turn"), _P("tool", "Read", "a.py"), _P("tool", "Grep", "x"),
                       _P("turn"), _P("tool", "Grep", "x"),
                       _P("turn"), _P("tool", "Edit", "a.py")])

    assert t.turns_to_first_edit == 3


def test_a_pass_that_edited_nothing_says_so_rather_than_reporting_zero() -> None:
    """Zero turns to first edit would mean it edited immediately — the opposite of the truth."""
    t = trajectory_of([_P("turn"), _P("tool", "Read", "a.py")])

    assert t.turns_to_first_edit is None
    assert "no edit" in t.note


def test_seconds_to_first_edit_needs_a_clock_and_says_nothing_without_one() -> None:
    """Only some harnesses stamp their stream. `0.0` would read as instantaneous; None reads as
    what it is — this stream cannot answer that question."""
    timed = trajectory_of([_P("tool", "Read", "a.py", at=100.0),
                           _P("tool", "Edit", "a.py", at=142.0)])
    untimed = trajectory_of([_P("tool", "Read", "a.py"), _P("tool", "Edit", "a.py")])

    assert timed.seconds_to_first_edit == 42.0
    assert untimed.seconds_to_first_edit is None


def test_a_refused_call_is_spend_and_is_not_credited_to_an_intent() -> None:
    """It never ran, so crediting it to `edit` would report editing that did not happen. But it is
    pass spent asking for a tool that was never going to arrive, so dropping it would report a
    cheaper run than the one that occurred."""
    t = trajectory_of([_P("refused", "Edit", "a.py"), _P("tool", "Read", "a.py")])

    assert t.refused == 1
    assert t.by_intent[EDIT] == 0
    assert t.tool_calls == 1
    assert "1 refused" in t.note


def test_the_spend_the_stream_reported_survives() -> None:
    """None is not zero: a provider that reports no pricing must never render as free."""
    assert trajectory_of([_P("tool", "Read", "a", cost_usd=0.25),
                          _P("tool", "Edit", "a", cost_usd=0.25)]).spent_usd == 0.5
    assert trajectory_of([_P("tool", "Read", "a")]).spent_usd is None


# ── it is pure ───────────────────────────────────────────────────────────────────────────────────

def test_reading_the_same_pulses_twice_is_identical() -> None:
    pulses = [_P("turn"), _P("tool", "Read", "a.py"), _P("tool", "Edit", "a.py")]

    assert trajectory_of(pulses) == trajectory_of(pulses)


def test_a_malformed_pulse_does_not_take_the_measurement_down() -> None:
    """Every caller is on a path where the run already happened. A summariser that raised would
    convert a finished pass into a crash, which is the trade `reading_of` already refuses."""
    class _Broken:
        kind = "tool"
        name = None          # the shape a partial stream produces

    t = trajectory_of([_Broken(), _P("tool", "Read", "a.py")])

    assert t.tool_calls == 2
    assert t.readable


def test_the_dataclass_defaults_are_the_unreadable_shape() -> None:
    """Guarded on the model rather than on one path: a `Trajectory()` built by any future caller
    must not claim to be a measurement of a run that did nothing."""
    assert Trajectory(readable=False).tool_calls == 0
    assert Trajectory(readable=False).turns_to_first_edit is None
