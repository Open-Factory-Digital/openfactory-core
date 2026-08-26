"""A floor that will take no card must not say it will (#134).

The operator disabled pickup for `podbeam` and then read his own floor:

    ● polling                 (header)
    floor: running
    Floor idle — the engine is on standby — a new card in TO-DO
    goes into production on its own (scanned every 3 min).

Every one of those is wrong for a disabled project, and the last one is a PROMISE. He would have
dragged a card into TO-DO and watched nothing happen, with the screen explaining that it should.

TWO SEPARATE MISTAKES, and they compounded:

  the copy   knew about `intake` — the poller SCHEDULE, which is deployment-wide — and nothing
             about this project's own `enabled` flag, which OVERRIDES it. A healthy schedule and
             a disabled project produce a perfectly reassuring sentence and no work.
  the pill   said "polling", which is this PAGE's socket falling back from SSE. On a floor screen,
             beside "floor: running", it reads as the factory polling the board. It now says
             "reconnecting", which cannot be mistaken for the factory doing anything.

AND `null` IS ITS OWN ANSWER, as everywhere else here: a cockpit read that FAILED leaves the flag
unknown, and an unknown pickup is not an armed one — the screen says it could not check.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from openfactory.api import app as api

PANEL = (Path(inspect.getfile(api)).parent / "panel.html").read_text()
CODE = "\n".join(ln for ln in PANEL.splitlines() if not ln.lstrip().startswith("//"))


def _fn(name: str) -> str:
    start = CODE.index(f"function {name}(")
    rest = CODE[start:]
    return rest[:rest.index("\n}\n")]


def _idle_block() -> str:
    """The floor card's empty-state decision, from the project flag to the rendered glyph.

    ANCHORED ON ITS OWN FIRST LINE, not on an enclosing function and not on `const held=` — the
    first cut did both and both were wrong: the copy does not live where the function scan said,
    and `const held=` occurs THREE times in this page, so `.index` found somebody else's. A slice
    bounded by text unique to this block cannot pick up a neighbour's."""
    start = CODE.index("const pk=window._pickup;")
    return CODE[start:CODE.index("</div>`;", start) + 8]


# ── 1. the server tells the page what it needs to be honest ─────────────────────────────────────

def test_the_cockpit_carries_whether_THIS_project_is_picked_up():
    src = inspect.getsource(api.factory)
    assert '"pickup_enabled": pickup' in src, (
        "the project page has no way to know its own pickup is off")
    assert "getattr(proj, \"enabled\", True)" in src


def test_a_registry_it_could_not_read_answers_NEITHER_true_nor_false():
    """`None` travels, and the page renders it as its own sentence. Defaulting to True would be
    the absence-reads-as-an-answer defect on the one field that decides whether work happens."""
    src = inspect.getsource(api.factory)
    assert "pickup: bool | None = None" in src, (
        "an unreadable registry now reports the project as armed")


def test_it_is_reachable_and_says_so(tmp_path, monkeypatch):
    """Reachability, driven: the field has to survive the route, not merely exist in the source."""
    from starlette.testclient import TestClient

    class Project:
        name = "acme"
        enabled = False
        tracker = type("T", (), {"options": {}})()

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKENS", raising=False)
    monkeypatch.setattr("openfactory.registry.ProjectRegistry.get", lambda self, n: Project())

    body = TestClient(api.app).get("/api/factory/acme").json()
    assert body["pickup_enabled"] is False


def _verdict(**over):
    """The platform's answer for a stated world (#144).

    These claims were read off a five-branch ternary in `panel.html`, then executed under node,
    and are now stated to the module that decides. The words are the same; the place they are
    decided is one layer in, where the Slack bot reads them too."""
    from openfactory import floor
    from tests.test_the_floor_is_a_platform_capability import world

    return floor.state(world(**over), "acme")



# ── 2. the copy stops promising ─────────────────────────────────────────────────────────────────
#
# REWRITTEN ONTO THE LADDER (#141). Every guard below asserted on a five-branch ternary that no
# longer exists: the project card had its own computation, in its own vocabulary, directly under a
# header that had reached its own conclusion — which is how `floor: running` came to sit on top of
# `Floor idle`. There is one computation now, and it is PURE, so these can state a world and read
# back the word instead of scraping HTML for a glyph.
#
# The claims are the same claims. Only the anchors moved.

def test_the_project_flag_is_checked_BEFORE_the_deployment_wide_schedule():
    """It overrides: a disabled project takes no card however healthy the schedule is. Decided
    after the schedule it would be unreachable on exactly the machine with a working poller."""
    fs = _verdict(projects=[{"name": "acme", "enabled": False,
                                        "box": {"state": "proven", "gate": ""}}])
    assert fs.cause == "pickup_off", (
        f"a healthy deployment-wide schedule masked this project's own switch: {fs['line']}")


