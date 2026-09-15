"""#129: one check makes a real agent call, and cannot be fooled by anything that did not.

On the published `v0.2.0` images no ticket could run and five checks were green (#122). Every one
of them proved a PROXY — the binary is on PATH, the binary starts, a credential is named, `curl`
reaches the endpoint — and each proxy runs somewhere the agent does not. `curl` in particular reads
the SYSTEM trust store and never looks at the harness runtime's own variable, which is the precise
gap the defect fell through.

THE QUESTION IS ARITHMETIC ON RANDOM OPERANDS, AND THAT IS THE WHOLE DESIGN. "Reply with OK" is
satisfied by a harness that echoes its prompt, by a stub, by a cached transcript and by a wrapper
that prints its own arguments — every one of which is a way this check passes while the agent is
unreachable, which is the failure it exists to end. A sum that appears nowhere in the question
cannot be produced by anything that did not read it and compute.
"""

from __future__ import annotations

import pytest

from openfactory import agent_answer as aa
from openfactory.adapters.agent.base import smoke_challenge, smoke_command_for, smoke_reply_for

_FIXED = lambda: ("What is 78 plus 59? Reply with the number alone.", "137")  # noqa: E731


def _probes(**over) -> aa.Probes:
    """A deployment where everything works, so each test below fails for the reason it names."""
    base = dict(
        smoke_command=lambda prompt: f"/opt/toolbox/claude -p {prompt!r}",
        run_in_box=lambda _cmd, _s: (0, "137\n"),
        credential_in_box=lambda: True,
        challenge=_FIXED,
    )
    base.update(over)
    return aa.Probes(**base)


# ── the question ────────────────────────────────────────────────────────────────────────────────

def test_the_expected_answer_is_actually_the_sum():
    """Verify the verifier: a challenge whose stated answer is wrong would report every working
    deployment as refusing."""
    for _ in range(20):
        prompt, expected = smoke_challenge()
        left, right = [int(n) for n in prompt.split("What is ")[1].split("?")[0].split(" plus ")]

        assert int(expected) == left + right, f"{prompt} -> {expected}"


def test_the_answer_is_not_in_the_question():
    """THE PROPERTY EVERYTHING RESTS ON. If the sum appeared in the prompt, a harness that echoed
    its input would pass — and so would a stub, which is how this check would become decoration."""
    for _ in range(20):
        prompt, expected = smoke_challenge()

        assert expected not in prompt, f"the answer {expected} is visible in {prompt!r}"


def test_the_operands_are_not_the_same_every_run():
    """A fixed question can be answered from a cache, or hardcoded by a well-meaning double."""
    seen = {smoke_challenge()[1] for _ in range(30)}

    assert len(seen) > 5, f"only {len(seen)} distinct answers in 30 draws: {seen}"


# ── the command each harness would run ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("module,klass", [
    ("claude_code", "ClaudeCodeAdapter"), ("codex", "CodexAdapter"),
    ("kimi", "KimiAdapter"), ("opencode", "OpenCodeAdapter")])
def test_every_shipped_harness_offers_a_smallest_call(module, klass):
    """Built through each adapter's own `_cli`, so what is exercised is the invocation a ticket
    uses — the binary at the path the box chose, its flags, its credential. A command assembled by
    hand here would prove something nothing issues, which is how #122 survived every check."""
    mod = __import__(f"openfactory.adapters.agent.{module}", fromlist=[klass])

    command = smoke_command_for(getattr(mod, klass)(), harness="/opt/tb/bin/x", prompt="Q?")

    assert command, f"{klass} offers no smallest call"
    assert "/opt/tb/bin/x" in command, f"{klass} did not use the path the box chose: {command}"
    assert "Q?" in command, f"{klass} does not carry the question: {command}"


def test_a_harness_from_elsewhere_is_allowed_not_to_offer_one():
    """NOT ADDED TO `CodingAgentAdapter`, on purpose: the protocol is what `conformance` holds
    third-party harnesses to, so a method added there retroactively fails every adapter a stranger
    has already shipped. `None` is reported, never assumed either way."""
    assert smoke_command_for(object(), harness="x", prompt="Q?") is None


# ── the three outcomes ──────────────────────────────────────────────────────────────────────────

def test_an_agent_that_answers_is_the_only_pass():
    answer = aa.ask(_probes())

    assert answer.state == aa.ANSWERED and answer.ok


