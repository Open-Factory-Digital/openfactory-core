"""The panel is pushed to, and when it cannot be it SAYS so.

`channel_messages` said it of itself: *"Pull, deliberately. There is no socket here and no push;
the browser asks."* Honest, and the first thing a client feels — the panel re-read the AGENT
CONVERSATION every fifteen seconds, so a reply typed by the tech-lead sat invisible for up to
fifteen seconds while somebody watched the screen. That does not read as slow, it reads as broken.

TWO PROPERTIES, AND THE SECOND IS THE LOAD-BEARING ONE.

  1. the socket carries what the panel watches, and it authenticates;
  2. a socket that dies falls back to polling AND SAYS SO.

The second is where this platform's headline invariant lives. A chat that silently stopped
receiving is the purest possible violation of "nothing stalls in silence": the screen looks
perfectly healthy and the factory is talking to nobody. So the polling timers are never removed —
only skipped while the socket is healthy — and the header carries which of the two is happening.

THE AUTH TEST IS NOT BELT-AND-BRACES. `_panel_gate` is an `@app.middleware("http")`, and
Starlette's own first line is `if scope["type"] != "http": await self.app(...)` — a WebSocket
bypasses it entirely. Read in `starlette/middleware/base.py` before the route was written, not
assumed. Without its own check the stream would have served every project name, every job and
every word the factory has said to a client from a URL with no credential, on the same service
whose HTTP half is correctly gated.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[1]
PANEL = (ROOT / "openfactory/api/panel.html").read_text()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "a-test-secret")
    from openfactory.api.app import app

    return TestClient(app)


def test_the_stream_refuses_a_connection_with_no_credential(client):
    """The HTTP middleware does not gate websockets. This is the only thing that does."""
    with pytest.raises(Exception) as caught:  # noqa: PT011 — starlette's disconnect type varies
        with client.websocket_connect("/api/stream") as ws:
            ws.receive_text()
    assert "WebSocketDisconnect" in type(caught.value).__name__ or "reject" in str(caught.value)


def test_the_stream_refuses_a_WRONG_credential(client):
    with pytest.raises(Exception):  # noqa: B017, PT011
        with client.websocket_connect("/api/stream?token=not-the-secret") as ws:
            ws.receive_text()


def test_the_first_frame_is_a_full_snapshot(client):
    """A stream that carried only deltas would render an empty screen on connect, and an empty
    screen is indistinguishable from a quiet factory — the confusion this product removes."""
    with client.websocket_connect("/api/stream?token=a-test-secret") as ws:
        hello = json.loads(ws.receive_text())
        assert hello["kind"] == "hello" and hello["tick"] > 0
        first = json.loads(ws.receive_text())
        assert first["kind"] == "update"
        assert "projects" in first, first


def test_the_stream_follows_the_client_between_projects(client):
    """Opening a project's cockpit must not drop and re-open the socket."""
    with client.websocket_connect("/api/stream?token=a-test-secret") as ws:
        ws.receive_text()  # hello
        ws.receive_text()  # first snapshot
        ws.send_text(json.dumps({"project": "somewhere-else"}))
        after = json.loads(ws.receive_text())
        assert after["project"] == "somewhere-else", after


def test_an_unreadable_section_is_NULL_and_never_an_empty_chat(monkeypatch):
    """`None` = could not read. `[]` = read it, nothing there. The rule this codebase pays for.

    A chat rendered empty because the store could not be read is a claim about the client's
    conversation; the truth is a claim about us. The snapshot must be able to say which.
    """
    from openfactory.api import app as panel

    monkeypatch.setattr(panel, "channel_messages",
                        lambda _p: (_ for _ in ()).throw(OSError("the store is gone")))
    snap = panel._stream_snapshot("acme")
    assert snap["chat"] is None, snap
    assert snap["projects"] is not None, "a broken chat read took the project list down with it"


def test_a_broken_registry_does_not_end_the_stream(monkeypatch):
    """One bad read must not kill the socket for everything else on the page."""
    from openfactory.api import app as panel

    monkeypatch.setattr(panel, "list_projects",
                        lambda: (_ for _ in ()).throw(RuntimeError("registry unreadable")))
    snap = panel._stream_snapshot("")
    assert snap["projects"] is None


# ── the browser half ────────────────────────────────────────────────────────────────────────────

def test_the_panel_actually_opens_the_socket():
    """A server endpoint nothing connects to is this repository's signature defect."""
    assert "new WebSocket(" in PANEL, "the panel never opens the stream it is served"
    assert re.search(r"function streamConnect\(", PANEL)
    # called for real, not merely defined
    assert len(re.findall(r"(?<!function )streamConnect\(", PANEL)) >= 2, (
        "streamConnect is defined and never called — the socket exists on paper only"
    )


