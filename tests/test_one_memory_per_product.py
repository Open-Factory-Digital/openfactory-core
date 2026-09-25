"""One memory per product — #266 slice 3, ADR-0051 D2 and its *Consequences*.

WHAT MOVED. The raw conversation log (`memory/transcript.py`, ADR-0024 §1) was partitioned by
REGISTRY project, so two registry projects pointing at one context repository — one product built
from two repositories — remembered one conversation by halves. It is partitioned by PRODUCT now
(`product/key.py`), and each row carries its product in its own `extra`.

WHAT MUST NOT MOVE WITH IT: a single turn a client said before the change. The rows written until
now stay where they are, under each registry project's own name, and every read of a product reads
them through — no copy, no migration — so the history is whole on the first turn after the deploy.
The deletion path follows the key: forgetting one registry project's conversations forgets its
product's, the old rows included, and names the registry projects that share them before it asks.
And nobody else's rows can cross in either direction, whatever a registry project happens to be
named — the mark decides, not the partition's name.

Run against the real `sqlite` sink, the one the open distribution ships, in a file of the test's
own: what is written is read back by the production reader and deleted by the production deleter.
"""

from __future__ import annotations

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.memory import transcript
from openfactory.product.key import product_key

BOOKS_DOCS, SHOP_DOCS = "acme/books-docs", "acme/shop-docs"


def _project(name: str, docs: str = BOOKS_DOCS) -> Project:
    return Project(name=name, repo_path=f"/work/{name}", language="pt-BR",
                   product=ProductConfig(docs_repo=docs, admins=["U0ADMIN"], agent_name="Nina"))


@pytest.fixture
def store(monkeypatch, tmp_path):
    """The open distribution's store, in a file of this test's own."""
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    return tmp_path / "metrics.db"


@pytest.fixture
def registry(monkeypatch, tmp_path) -> dict[str, Project]:
    """Two registry projects of ONE product, and one of another."""
    from openfactory.registry import ProjectRegistry

    path = tmp_path / "registry.yaml"
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(path))
    projects = {p.name: p for p in (_project("books"), _project("books-api"),
                                    _project("shop", SHOP_DOCS))}
    for p in projects.values():
        ProjectRegistry(path).add(p)
    return projects


def _said(turns) -> list[tuple[str, str]]:
    return [(t.role, t.text) for t in turns]


def test_two_registry_projects_of_one_product_share_ONE_memory(store, registry):
    """A person who talks to the role from the product's web page and then from its API page is
    one conversation, remembered whole from either — and not from another product's."""
    books, api, shop = registry["books"], registry["books-api"], registry["shop"]

    transcript.record(books, thread="person:ana", role="person", text="o saldo vem errado",
                      actor="ana")
    transcript.record(api, thread="person:ana", role="agent", text="vou olhar o extrato")

    expected = [("person", "o saldo vem errado"), ("agent", "vou olhar o extrato")]
    assert _said(transcript.recent(books, thread="person:ana")) == expected
    assert _said(transcript.recent(api, thread="person:ana")) == expected
    assert transcript.recent(shop, thread="person:ana") == [], "another product read it"


def test_a_row_is_written_under_the_PRODUCT_and_carries_its_mark(store, registry):
    from openfactory.observability.query import records_of_kind

    transcript.record(registry["books-api"], thread="sala", role="person", text="oi")

    rows = records_of_kind(product_key(registry["books"]), transcript.TRANSCRIPT_KIND)
    assert [(r["ticket"], r["extra"][transcript.PRODUCT_MARK]) for r in rows] == [
        ("sala", product_key(registry["books"]))]
    assert records_of_kind("books-api", transcript.TRANSCRIPT_KIND) == [], (
        "a new row went to the registry project's old partition")


def test_NO_history_is_lost_the_rows_written_before_the_move_are_READ_THROUGH(store, registry):
    """The rows the old code wrote — under each registry project's own name, unmarked — are read
    as the product's, from every member, merged in order with what is written now. Nothing is
    copied: this is the only place they are read from, and the only place retention and a
    deletion have to find them."""
    books, api = registry["books"], registry["books-api"]
    # exactly what the code before #266 slice 3 wrote: the registry project's NAME as partition
    transcript.record("books", thread="sala", role="person", text="antes, do site", actor="ana")
    transcript.record("books-api", thread="sala", role="agent", text="antes, da api")
    transcript.record(books, thread="sala", role="person", text="depois", actor="ana")

    expected = [("person", "antes, do site"), ("agent", "antes, da api"), ("person", "depois")]
    assert _said(transcript.recent(books, thread="sala")) == expected
    assert _said(transcript.recent(api, thread="sala")) == expected


def test_a_project_NAMED_like_a_product_key_cannot_mix_two_clients_words(store, registry,
                                                                         monkeypatch):
    """A registry project may be called anything. One called exactly like the books product's key,
    but belonging to ANOTHER product, wrote its old rows under that name — the books product's
    partition. The mark keeps them apart in both directions: those rows are not the books
    product's, and the books product's rows are not theirs."""
    from openfactory.registry import ProjectRegistry

    impostor = _project(product_key(registry["books"]), "acme/elsewhere")
    ProjectRegistry().add(impostor)
    transcript.record(impostor.name, thread="sala", role="person", text="de outro cliente")
    transcript.record(registry["books"], thread="sala", role="person", text="dos livros")

    assert _said(transcript.recent(registry["books"], thread="sala")) == [
        ("person", "dos livros")]
    assert _said(transcript.recent(impostor, thread="sala")) == [
        ("person", "de outro cliente")]


