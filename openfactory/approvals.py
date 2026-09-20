"""Prod-approval identity gate (ADR-0001 D-12): production requires a human action.

An approver must be in the project's `prod_approvers` allowlist AND authenticate
with a password. Passwords are stored only as SHA-256 hashes, in a file-backed store
(`~/.openfactory/approvers.json`, gitignored) — manage it with `openfactory approver add <login>`.
An env override (`OPENFACTORY_APPROVERS` as JSON) wins, for CI and for a deployed panel with no
home directory to mount — and while it is set the file is neither read nor written: `source()` is
the one place that says which of the two is in force. Every approval is recorded on the ticket
(who + when + version + comment).

THE DIRECTION OF FAILURE, since this is an authorization store: a store that cannot be read
authorizes NOBODY and says so by name (`ApproverSource.problem`), a write never replaces a file it
could not read, and an entry that is not a hash costs only itself (`ApproverSource.malformed`).
No sentence here repeats a value — the values are the hashes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}

#: The override. Set to anything but blanks, it IS this deployment's approvers and the file is not
#: consulted — the deployed panel's shape, where the store arrives as one injected secret.
VARIABLE = "OPENFACTORY_APPROVERS"

_JSON_NAMES = {list: "array", dict: "object", str: "string", bool: "boolean", int: "number",
               float: "number", type(None): "null"}

#: A digest as `hash_password` and the legacy store write it. Lower case only: both compares below
#: are against `.hex()` / `.hexdigest()`, so an upper-case digest is one no password can match.
_DIGEST = re.compile(r"[0-9a-f]{64}")


def hash_password(pw: str) -> str:
    """Salted scrypt (engineering.md #9). Format: `scrypt$<salt_hex>$<hash_hex>`."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(pw.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _not_a_hash(stored: object) -> str:
    """Empty for a value some password CAN match; otherwise what it is instead — its KIND, never
    the value, because a cut hash is still most of a hash.

    EXACTLY THE SET THE COMPARE BELOW COULD EVER ANSWER True FOR, no stricter: the salt goes
    through the same `bytes.fromhex` it will go through there. Measured 2026-09-19 on what that
    compare did with the rest: a number, `true`, an object or an array raised `AttributeError`, a
    `scrypt$` string cut after its salt raised `ValueError` from the unpack, a salt that is not
    hex raised it from `fromhex`, a non-ASCII string raised `TypeError` from `compare_digest` —
    each one a 500 in the approval dialog carrying Python's sentence — and `null`, `0`, `""` and a
    hash that lost its tail were "bad password" for ever. None of them ever verified."""
    if not isinstance(stored, str):
        return f"a JSON {_JSON_NAMES.get(type(stored), 'value')}, not a hash string"
    if stored.startswith("scrypt$"):
        salt_hex, _, hash_hex = stored[len("scrypt$"):].partition("$")
        try:
            bytes.fromhex(salt_hex)
        except ValueError:
            hash_hex = ""
        if _DIGEST.fullmatch(hash_hex):
            return ""
        return ("a `scrypt$` string that is cut short or mistyped (the shape is "
                "`scrypt$<salt, hex>$<64 hex digits>`)")
    if _DIGEST.fullmatch(stored):
        return ""
    return ("a string that is not a hash (`scrypt$<salt, hex>$<64 hex digits>`, or the legacy 64 "
            "hex digits)")


def _password_matches(pw: str, stored: str) -> bool:
    """Constant-time compare. Understands the salted scrypt format and the legacy
    unsalted sha256 (so old stores keep working until re-added). What is not a hash matches
    nothing, and does not raise: `identity/people.py` is the other caller."""
    if _not_a_hash(stored):
        return False
    if stored.startswith("scrypt$"):
        _, salt_hex, hash_hex = stored.split("$", 2)
        digest = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
        return hmac.compare_digest(digest.hex(), hash_hex)
    return hmac.compare_digest(hashlib.sha256(pw.encode()).hexdigest(), stored)  # legacy


def _store_path() -> Path:
    explicit = os.environ.get("OPENFACTORY_APPROVERS_FILE")
    if explicit:
        return Path(explicit)
    from openfactory import namespace as _ns
    return _ns.operator_path("approvers.json")


class NotTheStoreInForce(RuntimeError):
    """A write to the file store, refused because this deployment does not read the file. The
    message is the sentence a person reads."""


class StoreCannotBeRead(RuntimeError):
    """A write to the file store, refused because what the file holds could not be read — so the
    write would have REPLACED it. The message is the sentence a person reads."""


def _sayable(login: str) -> str:
    """A login, for a sentence — unless it is itself a hash (keys and values swapped by hand), in
    which case the login is where the hash lives and is not repeated either."""
    return login if _not_a_hash(login) else "<a login that is itself a hash>"


@dataclass(frozen=True)
class ApproverSource:
    """Where this deployment's approvers come from: the variable, or the file at `path`.

    THE ONE QUESTION, AND `_load` IS ITS ANSWER (#202). The read lived in `_load` alone and told
    nobody which branch it took, so every writer guessed: `add_approver` always wrote the file,
    `approver add` printed `saved` over it, and with the variable set the login it had just saved
    was not an approver — found when #189 cured the same blindness in `approver remove` with a
    check of its own. One answer now, and the verbs, the writers and the release gate's "nobody
    can approve here" all read it: one rule, not one spelling per caller."""

    variable: bool            # True: `OPENFACTORY_APPROVERS` is set, and the file is not consulted
    path: Path                # the file store — named even while it is not read, so a refusal can
    #                           say WHICH file it left alone
    # login → hash, from whichever of the two is in force — ONLY the entries a password can match.
    # `repr=False` here and on `entries`: a dataclass prints its fields, and these are the hashes.
    logins: dict[str, str] = field(repr=False)
    problem: str = ""         # the store in force is not `{login: hash}`: what it is instead
    # login → what its value is instead of a hash (`_not_a_hash`: the kind, never the value). THE
    # SAME SHAPE AS `problem`, ONE LEVEL DOWN (2026-09-19): the container was checked and the
    # entries were not, so `{"ana": 5}` listed ana as an approver and answered her with a 500.
    malformed: dict[str, str] = field(default_factory=dict)
    # Everything the store holds, AS STORED — for the writers alone, so a write changes the one
    # login it names. Built from `logins`, adding carla would drop a malformed `{"hash": "…"}`
    # that a person could still have repaired by hand.
    entries: dict[str, object] = field(default_factory=dict, repr=False)

    @property
    def named(self) -> str:
        """The source in words — what `approver list` says it is reading."""
        if self.variable:
            return (f"`{VARIABLE}` (the variable wins over the file store, {self.path}, which is "
                    f"not read while it is set)")
        return f"the file store, {self.path}"

    @property
    def where(self) -> str:
        """The store in force, short, for the middle of a sentence (`named` is the long form)."""
        return f"`{VARIABLE}`" if self.variable else f"the file store, {self.path},"

    @property
    def unreadable(self) -> str:
        """Empty unless the store in force cannot be read — then the sentence for it.

        IN FORCE AND EMPTY, never a fall back to the file: a typo in an injected secret must not
        quietly arm whatever logins a file on that box happens to hold. It was already so (`_load`
        answered `{}`); what was missing is anybody being TOLD — the gate said the secret was not
        provisioned, and `approver list` printed an empty roster and exited 0."""
        if not self.problem:
            return ""
        if not self.variable:
            # NOBODY, AND NOT WHOEVER COULD STILL BE PARSED OUT OF IT: what a cut file still holds
            # is not what somebody decided it should hold. It raised before this (2026-09-19) —
            # the same nobody, said as `JSONDecodeError` on the CLI and as a 500 in the dialog.
            return (f"the approver file store, {self.path}, cannot be read — {self.problem} — so "
                    f"this deployment has NO approvers: a store that cannot be read authorizes "
                    f"nobody. {self.how_to_repair}")
        return (f"`{VARIABLE}` is set and cannot be read — {self.problem} — so this deployment "
                f"has NO approvers: the file store is not consulted while the variable is set. "
                f"Correct it where this deployment sets it (JSON, login → hash), then restart "
                f"what reads it.")

    @property
    def how_to_repair(self) -> str:
        """The remedy half for a FILE that cannot be read. `mv` is spelled out because starting
        over is the one remedy that loses something, and the person is the one who decides it."""
        return (f"Repair it (one JSON object, login → hash, readable by the user this runs as) or "
                f"restore it from a copy; to start the store over, move it aside "
                f"(`mv {self.path} {self.path}.broken`) and add each approver again with "
                f"`openfactory approver add <login>`.")

    @property
    def malformed_named(self) -> str:
        """The entries that are not hashes — each by login and by KIND, never by value."""
        return "; ".join(f"`{_sayable(login)}` is {what}"
                         for login, what in sorted(self.malformed.items()))

    @property
    def unusable(self) -> str:
        """Empty unless some entries are not hashes — then the sentence naming them. They
        authorize nobody, and they cost nobody else anything."""
        if not self.malformed:
            return ""
        one = len(self.malformed) == 1
        return (f"{len(self.malformed)} entr{'y' if one else 'ies'} in {self.where} cannot be "
                f"used and authorize{'s' if one else ''} nobody — {self.malformed_named}. "
                f"{self.how_to_add()}")

    def why_no_password_works_for(self, login: str) -> str:
        """Empty unless `login`'s own entry is malformed — then the sentence for the person who
        is typing a password nothing can match, instead of "bad password" for ever."""
        what = self.malformed.get(login)
        if not what:
            return ""
        return (f"the entry for {_sayable(login)!r} in {self.where} is {what}, so no password "
                f"can work for that login until the entry is replaced. {self.how_to_add(login)}")

    @property
    def why_the_file_is_not_written(self) -> str:
        """Empty while the file is in force and can be read; otherwise the cause half of every
        write's refusal."""
        if self.variable:
            return (f"this deployment's approvers come from `{VARIABLE}`, which wins over the "
                    f"file store ({self.path}) on every read, so the file was left as it was.")
        if self.problem:
            return (f"the file store, {self.path}, cannot be read — {self.problem} — and a write "
                    f"now would replace whatever it holds with this one change, so it was left "
                    f"as it was.")
        return ""

    def how_to_add(self, login: str = "<login>") -> str:
        """The remedy half, for whoever has to tell a person "that login is not an approver here"
        — so nobody is sent to a verb that will refuse them without saying why."""
        if self.problem:
            return self.unreadable
        if not self.variable:
            return f"Run `openfactory approver add {login}` where this deployment runs."
        # THE BLANK ASSIGNMENT, not `env -u`: the CLI loads `.env`, and `load_dotenv` fills in a
        # name the environment does not hold but never overwrites one it does — even an empty one.
        return (f"Add {login} to the variable where this deployment sets it, then restart what "
                f"reads it. `{VARIABLE}= openfactory approver add {login}` mints the entry "
                f"(login → hash) in that file, to copy from.")


def _file_text(path: Path) -> tuple[str, str]:
    """`(text, problem)` for the file store. NO FILE IS AN EMPTY STORE, the one thing here that
    is not a problem — and it is the READ that says so, not `path.exists()`, which answers False
    for a file inside a directory this user may not enter and would call that store empty too."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "{}", ""
    except OSError as exc:
        return "", f"it cannot be opened ({exc.strerror or type(exc).__name__})"
    except UnicodeDecodeError:
        return "", "it is not UTF-8 text"
    if not text.strip():
        # `json.loads("")` calls this "Expecting value", which names nothing a person can act on
        return "", ("it is empty, which is what a write cut short leaves behind (a store with "
                    "nobody in it is `{}`)")
    return text, ""


def _read(text: str, what: str) -> dict:
    """What both stores fill the same way, from the JSON text one of them holds.

    THE PROBLEM NEVER REPEATS THE VALUE: it is where the hashes live, and the sentence reaches a
    terminal, a log line and the panel's approval dialog."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"logins": {}, "problem": f"{what} is not JSON ({exc.msg}, line {exc.lineno} "
                                         f"column {exc.colno})"}
    if not isinstance(data, dict):
        return {"logins": {}, "problem": f"{what} is a JSON {_JSON_NAMES.get(type(data), 'value')}"
                                         f", not an object of login → hash"}
    malformed = {login: _not_a_hash(value) for login, value in data.items() if _not_a_hash(value)}
    return {"logins": {k: v for k, v in data.items() if k not in malformed},
            "malformed": malformed, "entries": data}


