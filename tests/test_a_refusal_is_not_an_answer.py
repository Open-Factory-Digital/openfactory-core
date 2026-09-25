"""A refusal is not an answer, and a session has a way out (#181).

WHAT HAPPENED. `api()` in the panel was `return r.json()` for ANY status. The scope gate's 403 —
`{"detail": "this credential is scoped to product and that is part of the floor."}` — therefore
reached every caller as the payload it had asked for. Observed on a one-machine deployment on
2026-09-18, in a floor tab whose credential had been replaced by a product-only sign-in in another
tab of the same browser: the cockpit drew harness blank, auth blank, `agent ?`, review `unknown`,
token pool `0 ()`; the header kept "Armed — nothing is running" and then turned to "heard nothing";
the server refused that tab dozens of times a minute and the page never said so. And there was no
way out of the session that caused it: `/auth/logout` and `whoami.logout` existed server-side, and
the string `logout` did not occur in the page.

EXECUTED, NOT READ. Every case below runs the page's own functions under node against a `fetch`
that answers what the case says. Reading the source would prove that the word "refusal" appears in
it, and this file's first version of that would have passed against the defect.

The two ends are joined in the last section: the 403 body and the `whoami` payloads fed to the page
there are the ones the real app answers under `TestClient`, so the page and the scope gate cannot
drift apart behind two green halves.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "openfactory/api/panel.html").read_text()


def _without_comments(page: str) -> str:
    """The JavaScript the browser executes, not the prose around it — this page explains every
    defect at length beside its fix, and a guard must not be satisfied by the explanation."""
    page = re.sub(r"/\*.*?\*/", "", page, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", r"\1", line) for line in page.splitlines())


CODE = _without_comments(PAGE)


def _function(name: str) -> str:
    """One complete production function, or "" when this page has none of that name (so a case can
    be driven against a page that predates the fix and fail on what it DOES, not on a lookup)."""
    at = CODE.find(f"function {name}(")
    if at < 0:
        return ""
    start = at - 6 if CODE[max(0, at - 6):at] == "async " else at
    depth = 0
    for pos in range(CODE.index("{", at), len(CODE)):
        if CODE[pos] == "{":
            depth += 1
        elif CODE[pos] == "}":
            depth -= 1
            if depth == 0:
                return CODE[start:pos + 1]
    raise AssertionError(f"could not find the end of panel function {name}")


def _const(name: str) -> str:
    found = re.search(rf"^const {re.escape(name)}=.*$", CODE, re.M)
    return found.group(0) if found else ""


#: What every case stands on: a `fetch` that answers from a table and records what was asked, a
#: clock the case moves, the two storages, a `location` that records a reload instead of doing one,
#: and a DOM of exactly the nodes the case names. `routes[url]` is a list of answers consumed in
#: order, the last one repeating; `{network: true}` is a request that never reached the panel.
PRELUDE = r"""
const calls=[];let routes={};let clock=1700000000000;Date.now=()=>clock;
function fetch(u,o){calls.push(((o&&o.method)||"GET")+" "+u);
  const q=routes[u];if(!q)return Promise.reject(new TypeError("Failed to fetch"));
  const a=q.length>1?q.shift():q[0];
  if(a.network)return Promise.reject(new TypeError("Failed to fetch"));
  return Promise.resolve({status:a.status,ok:a.status>=200&&a.status<300,clone(){return this},
    json:async()=>{if(a.text!==undefined)throw new SyntaxError("Unexpected token <");
                   return JSON.parse(JSON.stringify(a.body))}})}
function storage(){const s={};return{getItem:k=>(k in s?s[k]:null),setItem:(k,v)=>{s[k]=String(v)},
  removeItem:k=>{delete s[k]}}}
const localStorage=storage(),sessionStorage=storage();
const went=[];const location={pathname:"/p/acme",search:"",origin:"http://panel.test",
  host:"panel.test",protocol:"http:",reload:()=>went.push("reload"),assign:u=>went.push("assign "+u)};
