"""The header may not state a fact the page has, at that instant, no way to know (#139).

2026-08-19, the pilot, on the reference surface: he could not understand any of it — "floor
running", "reconnecting" and nothing at all were, he said, the same thing to him. He was reading
`floor: running` in the header, `Floor idle` in the card directly below it, and a `reconnecting`
pill that is not about the factory at all but about his own browser's socket.

The vocabulary was half the problem. THIS FILE IS THE OTHER HALF, and it is the half nobody had
looked at: the page could not see the facts it was reporting.

    the stream   `/api/temporal/stream` carried `jobs` and nothing else — no `intake`, no `build`.
    the page     `engine = JSON.parse(e.data)` REPLACED the whole object with that frame.
    therefore    every frame deleted the poller's state and the build stamps, and only the
                 20-second safety-net poll put them back.
    and at boot  `loadEngine` was on a 20-second interval and was never called once up front.

MEASURED, on the live pilot, before the fix: the SSE opening frame's keys were exactly
`[address, connected, jobs, ui_base]`, and in 26 seconds on an idle floor the stream sent 1 data
frame and 12 heartbeats. So for the first 20 seconds after EVERY reload, `floorStatement` fell
through every intake branch and returned `running` — whatever the poller was doing — and
`paintBuildSplit` saw `agree === undefined` and hid itself. The operator's screen was not
confusing by accident; it was stating things it could not know.

THE FIX IS TWO-SIDED ON PURPOSE. The server sends the facts, AND the page keeps a fact it is not
sent. Either alone leaves the failure reachable: a panel running against an older worker gets no
`intake` on the stream, and a page that erased what it was not sent would go blind again.
"""

from __future__ import annotations

import inspect
import io
import json
import re
import shutil
import subprocess
import tokenize
from pathlib import Path

import pytest

from openfactory.api import app as api

PANEL_PATH = Path(inspect.getfile(api)).parent / "panel.html"
PANEL = PANEL_PATH.read_text()
CODE = "\n".join(ln for ln in PANEL.splitlines() if not ln.lstrip().startswith("//"))


def _code(fn) -> str:
    """`inspect.getsource(fn)` with the COMMENTS AND THE DOCSTRING TAKEN OUT.

    ADDED 2026-09-17, AFTER THIS GUARD SET WENT DECORATIVE UNDER ITS OWN PROSE. The blip case
    below then asserted the literal `slow, slow_at = {}, 0.0` was in the stream. #146's second pass
    added a comment four lines above it explaining that the stream drops everything on a blip — and
    quoted that exact line to say so. `tools/mutations/139_a_frame_erases_what_it_omits.py`'s "a
    blip carries a stale poller read across it" row, which had been red for as long as it existed,
    then SURVIVED: the cut deleted the code and the guard read the sentence describing it (measured
    2026-09-17, 18 rows, 17 red). That case now DRIVES the loop instead — see its own docstring for
    the second reason it had to — and the three cases left here still read the source, which is why
    this helper stays.

    That is the sixth-and-then-some instance of the failure CONTRIBUTING names — "a guard that
    greps a file is satisfied by the EXPLANATION of the very thing it forbids" — and its remedy is
    the one written there: where you must search text, strip the comments first. Parsed with
    `tokenize` rather than matched with a regex, because `#` and `\"\"\"` inside a string literal
    are code, and a regex cannot tell. The lines are blanked rather than removed so a failure
    message still points at the line number the reader sees in the file.
    """
    src = inspect.getsource(fn)
    lines = src.splitlines(keepends=True)
    blank: set[int] = set()
    seen_indent = False
    docstring_done = False
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.INDENT:
            seen_indent = True
        elif tok.type == tokenize.COMMENT:
            lines[tok.start[0] - 1] = lines[tok.start[0] - 1][:tok.start[1]].rstrip() + "\n"
        elif tok.type == tokenize.STRING and seen_indent and not docstring_done:
            # The body's FIRST string statement is the docstring; every later one is a value.
            docstring_done = True
            blank.update(range(tok.start[0], tok.end[0] + 1))
    return "".join("\n" if i in blank else ln for i, ln in enumerate(lines, 1))