def source() -> ApproverSource:
    path = _store_path()
    raw = os.environ.get(VARIABLE, "").strip()
    if raw:
        return ApproverSource(variable=True, path=path, **_read(raw, "its value"))
    text, problem = _file_text(path)
    if problem:
        return ApproverSource(variable=False, path=path, logins={}, problem=problem)
    return ApproverSource(variable=False, path=path, **_read(text, "it"))


def _load() -> dict[str, str]:
    return source().logins


def _the_file_in_force() -> ApproverSource:
    """The source, for a WRITER — or the refusal. A write the deployment would not read is not
    made and then explained: `add_approver` wrote the file whatever was in force, and #189's
    `remove` took the login out of the file on its way to saying she was still an approver."""
    src = source()
    if src.variable:
        raise NotTheStoreInForce(src.why_the_file_is_not_written)
    if src.problem:
        # REFUSED, NOT BACKED UP AND REPLACED. The file that cannot be parsed is often the only
        # copy of everybody's hash, and one brace away from whole; a verb that moved it aside and
        # wrote `{carla: …}` would leave a store that lists, exits 0 and approves — for carla
        # alone. Starting over is a person's decision, and `how_to_repair` spells its one line.
        raise StoreCannotBeRead(src.why_the_file_is_not_written)
    return src


