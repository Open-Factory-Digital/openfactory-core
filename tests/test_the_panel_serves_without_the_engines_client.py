"""The panel serves without the engine's client library, and what IS the engine's says so (#178).

THREE DOCSTRINGS PROMISED IT AND THE PAGE DID NOT KEEP IT. `actions/__init__.py` (twice) and
`runtime/temporal/view.py` say the panel is built to serve without the `runtime` extra
(`temporalio`). Measured on `main` at `1512d0a`, the app served through `TestClient` in an
interpreter where `temporalio` cannot be found, a local project registered, every GET route asked
once: **12 of 41 answered 500**, each one `ModuleNotFoundError: No module named 'temporalio'` —

    /  /p/{project}  /p/{project}/board  /p/{project}/card/{ref}  /p/{project}/pr/{ref}
    /logs  /logs/{project}  /logs/{project}/{issue}  /product/{project}
    /api/floor  /api/floor/{project}  /api/attention

— by two roads. The page's own WORDS (`ATTENTION_STATES`, the merge-wait sentences) were defined
in `view.py` and `workflow.py`, which import `temporalio` at the top, and `_panel_vocabulary`
fetched them on every render. And the floor's `_engine`, whose docstring says "never raises", had
its import of `view` ABOVE the `try` whose `except` is commented "a deployment with no runtime
extra still answers". On the command line the same install met a raw traceback from `openfactory
worker`, `poller pause` and `poller resume`.

EVERYTHING HERE RUNS IN A CHILD INTERPRETER, on purpose. Making a library unimportable means
editing `sys.meta_path` and `sys.modules`, and both are process-wide: done in the suite's own
process it would leak into whichever test the worker runs next, under `-n` and in either order —
a state leak worse than the defect. The child installs the refusal before it imports anything of
ours, does its reading, and prints JSON; this process never blocks anything.

IT READS THE THING. The routes are enumerated from `app.routes`, never listed by hand, so a route
added tomorrow is asked too; the commands are walked from the Typer app the same way; and what is
asserted is each answer's status, the floor's own verdict and what a command printed — not text
about any of them.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: The child. `BLOCK=1` makes `temporalio` unfindable BEFORE anything of ours is imported — a
#: finder at the head of `sys.meta_path` that refuses the name, which is what an install without
#: the extra looks like to `import` and to `importlib.util.find_spec` alike.
_CHILD = r'''
import asyncio, importlib.abc, inspect, json, os, re, sys, typing


class _Refuse(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "temporalio" or name.startswith("temporalio."):
            raise ModuleNotFoundError(f"No module named {name!r}", name="temporalio")
        return None


if os.environ["BLOCK"] == "1":
    sys.meta_path.insert(0, _Refuse())


def _engine_loaded():
    return sorted(m for m in sys.modules if m.split(".")[0] == "temporalio")[:3]


def _deployment():
    """A registered local project with a board and one card — so the routes that take a project
    and a card run their real bodies instead of answering 404 at the door."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    registry = ProjectRegistry()
    registry.add(Project(name="acme", repo_path=os.environ["HOME"],
                         tracker=ProviderRef(kind="local", repo="acme", options={})))
    project = registry.get("acme")
    LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
    ref = build_tracker(project).create_ticket(title="Serve the page",
                                               body="## Objective\nServe it\n")
    build_board(project).set_column(issue=ref, issue_url="", name="TO-DO")
    return str(ref).lstrip("#")


class _Request:
    """What the two streaming routes read of a request: its headers, and whether it is gone."""
    headers: dict = {}

    async def is_disconnected(self):
        return False


async def _first_frame(endpoint, values):
    """A stream never ends, so it is asked for ONE frame — by calling the route's own function
    and reading its body iterator, which is the code a browser would be served by."""
    kwargs = {name: (_Request() if name == "request" else values.get(name, "x"))
              for name in inspect.signature(endpoint).parameters}
    response = await endpoint(**kwargs)
    frames = response.body_iterator
    try:
        return await asyncio.wait_for(anext(frames), timeout=20)
    finally:
        await frames.aclose()


