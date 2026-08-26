"""C-39 — the tech-lead only saw the harness after it died.

The product owner's question was "if the harness stops because it needs something, can the
tech-lead see it?", and
the measured answer was no: `capture_output=True` means the output only exists once the process
exits, so the only thing that catches a wedged harness is the 4h wall — whose sentence then GUESSES
between three causes it cannot distinguish.

These pin the half of that this pass builds: a reader that turns any of the four harness streams
into one neutral vocabulary, and the arithmetic over it that names a stall. Two properties matter
more than any individual signal:

  * a signal that cannot be computed is REPORTED as uncomputable, never as "nothing wrong". The
    silence signal is unavailable on three of the four harnesses and the container box discards
    the transcript entirely at the wall — if either of those read as a calm agent, this module
    would be a more expensive way to be blind;
  * nothing here matches text. The `_RATE_RE` class of defect (a generated id containing `429`, an
    agent writing about rate limits) parked healthy jobs in three adapters, and a watcher reading
    the same stream is exactly where it would come back.
"""

from __future__ import annotations

import json

from openfactory.adapters.agent.stream import (
    ERROR,
    REFUSED,
    TEXT,
    TOOL,
    TURN,
    USAGE,
    Pulse,
    pulses_of,
    reading_of,
)
from openfactory.techlead.watch import (
    BLOCKED,
    HARNESS_SIGNALS,
    SILENT,
    SPINNING,
    HarnessReading,
    read_harness,
)

#: a plausible wall clock, so `_clock` accepts it as one (epoch seconds, 2026-08-06)
T0 = 1_785_000_000.0


def _lines(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events)


# ── the four streams, one vocabulary ─────────────────────────────────────────────────────────────

def _claude_assistant(*blocks: dict) -> dict:
    return {"type": "assistant", "message": {"content": list(blocks)}}


def test_claude_stream_becomes_turns_tools_and_an_end():
    out = _lines(
        {"type": "system", "subtype": "init"},
        _claude_assistant({"type": "text", "text": "let me look"},
                          {"type": "tool_use", "name": "Read", "input": {"file_path": "a.py"}}),
        {"type": "result", "subtype": "success", "total_cost_usd": 0.42},
    )
    pulses = pulses_of("claude_code", out)
    assert [p.kind for p in pulses] == [TURN, TEXT, TOOL, "end"]
    assert pulses[2].label == "Read: a.py"
    assert pulses[3].cost_usd == 0.42


def test_codex_items_become_tool_calls():
    out = _lines(
        {"type": "thread.started", "thread_id": "t1"},
        {"type": "turn.started"},
        {"type": "item.completed",
         "item": {"type": "command_execution", "command": "pytest -q", "exit_code": 0}},
        {"type": "item.completed",
         "item": {"type": "file_change", "changes": [{"path": "app.py", "kind": "edit"}]}},
        {"type": "turn.completed", "usage": {"input_tokens": 10}},
    )
    pulses = pulses_of("codex", out)
    assert [p.kind for p in pulses] == [TURN, TOOL, TOOL, USAGE]
    assert pulses[1].label == "Bash: pytest -q"
    assert pulses[2].label == "Edit: app.py"


def test_opencode_is_the_one_stream_that_carries_a_clock():
    """Everything downstream of "no event for N minutes" depends on this being real rather than
    assumed — so it is asserted, per harness, instead of hoped for."""
    out = _lines(
        {"type": "step_start", "timestamp": int(T0 * 1000), "part": {"type": "step-start"}},
        {"type": "tool_use", "timestamp": int((T0 + 5) * 1000),
         "part": {"type": "tool", "tool": "bash",
                  "state": {"status": "completed", "input": {"command": "pytest -q"}}}},
        {"type": "step_finish", "timestamp": int((T0 + 9) * 1000),
         "part": {"type": "step-finish", "cost": 0.004}},
    )
    pulses = pulses_of("opencode", out)
    assert [p.kind for p in pulses] == [TURN, TOOL, USAGE]
    assert [p.at for p in pulses] == [T0, T0 + 5, T0 + 9]
    assert pulses[1].label == "bash: pytest -q"
    assert pulses[2].cost_usd == 0.004

    assert all(p.at is None for p in pulses_of("claude_code", _lines(_claude_assistant()))), \
        "claude stamps nothing — a reader that invents a time here invents the whole signal"


