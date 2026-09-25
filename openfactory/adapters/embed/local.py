"""The local embedding row — a static embedding model read from a folder on this machine (#269
slice 2, ADR-0053 D9, decision 14: "a local model is the default").

WHY THIS ROW, AND WHY THIS LIBRARY. A product's index must run on the client's machine (ADR-0040)
with no text leaving it to be embedded. The candidates measured on 2026-09-24 differ most in what
they bring with them:

  - `model2vec` (MIT, MinishLab) — a STATIC embedding: a token's vector is looked up in a table
    and a text's is their mean. No neural network runs, so there is no torch and no ONNX runtime;
    what it installs is numpy, the `tokenizers` and `safetensors` readers and their small
    dependencies. Its weights are a `safetensors` file, a format that holds numbers and nothing
    that executes, read through `safetensors.safe_open` — never a pickle.
  - `fastembed` — an ONNX runtime (a native inference engine) and an ONNX graph per model;
  - `sentence-transformers` — torch and transformers, gigabytes of native code.

Measured with the two pinned models below, loaded offline on a laptop: `potion-base-8M` (English,
30 MB) loads in 0.3 s, takes 56 MB and embeds about 24,000 chunks of 500 characters a second;
`potion-multilingual-128M` (101 languages, Portuguese among them, 512 MB) loads in 1.0 s, takes
about 1.1 GB and embeds about 20,000 a second. Both make 256-dimensional vectors. A product whose
people write Portuguese wants the multilingual one; a small English-only deployment can take the
small one. That choice is the operator's; which models may be loaded at all is not.

NOTHING IS DOWNLOADED, EVER. The library would fetch a model from its hub when handed a name it
does not find on disk; this row hands it only an absolute path to a folder it has checked holds the
model's files, and turns the hub's client off for the process before the library is imported
(`HF_HUB_OFFLINE=1`) — so a folder removed between the check and the load is an error, not a
download. Putting the model in the folder is an operator's step, done once, where they can see it.

NOTHING UNPINNED IS LOADED. The weights are hashed before they are read, and a model whose SHA-256
is neither one of `PINNED` nor the one the operator declared (`OPENFACTORY_EMBED_MODEL_SHA256`) is
refused by name. The library itself is pinned exactly in the `embed` extra (`pyproject.toml`), for
the reason the PDF reader is: a new version is a change somebody reads before a worker runs it.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

from openfactory.adapters.embed.base import EmbedderUnavailable

log = logging.getLogger("openfactory.embed")

#: The folder holding the model — absolute, on this machine.
MODEL_ENV = "OPENFACTORY_EMBED_MODEL"
#: The SHA-256 of a model's `model.safetensors` the operator accepts besides the pinned ones.
DIGEST_ENV = "OPENFACTORY_EMBED_MODEL_SHA256"
#: The extra that installs the library, as the refusal names it.
EXTRA = "embed"

#: The models this row loads without being told their digest: the SHA-256 of each one's weights,
#: and where they come from — the name and the revision they were measured at on 2026-09-24.
PINNED: dict[str, str] = {
    "14b5eb39cb4ce5666da8ad1f3dc6be4346e9b2d601c073302fa0a31bf7943397":
        "minishlab/potion-multilingual-128M at revision 73908c3438cf03b6a01bcb9611d62b23d0726f08",
    "f65d0f325faadc1e121c319e2faa41170d3fa07d8c89abd48ca5358d9a223de2":
        "minishlab/potion-base-8M at revision bf8b056651a2c21b8d2565580b8569da283cab23",
}
#: What the recommended model is called, for the sentence that says how to get one.
RECOMMENDED = PINNED["14b5eb39cb4ce5666da8ad1f3dc6be4346e9b2d601c073302fa0a31bf7943397"]

#: The files a model folder must hold before the library is handed it.
REQUIRED = ("model.safetensors", "tokenizer.json", "config.json")

#: The most texts handed to the model at once, and the longest text in characters: a static model
#: reads a bounded number of tokens anyway, and a chunk is already short (`index/items.py`).
BATCH = 256
MAX_CHARS = 4000

_HASHED: dict[tuple[str, int, int], str] = {}
_LOCK = threading.Lock()


def _digest(weights: Path) -> str:
    """The SHA-256 of the weights, hashed once per process per (path, size, mtime) — half a
    gigabyte is a second of work, and a turn should not pay it twice."""
    st = weights.stat()
    key = (str(weights), st.st_size, st.st_mtime_ns)
    with _LOCK:
        known = _HASHED.get(key)
    if known:
        return known
    digest = hashlib.sha256()
    with weights.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    with _LOCK:
        _HASHED[key] = digest.hexdigest()
    return _HASHED[key]


def _installed() -> bool:
    """Whether the library is here — FOUND, NEVER IMPORTED: the import is `configured`'s, after
    the hub's client is off. One already loaded counts, whatever loaded it."""
    import importlib.util
    import sys

    if sys.modules.get("model2vec") is not None:
        return True
    try:
        return importlib.util.find_spec("model2vec") is not None
    except (ImportError, ValueError):
        return False


