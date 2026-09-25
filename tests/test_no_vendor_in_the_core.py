"""A core without a vendor, and a role that answers only what is addressed to it — #266 slice 6.

ADR-0051 D16 and D14, decisions 3 and 6. What this file holds, in the brief's order:

  1. AN EXISTING CONFIGURATION STILL LOADS AND SAYS WHAT CHANGED. The keys a chat vendor named —
     its channel coordinate, its admin list, its two bot tokens — are read as aliases for one minor
     version, each named once, by name, at WARNING; an alias moves a value and never widens what
     the new spelling says; and an old coordinate no longer chooses the channel.
  2. PEOPLE, NOT A VENDOR'S USER IDS. Product writes are authorised by the person the platform
     knows. A chat add-on maps its own users to people through its port
     (`adapters/channel/base.py::PeopleOfAChannel`), asked at the chat adapter's door; a user it
     cannot name is a guest, who may write nothing; and nothing the core writes wears a vendor's
     mention syntax any more.
  3. ADDRESSING IN A GROUP. The core's definition (`product/addressing.py`): a mention, a reply
     inside a conversation the role takes part in, a direct conversation — each starts a turn, on
     the conversation workflow as it ships. Anything else is kept: recorded, found by recall,
     starting no turn, joining nobody's, and never in a prompt.
  4. THE WHOLE CONVERSATION WITH NO ADD-ON INSTALLED — the panel and the CLI, through the door, on
     an engine of its own, with every add-on hidden and any attempt to build a channel refused.

The vendor-name guard itself is `tests/test_the_core_names_no_vendor.py`.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import time

import pytest
import yaml
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

import openfactory.memory.store as loop_store
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.memory import transcript
from openfactory.memory.transcript import TRANSCRIPT_KIND
from openfactory.product import addressing, door, engine, speaker, staging, voice
from openfactory.product.engine import Message, Reply
from openfactory.product.key import product_key
from openfactory.product.module import may_act
from openfactory.registry import ProjectRegistry
from openfactory.runtime.temporal import TASK_QUEUE
from openfactory.runtime.temporal.activities import (
    conversation_overheard,
    conversation_report,
    conversation_turn,
)
from openfactory.runtime.temporal.conversation import ConversationWorkflow
from openfactory.runtime.temporal.io import TurnInput
from tests.test_the_conversation_is_pinned import PLAIN, REQUEST, _asking, _Module
from tests.test_the_one_door import _Worker
from tests.the_sink_door import SINK_DOOR

#: THIS FILE STARTS ITS OWN ENGINE for the conversation's tests, like `test_the_one_door`.
pytestmark = pytest.mark.owns_its_engine

REGISTRY_LOG = "openfactory.registry"
LANG, AGENT = "pt-BR", "Nina"
ANA, BIA = "ana@acme.example", "bia@acme.example"
QUICK = door.Settings(debounce_seconds=0.2, bound_seconds=10.0)


def _project(name: str = "books", **product) -> Project:
    return Project(name=name, repo_path=f"/work/{name}", language=LANG,
                   product=ProductConfig(docs_repo="acme/books-docs", agent_name=AGENT,
                                         **({"admins": [ANA]} | product)))


class _Table:
    """The append-only telemetry table, in memory, behind the write AND the read."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record(self, rec) -> bool:
        self.rows.append({"project": rec.project, "kind": rec.kind, "ticket": rec.ticket,
                          "role": rec.role, "ts": rec.ts, "extra": dict(rec.extra)})
        return True

    def of_kind(self, project, kind, limit=500, **_kw) -> list[dict]:
        rows = [r for r in self.rows if r["project"] == project and r["kind"] == kind]
        return sorted(rows, key=lambda r: str(r["ts"]))[-limit:]

    def said(self, text: str) -> list[dict]:
        return [r for r in self.rows if r["kind"] == TRANSCRIPT_KIND
                and r["extra"].get("text") == text]


@pytest.fixture
def table(monkeypatch, tmp_path) -> _Table:
    """The product's memory in one in-memory table, and its recall index in this test's own
    directory."""
    t = _Table()
    monkeypatch.setattr(SINK_DOOR, lambda *a, **k: t)
    monkeypatch.setattr("openfactory.observability.query.records_of_kind", t.of_kind)
    monkeypatch.setattr("openfactory.paths.project_memory_dir", lambda p: tmp_path / "mem")
    return t


