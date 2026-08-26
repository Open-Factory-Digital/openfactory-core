"""The wall-clock walls, and the ONE place a timeout stops being an exception.

A hung agent used to surface as `subprocess.TimeoutExpired` propagating all the way out of the
job — so the ticket parked as a generic "errored" crash and the reason (it ran for an hour and was
killed) was lost. The tech-lead then diagnosed a crash that never happened.

So a timeout is converted, here, into a normal non-zero exit with a message that SAYS what
happened. Callers already handle non-zero exits; nobody has to learn a new failure mode, and the
message travels the existing path all the way to the tech-lead's diagnosis (the hold note becomes
the "raw failure" it reads).

`124` is the conventional shell exit code for "killed by timeout" (what `timeout(1)` returns), so
a log reader recognises it without a lookup table.
"""

from __future__ import annotations

import os

TIMEOUT_EXIT = 124

# THE agent wall. Four hours, because a coding task that has run four hours has a problem —
# it is not about to succeed on hour five, and it is burning money while it doesn't.
#
# It matters most for a harness with NO turn cap: Claude bounds effort with `--max-turns` (the
# ADR-0013 D4 budget), but Codex exposes no equivalent flag or config key, so for it this wall IS
# the bound. Rather than leave that asymmetric, the same wall applies to every harness: one
# concept, one number, and a turn-capped run still stops on turns first.
AGENT_TIMEOUT = int(os.environ.get("OPENFACTORY_AGENT_TIMEOUT", str(4 * 60 * 60)))

# THREE NESTED CLOCKS, and the order between them is a feature — so it is derived here rather than
# written as a literal in three files that drift apart.
#
#     AGENT_TIMEOUT      inside the box: the agent process itself
#     LAUNCHER_TIMEOUT   the launcher waiting for that box to stop
#     ACTIVITY_CEILING   Temporal waiting for the whole activity
#
# Only the innermost one produces an EXPLANATION. The agent wall stops a stuck run with a sentence
# that travels the normal failure path to the tech-lead and to a human. The outer two produce
# nothing useful: the launcher gives up on a task that is still working, and Temporal cancels the
# activity — on the fargate path retrying it, so the ticket restarts from scratch having explained
# nothing. Whichever clock fires first decides whether a four-hour failure teaches anybody anything.
#
# So each outer clock must be STRICTLY greater than the one inside it, by enough to cover the work
# that layer adds: the box still has to commit, push and open a PR after the agent stops, and the
# activity still has to clone and set up before the box starts. Equal values are not "safe" — they
# hand the race to the layer that stays silent.
#
# All three were wrong in different directions: the launcher and the agent were both exactly 4h, the
# activity was 4h too, and `repair_ci` sat at 2h with a 4h agent inside it — a stuck CI repair could
# only ever die the silent way.
_BOX_OVERHEAD = 15 * 60  # commit + push + PR, after the agent stops
_ORCHESTRATION_OVERHEAD = 15 * 60  # clone + setup, before the box starts

LAUNCHER_TIMEOUT = AGENT_TIMEOUT + _BOX_OVERHEAD
ACTIVITY_CEILING = LAUNCHER_TIMEOUT + _ORCHESTRATION_OVERHEAD


def timed_out(exit_code: int, output: str) -> bool:
    """Whether a sandbox result is our converted timeout (and not a command that happens to exit
    124 on its own — hence the marker in the text)."""
    return exit_code == TIMEOUT_EXIT and TIMEOUT_MARKER in (output or "")


TIMEOUT_MARKER = "OPENFACTORY_TIMEOUT:"


def timeout_result(command: str, seconds: int, partial: str = "") -> tuple[int, str]:
    """The (exit_code, output) a sandbox returns instead of raising. Keeps whatever the process
    had already written — on a long agent run that partial output is often the only record of how
    far it got."""
    head = (
        f"{TIMEOUT_MARKER} killed after {seconds}s ({seconds / 3600:.1f}h) — the command exceeded "
        f"the wall-clock wall and was terminated.\n$ {command[:400]}\n"
    )
    return TIMEOUT_EXIT, head + (partial or "")
