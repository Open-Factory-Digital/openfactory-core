"""The seal on a human gate's answer: proof that a process HOLDING THE GATE KEY sent it.

THE GATES TRUSTED THE SIGNAL. `JobWorkflow.approve_prod` and `JobWorkflow.human_merge_gate` are
answered by a person, and the person is authenticated where they press the button — the panel
checks the approver's password (`approvals.verify_approver`) and the caller's token before it
sends anything. The workflow then believed whatever `approver` / `by` arrived. So anybody who could
reach the engine could send the same signal straight to it and skip the password the production
gate is documented to require — which on every compose install up to 0.4.1 was anybody on the
network, because the engine was published on all interfaces with no authentication.

Closing the port closes that door; this closes the class. Each answer is sealed with the gate key,
over EXACTLY the fields the workflow will act on, for exactly one workflow, with a short expiry, and
the worker verifies the seal in an activity (`verify_gate_seal`) before it releases or merges. An
answer that did not come from a process holding the key is refused, recorded where the panel reads
it, and the gate stays open. A seal is spent once. A path to the ENGINE the platform did not intend
— a hosted engine's API key in the wrong hands, a port somebody opens again — can then read and
cancel, but it cannot approve a release or land a pull request.

WHAT IT DOES NOT PROVE: that the panel sent it. TWO SIGNERS are legitimate — the panel
(`view.approve_job` / `view.answer_merge_gate`) and the worker's product role, which releases
through `approve_job` when the client confirms (`product/release.py`) — and the key is symmetric,
so ANY process that can read it can seal. Where the key lives decides who that is:

    container box   job code sees its clone, the toolbox, the guidelines and a cache — never the
                    state directory, and never the variable (`box.env` refuses to carry it). The
                    seal holds against it.
    worktree box    runs as the operator's own user with no filesystem confinement: it can read
                    the key file wherever it is, and the seal does NOT hold against it. That door
                    already runs agent code with the operator's rights; this is one more of them.
    judging roles   on compose they run as worktree boxes INSIDE the worker container, where the
                    key must be for the worker to verify — the same limit.

Closing that needs an asymmetric seal (the worker verifying with a public key it cannot sign
with), which also needs the product role's release to be signed somewhere other than the worker.

THE KEY. `OPENFACTORY_GATE_SECRET` when it is set — the only shape for a deployment whose panel
and worker share no disk (a hosted worker). Otherwise a file both halves can read: beside the
registry when `OPENFACTORY_REGISTRY` names one (compose mounts that directory into both
containers), else `~/.openfactory/gate.key` (one machine, one home). The first process to need it
creates it, 0600. Two halves that hold different keys refuse every answer, by name, rather than
accepting any — the direction of failure an authorization check must have.

A LEAF: the standard library only, so the panel can import it without `temporalio`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

VARIABLE = "OPENFACTORY_GATE_SECRET"
FILENAME = "gate.key"

#: How long a sealed answer stays good. The panel signals the moment it has checked the person,
#: and the worker verifies as soon as the workflow wakes — seconds. Minutes of slack cover a busy
#: worker; anything longer only widens the window a copied seal could be replayed in.
TTL_SECONDS = 600

APPROVE_PROD = "approve_prod"
MERGE_GATE = "human_merge_gate"
#: What `openfactory doctor` seals to ask the WORKER whether it would accept this process's answers
#: (`GateKeyProbeWorkflow`). A kind of its own, so a probe's seal can never answer a gate.
PROBE = "gate_key_probe"

_VERSION = "v1"


def key_path() -> Path:
    registry = (os.environ.get("OPENFACTORY_REGISTRY") or "").strip()
    if registry:
        return Path(registry).expanduser().parent / FILENAME
    from openfactory import namespace

    return namespace.operator_path(FILENAME)


def _key() -> bytes:
    declared = (os.environ.get(VARIABLE) or "").strip()
    if declared:
        return declared.encode()
    path = key_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as out:
            out.write(secrets.token_hex(32))
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        # A half-written key (the creator died between open and write) must never become an
        # empty HMAC key that everybody knows.
        raise RuntimeError(f"the gate key at {path} is empty — delete it and restart the panel "
                           f"and the worker, or set {VARIABLE} on both")
    return text.encode()


def _message(kind: str, workflow_id: str, expires: int, nonce: str,
             fields: tuple[str, ...]) -> bytes:
    return json.dumps([_VERSION, kind, workflow_id, expires, nonce, *fields],
                      ensure_ascii=True, separators=(",", ":")).encode()


def seal(kind: str, workflow_id: str, *fields: str, now: float | None = None) -> str:
    """The seal for one answer to one workflow's gate: `v1.<expiry>.<nonce>.<hmac>`.

    THE NONCE MAKES EVERY SEAL ONE OF A KIND. The workflow spends a seal once, so without it two
    identical answers sealed in the same second — a retried Merge, a double click — would carry
    the same seal and the second would be refused as a replay of the first."""
    expires = int(now if now is not None else time.time()) + TTL_SECONDS
    nonce = secrets.token_hex(8)
    mac = hmac.new(_key(), _message(kind, workflow_id, expires, nonce, tuple(fields)),
                   hashlib.sha256).hexdigest()
    return f"{_VERSION}.{expires}.{nonce}.{mac}"


def refusal(token: str, kind: str, workflow_id: str, *fields: str,
            now: float | None = None) -> str:
    """Empty when `token` seals exactly this answer and has not expired; otherwise why not.

    NEVER RAISES: a key that cannot be read is a refusal that says so, not an exception that a
    caller might catch and treat as "could not check, carry on"."""
    if not token:
        return "the answer carries no seal — it was not sent by this deployment's panel"
    version = token.split(".", 1)[0]
    if version != _VERSION:
        return f"the answer's seal is of an unknown version ({version[:16]!r})"
    try:
        _, expires_text, nonce, mac = token.split(".")
        expires = int(expires_text)
    except ValueError:
        return "the answer's seal is malformed"
    if (now if now is not None else time.time()) > expires:
        return "the answer's seal has expired — answer the gate again from the panel"
    try:
        key = _key()
    except (OSError, RuntimeError) as exc:
        return f"the gate key cannot be read ({exc.__class__.__name__}: {exc})"
    expected = hmac.new(key, _message(kind, workflow_id, expires, nonce, tuple(fields)),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, mac):
        return ("the answer's seal does not match — it was not sent by this deployment's panel, "
                f"or the panel and the worker hold different gate keys (set {VARIABLE} on both)")
    return ""