def test_a_timestamp_that_is_not_a_wall_clock_is_refused():
    """opencode's own test fixtures count 1, 2, 3, and reading a sequence number as epoch seconds
    would date every event to 1970 and report a 56-year silence on a healthy run. The magnitude is
    the only thing that settles seconds-vs-milliseconds-vs-counter, so it is checked."""
    counter = _lines({"type": "step_start", "timestamp": 1, "part": {}},
                     {"type": "text", "timestamp": 2, "part": {}})
    assert [p.at for p in pulses_of("opencode", counter)] == [None, None]

    seconds = _lines({"type": "text", "timestamp": int(T0), "part": {}})
    assert pulses_of("opencode", seconds)[0].at == T0


def test_an_unknown_harness_reads_as_None_not_as_an_empty_stream():
    """`None` and `[]` are different answers: "there is no reader for this" versus "read it, it was
    empty". Collapsing them is how a harness nobody wrote a reader for reads as a quiet one."""
    assert pulses_of("some-new-harness", '{"type":"result"}') is None
    assert pulses_of("claude_code", "not json at all\n") == []


def test_prose_and_truncated_lines_are_skipped_not_fatal():
    """A CLI prints banners, and a stream read from a PREFIX ends mid-line by definition — that is
    the case a live watcher lives in, so it cannot be an error here."""
    out = ("Warning: Opus 5 not available — using Opus 4.5\n"
           + _lines(_claude_assistant({"type": "tool_use", "name": "Read", "input": {}}))
           + '\n{"type":"assis')
    assert [p.kind for p in pulses_of("claude_code", out)] == [TURN, TOOL]


def test_reading_a_prefix_gives_exactly_the_prefix_pulses():
    """The property that makes this the LIVE watcher's reader and not just a post-mortem parser:
    no terminal event required, no state carried, prefix-stable."""
    events = [_claude_assistant({"type": "tool_use", "name": "Read", "input": {"file_path": "a"}}),
              _claude_assistant({"type": "tool_use", "name": "Edit", "input": {"file_path": "b"}}),
              {"type": "result", "subtype": "success"}]
    whole = pulses_of("claude_code", _lines(*events))
    prefix = pulses_of("claude_code", _lines(*events[:2]))
    assert whole[:len(prefix)] == prefix


# ── the signals ──────────────────────────────────────────────────────────────────────────────────

def test_a_harness_that_went_quiet_is_named_with_its_measurement():
    pulses = [Pulse(TOOL, name="bash", target="pytest -q", at=T0)]
    reading = read_harness(pulses, now=T0 + 40 * 60)
    assert [s.kind for s in reading.stalls] == [SILENT]
    assert "40 min" in reading.stalls[0].detail
    assert reading.quiet_seconds == 40 * 60


def test_a_gap_inside_the_threshold_is_work_not_a_stall():
    """One slow test suite inside a cold container is minutes. Too short a threshold kills a
    legitimate pass, which is why the first cut only observes."""
    reading = read_harness([Pulse(TOOL, name="bash", target="pytest", at=T0)], now=T0 + 60)
    assert reading.stalls == ()
    assert "silence" not in reading.blind_to  # it was measured, and it was fine


def test_the_same_call_over_and_over_is_a_loop():
    pulses = [Pulse(TOOL, name="Bash", target="pytest -q") for _ in range(9)]
    reading = read_harness(pulses, now=T0)
    assert [s.kind for s in reading.stalls] == [SPINNING]
    assert "Bash: pytest -q" in reading.stalls[0].detail


def test_different_commands_of_the_same_tool_are_NOT_a_loop():
    """`Bash` twenty times is a normal pass. Counting the TOOL rather than the CALL would report a
    spin on every run that shells out, which is every run."""
    pulses = [Pulse(TOOL, name="Bash", target=f"step-{i}") for i in range(20)]
    assert read_harness(pulses, now=T0).stalls == ()