def test_an_echo_of_the_QUESTION_is_not_an_answer():
    """The failure mode this check is built against, stated as a test. A harness that printed its
    own arguments — a wrapper, a stub, a `--help` — would satisfy "reply with OK"."""
    prompt, _ = _FIXED()
    answer = aa.ask(_probes(run_in_box=lambda _c, _s: (0, f"> {prompt}\n")))

    assert answer.state == aa.REFUSED, f"an echoed prompt was accepted as an answer: {answer}"
    assert not answer.ok


def test_the_v0_2_0_failure_is_reported_as_a_refusal_with_the_text_that_names_it():
    """What the deployment actually printed. The remedy has to send a reader at the trust store,
    because that is the one thing no other station could see."""
    out = ("warn: ignoring extra certs from …/extra-ca.crt, load failed: error:10000009:"
           "SSL routines:OPENSSL_internal:PEM routines\n"
           "API Error: Unable to connect to API (FailedToOpenSocket)\n")
    answer = aa.ask(_probes(run_in_box=lambda _c, _s: (1, out)))

    assert answer.state == aa.REFUSED and not answer.ok
    assert "FailedToOpenSocket" in answer.detail, "the harness's own words were dropped"
    assert "trust store" in answer.remedy, answer.remedy


def test_a_harness_that_exits_clean_without_answering_still_fails():
    """Authenticated against the wrong account, or answering from a cache. Exit zero is not the
    claim — the claim is that the question came back answered."""
    answer = aa.ask(_probes(run_in_box=lambda _c, _s: (0, "Sure! I can help with that.\n")))

    assert answer.state == aa.REFUSED and not answer.ok


def test_no_credential_is_NOT_ATTEMPTED_and_spends_nothing():
    """CI's case forever, and a fresh install's. Reporting a pass here would be the exact failure
    this issue is about; reporting a refusal would blame the agent for a question nobody asked."""
    asked = []
    answer = aa.ask(_probes(credential_in_box=lambda: False,
                            run_in_box=lambda c, _s: asked.append(c) or (0, "137")))

    assert answer.state == aa.NOT_ATTEMPTED
    assert not answer.ok, "`not attempted` must not read as proven"
    assert asked == [], "a call was made with no credential — that is money spent on a certainty"


def test_a_harness_with_no_smallest_call_is_NOT_ATTEMPTED():
    answer = aa.ask(_probes(smoke_command=lambda _p: None))

    assert answer.state == aa.NOT_ATTEMPTED and not answer.ok


def test_a_credential_probe_that_cannot_look_still_asks():
    """`None` is *could not read*, not *absent*. Refusing here would block every box this
    deployment cannot introspect, which is the false negative `box prove` already learned about."""
    answer = aa.ask(_probes(credential_in_box=lambda: None))

    assert answer.state == aa.ANSWERED


# ── reading the reply ───────────────────────────────────────────────────────────────────────────

def test_a_longer_number_containing_it_is_not_the_answer():
    """`1137` contains `137`. A substring match would accept a token count, a timestamp or a port
    as proof that the agent answered."""
    answer = aa.ask(_probes(run_in_box=lambda _c, _s: (0, "tokens: 1137\n")))

    assert answer.state == aa.REFUSED, "a digit inside a longer number was read as the answer"


def test_the_answer_is_found_inside_the_json_a_harness_streams():
    """Every shipped harness is asked for structured output, so the number arrives quoted, comma'd
    or brace'd. A guard that only accepted a bare line would fail every real deployment."""
    answer = aa.ask(_probes(
        run_in_box=lambda _c, _s: (0, '{"type":"result","result":"137","cost_usd":0.002}\n')))

    assert answer.state == aa.ANSWERED


def test_a_harness_that_HANGS_is_a_refusal_with_the_sentence_that_explains_it():
    """MEASURED, NOT IMAGINED. Pointing `NODE_EXTRA_CA_CERTS` at an empty file — exactly what
    `v0.2.0` shipped — makes the real harness sit there rather than fail: it was killed at 150s on
    this machine, while `curl` answered 405 through the same broken variable in under a second.

    So a wall is the shape this defect actually takes, and a check that only read exit codes would
    wait for a verdict the harness was never going to give."""
    from openfactory.adapters.sandbox.timeouts import timeout_result

    answer = aa.ask(_probes(run_in_box=lambda c, s: timeout_result(c, s, partial="")))

    assert answer.state == aa.REFUSED and not answer.ok
    assert str(aa.SMOKE_SECONDS) in answer.detail, answer.detail
    assert "curl" in answer.remedy, "the remedy does not say why the network station missed it"


