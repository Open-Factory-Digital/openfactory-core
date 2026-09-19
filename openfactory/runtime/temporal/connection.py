"""One place to connect to Temporal — dev-server or Temporal Cloud, env-driven.

The SAME code runs everywhere (ADR-0001 D-16); only the connection target changes:

    dev:    TEMPORAL_ADDRESS=localhost:7233                        (default, no auth)
    cloud:  TEMPORAL_ADDRESS=<region>.<cloud>.api.temporal.io:7233
            TEMPORAL_NAMESPACE=<namespace>.<account>
            TEMPORAL_API_KEY=<key>                                 (API-key auth + TLS)
      or    TEMPORAL_TLS_CERT=/path/client.pem
            TEMPORAL_TLS_KEY=/path/client.key                      (classic mTLS)
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import TLSConfig

from openfactory.listeners import ENGINE

#: The one local target, spelled once. Named so a deployment can DECLARE it — which is the whole
#: difference between "I meant the dev server" and "nobody told me anything" (#163). ASKED OF THE
#: ONE DEFINITION (#183), so it is the port `openfactory up` starts the engine on by construction.
LOCAL_DEV_ADDRESS = ENGINE.local()

#: Every name this deployment could have used to say where its engine is. Read at call time, in
#: order; `TEMPORAL_ENDPOINT` is what Temporal Cloud's console calls the gRPC endpoint, and the
#: terraform in this repository sets that one while the compose stack sets the other.
_ADDRESS_VARS = ENGINE.reach_vars


class EngineNotDeclared(RuntimeError):
    """Nobody said where the durable engine is.

    ITS OWN TYPE, because every caller of `address()` already has an except-branch that degrades
    honestly, and this must land there rather than in a generic handler that reports "the engine
    did not answer" — which is the sentence a silent localhost produced for a year.
    """


def address() -> str:
    """Where this deployment's durable engine is. RAISES when nobody said (#163).

    IT DEFAULTED TO `localhost:7233`, and the house memory records what that cost: a worker with a
    misconfigured environment connects to something real-looking on the machine it happens to be
    running on and does nothing visible — no error, no workflows, a green process. Measured worse
    than that once: with the OSS compose stack up, a test run started a REAL workflow on a
    developer's engine (#107), and the suite stayed green throughout.

    A DEV SERVER IS STILL ONE LINE: `TEMPORAL_ADDRESS=localhost:7233`, which is what the compose
    stack, the terraform and `docs/configuration.md` all already do. What changed is that saying
    it is now required — an unset environment is a fact about the deployment, not a preference for
    the developer's laptop.
    """
    if found := ENGINE.declared():
        return found
    raise EngineNotDeclared(
        "this deployment does not say where its durable engine is: set "
        + " or ".join(f"`{v}`" for v in _ADDRESS_VARS)
        + f" (a local dev server is `{_ADDRESS_VARS[0]}={LOCAL_DEV_ADDRESS}`). Nothing is "
        "assumed, because a silent fall back to a local engine is a worker that connects "
        "somewhere real-looking and does nothing visible.")


def namespace() -> str:
    return os.environ.get("TEMPORAL_NAMESPACE", "default")


def _auth() -> dict:
    api_key = os.environ.get("TEMPORAL_API_KEY")
    if api_key:  # Temporal Cloud API-key auth (TLS required)
        return {"api_key": api_key, "tls": True}
    cert, key = os.environ.get("TEMPORAL_TLS_CERT"), os.environ.get("TEMPORAL_TLS_KEY")
    if cert and key:  # classic mTLS client cert
        return {
            "tls": TLSConfig(
                client_cert=Path(cert).read_bytes(),
                client_private_key=Path(key).read_bytes(),
            )
        }
    return {}  # plain dev-server


#: How much of the auth digest travels in a pool key. Twelve hex characters is 48 bits — far more
#: than the handful of targets one process ever holds, and short enough to sit in a log line
#: without wrapping.
_DIGEST_CHARS = 12


def _contents(path: str) -> str:
    """The bytes at `path`, digested — or a marker naming it, when they cannot be read.

    NEVER RAISES. A key computation that refuses has no sentence to say about the file; `_auth()`
    does, one line later, inside the connect attempt where the caller is already holding a
    degraded read. The marker still CHANGES when a path appears or disappears, which is the only
    question this value is asked.
    """
    if not path:
        return ""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return "unreadable\x00" + path


def fingerprint() -> tuple[str, str, str]:
    """`(address, namespace, auth-digest)` — what this process would connect to, and as whom.

    ASKED OF THIS MODULE FOR THE SAME REASON `view.temporal_config()` is (#163): two answers to
    "where is the engine" is the defect this file was fixed for, and a caller that wants to know
    whether two connections would land in the same place must not re-read the environment with its
    own precedence to find out. It raises `EngineNotDeclared` exactly as `address()` does — which
    is the refusal `connect()` would produce one line later anyway.

    Its caller is `view.connect()`, which reuses one client per target (GitHub issue #134): the
    panel opened a fresh gRPC client on every `/api/floor` request, and the reporter measured 20 →
    32 open connections over six requests on 2026-09-15. "Same target" has to include the AUTH
    material, because a redeployment that swaps an API key while keeping the address must not be
    served by a client holding the old credential.

    THE SECRET NEVER ENTERS THE KEY — a truncated SHA-256 goes in instead. A pool key reaches a log
    line, a `repr` and a test failure message, and this repository already carries guards against
    credentials travelling that way (`tests/conftest.py`'s strip exists because `.env` once reached
    the whole suite). The digest answers the only question the key asks — *did this change?* —
    and answers nothing else.

    IT DIGESTS THE TLS FILES' CONTENTS, NOT THEIR PATHS, and that costs two file reads per
    `connect()` call on an mTLS deployment. IT DIGESTED THE PATHS, and the reviewer of #145 drove
    the difference on 2026-09-15: rewrite the file at `TEMPORAL_TLS_CERT` in place, with
    `Client.connect` faked to record the bytes it is handed, and

        da669de: first request used b'CERT-BEFORE' | second request used b'CERT-ROTATED-IN-PLACE'
        the pool, on paths:  first b'CERT-BEFORE' | second b'CERT-BEFORE'

    — because before the pool the panel connected on every request, so `_auth()` re-read both files
    every time. Reuse silently dropped that re-read. TWO READS PER CALL IS STRICTLY CHEAPER THAN
    WHAT IT REPLACES: `da669de` read both files on every read-side request too, and then opened a
    gRPC client as well. This reads them and hands back the client it already holds. A deployment
    on API-key auth or a plain dev server has no files here and pays nothing.

    AN UNREADABLE FILE DOES NOT RAISE OUT OF HERE. It digests to a marker, so the honest error
    still comes from `_auth()` inside the connect attempt — where `view.connect()`'s
    failure-sharing path reports it once to every caller queued behind it, rather than from a key
    computation that has no sentence to say about it.
    """
    cert = os.environ.get("TEMPORAL_TLS_CERT") or ""
    key = os.environ.get("TEMPORAL_TLS_KEY") or ""
    material = "\x00".join((
        "api_key", os.environ.get("TEMPORAL_API_KEY") or "",
        "tls_cert", cert, _contents(cert),
        "tls_key", key, _contents(key),
    ))
    digest = hashlib.sha256(material.encode()).hexdigest()[:_DIGEST_CHARS]
    return address(), namespace(), digest


async def connect() -> Client:
    return await Client.connect(
        address(), namespace=namespace(), data_converter=pydantic_data_converter, **_auth()
    )


class EngineNotListening(RuntimeError):
    """Nothing accepted a connection where the engine was declared, for as long as was allowed.

    ITS OWN TYPE, as `EngineNotDeclared` is: it is the one failure at a worker's birth that is
    about TIMING rather than configuration, and the entry point turns it into a sentence and an
    exit code instead of the traceback #135 was filed with."""


#: How long a process being born waits for its engine to start listening, in seconds.
_STARTS_IN_VAR = "OPENFACTORY_ENGINE_STARTS_IN"
_STARTS_IN_S = 30.0


def engine_starts_in() -> float:
    """The bound on the wait below. A DEPLOYMENT'S NUMBER, read per call: how long an engine takes
    to bind is a property of somebody's disk — the dev server recovers its local database before
    it listens, and #135 was likelier exactly after a hard kill, when that recovery is longest."""
    try:
        wanted = float(os.environ.get(_STARTS_IN_VAR, "") or _STARTS_IN_S)
    except ValueError:
        return _STARTS_IN_S
    return wanted if wanted > 0 else _STARTS_IN_S


async def _listening(host: str, port: int) -> bool:
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=1.0)
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


async def connect_at_birth(*, within: float | None = None, every: float = 0.25) -> Client:
    """`connect()`, for a process that may have been started BESIDE its engine (#135).

    THE RACE. `openfactory up` starts the engine, the worker and the panel together, and on some
    restarts the worker dialled before the engine's dev server had bound its port: `connect()`
    raised, the worker exited, and because one dying process ends the set the panel went down with
    it. Same command, nothing changed between runs.

    IT IS THE WORKER'S WAIT, NOT `up`'s. The worker is the process with the dependency, and the
    client already rides out an engine that goes away while the worker RUNS; the one outage it did
    not survive was the one at its own first connect. Every starter has that race — `up`, a worker
    started by hand beside `temporal server start-dev`, compose whenever the engine container
    restarts (`depends_on` orders the first start only) — so waiting in `up` would have fixed one
    starter of three, and left `host.run` holding a second job besides ending the set together.

    THE SOCKET IS ASKED, NOT THE ERROR MESSAGE. The client raises an untyped `RuntimeError` for a
    refused connection, so telling "nothing is listening yet" from "something said no" by its text
    would be parsing a string another project owns. So: wait, bounded, until the declared address
    ACCEPTS a connection — then connect exactly once, and let whatever that raises (a bad key, a
    namespace that does not exist) raise as it always did. A refusal that is an answer is never
    retried, by construction: `connect()` is never retried at all.

    An engine nobody declared still raises `EngineNotDeclared` at once (#163) — there is no
    address to wait on, and none is assumed.
    """
    where = address()
    bound = engine_starts_in() if within is None else within
    parts = urlsplit(f"//{where}")
    host, port = parts.hostname or where, parts.port or ENGINE.default_port
    deadline = time.monotonic() + bound
    while not await _listening(host, port):
        if time.monotonic() >= deadline:
            raise EngineNotListening(
                f"the durable engine at {where} accepted no connection in {bound:.0f}s — this "
                f"process dials it as it starts, and nothing was listening. Is the engine "
                f"running (`openfactory up` starts it beside the worker; `temporal server "
                f"start-dev` starts it alone)? Is `{_ADDRESS_VARS[0]}` where it listens "
                f"(`openfactory doctor` checks)? An engine that is only slow to start is given "
                f"longer with `{_STARTS_IN_VAR}`.")
        await asyncio.sleep(every)
    return await connect()