def test_calls_the_stream_did_not_describe_are_not_assumed_identical():
    """No `target` means the stream did not say what the call was. Two of those are not KNOWN to be
    the same call, and treating them as such would invent a loop out of missing data."""
    pulses = [Pulse(TOOL, name="bash") for _ in range(20)]
    assert read_harness(pulses, now=T0).stalls == ()


def test_calls_the_stream_did_not_describe_leave_the_loop_question_UNANSWERED():
    """The other half of the test above, and the half that was missing.

    Refusing to count keyless calls stops a loop being INVENTED; it does not make the question
    answerable. Twenty un-described shell-outs came back as "nothing in the stream looks like a
    stall (20 events read)" with an empty `blind_to` — a clean bill of health on a stream that
    could not answer, which is this module's own named failure mode wearing the third hat.

    Not hypothetical, and worst where it matters most: opencode's captured tool events carry
    `state: {"input": {}}` (the fixture in tests/test_opencode_harness.py), so the one harness with
    a clock is also the one most likely to produce keyless calls."""
    keyless = read_harness([Pulse(TOOL, name="bash") for _ in range(20)],
                           now=T0, grant_known=True)
    assert keyless.stalls == ()
    assert "looping" in keyless.blind_to
    assert "not a clean bill of health" in keyless.note

    out = _lines(*[{"type": "tool_use", "timestamp": int((T0 + i) * 1000),
                    "part": {"tool": "bash", "state": {"status": "completed", "input": {}}}}
                   for i in range(20)])
    through_opencode = read_harness(pulses_of("opencode", out), now=T0 + 25, grant_known=True)
    assert "looping" in through_opencode.blind_to, through_opencode.note


def test_one_answerable_half_is_enough_for_the_loop_question_to_count_as_asked():
    """…and the blindness must not swing the other way. A stream that records its arguments, or one
    that emits turns at all, HAS been looked at — flagging those as blind would print "we cannot
    see" on every healthy reading, which is how a caveat stops being read."""
    described = read_harness([Pulse(TOOL, name="Bash", target=f"step-{i}") for i in range(20)],
                             now=T0, grant_known=True)
    assert "looping" not in described.blind_to
    turns_only = read_harness([Pulse(TURN), Pulse(TEXT)], now=T0, grant_known=True)
    assert "looping" not in turns_only.blind_to


def test_turns_that_produce_no_tool_call_are_a_spin():
    pulses = []
    for _ in range(6):
        pulses += [Pulse(TURN), Pulse(TEXT)]
    reading = read_harness(pulses, now=T0)
    assert [s.kind for s in reading.stalls] == [SPINNING]
    assert "6 turns in a row" in reading.stalls[0].detail


def test_a_working_run_never_trips_the_spin_signal():
    """The card's own acceptance criterion has two halves, and this is the second: a normal run
    must NOT fire the alarm."""
    pulses = []
    for i in range(12):
        pulses += [Pulse(TURN), Pulse(TOOL, name="Edit", target=f"file{i}.py")]
    pulses.append(Pulse("end"))
    assert read_harness(pulses, now=T0, grant_known=True).stalls == ()


def test_reaching_for_an_ungranted_tool_again_and_again_is_blocked():
    """The failure `--auto` and `-y` exist to avoid, and the one that cost a whole TDD loop: the
    harness keeps asking for something nobody is going to approve. Structural — a REFUSED pulse
    exists because the tool is outside the allow-list the framework itself passed to the CLI."""
    pulses = [Pulse(REFUSED, name="Edit", target=f"f{i}.py") for i in range(4)]
    reading = read_harness(pulses, now=T0, grant_known=True)
    assert [s.kind for s in reading.stalls] == [BLOCKED]
    assert "Edit" in reading.stalls[0].detail and "4 attempts" in reading.stalls[0].detail


