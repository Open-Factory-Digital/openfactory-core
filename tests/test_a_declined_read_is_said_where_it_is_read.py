"""A declined read is said where it is read: the budget's hover text and the tech-lead chat.

WHAT WAS LEFT. #181 made `api()` reject every non-2xx with the server's sentence, and named two
readers whose `catch` still said nothing true about it:

  · `pollBudget` answered EVERY failure with `{state:"unread"}` — the SERVER's word for "the probe
    failed on a vendor that does report a budget" — so a 403 about the session, a request that
    never left the browser, and the moment before the first answer all hovered as "API budget
    could not be read — the poller scans without that safety net". A statement about the poller,
    made out of a sentence about the session.
  · `refreshChat` returned from its `catch` before painting. The thread stayed, which is right —
    but so did the silence: no note, Send still offered, and because EVERY chat gesture reports
    its outcome through that repaint, a question typed into a declined chat cleared the input,
    drew nothing, and showed neither the question nor the refusal. Measured 2026-09-19 with the
    cases below against the page as it was: 18 of 19 red.

EXECUTED, NOT READ — the harness is `test_a_refusal_is_not_an_answer`'s: the page's own functions
under node, against a `fetch` the case controls. The last section feeds the page the bytes the REAL
scope gate answers for the chat's read and for its send.
"""
from __future__ import annotations

import json
import re

import pytest

from tests.test_a_refusal_is_not_an_answer import (  # noqa: F401
    ANA,
    CODE,
    REFUSED,
    _const,
    run,
    two_people,
)

SAID = REFUSED["body"]["detail"]
THE_POLLER_CLAIM = "the poller scans without that safety net"


def _let(name: str) -> str:
    """The page's own declaration of a top-level `let`, so a case starts from the value a browser
    starts from — and "" on a page that has none, so the case fails on what the page DOES."""
    found = re.search(rf"^let {re.escape(name)}=.*$", CODE, re.M)
    return found.group(0) if found else ""


# ── 1. the budget's hover text ─────────────────────────────────────────────────────────────────

BUDGET = _let("_budget")
OK_BUDGET = {"summary": {"state": "ok", "vendor": "GitHub", "resource": "core", "remaining": 4200,
                         "limit": 5000}, "rows": []}


def budget(scenario: str) -> dict:
    return run(scenario, "pollBudget", "budgetLine", stubs=BUDGET)


def test_a_DECLINED_budget_read_says_nothing_about_the_poller():
    """What hovered under a header that already said Refused."""
    got = budget(f"routes={{'/api/budget':[{json.dumps(REFUSED)}],'/api/whoami':[{{status:200,"
                 f"body:{json.dumps(ANA)}}}]}};await pollBudget();"
                 "return {line:budgetLine(_budget),state:_budget.state,painted:[...painted]}")
    assert THE_POLLER_CLAIM not in got["line"], (
        f"a 403 about the session hovers as a fact about the poller: {got['line']!r}")
    assert got["state"] == "refused"
    assert "this session may not read it" in got["line"], got["line"]
    assert got["painted"] == ["floor"], "the header was not redrawn with it"


def test_a_401_is_the_same_answer():
    got = budget("routes={'/api/budget':[{status:401,body:{detail:'that session ended'}}]};"
                 "await pollBudget();return {line:budgetLine(_budget),state:_budget.state}")
    assert got["state"] == "refused" and THE_POLLER_CLAIM not in got["line"], got


@pytest.mark.parametrize("answer", ["{network:true}", "{status:502,text:'<html>'}"])
def test_a_page_that_COULD_NOT_ASK_says_that_and_not_the_vendors_word(answer):
    """`unread` is the server's: its probe failed on the vendor. A request that never reached the
    panel — or reached a proxy's error page — knows nothing about the probe either way."""
    got = budget(f"routes={{'/api/budget':[{answer}]}};await pollBudget();"
                 "return {line:budgetLine(_budget),state:_budget.state}")
    assert got["state"] == "unasked", got
    assert THE_POLLER_CLAIM not in got["line"] and "this page could not read it" in got["line"], got


def test_BEFORE_the_first_answer_the_hover_claims_nothing():
    got = budget("return {line:budgetLine(_budget)}")
    assert got["line"] == "", f"nothing has been asked yet and the hover says {got['line']!r}"


def test_the_servers_own_UNREAD_still_reads_as_it_did():
    """The sentence is TRUE when the server says it, and must survive: the poller does fail open."""
    got = budget("routes={'/api/budget':[{status:200,body:{summary:{state:'unread',"
                 "vendor:'GitHub'},rows:[]}}]};await pollBudget();return {line:budgetLine(_budget)}")
    assert got["line"] == f"GitHub budget could not be read — {THE_POLLER_CLAIM}"


def test_the_numbers_COME_BACK_when_the_read_is_answered_again():
    got = budget(f"routes={{'/api/budget':[{json.dumps(REFUSED)},{{status:200,"
                 f"body:{json.dumps(OK_BUDGET)}}}],'/api/whoami':[{{status:200,"
                 f"body:{json.dumps(ANA)}}}]}};await pollBudget();const a=_budget.state;"
                 "await pollBudget();return {a,line:budgetLine(_budget)}")
    assert got == {"a": "refused", "line": "GitHub core budget 4200/5000"}


