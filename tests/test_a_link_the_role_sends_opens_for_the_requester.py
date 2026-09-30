"""The preview and card links the product role sends open for the person they are sent to (#444).

`boot()` hands a product-scoped credential to `bootProduct()` before anything reads the path, and
the code that understands `/p/<project>/(card|preview)/<ref>` lived on the floor's path only. The
requester — product-scoped by design — opened "you can already try #1000007: /p/…/preview/1000007"
and got the product page: no preview, no card. The operator, who needs no link, was the one it
worked for."""
import re
from pathlib import Path

PAGE = (Path(__file__).resolve().parent.parent / "openfactory/api/panel.html").read_text()
CODE = PAGE[PAGE.index("<script>"):]


def _function(name: str) -> str:
    start = CODE.index(f"function {name}(")
    nxt = re.search(r"\n(async )?function ", CODE[start + 10:])
    return CODE[start:start + 10 + (nxt.start() if nxt else len(CODE))]


def test_the_product_page_reads_the_link_before_it_asks_which_project():
    boot = _function("bootProduct")
    assert "curBoard()" in boot, "the product page must read the link the floor reads"
    assert boot.index("curBoard()") < boot.index('api("/api/product/projects")'), (
        "the project a link names comes before the one-project guess")
    assert re.search(r'history\.replaceState\(\{\},"","/product/"\+encodeURIComponent\(name\)\)',
                     boot[boot.index("curBoard()"):]), (
        "the address becomes the product page's own, so a reload stays on it")


def test_a_preview_link_walks_into_the_preview_and_a_card_link_opens_the_card():
    boot = _function("bootProduct")
    tail = boot[boot.index("loadSessions()"):]
    assert "if(linked.preview)openPreviewNow(linked.project,linked.card)" in tail, (
        "a preview link must walk into the preview, with the key the server mints for this person")
    assert 'pvTab("board");pvCardOpen(linked.card)' in tail, (
        "a card link — and a preview that is not up — opens the card on the Board tab")


def test_the_link_parser_the_product_page_uses_is_the_floors():
    parser = _function("curBoard")
    assert "(board|card|pr|preview)(?=\\/|$)" in parser and 'm[2]==="preview"' in parser


def _whole(name: str) -> str:
    at = CODE.index(f"function {name}(")
    start = at - 6 if CODE[max(0, at - 6):at] == "async " else at
    depth = 0
    for pos in range(CODE.index("{", at), len(CODE)):
        depth += {"{": 1, "}": -1}.get(CODE[pos], 0)
        if depth == 0:
            return CODE[start:pos + 1]
    raise AssertionError(name)


def _boot(path: str) -> dict:
    """`bootProduct` itself, under node, at `path` — with the page's own `curBoard` and
    `curProduct`, and every read and painter it calls recorded instead of performed."""
    import json
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH — the page's JavaScript cannot be executed here")
    stubs = ("loadAgenda loadDocuments loadProductStatus loadRequirements loadSessions paintScope "
             "pvBoardLoad pvPaintHead pvSize renderProduct sayWhyThisPage").split()
    script = "\n".join([
        f"const location={{pathname:{json.dumps(path)}}};",
        "const calls=[];let url=location.pathname;",
        "const history={replaceState:(a,b,u)=>{url=u;location.pathname=u}};",
        "const localStorage={getItem:()=>null,setItem(){}};",
        "const document={body:{classList:{add(){}}},addEventListener(){}};",
        "const window={addEventListener(){}};const $=()=>null;",
        "let _surface='',_prod={project:''},_pc={},_pv={};",
        "const api=async u=>{calls.push(['api',u]);return[]};",
        "const pvSid=x=>x;const pvAway=()=>{};",
        "const openPreviewNow=(p,c)=>calls.push(['preview',p,c]);",
        "const pvTab=k=>calls.push(['tab',k]);const pvCardOpen=r=>calls.push(['card',r]);",
        *(f"const {s}=()=>{{}};" for s in stubs),
        _whole("curProduct"), _whole("curBoard"), _whole("bootProduct"),
        "bootProduct().then(()=>console.log(JSON.stringify({url,project:_prod.project,calls})))"])
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-1500:]
    return json.loads(done.stdout)


def test_under_node_a_preview_link_walks_into_the_preview_for_a_product_login():
    got = _boot("/p/mockupstudio/preview/1000007")
    assert got["project"] == "mockupstudio" and got["url"] == "/product/mockupstudio", got
    assert ["preview", "mockupstudio", "1000007"] in got["calls"], got["calls"]
    assert ["api", "/api/product/projects"] not in got["calls"], "the link named the project"


def test_under_node_a_card_link_opens_the_card_and_never_the_preview():
    got = _boot("/p/mockupstudio/card/1000007")
    assert ["tab", "board"] in got["calls"] and ["card", "1000007"] in got["calls"], got["calls"]
    assert not any(c[0] == "preview" for c in got["calls"]), got["calls"]


def test_under_node_the_product_page_itself_is_untouched():
    got = _boot("/product/mockupstudio")
    assert got["url"] == "/product/mockupstudio" and got["project"] == "mockupstudio"
    assert not any(c[0] in ("preview", "card") for c in got["calls"]), got["calls"]


def test_under_node_the_parser_tells_a_preview_from_a_pull_request():
    """`pr` is a prefix of `preview`: the alternation read `/p/x/preview/7` as `pr` with no ref,
    so the floor's path — the operator's — was dead for the same link too."""
    import json
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH — the page's JavaScript cannot be executed here")
    cases = ["/p/x/preview/7", "/p/x/pr/5", "/p/x/card/9", "/p/x/board", "/p/x/prx/1"]
    script = "\n".join([
        "const location={pathname:''};", _whole("curBoard"),
        f"console.log(JSON.stringify({json.dumps(cases)}.map(p=>{{location.pathname=p;"
        f"return curBoard()}})))"])
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-800:]
    preview, pr, card, board, unknown = json.loads(done.stdout)
    assert preview == {"project": "x", "card": "7", "pr": "", "preview": True}, preview
    assert pr == {"project": "x", "card": "", "pr": "5", "preview": False}, pr
    assert card["card"] == "9" and not card["preview"], card
    assert board == {"project": "x", "card": "", "pr": "", "preview": False}, board
    assert unknown is None, f"a segment the page does not know is no view at all: {unknown}"
