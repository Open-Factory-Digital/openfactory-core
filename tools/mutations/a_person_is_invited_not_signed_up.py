"""#33 slice 2 (a person is invited, not signed up): every rule of the store and the doors is a cut.

Rows remove one rule each — the link's expiry, the password floor, the session's expiry, a
revocation, the wrong password, the voucher, a write that did not land, the hash instead of the
token, the session reaching `identify`, the door closing, the login page appearing, logout
revoking, `next` staying home, the two passwords agreeing, the unknown link's 404, the panel
action's admin gate and voucher, the shell's refusal of a sink that keeps nothing — and the guard
file must go red for each.
"""

TEST = "tests/test_a_person_is_invited_not_signed_up.py"
PEOPLE = "openfactory/identity/people.py"
LOCAL = "openfactory/identity/local.py"
APP = "openfactory/api/app.py"
CATALOG = "openfactory/actions/catalog.py"
METRICS = "openfactory/observability/metrics.py"
CLI_DOC = "docs/reference/cli.md"

MUTATIONS = [
    # ── the store ──
    ("an expired invitation is still pending", PEOPLE,
     "            if inv.expires_at > now and inv.id not in snap.people:\n",
     "            if inv.id not in snap.people:\n"),

    ("the password floor is gone", PEOPLE,
     '        if len(str(password or "")) < PASSWORD_MIN_CHARS:\n',
     "        if False:\n"),

    ("a session never expires", PEOPLE,
     "            if s.expires_at > now:\n                snap.sessions[s.token_hash] = s\n",
     "            if True:\n                snap.sessions[s.token_hash] = s\n"),

    ("a revocation is ignored", PEOPLE,
     '        elif event == "revoked":\n            snap.sessions.pop(str(x.get("token_hash") or ""), None)\n',
     '        elif event == "revoked":\n            pass\n'),

    ("the wrong password logs in", PEOPLE,
     '        if not _password_matches(str(password or ""), person.password_hash):\n            return ""\n',
     '        if False:\n            return ""\n'),

    ("nobody has to vouch", PEOPLE,
     '        if not str(by or "").strip():\n'
     '            return "an invitation records who vouched for the person, and nobody did"\n',
     '        if False:\n'
     '            return "an invitation records who vouched for the person, and nobody did"\n'),

    ("a write that did not land is handed out as a link", PEOPLE,
     '        if not landed:\n            return "the invitation was not recorded',
     '        if False:\n            return "the invitation was not recorded'),

    ("the token is stored plain", PEOPLE,
     "        inv = Invitation(id=ident, token_hash=digest(token), display=str(display or \"\").strip(),\n",
     "        inv = Invitation(id=ident, token_hash=token, display=str(display or \"\").strip(),\n"),

    # ── the local row ──
    ("a session is not a person", LOCAL,
     "            registered = self.people().session_of(token)\n",
     "            registered = None\n"),

    ("a registered person leaves the door open", LOCAL,
     "        return not self.people().has_people()\n",
     "        return True\n"),

    ("no login page once people exist", LOCAL,
     '        return LOGIN_PATH if self.people().has_people() else ""\n',
     '        return ""\n'),

    # ── the panel ──
    ("logout leaves the session alive", APP,
     "        if held and local.people().revoke(held):\n",
     "        if False:\n"),

    ("`next` may leave the origin on the form", APP,
     '    next_path = _sso.safe_next(fields.get("next", "/"))\n',
     '    next_path = fields.get("next", "/")\n'),

    ("two different passwords register", APP,
     '    if fields.get("password", "") != fields.get("again", ""):\n',
     "    if False:\n"),

    ("an unknown link gets a form", APP,
     "    if invitation is None:\n        return _no_invitation()\n"
     '    return _auth_page("Register", _register_form(invite, invitation.display))\n',
     '    return _auth_page("Register", _register_form(invite, getattr(invitation, "display", "")))\n'),

    ("a refused sign-in still gets a session cookie", APP,
     '    if not token:\n        log.info("OPENFACTORY_LOGIN_REFUSED',
     '    if False:\n        log.info("OPENFACTORY_LOGIN_REFUSED'),

    # ── the panel's action and the shell ──
    ("anybody may invite from the panel", CATALOG,
     '            optional=("display", "product"),\n            params={\n',
     '            optional=("display", "product"),\n            needs_admin=False,\n            params={\n'),

    ("the actor is not the voucher", CATALOG,
     '                                       by=(by.id or "").strip())\n',
     '                                       by="panel")\n'),

    ("a sink that keeps nothing is not refused before a link is minted", CATALOG,
     "    why = _people.sink_is_durable()\n    if why:\n        return refused(UNAVAILABLE, why)\n",
     '    why = ""\n    if why:\n        return refused(UNAVAILABLE, why)\n'),

    # ── the window the fold reads (found in review, 2026-09-03) ──
    ("a revocation is permanent again — the accounts scroll out from under it", PEOPLE,
     '        return bool(self._record("revoked", {"token_hash": session.token_hash},\n'
     "                                 expires_at=session.expires_at))\n",
     '        return bool(self._record("revoked", {"token_hash": session.token_hash}))\n'),

    ("a session is written without an expiry too", PEOPLE,
     '                                         "expires_at": expires}, expires_at=expires)\n',
     '                                         "expires_at": expires})\n'),

    ("an invitation never expires out of the window", PEOPLE,
     "                         expires_at=now + INVITE_TTL_SECONDS)\n",
     "                         expires_at=None)\n"),

    # ── the declaration and the document ──
    ("the kind is not declared", METRICS,
     '                     "person"]\n',
     "                     ]\n"),

    ("the shell reference forgets the command", CLI_DOC,
     "| `openfactory people invite \\| list` |",
     "| `openfactory approver-people` |"),
]