def add_approver(login: str, password: str) -> None:
    src = _the_file_in_force()
    store = {**src.entries, login: hash_password(password)}
    src.path.parent.mkdir(parents=True, exist_ok=True)
    src.path.write_text(json.dumps(store, indent=2, sort_keys=True))


def remove_approver(login: str) -> bool:
    """Take `login` out of the file store. True iff it was there.

    THE ANSWER IS THE POINT (#138's shape, one table over). This was `store.pop(login, None)`
    returning nothing, and the verb above it printed `removed '<login>'` whatever happened — so a
    mistyped login reported success while the person kept their say over a production release.
    Nothing is written when nothing was removed.

    AND IT REFUSES WHILE THE FILE IS NOT WHAT IS READ (`NotTheStoreInForce`): no process can take a
    login out of its parent's environment, and editing a file nothing reads is not a removal."""
    src = _the_file_in_force()
    if login not in src.entries:  # a malformed entry IS there, and removing it is one of its cures
        return False
    store = {k: v for k, v in src.entries.items() if k != login}
    src.path.write_text(json.dumps(store, indent=2, sort_keys=True))
    return True


def list_approvers() -> list[str]:
    return sorted(_load().keys())


def verify_approver(login: str, password: str, allowed: list[str]) -> bool:
    """True iff `login` is an allowed approver for the project AND the password matches
    the stored hash."""
    if login not in allowed:
        return False
    expected = _load().get(login)
    return bool(expected) and _password_matches(password, expected)
