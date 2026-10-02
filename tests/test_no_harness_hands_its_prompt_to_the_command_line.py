"""No harness hands its prompt to the command line, at any door, whatever a project's documents
weigh (#326).

THE INCIDENT. A deployment ran this repository as one of its own projects with
`docs.constraints: docs/adr/**` — 51 ADRs, each under the 8,000-character inlining cap and nothing
bounding their sum — so the prompt came to 367,315 bytes and travelled as one argument of `sh -c`.
`execve` refused it, `OSError: [Errno 7] Argument list too long: '/bin/sh'`, in the sizer and then
in the executor, until the job parked. #349 gave both boxes a channel off the command line
(`stage_input`) and #360 routed every harness through it.

WHAT WAS PROVEN, AND WHERE THE PROOF STOPPED. The end-to-end test drove one harness
(`claude_code`) through one door (`execute`) with a 136 KB prompt and asserted the reply said
"read " — which "read 0 bytes" also says. 136 KB is past Linux's 128 KiB per-argument cap and an
eighth of macOS's `ARG_MAX` (1,048,576 bytes, `getconf ARG_MAX` on Darwin 25.6), which bounds the
whole list and has no per-argument cap. Measured on a Mac on 2026-10-01: with claude's builder cut
to put the prompt back on argv, `test_a_corpus_past_the_ceiling_runs_instead_of_raising` stayed
green (1 passed). Every other door, and every other harness, was proven by reading the command
STRING a recording box was handed.

WHAT THIS FILE PROVES, BY RUNNING IT. Every harness the registry ships, through every door every
role builder exposes — 70 on 2026-10-01: 57 on the three harnesses that stage, 13 on the one that
cannot — on the REAL worktree box (a real `/bin/sh`, a real `cat |`), and once on the real
container box where a daemon and the box image exist, against a stand-in for the CLI that writes
down what its PROCESS was handed: its argv, its stdin, its environment. The corpus has the
incident's shape (documents just under the inlining cap — 140 of them on that Mac, 1,120,000
bytes) and is sized past THIS platform's `ARG_MAX`; the first test shows that, as an argument, it
cannot be exec'd here at all.
"""

from __future__ import annotations

import errno
import inspect
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.adapters.agent import registry
from openfactory.adapters.agent.base import (
    _COMMAND_MARGIN,
    HARNESSES_WITHOUT_STAGED_PROMPT,
    MAX_ARG_STRLEN,
    AgentContext,
)
from openfactory.adapters.reviewer.base import ReviewInput
from openfactory.adapters.sandbox.base import Workspace
from openfactory.adapters.sandbox.worktree import WorktreeSandbox
from openfactory.contracts import Ticket
from openfactory.orchestrator.context import _MAX_DOC_CHARS

#: Past what ONE exec may carry on this platform, whichever limit it has: macOS bounds the whole
#: list (`ARG_MAX`), Linux bounds the list AND each argument (`MAX_ARG_STRLEN`). Capped, because a
#: raised stack limit makes Linux report an `ARG_MAX` of gigabytes while its 128 KiB cap on a single
#: argument still holds — the control below is what says the size is honest wherever this runs.
_PAST_ARG_MAX = min(os.sysconf("SC_ARG_MAX"), 4 * 1024 * 1024) + 64 * 1024

#: One line per document, unique per run: what reached a process is read back by these, so a
#: document that went missing — or turned up on the command line — is named by its number.
_MARK = re.compile(r"ADR-\d{4} [0-9a-f]{16}")

#: How long the stand-in's own argv may be: flags, a model, the harness path. The prompt is
#: megabytes; anything near this is the prompt, or a piece of it.
_ARGV_BOUND = 4096

_ROLES = {
    "executor": registry.build_executor,
    "techlead": registry.build_techlead,
    "product": registry.build_product,
    "reviewer": registry.build_reviewer,
}

