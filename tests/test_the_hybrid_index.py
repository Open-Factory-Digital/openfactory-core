"""The product's memory is one hybrid index per product, where time and supersession are data (#269
slice 2, ADR-0053 D3, D5, D9, D10).

THE ACCEPTANCE CRITERIA, each a test below by name:

  - on the years-old fixture, "what holds today about X?" returns the superseding decision, never
    the superseded one, and says the timeline when both are shown;
  - exact terms beat semantic neighbours;
  - an internal document never reaches a client's search;
  - without an embedder the index still answers — by words, metadata and time — and says so;

and the rules the slice was given: no product's item reaches another product's search, the index
is derived and rebuilt from its sources, and nothing is sent to a network by default.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openfactory.contracts.document import CLIENT, INTERNAL
from openfactory.product.index import retrieval
from openfactory.product.index.items import SUPERSEDED, Item
from openfactory.product.index.search import Query, search
from openfactory.product.index.store import ForeignIndex, Index, index_path
from openfactory.product.index.sync import sync
from tests import index_bed as bed

ROOT = Path(__file__).resolve().parent.parent

EMAIL_2021 = "client/correspondence/2021-03-15-invoice-numbering.eml"
POST_2021 = "client/correspondence/2021-06-02-reminders-by-post.eml"
MINUTES_2023 = "client/minutes/2023-03-12-billing-review.md"
MARGIN = "internal/2023-02-20-margin-review.md"
LAYOUT = "client/2022-01-18-statement-layout.md"


@pytest.fixture(autouse=True)
def _no_embedder_is_remembered():
    from openfactory.adapters.embed import registry

    registry._reset_for_tests()
    yield
    registry._reset_for_tests()


def _everything(found) -> list:
    """Every hit the search returned, and every item listed under one."""
    return [*found.hits, *(old for hit in found.hits for old in hit.history)]


def _sources(hits) -> set[str]:
    return {h.source for h in hits}


# ── acceptance: what holds today is the superseding decision ────────────────────────────────────

@pytest.mark.parametrize("semantic", [False, True], ids=["words", "words-and-meaning"])
def test_what_holds_today_is_the_superseding_decision_never_the_superseded_one(tmp_path,
                                                                             semantic):
    """The 2021 rule — the e-mail, REQ-0004 and the card that built it — is never handed over as
    what holds; REQ-0009 is, with the whole timeline under it."""
    embedder = bed.ConceptEmbedder() if semantic else None
    _project, index = bed.build(tmp_path, embedder=embedder)

    found = search(index, Query(text="What holds today about invoice numbering?",
                                audience=INTERNAL), embedder=embedder)

    assert found.hits, "nothing was found about invoice numbering"
    assert all(h.status != SUPERSEDED for h in found.hits), [
        (h.id, h.status) for h in found.hits]
    handed = {h.grp for h in found.hits}
    for gone in ("req:0004", f"doc:{EMAIL_2021}", "card:tidewater:498"):
        assert gone not in handed, f"{gone} was handed over as current"
    holds = next(h for h in found.hits if h.number == 9)
    assert found.hits.index(holds) == min(i for i, h in enumerate(found.hits)
                                          if h.number is not None), \
        "the first requirement a person is shown about numbering must be the one that holds"
    history = {h.grp: h for h in holds.history}
    assert {"req:0004", f"doc:{EMAIL_2021}", "card:tidewater:498"} <= set(history)
    assert all(h.status == SUPERSEDED and h.successors == (9,) for h in holds.history)
    assert [h.date for h in holds.history] == sorted(h.date for h in holds.history), \
        "the timeline is oldest first"

    said = retrieval.render(found, heading="test")
    assert "What holds today: REQ-0009." in said
    timeline = next(line for line in said.splitlines() if line.startswith("- timeline:"))
    assert timeline.index("2021-03-15") < timeline.index("2023-03-12 REQ-0009"), timeline
    assert "SUPERSEDED · REQ-0004" in said
    assert not any(line.startswith("## ") and "REQ-0004" in line for line in said.splitlines()), \
        "REQ-0004 was given a heading of its own — it is only ever listed under what replaced it"


def test_what_holds_brings_the_timeline_that_led_to_it(tmp_path):
    """Asked in words only REQ-0009 carries, the answer still says what it replaced: "what holds
    today" is answered with its history."""
    _project, index = bed.build(tmp_path)

    found = search(index, Query(text="tax authority unbroken sequence per issuer",
                                audience=CLIENT))

    holds = next(h for h in found.hits if h.number == 9)
    assert 4 in {h.number for h in holds.history}
    assert "req:0004" not in {h.grp for h in found.hits}


