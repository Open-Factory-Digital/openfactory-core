"""The product owner's page is a chat, with the product beside it (#335).

The client talks to the product role on this page, and it was a column of buttons and a list that
pushed everything down with every message. It is now what every chat a person already uses is: the
conversations on the left (the project's room pinned, one's own below, a new one a click away), the
conversation in the middle, and the product — requirements, agenda, documents, board — beside it.
These tests execute the page's own functions under node (`test_the_panel_is_a_chat._run`) and hold
what a regression would cost a client:

  1. what the role writes is rendered as markdown, and never as HTML somebody typed;
  2. the page names a conversation by the room or a session id — never a private key;
  3. a session id reaches a click handler only in the server's shape;
  4. the list shows one's conversations, a new one before its first message, and a search;
  5. the role's sign-off is not repeated under a message that already names it.
"""
from __future__ import annotations

import pytest

from tests.test_the_panel_is_a_chat import CODE, _function, _run

# ── 1. markdown, safely ─────────────────────────────────────────────────────────────────────────

def _md(text: str) -> str:
    import json

    return _run(f"return pvMd({json.dumps(text)})", pathname="/product/books")


@pytest.mark.parametrize("hostile", [
    "<img src=x onerror=alert(1)>",
    "<script>alert(1)</script>",
    "**<b onmouseover=alert(1)>x</b>**",
    "```\n</code></pre><script>alert(1)</script>\n```",
])
def test_nothing_a_person_typed_becomes_html(hostile):
    out = _md(hostile)
    for tag in ("<img", "<script", "<b onmouseover", "</code></pre><script"):
        assert tag not in out, out
    assert "&lt;" in out


def test_a_link_is_only_ever_http_and_never_breaks_out_of_its_attribute():
    assert '<a href="https://example.com/a" target="_blank" rel="noopener noreferrer">docs</a>' \
        in _md("see [docs](https://example.com/a)")
    assert "<a " not in _md("[x](javascript:alert(1))")
    broken = _md('[x](https://a.b/"onmouseover="alert(1))')
    assert '"onmouseover' not in broken, broken


def test_the_role_s_markdown_is_rendered_as_structure():
    out = _md("## Plano\n\n**5** requisitos:\n- um\n- dois\n\n1. primeiro\n\n> citado\n\n`código`")
    assert "<h4>Plano</h4>" in out
    assert "<b>5</b> requisitos:" in out
    assert "<ul><li>um</li><li>dois</li></ul>" in out
    assert "<ol><li>primeiro</li></ol>" in out
    assert "<blockquote>citado</blockquote>" in out
    assert "<code>código</code>" in out


# ── 2. the page names the room or a session, never a key ───────────────────────────────────────

def test_a_session_is_asked_for_by_its_id_and_the_room_carries_none():
    got = _run("""const s={readyState:1,send(x){sent.push(JSON.parse(x))}};
      _pc.sock=s;_pc.project='books';
      _pc.room=false;_pc.session='k3f9a2';pchatSubscribe();
      _pc.room=true;pchatSubscribe();
      _pc.room=false;_pc.session='';pchatSubscribe();return sent""", pathname="/product/books")
    assert got == [{"kind": "subscribe", "project": "books", "room": False, "session": "k3f9a2"},
                   {"kind": "subscribe", "project": "books", "room": True},
                   {"kind": "subscribe", "project": "books", "room": False}]
    assert "person:" not in _function("pchatSubscribe")


# ── 3. a session id only in the server's shape ──────────────────────────────────────────────────

def test_a_session_id_is_letters_and_digits_or_nothing():
    got = _run("""return ['k3f9a2',"x');alert(1);('", 'AB12', 'abc', 'a'.repeat(25), null]
      .map(pvSid)""", pathname="/product/books")
    assert got == ["k3f9a2", "", "", "", "", ""]


