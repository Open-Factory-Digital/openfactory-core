"""`sdlc box prove` reports while it runs. The factory coming up has to be visible.

The product owner, on what a client's first hour has to feel like:

    *"putting myself in the client's shoes, I will want to SEE the box working, because this is an
    OpenFactory… think of something interactive, the opening day of a factory: it switches this
    on, configures that, brings the box up with the harness, runs a test"*

MEASURED BEFORE THIS: `prove` printed nothing until every station had finished. It pulls an image,
runs the client's `setup:` and then their whole `validate:` suite — `box.run(...)` with a 1800s
timeout per command — and both sandbox adapters have accepted an `on_output` callback since C-39,
with `test_the_box_transmits_while_it_runs.py` asserting they honour it. `box_prove` was the one
caller that never passed it. So the single command that IS the factory coming alive was the single
command that showed nothing while it happened, in front of the room deciding whether to buy. A
terminal that has not moved for four minutes is indistinguishable from one that has hung.

WHAT IS ASSERTED HERE is the property, not the wording: every station announces, the long ones
stream their own output, and a broken renderer can never fail a good box.
"""

from __future__ import annotations

import pytest

from openfactory.box_prove import Probes, prove


def _probes(**over) -> Probes:
    """A box that passes every station, so a test about REPORTING is not also a test about
    failure. Streaming is opt-in per case: `run_streaming=None` is the honest shape of every
    probe set that cannot stream, and half of these assert that path stays correct."""
    base = dict(
        resolve_digest=lambda _i: "sha256:" + "a" * 64,
        image_platform=lambda _i: ("linux", "arm64", "glibc"),
        toolbox_stamp=lambda: {"variant": "linux-arm64-glibc", "harnesses": ["claude"]},
        contract=lambda _i: {},
        run_in_box=lambda _c: (0, "done"),
        harness_reachable=lambda: (True, "ok"),
        setup_commands=lambda: ["pip install -e ."],
        validate_commands=lambda: {"test": "pytest -q"},
        harness_name=lambda: "claude",
        env_in_box=lambda names: dict.fromkeys(names, "x"),
    )
    base.update(over)
    return Probes(**base)


def test_every_station_announces_its_result():
    """One line per station, as it lands — not a wall at the end."""
    seen: list[tuple[str, str]] = []
    proof = prove("acme", "img", _probes(), on_stage=lambda k, t: seen.append((k, t)))

    done = [t for k, t in seen if k == "done"]
    assert len(done) == len(proof.findings), (
        f"{len(proof.findings)} stations ran and {len(done)} were announced — a station that "
        f"lands silently is exactly the gap this reporting exists to close"
    )
    for check in ("image", "toolbox", "contract", "setup", "validate"):
        assert any(check in line for line in done), f"{check} never announced: {done}"


def test_a_NEW_station_cannot_be_added_silently():
    """The reason the reporting is on the findings LIST rather than at fourteen call sites.

    Instrumenting each `findings.append` by hand would have worked on the day it was written and
    rotted at the fifteenth station — which would land silent, and silence is the whole defect.
    Here a station is appended the way any new one would be, and it announces without anyone
    having remembered to make it.
    """
    from openfactory.box_prove import Finding

    seen: list[str] = []

    def watcher(kind, text):
        if kind == "done":
            seen.append(text)

    captured: list = []

    def spy(_c):
        return (0, "")

    proof = prove("acme", "img", _probes(run_in_box=spy), on_stage=watcher)
    before = len(seen)
    proof.findings.append(Finding("a_brand_new_station", True, "invented after the fact"))
    captured.append(proof)

    assert len(seen) == before + 1 and "a_brand_new_station" in seen[-1], (
        "a station appended after the fact did not announce — the reporting is attached to the "
        "call sites again, and the next one added will be invisible"
    )


def test_the_long_stations_stream_their_own_output():
    """`setup:` and the client's gates are the minutes-long ones, and they are what must stream."""
    lines: list[str] = []

    def streaming(command, on_line):
        for chunk in (f"[{command}] 1/3", f"[{command}] 2/3", f"[{command}] 3/3"):
            on_line(chunk)
        return (0, "done")

    prove("acme", "img", _probes(run_streaming=streaming),
          on_stage=lambda k, t: lines.append(t) if k == "line" else None)

    assert any("pip install -e ." in x for x in lines), (
        f"the client's `setup:` produced no visible output: {lines}"
    )
    assert any("pytest -q" in x for x in lines), (
        f"the client's own gates produced no visible output: {lines}"
    )