def test_the_second_reversal_holds_the_same_way(tmp_path):
    _project, index = bed.build(tmp_path)

    found = search(index, Query(text="What holds today about payment reminders?",
                                audience=CLIENT))

    assert all(h.status != SUPERSEDED for h in found.hits)
    holds = next(h for h in found.hits if h.number == 10)
    assert {"req:0005", f"doc:{POST_2021}"} <= {h.grp for h in holds.history}
    assert "req:0005" not in {h.grp for h in found.hits}


def test_what_only_the_superseded_matched_brings_what_replaced_it(tmp_path):
    """A query in the 2021 words finds the 2021 items — and they come back only under REQ-0010,
    pulled in although the words did not match it."""
    _project, index = bed.build(tmp_path)

    found = search(index, Query(text="registered post letter proof of delivery",
                                audience=CLIENT))

    assert f"doc:{POST_2021}" not in {h.grp for h in found.hits}
    holds = next(h for h in found.hits if h.number == 10)
    assert f"doc:{POST_2021}" in {h.grp for h in holds.history}
    assert "SUPERSEDED" in retrieval.render(found, heading="t")


def test_a_superseded_item_whose_successor_cannot_be_shown_is_not_listed(tmp_path):
    """The rule is "only together with what replaced it": with REQ-0009 gone from the corpus, the
    2021 rule is not listed at all — and the search says it held some back."""
    root = bed.context(tmp_path)
    (root / "requirements" / "0009-one-invoice-sequence.md").unlink()
    _project, index = bed.build(tmp_path, root=root)

    found = search(index, Query(text="invoice numbers restart every January prefix",
                                audience=CLIENT))

    assert "req:0004" not in {h.grp for h in _everything(found)}
    assert f"doc:{EMAIL_2021}" not in {h.grp for h in _everything(found)}
    assert found.withheld >= 2
    assert "not listed" in retrieval.render(found, heading="t")


def test_a_chain_of_supersessions_ends_at_what_holds(tmp_path):
    root = bed.context(tmp_path)
    old = root / "requirements" / "0009-one-invoice-sequence.md"
    old.write_text(old.read_text().replace("**Status:** accepted", "**Status:** superseded-by 0011"))
    (root / "requirements" / "0011-numbers-per-branch.md").write_text(
        "# REQ-0011 — Invoice numbers run per branch\n\n- **Status:** accepted\n"
        "- **Date:** 2024-09-01\n- **Supersedes:** 0009\n\n## Why\n\nEach branch keeps its own "
        "continuous invoice sequence.\n", encoding="utf-8")
    _project, index = bed.build(tmp_path, root=root)

    found = search(index, Query(text="invoice numbers restart sequence", audience=CLIENT))

    holds = next(h for h in found.hits if h.number == 11)
    assert {"req:0004", "req:0009"} <= {h.grp for h in holds.history}
    assert all(h.successors == (11,) for h in holds.history)


def test_a_dropped_requirement_is_history_never_current(tmp_path):
    _project, index = bed.build(tmp_path)

    found = search(index, Query(text="fuel surcharge line", audience=CLIENT))

    dropped = {h.grp: h.status for h in found.hits}
    assert dropped.get("req:0007") == "dropped"
    assert dropped.get("card:tidewater:640") == "dropped", \
        "the card of a dropped requirement is history as well"
    assert "DROPPED — decided against" in retrieval.render(found, heading="t")


# ── acceptance: exact terms beat semantic neighbours ────────────────────────────────────────────

def _synthetic(tmp_path, embedder):
    """A small index with one item that carries card #512 and nothing else of the query, and two
    neighbours that carry every other word of it."""
    index = Index(bed.KEY)
    with index.open() as con:
        for n, (text, cards) in enumerate([
                ("Card closed.", ("512",)),
                ("monthly statement pdf balance statement lines monthly statement", ()),
                ("monthly statement pdf balance month statement", ())]):
            item = Item(id=f"doc:x{n}#0", grp=f"doc:x{n}", product=bed.KEY, kind="document",
                        source=f"x{n}.md", text=text, title=f"x{n}", audience=CLIENT,
                        cards=cards, date=f"2022-0{n + 1}-01")
            index.replace_group(con, item.grp, "v1", [item])
        con.commit()
    sync(index, embedder=embedder)
    return index