const document={cookie:""};function prompt(){return null}
const nodes={};function node(){return{innerHTML:"",textContent:"",title:"",className:"",style:{display:""}}}
function $(s){return nodes[s]||null}
const toasts=[];function toast(a,b,c){toasts.push([a,b,c])}
const painted=[];function paintFloor(){painted.push("floor")}
let me=null,_surface="floor",_whoAsk=null,_whoAskedAt=0;
let _floor=null,_floorAt=0,_floorErr="",_floorRefused="";const _bootAt=0;
let _streamsEnded={};
let engine={connected:true,jobs:[{project:"acme",issue:"7",status:"running"}]},_engineAt=0,_engineErr="";
let projects=[{name:"acme"}];
const settle=async()=>{for(let i=0;i<6;i++)await new Promise(r=>setImmediate(r))};
"""

#: The page's own code every case runs on. `refusal`, `declined` and the session functions do not
#: exist before the fix, and are simply absent then.
CORE = ("esc", "safeUrl", "WHO_AGAIN_MS", "MOVED_KEY", "FS_STALE_MS")
#: `reopenEndedStreams` rides along because an ANSWERED `loadFloor` calls it (#208: a stream the
#: server ended comes back once the floor is answered); with nothing ended it does nothing.
FUNCTIONS = ("authHeaders", "mfetch", "refusal", "api", "declined", "productOnly", "askWhoAgain",
             "takeBootsRoute", "sayWhyThisPage", "sessionWho", "paintSession", "curProject",
             "reopenEndedStreams")


def run(scenario: str, *more: str, stubs: str = "") -> dict:
    """Run `scenario` (the body of an async function that returns what the case asserts on) over
    the page's real functions. `stubs` is declared at the TOP level, beside them — the page's
    functions are globals and only see what is global, so a painter stubbed inside the scenario
    would be invisible to the function under test."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH — the page's JavaScript cannot be executed here")
    script = "\n".join([
        PRELUDE, stubs, *(_const(c) for c in CORE),
        *(_function(f) for f in (*FUNCTIONS, *more)),
        "(async()=>{" + scenario + "})().then(o=>console.log(JSON.stringify(o)))"
        ".catch(e=>{console.error(String(e&&e.stack||e));process.exit(1)})"])
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-1200:]
    return json.loads(done.stdout)


REFUSED = {"status": 403, "body": {
    "detail": "this credential is scoped to product and that is part of the floor."}}
ANA = {"id": "ana", "display": "Ana", "known": True, "scopes": None, "logout": "/auth/logout"}
BIA = {"id": "bia", "display": "Bia", "known": True, "scopes": ["product"],
       "logout": "/auth/logout"}

#: What the case gets back from a call: how it ended, and with what.
OUTCOME = """
const outcome=async p=>{try{return{resolved:await p}}
  catch(e){return{rejected:true,name:e.name,status:e.status,body:e.body,message:e.message}}};
"""


# ── 1. `api()` never hands a refusal over as the payload ────────────────────────────────────────

def test_a_403_REJECTS_and_carries_what_the_server_said():
    """THE DEFECT, in one assertion. The scope gate's body is valid JSON, so `r.json()` resolved
    with it and the caller's `catch` never ran."""
    got = run(OUTCOME + f"routes={{'/api/floor':[{json.dumps(REFUSED)}]}};"
              "return outcome(api('/api/floor'))")
    assert got.get("rejected"), f"a 403 was handed to the caller as its answer: {got}"
    assert got["status"] == 403 and got["body"] == REFUSED["body"]
    assert got["message"] == REFUSED["body"]["detail"], (
        "the rejection does not read as the server's own sentence, so a caller that prints "
        "`e.message` cannot tell the person what to do")


@pytest.mark.parametrize("status", [400, 401, 404, 409, 422, 500, 503])
def test_EVERY_non_2xx_with_a_json_body_rejects(status):
    """Not a special case for the 403, and not for one route: the rule is the status."""
    body = {"detail": "engine unreachable"}
    got = run(OUTCOME + f"routes={{'/api/x':[{json.dumps({'status': status, 'body': body})}]}};"
              "return outcome(api('/api/x'))")
    assert got.get("rejected") and got["status"] == status and got["body"] == body, got


def test_a_2xx_is_STILL_the_answer():
    """The positive twin — an `api()` that rejected everything would pass every case above."""
    got = run(OUTCOME + "routes={'/api/x':[{status:200,body:{word:'Armed'}}]};"
              "return outcome(api('/api/x'))")
    assert got == {"resolved": {"word": "Armed"}}


def test_a_refusal_whose_body_is_not_a_sentence_still_carries_its_status():
    """A 422's `detail` is a LIST, and a proxy's 502 is HTML. Neither may become `e.message` as
    `[object Object]`, and neither may lose the status the caller decides on."""
    got = run(OUTCOME + """
      routes={'/a':[{status:422,body:{detail:[{loc:['body'],msg:'field required'}]}}],
              '/b':[{status:502,text:'<html>bad gateway</html>'}]};
      return {a:await outcome(api('/a')),b:await outcome(api('/b'))}""")
    assert got["a"]["status"] == 422 and "422" in got["a"]["message"], got["a"]
    assert got["a"]["body"]["detail"][0]["msg"] == "field required"
    assert got["b"]["status"] == 502 and got["b"]["body"] is None and "502" in got["b"]["message"]


def test_a_caller_that_reads_the_error_body_ITSELF_still_can():
    """Every POST on the page goes through `mfetch`, checks `r.ok` and shows `d.detail`. That door
    is not the defect and must not change: it still hands back the response, whatever its status."""
    got = run(f"routes={{'/api/act/merge':[{json.dumps(REFUSED)}],'/api/whoami':[{{status:200,"
              f"body:{json.dumps(ANA)}}}]}};"
              "const r=await mfetch('/api/act/merge',{method:'POST'});"
              "return {ok:r.ok,status:r.status,detail:(await r.json()).detail}")
    assert got == {"ok": False, "status": 403, "detail": REFUSED["body"]["detail"]}


