"""Three defects visible in the product owner's FIRST real conversation with the role, 2026-07-29.

The message they sent was "preciso que organize nosso backlog". What came back was substantively
good — it refused to invent a priority without written requirements, and gave real counts. But the
thread showed three things no audit had caught, because all three are only visible when a human
reads a real exchange:

    it answered TWICE          a channel @mention is delivered as app_mention AND message
    both answers were CUT      mid-word, at exactly 1000 characters
    it could not see the cards "tenho só os identificadores dos itens, não o texto de cada um"

The third is the one it told us itself, which is the best kind of bug report.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import add_ons

# ── A. the reply must not be truncated ──────────────────────────────────────────────────────────

class _Res:
    def __init__(self, result: str, summary: str = ""):
        self.raw_output = "\n".join([
            json.dumps({"type": "assistant", "message": "thinking"}),
            "a bare line the stream carries by design",
            json.dumps({"type": "result", "result": result}),
        ])
        self.summary = summary


def test_a_long_answer_reaches_the_client_whole():
    """`summary` is capped at 1000 chars so an operator scanning a job list gets a line, not an
    essay. A REPLY TO A PERSON needs the whole thing: both of the product owner's answers ended
    mid-word,
    and a truncated answer is worse than a short one — the reader cannot tell whether the agent
    stopped thinking or the message was cut."""
    from openfactory.product.role import _full_answer

    long = "A" * 3500
    assert _full_answer(_Res(long, summary="A" * 1000)) == long


def test_it_falls_back_to_the_summary_when_the_stream_is_unreadable():
    """Short beats truncated; truncated beats nothing, but only just."""
    from openfactory.product.role import _full_answer

    class _Bare:
        raw_output = ""
        summary = "só o resumo"

    assert _full_answer(_Bare()) == "só o resumo"


def test_the_conversational_answer_no_longer_reads_the_capped_summary():
    """Guarded at the call site: `answer()` must not go back to `res.summary` directly."""
    tree = ast.parse(Path("openfactory/product/role.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "answer")
    body = ast.unparse(fn)
    assert "_full_answer(res)" in body, "the client-facing answer is capped again"


# ── B. one human message, one reply ─────────────────────────────────────────────────────────────

def test_a_channel_mention_is_not_answered_twice():
    """Slack delivers a channel @mention as BOTH `app_mention` and `message`. The product path
    handled both: two model calls, two near-identical replies, double the cost — visible in the
    thread as "2 respostas". The product role answers plain messages by design, so dropping the
    mention twin loses nothing."""
    src = add_ons.source("openfactory/runtime/slack/bot.py").read_text()
    tree = ast.parse(src)
    handler = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
                   and "is_product_channel" in ast.unparse(n))
    body = ast.unparse(handler)
    guard = 'etype == \'app_mention\' and product_channel.is_product_channel(project, channel)'
    assert guard in body, "the app_mention twin is handled again — every mention costs twice"
    # and the guard must come BEFORE the handling branch, or it dedupes nothing
    assert body.index(guard) < body.rindex("product_channel.handle"), "the guard is too late"


# ── C. the board must carry titles ──────────────────────────────────────────────────────────────

def test_the_role_sees_card_TITLES_not_just_numbers():
    """Its own words to the client: "tenho só os identificadores dos itens, não o texto de cada
    um... não consigo dizer o que é duplicado, o que ficou obsoleto ou o que é urgente". A board
    injected as bare ids cannot support a single judgement worth making."""
    from openfactory.product.role import ProductRole

    class _Agent:
        name = "fake"

    role = ProductRole(_Agent(), board={41: "Backlog", 42: "In progress"},
                       titles={41: "Exportar balancete em PDF", 42: "Conciliação automática"})
    section = "\n".join(role._board_section())
    assert "Exportar balancete em PDF" in section
    assert "Conciliação automática" in section


def test_done_cards_are_counted_not_listed():
    """190 finished cards' titles would cost more tokens than every other column together and
    answer no question anybody asks — the token-efficiency claim is not a slogan."""
    from openfactory.product.role import ProductRole

    class _Agent:
        name = "fake"

    role = ProductRole(_Agent(), board={n: "Done" for n in range(1, 191)},
                       titles={n: f"Entrega {n}" for n in range(1, 191)})
    section = "\n".join(role._board_section())
    assert "190" in section and "Entrega 1" not in section


def test_a_card_with_no_title_still_appears():
    """A missing title must lose the title, never the card."""
    from openfactory.product.role import ProductRole

    class _Agent:
        name = "fake"

    section = "\n".join(ProductRole(_Agent(), board={7: "Backlog"}, titles={})._board_section())
    assert "#7" in section


# ── A, at the ROOT: every path that reads a harness result, not just the chatty one ─────────────

def test_EVERY_reader_of_a_harness_result_gets_the_full_text():
    """The product owner's instruction, and the reason it mattered here: *"always go and fix the
    ROOT cause, remembering that we are in a pilot and this will be scaled to N clients."*

    The first fix patched `answer()` — the path whose symptom he could SEE (a reply ending
    mid-word). The cap applies to four more callers, and all four parse JSON out of that text:
    `draft`, `issues_for`, `survey`, `_ask_json`. Truncated JSON does not read as truncated: the
    parse fails and the role says "não consegui", with nothing anywhere reporting that the output
    was cut rather than wrong. A requirement long enough to matter, or a breakdown into more than
    a few issues, hits it — on a client with a real backlog that is the normal case, not an edge.

    So the guard is on the MODULE, not on one function: nothing here may read `res.summary`
    except the fallback inside `_full_answer` and the failure-reason formatter."""
    src = Path("openfactory/product/role.py").read_text()
    tree = ast.parse(src)

    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if fn.name in ("_full_answer", "_failure_reason"):
            continue  # the one legitimate fallback, and the error formatter
        body = ast.unparse(fn)
        if "res.summary" in body or ".summary or" in body:
            offenders.append(fn.name)
    assert not offenders, (
        f"these read the 1000-char capped summary directly: {offenders}. Use _full_answer(res) — "
        f"four of them parse JSON out of it, where a cap is a silent parse failure."
    )


def test_a_long_JSON_payload_survives_the_read():
    """The severe symptom, reproduced: a payload longer than the cap must come back parseable."""
    import json as _json

    from openfactory.product.role import _full_answer

    payload = _json.dumps({"issues": [{"title": f"Issue {i}", "why": "x" * 60}
                                      for i in range(30)]})
    assert len(payload) > 1000
    got = _full_answer(_Res(payload, summary=payload[:1000]))
    assert _json.loads(got), "the payload came back truncated — the parse would have failed"