@pytest.fixture
def ledger(monkeypatch) -> list:
    """The loop ledger as a list, append-only like the real one."""
    rows: list = []
    monkeypatch.setattr(loop_store, "read", lambda project: list(rows))
    monkeypatch.setattr(loop_store, "write", lambda project, loops: rows.extend(loops))
    return rows


def _registry_file(tmp_path, projects: dict) -> ProjectRegistry:
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({"projects": projects}))
    return ProjectRegistry(path)


def _deprecations(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.name == REGISTRY_LOG and "OPENFACTORY_DEPRECATED_KEY" in r.getMessage()
            and r.levelno == logging.WARNING]


# ── 1. an existing configuration with the old keys loads, and warns once, by name ───────────────

OLD = {"name": "books", "repo_path": "/t",
       "slack_channel": "C0OPS", "slack_admins": ["U0OPS"],
       "slack_bot_token_env": "BOT_TOKEN_BOOKS", "slack_app_token_env": "APP_TOKEN_BOOKS",
       "product": {"docs_repo": "acme/books-docs", "slack_channel": "C0PROD",
                   "slack_admins": ["U0ANA"]}}


def test_an_existing_configuration_with_the_old_keys_loads_and_warns_once_by_name(tmp_path,
                                                                                   caplog):
    """Decision 6: the old keys are read as aliases, with a deprecation warning, for one minor
    version. Every value lands where it lives now; every old key is named — at WARNING, since
    it will stop being read — and named ONCE, however many times the registry is read."""
    reg = _registry_file(tmp_path, {"books": OLD,
                                    "shop": {"name": "shop", "repo_path": "/s",
                                             "channel_id": "C0SHOP"}})
    with caplog.at_level(logging.WARNING, logger=REGISTRY_LOG):
        books = next(p for p in reg.list() if p.name == "books")
        shop = reg.get("shop")

    assert books.channel_options == {"channel": "C0OPS", "bot_token_env": "BOT_TOKEN_BOOKS",
                                     "app_token_env": "APP_TOKEN_BOOKS"}
    assert books.admins == ["U0OPS"]
    assert books.product.channel_options == {"channel": "C0PROD"}
    assert books.product.admins == ["U0ANA"]
    assert shop.channel_options == {"channel": "C0SHOP"}

    said = _deprecations(caplog)
    for old in ("'slack_channel'", "'slack_admins'", "'slack_bot_token_env'",
                "'slack_app_token_env'", "'product.slack_channel'", "'product.slack_admins'",
                "'channel_id'"):
        assert sum(old in line for line in said) == 1, (old, said)
    assert all("deprecated" in line and "0.5.0" in line for line in said), said

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=REGISTRY_LOG):
        reg.list()
        reg.get("books")
    assert _deprecations(caplog) == [], "an old key was named again — once is the promise"


def test_an_alias_never_grants_more_than_the_new_spelling_says(tmp_path, caplog):
    """THE NEW SPELLING WINS, AND THE TWO ARE NEVER MERGED. An old admin list beside a new one is
    ignored — and said to be — rather than added to it: a merge would let a stale line in a file
    nobody reviews widen who may write. An explicitly EMPTY new list still means nobody."""
    reg = _registry_file(tmp_path, {
        "books": {"name": "books", "repo_path": "/t",
                  "product": {"docs_repo": "a/b", "admins": [ANA],
                              "slack_admins": [ANA, "U0INTRUDER"]}},
        "shop": {"name": "shop", "repo_path": "/s",
                 "product": {"docs_repo": "a/s", "admins": [], "slack_admins": ["U0INTRUDER"]}}})
    with caplog.at_level(logging.WARNING, logger=REGISTRY_LOG):
        books, shop = reg.get("books"), reg.get("shop")

    assert books.product.admins == [ANA]
    assert shop.product.admins == []
    assert not may_act(books, "U0INTRUDER") and not may_act(shop, "U0INTRUDER")
    assert may_act(books, ANA)
    said = _deprecations(caplog)
    assert any("'product.slack_admins'" in line and "IGNORED" in line for line in said), said