# ── 2. the floor header: refused is not "heard nothing", and neither is the last verdict ────────

ARMED = {"word": "Armed", "short": "Armed", "level": "ok", "rung": 9, "cause": "armed",
         "clause": "nothing is running — the next card in TO-DO will be picked up",
         "line": "Armed — nothing is running — the next card in TO-DO will be picked up",
         "detail": "", "cmd": "", "meta": "", "actions": [], "also": [], "also_more": 0,
         "census_line": ""}

#: One permitted read, then the credential changes under the tab and every read is refused.
THE_SESSION_CHANGES = (
    f"routes={{'/api/floor/acme':[{{status:200,body:{json.dumps(ARMED)}}},{json.dumps(REFUSED)}],"
    f"'/api/whoami':[{{status:200,body:{json.dumps({**BIA, 'scopes': ['other']})}}}]}};"
    f"me={json.dumps(ANA)};await loadFloor();const before=floorNow();"
    "await loadFloor();await settle();")


def test_a_refused_floor_is_SAID_and_the_last_verdict_is_not_repeated():
    """What was on screen: "Armed — nothing is running — the next card in TO-DO will be picked
    up", over a tab the server was refusing on every frame."""
    got = run(THE_SESSION_CHANGES + "return {before:before.word,now:floorNow()}",
              "loadFloor", "floorNow", "fsDur")
    assert got["before"] == "Armed", "the case never had a verdict to keep"
    now = got["now"]
    assert now["word"] == "Refused" and now["cause"] == "session_refused", (
        f"the header still reads {now['line']!r} while every floor read is refused")
    assert "Armed" not in json.dumps(now), (
        "a verdict given to the previous credential is repeated under this one")
    assert "Bia" in now["line"] and "may not read the floor" in now["line"], now["line"]
    assert "sign out" in now["line"].lower(), "the remedy this deployment has is not offered"
    assert now["detail"] == REFUSED["body"]["detail"], "the server's own sentence was dropped"


def test_REFUSED_does_not_decay_into_HEARD_NOTHING():
    """After `FS_STALE_MS` the old header said "this page has heard nothing for N". It hears on
    every frame — that this session may not look."""
    got = run(THE_SESSION_CHANGES + "clock+=10*60*1000;return floorNow()",
              "loadFloor", "floorNow", "fsDur")
    assert got["cause"] == "session_refused", f"ten minutes on, the header reads {got['line']!r}"
    assert "heard nothing" not in got["line"]


def test_a_page_that_COULD_NOT_ASK_says_that_and_not_refused():
    """The other cause, with the other remedy: reload, or check the network."""
    got = run("routes={'/api/floor/acme':[{network:true}]};await loadFloor();return floorNow()",
              "loadFloor", "floorNow", "fsDur")
    assert got["cause"] == "page_blind" and "could not reach its own API" in got["line"], got


def test_a_token_deployment_is_not_told_to_sign_out():
    """`logout: null` — there is no session to end, and the sentence must not send the person to
    a control the header does not draw."""
    got = run(f"routes={{'/api/floor/acme':[{json.dumps(REFUSED)}],'/api/whoami':[{{status:200,"
              f"body:{json.dumps({**ANA, 'logout': None, 'scopes': ['other']})}}}]}};"
              "await loadFloor();await settle();return floorNow()",
              "loadFloor", "floorNow", "fsDur")
    assert got["word"] == "Refused" and "sign out" not in got["line"].lower(), got["line"]


def test_the_floor_COMES_BACK_when_it_is_answered_again():
    """A refusal that never cleared would be the same defect wearing the opposite sign."""
    got = run(f"routes={{'/api/floor/acme':[{json.dumps(REFUSED)},{{status:200,"
              f"body:{json.dumps(ARMED)}}}],'/api/whoami':[{{status:200,body:{json.dumps(ANA)}}}]}};"
              "await loadFloor();const a=floorNow().word;await loadFloor();"
              "return {a,b:floorNow().word}", "loadFloor", "floorNow", "fsDur")
    assert got == {"a": "Refused", "b": "Armed"}


# ── 3. the readers that drew a refusal as the factory ──────────────────────────────────────────

#: RE-PINNED 2026-09-24 (#298): an idle floor is one the engine was ASKED about — `jobs_read_at`
#: says when, `jobs_unread` is empty — because a list nobody read no longer offers the scan. The
#: two states here are the ones this file means: a floor read idle, and one read busy.
SCAN = ("idle={jobs:[],jobs_read_at:1,jobs_unread:''},"
        "busy={jobs:[{project:'acme',issue:'7',status:'running'}],jobs_read_at:1,jobs_unread:''};"
        "const ask=(e,parked,refused)=>{engine=e;_floorRefused=refused;return scanOffered(parked)};")


