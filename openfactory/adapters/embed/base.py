"""The embedding port — texts in, one vector each out (#269 slice 2, ADR-0053 D9, decision 14).

A REPLACEABLE SEAM, THE SAME KIND AS EXTRACTION. Which model makes the product's vectors is a row
in `registry.py::EMBEDDERS`, chosen by configuration (`OPENFACTORY_EMBED`), and a stranger's
package adds one through the `embed.<kind>` entry point without editing a file of ours
(`plugins.py`). An external embedding API is such a row, and is used only when the client turns it
on (decision 14): the rows this core ships send nothing anywhere.

A ROW SAYS WHO IT IS. `id` names the row and the exact model behind it — for the local row, the
digest of the weights it loaded — and the index keeps it beside the vectors. A vector is compared
only with vectors of the same `id`: two models place the same sentence in two unrelated spaces,
and a cosine across them is a number that means nothing while looking like a score.

UNAVAILABLE IS A SENTENCE, NEVER A CRASH AND NEVER A SILENCE. A row that cannot be built here — its
extra is not installed, no model is configured, the model on disk is not one anybody pinned —
raises `EmbedderUnavailable` with what to do about it, and the index answers without the semantic
stage and SAYS SO on every search (`product/index/search.py`): "found by exact words, metadata and
time only" is a different claim from "found".
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class EmbedderUnavailable(RuntimeError):
    """No vector can be made on this deployment; `str(exc)` is the sentence a person reads —
    why, and what would change it."""


@runtime_checkable
class Embedder(Protocol):
    """One row: `embed` answers one unit-length vector of `dims` floats per text, in order."""

    #: the row's kind and the model's identity — `local:<digest>` — kept beside every vector
    id: str
    dims: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...
