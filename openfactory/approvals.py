"""Prod-approval identity gate (ADR-0001 D-12): production requires a human action.

An approver must be in the project's `prod_approvers` allowlist AND authenticate
with a password. Passwords are stored only as SHA-256 hashes, in a file-backed store
(`~/.openfactory/approvers.json`, gitignored) — manage it with `openfactory approver add <login>`.
An env override (`OPENFACTORY_APPROVERS` as JSON) wins, for CI and for a deployed panel with no
home directory to mount — and while it is set the file is neither read nor written: `source()` is
the one place that says which of the two is in force. Every approval is recorded on the ticket
(who + when + version + comment).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}

#: The override. Set to anything but blanks, it IS this deployment's approvers and the file is not
#: consulted — the deployed panel's shape, where the store arrives as one injected secret.
VARIABLE = "OPENFACTORY_APPROVERS"

_JSON_NAMES = {list: "array", str: "string", bool: "boolean", int: "number", float: "number",
               type(None): "null"}


def hash_password(pw: str) -> str:
    """Salted scrypt (engineering.md #9). Format: `scrypt$<salt_hex>$<hash_hex>`."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(pw.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _password_matches(pw: str, stored: str) -> bool:
    """Constant-time compare. Understands the salted scrypt format and the legacy
    unsalted sha256 (so old stores keep working until re-added)."""
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
    logins: dict[str, str]    # login → hash, from whichever of the two is in force
    problem: str = ""         # the variable is set and is not `{login: hash}`: what it is instead

    @property
    def named(self) -> str:
        """The source in words — what `approver list` says it is reading."""
        if self.variable:
            return (f"`{VARIABLE}` (the variable wins over the file store, {self.path}, which is "
                    f"not read while it is set)")
        return f"the file store, {self.path}"

    @property
    def unreadable(self) -> str:
        """Empty unless the variable is set and cannot be read — then the sentence for it.

        IN FORCE AND EMPTY, never a fall back to the file: a typo in an injected secret must not
        quietly arm whatever logins a file on that box happens to hold. It was already so (`_load`
        answered `{}`); what was missing is anybody being TOLD — the gate said the secret was not
        provisioned, and `approver list` printed an empty roster and exited 0."""
        if not self.problem:
            return ""
        return (f"`{VARIABLE}` is set and cannot be read — {self.problem} — so this deployment "
                f"has NO approvers: the file store is not consulted while the variable is set. "
                f"Correct it where this deployment sets it (JSON, login → hash), then restart "
                f"what reads it.")

    @property
    def why_the_file_is_not_written(self) -> str:
        """Empty while the file is in force; otherwise the cause half of every write's refusal."""
        if not self.variable:
            return ""
        return (f"this deployment's approvers come from `{VARIABLE}`, which wins over the file "
                f"store ({self.path}) on every read, so the file was left as it was.")

    def how_to_add(self, login: str = "<login>") -> str:
        """The remedy half, for whoever has to tell a person "that login is not an approver here"
        — so nobody is sent to a verb that will refuse them without saying why."""
        if not self.variable:
            return f"Run `openfactory approver add {login}` where this deployment runs."
        if self.problem:
            return self.unreadable
        # THE BLANK ASSIGNMENT, not `env -u`: the CLI loads `.env`, and `load_dotenv` fills in a
        # name the environment does not hold but never overwrites one it does — even an empty one.
        return (f"Add {login} to the variable where this deployment sets it, then restart what "
                f"reads it. `{VARIABLE}= openfactory approver add {login}` mints the entry "
                f"(login → hash) in that file, to copy from.")


def source() -> ApproverSource:
    path = _store_path()
    raw = os.environ.get(VARIABLE, "").strip()
    if not raw:
        return ApproverSource(variable=False, path=path,
                              logins=json.loads(path.read_text()) if path.exists() else {})
    # THE PROBLEM NEVER REPEATS THE VALUE: it is where the hashes live, and the sentence reaches a
    # terminal, a log line and the panel's approval dialog.
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ApproverSource(variable=True, path=path, logins={},
                              problem=f"its value is not JSON ({exc.msg}, character {exc.pos})")
    if not isinstance(data, dict):
        return ApproverSource(variable=True, path=path, logins={},
                              problem=f"its value is a JSON {_JSON_NAMES.get(type(data), 'value')}"
                                      f", not an object of login → hash")
    return ApproverSource(variable=True, path=path, logins=data)


def _load() -> dict[str, str]:
    return source().logins


def _the_file_in_force() -> ApproverSource:
    """The source, for a WRITER — or the refusal. A write the deployment would not read is not
    made and then explained: `add_approver` wrote the file whatever was in force, and #189's
    `remove` took the login out of the file on its way to saying she was still an approver."""
    src = source()
    if src.variable:
        raise NotTheStoreInForce(src.why_the_file_is_not_written)
    return src


def add_approver(login: str, password: str) -> None:
    src = _the_file_in_force()
    store = {**src.logins, login: hash_password(password)}
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
    if login not in src.logins:
        return False
    store = {k: v for k, v in src.logins.items() if k != login}
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