def test_SCAN_is_not_offered_to_a_session_the_server_has_declined():
    """It sat on the project page under "Armed — the next card in TO-DO will be picked up", in a
    tab whose every floor call was a 403. `floorNow()` offering only Reload changes nothing here:
    this button is drawn by the project page, not by the header."""
    got = run(SCAN + f"return ask(idle,false,{json.dumps(REFUSED['body']['detail'])})",
              "scanOffered")
    assert got is False, "a declined session is still offered a scan that can only be refused"


def test_SCAN_is_still_offered_on_an_idle_floor_and_still_not_while_a_job_holds_it():
    """The two rules it already had, and the twin: a decision that always said no would pass the
    case above."""
    got = run(SCAN + "return {idle:ask(idle,false,''),running:ask(busy,false,''),"
              "parked:ask(idle,true,'')}", "scanOffered")
    assert got == {"idle": True, "running": False, "parked": False}, got


def test_the_project_page_ASKS_that_decision():
    """The rule is only a rule if the page that draws the button reads it."""
    body = _function("refreshProject")      # comments already stripped: the code, not its prose
    assert re.search(r"sb\.style\.display\s*=\s*scanOffered\(parked\)", body), (
        "the project page decides the button some other way")


def test_a_refused_ENGINE_read_does_not_become_a_frame_with_no_jobs():
    """`loadEngine` merged `{detail}` into `engine`: `jobs` became `[]`, so a running job left the
    screen and "nothing is running" was true of the page and false of the factory."""
    got = run(f"routes={{'/api/temporal/jobs':[{json.dumps(REFUSED)}],'/api/whoami':[{{status:200,"
              f"body:{json.dumps(ANA)}}}]}};"
              "await loadEngine();return {engine,_engineErr}",
              "applyEngineFrame", "loadEngine", stubs="function applyEngine(){}")
    assert got["engine"]["jobs"] == [{"project": "acme", "issue": "7", "status": "running"}], (
        f"a refusal rewrote the engine state: {got['engine']}")
    assert "detail" not in got["engine"]
    assert got["_engineErr"] == REFUSED["body"]["detail"]


COCKPIT = """
nodes["#cockpit"]=node();function refreshProject(){}function applyPipelineShape(){}
var window={_pickup:{}};
"""


def test_a_refused_COCKPIT_says_so_instead_of_drawing_an_unconfigured_factory():
    """Harness blank, auth blank, `agent ?`, review `unknown`, token pool `0 ()` — read by the
    operator as "nothing is configured", on a deployment running Claude Code on a subscription."""
    got = run(f"routes={{'/api/factory/acme':[{json.dumps(REFUSED)}],'/api/whoami':"
              f"[{{status:200,body:{json.dumps(ANA)}}}]}};"
              "await loadCockpit('acme');return nodes['#cockpit'].innerHTML", "loadCockpit",
              stubs=COCKPIT)
    assert REFUSED["body"]["detail"] in got, f"the cockpit does not say it was refused: {got!r}"
    for drawn in ("token pool", "harness", "agent"):
        assert drawn not in got, f"a gauge ({drawn}) was drawn from a refusal: {got!r}"


def test_a_refused_COCKPIT_still_leaves_pickup_UNKNOWN_and_redraws_the_floor():
    """What `catch(e){refreshProject();return}` was for (#134), and the catch does more now: the
    flag stays `null` — never the previous project's, never `undefined` read off a refusal — and the
    floor card is redrawn from it. Saying why must not have cost either."""
    got = run(f"routes={{'/api/factory/acme':[{json.dumps(REFUSED)}],'/api/whoami':"
              f"[{{status:200,body:{json.dumps(ANA)}}}]}};window._pickup.acme=true;"
              "await loadCockpit('acme');"
              "return {pickup:window._pickup.acme,redrawn,shaped}", "loadCockpit",
              stubs="nodes['#cockpit']=node();let redrawn=0,shaped=0;"
                    "function refreshProject(){redrawn++}function applyPipelineShape(){shaped++}"
                    "var window={_pickup:{}};")
    assert got == {"pickup": None, "redrawn": 1, "shaped": 0}, got


def test_a_field_the_answer_did_not_carry_reads_UNKNOWN_and_never_blank():
    """The second line of defence, for a 2xx that is thinner than the page expects (an older
    panel behind a newer page): a hole in the payload is not "nothing configured"."""
    got = run("routes={'/api/factory/acme':[{status:200,body:{project:'acme'}}]};"
              "await loadCockpit('acme');return nodes['#cockpit'].innerHTML",
              "loadCockpit", stubs=COCKPIT)
    gauges = dict(re.findall(r'<span class="lbl">([^<]+)</span><b>(.*?)</b></div>', got))
    assert set(gauges) >= {"harness", "auth", "models", "review", "token pool"}, gauges
    for name, value in gauges.items():
        assert "unknown" in value, f"the {name} gauge reads {value!r} for a field nobody sent"
    assert "undefined" not in got and "0 (" not in got and "agent" not in gauges["models"]


