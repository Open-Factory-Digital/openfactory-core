"""Throwaway directories, and the one rule about deleting them.

WHY THIS EXISTS, measured 2026-08-21. Two places in `techlead/` end a `try` with

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

where `tmp` came back from a helper that is documented to hand over a directory the caller now
owns. The product side was correct — `clone_repo` always returns a `tempfile.mkdtemp(...)` — but
the contract is "delete whatever I gave you", and a contract like that has no floor. Three tests
stubbed the helper with the literal string `"/tmp"`, so the suite called `shutil.rmtree("/tmp")`.

IT WAS INVISIBLE FOR AS LONG AS IT EXISTED, because of where pytest keeps its files. On macOS the
basetemp lives under `/private/var/folders/…`, so wiping `/tmp` destroyed nothing anybody noticed.
On Linux it lives *in* `/tmp`, so the run deleted its own temp root and 898 later tests failed with
`FileNotFoundError: '/tmp/pytest-of-runner/pytest-0'` — a cascade that looked nothing like its
cause and hid five real defects underneath it.

`ignore_errors=True` is what let it pass silently: a recursive delete of the wrong tree cannot
fail, by construction.

So the rule is not "be careful with rmtree". It is that a scratch directory carries its identity in
its NAME, and nothing else is deletable by these call sites.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

log = logging.getLogger("openfactory.scratch")

#: Every throwaway directory this platform makes starts with this. It is the ownership claim: the
#: prefix is how a later `discard()` knows the tree is ours to remove.
PREFIX = "openfactory-"


def make(kind: str) -> Path:
    """A fresh scratch directory, named so that `discard` will accept it back."""
    return Path(tempfile.mkdtemp(prefix=f"{PREFIX}{kind}-"))


def is_ours(path: Path | str) -> bool:
    """Is this a scratch directory THIS platform created?

    Two questions, both required. Inside the system temp directory — so a repository checkout or a
    client's working tree can never qualify — AND named with our prefix, so a sibling's temp files
    and the temp root ITSELF are excluded. `/tmp` is inside the temp directory and is not one of
    ours; that distinction is the whole point.
    """
    p = Path(path)
    root = Path(tempfile.gettempdir()).resolve()
    try:
        resolved = p.resolve()
    except OSError:
        return False
    if resolved == root or not resolved.is_relative_to(root):
        return False
    # The prefix must be on the entry directly beneath the temp root, not merely somewhere in the
    # path: `<tmp>/openfactory-x/../../` games and a nested match both fail this.
    top = resolved.relative_to(root).parts[0]
    return top.startswith(PREFIX)


def discard(path: Path | str | None) -> bool:
    """Remove a scratch directory. Returns whether it did.

    REFUSES ANYTHING IT DOES NOT RECOGNISE, loudly in the log and without raising — these call
    sites run in a `finally` where an exception would replace a real answer with a crash. A refusal
    leaks one temp directory; the alternative leaked the machine's entire `/tmp`.
    """
    if path is None:
        return False
    if not is_ours(path):
        log.error("refusing to delete %s — not a scratch directory this platform created", path)
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True