def test_a_disabled_project_is_told_it_will_NOT_be_taken():
    fs = _verdict(projects=[{"name": "acme", "enabled": False,
                                        "box": {"state": "proven", "gate": ""}}])
    assert "will not be taken" in fs.clause
    assert any(a["key"] == "enable" for a in fs.actions), (
        "it says pickup is off and never says how to turn it on")


def test_an_UNKNOWN_pickup_is_not_reported_as_armed():
    """`null` is its own answer. Defaulting to armed would be the absence-reads-as-compliance
    defect on the one field that decides whether work happens at all."""
    fs = _verdict(projects=[{"name": "acme", "enabled": None,
                                    "box": {"state": "proven", "gate": ""}}])
    assert fs.word == "Unknown", fs.line
    assert "could not read" in fs.clause


def test_the_reassuring_sentence_SURVIVES_for_a_project_that_really_is_armed():
    """The positive twin. A fix that made every floor look held would be worse than the promise it
    replaced — an operator who cannot tell armed from paused stops reading the box."""
    fs = _verdict()
    assert fs.word == "Armed" and "will be picked up" in fs.clause


def test_a_DISABLED_project_renders_the_held_glyph_and_no_promise():
    """The card's glyph now comes from the same `level` as its word, so the two cannot disagree —
    they used to be separate expressions, and a mutation that changed one left the other."""
    fs = _verdict(projects=[{"name": "acme", "enabled": False,
                                        "box": {"state": "proven", "gate": ""}}])
    assert fs.level == "err", "a floor that will take nothing is not painted as stopped"
    assert "will be picked up" not in fs.clause, "it still promises"


def test_a_PAUSED_SCHEDULE_is_still_reported_when_the_project_itself_is_on():
    """The branch that existed before this card must survive it."""
    fs = _verdict(intake={"on": False, "note": "held by hand"})
    assert fs.cause == "poller_paused" and "held by hand" in fs.clause


def test_the_idle_card_REDRAWS_when_the_answer_finally_arrives():
    """#133, and it is the most important guard in this file: the half that shipped broken while
    every other one passed. The card only re-renders when its key changes, and the key was the SET
    OF RUNNING JOBS — which for an idle floor is `""`, for ever. So it kept the sentence it was
    first painted with: the operator enabled his project, the server said `pickup_enabled: true`,
    and the screen went on saying it could not read the pickup.

    The claim is now STRONGER than it was. The key carries the ladder's own verdict, so the card
    redraws when ANY input to that verdict moves — not only the three somebody remembered."""
    keys = re.search(r"const key=active\.length\s*\?(.+?);\n", CODE, re.S)
    assert keys, "the floor card's redraw key is no longer where this guard can read it"
    idle = keys.group(1).split(":", 1)[1]
    for part in ("fs.cause", "fs.clause"):
        assert part in idle, (
            f"the idle card does not redraw when {part} changes — it will keep whatever sentence "
            f"it was first painted with")
    assert "active.map" in keys.group(1).split(":", 1)[0], (
        "a RUNNING floor no longer keys on its job set — re-rendering the machine card on every "
        "frame wipes the live log feed, which is what that key exists to prevent")


def test_the_cockpit_load_stores_the_flag_and_REDRAWS():
    body = _fn("loadCockpit")
    # BOTH assignments, not "one of them somewhere". The first cut asserted the substring once,
    # and a mutation that de-keyed only the ANSWER (leaving the `=null` line keyed) sailed past —
    # the second-occurrence defect, for the fifth time in this repository.
    assert body.replace(" ", "").count("window._pickup[name]=") == 2, (
        "the pickup answer is no longer stored per project on both paths, so the index reads a "
        "value belonging to whichever project was opened last")
    assert body.count("refreshProject()") >= 2, (
        "the floor card is not redrawn after the flag arrives — the truth waits for the next "
        "engine tick, and on a failed read it never comes at all")


def test_a_FAILED_cockpit_read_leaves_it_unknown_rather_than_stale():
    body = _fn("loadCockpit")
    assert "window._pickup[name]=null;" in body.replace(" ", ""), (
        "a stale flag from the previous project survives")
    assert "catch(e){refreshProject();return}" in body, (
        "a cockpit that failed leaves the floor showing whatever it showed before")


# ── 4. the pill that reads as the factory ───────────────────────────────────────────────────────

def test_the_socket_pill_cannot_be_read_as_the_FACTORY_polling():
    """It reports THIS PAGE's stream, not the board scan. Beside "floor: running", "polling" is
    the word an operator uses for the poller — which is how a disabled project read as busy."""
    look = re.search(r"const look=\{[^}]*\}", CODE).group(0)
    assert "reconnecting" in look
    assert '"polling"' not in look and "'polling'" not in look, (
        f"the pill still labels the page's socket with the factory's word: {look}")


def test_the_state_KEY_is_untouched_so_every_caller_still_works():
    """Only the LABEL changed. Renaming the key would silently drop every `streamStatus("polling")`
    into the `[""+state]` fallback and paint an unstyled pill."""
    assert "polling:[" in CODE.replace(" ", ""), "the state key was renamed with the label"
    assert 'streamStatus("polling"' in CODE
