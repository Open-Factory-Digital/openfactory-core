"""Run an activity the way a worker runs it: inside an activity context, holding the worker's client.

NOT A TEST FILE. An activity that needs the durable engine asks `activities.engine_client()`, which
is `temporalio.activity.client()` — the client the worker that runs it already holds (#217). A
bare `asyncio.run(acts.start_jobs(...))` has no worker and therefore no client, and the seam
refuses it by name; the SDK's own answer for a test is an `ActivityEnvironment` built with the
client the activity should find, and this is that answer spelled once.

IT REPLACED a `monkeypatch.setattr(connection, "connect", …)` in five files. That double was honest
while the activities opened a client of their own on every execution; once they stopped, a test
still patching `connection.connect` would have been patching a door nothing under test walks
through — green, and measuring nothing.
"""

from __future__ import annotations

import asyncio

from temporalio.testing import ActivityEnvironment


def run_in_a_worker(fn, *args, client):
    """`fn(*args)` executed as an activity whose worker holds `client`; returns what it returns.

    `client` is REQUIRED and keyword-only: an environment built without one is the SDK's default,
    and inside it the seam refuses exactly as it does in a `def` activity — a test that forgot the
    client should read that here, as a missing argument, not three frames down."""
    return asyncio.run(ActivityEnvironment(client=client).run(fn, *args))