def routes():
    from fastapi.responses import StreamingResponse
    from fastapi.testclient import TestClient

    ref = _deployment()
    from openfactory.api import app as panel

    values = {"project": "acme", "issue": ref, "ref": ref}
    client = TestClient(panel.app, raise_server_exceptions=False)
    asked = []
    for route in panel.app.routes:
        if "GET" not in (getattr(route, "methods", None) or ()):
            continue
        path = re.sub(r"\{(\w+)(?::\w+)?\}", lambda m: values.get(m.group(1), "x"), route.path)
        row = {"route": route.path, "asked": path}
        if typing.get_type_hints(route.endpoint).get("return") is StreamingResponse:
            try:
                frame = asyncio.run(_first_frame(route.endpoint, values))
                row.update(status=200, stream=True,
                           body=(frame.decode() if isinstance(frame, bytes) else str(frame))[:400])
            except Exception as exc:  # noqa: BLE001 — reported, never raised: the parent judges
                row.update(status=500, stream=True, body=f"{type(exc).__name__}: {exc}"[:400])
        else:
            answer = client.get(path)
            row.update(status=answer.status_code, body=answer.text[:4000])
        asked.append(row)
    return {"routes": asked, "engine_loaded": _engine_loaded()}


def words():
    """The page and its words, in an interpreter that HAS the library — and must not reach it."""
    from fastapi.testclient import TestClient

    _deployment()
    from openfactory.api import app as panel

    client = TestClient(panel.app, raise_server_exceptions=False)
    statuses = {path: client.get(path).status_code for path in ("/", "/api/attention")}
    return {"statuses": statuses, "vocabulary": panel._panel_vocabulary(),
            "engine_loaded": _engine_loaded()}


def commands():
    import typer.main
    from typer.testing import CliRunner

    from openfactory import cli

    def leaves(command, path):
        subs = getattr(command, "commands", None)
        if not subs:
            yield path
            return
        for name, sub in sorted(subs.items()):
            yield from leaves(sub, [*path, name])

    # Started with no arguments these five serve, supervise or ask questions for ever; their
    # `--help` is asked like everybody else's.
    never_bare = {("up",), ("serve",), ("poll",), ("init",), ("onboard",)}
    rows = []
    for path in leaves(typer.main.get_command(cli.app), []):
        for argv in ([*path, "--help"], path):
            if argv == path and tuple(path) in never_bare:
                continue
            result = CliRunner().invoke(cli.app, argv)
            raised = result.exception
            rows.append({"argv": argv, "exit": result.exit_code, "said": result.output[-1500:],
                         "raised": "" if raised is None or isinstance(raised, SystemExit)
                                   else f"{type(raised).__name__}: {raised}"[:300]})
    return {"commands": rows}


def worker_module():
    """`python -m openfactory.runtime.temporal.worker` — what compose and `up` run."""
    import runpy

    try:
        runpy.run_module("openfactory.runtime.temporal.worker", run_name="__main__")
    except SystemExit as exc:
        return {"exit": str(exc.code)}
    except BaseException as exc:  # noqa: BLE001 — the raw traceback this is about
        return {"raised": f"{type(exc).__name__}: {exc}"[:300]}
    return {"ran": True}


print("\n@@RESULT@@" + json.dumps({"routes": routes, "words": words, "commands": commands,
                                   "worker_module": worker_module}[sys.argv[1]]()))
