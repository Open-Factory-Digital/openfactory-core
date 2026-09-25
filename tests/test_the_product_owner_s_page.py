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