def test_the_read_only_planner_probing_edit_twice_is_not_blocked():
    """The planner is DENIED `Edit` by design and probes it anyway — `_parse_stream` already drops
    those from the action trace for exactly this reason. One or two is probing."""
    pulses = [Pulse(REFUSED, name="Edit", target="a.py"), Pulse(REFUSED, name="Write",
                                                               target="a.py"),
              Pulse(TOOL, name="Read", target="a.py")]
    assert read_harness(pulses, now=T0, grant_known=True).stalls == ()


def test_the_reading_never_reads_the_transcript_as_text():
    """The `_RATE_RE` defect, aimed at the watcher. A run whose ids and prose are full of `429`,
    `rate limit` and `permission denied` — the shapes that parked healthy jobs in three adapters —
    must produce no stall at all, because nothing here looks at text."""
    out = _lines(
        {"type": "step_start", "timestamp": int(T0 * 1000),
         "part": {"id": "prt_fd2a429fe6001cYQJaMIVAC37V5"}},
        {"type": "tool_use", "timestamp": int((T0 + 1) * 1000),
         "part": {"tool": "bash", "state": {"status": "completed",
                                            "input": {"command": "pytest tests/test_429.py"}}}},
        {"type": "text", "timestamp": int((T0 + 2) * 1000),
         "part": {"text": "handled the 429 rate limit; permission denied was expected"}},
        {"type": "step_finish", "timestamp": int((T0 + 3) * 1000), "part": {"cost": 0.01}},
    )
    reading = read_harness(pulses_of("opencode", out), now=T0 + 5, grant_known=True)
    assert reading.stalls == ()
    assert reading.spent_usd == 0.01


# ── blindness is reported, never rendered as health ──────────────────────────────────────────────

def test_an_empty_stream_is_blindness_not_an_idle_agent():
    """ContainerSandbox.run — the production box — converts its timeout WITHOUT the partial output
    (`timeout_result(command, timeout)`, no third argument), so at the wall the transcript is
    already gone. "The agent did nothing" would be a confident lie about the one run nobody can
    re-observe."""
    reading = read_harness([], now=T0)
    assert reading.stalls == ()
    assert reading.blind_to == HARNESS_SIGNALS
    assert "no harness events were read" in reading.note
    assert "not a clean bill of health" in reading.note


def test_an_unreadable_harness_is_blind_to_everything():
    assert read_harness(None).blind_to == HARNESS_SIGNALS


def test_a_clockless_harness_says_it_cannot_answer_the_silence_question():
    """Three of the four harnesses stamp nothing. The gap belongs in the sentence a human reads,
    not in a footnote nobody opens — a live watcher stamps arrival itself and closes it."""
    reading = read_harness(pulses_of("claude_code", _lines(
        _claude_assistant({"type": "tool_use", "name": "Read", "input": {"file_path": "a"}}))),
        now=T0, grant_known=True)
    assert "silence" in reading.blind_to
    assert "silence" in reading.note


def test_not_knowing_the_grant_is_blindness_not_good_behaviour():
    """No REFUSED pulses means EITHER "it only used what it was given" OR "nobody said what it was
    given". Absence reading as compliance is the negative-guard failure this house names."""
    assert "ungranted" in read_harness([Pulse(TOOL, name="Read", target="a")], now=T0).blind_to
    assert "ungranted" not in read_harness(
        [Pulse(TOOL, name="Read", target="a")], now=T0, grant_known=True).blind_to


def test_a_stream_with_no_tools_and_no_turns_cannot_answer_the_loop_question():
    pulses = [Pulse(ERROR), Pulse(ERROR)]
    assert "looping" in read_harness(pulses, now=T0, grant_known=True).blind_to


def test_the_note_is_never_empty_even_when_nothing_is_wrong():
    """A reader that says nothing when it found nothing is indistinguishable from one that was
    never called — and this repository has shipped that ambiguity before."""
    clean = read_harness([Pulse(TOOL, name="Edit", target="a.py", at=T0)],
                         now=T0 + 10, grant_known=True)
    assert clean.stalls == () and clean.blind_to == ()
    assert "nothing in the stream looks like a stall" in clean.note


