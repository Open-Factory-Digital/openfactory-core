"""A stack rebuilt by halves must say so (#135).

2026-08-17, the pilot. A fix landed in the panel; I told him to run `up -d --build worker`. He did,
pressed F5, and read a page served by an image twenty-eight hours older — reporting the older world,
missing the fix he was looking for, with nothing on screen able to say it. He concluded the fix had
not worked. `docker ps` had it in one line (`Up 28 hours` beside `Up 2 minutes`) and neither of us
was looking at `docker ps`.

`build_stamp()` already answered "which code am I". The gap was that EVERY SURFACE PRINTED ITS OWN:
the worker's doctor line described the worker, the panel described the panel, and no reader of
either could see the pair. Both containers mount the same state volume, so the worker writes its
build there at boot and the panel reads it back.

AND THE THIRD ANSWER IS NOT A FAILURE. `agree = None` — a checkout with no halves, or a worker too
old to announce — makes NO claim and shows nothing. A banner that fires on a healthy stack is how
operators learn to scroll past banners, and this is the one banner that must never be scrolled past.
"""

from __future__ import annotations

import inspect
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from openfactory import namespace as ns
from openfactory.api import app as api

PANEL = (Path(inspect.getfile(api)).parent / "panel.html").read_text()
CODE = "\n".join(ln for ln in PANEL.splitlines() if not ln.lstrip().startswith("//"))


# ── 1. the worker leaves its build where the OTHER container can read it ────────────────────────