def _brace_balanced(src: str, opener: str) -> str:
    """The ONE statement starting at `opener`, cut at ITS OWN closing brace.

    Added 2026-09-17 (#146, second pass), when the cached pair became a two-line assignment. The
    slice used to end at the first newline, which would then have held only half the statement —
    and the half it dropped is `"build": _build_report()`, which appears AGAIN on the disconnected
    branch below. Ending at the newline and searching the remainder of the function would have
    matched that second occurrence, which is exactly the false positive this file's own docstring
    records for the first cut of this guard. So the end is computed from the braces, not guessed.
    """
    start = src.index(opener)
    depth = 0
    for i in range(start + opener.index("{"), len(src)):
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        if depth == 0:
            return src[start:i + 1]
    raise AssertionError(f"{opener!r} is never closed — the stream's source is not what this "
                         f"guard can read")


# ── 1. the server sends what the header is made of ──────────────────────────────────────────────

def test_the_STREAM_carries_the_poller_state_and_the_build_stamps():
    """The frame the page lives on. `/api/temporal/jobs` always carried these; the STREAM did not,
    and the stream is what the page actually runs on between polls."""
    src = _code(api.temporal_stream)
    # RE-PINNED 2026-09-17 (#146, second pass): the stream's intake read now goes through the
    # process-wide memo, `_floor_reading.intake_cached(client)`, instead of calling `tv.intake`
    # itself — all three readers of that schedule read share one window. The assertion is the same
    # one: the poller's state is in the pair the frame is built from. Only the call it names moved.
    INTAKE = '"intake": await _floor_reading.intake_cached(client)'
    assert INTAKE in src, (
        "the stream still omits the poller's state — the header goes blind between polls")
    slow = _brace_balanced(src, "slow = {")
    assert INTAKE in slow and '"build": _build_report()' in slow, (
        f"the frame's cached pair is {slow.strip()!r} — a fact the header is made of is missing. "
        f"(Asserted on the assignment, not on the file: `_build_report()` also appears on the "
        f"disconnected branch, and the first cut of this guard passed on that second occurrence. "
        f"The assignment now spans two lines, so the slice ends at its own closing brace rather "
        f"than at the first newline — cutting at the newline would have read half of it and "
        f"passed on an `intake` with no `build`.)")
    assert "**slow}" in src, "the cached pair is computed and never reaches the frame"


def test_the_slow_facts_are_CACHED_rather_than_read_every_two_seconds():
    """`tv.intake` describes `1 + N + P` Temporal schedules — the poller, one per enabled project,
    one more per project declaring a `product`: 2 for one project, 4 for three, 7 for three with
    products, 11 for five with products (measured 2026-09-16; the count itself is guarded in
    `tests/test_the_floor_is_not_re_read_on_every_frame.py` §6, against a counting client). At the
    stream's 2-second tick, per connected browser, that turns a status line into load — so a status
    line nobody can afford is a status line somebody removes.

    "3-5 schedules" stood in this docstring and in the stream's own until 2026-09-17. It was never
    measured, and #146's whole argument is that an unchecked number in a comment is a defect."""
    src = _code(api.temporal_stream)
    assert "_STREAM_SLOW_S" in src, "the schedule read is not throttled at all"
    assert api._STREAM_SLOW_S <= 30, (
        f"the slow-fact cache is {api._STREAM_SLOW_S}s — long enough for the header to lag a "
        f"change an operator just made")
    assert api._STREAM_SLOW_S >= 5, "the cache is too short to be a cache"


