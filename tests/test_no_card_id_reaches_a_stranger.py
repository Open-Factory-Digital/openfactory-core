"""What a stranger reads carries no card id — the help screens, the conformance findings, the logs.

The tree is full of `#NNN` and `C-NN`: 902 in the package and 1,295 in the tests (measured
2026-08-24), the ids of cards on the tracker this repository had before it was public. In a
comment or a docstring they are PROVENANCE — the sentence carries the reasoning, the id says
which incident earned it — and `CONTRIBUTING.md` tells a contributor to read them that way. A
mass strip was measured and refused: the same sweep would eat `#189` and `#412` where they are
FORMAT EXAMPLES inside prompts, and this repository's own lesson is three self-inflicted breakages
in one day from pattern edits.

A comment is not a surface. Three things are, and a card id on them is a reference to a tracker
the reader cannot open:

  * every `--help` screen — typer renders the docstring, so `(C-16)` at the end of a summary line
    is printed to whoever types `openfactory project --help`. 7 of 51 screens carried one;
  * the conformance suite's `taught_by` strings — `openfactory conformance-adapter` prints them
    to a third party running THEIR adapter against our rules. 3 findings carried one;
  * a log line — an operator's terminal. 1 carried one.

THE FIRST VERSION OF THE HELP SWEEP READ ZERO SCREENS and passed. So every sweep here has a
floor on what it read, and a positive twin that plants an id and watches the sweep see it —
absence read as compliance is the shape this repository pays for most.
"""

from __future__ import annotations

import ast
import pathlib
import re

import click
import typer
from typer.testing import CliRunner

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: A card id as it was written: `#124`, `C-22`. Two or three digits after the hash — one digit is
#: never a card here and four is a year or a port; two after `C-`, which is the older scheme.
CARD_ID = re.compile(r"#\d{2,3}\b|C-\d{2}\b")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


# ── the help screens ────────────────────────────────────────────────────────────────────────────

def _help_screens(app: typer.Typer) -> list[tuple[str, str]]:
    """Every `--help` a user can reach, as (command path, rendered text) — the whole command
    tree, walked from the root, each screen rendered the way the terminal renders it."""
    paths: list[list[str]] = []

    def walk(cmd: click.Command, path: list[str]) -> None:
        paths.append(path)
        for name, sub in getattr(cmd, "commands", {}).items():
            walk(sub, [*path, name])

    walk(typer.main.get_command(app), [])
    runner = CliRunner()
    out = []
    for path in paths:
        # a wide, plain terminal: no colour codes to strip and no wrapping that could split an
        # id across two lines and hide it from the pattern
        result = runner.invoke(app, [*path, "--help"],
                               env={"TERM": "dumb", "NO_COLOR": "1", "COLUMNS": "200"})
        assert result.exit_code == 0, f"`{' '.join(path)} --help` failed: {result.output[-300:]}"
        out.append((" ".join(path) or "<root>", _ANSI.sub("", result.output)))
    return out


def test_no_help_screen_names_a_card():
    from openfactory.cli import app

    screens = _help_screens(app)
    assert len(screens) >= 40, f"only {len(screens)} help screens swept — the tree was not walked"
    hits = [f"{name}: {', '.join(CARD_ID.findall(text))}"
            for name, text in screens if CARD_ID.search(text)]
    assert not hits, (
        "a `--help` screen cites a card on the tracker this repository had before it was public "
        "— a stranger cannot open it. Keep the reasoning, drop the id (a comment above the "
        "function may keep it as provenance):\n  " + "\n  ".join(hits))


def test_the_help_sweep_can_SEE_a_card_id():
    """The positive twin, on an app of its own — the sweep is only worth its green if it would
    have gone red on the seven screens it was written for."""
    planted = typer.Typer(help="A tiny app for the sweep.")
    sub = typer.Typer(help="A group whose summary cites a card (C-36).")
    planted.add_typer(sub, name="group")

    @planted.command()
    def init() -> None:
        """Generate the environment from a few answers, instead of a template (#116)."""

    @sub.command()
    def inner() -> None:
        """Inside the group, the older scheme (C-22)."""

    screens = dict(_help_screens(planted))
    assert set(screens) >= {"<root>", "init", "group", "group inner"}, sorted(screens)
    assert "#116" in CARD_ID.findall(screens["init"])
    assert "C-22" in CARD_ID.findall(screens["group inner"])
    assert "C-36" in CARD_ID.findall(screens["<root>"]), "a group's summary line is not swept"