def test_a_configured_factory_is_still_drawn_as_one():
    """The positive twin: the real values, on the real payload's shape."""
    full = {"project": "acme", "harness": "Claude Code", "auth_format": "anthropic",
            "auth_credential": "subscription", "tokens": {"count": 1, "source": "env"},
            "models": {"executor": "opus"}, "review_mode": "independent", "single_agent": True,
            "links": {}}
    got = run(f"routes={{'/api/factory/acme':[{{status:200,body:{json.dumps(full)}}}]}};"
              "await loadCockpit('acme');return nodes['#cockpit'].innerHTML",
              "loadCockpit", stubs=COCKPIT)
    for said in ("Claude Code", "anthropic", "subscription", "opus", "independent", "(env)"):
        assert said in got, f"{said!r} is missing from a healthy cockpit"
    assert "unknown" not in got


def test_a_refused_BOARD_is_not_an_empty_board():
    """`{detail}` has neither `columns` nor `cards`; `undefined` is not `null`, so it passed the
    "could not be read" test and was painted as a board with no columns."""
    got = run(f"routes={{'/api/board/acme':[{json.dumps(REFUSED)}],'/api/whoami':[{{status:200,"
              f"body:{json.dumps(ANA)}}}]}};"
              "await refreshBoard();return {data:_bd.data,why:_bd.why,drew}", "refreshBoard",
              stubs="let _bd={project:'acme',sig:null,timer:1,data:{columns:['x']}};let drew=0;"
                    "function paintBoard(){drew++}function paintCard(){}function paintPR(){}"
                    "function _bwatch(){}")
    assert got["data"] is None, f"the refusal was kept as the board: {got['data']}"
    assert got["why"] == REFUSED["body"]["detail"] and got["drew"] == 1


def test_the_board_SAYS_why_it_has_nothing_to_show():
    got = run("nodes['#boardview']=node();paintBoard();return nodes['#boardview'].innerHTML",
              "paintBoard", stubs="let _bd={project:'acme',data:null,why:"
              + json.dumps(REFUSED["body"]["detail"]) + "};")
    assert "The board could not be read" in got and REFUSED["body"]["detail"] in got, got


def test_a_refused_COST_read_is_not_handed_to_the_dashboard():
    """`{detail}` is truthy, so it went to `_renderDashShell` as the telemetry."""
    got = run(f"routes={{'/api/metrics':[{json.dumps(REFUSED)}],'/api/whoami':[{{status:200,"
              f"body:{json.dumps(ANA)}}}]}};nodes['#dash']=node();"
              "await openCosts();return {shells,html:nodes['#dash'].innerHTML}", "openCosts",
              stubs="let shells=0,_DASH=null;function _ensureChart(){}"
                    "function _renderDashShell(){shells++}function _dashApply(){}")
    assert got["shells"] == 0, "a refusal was rendered as cost telemetry"
    assert REFUSED["body"]["detail"] in got["html"], got["html"]


def test_a_refused_LOG_read_is_not_a_run_that_wrote_no_journal():
    got = run(f"routes={{'/api/jobs/acme/7/events':[{json.dumps(REFUSED)}],'/api/whoami':"
              f"[{{status:200,body:{json.dumps(ANA)}}}]}};nodes['#logdetail']=node();"
              "await loadJobLog('acme','7');return nodes['#logdetail'].innerHTML",
              "loadJobLog", "paintJobLog",
              stubs="let _logs={rows:[],error:'',loaded:'',events:null,all:false};"
                    "const _LOG_CAP=400;function evLine(){return ''}")
    assert "wrote no journal" not in got, "a refused read is reported as a fact about the run"
    assert REFUSED["body"]["detail"] in got, got


def test_a_refused_JOB_DETAIL_says_it_could_not_load():
    """It used to pass the `d.error` test (there was none) and draw the modal from `undefined`."""
    got = run(f"routes={{'/api/jobs/acme/7/detail':[{json.dumps(REFUSED)}],"
              f"'/api/jobs/acme/7/events':[{json.dumps(REFUSED)}],"
              f"'/api/whoami':[{{status:200,body:{json.dumps(ANA)}}}]}};"
              "try{await openJobDetail('acme','7')}catch(e){modals.push('THREW '+e)}"
              "return modals[modals.length-1]", "openJobDetail",
              stubs="const modals=[];function modal(h){modals.push(h)}")
    assert "couldn't load" in got and REFUSED["body"]["detail"] in got, got[:300]


def test_a_refused_project_list_does_not_REPLACE_the_projects():
    """`projects=await api(...).catch(()=>projects)` — the catch never ran, so after enabling a
    project under a refused session the index was rendered from `{detail}`."""
    got = run(f"routes={{'/api/projects/acme/enabled':[{{status:200,body:{{}}}}],"
              f"'/api/projects':[{json.dumps(REFUSED)}],"
              f"'/api/whoami':[{{status:200,body:{json.dumps(ANA)}}}]}};"
              "await toggleProject('acme',true);return projects",
              "toggleProject", stubs="function render(){}")
    assert got == [{"name": "acme"}], f"the project list became {got}"