def _refuse(sentence: str) -> EmbedderUnavailable:
    return EmbedderUnavailable(f"{sentence} — until then the product's index answers by exact "
                               f"words, metadata and time only")


class LocalRow:
    """A static embedding model on this machine. Build it with `configured()`."""

    kind = "local"

    def __init__(self, model, *, digest: str, folder: Path) -> None:
        self._model = model
        self.digest = digest
        self.folder = folder
        self.id = f"{self.kind}:{digest[:16]}"
        self.dims = int(model.dim)

    @classmethod
    def configured(cls) -> LocalRow:
        """The row over the model the deployment configured — or `EmbedderUnavailable`, saying
        which step is missing: the folder, its files, a pinned digest, the extra."""
        folder, digest = cls.verified()
        # THE HUB'S CLIENT IS OFF BEFORE THE LIBRARY IS IMPORTED: it reads the switch at import.
        # Only this row uses that client, so the switch changes nothing else in the process.
        os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            from model2vec import StaticModel
        except ImportError:
            raise _refuse(f"the local embedding row needs the `{EXTRA}` extra, which is not "
                          f"installed here (from a checkout: pip install -e '.[{EXTRA}]')"
                          ) from None
        try:
            model = StaticModel.from_pretrained(str(folder.resolve()))
        except Exception as exc:  # noqa: BLE001 — a model that will not load is a reason
            log.warning("the local embedding model in %s could not be loaded", folder,
                        exc_info=True)
            raise _refuse(f"the model in {folder} could not be loaded (the reason is in the "
                          f"platform's log)") from exc
        log.info("OPENFACTORY_EMBED_LOCAL model=%s digest=%s pinned=%s dims=%s", folder,
                 digest[:16], "yes" if digest in PINNED else "declared", getattr(model, "dim", "?"))
        return cls(model, digest=digest, folder=folder)

    @classmethod
    def verified(cls) -> tuple[Path, str]:
        """`(folder, digest)` of the model this row WOULD load — every check `configured` makes
        before it loads anything: the folder, its files, the weights' digest, the extra. What
        `openfactory doctor` asks (#337), so a diagnostic never holds a gigabyte to say "on"."""
        raw = (os.environ.get(MODEL_ENV) or "").strip()
        if not raw:
            raise _refuse(f"no local embedding model is configured: set {MODEL_ENV} to a folder "
                          f"on this machine holding one ({RECOMMENDED} is the recommended one)")
        folder = Path(raw).expanduser()
        if not folder.is_absolute():
            raise _refuse(f"{MODEL_ENV}={raw!r} is not an absolute path — a model is read from a "
                          f"folder on this machine, and a bare name is what a library would go "
                          f"and download")
        if not folder.is_dir():
            raise _refuse(f"{MODEL_ENV} names {folder}, which is not a folder on this machine — "
                          f"nothing is downloaded to stand in for it")
        missing = [name for name in REQUIRED if not (folder / name).is_file()]
        if missing:
            raise _refuse(f"the model folder {folder} has no {', '.join(missing)}")
        digest = _digest(folder / "model.safetensors")
        declared = (os.environ.get(DIGEST_ENV) or "").strip().lower()
        if digest not in PINNED and digest != declared:
            raise _refuse(f"the model in {folder} is not one this platform pins (its weights' "
                          f"SHA-256 is {digest}) and nobody declared it: set {DIGEST_ENV} to that "
                          f"digest to accept it — nothing unpinned is loaded")
        if not _installed():
            raise _refuse(f"the local embedding row needs the `{EXTRA}` extra, which is not "
                          f"installed here (from a checkout: pip install -e '.[{EXTRA}]')")
        return folder, digest

    def embed(self, texts: list[str]) -> list[list[float]]:
        """One unit-length vector per text. Batched, single-process: a worker's activity is not
        the place for a pool of forked encoders."""
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            batch = [str(t or "")[:MAX_CHARS] for t in texts[start:start + BATCH]]
            vectors = self._model.encode(batch, show_progress_bar=False,
                                         use_multiprocessing=False)
            for vector in vectors:
                values = [float(x) for x in vector]
                norm = sum(x * x for x in values) ** 0.5 or 1.0
                out.append([x / norm for x in values])
        return out
