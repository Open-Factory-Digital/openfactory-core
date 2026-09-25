"""The product's documents, read (#269 slice 1, ADR-0053 "The guardian's memory").

Every document in a product's context repository — text, markdown, mermaid, draw.io, e-mail, PDF,
images — becomes normalised text plus a record, once per version, and every one that cannot be
read is recorded with why:

    ingest.py    the incremental pass (the schedule's) and the event (one file), and `overview`,
                 what the panel and the role's facts show
    record.py    what is read without a model, and the audience label
    reading.py   what only a model writes: the summary and the decisions, once per version
    store.py     where the records live — derived, per product, rebuildable

What reads each type of file is the extraction axis (`openfactory/adapters/extract/`); the record
is `contracts/document.py`, the contract slice 2's index is built from.

NOTHING IS RE-EXPORTED HERE. A package attribute named `ingest` would shadow the `ingest` module,
and a patch or an import that names `documents.ingest` would reach the function instead of the
module; callers import from the module they mean.
"""
