"""The panel must say whether work is being PICKED UP, not only whether the engine answers.

The product owner, 2026-07-31, looking at the panel: *"we should not have to look at anything
local, it is all in the cloud."* That was right, and the panel could not answer the question.

TWO FACTS THAT LOOKED LIKE ONE. `engine live` means the platform can reach Temporal. Whether the
POLLER — the thing that picks a card out of TO-DO and starts a job — is running is a different
fact, and it was on no screen. A paused poller under a reachable engine rendered exactly like a
healthy factory, beneath a line that read, flatly:

    the engine is on standby — a new card in TO-DO goes into production on its own
    (scanned every 3 min)

which is false while intake is paused. Cards sit in TO-DO, the floor stays idle, and the only way
to find out was to run a script from a laptop with the cloud credentials sourced — not an answer a
product can rely on somebody having.

AND IT IS NOT HYPOTHETICAL. Pausing this schedule is the ONLY real way to hold the queue (emptying
TO-DO does not: auto-split refills it), so it is a lever an operator genuinely pulls — the live
schedule still carries the note from the last time it was pulled.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openfactory.runtime.temporal import view as tv

PANEL = Path("openfactory/api/panel.html").read_text()
CODE = "\n".join(ln for ln in PANEL.splitlines() if not ln.lstrip().startswith("//"))


def _verdict(**over):
    """The platform's answer for a stated world (#144).

    These claims used to be read off a five-branch ternary in `panel.html`, then executed under
    node, and are now stated to the module that decides — the same claims, one layer in, where the
    Slack bot and a customer's own dashboard read them too."""
    from openfactory import floor
    from tests.test_the_floor_is_a_platform_capability import world

    return floor.state(world(**over), "acme")


class _State:
    def __init__(self, paused, note=""):
        self.paused, self.note = paused, note


class _Desc:
    def __init__(self, state):
        self.schedule = type("S", (), {"state": state})()


class _Handle:
    def __init__(self, state=None, raises=False):
        self._state, self._raises = state, raises

    async def describe(self):
        if self._raises:
            raise RuntimeError("schedule not found")
        return _Desc(self._state)


class _Client:
    def __init__(self, handle):
        self._handle = handle

    def get_schedule_handle(self, _id):
        return self._handle


@pytest.fixture(autouse=True)
def _no_watchers(monkeypatch):
    """The poller-only tests predate the watcher check (#24 item 6); they keep their exact
    claims by declaring a deployment with no per-project watchers, and the watcher tests below
    override this with their own ids."""
    monkeypatch.setattr(tv, "_watcher_schedule_ids", lambda: [])


@pytest.mark.asyncio
async def test_a_running_poller_reads_as_ON():
    got = await tv.intake(_Client(_Handle(_State(paused=False))))

    assert {k: got[k] for k in ("known", "on", "note", "watchers")} == {
        "known": True, "on": True, "note": "", "watchers": {}}
    # …AND THE CADENCE READS AS NOT-TOLD, because this double exposes `.schedule.state` and
    # nothing else (#140). That is the shape an older Temporal server has too, so it is the case
    # that must never take the switch answer down with it: the switch is known, the cadence is
    # honestly unknown, and the two are separately reportable.
    assert all(got[k] is None for k in ("fired_ago_s", "next_in_s", "every_s", "created_ago_s")), (
        f"a schedule that told us nothing about its cadence answered with numbers anyway: {got}")


@pytest.mark.asyncio
async def test_a_paused_poller_reads_as_OFF_and_carries_its_note():
    """The note is why it was paused, and it is the most useful thing on screen at that moment —
    an operator seeing "paused" without knowing why will either resume blindly or leave it."""
    got = await tv.intake(_Client(_Handle(_State(paused=True, note="segurando para a auditoria"))))

    assert got["on"] is False and got["known"] is True
    assert "auditoria" in got["note"]


@pytest.mark.asyncio
async def test_a_schedule_that_cannot_be_READ_is_never_guessed_as_running():
    """`known=False`, never `on=True`. A header claiming intake is running when nobody could ask
    is the same lie one layer down — and it is the direction that costs something, because it is
    the reassuring one."""
    got = await tv.intake(_Client(_Handle(raises=True)))

    assert got["known"] is False
    assert got["on"] is not True, got


