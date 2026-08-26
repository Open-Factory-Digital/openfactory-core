"""`openfactory/onboarding/firstrun.py` is reachable by a human. Asserted, because it was not.

1,580 lines that answer the only question a client asks in the room — *does the factory work
here?* — and its own entry point said so in its docstring:

    NOTHING REACHES THIS YET, AND SAYING SO IS THE POINT. As of this change there is no `CATALOG`
    row, no CLI command and no panel button for the first round.

An honest gap is still a gap. `sdlc env rehearse` is the door, and this file is what stops it
being closed again by a refactor that looks like tidying.

WHY THE CLI AND NOT THE CATALOG, since the sibling rows (`env read`, `env context`, `env check`)
are all actions. Every station of this round needs a box: a docker daemon, the project's image,
the toolbox, a checkout, a harness. `POST /api/act/{name}` runs inside the panel's own service,
which has none of them — and `box prove`, the one capability in this platform with exactly the
same requirement, is CLI-only for exactly this reason. A row that could only ever refuse is worse
than no row: it puts a button on a screen that answers "not here" every time it is pressed.

THE CONSENT IS THE PART TO GUARD. This round makes two real agent passes and may run a client's
own test suite on a machine in their office. Both of those are somebody's decision, and a command
that made either of them by default would be spending money and running unknown code on an
assumption — the two failures this module's `Consent` object exists to prevent.
"""

from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _command(func: str = "env_rehearse_cmd") -> ast.FunctionDef:
    tree = ast.parse((ROOT / "openfactory/cli.py").read_text())
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == func), None)
    assert node is not None, f"{func} is gone from openfactory/cli.py — the first round has no door again"
    return node


