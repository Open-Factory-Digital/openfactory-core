"""`openfactory box answer` — the one check that asks the agent a question and reads the reply.

WHY THIS IS NOT PART OF `box prove` (#129). That command's contract, stated in its own help and
relied on by the pickup gate, is *no agent, no tokens spent*. It is right: a gate that runs before
every card must not bill anybody. This is the other claim, and it has the other cadence — an
INSTALLATION fact, checked once after an install or an upgrade, not once per pickup. Keeping them
in separate modules is so nobody wires this into that gate by reaching for a function that was
simply nearby.

WHAT IT COST TO NOT HAVE THIS. On the published `v0.2.0` images no ticket could run — the extra-CA
file was empty and the harness runtime refuses an empty PEM (#122). Five checks watched it happen:

    doctor          → OK, 13/13          (asks whether the binary is on PATH)
    box prove       → PROVEN             (promises not to make the call)
    the network station → the endpoint answers   (probes with `curl`, which reads the SYSTEM trust
                                                  store and never looks at the harness's variable)
    the poller      → running
    CI              → green              (no workflow holds an agent credential, so nothing
                                          between a commit and a published image can make a call)

Every one of them proves a PROXY, and each proxy runs somewhere the agent does not. The row that
was empty is this one, and it is the only row a user's first ticket depends on.

NOT PROVEN IS A RESULT, and the important one. The failure this exists to end is a check that goes
green for the wrong reason, so a missing credential, a harness with no smallest call and a box that
would not start are each reported as *not attempted* — never as a pass.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

#: What the three outcomes are called, once, so the renderers cannot disagree.
ANSWERED, REFUSED, NOT_ATTEMPTED = "answered", "refused", "not attempted"

#: How long one question gets. Two-digit arithmetic with no tools and no repository answers in
#: seconds; `box_prove` runs its stations at 1800s because a client's test suite needs it, and
#: inheriting that here would turn a hung TLS handshake into a half-hour of blank terminal.
SMOKE_SECONDS = 120


@dataclass
class Answer:
    """What came back, and what a person should do about it."""

    state: str
    detail: str
    remedy: str = ""

    @property
    def ok(self) -> bool:
        """ANSWERED ALONE. `not attempted` is deliberately not ok: it is the honest report of a
        question nobody asked, and a deployment that cannot ask has not been proven able to run."""
        return self.state == ANSWERED


@dataclass
class Probes:
    """Injected, exactly as in `doctor.py` and `box_prove.py`, so every branch below is reachable
    in a test without a container, a credential or a network."""

    #: The shell for one question, or None when this harness offers no smallest call.
    smoke_command: Callable[[str], str | None]
    #: Run it inside the box the ticket would use, for at most `seconds`, and hand back
    #: `(rc, output)` — never raise. A WALL IS THE POINT, not housekeeping: measured on this
    #: machine, a harness whose `NODE_EXTRA_CA_CERTS` names an empty file does not exit with an
    #: error, it HANGS. `curl` answered 405 through the same broken variable in under a second.
    run_in_box: Callable[[str, int], tuple[int, str]]
    #: Whether the route's credential is present INSIDE the box. `None` = could not look, which is
    #: not the same as absent and must not be reported as one.
    credential_in_box: Callable[[], bool | None]
    #: `(question, the answer it must give)`. Injected so a test is deterministic; the default is
    #: random per call on purpose.
    challenge: Callable[[], tuple[str, str]] | None = None
    #: Called ONCE, and only when a call was actually made — so a deployment's books show this
    #: spender too. #109 added `record_one_pass` because a second spender keeping its own books is
    #: how the first live onboarding shipped six paid passes over a dashboard showing no spend.
    #: Not called for `not attempted`, because nothing was spent and a row saying otherwise is a
    #: lie the dashboard cannot see through.
    on_pass: Callable[[], None] | None = None
    #: Why the box could not be started, or `""` when it was. Asked FIRST: every other probe runs
    #: inside the box, and through a box that is not there each of them answers something that
    #: reads like a verdict — the credential probe says *could not look*, and the call comes back
    #: as exit 1 with the start error as its output. Read as the harness's answer, that was a
    #: REFUSED with a trust-store remedy, and a spend recorded for a call nobody made.
    box_error: Callable[[], str] | None = None
    #: The harness's OWN reading of its reply, from its adapter (`smoke_reply_for`). `None` from
    #: it means the harness offers no reader, and the generic `reply_texts` is used instead.
    read_reply: Callable[[str], str | None] | None = None


def ask(p: Probes) -> Answer:
    """Ask once, and decide only from what came back."""
    from openfactory.adapters.agent.base import smoke_challenge

    prompt, expected = (p.challenge or smoke_challenge)()

    if why := (p.box_error() if p.box_error else ""):
        return Answer(NOT_ATTEMPTED, f"the box could not be started, so nothing was asked: {why}",
                      "`openfactory box prove` starts the same box and says what stopped it — fix "
                      "that, then run this again. Nothing was spent, and nothing was proven about "
                      "the agent either way")

    present = p.credential_in_box()
    if present is False:
        return Answer(NOT_ATTEMPTED, "no harness credential reached the box, so nothing was asked",
                      "this is what `box prove`'s `harness auth` station reports on — name the "
                      "variable in the project's `box.env`, then run this again. Spending nothing "
                      "is the right outcome here; a PASS would not be")

    command = p.smoke_command(prompt)
    if command is None:
        return Answer(NOT_ATTEMPTED,
                      "this harness does not offer a smallest call, so the agent was not asked",
                      "the four harnesses the core ships implement `smoke_command`; a harness from "
                      "elsewhere is not required to, and this reports that rather than assuming "
                      "the worst or the best")

    from openfactory.adapters.sandbox.timeouts import timed_out

    rc, out = p.run_in_box(command, SMOKE_SECONDS)
    if p.on_pass:
        p.on_pass()

    # THE WALL IS READ BEFORE ANYTHING LOOKS FOR A NUMBER, and that ordering is a bug this file
    # shipped once. The sandbox reports a wall as `killed after {seconds}s`; the answer being
    # looked for is a two-digit sum — so a run walled at 45s whose drawn answer was 45 came back
    # ANSWERED, off the timeout message's own text. Found by coincidence while measuring the
    # defect below, which is the only way it was ever going to be found. A wall is never an
    # answer, and a check that reads its own error message as the agent's reply is the exact
    # failure this command exists to end.
    if timed_out(rc, out):
        # THE SHAPE THE SHIPPED DEFECT ACTUALLY TAKES. Reproduced here by pointing
        # `NODE_EXTRA_CA_CERTS` at an empty file, exactly as `v0.2.0` did: the harness did not
        # refuse, it sat there. A check that only looked at exit codes would wait forever for a
        # verdict the harness was never going to give.
        return Answer(REFUSED,
                      f"the harness never answered within {SMOKE_SECONDS}s and was killed",
                      "a HANG rather than a refusal is what a TLS or trust-store fault usually "
                      "looks like from here — the runtime is retrying a handshake that cannot "
                      "complete. `curl` finishes through the same fault in under a second, which "
                      "is why the network station cannot see this. Check `box prove`'s `trust "
                      "store` station and any proxy between the box and the endpoint")

    if _answer_in(out, expected, p.read_reply):
        return Answer(ANSWERED, f"the agent was asked `{prompt.split('?')[0]}?` and answered "
                                f"{expected} — the call completed end to end")

    if rc != 0:
        return Answer(REFUSED, f"the harness exited {rc} and never answered:\n{_tail(out)}",
                      "this is the failure no other check in this deployment can see. A TLS or "
                      "trust-store fault names itself here — look for `PEM routines`, "
                      "`FailedToOpenSocket` or a proxy's refusal in the lines above, and check "
                      "`box prove`'s `trust store` station")
    return Answer(REFUSED,
                  f"the harness exited 0 but {expected} is not in what it said:\n{_tail(out)}",
                  "a harness that succeeds without answering is usually authenticated against the "
                  "wrong account or answering from a cache. The question is arithmetic on operands "
                  "chosen at random, so nothing that did not read it can get this right")


def _answer_in(out: str, expected: str,
               read: Callable[[str], str | None] | None = None) -> bool:
    """Did the model SAY the number — not, did the number appear somewhere in the stream.

    THIS FUNCTION SHIPPED THE FAILURE THE WHOLE COMMAND EXISTS TO END. It was a digit-bounded
    `re.search` over everything the CLI printed. Every shipped harness is asked for structured
    output, and that envelope carries `input_tokens`, `output_tokens`, `duration_ms`, a cost and a
    session id — so a refusal came back ANSWERED because the harness reported how many tokens it
    had read. The sum is drawn from 22-178 and a short prompt's token count lives in that same
    range, so the collision is structural rather than unlucky: measured at **0.7% over 2000
    draws** against one realistic envelope whose reply text was `I cannot help with that`.

    `prose_only` in `adapters/agent/base.py` already documents the identical mistake — adapters
    matching `429` against a raw stream and catching it inside session ids. Same shape, twice.

    So the reply is extracted and compared WHOLE. The question asks for the number alone, with no
    words and no punctuation, so an answer that needs a substring search to find is not the answer
    that was asked for.

    READ BY THE HARNESS THAT WROTE IT, when its adapter says how (`smoke_reply`). The generic walk
    below knows where a reply sits in one harness's envelope, and on two of the four shipped ones
    it found nothing: codex nests the reply in `item` and opencode in `part`, so a correct answer
    came back REFUSED with a remedy about the wrong account. Each adapter already parses its own
    stream for a ticket, so this asks that parser. And an adapter's `""` IS its answer — it is not
    second-guessed by a search, because a second opinion from the stream is how a token count got
    in the first time.
    """
    said = read(out) if read else None
    if said is not None:
        return said.strip() == expected
    from openfactory.adapters.agent.base import reply_texts

    return any(text.strip() == expected for text in reply_texts(out))


def _tail(out: str, lines: int = 12) -> str:
    return "\n".join((out or "").splitlines()[-lines:])