def test_a_refused_ADDRESS_read_is_not_the_doors_verdict():
    """The one reader that parsed `mfetch`'s body without looking at the status. `{detail}` has no
    `refusal` and no `kind`, so the form said "undefined — on a host, so the coordinates below…"
    and kept it as what the door had read."""
    url = "/api/address?repo_path=%2Fsrc%2Facme&repo="
    got = run(f"routes={{{json.dumps(url)}:[{json.dumps(REFUSED)}],'/api/whoami':[{{status:200,"
              f"body:{json.dumps(ANA)}}}]}};"
              "for(const id of ['#np_reading','#np_go','#np_coords','#np_path'])nodes[id]=node();"
              "nodes['#np_path'].value='/src/acme';await readAddress();"
              "return {read:_npRead,said:nodes['#np_reading'].innerHTML,"
              "locked:!!nodes['#np_go'].disabled}", "readAddress",
              stubs="let _npRead=null,_npHosted=false;const np_repo={value:''};")
    assert got["read"] is None, f"a refusal was kept as the door's reading: {got['read']}"
    assert "on a host" not in got["said"] and REFUSED["body"]["detail"] in got["said"], got
    assert got["locked"] is False, "Register was locked by a read nobody answered"


def test_a_refused_narration_feed_is_not_ITERATED():
    """`for(const m of {detail})` throws a TypeError out of a timer, six times a minute."""
    got = run(f"routes={{'/api/coordinator/messages':[{json.dumps(REFUSED)}],'/api/whoami':"
              f"[{{status:200,body:{json.dumps(ANA)}}}]}};"
              "let threw='';try{await pollCoordinator()}catch(e){threw=String(e)}"
              "return {threw,toasts}", "pollCoordinator", stubs="var window={};")
    assert got == {"threw": "", "toasts": []}, got


# ── 4. a 403 asks who this browser is holding NOW ───────────────────────────────────────────────

def test_a_burst_of_refusals_asks_WHO_once():
    """Six pollers are refused together. The answer to "who am I now" does not change between the
    first and the sixth, and `/api/whoami` is not a thing to hammer."""
    got = run(f"routes={{'/api/x':[{json.dumps(REFUSED)}],'/api/whoami':[{{status:200,"
              f"body:{json.dumps({**BIA, 'scopes': ['other']})}}}]}};me={json.dumps(ANA)};"
              "nodes['#who']=node();"
              "await Promise.all([1,2,3,4,5,6].map(()=>api('/api/x').catch(()=>0)));await settle();"
              "await api('/api/x').catch(()=>0);await settle();"
              "return {asked:calls.filter(c=>c.endsWith('/api/whoami')).length,me,"
              "who:nodes['#who'].innerHTML,painted}")
    assert got["asked"] == 1, f"/api/whoami was asked {got['asked']} times for one burst"
    assert got["me"]["id"] == "bia", "the page still believes it is the previous person"
    assert "Bia" in got["who"], "the header still names the previous person"
    assert "floor" in got["painted"], "the header was not repainted with who is signed in"


def test_it_asks_AGAIN_once_the_moment_has_passed():
    got = run(f"routes={{'/api/x':[{json.dumps(REFUSED)}],'/api/whoami':[{{status:200,"
              f"body:{json.dumps({**BIA, 'scopes': ['other']})}}}]}};"
              "await api('/api/x').catch(()=>0);await settle();clock+=WHO_AGAIN_MS+1;"
              "await api('/api/x').catch(()=>0);await settle();"
              "return calls.filter(c=>c.endsWith('/api/whoami')).length")
    assert got == 2


def test_a_credential_that_became_PRODUCT_ONLY_takes_the_route_boot_takes():
    """`boot()` would never have drawn the floor for it. A reload — not a call to `bootProduct()` —
    because the floor boot left timers, streams and a reconnecting socket behind, all refused."""
    got = run(f"routes={{'/api/x':[{json.dumps(REFUSED)}],'/api/whoami':[{{status:200,"
              f"body:{json.dumps(BIA)}}}]}};me={json.dumps(ANA)};"
              "await api('/api/x').catch(()=>0);await settle();"
              "const first=[...went];clock+=WHO_AGAIN_MS+1;"
              "await api('/api/x').catch(()=>0);await settle();"
              "return {first,after:went,say:sessionStorage.getItem(MOVED_KEY+'.say')}")
    assert got["first"] == ["reload"], f"the tab stayed on a floor it may not read: {got}"
    assert got["after"] == ["reload"], (
        "it reloaded AGAIN seconds later — a deployment whose first whoami fails would loop")
    assert got["say"] == "1", "the page it lands on has nothing to tell it why it is there"


def test_the_PRODUCT_page_is_not_sent_anywhere_by_a_refused_row():
    """On the product page a 403 is a row this person may not run. It is said where they pressed
    it; the page is already the one meant for them."""
    got = run(f"routes={{'/api/act/merge':[{json.dumps(REFUSED)}],'/api/whoami':[{{status:200,"
              f"body:{json.dumps(BIA)}}}]}};me={json.dumps(BIA)};_surface='product';"
              "await mfetch('/api/act/merge',{method:'POST'});await settle();return went")
    assert got == []