def test_an_old_coordinate_no_longer_chooses_the_channel(tmp_path, caplog):
    """THE INFERENCE IS GONE (ADR-0051 D16). A project that carries an old chat coordinate and
    declares no `channel:` talks through the panel — and the warning says how to keep it on its
    add-on. One that declares its channel keeps it, the coordinate becoming the add-on's own
    option, handed back to it without being read."""
    from openfactory.adapters.channel.registry import channel_destination, channel_kind

    reg = _registry_file(tmp_path, {
        "books": {"name": "books", "repo_path": "/t", "slack_channel": "C0OPS"},
        "shop": {"name": "shop", "repo_path": "/s", "channel": "chat", "channel_id": "C0SHOP"}})
    with caplog.at_level(logging.WARNING, logger=REGISTRY_LOG):
        books, shop = reg.get("books"), reg.get("shop")

    assert channel_kind(books) == "panel"
    assert channel_kind(shop) == "chat" and channel_destination(shop) == "C0SHOP"
    said = _deprecations(caplog)
    books_line = next(line for line in said if "'books'" in line)
    shop_line = next(line for line in said if "'shop'" in line)
    assert "`channel: <kind>`" in books_line and "`channel: <kind>`" not in shop_line


def test_a_write_leaves_only_the_new_spellings(tmp_path):
    """Self-migrating, as C-08 was: anything the registry writes back uses the new places, so the
    old keys drain away rather than needing a flag day."""
    reg = _registry_file(tmp_path, {"books": OLD})
    reg.add(Project(name="other", repo_path="/o"))
    written = yaml.safe_load((tmp_path / "registry.yaml").read_text())["projects"]["books"]
    assert not {k for k in written if k.startswith("slack_")} and "channel_id" not in written
    assert written["channel_options"]["channel"] == "C0OPS"
    assert written["product"]["channel_options"] == {"channel": "C0PROD"}
    assert not {k for k in written["product"] if k.startswith("slack_")}


# ── 2. product admins are people of the platform ────────────────────────────────────────────────

class _People:
    """An add-on's answer to who its users are — `PeopleOfAChannel`, from a table it keeps."""

    def __init__(self, known: dict[str, str] | None = None, *, breaks: bool = False) -> None:
        self.known = dict(known or {})
        self.breaks = breaks
        self.asked: list[tuple[str, str]] = []

    def person_of(self, user, *, project):
        self.asked.append((user, project.name))
        if self.breaks:
            raise RuntimeError("the directory is down")
        return self.known.get(user, "")


def test_a_product_write_is_authorised_by_the_person_never_by_a_vendor_id():
    project = _project()
    assert may_act(project, ANA)
    assert not may_act(project, "U0ANA"), "a vendor's id is not a person of this product"


def test_the_port_is_a_protocol_an_add_on_implements_by_shape():
    from openfactory.adapters.channel import PeopleOfAChannel

    assert isinstance(_People(), PeopleOfAChannel)
    assert not isinstance(object(), PeopleOfAChannel)


def test_the_chat_adapter_turns_its_user_into_a_person_before_the_door(monkeypatch):
    """THE ADD-ON'S USER NEVER REACHES THE CORE. `handle` asks the add-on's port who the user is,
    and the message the door is handed carries that person — with the add-on's own name, what it
    detected, and its conversation's keys, and no trace of the vendor's id."""
    from openfactory.product import channel as pc

    sent: list[Message] = []
    monkeypatch.setattr("openfactory.product.door.say",
                        lambda project, message, notify=None: sent.append(message) or [
                            Reply(text="resposta", in_reply_to=message.id)])
    people = _People({"U0ANA": ANA})

    said = pc.handle(_project(), text="@nina e o PDF?", user="U0ANA", conversation="T1",
                     room="C0PROD", people=people, via="chat", mentioned=True,
                     in_reply_to="m0", message_id="m1-chat-0001")

    assert said == "resposta"
    [message] = sent
    assert (message.speaker, message.via, message.mentions_role, message.direct) == (
        ANA, "chat", True, False)
    assert (message.conversation, message.room, message.in_reply_to, message.id) == (
        "T1", "C0PROD", "m0", "m1-chat-0001")
    assert "U0ANA" not in message.model_dump_json()
    assert people.asked == [("U0ANA", "books")]


@pytest.mark.parametrize("people", [_People(), _People(breaks=True), object()],
                         ids=["unknown", "port-raises", "no-port"])