@pytest.mark.asyncio
async def test_a_BLIP_does_not_carry_a_stale_poller_read_across_it(monkeypatch, tmp_path):
    """The page is never shown a poller state from BEFORE an engine failure.

    DRIVEN NOW, NOT READ (2026-09-17). This case used to assert the literal `slow, slow_at = {}, 0.0`
    was in the stream's source, and that line is still there — but #146's second pass moved the
    intake read onto a PROCESS-WIDE memo, and clearing the generator's own copy then only forces a
    re-read that the shared memo can answer with the value the blip was meant to discard. The line
    the guard read stopped carrying the property the guard is named for: green, and measuring the
    build copy. That is the same failure as the one four lines up in `_code`'s docstring, one level
    out — a guard describing an invariant the code no longer holds — so it stopped reading the
    stream and started running it.

    THREE PASSES OF THE REAL LOOP: a good frame, an engine that dies, and a good frame after it.
    The poller is PAUSED during the outage, so the post-blip answer differs from the pre-blip one
    and a stale read is visible in the frame itself rather than only in a call count. Both are
    asserted: the frame says `on: False`, and `tv.intake` was read twice.
    """
    from openfactory.floor import reading
    from openfactory.runtime.temporal import view as tv

    reg = tmp_path / "registry.yaml"
    reg.write_text("projects: {}\n")
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))

    answers = [{"known": True, "on": True, "note": "", "watchers": {}},
               {"known": True, "on": False, "note": "paused while it was away", "watchers": {}}]
    reads: list[dict] = []
    alive = [True]

    async def _intake(_client=None):
        reads.append(answers[min(len(reads), len(answers) - 1)])
        return reads[-1]

    async def _list_jobs(*_a, **_k):
        if not alive[0]:
            raise RuntimeError("the engine went away")
        return []

    async def _connect(*_a, **_k):
        return object()

    async def _no_wait(*_a, **_k):
        return None

    monkeypatch.setattr(tv, "intake", _intake)
    monkeypatch.setattr(tv, "list_jobs", _list_jobs)
    monkeypatch.setattr(tv, "connect", _connect)
    monkeypatch.setattr(tv, "temporal_config", lambda: ("localhost:7233", "default"))
    monkeypatch.setattr(tv, "ui_base", lambda: "")
    # The loop sleeps 2 s between passes. Three passes of real wall clock is six seconds of suite
    # for a property that is about ORDER, not duration — and both windows (the generator's 10 s and
    # the shared memo's) must stay UNEXPIRED across the blip, or this case would pass on a cache
    # that merely timed out rather than on one the blip dropped.
    monkeypatch.setattr(api.asyncio, "sleep", _no_wait)
    reading.forget_intake()

    class _Socket:
        """Three passes, then hang up."""

        def __init__(self):
            self.asked = 0

        async def is_disconnected(self):
            self.asked += 1
            if self.asked == 3:      # the third pass runs against a recovered engine
                alive[0] = True
            elif self.asked == 2:    # …the second one dies inside the frame
                alive[0] = False
            return self.asked > 3

    frames = []
    response = await api.temporal_stream(_Socket())
    async for chunk in response.body_iterator:
        if chunk.startswith("data: "):
            frames.append(json.loads(chunk[len("data: "):]))

    assert len(frames) == 3, f"the loop did not run three passes: {frames}"
    assert frames[0]["connected"] is True and frames[0]["intake"]["on"] is True, (
        f"the first frame did not read a running poller: {frames[0]}")
    assert frames[1]["connected"] is False, (
        f"the engine died and the stream did not say so: {frames[1]}")
    assert "intake" not in frames[1], (
        f"a poller state appears beside a frame saying the engine is unreachable: {frames[1]}")

    assert frames[2]["intake"] == answers[1], (
        f"the frame after the blip carries the poller state from BEFORE it ({frames[2]['intake']}) "
        f"— the poller was paused while the engine was away and the page is being told it runs. "
        f"Clearing the generator's own `slow` is not enough since the read became process-wide; "
        f"the blip must drop the shared memo too (`floor.reading.forget_intake`)")
    assert len(reads) == 2, (
        f"the schedules were read {len(reads)} time(s) across the blip, not 2 — the post-blip "
        f"frame was served from a memo filled before the engine died")