_STAND_IN = '''\
#!{interpreter}
"""Stands in for a harness CLI: writes down what its PROCESS was handed, then answers."""
import json, os, sys
from pathlib import Path

calls = Path({calls!r})
calls.mkdir(parents=True, exist_ok=True)
data = b"" if sys.stdin.isatty() else sys.stdin.buffer.read()
n = len(list(calls.glob("*.json")))
(calls / f"{{n}}.stdin").write_bytes(data)
(calls / f"{{n}}.json").write_text(json.dumps({{
    "argv": sys.argv[1:],
    "env": {{k: v for k, v in os.environ.items() if k.startswith("OPENCODE_")}},
}}))
args = sys.argv[1:]
if "-o" in args:  # codex's --output-last-message, read back by a second command
    Path(args[args.index("-o") + 1]).write_text("done")
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False,
                  "result": "read %d bytes" % len(data), "num_turns": 1}}))
'''


def _install_stand_in(where: Path, *, interpreter: str, calls: str) -> Path:
    where.mkdir(parents=True, exist_ok=True)
    stand_in = where / "harness"
    stand_in.write_text(_STAND_IN.format(interpreter=interpreter, calls=calls))
    stand_in.chmod(0o755)
    return stand_in


def _calls(calls: Path) -> list[dict]:
    """What the stand-in wrote down since the last read — and then forgotten, so each door is
    judged on its own invocations."""
    made = []
    for record in sorted(calls.glob("*.json"), key=lambda p: int(p.stem)):
        call = json.loads(record.read_text())
        stdin = record.with_suffix(".stdin")
        call["stdin"] = stdin.read_bytes().decode("utf-8", "replace")
        made.append(call)
        record.unlink()
        stdin.unlink()
    return made


@pytest.fixture(scope="module")
def corpus() -> list[str]:
    """Documents the way `build_context` inlines them — each just under the per-file cap, as many
    as it takes to pass the platform's limit. The sum is the thing nothing bounded."""
    docs, size = [], 0
    while size < _PAST_ARG_MAX:
        head = f"# ADR-{len(docs):04d} {secrets.token_hex(8)}\n"
        body = ("The decision, the context it was taken in, and what it costs. " * 200)
        doc = head + body[: _MAX_DOC_CHARS - len(head)]
        docs.append(doc)
        size += len(doc.encode())
    return docs


@pytest.fixture
def real_box(tmp_path, monkeypatch):
    """The REAL worktree box, whose `harness_path` answers the stand-in for every harness."""
    calls = tmp_path / "calls"
    stand_in = _install_stand_in(tmp_path / "bin", interpreter=sys.executable, calls=str(calls))
    box = WorktreeSandbox(root=tmp_path / "worktrees")
    ws = Workspace(path=tmp_path / "worktrees" / "job", branch="openfactory/326",
                   base_branch="main")
    ws.path.mkdir(parents=True)
    monkeypatch.setattr(box, "harness_path", lambda name: str(stand_in))
    yield box, ws, calls
    box.cleanup(workspace=ws)


def _doors(built) -> list[str]:
    """Every public method that takes a box — the doors a prompt goes through. Read off the object
    the registry builds, so a door added later is driven here without a line of this file changing.
    """
    return [name for name, fn in inspect.getmembers(built, inspect.ismethod)
            if not name.startswith("_") and "sandbox" in inspect.signature(fn).parameters]


