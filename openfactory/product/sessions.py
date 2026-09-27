"""A person's conversations with the product role: what they call them, and deleting one (#335).

A NAME IS THE PERSON'S, NOT THE CONVERSATION'S. A conversation is titled by the first thing its
person asked (`actions/catalog.py::_session_title`) until they name it; the name they give is kept
per product, in a file of that person's alone — named by a digest of their key
(`speaker.sealed`), so the file's name says nobody's — and read only for them.

DELETING IS ERASING, NOT HIDING. A person who deletes a conversation expects what they said in it
to be gone — from their list, and from what the role remembers. The words live in four places,
and each is told:

    the transcript         each line written again with no text (`transcript.erase`)
    the project's memory   the recall index drops its lines (`recall.forget_conversation`)
    the product's index    its lines leave the hybrid index (`Index.forget_conversation`)
    the search record      the searches made in it, whose queries were its words
    its files              each one's claim dropped, and a file no other conversation holds
                           erased, bytes and all (`attachments.forget_conversation`)

WHAT THE CONVERSATION ALREADY BECAME STAYS: a requirement it drafted, a decision it recorded, a
fact it taught, a card it opened, a summary filed into the context repository — those are the
product's now, written with a person's yes, and the deletion says so rather than pretending
otherwise. The ROOM is everybody's and is never deleted by one of them; only one's own private
conversations are, and only by their owner.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("openfactory.product.sessions")

#: The longest name a person may give a conversation.
MAX_TITLE = 80
#: How the person's first conversation — the one with no session id — is keyed in their names.
FIRST = "_first"
#: How long a deletion waits for each store's lock before it says it could not finish.
WAIT_SECONDS = 10.0


def _names_file(key: str, owner: str) -> Path:
    from openfactory.paths import product_state_dir
    from openfactory.product.speaker import sealed

    return product_state_dir(key) / "sessions" / f"{sealed(owner)}.json"


def _slot(session: str) -> str:
    return session or FIRST


def clean_title(title: str) -> str:
    """A name as a person may give one: one line, no control characters, at most `MAX_TITLE`."""
    flat = re.sub(r"[\x00-\x1f\x7f]+", " ", str(title or ""))
    return re.sub(r"\s+", " ", flat).strip()[:MAX_TITLE].strip()


def titles(key: str, owner: str) -> dict[str, str]:
    """`session id → name` for the conversations `owner` named — "" is their first one."""
    path = _names_file(key, owner)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    names = data.get("titles") if isinstance(data, dict) else None
    if not isinstance(names, dict):
        return {}
    return {("" if k == FIRST else str(k)): str(v) for k, v in names.items() if str(v).strip()}


def _write(key: str, owner: str, names: dict[str, str]) -> None:
    from openfactory.util.filelock import lock_beside, replace_atomically

    path = _names_file(key, owner)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_beside(path)
    lock.acquire(timeout=WAIT_SECONDS)
    try:
        replace_atomically(path, json.dumps(
            {"titles": {_slot(k): v for k, v in sorted(names.items())}},
            ensure_ascii=False, sort_keys=True))
    finally:
        lock.release()


def rename(key: str, owner: str, session: str, title: str) -> str:
    """Name `owner`'s conversation `session` — the name as kept, "" when it was cleared (the
    conversation is then titled by its first question again)."""
    name = clean_title(title)
    names = titles(key, owner)
    if name:
        names[session] = name
    else:
        names.pop(session, None)
    _write(key, owner, names)
    return name


@dataclass(frozen=True)
class Deleted:
    """What deleting one conversation erased, store by store — and whether every line of it was
    within reach (`complete`), which is what the person is told."""

    lines: int
    remembered: int
    indexed: int
    searches: int
    complete: bool


def delete(project, *, conversation: str) -> Deleted:
    """Erase `conversation` — see the module's table. The caller has already decided it is the
    caller's own private one. RAISES `filelock.Waited` when a store stayed locked past the wait:
    a deletion that did not run everywhere is never reported as done."""
    from openfactory.memory import transcript
    from openfactory.memory.recall import forget_conversation as forget_remembered
    from openfactory.paths import project_memory_dir
    from openfactory.product.conversation import owner_of, session_of
    from openfactory.product.index.retrieval import forget_conversation as forget_searches
    from openfactory.product.index.store import Index
    from openfactory.product.key import product_key

    key = product_key(project)
    lines, complete = transcript.erase(project, thread=conversation)
    remembered = forget_remembered(str(getattr(project, "name", "") or ""), conversation,
                                   index_dir=project_memory_dir(project))
    indexed = Index(key).forget_conversation(conversation, wait=WAIT_SECONDS)
    searches = forget_searches(key, conversation)
    from openfactory.product.attachments import forget_conversation as forget_files

    files = forget_files(key, conversation)
    owner = owner_of(conversation)
    names = titles(key, owner)
    if names.pop(session_of(conversation), None) is not None:
        _write(key, owner, names)
    log.warning("OPENFACTORY_PRODUCT_CONVERSATION_DELETED product=%s lines=%d remembered=%d "
                "indexed=%d searches=%d files=%d complete=%s", key, lines, remembered, indexed,
                searches, files, complete)
    return Deleted(lines=lines, remembered=remembered, indexed=indexed, searches=searches,
                   complete=complete)


__all__ = ["FIRST", "MAX_TITLE", "Deleted", "clean_title", "delete", "rename", "titles"]
