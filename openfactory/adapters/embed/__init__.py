"""The embedding axis — what turns a text into a vector for the product's index (#269 slice 2,
ADR-0053 D9, decision 14).

`base.py` is the port, `registry.py` the rows and the one line of configuration that chooses one,
`local.py` the row a deployment is born with. Nothing here decides WHAT is embedded or how a
vector is scored: that is the index's (`openfactory/product/index/`), which hands a row a batch of
texts and keeps what comes back beside the row's identity.
"""
