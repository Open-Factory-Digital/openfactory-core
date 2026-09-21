"""One gate: the socket's handshake asks it, and nobody asks it on the event loop.

#208 put the panel's authorization decision in `_gate_verdict` and left two doors beside it, by
name. The cuts here restore each — the handshake's own copy of the rule (a different credential,
no audit line, no memory of what was presented, a provider's exception escaping raw), and the
middleware's ask on the loop — and then go the other way: a hop on every path including the shell,
a gate that guards nothing, a refusal that writes the credential into the close reason.

THE ENUMERATION ROWS ARE THE INTERESTING ONES. A copy of an authorization rule is not a bug you
can see in a diff of the function it was copied FROM, which is how the socket kept a stale one
through two pull requests that touched the gate. So the last cuts add a second door — a websocket
route, and a helper that resolves who somebody is — written exactly the way this one was.
"""

TEST = "tests/test_everyone_who_opens_a_door_asks_the_one_gate.py"

APP = "openfactory/api/app.py"

_THE_ASK = ('    watch = _CredentialWatch(ws.url.path, _credential_of(ws))\n'
            '    refused = await watch.asked()\n'
            '    if refused is not None:\n'
            '        await ws.close(code=_close_code(refused["why"]), reason=refused["why"])\n'
            '        return\n')

MUTATIONS = [
    # ── 1. the handshake's own copy of the rule ─────────────────────────────────────────────────
    ("THE DEFECT ITSELF: the handshake reads `?token=` then the cookie and never the header, so "
     "the two transports answer one presentation two ways", APP,
     "    watch = _CredentialWatch(ws.url.path, _credential_of(ws))\n",
     '    watch = _CredentialWatch(ws.url.path, ws.query_params.get("token")\n'
     '                             or ws.cookies.get("openfactory_token") or "")\n'),

    ("it checks WHO and not WHAT THEY MAY SEE — asked about a path every credential may read",
     APP,
     "    watch = _CredentialWatch(ws.url.path, _credential_of(ws))\n",
     "    watch = _CredentialWatch(_UNSCOPED_ROUTES[0], _credential_of(ws))\n"),

    ("it forgets what the connection presented, as it did whenever the panel was open", APP,
     "    watch = _CredentialWatch(ws.url.path, _credential_of(ws))\n",
     '    watch = _CredentialWatch(ws.url.path, "")\n'),

    ("nobody is asked at all: the socket is open to a URL", APP, _THE_ASK,
     "    watch = _CredentialWatch(ws.url.path, _credential_of(ws))\n"),

    ("it accepts first and asks after, so a refused client is a client that was let in", APP,
     _THE_ASK,
     "    await ws.accept()\n" + _THE_ASK),

    ("…and the other way: the handshake refuses everybody, 'fixing' the copy by removing the "
     "socket", APP,
     "    refused = await watch.asked()\n    if refused is not None:\n",
     '    refused = await watch.asked() or {"why": "not_allowed"}\n    if refused is not None:\n'),

    # ── 2. what it says when it refuses ─────────────────────────────────────────────────────────
    ("a policy refusal and a check nobody could make are closed with each other's code", APP,
     '    return 1011 if why == _ENDED_UNAVAILABLE else 1008\n',
     '    return 1008 if why == _ENDED_UNAVAILABLE else 1011\n'),

    ("the close reason carries the credential it refused", APP,
     '        await ws.close(code=_close_code(refused["why"]), reason=refused["why"])\n',
     '        await ws.close(code=_close_code(refused["why"]),\n'
     '                       reason=f"{refused[\'why\']} {_credential_of(ws)}")\n'),

    ("a scope refusal leaves no audit line, wherever it happens", APP,
     '        log.warning("DENIED_SCOPE_READ %s (%s) for a credential scoped to %s",\n'
     '                    path, wanted, ", ".join(sorted(scopes)) or "nothing")\n', ""),

    # ── 3. the ask, and the loop it must not run on ─────────────────────────────────────────────
    ("the middleware goes back to asking on the event loop", APP,
     "    refused = await _ask_the_gate(request.url.path, _credential_of(request))\n",
     "    refused = _gate_verdict(request.url.path, _credential_of(request))\n"),

    ("…or the seam itself stops leaving it, which is everybody at once", APP,
     "    return await asyncio.to_thread(_gate_verdict, path, credential)\n",
     "    return _gate_verdict(path, credential)\n"),

    ("every path takes a thread, so the shell and the login page queue behind the identity "
     "provider", APP,
     "    if not _gated(path):\n        return None\n"
     "    return await asyncio.to_thread(_gate_verdict, path, credential)\n",
     "    return await asyncio.to_thread(_gate_verdict, path, credential)\n"),

    ("…and the other way: nothing is gated any more", APP,
     '    return path.startswith("/api/")\n',
     '    return path.startswith("/api-nothing-is-mounted-here/")\n'),

    # ── 4. a second door, written the way this one was ──────────────────────────────────────────
    ("A SECOND SOCKET ARRIVES, gated by hand the way this one was", APP, "",
     '\n\n@app.websocket("/api/live")\n'
     "async def live(ws: WebSocket) -> None:\n"
     '    """A second socket, authorized the way the first one used to be."""\n'
     "    from openfactory.identity import build_identity\n\n"
     "    provider = build_identity()\n"
     '    if not getattr(provider, "open_to_everyone", lambda: False)():\n'
     '        token = ws.query_params.get("token") or ""\n'
     '        if provider.identify(credential=token, via="panel") is None:\n'
     '            await ws.close(code=1008, reason="unauthorized")\n'
     "            return\n"
     "    await ws.accept()\n"),

    ("a helper decides admission beside the gate, where no route's own code shows it", APP, "",
     "\n\ndef _may_read(request) -> bool:\n"
     '    """Whether this request may read — a second opinion, in a helper."""\n'
     "    from openfactory.identity import build_identity\n\n"
     "    return build_identity().identify(\n"
     '        credential=_credential_of(request), via="panel") is not None\n'),
]
