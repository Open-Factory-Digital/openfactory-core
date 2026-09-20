"""#145: the live socket, made real, scoped, and shared.

Three defects on one transport. The cuts restore each — a missing dependency, a scope nobody
checked, a loop per tab — and then go the other way: a scope check that refuses everybody, a
preflight that leaks, an unbounded queue.

THE FIRST CUT IS THE INTERESTING ONE. It removes the dependency, and the guard that catches it is
the only shape that could: every earlier test connected through Starlette's in-process TestClient,
which imports no protocol library at all, so the whole suite stayed green while the deployed socket
404'd for everybody.
"""

TEST = "tests/test_the_socket_is_real_and_scoped.py"
APP = "openfactory/api/app.py"
PYPROJECT = "pyproject.toml"

MUTATIONS = [
    # ── it was dead everywhere ──────────────────────────────────────────────────────────────────
    ("no WebSocket implementation is declared — the socket 404s outside a developer's venv",
     PYPROJECT, '    "websockets>=12",\n', ""),

    ("it is declared in an EXTRA the panel image does not install", PYPROJECT,
     '    "websockets>=12",\n', ""),

    # ── it checked identity and not scope ───────────────────────────────────────────────────────
    # RE-PINNED 2026-09-19, all three: the handshake no longer spells a scope check of its own —
    # it is the watch's first ask of `_gate_verdict`, about its own path. The claims are the
    # same; each cut is made where the rule lives now.
    ("the socket goes back to checking WHO and not WHAT THEY MAY SEE", APP,
     # asked about a path every credential may read: identity is still checked, scope is not
     "    refused = await watch.asked()\n",
     "    refused = await _CredentialWatch(_UNSCOPED_ROUTES[0], _credential_of(ws)).asked()\n"),

    ("the scope check asks for the wrong scope", APP,
     "    return actions.FLOOR\n",
     "    return actions.PRODUCT\n"),

    ("…and the other way: it refuses everybody, 'fixing' the hole by removing the feature", APP,
     "    if refused is not None:\n"
     '        await ws.close(code=_close_code(refused["why"]), reason=refused["why"])\n',
     "    if True:\n"
     '        await ws.close(code=1008, reason="not_allowed")\n'),

    # ── one loop per tab ────────────────────────────────────────────────────────────────────────
    ("every subscriber reads for itself again", APP,
     # RE-PINNED 2026-09-19 (#208): the goodbye of a socket whose credential ended now sits
     # between the read and the project filter, so the cut is the read alone — and it names
     # `for_project`, which the lines under it still ask about.
     "            for_project, snap = await queue.get()\n",
     "            await asyncio.sleep(_STREAM_TICK)\n"
     "            for_project, snap = project, await asyncio.to_thread(_stream_snapshot, "
     "project)\n"),

    ("the shared reader is never stopped, so the process never idles", APP,
     "        if not self._subs and self._task is not None:\n"
     "            self._task.cancel()\n"
     "            self._task = None", "        return"),

    ("the subscriber queue is unbounded — one slow socket kills the process", APP,
     "        q: asyncio.Queue = asyncio.Queue(maxsize=8)",
     "        q: asyncio.Queue = asyncio.Queue()"),

    ("one bad tick ends the fan-out for everybody", APP,
     "            except Exception as exc:  # noqa: BLE001 — one bad tick must not end the "
     "fan-out for\n"
     "                # everybody. Named rather than swallowed: a reader that dies silently here "
     "looks\n"
     "                # exactly like a factory with nothing to report.\n"
     '                log.warning("the panel broadcast tick failed (%s)", str(exc)[:200])',
     "            except Exception:  # noqa: BLE001\n                raise"),

    ("the shared read goes back onto the event loop, blocking every other connection", APP,
     "                    snap = await asyncio.to_thread(_stream_snapshot, project)",
     "                    snap = _stream_snapshot(project)"),

    # ── somebody else's dashboard ───────────────────────────────────────────────────────────────
    ("CORS is mounted unconditionally, so any page a logged-in operator visits reads the factory",
     APP, "if _ORIGINS:\n", "if True:\n"),

    ("the preflight is gated, so no cross-origin call is ever made", APP,
     '    if request.method == "OPTIONS" and request.headers.get('
     '"access-control-request-method"):\n        return await call_next(request)\n', ""),

    ("…and the other way: every OPTIONS bypasses the gate, preflight or not", APP,
     '    if request.method == "OPTIONS" and request.headers.get('
     '"access-control-request-method"):',
     '    if request.method == "OPTIONS":'),
]
