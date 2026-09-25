"""The gate holds when the people store cannot be read: every reader's answer is a cut.

"I cannot read who is registered" is never "nobody is registered". The rows below put the fold
back one reader at a time — the store itself, the sink that cannot be built, the local row's three
answers and its declaration, the one admission decision, each of the three doors that render it,
the forms, the shell, the action row — and one row per way of "fixing" it that the guard must also
refuse: the cause sent to a caller nobody identified, a double's every-answer taken for a
declaration, a failed read remembered, a new install locked out.
"""

TEST = "tests/test_the_gate_holds_when_the_store_cannot_be_read.py"
PEOPLE = "openfactory/identity/people.py"
LOCAL = "openfactory/identity/local.py"
APP = "openfactory/api/app.py"
VIEW = "openfactory/api/metrics_view.py"
CATALOG = "openfactory/actions/catalog.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    # ── the store ───────────────────────────────────────────────────────────────────────────────
    ("an unreadable store is an empty snapshot again — the fold itself", PEOPLE,
     "            if isinstance(exc, StoreUnreadable):\n"
     "                raise\n"
     "            raise StoreUnreadable(f\"the people store could not be read: {exc}\") from exc\n",
     "            return snap\n"),

    ("only the typed exception counts, so a sink that throws its own takes the door down", PEOPLE,
     "            raise StoreUnreadable(f\"the people store could not be read: {exc}\") from exc\n",
     "            raise\n"),

    ("a failed read is remembered, so the store never recovers without a restart", PEOPLE,
     "            if isinstance(exc, StoreUnreadable):\n"
     "                raise\n",
     "            self._read = lambda: (_ for _ in ()).throw(exc)\n"
     "            if isinstance(exc, StoreUnreadable):\n"
     "                raise\n"),

    ("a window full of newer rows reads as `nobody is registered`", PEOPLE,
     "        if not snap.people and len(rows) >= READ_LAST:\n",
     "        if False:\n"),

    ("…and the other way: any full window refuses, so a busy deployment cannot be read at all",
     PEOPLE,
     "        if not snap.people and len(rows) >= READ_LAST:\n",
     "        if len(rows) >= READ_LAST:\n"),

    ("the people read stops saying it gates, so a sink that cannot be built is no store", PEOPLE,
     "    return records_of_kind(PROJECT, KIND, limit=READ_LAST, must_answer=True)\n",
     "    return records_of_kind(PROJECT, KIND, limit=READ_LAST)\n"),

    ("a sink that cannot be built is `no data` even for a caller that gates", VIEW,
     "        if must_build:\n", "        if False:\n"),

    ("the reader forgets the writer's default file, so `sqlite` with no file locks a new "
     "install out", VIEW,
     "        sink = build_metrics_sink(kind, path=metrics_db_path())\n",
     "        sink = build_metrics_sink(kind, path=None)\n"),

    # ── the local row ───────────────────────────────────────────────────────────────────────────
    ("could-not-look opens the door — the original direction", LOCAL,
     "            self._could_not_read(exc)\n            return False\n",
     "            self._could_not_read(exc)\n            return True\n"),

    ("the door closes and does not say why, so an anonymous caller is told 401", LOCAL,
     "            self._could_not_read(exc)\n            return False\n",
     "            return False\n"),

    ("a session that could not be looked up is `nobody`, so a signed-in person is told 401", LOCAL,
     "            self._could_not_read(exc)\n            return None\n",
     "            return None\n"),

    ("a login page is drawn while nobody can sign in", LOCAL,
     "            self._could_not_read(exc)\n            return \"\"\n",
     "            self._could_not_read(exc)\n            return LOGIN_PATH\n"),

    ("one request reads a dead store once per question", LOCAL,
     "        if self._unreadable:\n", "        if False:\n"),

    # ── the one decision ────────────────────────────────────────────────────────────────────────
    ("the admission ignores the declaration: everybody unresolved is `unauthorized`", APP,
     "        why = _why_unavailable(provider)\n        if why:\n",
     "        why = _why_unavailable(provider)\n        if False:\n"),

    ("the refusal carries the cause — a file's path — to a caller nobody identified", APP,
     "            return _Admission(provider=provider, unavailable=PEOPLE_UNAVAILABLE)\n",
     "            return _Admission(provider=provider,\n"
     "                              unavailable=f\"{IDENTITY_UNAVAILABLE}: {why}\")\n"),

    ("anything a provider answers is a declaration, so a double that answers everything is "
     "down", APP,
     "    return why.strip() if isinstance(why, str) else \"\"\n",
     "    return str(why).strip()\n"),

    # ── the three doors that render it ──────────────────────────────────────────────────────────
    ("the HTTP gate does not render `unavailable`", APP,
     # RE-PINNED 2026-09-20 (#208): the gate renders its refusals in `_gate_verdict` now, because
     # an open stream asks that same function again; this is the same rendering, one frame out.
     "    if door.unavailable:\n"
     "        return _Refusal(503, {\"detail\": door.unavailable})\n",
     "    if False:\n"
     "        return _Refusal(503, {\"detail\": door.unavailable})\n"),

    ("`require_auth` does not render `unavailable`", APP,
     "    if door.unavailable:\n        # A provider that cannot be built",
     "    if False:\n        # A provider that cannot be built"),

    ("the socket does not render `unavailable`", APP,
     # RE-PINNED 2026-09-20 (#228): the handshake has no `if door.unavailable` of its own any
     # more — it asks the gate like everybody else and renders whatever it answers. So the cut
     # is that one branch, made blind to the door's outage: the socket opens anyway when nobody
     # could be checked. Same claim, at the site that now carries it.
     '    refused = await watch.asked()\n    if refused is not None:\n',
     '    refused = await watch.asked()\n'
     '    if refused is not None and refused["why"] != _ENDED_UNAVAILABLE:\n'),

    ("the socket calls it a policy violation, so the page stops retrying a good credential", APP,
     # RE-PINNED 2026-09-20 (#228): the code is `_close_code`'s, one mapping for the refused open
     # and for the close ten seconds later — so the cut is the mapping, and it says 1008 to an
     # outage on both.
     "    return 1011 if why == _ENDED_UNAVAILABLE else 1008\n",
     "    return 1008\n"),

    # ── the forms ───────────────────────────────────────────────────────────────────────────────
    ("the form-login helper asks `login_path` again, where unreadable and nobody are both \"\"",
     APP,
     "    if local is not None and local.people().has_people():\n        return local\n",
     "    if local is not None and local.login_path:\n        return local\n"),

    ("the login page answers an outage with `nobody is registered by invitation yet`", APP,
     "        try:\n            local = _form_login()\n        except StoreUnreadable as exc:\n"
     "            return _people_unreadable(exc, \"signing in\")\n",
     "        try:\n            local = _form_login()\n        except StoreUnreadable:\n"
     "            local = None\n"),

    ("the login POST answers an outage with `nobody is registered by invitation yet`", APP,
     "    try:\n        local = _form_login()\n    except StoreUnreadable as exc:\n"
     "        return _people_unreadable(exc, \"signing in\")\n",
     "    try:\n        local = _form_login()\n    except StoreUnreadable:\n"
     "        local = None\n"),

    ("a good link is called one this deployment did not issue", APP,
     "        invitation = local.people().invitation_for(invite) if local is not None else None\n"
     "    except StoreUnreadable as exc:\n"
     "        return _people_unreadable(exc, \"registering\")\n",
     "        invitation = local.people().invitation_for(invite) if local is not None else None\n"
     "    except StoreUnreadable:\n"
     "        invitation = None\n"),

    ("a redemption against a store that cannot be read is a 404 about the link", APP,
     # RE-PINNED 2026-09-24: `_redeem` takes the request, so the session cookie it sets can be
     # the `__Host-` spelling over TLS (#271, #265 slice 0). The claim is unchanged.
     "        return _redeem(request, local, fields)\n    except StoreUnreadable as exc:\n",
     "        return _redeem(request, local, fields)\n    except _NeverRaised as exc:\n"),

    ("the forms' refusal is a 200", APP,
     "        status_code=503, headers=_NO_CACHE)\n",
     "        status_code=200, headers=_NO_CACHE)\n"),

    ("logout says nothing about the session it could not revoke", APP,
     "            log.warning(\"OPENFACTORY_LOGOUT_NOT_REVOKED the people store could not be read, "
     "so \"\n",
     "            log.debug(\"OPENFACTORY_LOGOUT_NOT_REVOKED the people store could not be read, "
     "so \"\n"),

    # ── the shell and the action row ────────────────────────────────────────────────────────────
    ("`people list` says nobody yet", CLI,
     "    except StoreUnreadable as exc:\n"
     "        # \"NOBODY YET\" IS AN ANSWER",
     "    except _NeverRaised as exc:\n"
     "        # \"NOBODY YET\" IS AN ANSWER"),

    ("`people list` names the store and exits 0", CLI,
     "                   f\"registered — {exc}\", err=True)\n"
     "        raise typer.Exit(code=1) from None\n",
     "                   f\"registered — {exc}\", err=True)\n        return\n"),

    ("the invite row calls an outage an invalid request", CATALOG,
     "        return refused(UNAVAILABLE, f\"the people store cannot be read, so no invitation "
     "was \"\n",
     "        return refused(INVALID, f\"the people store cannot be read, so no invitation "
     "was \"\n"),
]
