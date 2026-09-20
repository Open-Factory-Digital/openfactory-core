"""#208, proven by breaking it — a stream ends when the credential that opened it stops being good.

READ FROM THE CODE, seen in a browser while reproducing #181. The panel gate runs when a request
arrives, and an event stream's request lasts as long as the tab: `/api/temporal/stream`, the
per-job stream and the socket were each authorized once, at the open. `/auth/logout` revoked the
session in the store and the stream it had opened went on delivering every running job to a
browser that was signed out; an expired session never expired; a credential narrowed to the
product area kept receiving the floor.

SEVEN CLAIMS:

  1. **Whatever stays open asks the gate again, on its own clock** — before a frame leaves, not
     after it; not on every frame; not once an hour.
  2. **It asks the gate's OWN function** (`_gate_verdict`), with the credential and the path it
     was opened with — so it holds for whatever answers `identify`, and the middleware answers
     what it always did.
  3. **The answer no is said once, typed, and the response ends**: a NAMED event carrying the
     gate's own body; `signed_out`, `not_allowed`, and `unavailable` for a check nobody could
     make — which still ends the stream, and never writes the credential down.
  4. **The check runs off the event loop.**
  5. **One seam, and a third stream cannot forget it**: both routes go through `_event_stream`,
     and a route that answers a stream any other way fails the suite by name.
  6. **The socket is asked again too**, and says `bye` with the same typed answer.
  7. **The page closes what the server ended instead of letting the browser reconnect it**, asks
     the gate with a read that can see a status, and reopens it when the floor is answered.

The guard is `tests/test_a_stream_ends_when_its_credential_does.py`: the real app over ASGI with a
real registered session, revoked through the real `/auth/logout`; and the page's own functions
under node.
"""

TEST = "tests/test_a_stream_ends_when_its_credential_does.py"

APP = "openfactory/api/app.py"
PAGE = "openfactory/api/panel.html"

_ASKED_BEFORE = (
    "            if watch.due():\n"
    "                ended = await watch.ended()\n"
    "                if ended is not None:\n"
    "                    yield f\"event: {STREAM_ENDED_EVENT}\\ndata: "
    "{json.dumps(ended, sort_keys=True)}\\n\\n\"\n"
    "                    return\n"
    "            yield frame\n")