def test_the_wall_is_this_command_s_own_and_not_the_suite_s():
    """`box_prove` runs its stations at 1800s because a client's test suite needs it. Inheriting
    that for one question turns a hung handshake into half an hour of blank terminal."""
    asked: list[int] = []
    aa.ask(_probes(run_in_box=lambda c, s: asked.append(s) or (0, "137")))

    assert asked == [aa.SMOKE_SECONDS]
    assert aa.SMOKE_SECONDS < 600, f"{aa.SMOKE_SECONDS}s is a wall nobody watches"


def test_a_wall_whose_MESSAGE_contains_the_answer_is_still_a_wall():
    """THE BUG THIS FILE SHIPPED ONCE, kept as a guard. The sandbox reports a wall as `killed
    after {seconds}s`, and the answer is a two-digit sum — so a run walled at 45 seconds, whose
    randomly drawn answer was 45, was reported ANSWERED off the timeout message's own text.

    Found by coincidence while measuring the real defect. A check that reads its own error
    message as the agent's reply is the exact failure this command exists to end, which is why
    the wall is now read before anything looks for a number."""
    from openfactory.adapters.sandbox.timeouts import timeout_result

    # THE PARTIAL OUTPUT IS WHAT MAKES THIS REACHABLE. Reading the reply whole rather than
    # searching the stream (Hermes, this branch) already stops `killed after 45s` being read as
    # the answer — but the sandbox keeps whatever the process had written, and a harness that
    # streamed its reply and THEN hung leaves a real-looking one in there. A run that was walled
    # did not answer, whatever is in its partial buffer.
    walled = timeout_result("claude -p 'What is 20 plus 25?'", 45,
                            partial='{"type":"result","result":"45"}\n')
    assert "45" in walled[1], "the premise moved — this wall no longer carries the number"

    answer = aa.ask(aa.Probes(smoke_command=lambda _p: "claude -p x",
                              run_in_box=lambda _c, _s: walled,
                              credential_in_box=lambda: True,
                              challenge=lambda: ("What is 20 plus 25?", "45")))

    assert answer.state == aa.REFUSED, "the timeout's own text was read as the agent's answer"


# ── the reply is READ, never searched for ───────────────────────────────────────────────────────

_REFUSAL = "\n".join([
    '{"type":"system","subtype":"init","session_id":"ses_02d1374e0dffe91"}',
    '{"type":"assistant","message":{"content":[{"type":"text","text":"I cannot help with that"}]}}',
    '{"type":"result","subtype":"success","result":"I cannot help with that",'
    '"duration_ms":1372,"num_turns":1,"total_cost_usd":0.0031,'
    '"usage":{"input_tokens":137,"output_tokens":6}}',
])


def test_a_refusal_is_not_an_answer_just_because_the_TOKEN_COUNT_matches():
    """THE DEFECT THIS BRANCH SHIPPED, and the third time the same class appeared in the command
    written to end it. `_answer_in` searched the whole stream with digit boundaries, and every
    shipped harness is asked for structured output — so `"input_tokens":137` satisfied a check
    looking for 137, and a refusal came back ANSWERED because the harness said how many tokens it
    had read.

    Structural, not unlucky: the sum is drawn from 22–178 and a short prompt's token count lives in
    that range. `prose_only` documents the identical mistake one file over — adapters matching
    `429` against a raw stream and catching it inside session ids."""
    answer = aa.ask(_probes(run_in_box=lambda _c, _s: (0, _REFUSAL),
                            challenge=lambda: ("What is 100 plus 37?", "137")))

    assert answer.state == aa.REFUSED, "telemetry was read as the model's reply"


def test_no_number_the_harness_MENTIONS_can_pass_over_many_draws():
    """The rate, not one example. Measured against the same envelope: the shipped search said
    ANSWERED 39 times in 2000 draws (1.9%) — every one of them a refusal reported as a working
    agent."""
    from openfactory.adapters.agent.base import reply_texts, smoke_challenge

    false_positives = sum(
        any(t.strip() == smoke_challenge()[1] for t in reply_texts(_REFUSAL)) for _ in range(500))

    assert false_positives == 0, f"{false_positives}/500 refusals read as answers"


