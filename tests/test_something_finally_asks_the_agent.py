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
from openfactory.adapters.agent.base import smoke_challenge, smoke_command_for

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

    walled = timeout_result("claude -p 'What is 20 plus 25?'", 45)
    assert "45" in walled[1], "the premise moved — this wall no longer mentions the number"

    answer = aa.ask(aa.Probes(smoke_command=lambda _p: "claude -p x",
                              run_in_box=lambda _c, _s: walled,
                              credential_in_box=lambda: True,
                              challenge=lambda: ("What is 20 plus 25?", "45")))

    assert answer.state == aa.REFUSED, "the timeout's own text was read as the agent's answer"