# ── 2. the tech-lead chat ──────────────────────────────────────────────────────────────────────

THREAD = {"messages": [{"kind": "said", "text": "picked up #7", "ts": "2026-09-19T10:00:00",
                        "token": "t1"}], "pending": [], "suggestion": None}
MESSAGES = "/api/messages/acme"
CHAT = ("let _chatProject='acme',_chatLocal=[],_chatTimer=null,_staged=null;const _RETIRED={};"
        "let _chatLast=null,_chatRefused='',_chatErr='';"
        "for(const n of ['#chatLog','#chatNote','#askInput','#askBtn'])nodes[n]=node();"
        "nodes['#askInput'].value='';")
CHAT_FUNCTIONS = ("refreshChat", "paintChat", "chatNote", "drawChatNote", "askTechlead",
                  "approveSuggestion")
WHO = f"'/api/whoami':[{{status:200,body:{json.dumps({**ANA, 'scopes': ['other']})}}}]"
SCREEN = ("({log:nodes['#chatLog'].innerHTML,note:nodes['#chatNote'].innerHTML,"
          "input:nodes['#askInput'].value,inputOff:!!nodes['#askInput'].disabled,"
          "sendOff:!!nodes['#askBtn'].disabled})")


def chat(scenario: str, stubs: str = "") -> dict:
    return run(scenario, *CHAT_FUNCTIONS, stubs=CHAT + stubs)


#: One answered read, then the credential changes under the tab.
READ_THEN_DECLINED = (f"routes={{'{MESSAGES}':[{{status:200,body:{json.dumps(THREAD)}}},"
                      f"{json.dumps(REFUSED)}],{WHO}}};await refreshChat();")


def test_a_DECLINED_thread_is_kept_AND_says_so():
    got = chat(READ_THEN_DECLINED + f"await refreshChat();return {SCREEN}")
    assert "picked up #7" in got["log"], "the thread on screen was wiped by a refusal"
    assert "may not read this conversation" in got["note"], (
        f"the chat says nothing about being declined: note={got['note']!r}")
    assert SAID in got["note"], "the server's own sentence was dropped"


def test_SEND_is_not_offered_to_a_session_the_server_has_declined():
    """The floor's rule for Scan (#181), for the same reason: the gate refuses the send before the
    route runs, so for this session pressing it has exactly one outcome."""
    got = chat(READ_THEN_DECLINED + f"await refreshChat();return {SCREEN}")
    assert got["inputOff"] and got["sendOff"], "a person may type into a chat that will refuse them"


def test_a_FIRST_read_that_is_declined_is_not_an_empty_conversation():
    got = chat(f"routes={{'{MESSAGES}':[{json.dumps(REFUSED)}],{WHO}}};await refreshChat();"
               f"return {SCREEN}")
    assert "may not read this conversation" in got["note"], "declined, and drawn as an empty thread"


def test_a_thread_that_COULD_NOT_BE_READ_says_that_and_still_offers_send():
    """The other cause, the other remedy — and no reason to think a send would be refused."""
    got = chat(f"routes={{'{MESSAGES}':[{{status:200,body:{json.dumps(THREAD)}}},{{network:true}}]}};"
               f"await refreshChat();await refreshChat();return {SCREEN}")
    assert "could not be read" in got["note"] and "may not" not in got["note"], got["note"]
    assert "picked up #7" in got["log"] and not got["inputOff"] and not got["sendOff"], got


def test_the_note_LEAVES_and_send_RETURNS_when_the_read_is_answered_again():
    """A refusal that never cleared would be the same defect wearing the opposite sign."""
    got = chat(f"routes={{'{MESSAGES}':[{json.dumps(REFUSED)},{{status:200,"
               f"body:{json.dumps(THREAD)}}}],{WHO}}};await refreshChat();"
               f"const a={SCREEN};await refreshChat();return {{a,b:{SCREEN}}}")
    assert got["a"]["note"] and got["a"]["sendOff"], "the case never had a note to withdraw"
    assert got["b"]["note"] == "" and not got["b"]["sendOff"] and not got["b"]["inputOff"], got["b"]
    assert "picked up #7" in got["b"]["log"]


def test_a_PUSHED_frame_withdraws_could_not_be_read_but_not_a_refusal():
    """The socket's frame IS an answer to "can this page hear" — and is not an answer to "may this
    credential read": that one is the read's alone, as the floor's is."""
    got = chat(f"routes={{'{MESSAGES}':[{{network:true}},{json.dumps(REFUSED)}],{WHO}}};"
               f"await refreshChat();paintChat({json.dumps(THREAD)});const a={SCREEN};"
               f"await refreshChat();paintChat({json.dumps(THREAD)});return {{a,b:{SCREEN}}}")
    assert got["a"]["note"] == "", got["a"]
    assert "may not read this conversation" in got["b"]["note"], got["b"]


