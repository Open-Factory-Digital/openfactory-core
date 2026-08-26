"""A value written by an agent reached an inline handler and executed (#147).

`esc()` is correct for element TEXT and insufficient inside an attribute, because the HTML parser
DECODES the attribute value before the JavaScript in it is parsed:

    key      = "');alert(document.cookie);//"
    escaped  = onclick="decide('acme','7','&#39;);alert(document.cookie);//')"
    parsed   = decide('acme','7','');alert(document.cookie);//')

Two statements. The second runs. And `DecisionOption.key` is an unvalidated `str` parsed out of an
AGENT's fenced JSON (`contracts/decision.py`), so its content is influenceable by the text of a
ticket on a client's board — which is exactly the input this product exists to take from strangers.

TWENTY-SIX SITES, not the seven the first ratchet knew. Its regex matched one shape,
`onclick="f('${esc(x)}')"`, so three doors stood open beside the one being watched: single-quoted
attributes, events other than `click`, and — the easiest of all to exploit — arguments passed as
NUMBERS, where nothing has to escape a string because there is no string:

    onclick="acceptRequirement(${r.number})"     →  acceptRequirement(1);alert(1);//)

THE FIX IS STRUCTURAL, not another escaper. A `data-*` attribute has no seam: the parser decodes
it into a string and `dataset` hands that string over. It is never source, so there is nothing for
a quote to close.
"""

from __future__ import annotations

import html as htmllib
import inspect
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from openfactory.api import app as api

PANEL = (Path(inspect.getfile(api)).parent / "panel.html").read_text()

#: The shapes an attacker's value actually takes. Each one closes the call and starts a statement.
HOSTILE = ["');alert(1);//", '");alert(1);//', "1);alert(1);//", "');fetch('//evil');//"]

#: EVERY way a value can reach an inline handler — and the ONE definition of it, imported by the
#: ratchet next door. The first version matched `onclick="f('${esc(x)}')"` alone, so three doors
#: stood open beside the one being watched: a single-quoted attribute, an event other than click,
#: and a bare number where nothing has to escape a string because there is no string.
#:
#: One home, because two regexes for one rule is the defect this whole day has been about: they
#: agree until somebody tightens one.
INLINE_HANDLER = re.compile(r"""on\w+\s*=\s*["'](\w+)\s*\([^)]*\$\{""", re.I)


def without_comments(page: str) -> str:
    """The page as the BROWSER will run it. The rule is documented beside the dispatcher that
    replaced these handlers, and the documentation contains an example of the shape it forbids —
    a guard that reads prose about itself fails the day somebody explains it."""
    code = re.sub(r"/\*.*?\*/", "", page, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in code.splitlines())


CODE = without_comments(PANEL)


def _esc(value: str) -> str:
    """The panel's own escaper, so this test cannot be more careful than the page is."""
    table = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}
    return re.sub(r"[&<>\"']", lambda m: table[m.group()], str(value))


# ── 1. the defect, demonstrated rather than described ───────────────────────────────────────────

@pytest.mark.parametrize("hostile", HOSTILE)
def test_escaping_is_NOT_ENOUGH_inside_an_attribute(hostile):
    """The reason `esc()` looked sufficient for two years. It IS sufficient — for text. The parser
    undoes it before the script engine ever sees the value."""
    markup = f"""<button onclick="decide('acme','7','{_esc(hostile)}')">go</button>"""
    assert "&#39;" in markup or "&quot;" in markup or "(" in markup

    seen_by_js = htmllib.unescape(re.search(r'onclick="([^"]*)"', markup).group(1))
    assert seen_by_js.count(";") >= 1
    # The proof: after the parser is done, what reaches the script engine is more than one call.
    assert seen_by_js.startswith("decide("), seen_by_js
    assert "alert(" in seen_by_js or "fetch(" in seen_by_js


