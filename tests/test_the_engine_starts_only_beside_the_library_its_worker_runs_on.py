"""The durable engine is started only beside the library its worker runs on (#171).

THE ONE-MACHINE INSTALL LEFT OUT THE `runtime` EXTRA while `openfactory up` told the reader to put
`temporal` on the PATH. Doing exactly that, reported from a real machine:

    ✓ engine, worker, panel — Ctrl-C stops them together.
      File "…/openfactory/runtime/temporal/worker.py", line 21, in <module>
        from temporalio.worker import Worker
    ModuleNotFoundError: No module named 'temporalio'
    ✗ worker exited (1) — stopping the rest

One dying process ends the set by design, so the panel went down with it: installing the engine as
told turned an attended factory that worked into one that did not start. Two things now hold, and
each is read from the thing itself — the plan `host.processes` returns, what `up` prints, and the
`pip install` lines the two install pages actually run.
"""

from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfactory.runtime import host

ROOT = Path(__file__).resolve().parents[1]

#: The pages whose install is the one a person then runs `openfactory up` from.
ONE_MACHINE_PAGES = ("README.md", "docs/setup/one-machine.md")


@pytest.fixture
def no_temporalio(monkeypatch):
    """This interpreter as an install made without the `runtime` extra: `temporalio` cannot be
    found or imported. A `None` in `sys.modules` is what Python itself reads as "not there"."""
    import sys

    for name in [m for m in sys.modules if m == "temporalio" or m.startswith("temporalio.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "temporalio", None)


# ── the plan ─────────────────────────────────────────────────────────────────────────────────────

def test_without_the_library_neither_the_engine_nor_its_worker_is_planned(no_temporalio,
                                                                           tmp_path):
    """The worker would die on its first import and take the panel with it; and an engine with no
    worker is the half-state the doctor reads as the durable half answering."""
    plan = [name for name, _ in host.processes(panel_port=8788, state=tmp_path,
                                               engine="/usr/bin/temporal")]

    assert plan == ["panel"], f"planned without the library the worker runs on: {plan}"


def test_with_the_library_the_engine_and_its_worker_are_planned_as_before(tmp_path):
    pytest.importorskip("temporalio")

    plan = [name for name, _ in host.processes(panel_port=8788, state=tmp_path,
                                               engine="/usr/bin/temporal")]

    assert plan == ["engine", "worker", "panel"], plan


# ── what `up` says ───────────────────────────────────────────────────────────────────────────────

def _up(monkeypatch, tmp_path, *, binary: str | None):
    """`openfactory up` with the processes captured instead of started."""
    from openfactory import cli

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(host, "the_engine", lambda: binary)
    started: list[list[str]] = []

    def run(plan, *, say, grace=host.GRACE_S):
        started.append([name for name, _ in plan])
        return 0

    monkeypatch.setattr(host, "run", run)
    result = CliRunner().invoke(cli.app, ["up"])
    assert result.exit_code == 0, result.output
    assert started, "up never reached the supervisor"
    return started[0], " ".join(result.output.split())


def test_up_with_the_binary_and_no_library_says_what_to_install_and_keeps_the_panel(
        no_temporalio, monkeypatch, tmp_path):
    plan, said = _up(monkeypatch, tmp_path, binary="/usr/bin/temporal")

    assert plan == ["panel"], plan
    assert "pip install -e '.[runtime]'" in said, said
    assert "`temporal` is on your PATH" in said, "the sentence must name what IS there too"
    assert "the durable half is off" in said, "the closing line must agree with the first"
    # THIS LINE ASSERTED THE OPPOSITE UNTIL #178, and was right to: the panel's page answered 500
    # without the library, so `up` left the panel out of what it promised. The page's words no
    # longer come from modules that import it, and the claim below is held where it is measured —
    # `tests/test_the_panel_serves_without_the_engines_client.py` asks every GET route in an
    # interpreter where `temporalio` cannot be found.
    assert "the panel works" in said, said
    assert "page needs" not in said, "the panel's page no longer needs the library (#178)"


def test_up_with_neither_names_BOTH_installs(no_temporalio, monkeypatch, tmp_path):
    """Naming only the binary is what sent the reader into the crash."""
    plan, said = _up(monkeypatch, tmp_path, binary=None)

    assert plan == ["panel"], plan
    assert "brew install temporal" in said, said
    assert "pip install -e '.[runtime]'" in said, said


def test_up_with_the_library_and_no_binary_names_only_the_binary(monkeypatch, tmp_path):
    pytest.importorskip("temporalio")

    plan, said = _up(monkeypatch, tmp_path, binary=None)

    assert plan == ["panel"], plan
    assert "brew install temporal" in said, said
    assert "[runtime]" not in said, "an install that has the library is not told to install it"
    assert "the panel works" in said, said


def test_up_with_both_says_nothing_is_missing(monkeypatch, tmp_path):
    pytest.importorskip("temporalio")

    plan, said = _up(monkeypatch, tmp_path, binary="/usr/bin/temporal")

    assert plan == ["engine", "worker", "panel"], plan
    assert "durable engine is off" not in said and "durable half is off" not in said, said


# ── the install pages ────────────────────────────────────────────────────────────────────────────

def _extras_that_bring(package: str) -> set[str]:
    """The extras of THIS package whose requirements include `package`, read from pyproject."""
    table = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    return {extra for extra, requirements in table.get("optional-dependencies", {}).items()
            if any(re.match(rf"{re.escape(package)}\b", r.strip()) for r in requirements)}


def _installs_of_the_checkout(page: Path) -> list[tuple[int, list[str]]]:
    """Every `pip install` of the checkout itself (`.` / `.[…]`) in the page's fenced shell
    blocks, as (line number, extras). Parsed with shlex, comments dropped, prose never read."""
    found: list[tuple[int, list[str]]] = []
    fenced = False
    for number, line in enumerate(page.read_text().splitlines(), start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            continue
        for command in re.split(r"&&|;", line):
            try:
                argv = shlex.split(command, comments=True)
            except ValueError:
                continue
            if argv[:2] == ["pip", "install"] or argv[1:3] == ["-m", "pip"]:
                for target in argv[2:]:
                    matched = re.fullmatch(r"\.(?:\[([^\]]*)\])?", target)
                    if matched:
                        extras = [e.strip() for e in (matched.group(1) or "").split(",")]
                        found.append((number, [e for e in extras if e]))
    return found


def test_the_install_pages_install_the_library_the_engines_worker_runs_on():
    bringing = _extras_that_bring("temporalio")
    assert bringing, "no extra of this package declares temporalio — the guard reads nothing"

    for relative in ONE_MACHINE_PAGES:
        installs = _installs_of_the_checkout(ROOT / relative)
        assert installs, f"{relative} no longer installs the checkout — the guard reads nothing"
        for number, extras in installs:
            assert bringing & set(extras), (
                f"{relative}:{number} installs the checkout with extras {extras or 'none'}, and "
                f"none of them brings temporalio ({sorted(bringing)} do) — `temporal` on the PATH "
                f"then starts a worker that dies on its first import")


def test_the_page_parser_reads_the_extras_it_is_given(tmp_path):
    """The parser the guard above stands on, held to both answers."""
    page = tmp_path / "page.md"
    page.write_text("pip install -e .\n\n```bash\ncd x && pip install -e .   # plain\n"
                    "pip install -e '.[dev, runtime]'\n```\n")

    assert _installs_of_the_checkout(page) == [(4, []), (5, ["dev", "runtime"])]