ARRIVAL = ("sayWhyThisPage", "movedNotice", "dismissMoved")


def test_the_page_it_lands_on_SAYS_why_and_KEEPS_saying_it():
    """The reload happens on a timer, in a tab nobody is looking at — the person is in the OTHER
    tab, signing in. A toast is gone in 4.5 s; they come back to a different page with no reason
    on it. So it is part of the page, and survives the page being drawn again."""
    got = run(f"me={json.dumps(BIA)};sessionStorage.setItem(MOVED_KEY+'.say','1');"
              "sayWhyThisPage();const first=movedNotice();const again=movedNotice();"
              "return {first,again,toasts}", *ARRIVAL, stubs="let _movedNote=false;")
    assert got["toasts"] == [], "said in a toast, which is gone before anybody reads it"
    assert "Bia (product)" in got["first"] and "may not read the floor" in got["first"], got
    assert 'href="/auth/logout"' in got["first"], "the remedy is named and not offered"
    assert got["again"] == got["first"], "a second paint of the page lost the reason"


def test_it_is_said_for_ONE_arrival_and_can_be_put_away():
    """A reason that followed every later reload would be noise by the second day; one that could
    not be dismissed would sit on the page of somebody who did mean to be there."""
    got = run(f"me={json.dumps(BIA)};sessionStorage.setItem(MOVED_KEY+'.say','1');"
              "sayWhyThisPage();const kept=sessionStorage.getItem(MOVED_KEY+'.say');"
              "dismissMoved();const after=movedNotice();"
              "_movedNote=false;sayWhyThisPage();"
              "return {kept,after,next:movedNotice()}", *ARRIVAL, stubs="let _movedNote=false;")
    assert got == {"kept": None, "after": "", "next": ""}, got


def test_the_product_page_DRAWS_it():
    """The notice exists only if the page that is drawn carries it."""
    got = run(f"me={json.dumps(BIA)};nodes['#app']=node();_movedNote=true;renderProduct('acme');"
              "const drawn=nodes['#app'].innerHTML;_movedNote=false;renderProduct('acme');"
              "return {drawn:drawn.includes('id=\"movedNote\"'),"
              "after:nodes['#app'].innerHTML.includes('id=\"movedNote\"')}",
              *ARRIVAL, "renderProduct",
              stubs="let _movedNote=false;function paintProductHead(){}"
                    "function paintRequirements(){}function paintThread(){}"
                    # the product chat it attaches (#266 slice 5) is not this case's subject
                    "function pchatUse(){}")
    assert got == {"drawn": True, "after": False}, got


def test_an_ordinary_product_page_has_no_such_notice():
    got = run(f"me={json.dumps(BIA)};sayWhyThisPage();return movedNotice()", *ARRIVAL,
              stubs="let _movedNote=false;")
    assert got == ""


def test_a_token_deployment_is_told_why_without_a_door():
    got = run(f"me={json.dumps({**BIA, 'logout': None})};"
              "sessionStorage.setItem(MOVED_KEY+'.say','1');sayWhyThisPage();return movedNotice()",
              *ARRIVAL, stubs="let _movedNote=false;")
    assert "may not read the floor" in got and "Sign out" not in got, got


# ── 5. the way out ─────────────────────────────────────────────────────────────────────────────

def test_a_session_gets_a_SIGN_OUT_that_goes_where_the_server_said():
    got = run(f"nodes['#who']=node();me={json.dumps(BIA)};paintSession();return nodes['#who']")
    assert got["style"]["display"] == "", "the control is still hidden"
    assert 'href="/auth/logout"' in got["innerHTML"] and "Sign out" in got["innerHTML"]
    assert "Bia (product)" in got["innerHTML"], "who is signed in, and how narrowly, is not said"


def test_an_UNSCOPED_person_is_named_without_a_scope():
    got = run(f"nodes['#who']=node();me={json.dumps(ANA)};paintSession();"
              "return nodes['#who'].innerHTML")
    assert ">Ana<" in got and "(" not in got, got


@pytest.mark.parametrize("who", [None, {**ANA, "logout": None}, {"detail": "unauthorized"}])
def test_NO_DOOR_where_there_is_nothing_to_leave(who):
    """`logout: null` is a token deployment — the server's own comment: "a page must not draw a
    door". And a control drawn earlier is taken away again when the answer changes."""
    got = run(f"nodes['#who']=node();me={json.dumps(BIA)};paintSession();"
              f"me={json.dumps(who)};paintSession();return nodes['#who']")
    assert got["style"]["display"] == "none" and got["innerHTML"] == "", got


