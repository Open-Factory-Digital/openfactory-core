"""The product chat shows a whole conversation, a page at a time, read by its key (#566).

A person's conversation of fourteen turns and 9,253 characters, reopened on the panel, began at
its eleventh turn: the page's catch-up read `transcript.recent`, the PROMPT's read — the newest
turns within 6,000 characters, out of the project's last 300 rows of every conversation — so two
replies that carried a card filled it, and the four turns where the requirement was worked out
were unreachable. `product_thread`, the CLI's view, read the same way.

Now the page and the row read `transcript.page`: the conversation's newest page and the cursor to
the one before it, through the store's `TicketReadingSink` — the conversation by its key, never
found by walking the project's recent rows. The prompt keeps its character budget.

RUN AGAINST THE REAL STORE: the SQLite metrics sink the open distribution ships, written through
`transcript.record`, as a turn writes it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.memory import transcript
from openfactory.product.key import product_key
from tests.test_one_memory_per_product import _project, registry, store  # noqa: F401
from tests.test_the_panel_is_a_chat import chat  # noqa: F401 — the socket's fixture

THREAD = "person:ana"


@pytest.fixture
def books(monkeypatch, tmp_path) -> Project:
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    project = Project(name="books", repo_path="/work/books", language="en",
                      tracker=ProviderRef(kind="local", repo="books", options={}),
                      product=ProductConfig(docs_repo="acme/books-docs", admins=["ana"],
                                            agent_name="Nina"))
    ProjectRegistry().add(project)
    return project


#: When the first turn of a test is said: an hour ago, so every row is inside its retention.
SAID_FROM = datetime.now(UTC) - timedelta(hours=1)


def _said(project, thread: str, n: int, *, size: int = 1000, prefix: str = "turn",
          start: int = 0) -> list[str]:
    """`n` turns of `size` characters in `thread`, alternating the person and the role, said a
    second apart from `start` seconds after `SAID_FROM`.

    STAMPED WHEN SAID (`at`), as every turn that arrives is (`engine.Message.at`, #394), never by
    the clock of the write: this machine's wall clock stepped back 89 ms every 30 s under the
    suite's load (measured, 2026-10-10), and forty writes a few milliseconds apart then came back
    in the clock's order — which is the clock's question, not the page's."""
    texts = []
    for i in range(n):
        text = f"{prefix} {i:03d} " + "x" * (size - len(prefix) - 5)
        role = "person" if i % 2 == 0 else "agent"
        at = (SAID_FROM + timedelta(seconds=start + i)).isoformat()
        assert transcript.record(project, thread=thread, role=role, text=text, at=at,
                                 actor="ana" if role == "person" else "")
        texts.append(text)
    return texts


def _every_page(project, thread: str, *, limit: int) -> list[list[str]]:
    """Every page, newest first, following each cursor to the start — or failing, never hanging,
    when a cursor leads back to a page already read."""
    pages, before = [], ""
    while len(pages) < 100:
        turns, before = transcript.page(project, thread=thread, before=before, limit=limit)
        pages.append([t.text for t in turns])
        if not before:
            return pages
    raise AssertionError(f"the cursor never reached the start: {pages[:3]}")


def test_forty_turns_of_a_thousand_characters_are_all_shown_across_pages(books):
    written = _said(books, THREAD, 40)

    pages = _every_page(books, THREAD, limit=15)

    assert [len(p) for p in pages] == [15, 15, 10], "each page is the next older one"
    assert [t for p in reversed(pages) for t in p] == written, "a turn was lost or repeated"


def test_the_prompts_read_keeps_its_budget(books):
    """THE PROMPT IS NOT THE PAGE: what a turn is handed stays within 6,000 characters."""
    _said(books, THREAD, 40)

    remembered = transcript.recent(books, thread=THREAD)

    assert sum(len(t.text) for t in remembered) <= transcript.DEFAULT_BUDGET
    assert len(remembered) < 40


def test_a_conversation_older_than_the_projects_last_rows_still_opens_whole(books, monkeypatch):
    """READ BY ITS KEY, NOT FOUND BY WALKING: 400 newer turns in another conversation of the
    product pushed this one out of the 300 rows a thread was looked for in — and the store that
    can read a conversation by its key is asked for it, never walked."""
    written = _said(books, THREAD, 25, size=200)
    _said(books, "person:bruno", 400, size=50, prefix="later", start=100)

    with monkeypatch.context() as walk:
        def _walked(*_a, **_k):
            raise AssertionError("the conversation was found by walking the product's rows")

        walk.setattr(transcript, "rows", _walked)
        pages = _every_page(books, THREAD, limit=40)

    assert pages == [written], "an older conversation opened cut short, or empty"
    assert transcript.recent(books, thread=THREAD) == [], (
        "the walk this replaces would have found it after all — the test no longer measures it")


def test_a_store_that_cannot_read_by_key_is_walked_and_still_paged(books, monkeypatch):
    """`TicketReadingSink` is a capability a store declares; one added from outside without it is
    read by a wider walk, and pages the same."""
    from openfactory.observability import registry as sinks
    from openfactory.observability.metrics import TicketReadingSink

    real = sinks.deployment_metrics_sink()

    class _Walked:
        def scan(self):
            return real.scan()

        def records_of_kind(self, project, kind, *, limit=500):
            return real.records_of_kind(project, kind, limit=limit)

    assert not isinstance(_Walked(), TicketReadingSink)
    written = _said(books, THREAD, 12)
    _said(books, "person:bruno", 3, prefix="other", start=100)
    monkeypatch.setattr(sinks, "deployment_metrics_sink", lambda: _Walked())

    pages = _every_page(books, THREAD, limit=5)

    assert [t for p in reversed(pages) for t in p] == written


def test_the_page_reads_the_PRODUCT_s_memory_by_the_one_rule_of_every_read(store,  # noqa: F811
                                                                           registry):  # noqa: F811
    """ADR-0051 D2 holds on the page as on the prompt: the rows a member wrote under its own name
    before the move are read through, and a project of ANOTHER product that is named like this
    product's key — so writes its old rows into this partition — is not read."""
    from openfactory.registry import ProjectRegistry

    books = registry["books"]
    impostor = _project(product_key(books), "acme/elsewhere")
    ProjectRegistry().add(impostor)
    said = [(SAID_FROM + timedelta(seconds=s)).isoformat() for s in range(3)]
    transcript.record("books-api", thread="sala", role="person", text="antes, da api", actor="ana",
                      at=said[0])
    transcript.record(impostor.name, thread="sala", role="person", text="de outro cliente",
                      at=said[1])
    transcript.record(books, thread="sala", role="agent", text="depois", at=said[2])

    for limit in (1, 40):
        pages = _every_page(registry["books-api"], "sala", limit=limit)
        assert [t for p in reversed(pages) for t in p] == ["antes, da api", "depois"], limit


def test_the_page_catch_up_is_the_newest_page_and_its_cursor(books, monkeypatch):
    from openfactory.api import product_chat

    monkeypatch.setattr(transcript, "PAGE_TURNS", 10)
    written = _said(books, THREAD, 25, size=100)

    newest, earlier = product_chat._history(books, THREAD, "ana")
    older, before = product_chat._history(books, THREAD, "ana", before=earlier)

    assert [t["text"] for t in newest] == written[-10:] and earlier
    assert [t["text"] for t in older] == written[-20:-10] and before
    assert [t["mine"] for t in newest[:2]] == [False, True], "who said it is still read"


def test_product_thread_pages_by_the_cursor_it_hands_back(books, monkeypatch):
    import asyncio

    from openfactory import actions
    from openfactory.actions import catalog

    monkeypatch.setattr(transcript, "PAGE_TURNS", 10)
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (object(), books, None))
    written = _said(books, THREAD, 15, size=100)
    ana = actions.Actor(id="ana", display="Ana", via="cli", admin=True, conversation=THREAD)

    first = asyncio.run(actions.perform("product_thread", by=ana, project="books"))
    second = asyncio.run(actions.perform("product_thread", by=ana, project="books",
                                         before=first.data["earlier"]))

    assert [t["text"] for t in first.data["turns"]] == written[-10:]
    assert f"before={first.data['earlier']}" in first.message
    assert [t["text"] for t in second.data["turns"]] == written[:5]
    assert second.data["earlier"] == ""


