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
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from openfactory.api import app as api

PANEL_PATH = Path(inspect.getfile(api)).parent / "panel.html"
PANEL = PANEL_PATH.read_text()
CODE = "\n".join(ln for ln in PANEL.splitlines() if not ln.lstrip().startswith("//"))


# ── 1. the server sends what the header is made of ──────────────────────────────────────────────

def test_the_STREAM_carries_the_poller_state_and_the_build_stamps():
    """The frame the page lives on. `/api/temporal/jobs` always carried these; the STREAM did not,
    and the stream is what the page actually runs on between polls."""
    src = inspect.getsource(api.temporal_stream)
    assert '"intake": await tv.intake(client)' in src, (
        "the stream still omits the poller's state — the header goes blind between polls")
    slow = src[src.index("slow = {"):]
    slow = slow[:slow.index("\n")]
    assert '"intake": await tv.intake(client)' in slow and '"build": _build_report()' in slow, (
        f"the frame's cached pair is {slow.strip()!r} — a fact the header is made of is missing. "
        f"(Asserted on the assignment, not on the file: `_build_report()` also appears on the "
        f"disconnected branch, and the first cut of this guard passed on that second occurrence.)")
    assert "**slow}" in src, "the cached pair is computed and never reaches the frame"


def test_the_slow_facts_are_CACHED_rather_than_read_every_two_seconds():
    """`tv.intake` describes 3-5 Temporal schedules. At the stream's 2-second tick, per connected
    browser, that turns a status line into load — so a status line nobody can afford is a status
    line somebody removes."""
    src = inspect.getsource(api.temporal_stream)
    assert "_STREAM_SLOW_S" in src, "the schedule read is not throttled at all"
    assert api._STREAM_SLOW_S <= 30, (
        f"the slow-fact cache is {api._STREAM_SLOW_S}s — long enough for the header to lag a "
        f"change an operator just made")
    assert api._STREAM_SLOW_S >= 5, "the cache is too short to be a cache"


def test_a_BLIP_does_not_carry_a_stale_poller_read_across_it():
    """The disconnected branch drops the cache. Keeping it would let the page show the schedule
    state from BEFORE an engine failure, beside a frame saying the engine is unreachable."""
    src = inspect.getsource(api.temporal_stream)
    assert "slow, slow_at = {}, 0.0" in src, (
        "an engine blip keeps the cached intake, so the page is told about a poller nobody could "
        "reach")


def test_the_DISCONNECTED_frame_still_carries_the_build_stamps():
    """A page that cannot reach the engine is MORE likely to be the stale half, not less — that is
    exactly the reading where the operator needs to know which code is answering him (#135)."""
    src = inspect.getsource(api.temporal_stream)
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