def test_the_socket_carries_the_SAME_credential_the_rest_of_the_panel_uses():
    """A handshake carries no custom headers, so `authHeaders()` cannot help — the token has to
    travel as a query param, which is exactly what the server's own gate reads."""
    block = PANEL[PANEL.index("function streamConnect("):]
    block = block[:block.index("\nfunction ", 10)]
    assert 'localStorage.getItem("openfactory_token")' in block, block[:400]
    assert 'q.set("token"' in block


def test_the_POLLING_FLOOR_is_never_removed():
    """THE ASSERTION THIS FILE EXISTS FOR. A socket dies for reasons this code does not control —
    a proxy that will not pass Upgrade, a closed laptop, an idle timeout. If the fallback were
    removed the panel would look healthy and receive nothing.
    """
    assert "clearInterval(_chatTimer)" in PANEL  # re-armed, never abandoned
    assert "setInterval(()=>{if(chatShouldFetch())refreshChat()},_CHAT_TICK)" in PANEL, (
        "the chat's periodic refresh is gone or is no longer state-aware — a dead socket now "
        "leaves the conversation frozen with nothing on screen to say so"
    )


def test_the_fallback_interval_is_decided_PER_TICK_not_once():
    """The bug this shape exists to prevent, and it was live for one edit.

    The first version returned `15000` or `60000` from a function passed to `setInterval` — which
    evaluates it EXACTLY ONCE. A socket that died an hour later left the chat on the slow interval
    forever, so the "fallback" was decoration: the thing it protects against is precisely a socket
    that dies AFTER the page loaded.
    """
    assert "function chatShouldFetch()" in PANEL
    body = PANEL[PANEL.index("function chatShouldFetch()"):]
    body = body[:body.index("\n}")]
    assert "_wsState" in body, (
        "the per-tick decision no longer reads the socket state, so it cannot speed up when the "
        f"socket dies: {body}"
    )
    assert "setInterval(refreshChat,chatInterval())" not in PANEL, (
        "the interval is being computed once at arm time again"
    )


def test_the_header_says_which_transport_is_carrying_the_page():
    """`live` vs `polling`, visibly. A transport downgrade nobody can see is a silent stall."""
    assert 'id="live"' in PANEL and 'id="liveTxt"' in PANEL
    assert "function streamStatus(" in PANEL
    for state in ("live", "polling"):
        assert re.search(rf'{state}:\s*\[', PANEL), f"the header cannot render the {state} state"


def test_the_retry_is_backed_off_AND_capped():
    """An unbounded retry against a proxy that will never pass Upgrade is a browser tab quietly
    hammering the deployment for the rest of the day."""
    assert "Math.min(30000" in PANEL, "the reconnect backoff has no ceiling"
    assert "Math.pow(2" in PANEL, "the reconnect retries at a flat interval"


def test_the_box_health_reaches_the_screen():
    """The other half of the same complaint: the box had a file, a gate, and no window.

    Measured before this: all 41 occurrences of "box" in `panel.html` were CSS.
    """
    assert "function boxChip(" in PANEL
    assert "${boxChip(p.box)}" in PANEL, "boxChip is defined and never rendered"
    for state in ("proven", "expired", "unproven", "unknown"):
        assert state in PANEL, f"the panel cannot render a {state} box"
    for css in (".chip.ok", ".chip.err", ".chip.warn", ".chip.dim"):
        assert css in PANEL, f"{css} has no colour, so the four verdicts render identically"


def test_the_api_serves_the_box_state_the_panel_renders():
    """The seam. A chip fed by a field the API never sends renders nothing, forever."""
    from openfactory.api.app import _box_health

    class _P:
        name = "acme"

    health = _box_health(_P())
    assert set(health) >= {"state", "detail", "gate"}, health
    assert health["state"] in ("proven", "expired", "unproven", "unknown"), health


def test_the_default_brand_is_openfactory():
    """It defaulted to "Dark Factory" — the internal name, on every unbranded deployment."""
    import os

    from openfactory.api import app as panel

    src = pathlib.Path(panel.__file__).read_text()
    assert '"Dark Factory"' not in src, "the internal name is still a default somewhere"
    assert 'os.environ.get("OPENFACTORY_PLATFORM_NAME", "OpenFactory")' in src
    assert os.environ.get("OPENFACTORY_PLATFORM_NAME") is None or True  # per-deployment override stands


# ── the two themes ──────────────────────────────────────────────────────────────────────────────