def test_the_page_asks_for_the_page_before_and_puts_it_above():
    """The panel's half: the catch-up's cursor is kept, a button at the top asks for the page
    before it over the same socket, and the answer is put above what is shown."""
    from pathlib import Path

    html = (Path(__file__).resolve().parent.parent / "openfactory/api/panel.html").read_text()
    assert html.count('_pc.earlier=m.earlier||"";') == 2, "the catch-up's cursor, or a page's"
    assert 'onclick="pchatEarlier()"' in html
    assert 's.send(JSON.stringify({kind:"earlier",before:_pc.earlier}))' in html
    assert 'else if(m.kind==="earlier")' in html and "_pc.items=older.concat(_pc.items)" in html
    assert "?earlier+_pc.items.map(pvMsg)" in html, "the button is built and never drawn"


def test_the_socket_hands_the_newest_page_and_answers_for_the_one_before(chat,  # noqa: F811
                                                                          monkeypatch):
    """END TO END OVER THE PANEL'S SOCKET: subscribing hands the newest page and the cursor of
    the one before; asking `earlier` with it answers that page, for the conversation subscribed —
    and the last page says there is nothing before it."""
    from fastapi.testclient import TestClient

    from openfactory.api import app as api
    from tests.test_the_panel_is_a_chat import ANA, _open, subscribe, until

    room = [transcript.Turn(role="person", text=f"linha {i:02d}", ts=f"t{i:02d}", actor="ana")
            for i in range(25)]

    def page(project, *, thread, before="", limit=None):
        upto = int(before) if before else len(room)
        start = max(0, upto - 10)
        return room[start:upto], (str(start) if start else "")

    monkeypatch.setattr(transcript, "page", page)

    with TestClient(api.app) as client, _open(client, ANA) as ana:
        history = subscribe(ana, room=True)[-1]
        assert [t["text"] for t in history["turns"]] == [f"linha {i:02d}" for i in range(15, 25)]
        assert history["earlier"] == "15"

        ana.send_json({"kind": "earlier", "before": history["earlier"]})
        older = until(ana, lambda f: f["kind"] == "earlier")[-1]
        assert [t["text"] for t in older["turns"]] == [f"linha {i:02d}" for i in range(5, 15)]

        ana.send_json({"kind": "earlier", "before": older["earlier"]})
        first = until(ana, lambda f: f["kind"] == "earlier")[-1]
        assert [t["text"] for t in first["turns"]] == [f"linha {i:02d}" for i in range(0, 5)]
        assert first["earlier"] == "", "the start of the conversation still offers a page before"