'''


@cache
def _child(what: str, *, block: bool) -> dict:
    """Run one reading in a fresh interpreter, in an empty home, and hand back what it printed."""
    import tempfile

    home = tempfile.mkdtemp(prefix="of-no-engine-client-")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("OPENFACTORY_", "TEMPORAL_"))}
    env.update(HOME=home, BLOCK="1" if block else "0", PYTHONPATH=str(ROOT),
               OPENFACTORY_REGISTRY=str(Path(home) / "registry.yaml"),
               OPENFACTORY_BOARD_DB=str(Path(home) / "board.db"))
    done = subprocess.run([sys.executable, "-c", _CHILD, what], cwd=home, env=env,
                          capture_output=True, text=True, timeout=300)
    assert "@@RESULT@@" in done.stdout, (
        f"the child interpreter never reported ({what}, block={block}):\n"
        f"{done.stdout[-1500:]}\n{done.stderr[-3000:]}")
    return json.loads(done.stdout.rsplit("@@RESULT@@", 1)[1])


def _install_sentence() -> str:
    from openfactory.runtime import host

    return host.RUNTIME_INSTALL


def _names_the_install(text: str) -> bool:
    return "pip install -e '.[runtime]'" in text and "temporalio" in text


# ── the panel's routes ───────────────────────────────────────────────────────────────────────────

def test_every_GET_route_answers_without_the_engines_client():
    """Either it answers, or it refuses BY NAME with what to install — never a 500."""
    asked = _child("routes", block=True)["routes"]
    paths = {row["route"] for row in asked}

    assert {"/", "/api/floor", "/api/attention", "/api/temporal/stream"} <= paths and len(asked) > 30, (
        f"the sweep did not reach the panel's routes — it asked {sorted(paths)}")
    broken = [f'{row["status"]} {row["route"]}  {row["body"][:160]}' for row in asked
              if row["status"] >= 500
              and not (row["status"] == 503 and _names_the_install(row["body"]))]
    assert not broken, (
        "with `temporalio` unimportable these routes neither answered nor refused by name:\n  "
        + "\n  ".join(broken))


def test_the_sweep_really_ran_without_the_library():
    """The reading above means nothing if the child could import the library after all."""
    assert _child("routes", block=True)["engine_loaded"] == []


def test_the_page_is_served_WITH_its_words():
    """`/` is not merely a 200: the vocabulary the server owns was rendered into it."""
    page = next(row for row in _child("routes", block=True)["routes"] if row["route"] == "/")

    assert page["status"] == 200, page["body"][:300]
    assert "__VOCABULARY__" not in page["body"], "the page was served with its token unfilled"


def test_the_floor_says_the_engine_is_ABSENT_and_what_to_install():
    """Not a 500 (the page reads that as its own failure), and not "the engine did not answer"
    (that sends the reader to a process and a port, and the remedy here is an install)."""
    floor = next(row for row in _child("routes", block=True)["routes"]
                 if row["route"] == "/api/floor")
    assert floor["status"] == 200, floor["body"][:300]
    said = json.loads(floor["body"])

    assert said["cause"] == "engine_down" and said["word"] == "Stopped", said
    assert _names_the_install(said["detail"]), (
        f"the floor must name the install that is missing, and said: {said['detail']!r}")
    assert "did not answer" not in said["clause"] + said["detail"], said


def test_ANOTHER_import_failing_is_not_blamed_on_the_install(monkeypatch):
    """The floor still never raises — but "install the runtime extra" is said only when that is
    what is missing. Anything else that breaks inside the engine's reader is reported as itself,
    or the reader is sent to reinstall a library they already have."""
    import asyncio

    import openfactory.runtime.temporal as engine
    from openfactory.floor import reading

    # `from package import module` is satisfied by the package's attribute before `sys.modules` is
    # ever asked, so both are taken away — and both are put back by `monkeypatch`.
    monkeypatch.delattr(engine, "view", raising=False)
    monkeypatch.setitem(sys.modules, "openfactory.runtime.temporal.view", None)

    client, connected, address, error = asyncio.run(reading._engine(None))

    assert (client, connected, address) == (None, False, "")
    assert error and not _names_the_install(error), error

    # …and the panel's engine routes, which ask the same question of the same exception.
    from openfactory.api import app as panel

    with pytest.raises(RuntimeError) as refused:
        panel._temporal()
    assert not _names_the_install(str(refused.value)), str(refused.value)


def test_the_engine_stream_degrades_to_one_frame_that_names_the_install():
    """The header rides this stream, so its first frame is what a fresh page is told."""
    stream = next(row for row in _child("routes", block=True)["routes"]
                  if row["route"] == "/api/temporal/stream")

    assert stream["status"] == 200, stream["body"]
    frame = json.loads(stream["body"].split("data: ", 1)[1])
    assert frame["connected"] is False and _names_the_install(frame["error"]), frame


def test_the_pages_words_cost_no_engine_import():
    """WITH the library installed, serving the page must still not import it: the words come from
    a module that does not know the engine's client exists. This is the case that fails on the
    old shape without blocking anything — `_panel_vocabulary` imported `view` and `workflow`."""
    pytest.importorskip("temporalio")
    got = _child("words", block=False)

    assert got["statuses"] == {"/": 200, "/api/attention": 200}, got["statuses"]
    assert got["engine_loaded"] == [], (
        f"serving the page imported the engine's client: {got['engine_loaded']}")
    assert "awaiting_your_merge" in got["vocabulary"]["alarm"]
    assert got["vocabulary"]["merge_wait"]["auto"] != got["vocabulary"]["merge_wait"]["human"]


# ── one definition ───────────────────────────────────────────────────────────────────────────────

#: The older names, and the modules that still carry them for their callers.
_NAMED_ELSEWHERE = {
    "openfactory/runtime/temporal/view.py": {"ATTENTION_STATES", "MERGE_WAIT"},
    "openfactory/runtime/temporal/workflow.py": {"merge_wait_note"},
    "openfactory/techlead/conversation.py": {"_MERGE_WAIT_KIND"},
}


@pytest.mark.parametrize("module", sorted(_NAMED_ELSEWHERE))
def test_the_words_are_NAMED_elsewhere_and_defined_once(module):
    """Moved, not copied. PARSED, because identity cannot see it: `"merge_wait" is "merge_wait"`
    holds between two modules that each spell the literal (CPython interns it), so a second
    spelling of the STRING passes every `is` — and a second spelling is precisely the copy the
    tech-lead kept, with a guard to pin it, while the word cost `temporalio` to read."""
    names = _NAMED_ELSEWHERE[module]
    tree = ast.parse((ROOT / module).read_text())

    respelled = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            respelled.append(f"def {node.name}")
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            bound = {t.id for t in targets if isinstance(t, ast.Name)} & names
            if bound and not isinstance(node.value, ast.Name):
                respelled.append(f"{sorted(bound)[0]} = <{type(node.value).__name__}>")
    assert not respelled, f"{module} spells its own copy again: {respelled}"


def test_the_older_names_are_the_very_objects_vocabulary_defines():
    pytest.importorskip("temporalio")
    from openfactory.runtime.temporal import view, vocabulary, workflow

    assert view.ATTENTION_STATES is vocabulary.ATTENTION_STATES
    assert workflow.merge_wait_note is vocabulary.merge_wait_note
    assert view.MERGE_WAIT == vocabulary.MERGE_WAIT


def test_the_vocabulary_module_imports_nothing_of_the_engine():
    """Parsed, not grepped: its docstring names every module it must not import."""
    engine = {"view", "workflow", "activities", "connection", "schedule", "poller", "worker"}
    tree = ast.parse((ROOT / "openfactory/runtime/temporal/vocabulary.py").read_text())

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported |= {f"{node.module}.{alias.name}" for alias in node.names}
    reached = {name for name in imported
               if name.split(".")[0] == "temporalio"
               or (name.startswith("openfactory.runtime.temporal.")
                   and name.rsplit(".", 1)[1] in engine)}
    assert not reached, f"`vocabulary.py` reaches the engine's client through {sorted(reached)}"


# ── the command line ─────────────────────────────────────────────────────────────────────────────

def test_no_command_ends_in_a_raw_exception_without_the_engines_client():
    """Every command, asked for its `--help` and then run bare: a usage error is an answer, a
    refusal is an answer, a `ModuleNotFoundError` is neither."""
    rows = _child("commands", block=True)["commands"]

    assert len(rows) > 80, f"the walk found only {len(rows)} invocations"
    raw = [f'openfactory {" ".join(row["argv"])} → {row["raised"]}' for row in rows if row["raised"]]
    assert not raw, "these ended in a raw exception:\n  " + "\n  ".join(raw)
    unhelpful = [" ".join(row["argv"]) for row in rows
                 if row["argv"][-1:] == ["--help"] and row["exit"] != 0]
    assert not unhelpful, f"`--help` did not answer for: {unhelpful}"


@pytest.mark.parametrize("argv,code", [(["worker"], 1), (["poller", "pause"], 2),
                                       (["poller", "resume"], 2)])
def test_a_command_that_IS_the_engines_refuses_in_a_sentence(argv, code):
    rows = _child("commands", block=True)["commands"]
    row = next(r for r in rows if r["argv"] == argv)

    assert row["exit"] == code and not row["raised"], row
    assert _install_sentence() in " ".join(row["said"].split()), row["said"]
    assert "may be unreachable" not in row["said"], (
        "a missing library is not an unreachable engine — that sends the reader to a process")


def test_the_worker_MODULE_refuses_in_a_sentence_too():
    """`python -m openfactory.runtime.temporal.worker` is the spelling its own docstring gives."""
    got = _child("worker_module", block=True)

    assert "raised" not in got, got
    assert _install_sentence() in " ".join(got.get("exit", "").split()), got


def test_importing_the_worker_still_RAISES_rather_than_exiting():
    """The refusal is for a program. An importer has an `except` of its own, and a `SystemExit`
    out of an import would walk straight through it."""
    script = ("import importlib.abc, sys\n"
              "class R(importlib.abc.MetaPathFinder):\n"
              "    def find_spec(self, name, path=None, target=None):\n"
              "        if name.split('.')[0] == 'temporalio':\n"
              "            raise ModuleNotFoundError(name=name)\n"
              "sys.meta_path.insert(0, R())\n"
              "try:\n"
              "    import openfactory.runtime.temporal.worker\n"
              "except ImportError:\n"
              "    print('IMPORT-ERROR')\n")
    done = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True,
                          text=True, timeout=120, env={**os.environ, "PYTHONPATH": str(ROOT)})

    assert done.stdout.strip() == "IMPORT-ERROR", done.stdout + done.stderr[-800:]
