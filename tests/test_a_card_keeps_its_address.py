"""Run the panel's routing functions: the address identifies the open drawer after navigation."""

import re

from tests.test_the_board_keeps_your_place import CODE, _function, _run


def _routes(scenario):
    functions = re.search(r"function curProject\(\).*", CODE).group() + "\n"
    functions += "\n".join(_function(name) for name in (
        "curBoard", "boardCardPath", "openBoard", "closeBoard",
        "boardOpenCard", "boardCloseCard", "render",
    ))
    return _run("""
const location={pathname:'/p/myapp/board'};
const paths=[location.pathname]; let position=0;
const history={pushState(state,title,path){
  paths.splice(++position); paths.push(path); location.pathname=path;
}};
function element(){const classes=new Set();return {
  innerHTML:'',classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),
  contains:c=>classes.has(c)},setAttribute(){}};}
const view=element(),drawer=element(),scrim=element();
function $(selector){return selector==='#boardview'?view:
  selector==='#boardview .drawer'?drawer:selector==='#boardview .scrim'?scrim:element();}
let _bd={project:'myapp',sig:null}, projects=[{name:'myapp'}];
let es=null, focus=null; const window={};
const loadFloor=()=>{},pchatFollowPage=()=>{},renderProject=()=>{},renderIndex=()=>{};
const curProduct=()=>null,curLogs=()=>null,toast=()=>{},esc=s=>s;
const renderProduct=()=>{},renderLogsPage=()=>{},openPreviewNow=()=>{};
let reads=0,watchers=0;
async function refreshBoard(){reads++;_bd.data={card:_bd.card};}
function _bwatch(){watchers++;}
async function boardOpenPR(ref){_bd.pr=ref;}
async function settle(){for(let i=0;i<4;i++)await new Promise(setImmediate);}
async function move(delta){position+=delta;location.pathname=paths[position];render();await settle();}
""" + functions + "\n(async()=>{" + scenario + "\n})().catch(e=>{console.error(e);process.exit(1)});")


def test_direct_card_link_survives_render_and_reload():
    got = _routes("""
location.pathname='/p/myapp/card/1'; paths[0]=location.pathname;
render(); await settle();
const first={path:location.pathname,card:_bd.card,open:drawer.classList.contains('on')};
render(); await settle();
console.log(JSON.stringify({first,path:location.pathname,card:_bd.card,paths}));
""")
    assert got == {"first": {"path": "/p/myapp/card/1", "card": "1", "open": True},
                   "path": "/p/myapp/card/1", "card": "1", "paths": ["/p/myapp/card/1"]}


def test_back_and_forward_restore_the_selected_card_and_closed_board():
    got = _routes("""
await openBoard('myapp'); await boardOpenCard('1'); await boardOpenCard('2');
await move(-1); const back={path:location.pathname,card:_bd.card};
await move(-1); const board={path:location.pathname,card:_bd.card};
await move(1); const forward={path:location.pathname,card:_bd.card};
console.log(JSON.stringify({back,board,forward}));
""")
    assert got == {"back": {"path": "/p/myapp/card/1", "card": "1"},
                   "board": {"path": "/p/myapp/board", "card": None},
                   "forward": {"path": "/p/myapp/card/1", "card": "1"}}


def test_closing_a_drawer_writes_the_board_address_and_back_reopens_it():
    got = _routes("""
await openBoard('myapp'); await boardOpenCard('1'); boardCloseCard();
const closed={path:location.pathname,card:_bd.card};
await move(-1);
console.log(JSON.stringify({closed,path:location.pathname,card:_bd.card}));
""")
    assert got == {"closed": {"path": "/p/myapp/board", "card": None},
                   "path": "/p/myapp/card/1", "card": "1"}


def test_preview_link_is_kept_until_a_different_card_is_selected():
    got = _routes("""
location.pathname='/p/myapp/preview/1';
await openBoard('myapp'); await boardOpenCard('1'); const preview=location.pathname;
await boardOpenCard('2');
console.log(JSON.stringify({preview,path:location.pathname}));
""")
    assert got == {"preview": "/p/myapp/preview/1", "path": "/p/myapp/card/2"}


def test_project_and_card_segments_are_encoded_and_pr_routes_are_preserved():
    got = _routes("""
await openBoard('café team'); await boardOpenCard('PROJ/7');
const card=location.pathname;
location.pathname='/p/caf%C3%A9%20team/pr/8'; await openBoard('café team');
const pr=location.pathname; closeBoard();
console.log(JSON.stringify({card,pr,closed:location.pathname}));
""")
    assert got == {"card": "/p/caf%C3%A9%20team/card/PROJ%2F7",
                   "pr": "/p/caf%C3%A9%20team/pr/8", "closed": "/p/caf%C3%A9%20team"}


def test_navigation_during_a_board_read_cannot_reopen_the_old_card():
    got = _routes("""
const pending=[];refreshBoard=()=>new Promise(resolve=>pending.push(resolve));
location.pathname='/p/myapp/card/1'; render();
location.pathname='/p/myapp/board'; render();
pending[1]();await settle();pending[0]();await settle();
console.log(JSON.stringify({path:location.pathname,card:_bd.card,reads:pending.length}));
""")
    assert got == {"path": "/p/myapp/board", "card": None, "reads": 2}


def test_opening_another_board_discards_the_previous_card_and_edit():
    got = _routes("""
await openBoard('myapp');await boardOpenCard('1');_bd.form={title:'old edit'};
await openBoard('other');
console.log(JSON.stringify({path:location.pathname,project:_bd.project,card:_bd.card,form:_bd.form}));
""")
    assert got == {"path": "/p/other/board", "project": "other", "card": None, "form": None}


def test_returning_to_the_same_address_does_not_let_an_old_read_clear_the_draft():
    got = _routes("""
const pending=[];refreshBoard=()=>new Promise(resolve=>pending.push(resolve));
location.pathname='/p/myapp/card/1'; render();
location.pathname='/p/myapp/board'; render();pending[1]();await settle();
location.pathname='/p/myapp/card/1';render();pending[2]();await settle();
pending[3]();await settle();_bd.draft='new draft';
pending[0]();await settle();
console.log(JSON.stringify({path:location.pathname,card:_bd.card,draft:_bd.draft,reads:pending.length}));
""")
    assert got == {"path": "/p/myapp/card/1", "card": "1", "draft": "new draft", "reads": 4}