def test_what_the_server_said_stays_DATA_in_the_header():
    got = run("nodes['#who']=node();me={id:'x',display:'<img src=x onerror=alert(1)>',"
              "scopes:['<b>'],logout:'javascript:alert(1)'};paintSession();"
              "return nodes['#who'].innerHTML")
    assert "<img" not in got and "<b>" not in got, got
    assert "javascript:" not in got and 'href="#"' in got, got


BOOT = """
nodes['#who']=node();const order=[];
function cookieToken(){return ''}function setToken(){}function ensureVisitor(){}
function paintThemeButton(){}function render(){}function engineStream(){}function streamConnect(){}
async function loadEngine(){}async function loadFloor(){}function pollBudget(){}
function pollCoordinator(){}function loadInbox(){}function tickTimers(){}
function setInterval(){}function bootProduct(){order.push('product:'+nodes['#who'].innerHTML)}
function pchatBoot(){}function curProduct(){return location.pathname.startsWith('/product/')?'acme':null}
"""


@pytest.mark.parametrize("who, page", [(ANA, "floor"), (BIA, "product")])
def test_BOTH_pages_boot_with_the_way_out_already_drawn(who, page):
    """"On every surface that has a session": the product page is where a person who redeemed the
    wrong invitation lands, and it is the one that had no exit at all."""
    got = run(f"routes={{'/api/whoami':[{{status:200,body:{json.dumps(who)}}}],"
              "'/api/projects':[{status:200,body:[]}]};await boot();"
              "return {order,who:nodes['#who'].innerHTML,_surface}", "boot", "loadProjects",
              stubs=BOOT)   # `loadProjects` is the boot's own project read since #298
    assert "Sign out" in got["who"] and who["display"] in got["who"], got
    if page == "product":
        assert got["order"] and "Sign out" in got["order"][0], (
            "the product page was drawn before the way out of it")
    else:
        assert got["_surface"] == "floor" and got["order"] == []


# ── 6. the two ends are one contract ───────────────────────────────────────────────────────────

@pytest.fixture
def two_people(monkeypatch, tmp_path):
    """An operator and a product-only person on one deployment — the two credentials one browser
    held in the report."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENFACTORY_IDENTITY", "local")
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_PRODUCT_TOKEN", raising=False)
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "op-secret:ana:Ana")
    monkeypatch.setenv("OPENFACTORY_PRODUCT_TOKENS", "ba-secret:bia:Bia")
    from openfactory.api.app import app
    return TestClient(app)


FLOOR_READS = ["/api/floor", "/api/floor/acme", "/api/factory/acme", "/api/temporal/jobs",
               "/api/budget", "/api/inbox", "/api/coordinator/messages"]


@pytest.mark.parametrize("path", FLOOR_READS)
def test_the_scope_gate_refuses_in_the_shape_the_page_reads(two_people, path):
    """Every read the report lists. 403, JSON, and a `detail` that is a SENTENCE — it is what the
    header and the cockpit now print."""
    r = two_people.get(path, headers={"authorization": "Bearer ba-secret"})
    assert r.status_code == 403, f"{path} answered {r.status_code} to a product credential"
    said = r.json()["detail"]
    assert isinstance(said, str) and "scoped to product" in said and "floor" in said


def test_a_SCAN_is_a_floor_call_like_the_rest(two_people):
    """Why the button is withdrawn rather than left to fail: the gate refuses it before the route
    runs, so for this session pressing it has exactly one outcome."""
    r = two_people.post("/api/projects/acme/scan", headers={"authorization": "Bearer ba-secret"})
    assert r.status_code == 403 and "floor" in r.json()["detail"]


def test_WHOAMI_is_the_one_read_a_refused_credential_may_still_make(two_people):
    """The re-ask depends on it: a `whoami` behind the same gate would leave the page unable to
    learn why it was refused."""
    r = two_people.get("/api/whoami", headers={"authorization": "Bearer ba-secret"})
    assert r.status_code == 200
    assert r.json()["scopes"] == ["product"] and r.json()["display"] == "Bia"


def test_the_page_reads_the_REAL_refusal_and_the_REAL_whoami(two_people):
    """Joined end to end: the server's bytes, the page's functions. Whatever either side renames,
    this is the case that says so."""
    ba = {"authorization": "Bearer ba-secret"}
    refused = two_people.get("/api/floor/acme", headers=ba)
    who = two_people.get("/api/whoami", headers=ba).json()
    got = run(f"routes={{'/api/floor/acme':[{{status:{refused.status_code},"
              f"body:{json.dumps(refused.json())}}}],"
              f"'/api/whoami':[{{status:200,body:{json.dumps(who)}}}]}};"
              f"me={json.dumps(ANA)};nodes['#who']=node();"
              "await loadFloor();await settle();"
              "return {went,refused:_floorRefused,who:nodes['#who'].innerHTML}",
              "loadFloor", "floorNow", "fsDur")
    assert got["refused"] == refused.json()["detail"]
    assert got["went"] == ["reload"], "a product-only credential stayed on the floor"
    # A token deployment has no login to end: `logout` is null and no door is drawn.
    assert who["logout"] is None and got["who"] == ""