def test_cost_is_reported_when_the_stream_reported_it_and_never_invented():
    priced = read_harness([Pulse(USAGE, cost_usd=0.4), Pulse(USAGE, cost_usd=0.1)], now=T0)
    assert priced.spent_usd == 0.5 and "$0.50" in priced.note
    unpriced = read_harness([Pulse(USAGE), Pulse(USAGE)], now=T0)
    assert unpriced.spent_usd is None and "$" not in unpriced.note


# ── one brain: whatever this says must survive the tech-lead's own classifier ────────────────────

def test_a_stall_note_never_classifies_as_something_the_factory_retries():
    """Card §4, "um cérebro só": the watcher must not become a second decision path. It does not
    decide anything — it writes a sentence that travels the ordinary park note into `classify`, so
    what is asserted here is the invariant that matters: none of these can degrade into an
    automatic retry, and the wording was chosen to avoid a rule rather than to hit one ("not
    granted", never "permission denied", which would send a human to fix infrastructure)."""
    from openfactory.techlead.classify import TRANSIENT, classify, remedy_for

    notes = [
        read_harness([Pulse(TOOL, name="bash", target="x", at=T0)], now=T0 + 3600).note,
        read_harness([Pulse(TOOL, name="Bash", target="pytest") for _ in range(9)],
                     now=T0, grant_known=True).note,
        read_harness([Pulse(REFUSED, name="Edit", target=f"f{i}") for i in range(4)],
                     now=T0, grant_known=True).note,
        read_harness([], now=T0).note,
        read_harness(None).note,
    ]
    for note in notes:
        verdict = classify(note)
        assert verdict.cause != TRANSIENT, f"{note!r} would be auto-retried"
        assert remedy_for(verdict).action != "retry", note


def test_the_WHOLE_park_note_is_never_read_as_something_the_factory_retries(monkeypatch):
    """The test above classifies the reading. `classify` never sees the reading on its own.

    What it sees is the hold note — `machine._hold` writes `f"agent stopped: {summary}"`, the
    workflow's self-heal rung reads `parked.note` and, on `transient`, waits and resumes without
    asking anybody (workflow.py `techlead-self-heal`). So the string under test has to be the whole
    summary, and when it was measured it came back `transient` → retry in 15 min: the wall's own
    wording said the task was "still running after 4h", the literal phrase the transient rule uses
    for a CI check that has not finished. A four-hour kill bought itself another four hours, while
    `test_hitting_the_wall_is_an_IMPEDIMENT_not_a_pause` stayed green because it checks
    `pause_reason` — the OTHER auto-resume mechanism.

    Driven through every adapter, because every adapter reaches the same sentence, and over both
    an empty transcript and a stall-carrying one so the appended reading is in the string too."""
    from openfactory.techlead.classify import TRANSIENT, classify, remedy_for

    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    spinning = _lines(*[_claude_assistant(
        {"type": "tool_use", "name": "Bash", "input": {"command": "npm test"}})
        for _ in range(10)])
    for stream in ("", spinning):
        code, out = _walled(stream)
        for adapter in _adapters():
            res = adapter.execute(sandbox=_FakeSandbox(out, code), workspace=_ws(),
                                  context=_ctx())
            note = f"agent stopped: {res.summary}"   # exactly what `machine._hold` parks with
            verdict = classify(note)
            who = type(adapter).__name__
            assert verdict.cause != TRANSIENT, f"{who} would be auto-retried: {note}"
            assert remedy_for(verdict).action != "retry", f"{who}: {note}"

    from openfactory.adapters.agent.claude_code import _parse_stream
    dead = f"agent stopped: {_parse_stream(1, spinning, allowed_tools=['Bash']).summary}"
    assert classify(dead).cause != TRANSIENT, dead
    assert remedy_for(classify(dead)).action != "retry", dead


# ── reachability: the call site every harness passes through ────────────────────────────────────

class _FakeSandbox:
    def __init__(self, out: str, code: int) -> None:
        self.out, self.code, self.commands = out, code, []

    def harness_path(self, name: str) -> str:
        return name

    def run(self, *, workspace, command: str, timeout: int):  # noqa: ARG002
        self.commands.append(command)
        if command.startswith("cat "):
            return 0, ""          # codex reads its last message from a file
        return self.code, self.out