def test_the_real_reply_is_still_found_where_each_harness_puts_it():
    """The other half: strictness that also rejected true answers would just move the failure."""
    from openfactory.adapters.agent.base import reply_texts

    for label, out in (
        ("a result envelope", '{"type":"result","result":"137","usage":{"input_tokens":41}}'),
        ("a nested content block",
         '{"type":"assistant","message":{"content":[{"type":"text","text":"137"}]}}'),
        ("a CLI that just prints it", "137\n"),
        ("a banner above the envelope", 'Warning: model substituted\n{"result":"137"}'),
    ):
        assert any(t.strip() == "137" for t in reply_texts(out)), f"missed it in {label}: {out!r}"


def test_the_stream_is_read_past_its_FIRST_object():
    """`json_envelope` answers "what did it conclude" for a single-envelope CLI. A streaming one
    emits an init event first, and the reply is never in it."""
    from openfactory.adapters.agent.base import reply_texts

    assert any(t.strip() == "137" for t in reply_texts(_REFUSAL.replace(
        '"result":"I cannot help with that"', '"result":"137"')))


def test_a_longer_number_is_not_the_answer_even_as_a_whole_reply():
    """`1137` is not `137`, and the comparison is whole-string for exactly this."""
    answer = aa.ask(_probes(run_in_box=lambda _c, _s: (0, '{"result":"1137"}'),
                            challenge=lambda: ("What is 100 plus 37?", "137")))

    assert answer.state == aa.REFUSED


# ── and the spend reaches the same books as every other spender ─────────────────────────────────

def test_a_call_that_was_MADE_is_recorded():
    """#109: a second spender keeping its own books is how the first live onboarding shipped six
    paid passes over a dashboard showing a day with no spend."""
    passes: list[int] = []
    aa.ask(_probes(on_pass=lambda: passes.append(1)))

    assert passes == [1]


def test_a_call_that_was_NEVER_MADE_is_not():
    """`not attempted` spent nothing. A row saying otherwise is a lie the dashboard cannot see
    through, and it would inflate exactly the number this command exists to make trustworthy."""
    passes: list[int] = []
    aa.ask(_probes(credential_in_box=lambda: False, on_pass=lambda: passes.append(1)))

    assert passes == []


# ── a box that never started asked nothing ──────────────────────────────────────────────────────

_NO_BOX = "a container named openfactory-myapp-prove already exists"


def test_a_box_that_never_started_is_NOT_ATTEMPTED_and_nothing_is_run_or_recorded():
    """FOUND IN REVIEW, reproduced through the real `ask`. Through a box that is not there every
    probe still answers something: the credential probe runs in the box, so it says *could not
    look* (None) and the question goes ahead; the call comes back as exit 1 with the start error
    as its output. That read as the HARNESS refusing — REFUSED, a remedy about the trust store,
    and a pass on the books for a call nobody made — while this command promises the opposite."""
    ran, passes = [], []
    answer = aa.ask(_probes(
        box_error=lambda: _NO_BOX,
        credential_in_box=lambda: None,          # what the presence probe answers through no box
        run_in_box=lambda c, _s: ran.append(c) or (1, f"the box could not be started: {_NO_BOX}"),
        on_pass=lambda: passes.append(1)))

    assert answer.state == aa.NOT_ATTEMPTED and not answer.ok
    assert _NO_BOX in answer.detail, "the reason the box gave was dropped"
    assert "box prove" in answer.remedy, answer.remedy
    assert ran == [], "a command was run in a box that is not there"
    assert passes == [], "a spend was recorded for a call nobody made"