def test_an_exact_card_number_beats_its_semantic_neighbours(tmp_path):
    embedder = bed.ConceptEmbedder()
    index = _synthetic(tmp_path, embedder)

    found = search(index, Query(text="the monthly statement pdf balance of card #512",
                                audience=CLIENT), embedder=embedder)

    assert [h.grp for h in found.hits][0] == "doc:x0", [(h.grp, h.exact, h.score)
                                                       for h in found.hits]
    assert found.hits[0].exact == 1 and found.hits[1].semantic is not None


def test_an_exact_requirement_number_is_found_whatever_its_spelling(tmp_path):
    _project, index = bed.build(tmp_path)

    for spelled in ("requirement 6", "REQ-0006", "requisito 6", "what does req 6 say"):
        found = search(index, Query(text=spelled, audience=CLIENT))
        assert found.hits and found.hits[0].number == 6, (spelled, [h.grp for h in found.hits])


def test_a_card_number_finds_the_card_first_on_the_fixture(tmp_path):
    embedder = bed.ConceptEmbedder()
    _project, index = bed.build(tmp_path, embedder=embedder)

    found = search(index, Query(text="What did card #512 deliver? monthly statement pdf",
                                audience=CLIENT), embedder=embedder)

    first = found.hits[0]
    assert "512" in first.cards, [(h.grp, h.exact) for h in found.hits]
    layout = [h.grp for h in found.hits].index(f"doc:{LAYOUT}") if f"doc:{LAYOUT}" in {
        h.grp for h in found.hits} else len(found.hits)
    assert all("512" in h.cards for h in found.hits[:layout]), \
        "a neighbour that never names #512 came before something that does"


def test_a_client_s_name_is_an_exact_term_while_it_is_rare(tmp_path):
    from openfactory.product.index.search import exact_terms

    _project, index = bed.build(tmp_path)

    found = search(index, Query(text="What was agreed with Nordwind about statements?",
                                audience=CLIENT))
    assert found.hits[0].exact >= 1 and "nordwind" in found.hits[0].text.lower()
    assert "Invoice" in exact_terms("Invoice numbering — what holds?").names
    common = search(index, Query(text="Invoice", audience=CLIENT))
    assert all(h.exact == 0 for h in common.hits), \
        "a word most of the product says is not a name, however it is capitalised"


@pytest.mark.parametrize("typed", ['"unbalanced', "NEAR(invoice sequence)", "invoice* OR -",
                                   "invoice AND NOT reminders", "col:text ^ {}", "#", ""])
def test_what_a_person_types_is_words_never_the_index_s_syntax(tmp_path, typed):
    _project, index = bed.build(tmp_path)

    found = search(index, Query(text=typed, audience=CLIENT))

    assert isinstance(found.hits, list)


# ── acceptance: an internal document never reaches a client ─────────────────────────────────────

@pytest.mark.parametrize("semantic", [False, True], ids=["words", "words-and-meaning"])
def test_an_internal_document_never_reaches_a_client_s_search(tmp_path, semantic):
    from openfactory.product.documents.record import turn_audience
    from openfactory.product.speaker import ADMIN, ENGINEER, Person
    from openfactory.product.speaker import CLIENT as CLIENT_ROLE

    embedder = bed.ConceptEmbedder() if semantic else None
    _project, index = bed.build(tmp_path, embedder=embedder)
    text = "Nordwind margin discount renewed percent"

    def seen(person, private):
        found = search(index, Query(text=text, audience=turn_audience(person, private=private)),
                       embedder=embedder)
        return found, _sources(_everything(found)), retrieval.render(found, heading="t")

    for person, private in ((Person(id="c", role=CLIENT_ROLE), True),
                            (Person(id="c", role=CLIENT_ROLE), False),
                            (Person(id="e", role=ENGINEER), False),
                            (Person(id="a", role=ADMIN), False)):
        found, sources, said = seen(person, private)
        assert MARGIN not in sources, (person.role, private)
        assert "12 percent" not in said and "margin-review" not in said
    engineer, sources, _said = seen(Person(id="e", role=ENGINEER), True)
    assert MARGIN in sources, "the product's own people, in private, may read it"
    client, _s, _t = seen(Person(id="c", role=CLIENT_ROLE), True)
    assert client.searched < engineer.searched, \
        "the filter is a count as well: what a client may search excludes the internal documents"