def _calls(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for call in ast.walk(node):
        if isinstance(call, ast.Call):
            if isinstance(call.func, ast.Attribute):
                out.add(call.func.attr)
            elif isinstance(call.func, ast.Name):
                out.add(call.func.id)
    return out


def test_a_human_can_type_the_command():
    from typer.testing import CliRunner

    from openfactory.cli import app

    result = CliRunner().invoke(app, ["env", "rehearse", "--help"])
    assert result.exit_code == 0, result.output
    # ANSI-stripped: typer styles each flag, so a plain `in` reports a flag missing on a CLI
    # that has it.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    for flag in ("--yes", "--gates", "--no-gates", "--by"):
        assert flag in plain, f"`sdlc env rehearse` lost {flag}:\n{plain}"


def test_the_command_runs_the_round():
    called = _calls(_command())
    missing = [name for name in ("probes_for", "rehearse", "render") if name not in called]
    assert not missing, (
        f"`sdlc env rehearse` does not call {missing} — the command exists and the capability "
        f"does not. It calls: {sorted(called)}"
    )


def test_nothing_is_spent_without_consent():
    """`--yes` is the ONLY thing that turns `spend_approved` on.

    `rehearse` refuses before the harness is constructed, so the guarantee lives there — but a
    command that passed `spend_approved=True` unconditionally would walk straight past it, and
    the estimate a client is shown would be a bill they never agreed to.
    """
    src = ast.unparse(_command())
    assert "spend_approved=yes" in src, (
        "the spend flag is not the `--yes` option — read what it IS bound to:\n" + src
    )


def test_the_gates_question_keeps_its_third_answer():
    """`gates_may_run` is tri-state and the third value is the honest default.

    True = somebody said yes. False = somebody said NO — a fifteen-year-old suite that talks to a
    shared dev database will truncate it, from a workshop, in front of its owners. None = nobody
    was asked, and the round then runs them only where a valid box proof already covers those exact
    commands. A CLI that collapsed None into False would silently answer a question nobody asked.
    """
    node = _command()
    gates = next((a for a in node.args.args if a.arg == "gates"), None)
    assert gates is not None, "`--gates/--no-gates` is gone; the client's suite question with it"
    default = node.args.defaults[node.args.args.index(gates) - (len(node.args.args) -
                                                               len(node.args.defaults))]
    assert isinstance(default, ast.Call), ast.unparse(default)
    assert ast.unparse(default.args[0]) == "None", (
        f"the default for --gates is {ast.unparse(default.args[0])}, not None — 'nobody was asked' "
        f"has been collapsed into an answer somebody will be held to"
    )


def test_the_consent_carries_a_name():
    """A consent with no name is a consent nobody gave, and the name lands in the client's report."""
    src = ast.unparse(_command())
    assert "getuser" in src and "by=" in src, (
        "the round is approved by nobody in particular:\n" + src
    )


def test_a_round_that_reached_no_agent_says_NOTHING_not_UNREPORTED():
    """Found on the first real run of `sdlc env rehearse`, in the one line about the client's money.

    The box was unproven, the round stopped at station one, and no harness was ever constructed —
    yet the report read `spent: not reported by this harness`, which is a claim about a harness
    that was never invoked. `spent_usd is None` cannot tell "no pass ran" from "a pass ran and was
    not priced", and a reader has to assume the second: something ran, unmeasured, on their bill.
    """
    from openfactory.onboarding.firstrun import (
        Consent,
        Estimate,
        Rehearsal,
        Stage,
    )

    def _run(*stages: Stage) -> str:
        run = Rehearsal(project="t", measured_on="local", sandbox_kind="container",
                        estimate=Estimate(passes=2, usd_low=None, usd_high=None, sample=0,
                                          basis="no basis", turn_cap=25),
                        consent=Consent(spend_approved=True, by="t"), stages=list(stages))
        return "\n".join(run.render())

    stopped = _run(Stage(name="box", ok=False, message="never proven", remedy="prove it",
                         measured_on="local"),
                   Stage(name="agent", ok=True, message="not reached — stopped at `box`",
                         measured_on="local", answered=False, reached=False))
    assert "spent: nothing — no agent pass was reached" in stopped, stopped
    assert "not reported by this harness" not in stopped, (
        "a round that reached no agent still blames the harness for the missing number:\n" + stopped
    )

    # THE POSITIVE TWIN. A line that always said "nothing" would pass the assertion above while
    # hiding a real unpriced pass — which is the more expensive of the two, because the total a
    # client compares against a competitor's would silently omit it.
    ran = _run(Stage(name="agent", ok=True, message="ran", measured_on="local", seconds=12.0))
    assert "spent: not reported by this harness" in ran, ran


def test_the_estimate_alone_touches_no_harness(monkeypatch, tmp_path):
    """The default invocation is a QUOTE. It must reach neither a harness nor a docker daemon.

    Exercised through `rehearse` itself rather than by reading the CLI, because this is a property
    of the round and the command only has to not add to it.
    """
    from openfactory.onboarding.firstrun import Consent, Probes, rehearse

    exploded: list[str] = []

    def _boom(*_a, **_k):
        exploded.append("touched")
        raise AssertionError("a quote built the world")

    probes = Probes(
        project_name="t", measured_on=lambda: "local", sandbox_kind=lambda: "container",
        image=_boom, box_ready=_boom, gates_already_proven=_boom, client_box_env=_boom,
        route_env_names=_boom, build_box=_boom, repo_path=_boom, manifest=_boom,
        executor=_boom, reviewer=_boom, context=_boom, bot=_boom,
        # The two the QUOTE is allowed to read: past spend is telemetry, and the cap is a number.
        past_runs=lambda: [], turn_cap_enforced=lambda: True, turn_cap=25,
    )
    run = rehearse(probes, consent=Consent())
    assert exploded == [], "the estimate-only path called into the box"
    assert run.not_run, "a round with no consent reported as though it had run"
    assert run.exit_code == 1, (
        "an unapproved round exits 0 — a script would read a quote as a proven environment"
    )
