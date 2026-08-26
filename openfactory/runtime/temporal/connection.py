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

import os
from pathlib import Path

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import TLSConfig

#: The one local target, spelled once. Named so a deployment can DECLARE it — which is the whole
#: difference between "I meant the dev server" and "nobody told me anything" (#163).
LOCAL_DEV_ADDRESS = "localhost:7233"

#: Every name this deployment could have used to say where its engine is. Read at call time, in
#: order; `TEMPORAL_ENDPOINT` is what Temporal Cloud's console calls the gRPC endpoint, and the
#: terraform in this repository sets that one while the compose stack sets the other.
_ADDRESS_VARS = ("TEMPORAL_ADDRESS", "TEMPORAL_ENDPOINT")


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
    for var in _ADDRESS_VARS:
        found = (os.environ.get(var) or "").strip()
        if found:
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


async def connect() -> Client:
    return await Client.connect(
        address(), namespace=namespace(), data_converter=pydantic_data_converter, **_auth()
    )