def test_a_probe_set_that_CANNOT_stream_still_proves():
    """`run_streaming=None` is ordinary and correct — every test double is one.

    The fallback is explicit rather than a `TypeError` handler around a wider call, because
    catching the exception a wrong signature raises is how a real defect gets to look like a
    supported configuration.
    """
    ran: list[str] = []
    proof = prove("acme", "img",
                  _probes(run_in_box=lambda c: (ran.append(c), (0, ""))[1], run_streaming=None),
                  on_stage=lambda _k, _t: None)

    assert proof.failures() == [], [f.message for f in proof.failures()]
    assert "pip install -e ." in ran and "pytest -q" in ran, ran


def test_the_default_is_UNCHANGED_and_silent():
    """`on_stage=None` must behave exactly as before — every existing caller passes nothing."""
    quiet = prove("acme", "img", _probes())
    loud = prove("acme", "img", _probes(), on_stage=lambda _k, _t: None)

    assert [f.check for f in quiet.findings] == [f.check for f in loud.findings]
    assert quiet.failures() == [] and loud.failures() == []


def test_a_BROKEN_renderer_never_fails_a_good_box():
    """A screen is not a result. The one thing worse than an invisible proof is a proof that a
    terminal problem turned into a failed box — which would hold pickup on a factory that works.
    """
    def hostile(_kind, _text):
        raise RuntimeError("the terminal went away")

    proof = prove("acme", "img", _probes(), on_stage=hostile)
    assert proof.failures() == [], [f.message for f in proof.failures()]
    assert len(proof.findings) >= 5


@pytest.mark.parametrize("adapter", ["worktree", "container"])
def test_the_sandbox_this_streams_through_really_takes_the_callback(adapter):
    """The reachability half. `prove` can only stream what the box streams, and the box's own
    guard (`test_the_box_transmits_while_it_runs.py`) proves it does — this asserts the SEAM
    between them still exists, which is the part that was missing for months."""
    import inspect

    from openfactory.adapters.sandbox import ContainerSandbox, WorktreeSandbox

    box = {"worktree": WorktreeSandbox, "container": ContainerSandbox}[adapter]
    assert "on_output" in inspect.signature(box.run).parameters, (
        f"{adapter} no longer accepts a line callback, so nothing downstream can stream"
    )


def test_box_probes_WIRES_the_streaming_seam():
    """And the live probe set supplies it — a field nothing populates is the signature defect.

    Read off `box_probes` rather than executed, because executing it needs a docker daemon and a
    client checkout; what must never regress is that the production builder fills the field.
    """
    import ast
    import inspect

    from openfactory import box_prove

    src = inspect.getsource(box_prove.box_probes)
    call = next(n for n in ast.walk(ast.parse(src.lstrip()))
                if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "Probes")
    supplied = {kw.arg for kw in call.keywords}
    assert "run_streaming" in supplied, (
        f"`box_probes` builds a Probes without `run_streaming`, so the live command falls back to "
        f"the silent path and this whole file guards a capability nobody gets. It supplies: "
        f"{sorted(supplied)}"
    )

    # THE LAST MILE, AND IT WAS THE ONE MUTATION THAT SURVIVED. Everything above proves the
    # callback is threaded from the CLI down to `_in_box`; nothing proved `_in_box` hands it to
    # the box. Deleting `on_output=on_line` from that one call left all eight assertions green
    # while restoring the exact silence this file exists to prevent — the signature defect of this
    # repository, one level below where the guard was looking.
    runs = [n for n in ast.walk(ast.parse(src.lstrip()))
            if isinstance(n, ast.Call)
            and getattr(getattr(n.func, "value", None), "id", "") == "box"
            and getattr(n.func, "attr", "") == "run"]
    assert runs, "`box_probes` no longer runs anything in the box"
    for node in runs:
        assert any(kw.arg == "on_output" for kw in node.keywords), (
            "`_in_box` calls `box.run(...)` without `on_output`, so the sandbox streams to nobody "
            "and `sdlc box prove` goes silent again for the whole length of the client's build"
        )
