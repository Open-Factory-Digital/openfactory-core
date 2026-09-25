"""The extraction axis — what reads each kind of document into text (#269 slice 1, ADR-0053).

`base.py` is the port, `registry.py` the rows and their configuration; each row lives in the module
named for what it reads. Nothing here decides WHICH documents are read or where their records go:
that is `openfactory/product/documents/`, which hands a row one document at a time.
"""
