"""The credential axis — how each VENDOR's credential is found, declared per kind.

`openfactory/credentials.py` is the composition root's reader of the process environment and
stays vendor-neutral; what it did not have was a way for a vendor to say "my token lives in
`GITLAB_TOKEN`" or "this deployment can mint one for me". Those facts were a closed dict in
core (`_VENDOR_DEFAULT_ENV`) plus the GitHub App mint spelled as the last resort of every
resolution. A stranger's forge got the deployment's GitHub token by default. See `registry.py`.
"""