MUTATIONS = [
    # ── 1. it is asked again, on its own clock ──────────────────────────────────────────────────
    ("THE DEFECT ITSELF: a stream is authorized at the open and never again", APP,
     "            if watch.due():\n                ended = await watch.ended()\n",
     "            if False:\n                ended = await watch.ended()\n"),

    ("it is asked AFTER the frame has left, so one more frame of the floor is delivered", APP,
     _ASKED_BEFORE,
     "            yield frame\n" + _ASKED_BEFORE.replace("            yield frame\n", "")),

    ("it is asked on EVERY frame — a store read per tab per second", APP,
     "        return _stream_clock() >= self._due\n",
     "        return True\n"),

    ("the interval is an hour: signed out means still streaming until lunch", APP,
     "_STREAM_RECHECK_S = 10.0\n",
     "_STREAM_RECHECK_S = 3600.0\n"),

    # ── 2. the gate's own function, the stream's own credential and path ────────────────────────
    ("it asks about a path every credential may read, so a narrowed scope is never noticed", APP,
     "            refused = await asyncio.to_thread(_gate_verdict, self.path, self._credential)",
     "            refused = await asyncio.to_thread(_gate_verdict, _UNSCOPED_ROUTES[0], "
     "self._credential)"),

    ("it forgets the credential it was opened with, and cuts a session that is still good", APP,
     "        self._credential = credential\n",
     "        self._credential = \"\"\n"),

    ("the verdict gates the HTML shell too — it is no longer the middleware's decision", APP,
     # RE-PINNED 2026-09-20 (rebase onto main): who a credential is now comes back from
     # `_admission`, the one decision every door renders, so the verdict's body is that call and
     # no longer `build_identity()` spelled out here. The path guard it cuts is unchanged.
     "    if not path.startswith(\"/api/\"):\n        return None\n    door = _admission(credential)",
     "    door = _admission(credential)"),

    ("a wrong Bearer header is rescued by the cookie behind it", APP,
     "        auth[7:] if auth.startswith(\"Bearer \")\n"
     "        else (request.cookies.get(\"openfactory_token\")\n"
     "              or request.query_params.get(\"token\") or \"\")\n",
     "        request.cookies.get(\"openfactory_token\")\n"
     "        or (auth[7:] if auth.startswith(\"Bearer \") else \"\")\n"
     "        or request.query_params.get(\"token\") or \"\"\n"),

    # ── 3. the answer no: once, typed, and then the end ─────────────────────────────────────────
    ("the goodbye is an ordinary message: `onmessage` paints it as a frame", APP,
     "                    yield f\"event: {STREAM_ENDED_EVENT}\\ndata: ",
     "                    yield f\"data: "),

    ("it says goodbye and goes on streaming", APP,
     "{json.dumps(ended, sort_keys=True)}\\n\\n\"\n                    return\n",
     "{json.dumps(ended, sort_keys=True)}\\n\\n\"\n"),

    ("the goodbye drops the gate's body, so the page is not told where the login is", APP,
     "        return {\"why\": why, \"status\": refused.status, **refused.body}",
     "        return {\"why\": why, \"status\": refused.status}"),

    ("a check that RAISED fails OPEN: the stream outlives the deployment's ability to vouch", APP,
     "            refused = _Refusal(503, {\"detail\": \"the credential this stream was opened "
     "with \"\n                                               \"could not be checked again\"})",
     "            refused = None"),

    ("a check nobody could make is reported as the person having signed out", APP,
     "        why = _ENDED_WHY.get(refused.status, _ENDED_UNAVAILABLE)",
     "        why = _ENDED_WHY.get(refused.status, \"signed_out\")"),

    ("the provider's sentence is logged as it came — with the credential in it", APP,
     "                said = said.replace(self._credential, \"<credential>\")",
     "                pass"),

    ("a stream that ends over its credential leaves no log line", APP,
     "        log.info(\"OPENFACTORY_STREAM_ENDED %s ended: %s (%s)\", self.path, why, "
     "refused.status)\n",
     ""),

    # ── 4. off the event loop ───────────────────────────────────────────────────────────────────
    ("the store is folded on the event loop", APP,
     "            refused = await asyncio.to_thread(_gate_verdict, self.path, self._credential)",
     "            refused = _gate_verdict(self.path, self._credential)"),

    # ── 5. one seam, and a third stream cannot forget ───────────────────────────────────────────
    ("the job stream answers without the seam", APP,
     "            await asyncio.sleep(1 if path.exists() else 3)\n\n"
     "    return _event_stream(request, gen())",
     "            await asyncio.sleep(1 if path.exists() else 3)\n\n"
     "    return StreamingResponse(gen(), media_type=\"text/event-stream\")"),

    ("the engine stream answers without the seam", APP,
     "            await asyncio.sleep(2)\n\n    return _event_stream(request, gen())",
     "            await asyncio.sleep(2)\n\n"
     "    return StreamingResponse(gen(), media_type=\"text/event-stream\")"),

    ("A THIRD STREAM ARRIVES, written the way the first two were", APP,
     "",
     "\n\n@app.get(\"/api/inbox/stream\")\n"
     "async def inbox_stream(request: Request) -> StreamingResponse:\n"
     "    async def gen():\n"
     "        while not await request.is_disconnected():\n"
     "            yield \": hb\\n\\n\"\n"
     "            await asyncio.sleep(2)\n\n"
     "    return StreamingResponse(gen(), media_type=\"text/event-stream\")\n"),

    ("…or behind a helper, and unannotated, where its own code does not show it", APP,
     "",
     "\n\ndef _sse(frames):\n"
     "    return StreamingResponse(frames, media_type=\"text/event-stream\")\n\n\n"
     "@app.get(\"/api/inbox/stream\")\n"
     "async def inbox_stream(request: Request):\n"
     "    async def gen():\n"
     "        yield \": hb\\n\\n\"\n\n"
     "    return _sse(gen())\n"),

    ("a third stream goes through the seam and nobody drives it", APP,
     "",
     "\n\n@app.get(\"/api/inbox/stream\")\n"
     "async def inbox_stream(request: Request) -> StreamingResponse:\n"
     "    async def gen():\n"
     "        yield \": hb\\n\\n\"\n\n"
     "    return _event_stream(request, gen())\n"),

    # ── 6. the socket ───────────────────────────────────────────────────────────────────────────
    ("the socket is asked at the handshake and never again", APP,
     "            ended = await watch.ended() if watch.due() else None\n",
     "            ended = None\n"),

    ("the socket's goodbye does not say why, so the page backs off into a refused handshake",
     APP,
     "                await ws.send_text(json.dumps({\"kind\": \"bye\", \"reason\": "
     "snap.get(\"detail\", \"\"),\n                                               "
     "\"ended\": snap}))",
     "                await ws.send_text(json.dumps({\"kind\": \"bye\", \"reason\": "
     "snap.get(\"detail\", \"\")}))"),

    ("the socket says bye and stays open", APP,
     "                await ws.close(code=1011 if snap[\"why\"] == _ENDED_UNAVAILABLE else 1008,\n"
     "                               reason=snap[\"why\"])\n",
     ""),

    # ── 7. the page ─────────────────────────────────────────────────────────────────────────────
    ("the server stops serving the event's name, and the page listens for `undefined`", APP,
     "        \"stream_ended\": STREAM_ENDED_EVENT,\n",
     ""),

    ("the engine stream does not listen for its own end", PAGE,
     "  source.addEventListener(STREAM_ENDED,()=>{\n"
     "    if(engineES===source)engineES=null;\n"
     "    streamEnded(\"engine\",source,engineStream)});\n",
     ""),

    ("the job feed does not listen for its own end", PAGE,
     "    streamEnded(\"feed\",source,()=>{",
     "    (()=>{})(\"feed\",source,()=>{"),

    ("the page leaves the source open: the browser reconnects it into a 401 it cannot see", PAGE,
     "  try{source.close()}catch(_){}\n  _streamsEnded[which]=reopen;",
     "  _streamsEnded[which]=reopen;"),

    ("the page reconnects at once, blindly", PAGE,
     "  _streamsEnded[which]=reopen;\n  loadFloor();",
     "  reopen();\n  loadFloor();"),

    ("the page closes the stream and asks nobody why", PAGE,
     "  _streamsEnded[which]=reopen;\n  loadFloor();",
     "  _streamsEnded[which]=reopen;"),

    ("a stream the server ended never comes back, even for a credential that is good", PAGE,
     "    reopenEndedStreams()}",
     "    }"),

    ("every answered floor reopens the same stream again", PAGE,
     "  const again=_streamsEnded;_streamsEnded={};",
     "  const again=_streamsEnded;"),

    ("the feed returns under its own replay: the journal is written beneath itself", PAGE,
     "      const feed=$(\"#feed\");if(feed)feed.innerHTML=\"\";\n      openFeed(p,i)})});",
     "      openFeed(p,i)})});"),

    ("the feed reopens for a card nobody is looking at", PAGE,
     "      if(es||!focus||focus.p!==p||focus.i!==i)return;\n",
     ""),

    ("a socket ended over its credential is backed off into a handshake refused for ever", PAGE,
     "      if(m.ended){if(_ws===sock)_ws=null;streamEnded(\"socket\",sock,streamConnect)}",
     ""),
]