def _arguments(fn, corpus: list[str]) -> dict:
    """The corpus in every text a door requires. In the card's Context as well as in its
    constraints, because the sizer's spec-only view (`techlead._ticket_text`) does not read
    constraints — and a door whose prompt carried none of the corpus would prove nothing here."""
    joined = "\n\n".join(corpus)
    ticket = Ticket(id="#326", title="add a health check", objective="expose /health",
                    context=joined, repo="o/r")
    context = AgentContext(ticket=ticket, constraints=corpus,
                           allowed_tools=["Read", "Edit", "Bash"])
    texts = {"prompt", "situation", "question", "brief", "failure_log"}
    kw: dict = {}
    for name, param in inspect.signature(fn).parameters.items():
        if name in ("sandbox", "workspace") or param.default is not inspect.Parameter.empty:
            continue
        if name == "context":
            kw[name] = context
        elif name == "review_input":
            kw[name] = ReviewInput(ticket=ticket, diff="+" + joined, constraints=corpus)
        elif name == "handle":
            kw[name] = ""  # an unreadable handle runs cold: the door is still the same door
        elif name in texts:
            kw[name] = joined
        else:
            raise AssertionError(
                f"`{fn.__qualname__}` takes `{name}`, which this guard does not know how to fill — "
                f"say here which text it carries, so the new door is driven with the corpus too")
    return kw


def _knock(where: str, fn, kw: dict):
    """Call one door, and turn the incident's own failure into a sentence naming the door."""
    try:
        return fn(**kw)
    except OSError as exc:
        pytest.fail(f"{where}: {exc} — the prompt reached the command line, and the kernel "
                    f"refused the exec before the harness existed (#326)")


def _project(kind: str):
    return SimpleNamespace(harness=kind, model=None, language=None)


# ── the premise ──────────────────────────────────────────────────────────────────────────────────


def test_the_corpus_is_one_this_platform_cannot_exec_as_an_argument(corpus):
    """THE CONTROL. Without it, every assertion below could pass on a platform where the corpus
    happens to fit — which is how the 136 KB proof came to say nothing on a Mac."""
    joined = "\n\n".join(corpus)
    with pytest.raises(OSError) as raised:
        subprocess.run(["/bin/sh", "-c", ":", "_", joined], capture_output=True, timeout=30)
    assert raised.value.errno == errno.E2BIG, raised.value


# ── every door of every harness, on the worktree box ─────────────────────────────────────────────


@pytest.mark.parametrize("role", sorted(_ROLES))
@pytest.mark.parametrize(
    "kind", sorted(k for k in registry.HARNESSES if k not in HARNESSES_WITHOUT_STAGED_PROMPT))
def test_every_door_hands_the_whole_prompt_over_stdin_and_none_of_it_on_argv(
        kind, role, real_box, corpus):
    box, ws, calls = real_box
    built = _ROLES[role](_project(kind))
    doors = _doors(built)
    assert doors, f"{kind}/{role}: {type(built).__name__} exposes no door that takes a box"
    sent = set(_MARK.findall("\n".join(corpus)))

    for door in doors:
        fn = getattr(built, door)
        where = f"{kind}/{role}.{door}"
        _knock(where, fn, {"sandbox": box, "workspace": ws, **_arguments(fn, corpus)})
        made = _calls(calls)
        assert made, f"{where}: the harness never ran, so nothing was delivered at all"
        for call in made:
            argv = call["argv"]
            assert not _MARK.findall(" ".join(argv)), (
                f"{where}: the prompt is on the command line — {len(_MARK.findall(' '.join(argv)))}"
                f" documents in the harness's argv")
            assert sum(len(a.encode()) for a in argv) < _ARGV_BOUND, (
                f"{where}: the harness's argv is {sum(len(a.encode()) for a in argv):,} bytes")
            got = set(_MARK.findall(call["stdin"]))
            assert got == sent, (
                f"{where}: the harness read {len(got)} of the {len(sent)} documents from stdin "
                f"({len(call['stdin'].encode()):,} bytes)")


# ── the harness whose CLI can only take an argument ──────────────────────────────────────────────