def test_a_document_nobody_labelled_is_internal_in_the_index(tmp_path):
    _project, index = bed.build(tmp_path)

    found = search(index, Query(text="kickoff spreadsheet billing team", audience=CLIENT))
    assert "notes/2020-02-10-kickoff.md" not in _sources(_everything(found))
    found = search(index, Query(text="kickoff spreadsheet billing team", audience=INTERNAL))
    assert "notes/2020-02-10-kickoff.md" in _sources(found.hits)


# ── the product partition ───────────────────────────────────────────────────────────────────────

def test_no_product_s_item_reaches_another_product_s_search(tmp_path):
    tidewater, index = bed.build(tmp_path)
    other = bed.project(tmp_path, name="lark", docs_repo="lark/context")
    other_root = tmp_path / "lark-context"
    (other_root / "notes").mkdir(parents=True)
    (other_root / "notes" / "hello.md").write_text("# Hello\n\nThe ledger closes monthly.\n")
    _other, other_index = bed.build(tmp_path, project_=other, root=other_root, board=False)

    assert other_index.path != index.path
    found = search(other_index, Query(text="Nordwind invoice numbering reminders #512",
                                      audience=INTERNAL))
    assert not found.hits, [h.source for h in found.hits]
    ours = search(index, Query(text="ledger closes monthly hello", audience=INTERNAL))
    assert "notes/hello.md" not in _sources(_everything(ours))
    assert "notes/hello.md" in _sources(search(other_index, Query(
        text="ledger closes monthly", audience=INTERNAL)).hits), "the other product finds its own"


def test_an_index_refuses_another_product_s_item(tmp_path):
    index = Index("repo:lark/context")
    item = Item(id="doc:x#0", grp="doc:x", product=bed.KEY, kind="document", source="x.md",
                text="Nordwind", audience=CLIENT)
    with index.open() as con, pytest.raises(ValueError, match="was handed the index"):
        index.replace_group(con, "doc:x", "v1", [item])


def test_an_index_file_built_for_another_product_is_not_read(tmp_path):
    _project, index = bed.build(tmp_path)
    theirs = Index("repo:lark/context")
    theirs.path.parent.mkdir(parents=True, exist_ok=True)
    theirs.path.write_bytes(index.path.read_bytes())

    with pytest.raises(ForeignIndex):
        search(theirs, Query(text="Nordwind", audience=INTERNAL))


def test_a_foreign_row_in_the_file_is_filtered_by_every_read(tmp_path):
    """Even a row that got into the file past the write's guard is not read by another product."""
    _project, index = bed.build(tmp_path)
    with index.open() as con:
        cur = con.execute(
            "INSERT INTO items (id, grp, product, kind, source, text, audience, status) VALUES "
            "('doc:leak#0', 'doc:leak', 'repo:lark/context', 'document', 'leak.md', "
            "'zebrafish ledger', 'client', 'current')")
        con.execute("INSERT INTO fts (rowid, title, text, terms) VALUES (?, '', "
                    "'zebrafish ledger', '')", (cur.lastrowid,))
        con.commit()

    found = search(index, Query(text="zebrafish", audience=INTERNAL))

    assert not found.hits


def test_two_registry_projects_of_one_product_search_one_index(tmp_path):
    web = bed.project(tmp_path, name="tidewater-web")
    api = bed.project(tmp_path, name="tidewater-api")
    _made, index = bed.build(tmp_path, project_=web)

    assert index_path(bed.KEY) == index.path
    retrieval.refresh(api)
    found = retrieval.run(api, Query(text="Nordwind monthly statement", audience=CLIENT),
                          by=retrieval.ENGINE, conversation="")
    assert any("nordwind" in h.text.lower() for h in found.hits)


# ── without an embedder, and with one ───────────────────────────────────────────────────────────

def test_without_an_embedder_the_index_answers_by_words_and_says_so(tmp_path):
    from openfactory.adapters.embed.local import MODEL_ENV

    row, why = retrieval.embedder()
    assert row is None and MODEL_ENV in why, why
    project, _index = bed.build(tmp_path)

    found = retrieval.run(project, Query(text="invoice numbering", audience=CLIENT),
                          by=retrieval.ENGINE, conversation="")

    assert found.hits, "degraded is not empty: the words, the metadata and the dates still answer"
    assert found.degraded == why
    said = retrieval.render(found, heading="t")
    assert "SEMANTIC SEARCH IS OFF OR PARTIAL" in said and MODEL_ENV in said
    assert retrieval.recorded(bed.KEY)[-1]["degraded"] == why