def _ws():
    from openfactory.adapters.sandbox.base import Workspace

    return Workspace(path="/work", branch="b", base_branch="main")


def _ctx():
    from openfactory.adapters.agent.base import AgentContext
    from openfactory.contracts import Ticket

    return AgentContext(ticket=Ticket(id="#7", title="t", objective="o", repo="o/r"))


def _walled(stream: str = "") -> tuple[int, str]:
    from openfactory.adapters.sandbox.timeouts import AGENT_TIMEOUT, timeout_result

    return timeout_result("claude -p ...", AGENT_TIMEOUT, stream)


def _adapters():
    """EVERY shipped harness, read off the registry — a literal list of four would let a fifth
    harness reach the wall through a helper nothing here drives, and read as compliant."""
    from openfactory.adapters.agent.registry import HARNESSES

    built = [build(model="anthropic/claude-sonnet-4-5", log_dir=None, language=None,
                   role="executor") for build in HARNESSES.values()]
    assert len(built) >= 4, "the registry lost a shipped harness"
    return built


def test_the_four_hour_wall_now_reports_what_the_stream_showed(monkeypatch):
    """THE REACHABILITY GUARD. `base.wall_result` is the one function all four adapters call when
    the wall fires (codex.py, kimi.py, opencode.py, claude_code.py `_invoke_once`), so
    a reading wired anywhere else would be a capability nothing reaches — this codebase's signature
    defect, ~20 times over. Driven through each adapter's real `execute`, not the helper."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    code, out = _walled()
    for adapter in _adapters():
        who = type(adapter).__name__
        res = adapter.execute(sandbox=_FakeSandbox(out, code), workspace=_ws(), context=_ctx())
        assert res.ok is False, who
        assert "What the harness's own stream shows:" in res.summary, who
        # and the guess it used to make ALONE is still there for the case the stream cannot settle
        assert "stuck, looping" in res.summary, who


def test_each_harness_reaches_the_wall_under_a_name_its_own_reader_answers_to(monkeypatch):
    """A SECOND reachability guard, because the first one cannot see this.

    `base.wall_result` takes the harness identity from `self.name`; `pulses_of` looks that string up
    in `_READERS`. Two tables, no compiler between them — and when they disagree the reading does
    not fail, it goes BLIND, which is this module's own honest answer. So the measurement stops
    existing on that harness while every test above stays green. Verified by mutation: renaming
    `CodexAdapter.name` and `OpenCodeAdapter.name` so no reader matched broke nothing at all.

    Each is therefore driven through its own wall with its own real event shape, asserting the
    MEASUREMENT rather than the sentence that introduces it (which is present either way)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    from openfactory.adapters.agent.codex import CodexAdapter
    from openfactory.adapters.agent.kimi import KimiAdapter
    from openfactory.adapters.agent.opencode import OpenCodeAdapter

    code, out = _walled(_lines(*[{"type": "item.completed",
                                  "item": {"type": "command_execution", "command": "pytest -q"}}
                                 for _ in range(9)]))
    res = CodexAdapter(model="gpt-5").execute(sandbox=_FakeSandbox(out, code), workspace=_ws(),
                                              context=_ctx())
    assert "repeating itself" in res.summary and "Bash: pytest -q" in res.summary

    code, out = _walled(_lines(*[{"type": "tool_use", "timestamp": int((T0 + i) * 1000),
                                  "part": {"tool": "bash",
                                           "state": {"status": "completed",
                                                     "input": {"command": "pytest -q"}}}}
                                 for i in range(9)]))
    res = OpenCodeAdapter(model="anthropic/claude-sonnet-4-5").execute(
        sandbox=_FakeSandbox(out, code), workspace=_ws(), context=_ctx())
    assert "repeating itself" in res.summary and "bash: pytest -q" in res.summary

    # kimi's stream schema is UNVERIFIED — nobody has run the binary — so there is no real event
    # shape to drive it with, and inventing one would be a test asserting against a contract that
    # does not exist. The half that owes nothing to the schema is still checkable: the name it
    # hands the wall is one the reader answers to.
    assert pulses_of(KimiAdapter(model="k2").name, "") is not None