@pytest.mark.parametrize("role", sorted(_ROLES))
@pytest.mark.parametrize("kind", sorted(HARNESSES_WITHOUT_STAGED_PROMPT))
def test_a_harness_that_takes_its_prompt_only_as_an_argument_refuses_the_corpus_by_name(
        kind, role, real_box, corpus):
    """`kimi-code`'s `-p` takes a value and reads nothing from stdin (0.31.1, pinned; 0.32.0), so
    for that row the prompt IS the argument. What the row owes is the named refusal: no process
    started with an argument the kernel would refuse, and a sentence a person can act on."""
    box, ws, calls = real_box
    built = _ROLES[role](_project(kind))
    doors = _doors(built)
    assert doors, f"{kind}/{role}: {type(built).__name__} exposes no door that takes a box"

    for door in doors:
        fn = getattr(built, door)
        where = f"{kind}/{role}.{door}"
        result = _knock(where, fn, {"sandbox": box, "workspace": ws, **_arguments(fn, corpus)})
        assert _calls(calls) == [], (
            f"{where}: a process was started with a prompt no argument can carry")
        said = getattr(result, "summary", "") or ""
        assert f"{MAX_ARG_STRLEN:,}-byte per-argument limit" in said, (
            f"{where}: the refusal does not name the limit — {said[:200]!r}")