def test_each_half_announces_under_its_OWN_role_and_the_others_read_it_back(tmp_path, monkeypatch):
    """The round trip, driven — announcing and reading are useless unless they meet on the volume.

    PER ROLE, AND SYMMETRIC. The stale half is whichever one you did not rebuild, so a product that
    stored one role's build (the one that happened to be fresh in the first episode) could only ever
    catch the split in one direction."""
    monkeypatch.setenv("OPENFACTORY_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(ns, "build_stamp", lambda: ("abc123", "2026-08-17T10:00:00Z"))
    assert ns.announce_build("worker") == "abc123"

    monkeypatch.setattr(ns, "build_stamp", lambda: ("def456", "2026-08-16T06:00:00Z"))
    assert ns.announce_build("panel") == "def456"

    assert ns.announced_builds() == {"worker": ("abc123", "2026-08-17T10:00:00Z"),
                                     "panel": ("def456", "2026-08-16T06:00:00Z")}


def test_a_role_this_release_has_never_heard_of_is_still_reported(tmp_path, monkeypatch):
    """The generalisation, asserted rather than believed: nothing enumerates the roles, so a half
    added later is named by a page built before it existed."""
    monkeypatch.setenv("OPENFACTORY_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(ns, "build_stamp", lambda: ("zzz", "t"))
    ns.announce_build("scheduler-that-does-not-exist-yet")

    assert "scheduler-that-does-not-exist-yet" in ns.announced_builds()


def test_nobody_has_announced_is_NOT_an_empty_stamp(tmp_path, monkeypatch):
    """The absence-reads-as-an-answer defect, on the field that decides whether to alarm. A stamp of
    `""` would compare unequal to a real one and fire the banner on every deployment whose other
    half predates this card."""
    monkeypatch.setenv("OPENFACTORY_STATE_DIR", str(tmp_path))
    assert ns.announced_builds() == {}


def test_a_HALF_WRITTEN_announcement_is_not_a_disagreement(tmp_path, monkeypatch):
    """A file caught mid-write, or truncated by a full disk, says nothing about anybody's build —
    and reading it as a differing stamp would alarm a healthy deployment."""
    monkeypatch.setenv("OPENFACTORY_STATE_DIR", str(tmp_path))
    (tmp_path / "build-worker.json").write_text('{"stamp": "abc', encoding="utf-8")
    assert ns.announced_builds() == {}


def test_the_disagreement_EXCLUDES_the_asking_role(tmp_path, monkeypatch):
    """A process comparing itself against its own announcement always agrees — which would make the
    worker's own doctor line the proof that everything is fine."""
    monkeypatch.setenv("OPENFACTORY_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(ns, "build_stamp", lambda: ("mine", "now"))
    ns.announce_build("worker")
    monkeypatch.setattr(ns, "build_stamp", lambda: ("theirs", "then"))
    ns.announce_build("panel")

    monkeypatch.setattr(ns, "build_stamp", lambda: ("mine", "now"))
    assert ns.build_disagreement("worker") == {"panel": ("theirs", "then")}

    # …and from the OTHER side, which is the same split seen by the half that is itself stale. The
    # asking process's own stamp is what it compares against, so the panel asks as "theirs".
    monkeypatch.setattr(ns, "build_stamp", lambda: ("theirs", "then"))
    assert ns.build_disagreement("panel") == {"worker": ("mine", "now")}, (
        "the split is only visible from one side — the stale half is whichever was not rebuilt")


def test_a_STALE_SELF_ANNOUNCEMENT_does_not_make_a_process_report_ITSELF(tmp_path, monkeypatch):
    """The case that makes `r != role` load-bearing, and a mutation survived until it was written.

    Normally a process's own file holds its own stamp, so the stamp comparison alone excludes it.
    But the announcement is BEST-EFFORT: a read-only volume, a full disk, or a container that was
    replaced while the file was being written all leave the role's file holding an OLDER boot's
    build. The worker would then read a stamp that differs from its own, under its own name, and
    tell the operator that the worker disagrees with the worker — sending him to rebuild the half
    that is already fresh."""
    monkeypatch.setenv("OPENFACTORY_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(ns, "build_stamp", lambda: ("last-boot", "yesterday"))
    ns.announce_build("worker")

    # …the worker is now running NEW code, and this boot's announcement did not land.
    monkeypatch.setattr(ns, "build_stamp", lambda: ("this-boot", "today"))
    assert ns.build_disagreement("worker") == {}, (
        "a process reported ITSELF as a half running different code")


def test_a_CHECKOUT_announces_nothing_at_all(tmp_path, monkeypatch):
    """No stamp means no image means one tree — there are no two halves to disagree. Writing here
    would mean creating `/var/lib/openfactory` on somebody's laptop to record that we are nothing in
    particular, or logging a permission warning every boot when that fails."""
    monkeypatch.setenv("OPENFACTORY_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(ns, "build_stamp", lambda: ("", ""))

    assert ns.announce_build("worker") == ""
    assert not list(tmp_path.iterdir()), "a checkout wrote a build file anyway"


def test_a_READ_ONLY_state_dir_does_not_stop_the_worker(tmp_path, monkeypatch, caplog):
    """Best-effort by design: a deployment that cannot record this still serves jobs. But NEVER
    silent — the failure mode it exists to prevent is itself invisible."""
    monkeypatch.setenv("OPENFACTORY_STATE_DIR", str(tmp_path / "wall" / "state"))
    monkeypatch.setattr(ns, "build_stamp", lambda: ("abc123", "t"))
    monkeypatch.setattr(ns.Path, "mkdir",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))

    with caplog.at_level("WARNING"):
        assert ns.announce_build("worker") == ""
    assert any("stale half" in r.message for r in caplog.records), (
        "it could not record the build and said nothing")


def test_a_role_that_ANNOUNCES_NOTHING_is_not_counted_as_agreeing(monkeypatch):
    """An empty stamp on disk is not a build, and `all(...)` over an empty-string stamp would call
    it a disagreement while `others` renders a half with no name for its code."""
    got = _report(("mine", "now"), {"worker": ("", "")}, monkeypatch)
    assert got["agree"] is None and got["others"] == {}


def test_BOTH_halves_announce_so_the_split_is_visible_from_either_side():
    """Reachability, both directions. The panel announcing is what lets the WORKER's doctor line
    name a stale panel — the reading the operator actually had on 2026-08-17."""
    import ast

    from openfactory import cli

    tree = ast.parse(inspect.getsource(cli.serve))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "announce_build"]
    assert calls, "the panel never records the build serving the page; a stale panel is invisible "\
                  "to every other half of the deployment"


def test_the_DOCTOR_names_a_half_that_disagrees():
    """The CLI reader gets the same truth as the panel. `doctor` runs INSIDE the worker, so its
    build line is the worker's opinion of itself — accurate, and about the half he was not looking
    at."""
    import ast

    from openfactory import cli

    tree = ast.parse(inspect.getsource(cli.doctor_cmd))
    assert any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "build_disagreement"
               for n in ast.walk(tree)), (
        "doctor prints its own build and never says the other half differs")


def test_the_worker_ANNOUNCES_AT_BOOT():
    """Reachability. The pair above is decoration if the worker never calls it — this is the
    defect class that has cost this project sixteen rounds: built, tested, reached by nothing."""
    import ast

    from openfactory.runtime.temporal import worker

    tree = ast.parse(inspect.getsource(worker.main))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "announce_build"]
    assert calls, "the worker never records the build it is running; the panel reads a stale file "\
                  "or none at all, for ever"


# ── 2. the report: three answers, and the third makes no claim ──────────────────────────────────

def _report(panel, announced, monkeypatch):
    monkeypatch.setattr(ns, "build_stamp", lambda: panel)
    monkeypatch.setattr(ns, "announced_builds", lambda **kw: dict(announced or {}))
    return api._build_report()


def test_two_different_builds_are_reported_as_DISAGREEING(monkeypatch):
    got = _report(("panelsha", "mon"), {"worker": ("workersha", "tue")}, monkeypatch)
    assert got["agree"] is False
    assert got["stamp"] == "panelsha" and got["built_at"] == "mon"
    assert got["others"]["worker"] == {"stamp": "workersha", "built_at": "tue"}, (
        "the operator is told the builds differ and not WHICH half is the old one")


def test_the_same_build_on_both_halves_AGREES(monkeypatch):
    """The positive twin. A report that always disagreed would fire the banner for ever, and the
    banner is the only thing on this page that says the page cannot be trusted."""
    assert _report(("same", "mon"), {"worker": ("same", "mon")}, monkeypatch)["agree"] is True


def test_a_WORKER_THAT_HAS_NOT_ANNOUNCED_makes_no_claim(monkeypatch):
    """Exactly the state of every deployment the moment it pulls this card, and the state of any
    deployment whose halves do not share a state directory. `False` here would alarm all of them."""
    assert _report(("panelsha", "mon"), {}, monkeypatch)["agree"] is None


def test_a_CHECKOUT_makes_no_claim(monkeypatch):
    assert _report(("", ""), {}, monkeypatch)["agree"] is None
    assert _report(("", ""), {"worker": ("x", "t")}, monkeypatch)["agree"] is None, (
        "an unstamped panel 'disagrees' with any worker it can see — a laptop running one worker "
        "container would be told its own deployment is split")


# ── 3. it reaches the page, on every branch ─────────────────────────────────────────────────────

@pytest.mark.parametrize("break_at", ["config", "connect"])
def test_the_report_rides_the_payload_even_when_the_ENGINE_IS_DOWN(monkeypatch, break_at):
    """A panel that cannot reach the engine is if anything MORE likely to be the stale half — and
    that is the reading where the operator most needs to know which code is answering him."""
    from starlette.testclient import TestClient

    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKENS", raising=False)
    monkeypatch.setattr(api, "_build_report", lambda: {"agree": False, "panel": "p", "worker": "w"})
    if break_at == "config":
        monkeypatch.setattr(api, "_temporal",
                            lambda: (_ for _ in ()).throw(RuntimeError("no runtime extra")))
    else:
        class TV:
            @staticmethod
            async def connect():
                raise OSError("engine unreachable")
        monkeypatch.setattr(api, "_temporal", lambda: (TV(), "addr", "ns"))

    body = TestClient(api.app).get("/api/temporal/jobs").json()
    assert body["connected"] is False
    assert body["build"]["agree"] is False, (
        f"the build report is dropped when the engine is unreachable via {break_at}")


def test_the_payload_carries_it_when_the_engine_IS_up():
    """The branch the operator is normally on, asserted on the source of the happy path — the two
    tests above only ever exercise the failure returns."""
    src = inspect.getsource(api.temporal_jobs)
    happy = src[src.index('"connected": True'):]
    assert '"build": build' in happy[:300], (
        "a healthy engine returns no build report, so the banner can never fire on a working stack "
        "— which is every stack this is meant to catch")


# ── 4. the banner, EXECUTED ─────────────────────────────────────────────────────────────────────

def _paint(build):
    """RUN `paintBuildSplit` on a real payload.

    Reading it as text proves only that the words exist somewhere in the function. This house has
    shipped five guards satisfied by a string in a comment or a second occurrence elsewhere; the
    only way to assert WHICH branch a given state takes is to take it."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH — the source-level guards still run")
    body = CODE[CODE.index("function paintBuildSplit()"):]
    body = body[:body.index("\n}\n") + 3]
    script = (
        "var el={style:{display:'?'},innerHTML:''};"
        "var $=function(){return el};"
        "var esc=function(s){return String(s)};"
        f"var engine={{build:{json.dumps(build)}}};\n"
        + body
        + "\npaintBuildSplit();console.log(JSON.stringify({shown:el.style.display,html:el.innerHTML}));"
    )
    got = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr[:400]
    return json.loads(got.stdout)


def test_a_SPLIT_deployment_is_told_so_and_told_the_fix():
    out = _paint({"agree": False, "stamp": "aaa111", "built_at": "Sun 10:00",
                  "others": {"worker": {"stamp": "bbb222", "built_at": "Mon 09:00"}}})

    assert out["shown"] == "", "the split is proven and the banner stays hidden"
    assert "more than one build" in out["html"]
    assert "worker" in out["html"], "it does not name the half that disagrees"
    assert "aaa111" in out["html"] and "bbb222" in out["html"], (
        "it announces a split and does not say which build each half runs")
    assert "Sun 10:00" in out["html"] and "Mon 09:00" in out["html"], (
        "no build times — the operator cannot tell WHICH half is the old one")
    assert "up -d --build" in out["html"], "it reports the problem and not the remedy"
    assert "with no service name" in out["html"], (
        "the remedy does not warn against the narrowed form — which is the exact command that "
        "CAUSED this: rebuilding one service is what leaves the other behind")


def test_a_role_the_PAGE_HAS_NEVER_HEARD_OF_is_named_anyway():
    """The generalisation, at the surface: nothing in the page enumerates roles, so a half added
    after this page was written is still named to the operator."""
    out = _paint({"agree": False, "stamp": "aaa", "built_at": "Sun",
                  "others": {"scheduler": {"stamp": "ccc", "built_at": "Fri"}}})
    assert "scheduler" in out["html"] and "ccc" in out["html"]


@pytest.mark.parametrize("build", [
    {"agree": True, "stamp": "same", "others": {"worker": {"stamp": "same"}}},
    {"agree": None, "stamp": "aaa", "others": {}},
    {},
], ids=["halves-agree", "cannot-be-established", "an-old-panel-payload"])
def test_ANY_answer_but_a_proven_split_shows_NOTHING(build):
    """The negative twin, and the more important one. This banner declares the screen unreliable;
    firing it on a healthy stack — or on the `null` that every deployment sees the moment it pulls
    this card — teaches operators to scroll past the one warning that must never be scrolled past."""
    out = _paint(build)
    assert out["shown"] == "none", f"the banner fired on {build}"


def test_it_is_painted_on_EVERY_engine_frame_and_on_every_view():
    """Reachability again, and the reason it is in `applyEngine` rather than a view: the split
    outlives a navigation, and it must CLEAR ITSELF once both halves match — the operator reading a
    stale panel is precisely the person who cannot tell whether his reload gave him anything."""
    body = CODE[CODE.index("function applyEngine()"):]
    body = body[:body.index("\n}\n") + 3]
    called = re.findall(r"(\w+)\(", body)
    assert "paintBuildSplit" in called, (
        "the banner is never painted from the engine frame — it would show whatever it was born "
        "with and never update")
    assert called.index("paintBuildSplit") < called.index("paintFloor"), (
        "the floor statement is painted before the warning that the page rendering it may be from "
        "the wrong build")


def test_the_banner_lives_in_the_HEADER_where_every_view_carries_it():
    """Placed in a view it would vanish on the page the operator happens to be reading — and the
    stale page is not a page he chooses."""
    head = PANEL[PANEL.index("<header class=\"top\">"):PANEL.index("</header>")]
    assert 'id="buildsplit"' in head, (
        "the split banner is not in the header, so at least one screen cannot show it")