def test_the_proof_box_says_WHY_it_did_not_start_and_nothing_when_it_did(tmp_path, monkeypatch):
    """`box answer` can refuse to run in a missing box only if the probes SAY it is missing — the
    reason lived in a closure `prove` never needed to hand out. Driven through the real
    `box_probes` with a box whose `prepare` refuses, because the claim is that wiring."""
    from types import SimpleNamespace

    from openfactory import box_prove
    from openfactory.adapters.sandbox import registry as sandboxes

    class _Box:
        def __init__(self, refusal):
            self.refusal = refusal

        def prepare(self, **_kw):
            if self.refusal:
                raise RuntimeError(self.refusal)
            return SimpleNamespace(path=str(tmp_path))

        def cleanup(self, **_kw):
            pass

        def harness_path(self, name):
            return f"/opt/tb/bin/{name}"

    monkeypatch.setattr(sandboxes, "installed_box_traits",
                        lambda _kind: SimpleNamespace(honours_image=True))
    project = SimpleNamespace(name="myapp", box=None)
    manifest = SimpleNamespace(base_branch="main", setup=[], validation={})
    for refusal in (_NO_BOX, ""):
        monkeypatch.setattr(sandboxes, "build_sandbox",
                            lambda *_a, refusal=refusal, **_kw: _Box(refusal))
        with box_prove.box_probes(project, "img", repo_path=tmp_path, manifest=manifest,
                                  key="myapp", sandbox="container") as probes:
            assert probes.box_start_error() == refusal, f"prepare refused with {refusal!r}"


# ── every shipped harness is read where IT puts the reply ──────────────────────────────────────

def _stream(*events) -> str:
    import json

    return "\n".join(json.dumps(e, separators=(",", ":")) for e in events)


def _claude(said: str, tokens: int) -> str:
    """`claude -p --output-format stream-json --verbose`, the shape `_REFUSAL` above records."""
    return _stream(
        {"type": "system", "subtype": "init", "session_id": "ses_02d1374e0dffe91"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}},
        {"type": "result", "subtype": "success", "result": said, "duration_ms": 1372,
         "usage": {"input_tokens": tokens, "output_tokens": 6}})


