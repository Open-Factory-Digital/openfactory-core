"""A preview start is said at once and followed, and a failed one is said as a failure (#404).

WHAT HAPPENED. Live on a compose deployment: the person pressed "start a preview" in the card's
drawer, the panel answered 200 with `state: starting` — and the drawer showed the same button and
the same line. Minutes later the record said `failed`, with why and what was left out; the drawer
still showed the button. `previewAct` redrew at once from a record the worker had not written to
yet, the section polled only while the record said `starting`, and a failure was one grey line
above the same button an untouched card has.

EXECUTED, NOT READ: the page's own `loadPreview`, `renderPreview` and `previewAct` run under node
against an `api` that answers what the case says, the way `test_a_refusal_is_not_an_answer.py`
drives the page. The body fed to the page is the one the real route answers.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from openfactory import preview
from openfactory.preview import demand, live

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "openfactory/api/panel.html").read_text()
PR = "https://forge/acme/shop/pull/12"


def _without_comments(page: str) -> str:
    page = re.sub(r"/\*.*?\*/", "", page, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", r"\1", line) for line in page.splitlines())


CODE = _without_comments(PAGE)


def _function(name: str) -> str:
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
    found = re.search(rf"^const {re.escape(name)}\s*=.*$", CODE, re.M)
    return found.group(0) if found else ""


#: `answers` is a list the page's `api` consumes in order, the last one repeating; `posted` is
#: what `mfetch` answers a POST with. `el` is the one node the section draws into.
PRELUDE = r"""
let clock=1700000000000;Date.now=()=>clock;
let answers=[];const asked=[];
async function api(u){asked.push(u);const a=answers.length>1?answers.shift():answers[0];return JSON.parse(JSON.stringify(a))}
let posted={status:200,body:{ok:true,state:"starting"}};const posts=[];
async function mfetch(u,o){posts.push(u);return {ok:posted.status<300,status:posted.status,json:async()=>posted.body}}
const toasts=[];function toast(a,b,c){toasts.push([a,b,c])}
const el={innerHTML:""};const document={getElementById:id=>id==="pv"?el:null};
const timers=[];function setTimeout(f,ms){timers.push(ms);return timers.length}function clearTimeout(){}
const went=[];const location={origin:"http://panel.test",assign:u=>went.push(u)};
"""

CONSTS = ("esc", "safeUrl", "_pvPoll", "_pvPending", "PV_PENDING_MS")
FUNCTIONS = ("renderPreview", "loadPreview", "previewAct", "openPreviewNow")


def run(scenario: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH — the page's JavaScript cannot be executed here")
    script = "\n".join([PRELUDE, *(_const(c) for c in CONSTS), *(_function(f) for f in FUNCTIONS),
                        "(async()=>{" + scenario + "})().then(o=>console.log(JSON.stringify(o)))"
                        ".catch(e=>{console.error(String(e&&e.stack||e));process.exit(1)})"])
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-1500:]
    return json.loads(done.stdout)


# ── the body, from the real route ───────────────────────────────────────────────────────────────


@pytest.fixture
def panel(monkeypatch, tmp_path):
    from openfactory.api import app as api
    from openfactory.contracts.project import Project
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOMAIN", "preview.localhost")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_SECRET", "s3cret")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", "compose")
    for env in ("OPENFACTORY_PANEL_TOKEN", "OPENFACTORY_PANEL_TOKENS", "OPENFACTORY_PRODUCT_TOKENS"):
        monkeypatch.delenv(env, raising=False)
    demand._CACHE.clear()
    reg = ProjectRegistry()
    reg.add(Project(name="acme", repo_path=str(tmp_path / "acme")))
    reg.add(Project(name="loja", repo_path=str(tmp_path / "loja"), language="pt-BR"))
    monkeypatch.setattr(demand, "forge_state", lambda *a, **k: demand.ForgeState(
        open=(PR,), heads={}, branches={}))
    yield TestClient(api.app)
    demand._CACHE.clear()


FAILED_WHY = "this unit has no open pull request — a preview shows a change, and there is none " \
             "to show yet."
LEFT_OUT = f"{PR}'s change is in `shop`, and this preview is of `acme`'s own repository — not " \
           f"included."


def _failed(project: str = "acme") -> preview.Preview:
    return preview.Preview(project=project, unit="12", cards=("12",), state=preview.FAILED,
                           pr_urls=(PR,), why=FAILED_WHY, missing=(LEFT_OUT,),
                           started_at=1_900_000_000, ended_at=1_900_000_060,
                           started_by=live.AUTO_STARTER)


def test_the_body_of_a_failed_preview_says_so_in_the_projects_language(panel):
    preview.record(_failed())
    preview.record(_failed("loja"))
    en = panel.get("/api/preview/acme/12").json()
    assert en["state"] == "failed" and en["why"] == FAILED_WHY and en["missing"] == [LEFT_OUT]
    assert en["headline"] == "The preview did not come up."
    assert en["started_at"] == 1_900_000_000 and en["ended_at"] == 1_900_000_060
    assert en["can_start"] is True, "a failed start can be started again"
    assert en["who"] == "started on its own when the pull request opened"
    pt = panel.get("/api/preview/loja/12").json()
    assert pt["headline"] == "A pré-visualização não subiu."
    assert pt["starting"].startswith("Subindo uma pré-visualização")
    assert pt["why"] == FAILED_WHY, "the reason is the step's own, never translated"


def test_every_state_has_its_line_in_both_languages():
    from openfactory.techlead import voice

    for key, entry in voice.PREVIEW.items():
        assert set(entry) >= {"en", "pt-BR"}, key
    offered = preview.Preview(project="a", unit="1", state=preview.OFFERED)
    up = preview.Preview(project="a", unit="1", state=preview.LIVE, expires_at=2_000_000_000)
    ended = preview.Preview(project="a", unit="1", state=preview.ENDED)
    assert live.headline(offered, can_start=True, language="pt-BR").startswith("Dá para subir")
    assert live.headline(offered, can_start=False, language="en") == ""
    assert live.headline(up, can_start=False, language="en", now=1.0) == \
        "The preview is up until 2033-05-18 03:33 UTC."
    assert live.headline(ended, can_start=True, language="pt-BR") == "A pré-visualização terminou."


# ── the page ────────────────────────────────────────────────────────────────────────────────────


def _body(panel, project: str = "acme") -> dict:
    return panel.get(f"/api/preview/{project}/12").json()


def test_a_failed_preview_is_drawn_as_a_failure_with_its_reason_and_start_again(panel):
    preview.record(_failed())
    body = _body(panel)
    got = run(f"answers=[{json.dumps(body)}];await loadPreview('acme','12','pv');"
              "return {html:el.innerHTML,timers}")
    html = got["html"]
    assert "preview failed" in html and "The preview did not come up." in html
    assert "there is none to show yet" in html, "the step's reason is under the headline"
    assert "not included" in html, "every part left out is said"
    assert ">start again</button>" in html and ">start a preview</button>" not in html
    assert got["timers"] == [], "a settled failure is not polled"


def test_a_click_whose_record_has_not_moved_says_starting_and_asks_again(panel):
    """The live sequence: the start is accepted, the record still says the last start's
    `failed`. The section says it is starting — not the failure it replaced — and asks again."""
    preview.record(_failed())
    before = _body(panel)
    # THE BUTTON THE PAGE DREW is the one pressed: its data, read off the drawn html
    got = run(f"answers=[{json.dumps(before)}];await loadPreview('acme','12','pv');"
              "const d={};for(const m of el.innerHTML.matchAll(/data-(\\w+)=\"([^\"]*)\"/g))"
              "d[m[1]]=m[2];const btn={dataset:{p:d.p,u:d.u,n:d.n,id:d.id,s:d.s},innerHTML:''};"
              "await previewAct(btn,'start');return {html:el.innerHTML,timers,posts,toasts,d}")
    assert got["d"]["s"] == str(before["started_at"]), "the button carries the start it replaces"
    assert got["posts"] == ["/api/preview/acme/12/start"]
    assert "Starting a preview" in got["html"], got["html"]
    assert "preview failed" not in got["html"], "the failure the click replaced is not redrawn"
    assert got["timers"] and got["timers"][-1] <= 4000, "it asks again while it waits"


def test_the_section_follows_the_new_start_to_its_failure(panel):
    preview.record(_failed())
    before = _body(panel)
    preview.record(_failed().model_copy(update={"started_at": 1_900_000_500,
                                                "ended_at": 1_900_000_560}))
    after = _body(panel)
    got = run(f"answers=[{json.dumps(before)},{json.dumps(before)},{json.dumps(after)}];"
              "await loadPreview('acme','12','pv');"
              f"const btn={{dataset:{{p:'acme',u:'12',n:'12',id:'pv',s:'{before['started_at']}'}},"
              "innerHTML:'',disabled:false};"
              "await previewAct(btn,'start');const waiting=el.innerHTML;"
              "await loadPreview('acme','12','pv');return {waiting,html:el.innerHTML}")
    assert "Starting a preview" in got["waiting"]
    assert "preview failed" in got["html"], "the newer start's failure is said once it is written"


def test_a_click_the_panel_refused_is_said_and_nothing_waits(panel):
    preview.record(_failed())
    body = _body(panel)
    got = run(f"answers=[{json.dumps(body)}];"
              "posted={status:409,body:{ok:false,message:'no preview can run here'}};"
              "const btn={dataset:{p:'acme',u:'12',n:'12',id:'pv',s:'0'},innerHTML:''};"
              "await previewAct(btn,'start');return {html:el.innerHTML,toasts,timers}")
    assert got["toasts"][0][1] == "no preview can run here"
    assert "preview failed" in got["html"] and got["timers"] == []


def test_a_waiting_click_gives_up_after_its_window(panel):
    preview.record(_failed())
    body = _body(panel)
    got = run(f"answers=[{json.dumps(body)}];"
              "const btn={dataset:{p:'acme',u:'12',n:'12',id:'pv',s:'"
              f"{body['started_at']}'}},innerHTML:''}};"
              "await previewAct(btn,'start');clock+=PV_PENDING_MS+1;"
              "await loadPreview('acme','12','pv');return {html:el.innerHTML}")
    assert "preview failed" in got["html"], "a start that never began is not 'starting' for ever"


def test_the_comments_link_walks_into_a_live_preview(panel):
    preview.record(preview.Preview(project="acme", unit="12", cards=("12",), state=preview.LIVE,
                                   services={"web": 3000}, from_change={"web": True},
                                   pr_urls=(PR,), expires_at=int(time.time()) + 3600,
                                   started_by=live.AUTO_STARTER))
    body = _body(panel)
    assert body["link"] == "/p/acme/preview/12"
    got = run(f"answers=[{json.dumps(body)}];await openPreviewNow('acme','12');return went")
    assert got == [body["services"][0]["url"]]
    nothing = run("answers=[{live:false,state:'failed'}];await openPreviewNow('acme','12');"
                  "return went")
    assert nothing == []


def test_the_route_the_comment_carries_is_served(panel):
    r = panel.get("/p/acme/preview/12")
    assert r.status_code == 200 and "openPreviewNow" in r.text
