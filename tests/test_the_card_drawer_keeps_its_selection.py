"""Execute the card drawer handlers with reads resolved deliberately out of order.

A response may paint only its current selection, and the loading interval must never
show controls belonging to the previously selected card.
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


@pytest.mark.parametrize("old_fails", [False, True])
@pytest.mark.parametrize("change", ["card", "project", "pr", "same", "replaced"])
def test_only_the_latest_read_for_the_current_selection_can_paint(change, old_fails):
    change_js = {
        "card": '_bd.card = "2";',
        "project": '_bd.project = "other";',
        "pr": '_bd.card = null; _bd.pr = "7";',
        "same": "",
        "replaced": '_bd = {..._bd, read:0};',
    }[change]
    result = _run(f"""
let _bd = {{project:"app",card:"1",pr:null,timer:1,sig:null}};
const queue = [], painted = [];
function api(url){{ return new Promise((resolve,reject)=>queue.push({{url,resolve,reject}})); }}
function paintBoard(){{ painted.push(_bd.data.marker); }}
function paintCard(){{}}
function paintPR(){{}}
function _bwatch(){{}}
globalThis._bd = _bd;
globalThis.api = api;
globalThis.paintBoard = paintBoard;
globalThis.paintCard = paintCard;
globalThis.paintPR = paintPR;
globalThis._bwatch = _bwatch;
const first = refreshBoard();
{change_js}
globalThis._bd = _bd;
const second = refreshBoard();
queue[1].resolve({{marker:"current"}}); await second;
queue[0].{('reject(new Error("old refusal"))' if old_fails else 'resolve({marker:"stale"})')};
await first;
console.log(JSON.stringify({{painted, marker:_bd.data.marker, why:_bd.why, urls:queue.map(q=>q.url)}}));
""", "refreshBoard")
    assert result["painted"] == ["current"]
    assert result["marker"] == "current"
    assert result["why"] == ""
    assert result["urls"][0] == "/api/board/app?card=1"


@pytest.mark.parametrize("change", ['_bd.card = null;', '_bd.project = "other";',
                                   '_bd.pr = "7";', '_bd = {..._bd};'])
def test_changing_or_closing_the_selection_invalidates_a_read_without_another_request(change):
    result = _run(f"""
globalThis._bd = {{project:"app",card:"1",pr:null,timer:1,sig:null}};
let reply, paints = 0;
globalThis.api = ()=>new Promise(resolve=>reply=resolve);
globalThis.paintBoard = ()=>paints++;
globalThis.paintCard = ()=>paints++;
globalThis.paintPR = ()=>paints++;
globalThis._bwatch = ()=>{{}};
const pending = refreshBoard();
{change}
reply({{marker:"stale"}}); await pending;
console.log(JSON.stringify({{paints, data:_bd.data||null, why:_bd.why||""}}));
""", "refreshBoard")
    assert result == {"paints": 0, "data": None, "why": ""}


def test_polling_that_starts_another_read_does_not_starve_current_responses():
    result = _run("""
globalThis._bd = {project:"app",card:"1",pr:null,timer:1,sig:null};
const replies = [], painted = [];
globalThis.api = ()=>new Promise(resolve=>replies.push(resolve));
globalThis.paintBoard = ()=>painted.push(_bd.data.marker);
globalThis.paintCard = ()=>{};
globalThis.paintPR = ()=>{};
globalThis._bwatch = ()=>{};
const first = refreshBoard(), second = refreshBoard();
replies[0]({marker:"first"}); await first;
const whilePending = painted.slice();
replies[1]({marker:"second"}); await second;
console.log(JSON.stringify({whilePending,painted}));
""", "refreshBoard")
    assert result == {"whilePending": ["first"], "painted": ["first", "second"]}


def test_a_read_from_an_earlier_open_of_the_same_card_is_stale():
    result = _run("""
