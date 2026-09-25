"""The product's memory, searchable — one hybrid index per product, where time and supersession are
data (#269 slice 2, ADR-0053 D3, D5, D8, D9, D10, D12).

ADR-0053's evidence layer: derived from the raw — the context repository's documents as slice 1
read them, the requirements corpus, the board's closed cards and the product's conversations — and
rebuildable from it at any time. Deleting the index costs the next turn a rebuild, never a fact.

    store.py      one SQLite file per product under its state directory: the items, their full-text
                  index and their vectors; refuses another product's rows
    items.py      what an item is, and how each source becomes items: a document's chunks and the
                  decisions a model read in it, a requirement and its register's rows, a closed
                  card, a line of a conversation
    sync.py       the index brought up to its sources, incrementally, and the missing vectors made
    search.py     the query pipeline: metadata filters → lexical → semantic → re-rank, and the
                  supersession rule — a superseded item only ever under what replaced it
    retrieval.py  the engine's step (D8): the search before the turn, written as files in the
                  role's facts pack, the role's own `[[BUSCA: …]]` rounds, and the record every
                  search leaves

NOTHING IS RE-EXPORTED HERE, for the reason `product/documents/__init__.py` gives: callers import
from the module they mean.
"""
