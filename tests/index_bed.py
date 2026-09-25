"""The years-old fixture made real — its documents read, its corpus and board loaded, its index
built — and the stand-ins the index's tests need (#269 slice 2).

WHAT IS REAL. The documents pass of slice 1 over a copy of `tests/fixtures/evaluation/tidewater/
context/`, the corpus parser, the board's `Ticket`, the index file under the product's state
directory, the sync, the search and the rendering. What is stood in for is only a MODEL: the
reader that writes a document's decisions (so the fixture's 2021 and 2023 decisions are also a
model's reading of them), and the embedder — a deterministic table of concepts, so a test can say
which item is the semantic neighbour of which query and pin an order the real model would decide
for its own reasons.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

from openfactory.product.documents.reading import Reading

FIXTURE = Path(__file__).parent / "fixtures" / "evaluation" / "tidewater"
#: The product's key, as `product_key` spells a registry project linked to `tidewater/context`.
KEY = "repo:tidewater/context"

#: What a model reads as the decisions of the two documents that carry the fixture's story.
DECISIONS = {
    "client/correspondence/2021-03-15-invoice-numbering.eml": [
        {"text": "invoice numbers restart every first of January with the year as a prefix",
         "date": "2021-03-15"}],
    "client/correspondence/2021-06-02-reminders-by-post.eml": [
        {"text": "payment reminders are sent by registered post", "date": "2021-06-02"}],
    "client/minutes/2023-03-12-billing-review.md": [
        {"text": "invoice numbers follow one continuous sequence from April 2023",
         "date": "2023-03-12"},
        {"text": "payment reminders go by e-mail, no longer by registered post",
         "date": "2023-03-12"}],
}


class FixtureReader:
    """The model step of the documents pass, answering the fixture's decisions from here."""

    def read(self, record):
        return Reading(summary=f"{record.title}.", decisions=DECISIONS.get(record.path, []),
                       by="stub/reader")


def project(tmp_path, name: str = "tidewater", docs_repo: str = "tidewater/context"):
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef

    return Project(name=name, repo_path=str(tmp_path / name),
                   tracker=ProviderRef(kind="github", repo=f"tidewater/{name}"),
                   forge=ProviderRef(kind="github", repo=f"tidewater/{name}"),
                   product=ProductConfig(docs_repo=docs_repo))


def context(tmp_path, *, into: str = "context") -> Path:
    root = tmp_path / into
    shutil.copytree(FIXTURE / "context", root)
    return root


def cards():
    from openfactory.product.triage import Ticket

    return [Ticket(**card) for card in yaml.safe_load(
        (FIXTURE / "board.yaml").read_text(encoding="utf-8"))["cards"]]


def corpus(root: Path):
    from openfactory.product.corpus import load_corpus

    return load_corpus(root / "requirements")


def build(tmp_path, *, embedder=None, said=None, project_=None, root: Path | None = None,
          board: bool = True):
    """`(project, index)` — the fixture ingested and indexed, as a turn's sync would leave it.
    `board=False` for a product that is not the fixture's: the fixture's cards are its alone."""
    from openfactory.product.documents.ingest import ingest
    from openfactory.product.documents.store import Store
    from openfactory.product.index.store import Index
    from openfactory.product.index.sync import sync
    from openfactory.product.key import product_key

    made = project_ or project(tmp_path)
    tree = root or context(tmp_path)
    ingest(made, root=tree, reader=FixtureReader(), announce=lambda *_a, **_k: False)
    index = Index(product_key(made))
    sync(index, records=Store(product_key(made)), corpus=corpus(tree),
         cards=cards() if board else None, member=made.name, said=said, embedder=embedder)
    return made, index


# ── the embedder, stood in for ──────────────────────────────────────────────────────────────────

#: The concepts the stand-in places a text in — one dimension each, and one for "none of these".
CONCEPTS = (
    {"number", "numbers", "numbering", "sequence", "restart", "restarts", "prefix", "continuous"},
    {"reminder", "reminders", "dunning", "post", "registered", "letter", "letters", "overdue"},
    {"statement", "statements", "monthly", "pdf", "balance", "month", "lines"},
    {"margin", "discount", "percent", "renewed", "renew"},
    {"surcharge", "fuel", "diesel"},
)


class ConceptEmbedder:
    """A deterministic embedder: a text's vector counts its words per concept, unit length. Two
    texts about the same concept are neighbours whatever words they share — which is what a real
    model is for, and what a test needs to decide by itself."""

    def __init__(self, id: str = "stub:concepts") -> None:
        self.id = id
        self.dims = len(CONCEPTS) + 1
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        out = []
        for text in texts:
            words = re.findall(r"[a-z0-9-]+", str(text).lower())
            vector = [float(sum(1 for w in words if w in concept)) for concept in CONCEPTS]
            vector.append(0.0 if any(vector) else 1.0)
            norm = sum(x * x for x in vector) ** 0.5
            out.append([x / norm for x in vector])
        return out


def said(where: str, text: str, *, ts: str, addressed: bool = True, role: str = "person"):
    """One line of a conversation as the product's recall index holds it."""
    from openfactory.memory.recall import CONVERSATION, Said

    return Said(id=f"t:{where}:{ts}", ts=ts, store=CONVERSATION, where=where, role=role,
                actor="ana", text=text, addressed=addressed)
