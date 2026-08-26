"""`env rehearse` lives only in the terminal, and that is a decision rather than an omission — #99.

ADR-0039 says a capability is a row in the catalogue and the front ends are mappings; ADR-0038
puts it harder — *"a capability that exists in only one channel is a capability the platform does
not have."* Four of the five `env` subcommands are rows. `rehearse` is not.

THE PRODUCT OWNER DECIDED IT STAYS THAT WAY (2026-08-08), and the reasons are measured rather than
preferred:

  THE VALUE IS THE STREAM. The round boots a box, runs a harness pass, runs the project's own
  gates and a reviewer on a synthetic ticket. It is what you run in the first meeting with the
  client's developers, and its worth is the stages appearing one at a time on a screen everybody
  is watching. A button trades that for "clicked, now wait".

  A BUTTON COULD ONLY TIME OUT. The round takes minutes; no deployment can be asked to hold an
  HTTP request open for it. That is not a fact about one hosting provider — a proxy, a load
  balancer and a browser tab each have their own ceiling, and `uvicorn` on a laptop has none at
  all, so the defect would pass where we develop and fail where clients run. `product_needs_action`
  and `product_baseline` are already CLI verbs for exactly this reason.

WHAT THIS FILE IS FOR. An exception nobody asserts is indistinguishable from a capability
somebody forgot to expose, and the difference decides whether the next person "fixes" it. So the
exception is written down, checked, and made to fail the day it stops being true — the same
staleness rule `test_provider_seams` uses for its allowlist.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The `env` subcommand that is deliberately terminal-only, and why. A dict rather than a set so
#: the reason travels with the name — an exception without one is a pass.
TERMINAL_ONLY = {
    "rehearse": (
        "the round's value is the stream of stages in front of a client's developers, and it "
        "takes minutes — longer than any request should be held open. The product owner decided 2026-08-08."
    ),
}


def _env_subcommands() -> set[str]:
    """Every `openfactory env <name>`, read off the CLI rather than listed here."""
    tree = ast.parse((ROOT / "openfactory/cli.py").read_text())
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call)
                    and getattr(dec.func, "attr", "") == "command"
                    and getattr(dec.func.value, "id", "") == "env_app"
                    and dec.args and isinstance(dec.args[0], ast.Constant)):
                found.add(dec.args[0].value)
    return found


def test_the_scan_finds_the_env_subcommands():
    """The positive twin, first. Every assertion below is satisfied by a scan that found nothing,
    and a derivation returning an empty set reads exactly like compliance."""
    found = _env_subcommands()

    assert {"read", "check", "apply", "context", "rehearse"} <= found, (
        f"the scan found {sorted(found)} — it cannot see the commands it exists to check")


def test_every_env_subcommand_is_a_ROW_except_the_ones_named_here():
    """The rule, and the exception in the same assertion so neither can drift.

    A new `env` verb that reaches only the terminal fails here and has to be argued for — which is
    the point: the argument is cheap to make and impossible to skip."""
    from openfactory import actions

    rows = {n[len("env_"):] for n in actions.names() if n.startswith("env_")}
    unreachable = sorted(_env_subcommands() - rows - set(TERMINAL_ONLY))

    assert not unreachable, (
        f"these `env` verbs exist only in the terminal and nothing says why: {unreachable}. "
        f"Either give them a catalogue row — ADR-0039: one action, N transports — or name them in "
        f"TERMINAL_ONLY with the reason, the way `rehearse` is.")


@pytest.mark.parametrize("name", sorted(TERMINAL_ONLY))
def test_a_named_exception_is_still_TRUE(name):
    """Staleness, the pattern `test_provider_seams` uses for its allowlist. The day somebody gives
    `rehearse` a row, this entry becomes a lie that reads as documentation — so it fails, and the
    fix is to delete it."""
    from openfactory import actions

    assert f"env_{name}" not in actions.names(), (
        f"`env_{name}` HAS a catalogue row now, and this file still calls it terminal-only. "
        f"Delete the TERMINAL_ONLY entry — the exception was paid down.")
    assert name in _env_subcommands(), (
        f"`env {name}` is named as a terminal-only exception and no longer exists as a command")


@pytest.mark.parametrize("name", sorted(TERMINAL_ONLY))
def test_the_exception_carries_its_REASON(name):
    """A named exception with no reason is an allowlist entry, and an allowlist entry is how a
    decision becomes a habit nobody can re-examine."""
    why = TERMINAL_ONLY[name]

    assert len(why) > 60 and any(w in why for w in ("because", "value", "takes", "stream")), (
        f"the exception for `{name}` does not say why: {why!r}")


def test_the_round_is_reachable_at_all():
    """The other half of "deliberately terminal-only": it has to BE in the terminal. "No button"
    is only honest if it is not also "no door" — the two product verbs that left the panel for the
    same reason were kept reachable as CLI verbs, and this is that check for this one."""
    from typer.testing import CliRunner

    from openfactory.cli import app

    result = CliRunner().invoke(app, ["env", "rehearse", "--help"])

    assert result.exit_code == 0, result.output
    # ANSI codes and Typer's box-drawing wrap the flags, so the raw text is not searchable —
    # measured, after asserting on it and getting a failure about formatting rather than about
    # the command.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output).replace("\n", " ")
    assert "--yes" in re.sub(r"\s+", " ", plain), (
        f"the round no longer refuses to spend without consent, or the help stopped saying so: "
        f"{plain[:400]}")