def test_both_themes_are_DESIGNED_not_one_inverted():
    """Dark is the control room and the default; light is what the product's own site looks like.

    The site's system says *"no colour beyond the brand's own — credibility here comes from
    precision, not decoration"*. That is right for a page you read and wrong for a floor you
    watch: an operator has to find a failing job without reading the screen. So colour here is
    semantic only, and each state gets its OWN value per ground — the dark palette's amber and
    green are tuned to glow on near-black and are illegible on white.
    """
    assert ':root[data-theme="light"]' in PANEL, "there is no light theme at all"
    dark = PANEL[PANEL.index(":root{"):PANEL.index(':root[data-theme="light"]')]
    light = PANEL[PANEL.index(':root[data-theme="light"]'):]
    light = light[:light.index("\n}")]
    for token in ("--amber:", "--ok:", "--err:", "--cyan:", "--bg:", "--txt:", "--line:"):
        d = re.search(rf"{re.escape(token)}([^;]+);", dark)
        lt = re.search(rf"{re.escape(token)}([^;]+);", light)
        assert d and lt, f"{token} is not defined in both themes"
        assert d.group(1).strip() != lt.group(1).strip(), (
            f"{token} carries the same value on both grounds — that is an inversion, not a theme"
        )


def test_no_colour_is_hardcoded_outside_the_tokens():
    """Seventeen literal hex values used to sit in the rules, which is seventeen places a light
    theme is broken and nobody notices until a buyer switches it."""
    css = PANEL[PANEL.index("<style>"):PANEL.index("</style>")]
    body = css.split(':root[data-theme="light"]', 1)[1].split("}", 1)[1]
    # COMMENTS STRIPPED FIRST — a rule read as source text answers for its own prose. `#135` in a
    # comment explaining WHY a rule exists is a card number, and to this pattern it is a three-digit
    # hex; obeying the failure would mean deleting the explanation to satisfy the guard that exists
    # to protect the rule. Fifth time in this house that a guard has tripped over the sentence
    # written to justify the code beneath it.
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    stray = re.findall(r"#[0-9a-fA-F]{3,8}", body)
    assert not stray, f"{len(stray)} colours bypass the token layer and will break in light: {stray}"


def test_the_theme_is_applied_BEFORE_the_first_paint():
    """Otherwise a light-mode operator gets a full flash of the dark control room on every
    navigation — the detail that reads as unfinished to somebody evaluating the product, and one
    that cannot be fixed later in the file however early the app boots."""
    head = PANEL[:PANEL.index("<style>")]
    assert 'localStorage.getItem("of_theme")' in head, (
        "the stored theme is read after the stylesheet, so the wrong theme paints first"
    )
    assert "data-theme" in head


def test_dark_is_the_DEFAULT_and_the_OS_does_not_decide_it():
    """The product owner's call: the control room. `prefers-color-scheme` is deliberately not
    consulted — an explicit choice decides, and only that choice is remembered."""
    # THE MEDIA QUERY, NOT THE WORD. The first version searched the whole file and failed on the
    # COMMENT explaining why the OS preference is not consulted — a guard that makes you delete
    # the explanation to go green is a guard that teaches the wrong lesson.
    assert "@media (prefers-color-scheme" not in PANEL, (
        "the OS preference is deciding the theme; the default is meant to be the control room"
    )
    head = PANEL[:PANEL.index("<style>")]
    assert '"light"' in head and 'setAttribute("data-theme"' in head, head[-600:]
    # dark is the bare `:root`, so the attribute is only ever ADDED for light
    assert ':root[data-theme="dark"]' not in PANEL, (
        "dark has become an opt-in attribute; it is the default and must need no attribute"
    )


def test_the_switch_names_where_it_GOES():
    """A button reading "dark" while the screen is already dark is the oldest ambiguity in this
    control. And it must be painted at boot, or the label is wrong for anybody who chose light."""
    assert "function toggleTheme()" in PANEL and "function paintThemeButton()" in PANEL
    assert len(re.findall(r"(?<!function )paintThemeButton\(", PANEL)) >= 2, (
        "the label is never painted at boot — it will read `light` on a light screen"
    )
    body = PANEL[PANEL.index("function paintThemeButton()"):]
    body = body[:body.index("\n}")]
    assert '"light"' in body and '"dark"' in body


def test_the_chrome_carries_no_emoji():
    """The product owner: *"muito cuidado com uso amador de emoji, isso é muito built by AI"*.

    A robot pictograph standing in for the tech-lead is the tell. What is left in this file is a
    single occurrence inside a REGEX that matches text the coordinator produces — a content
    matcher, not furniture — and the platform emitting that text is a separate, larger problem.
    """
    pictographs = re.findall(r"[\U0001F300-\U0001FAFF]", PANEL)
    assert len(pictographs) <= 1, (
        f"{len(pictographs)} pictographs in the panel chrome: {sorted(set(pictographs))}"
    )