def test_a_new_conversation_mints_an_id_the_server_takes():
    import re

    new = _function("pvNewChat")
    assert "crypto.getRandomValues" in new and "Math.random" not in new
    got = _run("""const b=new Uint8Array(8);crypto.getRandomValues(b);
      return Array.from(b,x=>(x%36).toString(36)).join("")""", pathname="/product/books")
    assert re.fullmatch(r"[a-z0-9]{4,24}", got)
    for where in ("bootProduct", "pvOpen", "paintSessions", "pchatFrame"):
        assert "pvSid(" in _function(where), f"{where} takes a session id unchecked"


# ── 4. the list of conversations ────────────────────────────────────────────────────────────────

_LIST = """nodes['#scopeRoom']=node();nodes['#scopeMine']=node();nodes['#pvSessions']=node();
  nodes['#pvFind']=node();
  _pv.sessions=[{session:'',title:'Primeira',last:'oi',last_ts:''},
                {session:'aaaa1',title:'Valor mensal',last:'Depende do plano.',last_ts:''},
                {session:'bbbb2',title:'Relatório',last:'ok',last_ts:''},
                {session:"x');alert(1);('",title:'forged',last:'',last_ts:''}];
  _pv.roomLast={text:'bom dia',ts:''};"""


def test_the_list_shows_the_room_one_s_first_conversation_and_one_s_sessions():
    got = _run(_LIST + """_pc.room=false;_pc.session='aaaa1';paintSessions();
      return {room:nodes['#scopeRoom'].innerHTML,mine:nodes['#scopeMine'].innerHTML,
              list:nodes['#pvSessions'].innerHTML}""", pathname="/product/books")
    assert "Project room" in got["room"] and "bom dia" in got["room"]
    assert "Primeira" in got["mine"]
    assert "Valor mensal" in got["list"] and "Relatório" in got["list"]
    assert 'data-act="pvOpen" data-s="aaaa1"' in got["list"]
    assert "forged" not in got["list"] and "alert" not in got["list"]


def test_a_new_conversation_is_listed_before_its_first_message():
    got = _run(_LIST + """_pc.room=false;_pc.session='zzzz9';paintSessions();
      return nodes['#pvSessions'].innerHTML""", pathname="/product/books")
    assert got.index("New conversation") < got.index("Valor mensal")


def test_the_search_filters_one_s_conversations():
    got = _run(_LIST + """_pc.room=true;nodes['#pvFind'].value='relat';paintSessions();
      const one=nodes['#pvSessions'].innerHTML;
      nodes['#pvFind'].value='nada disso';paintSessions();
      return {one,none:nodes['#pvSessions'].innerHTML}""", pathname="/product/books")
    assert "Relatório" in got["one"] and "Valor mensal" not in got["one"]
    assert "no conversation of yours matches" in got["none"]


# ── 5. the sign-off ─────────────────────────────────────────────────────────────────────────────

def test_the_role_s_sign_off_is_not_repeated_under_its_own_name():
    got = _run("""_pc.agentName='Clara';
      return pvMsg({who:'agent',text:'Tudo certo.\\n\\n— Clara'})""", pathname="/product/books")
    assert "Tudo certo." in got and "— Clara" not in got


def test_the_page_is_the_whole_screen():
    assert "body.ps" in CODE and ".pv{" in CODE.replace(" ", "")
    assert 'document.body.classList.add("ps")' in _function("bootProduct") or \
        "classList.add('ps')" in _function("bootProduct")


# ── 6. one's own conversations are renamed and deleted from the list ───────────────────────────

_KEPT = _LIST.replace("last:'Depende do plano.',last_ts:''", "last:'Depende do plano.',"
                      "last_ts:'2026-09-25T10:00:00+00:00'")


