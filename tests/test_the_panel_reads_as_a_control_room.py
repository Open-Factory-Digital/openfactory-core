"""The panel answers three questions, in the order somebody actually asks them.

THIS FILE IS THE DEFINITION OF DONE FOR THE PANEL REDESIGN, and it was written failing on
purpose: the brief came first, the guard second, the panel third.
Read that brief before making anything here pass — a guard satisfied by the wrong change is worse
than one that is red.

An operator opening this at nine in the morning asks, in this order:

    1. does anything need me?
    2. is the factory working?
    3. what is it doing, and what did it do?

The panel answers them in roughly the reverse order and scatters each: (1) lives behind a modal,
(2) is spread across six header pills of identical weight, and (3) is the first thing on the page.
**Six pills of equal weight is a status bar with no hierarchy** — when everything is equally loud
nothing is, and a job waiting on a human looks exactly like "the engine is connected", which it
almost always is.

WHY THESE ARE STRUCTURAL ASSERTIONS AND NOT SCREENSHOTS. A layout cannot be tested by a string
match, and pretending otherwise produces guards that pass over an ugly page. What CAN be asserted
is the shape underneath a good one: the inbox is reachable without a click, the floor is one
element rather than six, every size and colour is a token, both themes are complete, and the
contrast is legible on each ground. Those are the things a cheaper model doing the mechanical work
will get wrong silently, and they are the reason this file exists rather than a checklist.

THE LAST ONE — CONTRAST — IS THE ONE NOBODY CHECKS BY EYE. It is computed here from the tokens
themselves, on both grounds, against WCAG's own ratio. A light theme where the muted text is
unreadable passes every other test in this repository.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PANEL = (ROOT / "openfactory/api/panel.html").read_text()
CSS = PANEL[PANEL.index("<style>"):PANEL.index("</style>")]


def _tokens(theme: str) -> dict[str, str]:
    """The resolved `--name: value` map for one ground."""
    if theme == "dark":
        block = CSS[CSS.index(":root{"):CSS.index(':root[data-theme="light"]')]
    else:
        base = _tokens("dark")
        block = CSS[CSS.index(':root[data-theme="light"]'):]
        block = block[:block.index("\n}")]
        return {**base, **dict(re.findall(r"--([a-z0-9-]+)\s*:\s*([^;]+);", block))}
    return dict(re.findall(r"--([a-z0-9-]+)\s*:\s*([^;]+);", block))


def _rgb(value: str) -> tuple[float, float, float] | None:
    """`#rgb` / `#rrggbb` -> 0..1 channels. None for anything else (gradients, rgba, var())."""
    v = value.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", v)
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _contrast(a: str, b: str) -> float | None:
    """WCAG contrast ratio between two hex colours, or None if either is not a flat colour."""
    ca, cb = _rgb(a), _rgb(b)
    if ca is None or cb is None:
        return None

    def lum(c):
        f = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]

    la, lb = sorted((lum(ca), lum(cb)))
    return (lb + 0.05) / (la + 0.05)


# ── question 1: does anything need me? ──────────────────────────────────────────────────────────

def test_what_needs_a_human_is_ON_THE_PAGE_not_behind_a_click():
    """`/api/inbox` already returns exactly this — one row per waiting job, each with executable
    options. It is this platform's own invariant made visible (*a wait is a question, never a
    state*), and it sat behind a modal while the projects grid took the top of the page."""
    assert "/api/inbox" in PANEL, (
        "the panel never reads the inbox — the one feed that answers 'does anything need me' is "
        "not on this page at all"
    )
    index = PANEL[PANEL.index("function renderIndex("):]
    index = index[:index.index("\nfunction ")]
    assert "inbox" in index.lower() or "needsYou" in index, (
        "the landing page does not render the inbox. It is the FIRST question an operator asks "
        "and it is still reachable only by opening a modal"
    )


def test_an_empty_inbox_still_renders_ITS_OWN_COMPONENT():
    """Empty must be one quiet line in the same place, never a blank region.

    A zone that disappears when empty teaches nobody where to look, so the day it is not empty the
    operator has never seen it before. This is the same reasoning as `None` vs `[]` one layer up:
    'nothing needs you' is an ANSWER and it has to be said.
    """
    assert re.search(r"nothing needs you|nada precisa de voc", PANEL, re.I), (
        "there is no empty state for the inbox — when nothing is waiting the zone vanishes"
    )


# ── question 2: is the factory working? ─────────────────────────────────────────────────────────

def test_the_floor_is_ONE_statement_not_six_pills():
    """Six pills of identical weight is a status bar with no hierarchy.

    `engine` / `plant` / `intake` / `ghrate` / `decisions` / `live` all render the same, so the one
    that means a human is blocked looks exactly like the one that means the engine is connected —
    which it almost always is. They compose into one sentence with a precedence order; the detail
    stays reachable, it just stops shouting.
    """
    # THE TAG, NOT THE EXACT STRING. The panel redesign gave <header> a class attribute
    # (class="top", for the new elevated/sticky treatment) — a literal "<header>" stopped
    # matching a real, unrelated, correct change. Same defect class the comment below already
    # warns about: match what the tag IS, not one exact spelling of it.
    header = PANEL[PANEL.index("<header"):PANEL.index("</header>")]
    pills = re.findall(r'class="pill[^"]*"[^>]*id="([a-zA-Z]+)"', header)
    # `live` and `theme` are about THIS PAGE, not about the factory, and stay.
    about_the_floor = [p for p in pills if p not in ("live", "theme")]
    assert len(about_the_floor) <= 2, (
        f"the header still carries {len(about_the_floor)} factory pills of equal weight "
        f"({about_the_floor}) — they belong in one statement with a precedence order"
    )


def test_the_floor_statement_names_the_PROBLEM_when_there_is_one():
    """Healthy is quiet; unhealthy is specific. `floor: degraded` would be the worst of both — as
    loud as a real alarm and as useless as silence."""
    # THE ELEMENT, NOT THE WORD. The first version searched for `floor:` and passed — on the CSS
    # token `--floor:` at line 45. A substring match that finds a colour variable and reports a
    # status element is exactly the shape of probe this repository has been burned by three times.
    # (Same reasoning is why the header lookup below matches "<header", not "<header>" — see the
    # sibling test above.)
    header = PANEL[PANEL.index("<header"):PANEL.index("</header>")]
    assert re.search(r'id="floor(Txt)?"', header), (
        "there is no single floor statement in the header — the six pills are still the answer"
    )
    # THE PANEL NO LONGER COMPOSES THE SENTENCE (#144) — the platform does, over `/api/floor`,
    # so that every channel gets the same words. What must remain true HERE is that the page
    # renders the specific clause it was given instead of substituting a vocabulary of its own:
    # a page that mapped causes to "degraded" would undo the whole thing one layer out.
    # (The claim that the causes are specific now lives with the module that makes them —
    # tests/test_the_floor_is_a_platform_capability.py.)
    assert "function floorState(" not in PANEL, (
        "the page computes the floor again — five vocabularies is how this started")
    assert '"/api/floor"' in PANEL, "the page does not ask the platform at all"
    painter = PANEL[PANEL.index("function paintFloor()"):]
    painter = painter[:painter.index("\n}\n")]
    assert "fs.line" in painter or "fs.clause" in painter, (
        "the header renders something other than the sentence the platform composed")
    # COMMENTS STRIPPED FIRST. Both `//` and `/* */`: the word "degraded" appears twice in this
    # file, in the two comments explaining why a degraded floor is a DIFFERENT SURFACE rather than
    # a recoloured word — the prose justifying the rule, tripping the guard that protects it, for
    # the seventh time in this repository.
    prose = re.sub(r"/\*.*?\*/", "", PANEL, flags=re.S)
    prose = "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in prose.splitlines()).lower()
    for invented in ("degraded", "something is wrong", "problem detected"):
        assert invented not in prose, (
            f"the page substitutes {invented!r} for the specific cause it was told")


# ── the rules the design has to keep ────────────────────────────────────────────────────────────

def test_there_is_a_maximum_WIDTH():
    """Text running the full width of a 34-inch monitor is unreadable, and it is the single
    clearest 'nobody designed this' signal on a page an enterprise is evaluating."""
    assert "--max" in CSS, "no maximum width token — the layout runs edge to edge"
    assert re.search(r"max-width:\s*var\(--max\)", CSS), (
        "the maximum width is declared and never applied"
    )


def test_the_tab_ICON_is_inline_and_actually_parses():
    """A broken favicon is invisible: the browser silently shows its default and the page looks
    fine, so nothing anywhere reports it.

    TWO WAYS IT FAILS SILENTLY, and this asserts against both. A URL pointing anywhere but this
    file is an outbound request from every operator's browser — on a client's private network
    that is a leak and a hang, the same reasoning that keeps the webfont and the header mark
    inline. And a standalone SVG WITHOUT `xmlns` renders as nothing at all: inline in HTML the
    parser supplies the namespace, in a `data:` URI it does not, so the one difference between
    the header's mark and this one is the one a copy-paste would drop.
    """
    import urllib.parse
    import xml.etree.ElementTree as ET

    link = re.search(r'<link[^>]*rel="icon"[^>]*href="([^"]+)"', PANEL)
    assert link, "the panel has no tab icon — the browser draws its own blank page glyph"
    href = link.group(1)
    assert href.startswith("data:image/svg+xml,"), (
        f"the tab icon is fetched rather than inline: {href[:60]}"
    )
    svg = urllib.parse.unquote(href[len("data:image/svg+xml,"):])
    ET.fromstring(svg)  # raises on malformed markup, which would render as nothing
    assert "xmlns" in svg, (
        "the icon SVG carries no xmlns — as a data URI it will not render, and the page will "
        "look exactly as it does when the icon is simply missing"
    )


def test_the_type_scale_is_TOKENS_not_literals():
    """Six sizes, named. Thirty-four literal `px` font sizes is not a scale, it is thirty-four
    decisions nobody made together."""
    for token in ("--t-xs", "--t-sm", "--t-md", "--t-lg", "--t-xl"):
        assert token in CSS, f"{token} is not defined — there is no type scale"
    body = CSS.split(':root[data-theme="light"]', 1)[1].split("}", 1)[1]
    literal = re.findall(r"font(?:-size)?:\s*(?:\d+\s+)?(\d+)px", body)
    assert len(literal) <= 4, (
        f"{len(literal)} literal font sizes bypass the scale: {sorted(set(literal))}"
    )


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_the_text_is_LEGIBLE_on_both_grounds(theme):
    """THE CHECK NOBODY DOES BY EYE, and the one a light theme fails silently.

    WCAG AA is 4.5:1 for body text and 3:1 for large or secondary text. `--muted` is the one that
    goes wrong: it is chosen against near-black, and the same value on white is a grey nobody can
    read — the page still 'works', and every other test in this repository passes.
    """
    t = _tokens(theme)
    bg = t.get("bg", "")
    for name, floor in (("txt", 4.5), ("muted", 3.0), ("dim", 2.0)):
        ratio = _contrast(t.get(name, ""), bg)
        if ratio is None:
            pytest.skip(f"--{name} or --bg is not a flat colour on {theme}")
        assert ratio >= floor, (
            f"--{name} on --bg is {ratio:.2f}:1 in the {theme} theme, below {floor}:1 — "
            f"unreadable, and nothing else in this suite would notice"
        )


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_a_STATE_is_distinguishable_from_the_ground(theme):
    """An operator has to find the failing job across a screen without reading it. A state colour
    that does not separate from its own background is decoration."""
    t = _tokens(theme)
    for state in ("ok", "err", "amber"):
        ratio = _contrast(t.get(state, ""), t.get("bg", ""))
        if ratio is None:
            pytest.skip(f"--{state} is not a flat colour on {theme}")
        assert ratio >= 3.0, (
            f"--{state} is {ratio:.2f}:1 against the {theme} ground — it cannot be seen at a "
            f"glance, which is the only job a state colour has"
        )


def test_the_javascript_still_parses():
    """Half of this file is a string, and Python tests read it as text. A green suite is not proof
    the page renders — this is the cheapest thing that is."""
    import subprocess
    import tempfile

    scripts = re.findall(r"<script[^>]*>(.*?)</script>", PANEL, re.S)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write("\n;\n".join(scripts))
        path = fh.name
    done = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    if done.returncode == 127 or "not found" in (done.stderr or ""):
        pytest.skip("node is not installed here")
    assert done.returncode == 0, f"the panel's JavaScript does not parse:\n{done.stderr[-1200:]}"


def test_every_function_this_page_defines_is_actually_CALLED():
    """A renderer nothing invokes is this repository's signature defect, in the one file where the
    test suite cannot see it: no Python test executes this JavaScript."""
    # A REFERENCE COUNTS, NOT ONLY A CALL. `setInterval(loadEngine, 20000)` and
    # `rows.map(recentRow)` use a function without ever writing `name(` — the first version of this
    # guard demanded the parenthesis and reported five live functions as dead. A guard that cries
    # wolf on correct code is a guard the next person deletes, and it would have sent somebody
    # hunting for a defect that was never there.
    code = re.sub(r"/\*[\s\S]*?\*/", "", PANEL)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    defined = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", code))
    orphans = []
    for name in sorted(defined):
        uses = len(re.findall(rf"\b{re.escape(name)}\b", code)) - len(
            re.findall(rf"function\s+{re.escape(name)}\b", code))
        if uses == 0:
            orphans.append(name)
    assert not orphans, (
        f"defined and referenced nowhere: {orphans} — dead code in the one file no test executes"
    )