def test_the_DISCONNECTED_frame_still_carries_the_build_stamps():
    """A page that cannot reach the engine is MORE likely to be the stale half, not less — that is
    exactly the reading where the operator needs to know which code is answering him (#135)."""
    src = _code(api.temporal_stream)
    tail = src[src.index('"connected": False, "address": addr, "error"'):]
    assert '"build": _build_report()' in tail[:220], (
        "the build report is dropped on the branch where it matters most")


# ── 2. the page keeps a fact it was not sent ────────────────────────────────────────────────────

def _frames(*payloads, start=None):
    """RUN `applyEngineFrame` over a sequence of frames and return the resulting `engine`.

    Executed, not read. Reading the source proves only that the word "intake" appears in the
    function; this house has shipped five guards satisfied by a string in a comment. The only way
    to assert what a given frame does to the previous state is to feed it one."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH — the source-level guards above still run")

    consts = re.search(r"const ENGINE_KEPT_IF_ABSENT=[^\n]*\n", CODE)
    assert consts, "the merge allowlist is no longer where this guard can read it"
    body = CODE[CODE.index("function applyEngineFrame("):]
    body = body[:body.index("\n}\n") + 3]

    script = (f"var engine={json.dumps(start)};var _engineAt=0;\n"
              + consts.group(0) + body
              + "\n" + "".join(f"applyEngineFrame({json.dumps(p)});" for p in payloads)
              + "\nconsole.log(JSON.stringify(engine));")
    got = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr[:400]
    return json.loads(got.stdout)


def test_a_frame_WITHOUT_intake_leaves_the_previous_answer_standing():
    """THE DEFECT, in one assertion. This is what wiped the poller's state twice a minute and made
    the header say `running` over a paused poller."""
    out = _frames(
        {"connected": True, "jobs": [], "intake": {"known": True, "on": False, "note": "held"}},
        {"connected": True, "jobs": []},          # …a frame from an older worker, or a partial one
    )
    assert out["intake"] == {"known": True, "on": False, "note": "held"}, (
        "a frame that said nothing about the poller ERASED what the page knew about it")


def test_a_frame_WITH_intake_replaces_it():
    """The positive twin. A merge that never overwrote would pin the first answer for ever, which
    is the same defect wearing the opposite sign."""
    out = _frames(
        {"connected": True, "jobs": [], "intake": {"known": True, "on": False, "note": "held"}},
        {"connected": True, "jobs": [], "intake": {"known": True, "on": True, "note": ""}},
    )
    assert out["intake"]["on"] is True, "the poller was resumed and the page kept saying paused"


def test_the_BUILD_stamps_survive_a_frame_that_omits_them():
    """Same rule, and the reason #135's banner was invisible in a browser: every stream frame
    dropped `build`, so `agree` was `undefined` and the banner hid itself."""
    out = _frames(
        {"connected": True, "jobs": [], "build": {"agree": False, "stamp": "aaa", "others": {}}},
        {"connected": True, "jobs": []},
    )
    assert out["build"]["agree"] is False, "the split was proven and then forgotten by the next frame"


def test_an_ERROR_belongs_to_the_FRAME_THAT_CARRIED_IT():
    """The trap a naive merge sets. `error` appears only on the disconnected frame — inherit it and
    the first blip pins its message on screen for the rest of the session, under a header that has
    long since gone healthy."""
    out = _frames(
        {"connected": False, "jobs": [], "error": "connection refused"},
        {"connected": True, "jobs": [], "address": "1.2.3.4:7233"},
    )
    assert "error" not in out, f"a recovered engine still carries {out.get('error')!r}"


def test_an_EMPTY_JOB_LIST_is_an_answer_and_is_never_kept():
    """`jobs: []` on a disconnected frame means "I cannot see any" — the frame's own answer. Keeping
    the previous list would leave finished work rendered as still in production, which is the
    stale-panel bug the heartbeat exists to prevent."""
    out = _frames(
        {"connected": True, "jobs": [{"project": "acme", "issue": "1", "status": "running"}]},
        {"connected": False, "jobs": [], "error": "engine unreachable"},
    )
    assert out["jobs"] == [], "a disconnected frame still shows the jobs from before it"


def test_a_frame_that_is_not_an_object_changes_NOTHING():
    """`api()` does not throw on a non-2xx — it returns the parsed error body. A route answering
    `null`, a string, or a bare list must not be able to blank the floor."""
    start = {"connected": True, "jobs": [{"issue": "1"}], "intake": {"known": True, "on": True}}
    for junk in (None, "unauthorized", 7):
        out = _frames(junk, start=start)
        assert out == start, f"the floor was rewritten by {junk!r}"


# ── 3. the page asks once, up front ─────────────────────────────────────────────────────────────

def test_the_FIRST_ANSWER_is_asked_for_at_boot():
    """`loadEngine` was only ever on a 20-second interval. So the first 20 seconds of every page
    load ran on the SSE's opening frame — which carried no `intake` and no `build` — and the header
    spent that window claiming the floor was running, for everybody, on every reload."""
    boot = CODE[CODE.index("async function boot()"):]
    boot = boot[:boot.index("\n}\n") + 3]
    assert "await loadEngine()" in boot, (
        "nothing fetches the complete engine state before the stream opens — the first paint is "
        "made of whatever the opening frame happened to carry")
    assert boot.index("await loadEngine()") < boot.index("engineStream()"), (
        "the stream opens before the one complete read, so the opening partial frame wins")


def test_a_PAINTER_THAT_THROWS_is_not_swallowed_by_the_parser_s_catch():
    """`applyEngine()` sat inside `try{engine=JSON.parse(...);applyEngine()}catch(_){}`. One missed
    null-guard in any painter therefore froze the panel on its last frame with nothing in the
    console, no toast and no banner — a screen that looks exactly like a quiet factory."""
    body = CODE[CODE.index("function engineStream()"):]
    body = body[:body.index("\n}\n") + 3]
    handler = body[body.index("onmessage"):]
    caught = handler[handler.index("try{"):handler.index("}")]
    assert "applyEngine()" not in caught, (
        "the painters still run inside the parser's catch — an exception in one of them silently "
        "freezes the whole page")
    assert "applyEngine()" in handler, "the frame is merged and then nothing repaints"


def test_a_FAILED_FETCH_is_not_reported_as_the_ENGINE_being_unreachable():
    """They are different facts and the panel stated the wrong one. `loadEngine`'s catch
    synthesised `{connected:false}`, so a browser that could not reach the PANEL announced that
    Temporal was down — sending an operator to look at the engine over a failure in his own tab."""
    body = CODE[CODE.index("async function loadEngine()"):]
    body = body[:body.index("\n}\n") + 3]
    assert "connected:false" not in body.replace(" ", ""), (
        "this page's own fetch failure is still rendered as a claim about the engine")
    assert "_engineErr" in body, "a failed read leaves no trace at all, so nothing can report it"


# ── 4. two live bugs the same pass removes ──────────────────────────────────────────────────────

def test_the_machine_card_KEY_does_not_outlive_the_view():
    """A live bug, found while reading this code. `refreshProject` skips redrawing `#active` when
    the running-job set is unchanged — so the live log feed is not wiped every frame. But the key
    survived navigation while `render()` recreated `#active` EMPTY, so leaving a project with a
    running job and returning while the same job ran skipped the redraw and left the card blank
    for as long as that job lasted."""
    body = CODE[CODE.index("function render()"):]
    body = body[:body.index("\n}\n") + 3]
    assert "window._machineKey=null" in body.replace(" ", ""), (
        "the redraw key outlives the view it belongs to — returning to a busy project shows an "
        "empty floor card")


def test_the_degraded_transport_has_a_TREATMENT_and_not_just_a_class():
    """`streamStatus` has emitted `pill b-warn` since the pill existed, and `.b-warn` was never
    defined — so the one state meant to stand out rendered flatter than the healthy one it was
    warning about."""
    css = PANEL[PANEL.index("<style>"):PANEL.index("</style>")]
    assert re.search(r"\n\.b-warn\{[^}]+\}", css), "`b-warn` is emitted and styled by nothing"
    assert "b-warn" in CODE, "nothing emits the class the rule above styles"