def test_a_user_the_add_on_cannot_name_is_a_guest_who_may_write_nothing(people):
    """"" from the port, a port that raises, and an add-on with no port at all: each makes the
    user a GUEST — told apart from every other guest, so two people's words are never one turn;
    carrying no vendor id; and refused every write, even by a list that names the guest."""
    project = _project()
    one = speaker.of_channel(people, "U0ONE", project=project, via="chat")
    two = speaker.of_channel(people, "U0TWO", project=project, via="chat")

    assert speaker.is_guest(one) and speaker.is_guest(two) and one != two
    assert "U0ONE" not in one
    listed = _project(admins=[ANA, one])
    assert not may_act(listed, one), "a guest wrote because a list happened to spell it"


def test_a_kept_message_posts_nothing_into_a_chat_room(monkeypatch):
    """A line the people in a room said to each other is acknowledged to nobody on a chat: the
    door's word that it was kept is for its sender, and `notify` posts into the room — so the
    adapter says nothing at all, and returns nothing to post."""
    from openfactory.product import channel as pc

    async def _kept(message, *, project=None, acknowledged=None, **_kw):
        ack = door.Ack(accepted=True, id=message.id, state=door.OVERHEARD,
                       text=voice.overheard(language=LANG, agent_name=AGENT))
        acknowledged(ack)
        return ack, []

    monkeypatch.setattr(door, "converse", _kept)
    posted: list[str] = []
    said = pc.handle(_project(), text="bom dia, pessoal", user="U0BIA", conversation="C0ROOM",
                     people=_People({"U0BIA": BIA}), via="chat", notify=posted.append)
    assert said is None and posted == []


def test_a_click_on_a_chat_add_on_is_authorised_as_the_person_it_names(monkeypatch):
    from openfactory.product import channel as pc

    asked: list[dict] = []
    monkeypatch.setattr(pc, "answer_staged",
                        lambda project, **kw: asked.append(kw) or ("done", "feito"))

    pc.confirm_by_click(_project(), token="t", approved=True, user="U0ANA",
                        people=_People({"U0ANA": ANA}), via="chat")
    pc.confirm_by_click(_project(), token="t", approved=True, user="U0NOBODY",
                        people=_People(), via="chat")

    assert (asked[0]["user"], asked[0]["via"]) == (ANA, "chat")
    assert speaker.is_guest(asked[1]["user"])