def _codex(said: str, tokens: int) -> str:
    """codex-cli 0.145.0's `--json` events, CAPTURED — `tests/test_agent_harness.py::_REAL_EVENTS`."""
    return _stream(
        {"type": "thread.started", "thread_id": "019f9eef-2cc2-7a11-9dae-d2998ce9bdeb"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": said}},
        {"type": "turn.completed", "usage": {"input_tokens": tokens, "cached_input_tokens": 48384,
                                             "output_tokens": 269, "reasoning_output_tokens": 0}})


def _opencode(said: str, tokens: int) -> str:
    """opencode's `run --format json` events, CAPTURED — `tests/test_opencode_harness.py::_IDS_WITH_429`."""
    sid = "ses_02d429e0dffeBgEKK74yFBlCLI"
    return _stream(
        {"type": "step_start", "timestamp": 1, "sessionID": sid,
         "part": {"type": "step-start", "id": "prt_fd2a429fe6001cYQJaMIVAC37V5"}},
        {"type": "text", "timestamp": 2, "sessionID": sid,
         "part": {"type": "text", "text": said, "id": "prt_fd429ac124f001WPNb6TDv7W8e4J"}},
        {"type": "step_finish", "timestamp": 3, "sessionID": sid,
         "part": {"type": "step-finish", "reason": "stop", "cost": 0.004,
                  "tokens": {"input": tokens, "output": 2, "cache": {"write": 0, "read": 0}}}})


def _kimi(said: str, tokens: int) -> str:
    """NOT CAPTURED: nobody has run kimi's `stream-json` yet, as its module docstring says. This is
    the shape its own `_final_text` assumes, so what is proven is that the check reads what the
    adapter reads — and nothing about the real binary."""
    return _stream({"role": "assistant", "content": said}, {"usage": {"input_tokens": tokens}})


_HARNESSES = [("claude_code", "ClaudeCodeAdapter", _claude), ("codex", "CodexAdapter", _codex),
              ("kimi", "KimiAdapter", _kimi), ("opencode", "OpenCodeAdapter", _opencode)]


def _reader(module: str, klass: str):
    adapter = getattr(__import__(f"openfactory.adapters.agent.{module}", fromlist=[klass]), klass)()
    return lambda out: smoke_reply_for(adapter, out)


@pytest.mark.parametrize("module,klass,stream", _HARNESSES)
def test_a_CORRECT_answer_is_believed_on_every_shipped_harness(module, klass, stream):
    """THE FALSE NEGATIVE THAT SHIPPED BESIDE THE FIX FOR THE FALSE POSITIVE. The generic walk over
    `_REPLY_KEYS` knows where a reply sits in Claude's envelope; codex nests it in `item` and
    opencode in `part`, so on two of the four shipped harnesses a correct `137` came back REFUSED
    with a remedy about the wrong account. Reproduced with the CAPTURED streams, then fixed by
    asking each adapter's own parser — the one a ticket's summary already goes through."""
    answer = aa.ask(_probes(run_in_box=lambda _c, _s: (0, stream("137", 41)),
                            read_reply=_reader(module, klass)))

    assert answer.state == aa.ANSWERED, f"{klass} said 137 and was not believed: {answer.detail}"


@pytest.mark.parametrize("module,klass,stream", _HARNESSES)
def test_a_refusal_is_not_an_answer_on_ANY_harness_when_the_token_count_matches(module, klass,
                                                                                  stream):
    """The first review's defect, held on every harness rather than on Claude's envelope alone:
    each stream carries the matching number in its own telemetry."""
    answer = aa.ask(_probes(run_in_box=lambda _c, _s: (0, stream("I cannot help with that", 137)),
                            read_reply=_reader(module, klass)))

    assert answer.state == aa.REFUSED, f"{klass}'s token count was read as its reply"


def test_an_adapters_EMPTY_reading_is_its_answer_and_is_not_searched_past():
    """The adapter found no reply. A generic search that second-guessed it would find whatever the
    stream happens to hold — which is exactly how a token count answered the question the first
    time."""
    answer = aa.ask(_probes(run_in_box=lambda _c, _s: (0, '{"type":"result","result":"137"}'),
                            read_reply=lambda _out: ""))

    assert answer.state == aa.REFUSED


def test_a_harness_from_elsewhere_with_no_reader_is_still_read():
    """Optional, like `smoke_command`: a third-party adapter that offers the call and not the
    reader is read the generic way rather than refused for a method nobody required of it."""
    assert smoke_reply_for(object(), '{"result":"137"}') is None
    answer = aa.ask(_probes(run_in_box=lambda _c, _s: (0, '{"type":"result","result":"137"}'),
                            read_reply=lambda out: smoke_reply_for(object(), out)))

    assert answer.state == aa.ANSWERED


# ── the command itself, where both fixes have to be wired ───────────────────────────────────────

def _box_answer(monkeypatch, *, start_error: str = ""):
    """`openfactory box answer` through the real command, with the project, the executor and the
    box replaced exactly where the command reads them. What this proves is the WIRING — the one
    thing no test of `ask` reaches, and the place both defects above would come back unseen."""
    import contextlib
    import re
    from types import SimpleNamespace

    from typer.testing import CliRunner

    from openfactory import box_prove, cli
    from openfactory.adapters.agent import registry
    from openfactory.adapters.agent.codex import CodexAdapter
    from openfactory.observability import job_record

    ran, recorded = [], []

    def run_in_box(command, _on_line, _seconds):
        ran.append(command)
        a, b = (int(n) for n in re.search(r"What is (\d+) plus (\d+)", command).groups())
        return 0, _codex(str(a + b), 41)

    @contextlib.contextmanager
    def one_box(*_a, **_kw):
        yield SimpleNamespace(harness_name=lambda: "/opt/tb/bin/codex", run_in_box=run_in_box,
                              box_start_error=lambda: start_error)

    monkeypatch.setattr(cli, "_get_project", lambda name: SimpleNamespace(name=name))
    monkeypatch.setattr(cli, "resolve_box_image", lambda *_a, **_kw: "img")
    monkeypatch.setattr(cli, "_box_kind", lambda _explicit: "container")
    monkeypatch.setattr(cli, "_credential_reached", lambda _probes: True)
    monkeypatch.setattr(registry, "build_executor", lambda _project: CodexAdapter())
    monkeypatch.setattr(box_prove, "box_probes", one_box)
    monkeypatch.setattr(job_record, "record_one_pass", lambda **kw: recorded.append(kw))
    return CliRunner().invoke(cli.app, ["box", "answer", "myapp"]), ran, recorded


def test_the_command_believes_a_codex_agent_that_answers(monkeypatch):
    result, ran, recorded = _box_answer(monkeypatch)

    assert result.exit_code == 0 and "ANSWERED" in result.output, result.output
    assert len(ran) == 1 and len(recorded) == 1, "one call, and one pass on the books"


def test_the_command_asks_nothing_in_a_box_that_never_started(monkeypatch):
    result, ran, recorded = _box_answer(monkeypatch, start_error=_NO_BOX)

    assert result.exit_code == 1 and aa.NOT_ATTEMPTED in result.output, result.output
    assert _NO_BOX in result.output
    assert ran == [] and recorded == [], "a call was run, or a spend recorded, with no box"