def test_a_question_typed_into_a_declined_chat_is_ANSWERED_ON_SCREEN():
    """The send path and the thread agree. Before: the input was cleared, the question was drawn
    nowhere, and the server's refusal of it was pushed into a list nothing painted."""
    got = chat(READ_THEN_DECLINED + f"routes['/api/act/ask']=[{json.dumps(REFUSED)}];"
               "nodes['#askInput'].value='why is #7 parked?';await askTechlead();await settle();"
               f"return {{calls,...{SCREEN}}}")
    assert "POST /api/act/ask" in got["calls"], "the case never sent"
    assert "why is #7 parked?" in got["log"], "what the person typed is nowhere on the screen"
    assert SAID in got["log"], "the refusal of the send was never drawn"
    assert SAID in got["note"], "the send was refused in the thread and the thread says nothing"
    assert "picked up #7" in got["log"]


def test_an_APPROVAL_pressed_in_a_declined_chat_is_answered_on_screen_too():
    got = chat(READ_THEN_DECLINED + f"routes['{MESSAGES}/suggestion']=[{json.dumps(REFUSED)}];"
               "const btn={disabled:false,textContent:''};await approveSuggestion(btn,'t1');"
               f"await settle();return {SCREEN}")
    assert SAID in got["log"], "the button went to 'executando…' and the refusal was never drawn"


def test_what_the_server_said_stays_DATA_in_the_note():
    hostile = {"status": 403, "body": {"detail": "<img src=x onerror=alert(1)>"}}
    got = chat(f"routes={{'{MESSAGES}':[{json.dumps(hostile)}],{WHO}}};await refreshChat();"
               f"return {SCREEN}")
    assert "<img" not in got["note"] and "&lt;img" in got["note"], got["note"]


MOUNT = (_const("_CHAT_TICK") + ";let _mounted=0;function streamWatch(){}"
         "function chatShouldFetch(){return false}function setInterval(){return 0}"
         "function clearInterval(){}"
         "document.querySelectorAll=()=>[];document.body={insertAdjacentHTML(_,html){_mounted++;"
         "for(const n of ['chatLog','chatNote','askInput','askBtn'])"
         "if(html.includes('id=\"'+n+'\"'))nodes['#'+n]=node()}};")


def test_the_chat_is_MOUNTED_with_a_place_for_the_note():
    got = run("for(const n in nodes)delete nodes[n];routes={};mountChat('acme');"
              "return {mounted:_mounted,has:Object.keys(nodes).sort()}",
              *CHAT_FUNCTIONS, "mountChat", stubs=CHAT + MOUNT)
    assert got["mounted"] == 1 and "#chatNote" in got["has"], got


def test_ANOTHER_projects_thread_is_not_what_a_refusal_keeps():
    """The kept thread is this project's last answer. Opening the next project under a credential
    that may not read it must not draw the previous project's conversation as its own."""
    got = run(f"routes={{'{MESSAGES}':[{{status:200,body:{json.dumps(THREAD)}}}],"
              f"'/api/messages/other':[{json.dumps(REFUSED)}],{WHO}}};await refreshChat();"
              f"mountChat('other');await settle();return {SCREEN}",
              *CHAT_FUNCTIONS, "mountChat", stubs=CHAT + MOUNT)
    assert "picked up #7" not in got["log"], "acme's thread is drawn in other's chat"
    assert "may not read this conversation" in got["note"]


@pytest.mark.parametrize("answer", [json.dumps(REFUSED), "{status:200,body:" + json.dumps(THREAD) + "}"])
def test_an_outcome_BELONGS_to_the_project_that_asked(answer):
    """A failed read used to do nothing, so one that landed after the person had opened the next
    project could not matter. It sets a note now — on the chat that asked, and no other."""
    got = chat(f"routes={{'{MESSAGES}':[{answer}],{WHO}}};const late=refreshChat();"
               f"_chatProject='other';await late;await settle();return {SCREEN}")
    assert got["note"] == "" and not got["sendOff"], f"acme's refusal is on other's chat: {got}"
    assert "picked up #7" not in got["log"], "acme's thread is drawn in other's chat"


# ── 3. the two ends are one contract ───────────────────────────────────────────────────────────

def test_the_chat_reads_the_REAL_refusal_of_its_read_and_of_its_send(two_people):  # noqa: F811
    """The server's bytes, the page's functions: a product-only credential under a floor tab."""
    ba = {"authorization": "Bearer ba-secret"}
    read = two_people.get(MESSAGES, headers=ba)
    send = two_people.post("/api/act/ask", headers=ba,
                           json={"params": {"project": "acme", "question": "q"}})
    assert read.status_code == 403 and send.status_code == 403, (read.status_code, send.status_code)
    got = chat(f"routes={{'{MESSAGES}':[{{status:200,body:{json.dumps(THREAD)}}},"
               f"{{status:403,body:{json.dumps(read.json())}}}],"
               f"'/api/act/ask':[{{status:403,body:{json.dumps(send.json())}}}],{WHO}}};"
               "await refreshChat();nodes['#askInput'].value='q?';await askTechlead();"
               f"await settle();return {SCREEN}")
    assert read.json()["detail"] in got["note"] and send.json()["detail"] in got["log"], got
    assert got["sendOff"] and got["inputOff"]
