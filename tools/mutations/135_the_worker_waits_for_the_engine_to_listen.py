"""#135: a worker started beside its engine waits, bounded, for the engine to be listening."""

TEST = "tests/test_the_worker_waits_for_the_engine_to_listen.py"
CONN = "openfactory/runtime/temporal/connection.py"
WORKER = "openfactory/runtime/temporal/worker.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    ("the worker dials at once again, and dies on the first refusal", CONN,
     "    while not await _listening(host, port):", "    while False:"),

    ("the wait has no bound: an engine that never starts holds the worker for ever", CONN,
     "        if time.monotonic() >= deadline:", "        if False:"),

    ("the bound is a constant nobody's deployment can move", CONN,
     '        wanted = float(os.environ.get(_STARTS_IN_VAR, "") or _STARTS_IN_S)',
     "        wanted = _STARTS_IN_S"),

    ("a refusal that is an ANSWER is waited out and dialled again", CONN,
     "        await asyncio.sleep(every)\n    return await connect()",
     "        await asyncio.sleep(every)\n"
     "    for _ in range(3):\n"
     "        try:\n"
     "            return await connect()\n"
     "        except RuntimeError:\n"
     "            await asyncio.sleep(every)\n"
     "    return await connect()"),

    ("the probe blocks the loop, so the wait cannot be interrupted", CONN,
     "        await asyncio.sleep(every)\n    return await connect()",
     "        time.sleep(every * 8)\n    return await connect()"),

    ("the sentence stops naming the address it waited on", CONN,
     '                f"the durable engine at {where} accepted no connection in {bound:.0f}s',
     '                f"the durable engine accepted no connection in {bound:.0f}s'),

    ("the worker's main goes back to the bare connect", WORKER,
     "    client = await connect_at_birth()  # dev-server or Temporal Cloud, per env",
     "    from openfactory.runtime.temporal.connection import connect\n"
     "    client = await connect()"),

    ("the refusal reaches the person as a traceback again", WORKER,
     "    except EngineNotListening as exc:\n        raise SystemExit(f\"worker: {exc}\") from None",
     "    except EngineNotListening:\n        raise"),

    ("`openfactory worker` keeps the old door", CLI,
     "    from openfactory.runtime.temporal.worker import born as worker_born\n\n"
     "    asyncio.run(worker_born())",
     "    from openfactory.runtime.temporal.worker import main as worker_born\n\n"
     "    asyncio.run(worker_born())"),
]