globalThis._bd = {project:"app",card:"1",pr:null,selection:{},timer:1,sig:null};
let reply, paints = 0;
globalThis.api = ()=>new Promise(resolve=>reply=resolve);
globalThis.paintBoard = ()=>paints++;
globalThis.paintCard = ()=>paints++;
globalThis.paintPR = ()=>paints++;
globalThis._bwatch = ()=>{};
const pending = refreshBoard();
_bd.selection = {};
reply({marker:"earlier opening"}); await pending;
console.log(JSON.stringify({paints}));
""", "refreshBoard")
    assert result["paints"] == 0


def test_selecting_a_card_removes_old_controls_before_the_read_and_cannot_reopen_after_close():
    result = _run("""
globalThis._bd = {project:"app",card:"1",pr:null,draft:"old",form:null};
const drawer = {innerHTML:"old card actions",classList:{add:()=>opened++},setAttribute:()=>{}};
let opened = 0, reply;
globalThis.$ = sel=>sel.endsWith(".drawer") ? drawer : null;
globalThis.esc = String;
globalThis.refreshBoard = ()=>new Promise(resolve=>reply=resolve);
const pending = boardOpenCard("2");
const loading = drawer.innerHTML;
_bd.card = null;
reply(); await pending;
console.log(JSON.stringify({loading, opened, pr:_bd.pr}));
""", "boardOpenCard")
    assert "old card actions" not in result["loading"]
    assert "loading" in result["loading"]
    assert result["opened"] == 0
    assert result["pr"] is None


def test_reopening_the_same_card_does_not_let_an_older_open_complete_the_new_selection():
    result = _run("""
globalThis._bd = {project:"app",card:null,pr:"7",draft:"",form:null};
let opened = 0;
const replies = [], drawer = {innerHTML:"",classList:{add:()=>opened++},setAttribute:()=>{}};
globalThis.$ = sel=>sel.endsWith(".drawer") ? drawer : null;
globalThis.esc = String;
globalThis.refreshBoard = ()=>new Promise(resolve=>replies.push(resolve));
const first = boardOpenCard("1"), second = boardOpenCard("1");
replies[0](); await first;
const before = opened;
replies[1](); await second;
console.log(JSON.stringify({before, opened, pr:_bd.pr}));
""", "boardOpenCard")
    assert result == {"before": 0, "opened": 1, "pr": None}


def test_reopening_an_unchanged_card_replaces_loading_with_its_contents():
    result = _run("""
globalThis._bd = {project:"app",card:null,pr:null,draft:"",form:null,sig:null,timer:1};
const drawer = {innerHTML:"",classList:{add:()=>{},remove:()=>{}},setAttribute:()=>{}};
let paints = 0;
globalThis.$ = sel=>sel.endsWith(".drawer") ? drawer : null;
globalThis.esc = String;
globalThis.api = async()=>({card:{ref:"1",title:"unchanged card"}});
globalThis.paintBoard = ()=>{};
globalThis.paintCard = ()=>{paints++;drawer.innerHTML=_bd.data.card.title};
globalThis.paintPR = ()=>{};
globalThis._bwatch = ()=>{};
await boardOpenCard("1");
const first = drawer.innerHTML;
boardCloseCard();
await boardOpenCard("1");
console.log(JSON.stringify({first,reopened:drawer.innerHTML,paints}));
""", "refreshBoard", "boardOpenCard", "boardCloseCard")
    assert result == {"first": "unchanged card", "reopened": "unchanged card", "paints": 2}


@pytest.mark.parametrize("ref, renders", [("1", True), ("2", False)])
def test_painting_a_card_requires_its_ref_to_match_the_current_target(ref, renders):
    result = _run(f"""
globalThis._bd = {{card:"{ref}",data:{{card:{{ref:"1",readable:false,comments:null}}}}}};
const drawer = {{innerHTML:"loading",classList:{{add:()=>{{}}}},setAttribute:()=>{{}}}};
globalThis.$ = sel=>sel.endsWith(".drawer") ? drawer : null;
globalThis.esc = String;
globalThis._bthread = ()=>"thread";
paintCard();
console.log(JSON.stringify({{html:drawer.innerHTML}}));
""", "paintCard")
    assert ("This card could not be read" in result["html"]) is renders
    if not renders:
        assert result["html"] == "loading"