@pytest.mark.asyncio
async def test_reading_the_schedule_never_raises_at_the_panel():
    """The panel degrades, it never 500s — every other reader in this module holds that line."""
    class _Broken:
        def get_schedule_handle(self, _id):
            raise RuntimeError("no client")

    assert (await tv.intake(_Broken()))["known"] is False


# ── the panel actually shows it ────────────────────────────────────────────────────────────────

def test_the_endpoint_the_header_already_reads_carries_it():
    """On the SAME payload, deliberately. A second fetch is a second thing to remember, and the
    header is rendered from `engine` — anything not on it is invisible by construction."""
    src = Path("openfactory/api/app.py").read_text()
    jobs = src.split("async def temporal_jobs")[1].split("@app.get")[0]

    assert '"intake": await tv.intake(client)' in jobs, (
        "the panel cannot know whether work is picked up")


def test_the_idle_screen_does_not_PROMISE_pickup_it_cannot_confirm():
    """The whole defect in one line of copy: an idle floor with intake paused was told, flatly,
    that TO-DO cards start on their own.

    ASSERTED ON THE LADDER (#141), not on the ternary this used to slice. The claim is unchanged
    and now cannot be satisfied by a string sitting in the source: each world is stated and the
    resulting sentence read back."""
    paused = _verdict(intake={"on": False})
    assert paused.cause == "poller_paused", (
        f"a paused intake still reads as an ordinary quiet floor: {paused['line']}")
    assert "no card in TO-DO will be picked up" in paused.clause, (
        "it reports the pause and does not say what it costs")

    unreadable = _verdict(intake={"known": False, "on": None})
    assert unreadable.word == "Unknown", (
        f"an unreadable schedule falls back to the reassuring sentence: {unreadable['line']}")

    # …and the promise survives, but only on the branch that earned it.
    armed = _verdict()
    assert "will be picked up" in armed.clause


def test_the_HEADER_shows_it_too_because_a_running_job_hides_the_idle_screen():
    """A paused intake matters WHILE a job is running: that job finishes and the next card is
    never picked up. The header is the only surface still visible then, and it is never hidden —
    quiet when healthy, specific when not.

    This used to be one of six pills of identical weight, which is its own defect: the one meaning
    a human is blocked read exactly like the one that is almost always true."""
    assert 'id="floor"' in PANEL and 'id="floorTxt"' in PANEL

    fs = _verdict(intake={"on": False},
                  jobs=[{"project": "acme", "issue": "7", "status": "running",
                         "action": None, "wedged": False}])
    assert fs.cause == "poller_paused", (
        f"a running job hid the fact that nothing will be picked up after it: {fs['line']}")

    # The painter DERIVES the banner's treatment from the level rather than deciding styling
    # itself — the visual verdict lives in CSS, checked next.
    paint = PANEL.split("function paintFloor(")[1]
    paint = paint[:paint.index("\n}")]
    assert 'lvl-"+fs.level' in paint, (
        "paintFloor no longer derives the banner class from the floor's own level")
    # A stopped factory washes the WHOLE banner (a different surface, not a recoloured word), and
    # a healthy one sets no such rule at all.
    css = PANEL[PANEL.index("<style>"):PANEL.index("</style>")]
    assert ".statusbar.lvl-err{background:var(--err-wash)}" in css, (
        "the err level no longer washes the floor banner — a stopped factory reads as ordinary")
    assert ".statusbar.lvl-ok{" not in css, (
        "the healthy floor level now has its own banner-background rule — 'quiet' is no longer "
        "genuinely quiet")


def test_the_note_reaches_the_screen_ESCAPED():
    """The one SECURITY guard in this area, and it must survive every rewrite: the schedule note is
    operator-authored free text that lands in `innerHTML`. The ladder puts it in the clause, and
    every painter of a clause escapes — asserted on all of them, because one that forgets is the
    whole hole."""
    for fn in ("paintFloor", "paintAlso"):
        body = CODE[CODE.index(f"function {fn}("):]
        body = body[:body.index("\n}\n") + 3]
        assert "esc(" in body, f"{fn} writes the floor's sentence into innerHTML unescaped"
    card = CODE[CODE.index("const glyph={"):]
    assert "esc(fs.clause)" in card[:600], (
        "the project card interpolates the floor's sentence raw — the schedule note is in it")