def test_the_wall_names_the_loop_instead_of_offering_three_hypotheses(monkeypatch):
    """The whole point of the card, at the one place it is reachable today: four hours of the same
    command is a fact the stream carried the entire time and nobody read."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    from openfactory.adapters.agent.claude_code import ClaudeCodeAdapter

    stream = _lines(*[_claude_assistant(
        {"type": "tool_use", "name": "Bash", "input": {"command": "npm test"}}) for _ in range(10)])
    code, out = _walled(stream)
    res = ClaudeCodeAdapter().execute(sandbox=_FakeSandbox(out, code), workspace=_ws(),
                                      context=_ctx())
    assert "repeating itself" in res.summary and "Bash: npm test" in res.summary


def test_the_wall_knows_which_tools_the_invocation_had_granted(monkeypatch):
    """`_invoke_once` is the only place that still holds the allow-list when the wall fires, so if
    it does not hand it on, the "reaching for what it was never granted" signal exists and is
    reachable by nothing. Driven through `plan()`, whose grant list is the read-only set — the
    exact invocation whose denials are otherwise invisible."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    from openfactory.adapters.agent.claude_code import ClaudeCodeAdapter

    stream = _lines(*[_claude_assistant(
        {"type": "tool_use", "name": "Edit", "input": {"file_path": f"f{i}.py"}})
        for i in range(4)])
    code, out = _walled(stream)
    res = ClaudeCodeAdapter().plan(sandbox=_FakeSandbox(out, code), workspace=_ws(),
                                   context=_ctx())
    assert "kept reaching for Edit" in res.summary
    assert "ungranted" not in res.summary  # the grant WAS known, so nothing is blind on it


def test_the_wall_on_the_container_box_says_the_record_is_missing(monkeypatch):
    """`ContainerSandbox.run` drops the partial output, so on the production box the wall arrives
    with an empty transcript. It must say the record is missing rather than describe a calm agent
    — the difference between "we cannot see" and "there was nothing to see"."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    from openfactory.adapters.agent.claude_code import ClaudeCodeAdapter

    code, out = _walled("")
    res = ClaudeCodeAdapter().execute(sandbox=_FakeSandbox(out, code), workspace=_ws(),
                                      context=_ctx())
    assert "no harness events were read" in res.summary
    assert "not a clean bill of health" in res.summary


def test_a_run_that_ends_with_no_result_event_explains_itself(monkeypatch):
    """The other death this reaches: the harness stopped mid-thought. "no result event in agent
    output" is true and tells nobody anything, while the events it DID emit are the only account
    of why."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    from openfactory.adapters.agent.claude_code import _parse_stream

    stream = _lines(*[_claude_assistant(
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "a.py"}}) for _ in range(5)])
    res = _parse_stream(0, stream, allowed_tools=["Read"])
    assert res.ok is False
    assert "What the stream shows:" in res.summary
    assert "kept reaching for Edit" in res.summary


def test_the_reading_can_never_turn_a_park_into_a_crash(monkeypatch):
    """Every caller is already on a failure path. A diagnosis that raised would replace a park with
    a bad explanation by a crash with none.

    The failure is FORCED rather than hoped for: the readers are defensive enough that no input
    found makes them throw, so a test that only fed them garbage would prove the garbage was
    handled and say nothing about the guard. `pulses_of` is patched where `reading_of` actually
    looks it up — its own module global — so the patch cannot go inert."""
    from openfactory.adapters.agent import stream as stream_module

    def boom(*_a, **_kw):
        raise RuntimeError("a vendor changed its event schema")

    monkeypatch.setattr(stream_module, "pulses_of", boom)
    reading = reading_of("claude_code", '{"type":"result"}')
    assert isinstance(reading, HarnessReading)
    assert reading.blind_to == HARNESS_SIGNALS
    assert "not a clean bill of health" in reading.note

    monkeypatch.undo()
    assert isinstance(reading_of("claude_code", "\x00 not a stream"), HarnessReading)
    assert reading_of("nope", '{"type":"result"}').blind_to == HARNESS_SIGNALS
