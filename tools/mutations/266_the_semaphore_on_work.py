"""Mutation plan for #266 slice 3 — one semaphore per product on what becomes work (ADR-0051
D7–D11).

Each row takes one rule away; every row must turn tests/test_the_semaphore_on_work.py red. The
six the slice names come first — the lock, the sequence re-check, the staged-draft read, the
anonymity, the atomic replace, the product keying — and after them the rules each of those rests
on: the number minted under the lock, the lock let go on an exception, no model under it, the
bounded rounds, the timeout said in words, the sequence a staged proposal carries.
"""

TEST = "tests/test_the_semaphore_on_work.py"
SEMAPHORE = "openfactory/product/semaphore.py"
MODULE = "openfactory/product/module.py"
AUTHORING = "openfactory/product/authoring.py"
STAGING = "openfactory/product/staging.py"
ENGINE = "openfactory/product/engine.py"
CONFIRM = "openfactory/product/confirm.py"
CASE = "openfactory/product/case.py"
RECALL = "openfactory/memory/recall.py"
FILELOCK = "openfactory/util/filelock.py"

MUTATIONS = [
    # ── the six the slice names ─────────────────────────────────────────────────────────────────
    ("the lock: every write of the product proceeds without the semaphore", SEMAPHORE,
     '    lock = FileLock(_dir(key) / "semaphore.lock")',
     '    lock = __import__("types").SimpleNamespace(acquire=lambda **_: None, '
     'release=lambda: None)'),

    ("the sequence re-check: what was saved after the turn's check is never looked at",
     SEMAPHORE,
     "            if now != mark:",
     "            if False:"),

    ("the staged-draft read: a draft staged in another conversation is never found", SEMAPHORE,
     "    return [exactly] if exactly is not None else closest(text, live)",
     "    return []"),

    # re-pinned 2026-09-24: the section is kept per text for the draft to read too (#269 slice 3)
    ("the anonymity: the already-asked section a conversation reads names who asked", MODULE,
     "        section = asked.render(matches, name_people=False)",
     "        section = asked.render(matches)"),

    ("the anonymity: the product's write log keeps the conversation key, which names a person",
     SEMAPHORE,
     '    return hashlib.sha256(conversation.encode()).hexdigest()[:16] if conversation else ""',
     "    return conversation"),

    ("the anonymity: the write log keeps the proposal token, which carries the conversation key",
     SEMAPHORE,
     '    return hashlib.sha256(token.encode()).hexdigest()[:16] if token else ""',
     "    return token"),

    ("the atomic replace: cases.json is truncated and rewritten in place", CASE,
     "            replace_atomically(path, json.dumps(",
     "            path.write_text(json.dumps("),

    ("the atomic replace: recall-index.json is truncated and rewritten in place", RECALL,
     '        replace_atomically(Path(path), json.dumps({"version": self.version,',
     '        Path(path).write_text(json.dumps({"version": self.version,'),

    ("the atomic replace narrows an existing store's mode", FILELOCK,
     '            if mode is not None:\n                os.fchmod(fh.fileno(), mode)\n',
     '', TEST + "::test_atomic_replace_preserves_an_existing_store_mode"),

    ("no last writer wins: a save overwrites the cases another process saved", CASE,
     "                if theirs.id != changed:",
     "                if False:"),

    ("the product keying: the semaphore is keyed by the registry project", SEMAPHORE,
     "        return product_key(project)",
     '        return f"project:{project.name}"'),

    # ── what those rest on ──────────────────────────────────────────────────────────────────────
    ("the number is minted from the corpus the turn read, not from the base under the lock",
     AUTHORING,
     "        if fresh > number and number not in own:",
     "        if False:"),

    ("only a saved record stops a write: a staged draft stops it too", SEMAPHORE,
     "                arrived = [i for i in moved if i.state == SAVED and i.kind in kinds]",
     "                arrived = [i for i in moved if i.kind in kinds]"),

    ("the model judges what arrived while the semaphore is still held", SEMAPHORE,
     "                if arrived and judge is not None:\n"
     "                    pending, mark = arrived, now",
     "                if arrived and judge is not None and judge(text, arrived) is not None:\n"
     "                    return Checked(found=judge(text, arrived))"),

    ("a write whose sequence keeps moving is written unchecked when the rounds run out",
     SEMAPHORE,
     "    return Checked(crowded=True)",
     "    return Checked(result=write())"),

    # its own test only: with nothing ever let go, every other race in the file waits out the
    # full timeout before going red, and that proves nothing this one does not
    ("the semaphore is kept after the write raises", SEMAPHORE,
     "        keys.remove(key)\n        lock.release()",
     "        keys.remove(key)",
     TEST + "::test_the_semaphore_is_let_go_when_the_write_raises"),

    ("a model call under the semaphore is let through", SEMAPHORE,
     "    if keys:",
     "    if False:"),

    ("a write that cannot have the semaphore says nothing a person can read", MODULE,
     "            return _could_not(semaphore_busy(language=lang), act=act, cause=exc)",
     '            return _could_not("", act=act, cause=exc)'),

    ("a staged card carries the sequence of its staging, not of the turn's check", ENGINE,
     '                                     "seq": ex.seen,',
     '                                     "seq": None,'),

    ("the yes does not hand the staged sequence to the card it files", CONFIRM,
     "        **_checked(module.file_ticket, entry))",
     "        )"),

    ("the anonymous notice of a staged twin is never said", STAGING,
     "    return asked_close_to_this(language=lang)",
     '    return ""'),

    ("an answered draft stays close to every later request", STAGING,
     "            semaphore.close(project, proposal_token(key, verified))",
     "            pass"),

    ("a draft is close to its own conversation's earlier draft", SEMAPHORE,
     "            if w != mine and i.kind in NEW_WORK and i.token not in closed",
     "            if i.kind in NEW_WORK and i.token not in closed"),

    # RE-PINNED 2026-09-25 (#335): `forget_conversation` takes the same lock, without a `try`
    ("a refresh of the recall index takes no lock of its own", RECALL,
     "    lock = lock_beside(path)\n    try:\n        lock.acquire(timeout=REFRESH_WAIT_SECONDS)",
     '    lock = __import__("types").SimpleNamespace(acquire=lambda **_: None, '
     "release=lambda: None)\n    try:\n        lock.acquire(timeout=REFRESH_WAIT_SECONDS)"),
    # FROM #285's REVIEW: the lock is named by `product_slug`, and the digest of the exact key is what
    # keeps two products whose names slug alike on two locks
    ("two products whose names slug alike share one semaphore", "openfactory/product/key.py",
     '    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]',
     '    digest = "0" * 10'),
]