def test_turned_off_on_purpose_is_said_as_well(monkeypatch):
    from openfactory.adapters.embed.registry import KIND_ENV, for_the_index

    monkeypatch.setenv(KIND_ENV, "none")
    row, why = for_the_index()
    assert row is None and "turned off" in why


def test_an_embed_row_nobody_knows_is_refused_by_name(monkeypatch):
    from openfactory.adapters.embed.registry import KIND_ENV, build_embedder, for_the_index

    with pytest.raises(ValueError, match="unknown embed row 'acme_typo'.*local"):
        build_embedder("acme_typo")
    monkeypatch.setenv(KIND_ENV, "acme_typo")
    assert "acme_typo" in for_the_index()[1]


def test_the_semantic_stage_finds_what_the_words_miss(tmp_path):
    embedder = bed.ConceptEmbedder()
    _project, index = bed.build(tmp_path, embedder=embedder)
    asked = Query(text="dunning", audience=CLIENT)

    with_meaning = search(index, asked, embedder=embedder)
    by_words = search(index, asked)

    assert not by_words.hits
    assert any(h.number == 10 for h in with_meaning.hits), [h.grp for h in with_meaning.hits]
    assert not with_meaning.degraded


def test_vectors_made_by_another_model_are_made_again(tmp_path):
    first = bed.ConceptEmbedder(id="stub:first")
    _project, index = bed.build(tmp_path, embedder=first)
    second = bed.ConceptEmbedder(id="stub:second")

    stale = search(index, Query(text="dunning", audience=CLIENT), embedder=second)
    assert "stub:first" in stale.degraded and not stale.hits

    sync(index, embedder=second)
    fresh = search(index, Query(text="dunning", audience=CLIENT), embedder=second)
    assert fresh.hits and not fresh.degraded
    with index.open() as con:
        assert Index.meta(con, "embedder") == "stub:second"


def test_a_turn_embeds_a_bounded_number_and_says_how_many_are_left(tmp_path):
    embedder = bed.ConceptEmbedder()
    _project, index = bed.build(tmp_path)

    done = sync(index, embedder=embedder, embed_limit=5)

    assert done.embedded == 5 and done.unembedded > 0
    found = search(index, Query(text="invoice", audience=CLIENT), embedder=embedder)
    assert "have no vector yet" in found.degraded


def test_the_index_builds_and_answers_with_every_cloud_sdk_blocked_and_no_network(tmp_path):
    """ADR-0040 D4's method, and ADR-0053 D9's acceptance: a subprocess that refuses to import a
    cloud SDK and refuses to open a socket reads the fixture, builds the index and answers."""
    probe = textwrap.dedent(f"""
        import builtins, os, socket, sys
        sys.path.insert(0, {str(ROOT)!r})
        os.environ["OPENFACTORY_LOG_DIR"] = {str(tmp_path / "logs")!r}
        real = builtins.__import__
        BLOCKED = ("boto3", "botocore", "google", "azure")
        def guarded(name, *a, **k):
            if name.split(".")[0] in BLOCKED:
                raise ImportError(f"{{name}} is not installed on this deployment")
            return real(name, *a, **k)
        builtins.__import__ = guarded
        def refuse(self, *a, **k):
            raise RuntimeError(f"a socket was opened: {{a}}")
        socket.socket.connect = refuse
        socket.create_connection = lambda *a, **k: refuse(None, *a)

        from pathlib import Path
        from tests import index_bed as bed
        from openfactory.product.index.search import Query, search
        project, index = bed.build(Path({str(tmp_path)!r}))
        found = search(index, Query(text="What holds today about invoice numbering?"))
        assert found.hits and found.degraded, found
        print("OK", len(found.hits))
    """)
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                          cwd=str(ROOT), timeout=180)
    assert done.returncode == 0 and "OK" in done.stdout, done.stderr[-2000:]


# ── the local row ───────────────────────────────────────────────────────────────────────────────

def _model_folder(tmp_path, weights: bytes = b"weights") -> tuple[Path, str]:
    import hashlib

    folder = tmp_path / "model"
    folder.mkdir()
    for name in ("tokenizer.json", "config.json"):
        (folder / name).write_text("{}")
    (folder / "model.safetensors").write_bytes(weights)
    return folder, hashlib.sha256(weights).hexdigest()