def test_only_one_s_own_kept_conversations_carry_a_menu():
    got = _run(_KEPT + """_pc.room=false;_pc.session='zzzz9';paintSessions();
      return {room:nodes['#scopeRoom'].innerHTML,list:nodes['#pvSessions'].innerHTML}""",
               pathname="/product/books")
    assert "pv-more" not in got["room"], "the room is everybody's — nobody renames or deletes it"
    assert 'data-act="pvMenu" data-s="aaaa1"' in got["list"]
    rows = got["list"].split('<div class="pv-conv')[1:]
    fresh = next(r for r in rows if "New conversation" in r)
    assert "pv-more" not in fresh, "a conversation nothing was said in has nothing to delete"


def test_the_menu_offers_rename_and_delete_and_rename_edits_in_place():
    got = _run(_KEPT + """_pc.room=true;_pv.menu='aaaa1';paintSessions();
      const menu=nodes['#pvSessions'].innerHTML;
      _pv.menu=null;_pv.editing='aaaa1';paintSessions();
      return {menu,edit:nodes['#pvSessions'].innerHTML}""", pathname="/product/books")
    assert 'data-act="pvRename" data-s="aaaa1"' in got["menu"]
    assert 'data-act="pvDelete" data-s="aaaa1"' in got["menu"]
    assert 'class="pv-rename"' in got["edit"] and 'value="Valor mensal"' in got["edit"]
    assert 'onkeydown="pvRenameKey(event,this)"' in got["edit"]


def test_the_delete_confirmation_says_what_is_erased_and_what_stays():
    body = _function("pvDelete")
    assert "is erased" in body and "stays" in body
    assert 'data-act="pvDeleteYes"' in body and "onclick=\"pvDeleteYes" not in body
    assert "product_session_delete" in _function("pvDeleteYes")
    assert "product_session_rename" in _function("pvRenameSave")


# ── 7. files in the conversation (#336) ────────────────────────────────────────────────────────

_SHOT = "a" * 64


def test_a_message_sends_the_ids_of_its_files_and_nothing_else_of_them():
    got = _run("""const s={readyState:1,send(x){sent.push(JSON.parse(x))}};
      _pc.sock=s;_pc.live=true;_pc.project='books';nodes['#prodThread']=node();
      pchatSay('',[{id:'""" + _SHOT + """',name:'print.png',size:10,url:'blob:x'}]);
      return sent""", pathname="/product/books")
    assert got[0]["attachments"] == [_SHOT] and got[0]["text"] == ""
    assert "url" not in str(got[0]) and "print.png" not in str(got[0])


def test_a_file_s_name_is_text_and_its_address_never_carries_the_credential():
    got = _run("""_pc.project='books';
      return pvFilesOf([{id:'""" + _SHOT + """',name:'<img src=x onerror=alert(1)>.pdf',size:2048},
                        {id:'""" + _SHOT + """',name:'tela.png',size:10,url:'blob:local'}])""",
               pathname="/product/books")
    assert "<img src=x" not in got and "&lt;img src=x" in got
    assert 'src="blob:local"' in got and "token" not in got
    assert 'data-act="pvOpenFile"' in got
    assert "authHeaders()" in _function("pvThumb") and "authHeaders()" in _function("pvOpenFile")


def test_a_message_of_files_alone_shows_the_files_not_their_placeholder():
    got = _run("""_pc.agentName='Nina';
      return pvMsg({who:'me',text:'[tela.png]',files:[{id:'""" + _SHOT + """',name:'tela.png',
                    size:10,url:'blob:local'}]})""", pathname="/product/books")
    assert "pv-shot" in got and "[tela.png]" not in got


def test_the_composer_takes_files_by_button_drop_and_paste():
    page = CODE
    assert 'onclick="pvPick()"' in page and 'onpaste="pvPaste(event)"' in page
    assert 'ondrop="pvDrop(event)"' in page
    assert "x-attachment-name" in _function("pvUpload")
    assert "pvReadyFiles()" in _function("askProduct")


# ── 8. the documents, as the repository holds them (#336) ─────────────────────────────────────

