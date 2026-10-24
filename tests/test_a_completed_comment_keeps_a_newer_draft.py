"""A completed comment request owns only its submitted draft and drawer selection.

Run the panel's actual JavaScript handlers with the POST response held until a newer
message is typed or another card is opened, without timing-dependent sleeps.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[1] / "openfactory/api/panel.html"


def _function(name: str) -> str:
    source = PANEL.read_text(encoding="utf-8")
    start = source.index(f"function {name}(")
    if source[max(0, start - 6):start] == "async ":
        start -= 6
    body = source[start:]
    return body[:body.index("\n}\n") + 3]


def _run(body: str, *functions: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH — cannot execute the panel's JavaScript")
    # Routing is outside these guards; provide its browser globals when its fix is merged.
    program = """
globalThis.location = {pathname:"/"};
globalThis.history = {pushState:()=>{}};
globalThis.curBoard = ()=>null;
globalThis.boardCardPath = ()=>location.pathname;
"""
    program += "\n".join(_function(name) for name in functions)
    program += "\n(async()=>{\n" + body + "\n})().catch(e=>{console.error(e);process.exit(1)});"
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize("change, expected, refreshes", [
    ("", "", 1),
    ('_bd.draft = "new unsent draft";', "new unsent draft", 1),
    ('_bd.draft = "  submitted  ";', "  submitted  ", 1),
    ('_bd.card = "2";', "submitted", 0),
    ('_bd.project = "other";', "submitted", 0),
    ('_bd.selection = {};', "submitted", 0),
    ('_bd = {..._bd};', "submitted", 0),
])
def test_a_completed_comment_owns_only_its_submitted_draft(change, expected, refreshes):
    result = _run(f"""
globalThis._bd = {{project:"app",card:"1",selection:{{}},draft:"submitted"}};
let reply, sent, refreshes = 0;
globalThis.act = (name,args)=>{{sent={{name,args}};return new Promise(resolve=>reply=resolve)}};
globalThis.refreshBoard = async()=>refreshes++;
globalThis.toast = ()=>{{}};
const pending = boardComment();
{change}
reply({{ok:true}}); await pending;
console.log(JSON.stringify({{draft:_bd.draft, sent, refreshes}}));
""", "boardComment")
    assert result["draft"] == expected
    assert result["refreshes"] == refreshes
    assert result["sent"] == {
        "name": "card_comment", "args": {"project": "app", "issue": "1", "message": "submitted"},
    }


def test_a_failed_comment_keeps_the_draft_and_reports_the_refusal():
    result = _run("""
globalThis._bd = {project:"app",card:"1",draft:"  submitted  "};
let sent, refusal;
globalThis.act = async(name,args)=>{sent=args;return {ok:false,message:"tracker refused"}};
globalThis.toast = (...args)=>refusal=args;
await boardComment();
console.log(JSON.stringify({draft:_bd.draft,sent,refusal}));
""", "boardComment")
    assert result["draft"] == "  submitted  "
    assert result["sent"]["message"] == "submitted"
    assert result["refusal"] == ["Not posted", "tracker refused", "err"]


def test_an_earlier_comment_cannot_clear_a_draft_after_leaving_and_reopening_its_card():
    result = _run("""
globalThis._bd = {project:"app",card:"1",selection:{},draft:"submitted"};
let reply, refreshes = 0;
globalThis.act = ()=>new Promise(resolve=>reply=resolve);
globalThis.refreshBoard = async()=>refreshes++;
globalThis.toast = ()=>{};
globalThis.$ = ()=>null;
const original = _bd.selection, pending = boardComment();
await boardOpenCard("2");
await boardOpenCard("1");
// The same text typed into a new drawer is still a new draft, owned by that selection.
_bd.draft = "submitted";
reply({ok:true}); await pending;
console.log(JSON.stringify({draft:_bd.draft,refreshes,newSelection:_bd.selection!==original}));
""", "boardComment", "boardOpenCard")
    assert result == {"draft": "submitted", "refreshes": 2, "newSelection": True}