# ── the OTHER standing loops are proven alive too (#24 item 6) ──────────────────────────────────
#
# Only the poller was on the payload. The product sweep and the tech-lead's rounds — the loop
# that carries the release bridge — are SILENT when they have nothing to say, so a dead watcher
# and a quiet week rendered identically: they could stop, or never be scheduled, and nothing
# anywhere would say so.

#: The real function, captured at import time — the autouse `_no_watchers` fixture replaces the
#: module attribute, and the one test ABOUT this function must not test the stub.
_REAL_WATCHER_IDS = tv._watcher_schedule_ids


class _PerIdClient:
    def __init__(self, states: dict):
        self._states = states

    def get_schedule_handle(self, sid):
        state = self._states.get(sid)
        return _Handle(state) if state is not None else _Handle(raises=True)


@pytest.mark.asyncio
async def test_a_paused_watcher_is_named_on_the_same_payload(monkeypatch):
    monkeypatch.setattr(tv, "_watcher_schedule_ids",
                        lambda: ["openfactory-techlead-watch-demo", "openfactory-product-sweep-demo"])
    client = _PerIdClient({
        "openfactory-poller": _State(paused=False),
        "openfactory-techlead-watch-demo": _State(paused=True, note="debug"),
        "openfactory-product-sweep-demo": _State(paused=False),
    })

    got = await tv.intake(client)

    assert got["on"] is True, "the poller reading moved"
    assert got["watchers"]["openfactory-techlead-watch-demo"]["on"] is False
    assert got["watchers"]["openfactory-product-sweep-demo"]["on"] is True


@pytest.mark.asyncio
async def test_a_watcher_that_was_never_scheduled_reads_as_unknown_not_healthy(monkeypatch):
    """The worse direction: a schedule that does not EXIST is not a paused one — it is a loop
    nobody ever started, and guessing it healthy is the reassuring lie again."""
    monkeypatch.setattr(tv, "_watcher_schedule_ids", lambda: ["openfactory-techlead-watch-demo"])
    client = _PerIdClient({"openfactory-poller": _State(paused=False)})

    got = await tv.intake(client)

    assert got["watchers"]["openfactory-techlead-watch-demo"]["known"] is False
    assert got["watchers"]["openfactory-techlead-watch-demo"]["on"] is not True


def test_the_watcher_ids_come_from_the_registry(monkeypatch):
    """One id per enabled project's rounds, plus the sweep only where the product module is on —
    a disabled project's dead watcher is not an alarm, it is configuration."""
    class _P:
        def __init__(self, name, enabled=True, product=None):
            self.name, self.enabled, self.product = name, enabled, product

    class _Reg:
        def list(self):
            return [_P("alpha", product=object()), _P("beta"), _P("off", enabled=False)]

    import openfactory.registry as registry_module

    monkeypatch.setattr(registry_module, "ProjectRegistry", lambda: _Reg())

    ids = _REAL_WATCHER_IDS()

    assert ids == ["openfactory-techlead-watch-alpha", "openfactory-product-sweep-alpha",
                   "openfactory-techlead-watch-beta"]


def test_a_dark_watcher_reaches_the_header():
    """Reachability, in the two halves it now has (#144).

    The panel no longer carries the vocabulary — the platform composes the sentence and the page
    renders it — so this asks the platform for the sentence AND checks the page has somewhere to
    put it. A cause with nowhere to render is the same silence one layer out."""
    got = _verdict(intake={"watchers": {"openfactory-techlead-watch-acme":
                                        {"known": True, "on": False, "note": ""}}})
    assert any("round is paused" in row["clause"] for row in got.also), (
        "a standing loop is dark and nothing anywhere says so")
    assert 'id="floorAlso"' in PANEL and "function paintAlso(" in PANEL, (
        "the platform names a demoted cause and the page has nowhere to show it")