def test_the_local_row_refuses_a_folder_that_is_not_one_and_downloads_nothing(tmp_path,
                                                                              monkeypatch):
    from openfactory.adapters.embed.base import EmbedderUnavailable
    from openfactory.adapters.embed.local import MODEL_ENV, LocalRow

    for value, said in (("minishlab/potion-base-8M", "not an absolute path"),
                        (str(tmp_path / "absent"), "not a folder on this machine")):
        monkeypatch.setenv(MODEL_ENV, value)
        with pytest.raises(EmbedderUnavailable, match=said):
            LocalRow.configured()
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv(MODEL_ENV, str(tmp_path / "empty"))
    with pytest.raises(EmbedderUnavailable, match="model.safetensors"):
        LocalRow.configured()


def test_the_local_row_loads_nothing_unpinned(tmp_path, monkeypatch):
    from openfactory.adapters.embed.base import EmbedderUnavailable
    from openfactory.adapters.embed.local import DIGEST_ENV, MODEL_ENV, LocalRow

    folder, digest = _model_folder(tmp_path)
    monkeypatch.setenv(MODEL_ENV, str(folder))
    monkeypatch.setitem(sys.modules, "model2vec", None)

    with pytest.raises(EmbedderUnavailable, match=f"not one this platform pins.*{digest}"):
        LocalRow.configured()
    monkeypatch.setenv(DIGEST_ENV, digest)
    with pytest.raises(EmbedderUnavailable, match="needs the `embed` extra"):
        LocalRow.configured()


def test_the_local_row_loads_a_declared_model_offline_from_its_folder(tmp_path, monkeypatch):
    import types

    from openfactory.adapters.embed.local import DIGEST_ENV, MODEL_ENV, LocalRow

    folder, digest = _model_folder(tmp_path)
    monkeypatch.setenv(MODEL_ENV, str(folder))
    monkeypatch.setenv(DIGEST_ENV, digest)
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    seen = {}

    class _Model:
        dim = 2

        def encode(self, texts, **kw):
            seen["kw"] = kw
            return [[3.0, 4.0] for _ in texts]

    def from_pretrained(path):
        seen.update(path=path, offline=__import__("os").environ.get("HF_HUB_OFFLINE"))
        return _Model()

    monkeypatch.setitem(sys.modules, "model2vec", types.SimpleNamespace(
        StaticModel=types.SimpleNamespace(from_pretrained=from_pretrained)))

    row = LocalRow.configured()

    assert seen["path"] == str(folder.resolve()) and seen["offline"] == "1"
    assert row.id == f"local:{digest[:16]}" and row.dims == 2
    assert row.embed(["a", "b"]) == [[0.6, 0.8], [0.6, 0.8]]
    assert seen["kw"]["use_multiprocessing"] is False


# ── the sync ────────────────────────────────────────────────────────────────────────────────────

def test_an_unchanged_source_is_not_read_again(tmp_path):
    from openfactory.product.documents.store import Store

    project, index = bed.build(tmp_path)

    again = sync(index, records=Store(bed.KEY), corpus=bed.corpus(tmp_path / "context"),
                 cards=bed.cards(), member=project.name)

    assert again.changed == 0 and again.removed == 0


def test_a_requirement_file_is_indexed_once_as_the_corpus_reads_it(tmp_path):
    _project, index = bed.build(tmp_path)

    with index.open() as con:
        groups = Index.groups(con, "doc:")
    assert not [g for g in groups if g.startswith("doc:requirements/")]
    assert f"doc:{MINUTES_2023}" in groups


def test_a_document_gone_from_the_repository_leaves_the_index(tmp_path):
    from openfactory.product.documents.ingest import ingest
    from openfactory.product.documents.store import Store

    project, index = bed.build(tmp_path)
    root = tmp_path / "context"
    (root / LAYOUT).unlink()
    ingest(project, root=root, reader=bed.FixtureReader(), announce=lambda *_a, **_k: False)

    done = sync(index, records=Store(bed.KEY))

    assert done.removed == 1
    assert f"doc:{LAYOUT}" not in {h.grp for h in search(
        index, Query(text="statement layout lines", audience=CLIENT)).hits}