def test_a_write_never_asks_the_registry(store, monkeypatch):
    """A turn is recorded under its product's key alone; a registry that cannot be read costs a
    read its siblings' old rows, never a write."""
    from openfactory.registry import ProjectRegistry

    def _unreadable(self):
        raise OSError("the registry is on a disk that went away")

    monkeypatch.setattr(ProjectRegistry, "list", _unreadable)
    books = _project("books")

    assert transcript.record(books, thread="sala", role="person", text="oi")
    assert _said(transcript.recent(books, thread="sala")) == [("person", "oi")]


# ── the deletion follows the key ────────────────────────────────────────────────────────────────

def test_forgetting_forgets_the_PRODUCT_the_rows_before_the_move_included(store, registry):
    """ADR-0051 *Consequences*: a deletion that left the rows still under a member's own name would
    report as done a request whose data is still there."""
    books, shop = registry["books"], registry["shop"]
    transcript.record("books", thread="sala", role="person", text="antes, do site")
    transcript.record("books-api", thread="sala", role="person", text="antes, da api")
    transcript.record(books, thread="sala", role="person", text="depois")
    transcript.record(shop, thread="sala", role="person", text="da loja")

    gone = transcript.forget(transcript.partition(books))

    assert gone == 3, gone
    assert transcript.recent(books, thread="sala") == []
    assert transcript.recent(registry["books-api"], thread="sala") == []
    assert _said(transcript.recent(shop, thread="sala")) == [("person", "da loja")], (
        "another product's conversation went with it")


def test_forgetting_is_REFUSED_when_somebody_else_writes_under_the_same_partition(store, registry):
    """A deletion by partition cannot tell a colliding project's rows from the product's, so it
    deletes nothing and says which name collides — a deletion request must never take another
    client's words with it."""
    from openfactory.registry import ProjectRegistry

    impostor = _project(product_key(registry["books"]), "acme/elsewhere")
    ProjectRegistry().add(impostor)
    transcript.record(impostor.name, thread="sala", role="person", text="de outro cliente")
    transcript.record(registry["books"], thread="sala", role="person", text="dos livros")

    with pytest.raises(ValueError, match="nothing was deleted"):
        transcript.forget(transcript.partition(registry["books"]))
    assert _said(transcript.recent(impostor, thread="sala")) == [("person", "de outro cliente")]
    assert _said(transcript.recent(registry["books"], thread="sala")) == [
        ("person", "dos livros")]


def test_the_command_NAMES_the_projects_that_share_the_memory_before_it_deletes(store, registry):
    from typer.testing import CliRunner

    from openfactory.cli import app

    transcript.record("books-api", thread="sala", role="person", text="antes, da api")
    transcript.record(registry["books"], thread="sala", role="person", text="depois")

    asked = CliRunner().invoke(app, ["project", "forget-conversations", "books"], input="n\n")
    assert "books-api" in asked.output and "Proceed?" in asked.output, asked.output
    assert asked.output.index("books-api") < asked.output.index("Proceed?")
    assert len(transcript.recent(registry["books"], thread="sala")) == 2, "it deleted on a no"

    done = CliRunner().invoke(app, ["project", "forget-conversations", "books", "--yes"])
    assert done.exit_code == 0, done.output
    assert "deleted 2 conversation row(s)" in done.output, done.output
    assert transcript.recent(registry["books"], thread="sala") == []


# ── the project's recall reads the product's memory ─────────────────────────────────────────────

def test_recall_reads_the_PRODUCT_s_conversations(store, registry, tmp_path):
    """What was said about something in another conversation of the product — on the other
    registry project's page — reaches the turn, as `engine._with_elsewhere` asks for it."""
    from openfactory.memory.recall import recall

    transcript.record(registry["books"], thread="sala-do-site", role="person",
                      text="o boleto venceu de novo", actor="ana")

    hits = recall("books-api", "boleto", index_dir=tmp_path / "index", own="sala-da-api",
                  partition=transcript.partition(registry["books-api"]))

    assert [h.said.text for h in hits] == ["o boleto venceu de novo"]


def test_the_engine_asks_recall_for_the_product_s_partition(monkeypatch, registry):
    from openfactory.memory import recall as recall_mod
    from openfactory.product import engine

    asked: dict = {}

    def _recall(project, query, **kw):
        asked.update(kw, project=project)
        return []

    monkeypatch.setattr(recall_mod, "recall", _recall)
    monkeypatch.setattr("openfactory.paths.project_memory_dir", lambda project: "/nowhere")

    engine._with_elsewhere(registry["books-api"], "", "boleto", own="sala")

    assert asked["partition"].key == product_key(registry["books"])
    assert set(asked["partition"].members) == {"books", "books-api"}