# ── the conformance findings ────────────────────────────────────────────────────────────────────

CONFORMANCE = ROOT / "openfactory" / "conformance"


def _literals(node: ast.AST) -> list[str]:
    """Every string literal under a node — plain constants and the literal parts of f-strings."""
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _finding_texts(source: str) -> list[tuple[int, str]]:
    """The text of every Finding a conformance module can produce: the literals passed to
    `_finding(...)` or `Finding(...)`, joined per call, with the line it is built on."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        if name not in ("_finding", "Finding"):
            continue
        parts = [*node.args, *(k.value for k in node.keywords)]
        out.append((node.lineno, " ".join(s for p in parts for s in _literals(p))))
    return out


def test_no_conformance_finding_names_a_card():
    texts = [(path.name, line, text)
             for path in sorted(CONFORMANCE.glob("*.py"))
             for line, text in _finding_texts(path.read_text())]
    assert len(texts) >= 10, f"only {len(texts)} findings read — the suite has lost its subject"
    hits = [f"{name}:{line}  {', '.join(CARD_ID.findall(text))}"
            for name, line, text in texts if CARD_ID.search(text)]
    assert not hits, (
        "a conformance finding cites a card on the pre-public tracker — it is printed to a third "
        "party running their adapter against these rules, and they cannot open it:\n  "
        + "\n  ".join(hits))


def test_the_finding_sweep_can_SEE_a_card_id():
    """The twin: a `taught_by` built from an f-string, a plain literal and a keyword must each be
    read — the three shapes the real findings use."""
    snippet = (
        "def rule(exc):\n"
        "    a = _finding('notifier.accepts-about', f'rejected: {exc}',\n"
        "                 'the thread-link (#24 item 3) rides on `about`')\n"
        "    b = Finding(rule='board.refs', detail='x', taught_by='a live bug (C-05)')\n"
        "    c = _finding('clean', 'nothing here', 'measured live, no id')\n"
    )
    texts = _finding_texts(snippet)
    assert len(texts) == 3
    found = {line: CARD_ID.findall(text) for line, text in texts}
    assert found[2] == ["#24"], found
    assert found[4] == ["C-05"], found
    assert found[5] == [], "an id was seen where none was written"


# ── the log lines ───────────────────────────────────────────────────────────────────────────────

_LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})


def _log_texts(source: str) -> list[tuple[int, str]]:
    """The literal text of every `<something>.info(...)`-shaped call: what a log line says before
    its arguments are filled in."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in _LOG_METHODS:
            parts = [*node.args, *(k.value for k in node.keywords)]
            out.append((node.lineno, " ".join(s for p in parts for s in _literals(p))))
    return out


def test_no_log_line_names_a_card():
    texts = [(path.relative_to(ROOT).as_posix(), line, text)
             for path in sorted(ROOT.joinpath("openfactory").rglob("*.py"))
             for line, text in _log_texts(path.read_text())]
    # measured 2026-08-25: well over a thousand log calls carry a literal; 300 is a floor against
    # the sweep silently reading nothing, not a count anybody maintains
    assert len(texts) >= 300, f"only {len(texts)} log literals read — the package was not walked"
    hits = [f"{rel}:{line}  {', '.join(CARD_ID.findall(text))}"
            for rel, line, text in texts if CARD_ID.search(text)]
    assert not hits, (
        "a log line cites a card on the pre-public tracker — an operator's terminal is a surface, "
        "and the id points nowhere they can go:\n  " + "\n  ".join(hits))


def test_the_log_sweep_can_SEE_a_card_id():
    snippet = (
        "def run():\n"
        "    activity.logger.info('%s has no url — falling back, which is deprecated (#122)', p)\n"
        "    log.warning('fine: %s', p)\n"
    )
    found = {line: CARD_ID.findall(text) for line, text in _log_texts(snippet)}
    assert found == {2: ["#122"], 3: []}, found