def test_nothing_the_core_writes_wears_a_vendor_mention():
    """`asked_by`, `accepted_by`, a closing note, the admins named under a proposal: they named
    the person in one chat vendor's mention syntax, which #279 noted. No string the core BUILDS
    carries it now; reading one an older row still carries (`.strip("<@>")`) is how a row staged
    before is read the same way, and is the only form left."""
    from pathlib import Path

    found = []
    for path in sorted(Path("openfactory").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        prose = {id(n.value) for n in ast.walk(tree)
                 if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                literal = "".join(v.value for v in node.values
                                  if isinstance(v, ast.Constant) and isinstance(v.value, str))
                if "<@" in literal:
                    found.append(f"{path}:{node.lineno}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in prose and "<@" in node.value and node.value != "<@>":
                found.append(f"{path}:{node.lineno}")
    assert not found, "the core builds a vendor's mention again:\n  " + "\n  ".join(found)


def test_the_admins_named_under_a_proposal_are_named_as_people():
    from openfactory.product.engine import _admin_mentions

    project = _project(admins=[ANA, BIA], accept_on_behalf=True)
    assert _admin_mentions(project) == f"{ANA} {BIA}"


def test_a_draft_records_who_asked_as_the_person(table, ledger):
    """What a turn stages says who asked by the person's id — the value the requester's own yes
    is compared with, and what the requirement file will name."""
    project = _project(admins=[ANA])
    module = _asking(project)
    staging._PENDING.clear()
    try:
        engine.turn(project, Message(project="books", conversation="person:bia", speaker=BIA,
                                     text=REQUEST, mentions_role=True), module=module)
        _key, staged = staging.find_waiting("person:bia", "person:bia", person=BIA)
    finally:
        staging._PENDING.clear()
    assert staged is not None and staged["asked_by"] == BIA and staged["requester"] == BIA
    assert module.asked("draft") == [{"request": REQUEST, "asked_by": BIA}]


# ── 3. what "addressed to the role" means ───────────────────────────────────────────────────────

@pytest.mark.parametrize("direct, mentioned, in_reply_to, takes_part, why", [
    (True, False, "", False, addressing.DIRECT),
    (False, True, "", False, addressing.MENTION),
    (False, False, "m1", True, addressing.REPLY),
    (False, False, "m1", False, ""),
    (False, False, "", True, ""),
    (False, False, "", False, ""),
], ids=["direct", "mention", "reply-where-it-takes-part", "reply-elsewhere",
        "not-a-reply", "nothing"])
def test_the_cores_one_definition(direct, mentioned, in_reply_to, takes_part, why):
    assert addressing.why_addressed(direct=direct, mentioned=mentioned, in_reply_to=in_reply_to,
                                    takes_part=takes_part) == why


def test_a_private_conversation_is_a_direct_one_whatever_the_transport_said():
    assert door.is_direct(Message(project="books", conversation="person:ana", text="x"))
    assert door.is_direct(Message(project="books", conversation="D0ANA", text="x", direct=True))
    assert not door.is_direct(Message(project="books", conversation="books", text="x"))


@pytest.mark.parametrize("text, mentioned", [
    ("@Nina, o extrato fecha no dia 5?", True),
    ("e aí @nína?", True),
    ("@po quanto custa?", True),
    ("pergunta pro @product", True),
    ("a Nina disse que fecha no dia 5", False),
    ("manda para po@acme.example", False),
    ("@ninaaa oi", False),
    ("bom dia, pessoal", False),
], ids=["name", "accents-and-case", "po", "product", "talking-about", "an-address",
        "a-longer-word", "chatter"])
def test_the_panels_room_detects_a_mention_its_own_way(text, mentioned):
    """The one part of D14 that is the transport's: the panel reads `@` and the role's name, or
    `@po` / `@product`, as a whole word — a room talking ABOUT the role is not talking TO it."""
    from openfactory.api.product_chat import mentions_the_role

    assert mentions_the_role(text, _project()) is mentioned


def test_the_ask_button_names_the_role_in_words_the_room_can_see():
    """The product page's "Ask" is a question to the role: in the room it writes the mention into
    the message itself — so everybody reading sees who it was for, and the server reads it from the
    words like any other — unless the words already name the role; in a person's own conversation
    it adds nothing, because everything there is for the role."""
    from tests.test_the_panel_is_a_chat import _run

    got = _run("""nodes['#prodAsk']=node();nodes['#prodThread']=node();
      _pc.sock={readyState:1,send(x){sent.push(JSON.parse(x))}};_pc.live=true;_pc.project='books';
      _pc.room=true;nodes['#prodAsk'].value='e o PDF?';askProduct();
      nodes['#prodAsk'].value='@Product já pedi';askProduct();
      _pc.room=false;nodes['#prodAsk'].value='só eu';askProduct();
      return sent.map(s=>s.text)""", pathname="/product/books")
    assert got == ["@po e o PDF?", "@Product já pedi", "só eu"]


async def test_the_row_says_the_role_was_named_unless_its_transport_says_otherwise(monkeypatch):
    """`product_say` IS the role's own row, so calling it names the role — the CLI's `product say`
    and every direct caller. The panel's room is the one caller that knows better, and says so."""
    from openfactory import actions
    from openfactory.actions import catalog
    from openfactory.actions.base import Actor

    sent: list[Message] = []

    async def _receive(message, *, project=None, client=None, settings=None):
        sent.append(message)
        return door.Ack(accepted=True, id=message.id, state=door.QUEUED)

    async def _connected():
        return object(), None

    project = _project()
    monkeypatch.setattr(door, "receive", _receive)
    monkeypatch.setattr(catalog, "_connected", _connected)
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (object(), project, None))
    cli = Actor(id="ana", via="cli", admin=True)
    for mentioned in (None, "false", "true"):
        await actions.perform("product_say", by=cli, project="books", message="oi",
                              wait="false", **({} if mentioned is None else
                                               {"mentioned": mentioned}))
    assert [m.mentions_role for m in sent] == [True, False, True]


# ── 3b. on the conversation workflow, as it ships ───────────────────────────────────────────────

@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


@pytest.fixture
def books(monkeypatch, tmp_path, table) -> Project:
    """One registry project with a product role, in a registry of this test's own — the one the
    REAL keeping activity and the REAL turn read — and the product's memory in the table."""
    path = tmp_path / "registry.yaml"
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(path))
    project = _project(admins=[ANA, BIA])
    ProjectRegistry(path).add(project)
    return project


def _kept_worker(env, w: _Worker) -> Worker:
    """The worker's side: the turns stood in for (`_Worker`, recording what is turned), and the
    REAL activity that keeps what is not addressed to the role."""
    turn, fast, _stand_in, report = w.activities()
    return Worker(env.client, task_queue=TASK_QUEUE, workflows=[ConversationWorkflow],
                  activities=[turn, fast, conversation_overheard, report])


def _said(text: str, *, speaker_: str = BIA, conversation: str = "books", mentioned=False,
          in_reply_to: str = "", direct: bool = False) -> Message:
    return Message(project="books", conversation=conversation, speaker=speaker_, text=text,
                   via="panel", mentions_role=mentioned, in_reply_to=in_reply_to,
                   direct=direct)


async def _until(ready, *, within: float = 10.0) -> None:
    deadline = time.monotonic() + within
    while not ready():
        if time.monotonic() > deadline:
            raise AssertionError("waited and it never happened")
        await asyncio.sleep(0.02)


async def _settled(env, ack: door.Ack) -> dict:
    stands = {}
    for _ in range(200):
        stands = await env.client.get_workflow_handle(ack.workflow_id).query("where", ack.id)
        if stands["state"] in ("answered", "overheard"):
            return stands
        await asyncio.sleep(0.05)
    raise AssertionError(f"{ack.id} never settled: {stands}")


async def test_a_room_message_not_addressed_to_the_role_is_KEPT_and_starts_no_turn(env, books,
                                                                                    table):
    """Decision 3. In the project's room, a line the people there say to each other is heard —
    the room's members see it — and KEPT in the product's memory, marked; it starts no turn, is
    answered by nothing, and its sender is told, alone, that it stayed with the room."""
    w = _Worker()
    async with _kept_worker(env, w):
        ack = await door.receive(_said("alguém viu o relatório de ontem?"), project=books,
                                 client=env.client, settings=QUICK)
        assert ack.accepted and ack.state == door.OVERHEARD
        assert ack.text == voice.overheard(language=LANG, agent_name=AGENT)
        await _until(lambda: bool(table.said("alguém viu o relatório de ontem?")))
        stands = await _settled(env, ack)
        watched = await door.watch(env.client, ack.workflow_id, 0)

    assert stands == {"state": "overheard", "ahead": 0, "coalesced": False, "duplicate": False,
                      "replies": []}
    assert w.turns == [] and w.fast == [], "a message nobody addressed to the role took a turn"
    [row] = table.said("alguém viu o relatório de ontem?")
    assert row["extra"]["addressed"] is False and row["ticket"] == "books"
    assert row["extra"]["actor"] == BIA and row["project"] == product_key(books)
    heard = [e for e in watched["entries"] if e["type"] == "said"]
    assert heard and heard[0]["overheard"] is True


async def test_a_MENTION_starts_a_turn(env, books, table):
    w = _Worker()
    async with _kept_worker(env, w):
        ack = await door.receive(_said("@nina o relatório fecha no dia 5?", mentioned=True),
                                 project=books, client=env.client, settings=QUICK)
        await _settled(env, ack)
    assert [t["text"] for t in w.turns] == ["@nina o relatório fecha no dia 5?"]


async def test_a_DIRECT_conversation_starts_a_turn_without_a_mention(env, books, table):
    w = _Worker()
    async with _kept_worker(env, w):
        ack = await door.receive(_said("o relatório fecha no dia 5?", conversation="person:bia"),
                                 project=books, client=env.client, settings=QUICK)
        await _settled(env, ack)
    assert [t["text"] for t in w.turns] == ["o relatório fecha no dia 5?"]


async def test_a_REPLY_inside_a_conversation_the_role_takes_part_in_starts_a_turn(env, books,
                                                                                  table):
    """A thread the role was brought into by a mention: a reply written there after it — while
    the role is still answering, even — is to the role, with no mention of its own. A reply in a
    thread the role never took part in is kept."""
    w = _Worker()
    released = w.hold("devagar")
    async with _kept_worker(env, w):
        first = await door.receive(_said("@nina devagar: e o PDF?", conversation="T1",
                                         mentioned=True),
                                   project=books, client=env.client, settings=QUICK)
        await _until(lambda: w.started("@nina devagar: e o PDF?"))
        reply = await door.receive(_said("é o do extrato mensal", conversation="T1",
                                         speaker_=ANA, in_reply_to=first.id),
                                   project=books, client=env.client, settings=QUICK)
        elsewhere = await door.receive(_said("isso é com o financeiro", conversation="T2",
                                             in_reply_to="m-de-outra-pessoa"),
                                       project=books, client=env.client, settings=QUICK)
        released.set()
        await _settled(env, reply)
        assert (await _settled(env, elsewhere))["state"] == "overheard"
    assert [t["text"] for t in w.turns] == ["@nina devagar: e o PDF?", "é o do extrato mensal"]


async def test_a_reply_where_the_products_memory_holds_the_role_speaking_starts_a_turn(
        env, books, table):
    """A conversation the role spoke in before this workflow ever ran — a thread from before a
    restart, a room it posted in — is one it takes part in: the door reads the product's memory
    for a reply nothing else made addressed, and only for that."""
    transcript.record(books, thread="T3", role="agent", text="o PDF sai na sexta.")
    w = _Worker()
    async with _kept_worker(env, w):
        ack = await door.receive(_said("e o CSV?", conversation="T3", in_reply_to="m-antes"),
                                 project=books, client=env.client, settings=QUICK)
        await _settled(env, ack)
    assert [t["text"] for t in w.turns] == ["e o CSV?"]


async def test_what_was_kept_never_joins_the_speakers_next_turn(env, books, table):
    """COALESCING GATHERS WHAT ONE SPEAKER SAID TO THE ROLE, and nothing they said to the room:
    Bia's line to the others and her question to the role, a moment apart, are one kept line and
    one turn that carries only the question."""
    w = _Worker()
    async with _kept_worker(env, w):
        kept = await door.receive(_said("gente, o cliente ligou de novo"), project=books,
                                  client=env.client, settings=QUICK)
        asked = await door.receive(_said("@po o extrato já sai em PDF?", mentioned=True),
                                   project=books, client=env.client, settings=QUICK)
        await _settled(env, asked)
        assert (await _settled(env, kept))["state"] == "overheard"
    assert [t["text"] for t in w.turns] == ["@po o extrato já sai em PDF?"]


# ── 3c. never in a prompt; found by recall ──────────────────────────────────────────────────────

async def test_what_was_kept_is_never_in_a_prompt_and_is_found_by_recall(table, ledger,
                                                                         monkeypatch):
    """Kept and searchable, never prompted (decision 3). Two lines the room said to each other —
    one in the room the turn is in, one in another conversation — and a line addressed to the
    role elsewhere: the turn's conversation block and its recall block read the last and neither
    of the first two; the explicit recall finds all three, and says which were addressed."""
    from openfactory import actions
    from openfactory.actions import catalog
    from openfactory.actions.base import Actor

    project = _project()
    transcript.record(project, thread="books", role="person", actor=BIA, addressed=False,
                      text="o fornecedor Tabajara atrasou de novo")
    transcript.record(project, thread="T9", role="person", actor=BIA, addressed=False,
                      text="o fornecedor Tabajara pediu desconto")
    transcript.record(project, thread="T8", role="person", actor=ANA,
                      text="o fornecedor Tabajara entrega na sexta")
    module = _Module(project)

    engine.turn(project, Message(project="books", conversation="books", speaker=ANA,
                                 text="o que sabemos do fornecedor Tabajara?",
                                 mentions_role=True), module=module)

    [asked] = module.asked("answer")
    prompt = asked["conversation"]
    assert "entrega na sexta" in prompt, "the recall block was not built at all"
    assert "atrasou" not in prompt and "desconto" not in prompt, prompt

    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (module, project, None))
    found = await actions.perform("product_recall", by=Actor(id=ANA, via="panel"),
                                  project="books", query="fornecedor Tabajara")
    hits = {h["text"]: h["addressed"] for h in found.data["hits"]}
    assert hits.get("o fornecedor Tabajara atrasou de novo") is False
    assert hits.get("o fornecedor Tabajara pediu desconto") is False
    assert hits.get("o fornecedor Tabajara entrega na sexta") is True


