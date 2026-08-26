"""Prod-approval identity gate (ADR-0001 D-12): production requires a human action.

An approver must be in the project's `prod_approvers` allowlist AND authenticate
with a password. Passwords are stored only as SHA-256 hashes, in a file-backed store
(`~/.openfactory/approvers.json`, gitignored) — manage it with `openfactory approver add <login>`.
An env override (`OPENFACTORY_APPROVERS` as JSON) wins, for CI. Every approval is recorded
on the ticket (who + when + version + comment).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


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


def _load() -> dict[str, str]:
    # env override (JSON) wins; else the file store
    raw = os.environ.get("OPENFACTORY_APPROVERS", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    path = _store_path()
    return json.loads(path.read_text()) if path.exists() else {}


def add_approver(login: str, password: str) -> None:
    path = _store_path()
    store = json.loads(path.read_text()) if path.exists() else {}
    store[login] = hash_password(password)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, sort_keys=True))


def remove_approver(login: str) -> None:
    path = _store_path()
    if not path.exists():
        return
    store = json.loads(path.read_text())
    store.pop(login, None)
    path.write_text(json.dumps(store, indent=2, sort_keys=True))


def list_approvers() -> list[str]:
    return sorted(_load().keys())


def verify_approver(login: str, password: str, allowed: list[str]) -> bool:
    """True iff `login` is an allowed approver for the project AND the password matches
    the stored hash."""
    if login not in allowed:
        return False
    expected = _load().get(login)
    return bool(expected) and _password_matches(password, expected)