_DOCS = """nodes['#prodDocs']=node();nodes['#prodDocCount']=node();nodes['#pvHere']=node();
  _prod.project='books';
  _prod.docs={checked_at:'x',read:4,listed_all:true,
    documents:[{path:'client/sla.pdf',title:'Acordo <b>SLA</b>',type:'pdf',audience:'client'},
               {path:'README.md',title:'Books',type:'markdown',audience:'internal'},
               {path:'requirements/0001-a.md',title:'REQ',type:'markdown',audience:'client'}],
    documents_internal:[{path:'internal/precos.md',title:'Preços',type:'markdown',audience:'internal'}],
    unreadable:[{path:'client/locked.pdf',type:'pdf',audience:'client',reason:'a protected PDF'}]};"""


def test_the_documents_are_grouped_by_their_folder_and_downloaded_or_asked_about():
    got = _run("globalThis._prod={};" + _DOCS + """paintDocuments();
      return {html:nodes['#prodDocs'].innerHTML,cnt:nodes['#prodDocCount'].textContent}""",
               pathname="/product/books")
    html = got["html"]
    assert html.index("the repository&#39;s root") < html.index("client/") < html.index("internal/")
    assert "requirements/0001-a.md" not in html, "the requirements have their own tab"
    assert "Acordo &lt;b&gt;SLA&lt;/b&gt;" in html and "<b>SLA</b>" not in html
    assert 'data-act="pvDocGet" data-p="client/sla.pdf"' in html
    assert 'data-act="pvDocAsk" data-p="internal/precos.md"' in html
    assert "unreadable · a protected PDF" in html
    assert got["cnt"] == "3 · 1 unreadable"


def test_the_documents_are_searched_by_title_and_path():
    got = _run("globalThis._prod={};" + _DOCS + """_pv.docQ='preço';paintDocuments();
      const one=nodes['#prodDocs'].innerHTML;_pv.docQ='nada';paintDocuments();
      return {one,none:nodes['#prodDocs'].innerHTML}""", pathname="/product/books")
    assert "internal/precos.md" in got["one"] and "client/sla.pdf" not in got["one"]
    assert "no document matches" in got["none"]


def test_the_conversation_s_files_are_offered_to_be_filed_or_said_to_be_the_product_s():
    got = _run("""nodes['#pvHere']=node();
      _pv.here=[{id:'""" + _SHOT + """',name:'spec.docx',size:2048,filed:''},
                {id:'""" + "b" * 64 + """',name:'ata.pdf',size:10,filed:'from-chat/2026-09-25-ata.pdf'}];
      pvPaintHere();return nodes['#pvHere'].innerHTML""", pathname="/product/books")
    assert "In this conversation" in got
    assert 'data-act="pvFileIt" data-i="' + _SHOT + '"' in got
    assert "in the product, at" in got and "from-chat/2026-09-25-ata.pdf" in got
    assert got.count("File into the product") == 1
    assert "product_file_attachment" in _function("pvFileYes")
    assert "authHeaders()" in _function("pvDocGet")
    assert got.count('data-act="pvDiscard"') == 2, "every file of the conversation is discarded"


def test_the_discard_confirmation_says_what_is_erased_and_what_stays():
    body = _function("pvDiscard")
    assert "cannot be undone" in body and "still names it" in body and "stays" in body
    assert 'data-act="pvDiscardYes"' in body and "onclick=\"pvDiscardYes" not in body
    assert "product_discard_attachment" in _function("pvDiscardYes")


def test_a_discarded_file_is_shown_as_gone_never_as_a_link():
    got = _run("""_pc.project='books';
      return pvFilesOf([{id:'""" + _SHOT + """',name:'tela.png',size:10,url:'blob:local',gone:true}])""",
               pathname="/product/books")
    assert "discarded" in got and "pvOpenFile" not in got and "blob:local" not in got