def test_the_room_is_SHOWN_every_line_and_a_prompt_reads_none_it_was_not_for(table):
    """The two readers of one conversation: the panel's history and the thread row show the room
    what the room said; the default — the read a prompt is built from — leaves it out."""
    project = _project()
    transcript.record(project, thread="books", role="person", actor=BIA, addressed=False,
                      text="bom dia, pessoal")
    transcript.record(project, thread="books", role="person", actor=ANA, text="@po e o PDF?")
    assert [t.text for t in transcript.recent(project, thread="books")] == ["@po e o PDF?"]
    shown = transcript.recent(project, thread="books", overheard=True)
    assert [(t.text, t.addressed) for t in shown] == [("bom dia, pessoal", False),
                                                      ("@po e o PDF?", True)]


# ── 4. the whole conversation, with no add-on installed ─────────────────────────────────────────

async def test_the_whole_conversation_works_with_no_add_on_installed(env, books, table, ledger,
                                                                     monkeypatch):
    """#266 slice 6's second criterion. Every add-on hidden, and any attempt to build a channel
    refused: the CLI asks and is answered; a person on the panel asks in their own conversation,
    is shown a draft, types "sim" and it is written in their name; in the project's room a line to
    the others is kept, and one that names the role is answered — all through the one door, on the
    conversation workflow and the worker's real turn."""
    from openfactory import actions, plugins
    from openfactory.actions import catalog
    from openfactory.actions.base import Actor
    from openfactory.adapters.channel import registry as channels
    from openfactory.product import module as module_mod

    monkeypatch.setattr(plugins, "_load", lambda: {})

    def _no_channel(*_a, **_k):
        raise AssertionError("the conversation reached for a channel adapter")

    monkeypatch.setattr(channels, "build_channel", _no_channel)
    monkeypatch.setattr("openfactory.adapters.channel.build_channel", _no_channel)
    monkeypatch.setenv(door.DEBOUNCE_ENV, "0.2")
    monkeypatch.setenv(door.BOUND_ENV, "20")
    module = _asking(books)
    monkeypatch.setattr(module_mod, "ProductModule", lambda project, *, via="": module)

    async def _connected():
        return env.client, None

    monkeypatch.setattr(catalog, "_connected", _connected)
    staging._PENDING.clear()
    cli = Actor(id="ana", display="ana", via="cli", admin=True)
    bia = Actor(id=BIA, display="Bia", via="panel", admin=True, conversation=f"person:{BIA}")
    try:
        async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[ConversationWorkflow],
                          activities=[conversation_turn, conversation_overheard,
                                      _fast_stand_in(), conversation_report]):
            asked = await actions.perform("product_say", by=cli, project="books",
                                          message="o extrato conciliado muda?")
            assert asked.ok and asked.message == PLAIN.text, asked

            drafted = await actions.perform("product_say", by=bia, project="books",
                                            message=REQUEST)
            assert drafted.ok and drafted.data["asks"] is True, drafted
            confirmed = await actions.perform("product_say", by=bia, project="books",
                                              message="sim")
            assert confirmed.ok, confirmed

            kept = await actions.perform("product_say", by=bia, project="books",
                                         thread="books", message="bom dia, pessoal",
                                         mentioned="false")
            assert kept.ok and kept.data["state"] == door.OVERHEARD, kept
            answered = await actions.perform("product_say", by=bia, project="books",
                                             thread="books", message="@po o extrato muda?",
                                             mentioned="true")
            assert answered.ok and answered.message == PLAIN.text, answered
    finally:
        staging._PENDING.clear()

    [proposed] = module.asked("propose")
    assert proposed["actor"] == BIA and proposed["asked_by"] == BIA
    assert table.said("bom dia, pessoal")[0]["extra"]["addressed"] is False
    assert not [q for q in module.asked("answer") if "bom dia" in q["question"]]


def _fast_stand_in():
    """The read-only lane, stood in: nothing in this conversation asks only to be shown."""
    @activity.defn(name="conversation_fast")
    async def fast(inp: TurnInput) -> dict:
        return {"replies": []}

    return fast


def test_the_vendor_id_never_travels_in_what_the_door_enqueues():
    """The arrival a conversation keeps in its history is built from the `Message` alone — so a
    person, and what the transport detected, and nothing a vendor shaped."""
    arrival = door._arrival(_said("oi", mentioned=True, in_reply_to="m0"), _project(),
                            fast=False, agent_name=AGENT)
    data = json.loads(arrival.model_dump_json())
    assert (data["speaker"], data["mentions_role"], data["direct"], data["took_part"]) == (
        BIA, True, False, False)