def test_the_ceiling_counts_the_bytes_a_multibyte_prompt_costs_not_its_characters(real_box):
    """The approval's note on #360: the ceiling was pinned only by ASCII prompts, so counting
    characters instead of bytes could not fail a test. It matters most on the argument-only row,
    which carries every prompt on argv. A prompt of '€' under the ceiling in characters is three
    times that in bytes — past the 128 KiB a Linux argument may hold."""
    box, ws, calls = real_box
    ceiling = MAX_ARG_STRLEN - _COMMAND_MARGIN
    prompt = "€" * (ceiling // 2)
    assert len(prompt) < ceiling < len(prompt.encode()), "the fixture must straddle the ceiling"

    (kind,) = sorted(HARNESSES_WITHOUT_STAGED_PROMPT)
    result = registry.HARNESSES[kind]().ask(sandbox=box, workspace=ws, prompt=prompt)

    assert _calls(calls) == [], "a prompt past the byte ceiling was put on the command line"
    assert not result.ok and f"{MAX_ARG_STRLEN:,}-byte per-argument limit" in result.summary


def test_a_multibyte_prompt_under_the_ceiling_reaches_the_argument_only_harness_intact(real_box):
    """The other side of the ceiling: a prompt that fits is delivered — through a real `sh -c`, its
    quoting and its multibyte characters — byte for byte, as the one argument after `-p`."""
    box, ws, calls = real_box
    prompt = "Decisão registada: o custo é medido em bytes. " + "€ç" * 20_000
    assert len(prompt.encode()) < MAX_ARG_STRLEN - _COMMAND_MARGIN

    (kind,) = sorted(HARNESSES_WITHOUT_STAGED_PROMPT)
    registry.HARNESSES[kind]().ask(sandbox=box, workspace=ws, prompt=prompt)

    made = _calls(calls)
    assert len(made) == 1, f"a prompt that fits started {len(made)} processes, not one"
    argv = made[0]["argv"]
    assert argv[argv.index("-p") + 1].endswith(prompt), "the argument is not the prompt it was"


# ── what the staged command must keep of the argument form ──────────────────────────────────────


def test_opencode_s_profile_is_handed_to_opencode_and_not_to_the_cat_that_feeds_it(real_box):
    """`cat <path> | VAR=… opencode run` and `VAR=… cat <path> | opencode run` differ by where two
    words sit, and only one of them hands opencode its read-only profile and the lock on the
    client's own `opencode.json`. A repository's `opencode.json` can grant `bash/edit/write` under
    this adapter's own agent name (verified when the lock was added), so the second spelling turns
    every judging pass into a writing one — with the command string still containing every word
    the string-level test looks for."""
    from openfactory.adapters.agent.opencode import judge_config

    box, ws, calls = real_box
    opencode = registry.HARNESSES["opencode"]()
    opencode.ask(sandbox=box, workspace=ws, prompt="which module owns /health?")
    opencode.execute(sandbox=box, workspace=ws, context=AgentContext(
        ticket=Ticket(id="#326", title="t", objective="o", repo="o/r"), allowed_tools=["Read"]))

    made = _calls(calls)
    assert len(made) == 2, f"two passes ran opencode {len(made)} times"
    judging, coding = made
    keys =("OPENCODE_CONFIG_CONTENT", "OPENCODE_DISABLE_PROJECT_CONFIG")
    assert "which module owns /health?" in judging["stdin"], "the judging prompt was not staged"
    assert {k: judging["env"].get(k) for k in keys} == {
        "OPENCODE_CONFIG_CONTENT": judge_config(), "OPENCODE_DISABLE_PROJECT_CONFIG": "1"}
    assert {k: coding["env"].get(k) for k in keys} == {
        "OPENCODE_CONFIG_CONTENT": None, "OPENCODE_DISABLE_PROJECT_CONFIG": "1"}


# ── the container box, across a real docker hop ──────────────────────────────────────────────────


def test_the_container_box_hands_the_corpus_over_too(tmp_path, monkeypatch, corpus):
    """"It is not one box," the issue says: the worktree box and the container box assembled the
    same string, and fixing one leaves the other broken. The container's half (`docker cp` in,
    `docker exec sh -c` to run) was proven against a recorded daemon; this asks a real one.

    The preconditions are asked at run time, as `test_the_box_transmits_while_it_runs` asks them:
    collection stays the same on every machine and the skip names what is missing."""
    from openfactory.adapters.sandbox.container import ContainerSandbox
    from openfactory.factory import resolve_box_image

    if not shutil.which("docker") or subprocess.run(
            ["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("no docker daemon on this machine — the container hop is unmeasured here")
    image = resolve_box_image(sandbox="container")
    if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode:
        pytest.skip(f"the box image {image!r} is not built on this machine — `docker compose "
                    f"build` makes it; the container hop is unmeasured until it exists")

    repo = tmp_path / "repo"
    repo.mkdir()
    for argv in (["git", "init", "-b", "main"], ["git", "config", "user.email", "t@t"],
                 ["git", "config", "user.name", "t"], ["git", "commit", "--allow-empty", "-m", "x"]):
        assert subprocess.run(argv, cwd=repo, capture_output=True).returncode == 0

    box = ContainerSandbox(image=image, project=f"argv-{secrets.token_hex(3)}")
    ws = box.prepare(repo_path=repo, base_branch="main", branch="sdlc/argv-326")
    try:
        # INSIDE the bind-mounted clone, so the box can run it and the host can read what it wrote.
        # The record directory is made HERE and opened to every uid: a box that runs as root
        # writes root-owned records, which the host can still read and unlink only from a
        # directory the host owns.
        calls = ws.host_path / ".stand-in" / "calls"
        calls.mkdir(parents=True)
        calls.chmod(0o777)
        _install_stand_in(ws.host_path / ".stand-in", interpreter="/usr/bin/env python3",
                          calls="/workspace/.stand-in/calls")
        monkeypatch.setattr(box, "harness_path", lambda name: "/workspace/.stand-in/harness")
        built = registry.build_executor(_project("claude_code"))
        _knock("claude_code/executor.execute on the container box", built.execute,
               {"sandbox": box, "workspace": ws, **_arguments(built.execute, corpus)})

        made = _calls(calls)
        assert len(made) == 1, f"the harness ran {len(made)} times in the box, not once"
        (call,) = made
        assert not _MARK.findall(" ".join(call["argv"])), "the prompt is on the command line"
        assert set(_MARK.findall(call["stdin"])) == set(_MARK.findall("\n".join(corpus))), (
            f"the harness read {len(call['stdin'].encode()):,} bytes from stdin, not the corpus")
    finally:
        box.cleanup(workspace=ws)