def test_an_unreadable_document_is_found_and_said_to_exist(tmp_path):
    root = bed.context(tmp_path)
    (root / "client" / "tariffs.xlsx").write_bytes(b"PK\x03\x04 not a document we read")
    _project, index = bed.build(tmp_path, root=root)

    found = search(index, Query(text="tariffs", audience=CLIENT))

    assert found.hits and found.hits[0].status == "unreadable"
    assert "EXISTS AND COULD NOT BE READ" in retrieval.render(found, heading="t")


def test_a_hit_says_where_it_is_when_and_how_it_was_read(tmp_path):
    """The citation: a PDF's page, a markdown section, the date and where the date came from, and
    how the text was read."""
    from tests import documents_bed

    root = bed.context(tmp_path)
    (root / "client" / "sla-v3.pdf").write_bytes(documents_bed.text_pdf(
        "SLA contract v3", "Availability of 99.9 percent a month", title="SLA contract v3"))
    _project, index = bed.build(tmp_path, root=root)

    pdf = search(index, Query(text="availability percent month", audience=CLIENT)).hits[0]
    assert (pdf.source, pdf.locator) == ("client/sla-v3.pdf", "page 1")
    assert (pdf.date, pdf.date_from) == ("2024-03-12", "metadata") and "a PDF" in pdf.origin
    minutes = next(h for h in search(index, Query(text="next billing review September",
                                                  audience=CLIENT)).hits
                   if h.source == MINUTES_2023)
    assert minutes.locator == "§ Next review" and minutes.date_from == "front matter"
    said = retrieval.render(search(index, Query(text="availability percent month",
                                                audience=CLIENT)), heading="t")
    assert "- where: `client/sla-v3.pdf`, page 1" in said
    assert "- dated: 2024-03-12 (metadata)" in said


def test_the_index_is_rebuilt_from_its_sources(tmp_path):
    from openfactory.product.documents.store import Store

    project, index = bed.build(tmp_path)
    with index.open() as con:
        before = sorted(r[0] for r in con.execute("SELECT id FROM items"))
    index.drop()

    sync(index, records=Store(bed.KEY), corpus=bed.corpus(tmp_path / "context"),
         cards=bed.cards(), member=project.name)

    with index.open() as con:
        assert sorted(r[0] for r in con.execute("SELECT id FROM items")) == before


def test_a_reopened_card_leaves_and_a_card_outside_the_read_stays(tmp_path):
    project, index = bed.build(tmp_path)
    reopened = [c.model_copy(update={"state": "open"}) if c.number == "512" else c
                for c in bed.cards() if c.number != "731"]

    sync(index, cards=reopened, member=project.name)

    with index.open() as con:
        groups = Index.groups(con, "card:")
    assert "card:tidewater:512" not in groups, "an open card is the board's, not the index's"
    assert "card:tidewater:731" in groups, "the board a turn reads is a window; the index remembers"


def test_lines_past_the_transcript_s_retention_leave_the_index(tmp_path):
    from openfactory.memory.transcript import RETENTION_DAYS

    now = datetime.now(UTC)
    old = (now - timedelta(days=RETENTION_DAYS + 3)).isoformat()
    new = (now - timedelta(days=2)).isoformat()
    lines = [bed.said("tidewater", "the zeppelin tariff was discussed", ts=old),
             bed.said("tidewater", "the zeppelin tariff again", ts=new)]
    _project, index = bed.build(tmp_path, said=lines)

    found = search(index, Query(text="zeppelin", audience=CLIENT))

    assert [h.text for h in found.hits] == ["the zeppelin tariff again"]


def test_the_search_refuses_to_run_under_the_semaphore(tmp_path):
    from openfactory.product import semaphore

    project, index = bed.build(tmp_path)
    with semaphore.held(project), pytest.raises(semaphore.ModelUnderSemaphore):
        search(index, Query(text="invoice", audience=CLIENT))


def test_a_corrupt_index_file_is_rebuilt_not_trusted(tmp_path):
    index = Index(bed.KEY)
    index.path.parent.mkdir(parents=True, exist_ok=True)
    index.path.write_bytes(b"this is not a database")

    with index.open() as con:
        assert Index.meta(con, "product") == bed.KEY


def test_the_index_s_own_columns_are_what_the_schema_says(tmp_path):
    """The file is SQLite a person can open: the three tables and the full-text index."""
    _project, index = bed.build(tmp_path)
    con = sqlite3.connect(index.path)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"meta", "groups", "items", "fts"} <= names