@pytest.mark.parametrize("hostile", HOSTILE)
def test_the_SAME_value_in_a_DATA_ATTRIBUTE_stays_one_string(hostile):
    """The fix, demonstrated the same way. `dataset` hands the value back whole — there is no
    parse step in which a quote could end anything, because it is never source."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH — the structural guards below still run")

    markup = f'<button data-act="decide" data-k="{_esc(hostile)}">go</button>'
    script = f"""
      var got=null;
      global.document={{}};
      // A minimal parse of the attribute, exactly as a browser does it: decode entities, hand the
      // result over as a string. No `eval`, because there is nothing to evaluate.
      var raw={json.dumps(markup)};
      var m=raw.match(/data-k="([^"]*)"/);
      got=m[1].replace(/&amp;/g,"&").replace(/&lt;/g,"<").replace(/&gt;/g,">")
              .replace(/&quot;/g,'"').replace(/&#39;/g,"'");
      console.log(JSON.stringify(got));
    """
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:400]
    assert json.loads(out.stdout) == hostile, (
        "the value came back changed — it was interpreted somewhere it should have been carried")


# ── 2. no site anywhere still does it ───────────────────────────────────────────────────────────

def test_NO_inline_handler_takes_an_interpolated_value():
    """Every shape, not the one the first ratchet knew: single quotes, any `on*` event, and an
    argument that is not a string at all."""
    offenders = sorted({m.group(1) for m in INLINE_HANDLER.finditer(CODE)})
    assert not offenders, (
        f"{offenders} still interpolate a value into JavaScript inside an attribute — give the "
        f"element `data-*` values and let the delegated listener read them")


@pytest.mark.parametrize("shape", [
    # the one the first ratchet knew
    'onclick="decide(\'${esc(o.key)}\')"',
    # …with the quotes the other way round
    "onclick='decide(\"${esc(o.key)}\")'",
    # …a different event
    'oninput="paintJobLog(\'${esc(p)}\')"',
    # …and no string at all to escape
    'onclick="acceptRequirement(${r.number})"',
    # …any handler, not just the two that were named
    'onmouseover="peek(\'${esc(x)}\')"',
])
def test_the_PATTERN_ITSELF_catches_every_shape(shape):
    """VERIFY THE VERIFIER, and here it is load-bearing rather than ceremonial.

    The guard above asserts that NOTHING matches — and a guard shaped like that cannot notice a
    weaker matcher, because zero offenders match any regex. A mutation narrowing the pattern back
    to its original one-shape form sailed straight through until this existed.

    So the pattern is fed the shapes it must catch, and this is the only test here that fails if
    somebody quietly tightens it."""
    assert INLINE_HANDLER.search(shape), (
        f"the detector walks past {shape!r} — a door left open beside the one being watched")


@pytest.mark.parametrize("innocent", [
    '<button data-act="decide" data-k="${esc(o.key)}">go</button>',   # the fix itself
    'onclick="closeModal()"',              # no interpolation, so nothing to inject
    'title="${esc(o.consequence)}"',       # an ordinary attribute, not a handler
])
def test_the_PATTERN_leaves_the_FIXED_shape_alone(innocent):
    """Its twin: a detector that fired on the fix, or on every attribute, is one somebody turns
    off within a week."""
    assert not INLINE_HANDLER.search(innocent), f"the detector fires on {innocent!r}"


def test_the_NUMBER_shape_is_covered_too():
    """The easiest variant to exploit and the one a string-focused guard misses entirely: an
    argument with no quotes around it needs nothing escaped to become a second statement."""
    pattern = re.compile(r"""on\w+\s*=\s*["']\w+\s*\(\s*\$\{[^}]*\}\s*\)""")
    assert not pattern.search(CODE), (
        "a handler takes a bare interpolated argument — `f(${n})` becomes `f(1);alert(1);//)`")


def test_the_RATCHET_is_empty_and_that_is_the_point():
    """Seven handlers were grandfathered so the ratchet could stop NEW ones while somebody dealt
    with the old. An empty allowlist is the only state in which the rule is simply true."""
    from tests import test_a_free_deployment_can_read_its_logs as ratchet

    assert ratchet._INLINE_ARG_HANDLERS == set(), (
        f"still grandfathered: {sorted(ratchet._INLINE_ARG_HANDLERS)}")


# ── 3. the buttons still work ───────────────────────────────────────────────────────────────────

def test_EVERY_data_act_verb_has_somewhere_to_go():
    """The half a security fix breaks silently: a converted button whose verb nobody dispatches is
    a dead control on a gate a human is waiting at, and it looks exactly like a working one."""
    used = sorted({m.group(1) for m in re.finditer(r'data-act="(\w+)"', CODE)})
    assert used, "nothing carries `data-act` — the conversion did not happen"

    table = CODE.split("const ACTS={")[1].split("};")[0]
    missing = [v for v in used if f"{v}:" not in table]
    assert not missing, f"{missing} have buttons and no entry in the dispatch table"


def test_EVERY_dispatch_entry_is_actually_USED():
    """Its twin. An entry nobody reaches is dead code in the one file no test executes — and the
    next reader cannot tell it from a verb whose buttons were removed by accident."""
    table = CODE.split("const ACTS={")[1].split("};")[0]
    declared = sorted({m.group(1) for m in re.finditer(r"^\s*(\w+):", table, re.M)})
    used = {m.group(1) for m in re.finditer(r'data-act="(\w+)"', CODE)}
    orphans = [v for v in declared if v not in used]
    assert not orphans, f"{orphans} are dispatched and nothing carries them"


def test_the_listener_is_DELEGATED_rather_than_per_button():
    """These buttons are regenerated inside an `innerHTML` on almost every frame. Attaching to each
    would mean re-attaching after every render, and the one render somebody forgets is a dead
    button — the failure this whole area keeps producing in a new costume."""
    assert 'closest("[data-act]")' in CODE
    assert 'addEventListener("click"' in CODE


def test_an_UNKNOWN_verb_is_named_rather_than_ignored():
    """A typo in one of twenty-six call sites would otherwise look exactly like a button the
    operator failed to press."""
    body = CODE.split('closest("[data-act]")')[1].split("});")[0]
    assert "console.warn" in body, "an unrecognised action fails silently"


# ── 4. an open pull request has not shipped ─────────────────────────────────────────────────────

def test_pr_open_is_NOT_in_the_terminal_good_set():
    """MEASURED ON THE PILOT (#148): the machine card printed `CURRENT STATION: shipped` directly
    beneath a header reading `Needs you`. A pull request that is open and waiting for a human has
    not shipped — it is the most common thing on this floor that NEEDS somebody, and it sat in the
    same set as `merged`."""
    shipped = re.search(r"const SHIPPED=new Set\(\[([^\]]*)\]\)", CODE).group(1)
    assert "merged" in shipped and "done" in shipped
    assert "pr_open" not in shipped, (
        "an open pull request is still counted as shipped — the card contradicts the header above "
        "it, which is the defect #141 removed, surviving in a set literal")


def test_the_BADGE_PAINTER_reads_the_same_set_rather_than_a_copy():
    """It carried its own hand-written `["merged","done","pr_open"]`, so fixing one would have left
    the other painting an open PR green."""
    badge = CODE[CODE.index("function domBadge("):]
    badge = badge[:badge.index("\n}") + 2] if "\n}" in badge else badge[:300]
    assert '"pr_open"' not in badge.split("if(s==")[0], "the badge keeps its own terminal-good list"
    assert "SHIPPED" in badge, "it does not read the one definition"


def test_an_open_PR_is_painted_as_WAITING_and_not_as_done():
    """Green is what this page uses for `done`. A PR waiting on a person is amber."""
    badge = CODE[CODE.index("function domBadge("):]
    badge = badge[:badge.index("\n}") + 2] if "\n}" in badge else badge[:400]
    assert 'if(s=="pr_open")return"b-run"' in badge.replace(" ", "")


# ── 5. a paragraph is not collected in a one-line box ───────────────────────────────────────────
#
# MEASURED ON THE PILOT (#150), and it cost a real agent pass. The operator pasted a ~560-character
# instruction into the Adjust dialog and the platform received twenty-six characters — the tail. It
# then ran a full pass on that tail, did exactly what the tail said, and reported success to
# everyone. `prompt()` is a single-LINE control; what a browser does with a multi-line paste is the
# browser's business, and NOTHING downstream can tell a mutilated instruction from a short one,
# because a short one is perfectly legitimate.

def _fn(name: str) -> str:
    """One function's source, brace-matched, comments already gone."""
    start = CODE.index(f"function {name}(")
    depth, i = 0, CODE.index("{", start)
    for j in range(i, len(CODE)):
        if CODE[j] == "{":
            depth += 1
        elif CODE[j] == "}":
            depth -= 1
            if depth == 0:
                return CODE[start:j + 1]
    raise AssertionError(f"{name} never closes")


def test_the_free_text_an_AGENT_will_read_is_not_collected_by_prompt():
    """The whole defect in one assertion. `prompt()` may keep asking for a login or a one-line
    reason — those are lines by nature. An instruction that becomes an agent's prompt is not."""
    for name in ("mergeGate", "submitAdjust", "openAdjust"):
        assert "prompt(" not in _fn(name), (
            f"{name} collects the adjust instruction with a single-line prompt() — the control "
            f"that silently delivered a fragment on the pilot")


def test_the_adjust_box_is_a_TEXTAREA_and_the_page_shows_what_it_holds():
    """A textarea keeps line breaks, and the count is the operator's own proof that what they
    pasted is what will be sent. Only the browser can supply that number — the server never sees
    what the box held, only what arrived."""
    box = _fn("openAdjust")
    assert '<textarea id="aj_text"' in box, "the instruction still has no real box"
    assert ".value.length" in box, "nothing ever measures what the box holds"

    # AND THE MEASUREMENT HAS TO REACH THE SCREEN. Asserting that both the element and the
    # measurement exist left `textContent=""` passing: the count was taken and thrown away, which
    # is the invisible state this whole card is about.
    shown = re.search(r'\$\("#aj_count"\)\.textContent\s*=\s*([^;]+);', box)
    assert shown, "the count is never written to the element that displays it"
    literal_free = re.sub(r'"[^"]*"', "", shown.group(1))
    assert re.search(r"\bn\b", literal_free), (
        f"the counter shows something that does not depend on the box's length: {shown.group(1)}")


def test_the_panel_does_not_keep_its_own_copy_of_the_LIMIT():
    """The action layer refuses an over-long instruction with a sentence naming the size and the
    ceiling. A second ceiling in this page is the drift this panel spent a week removing — so the
    count is here and the limit is not."""
    from openfactory.actions.catalog import _ADJUST_MAX_CHARS

    assert str(_ADJUST_MAX_CHARS) not in _fn("openAdjust"), (
        f"the page hard-codes {_ADJUST_MAX_CHARS} — one ceiling, in the layer that enforces it")


def test_the_send_path_cannot_be_reached_with_an_empty_instruction():
    """`prompt()` returning null was handled; a textarea that is merely blank must be too, or the
    gate spends a pass on nothing at full price."""
    assert ".trim()" in _fn("submitAdjust"), "a blank box would be sent"
    assert "openAdjust" in _fn("mergeGate"), (
        "the verb no longer opens the box, so the Adjust button would post an empty instruction")
