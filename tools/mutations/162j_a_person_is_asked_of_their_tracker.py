"""#162 (slack/people.py:101): a person is asked of the tracker that issued their ref."""

TEST = "tests/test_a_person_is_asked_of_their_own_tracker.py"
SLACK = "tests/test_slack_people.py"
BASE = "openfactory/adapters/tracker/base.py"
GH = "openfactory/adapters/tracker/github.py"
JIRA = "openfactory/adapters/tracker/jira.py"
ADO = "openfactory/adapters/tracker/azure_devops.py"
PEOPLE = "openfactory/runtime/slack/people.py"
CHANNEL = "openfactory/adapters/channel/slack.py"
ACT = "openfactory/runtime/temporal/activities.py"

MUTATIONS = [
    # ── the weld comes back ─────────────────────────────────────────────────────────────────────
    ("every person is looked up on github.com again, whatever the tracker", PEOPLE,
     "        ask = getattr(tracker, \"person\", None)\n"
     "        return dict(ask(ref) or {}) if callable(ask) else {}",
     "        import subprocess\n\n"
     '        p = subprocess.run(["gh", "api", f"users/{ref}"], capture_output=True, text=True)\n'
     '        return {"id": ref} if p.returncode else {"id": ref, "name": "x"}'),

    ("the contract stops declaring the question", BASE,
     "    def person(self, ref: str) -> dict:", "    def _person_removed(self, ref: str) -> dict:"),

    # ── each vendor ─────────────────────────────────────────────────────────────────────────────
    ("Azure invents a display name out of the sign-in address", ADO,
     '        return {"id": who, "name": "", "email": who.lower() if "@" in who else ""}',
     '        return {"id": who, "name": who.split("@")[0], '
     '"email": who.lower() if "@" in who else ""}'),

    ("…and passes a non-address ref off as an email", ADO,
     '"email": who.lower() if "@" in who else ""}', '"email": who.lower()}'),

    ("Jira stops escaping the account id in the query", JIRA,
     '            data = self._call("GET", f"user?accountId={urllib.parse.quote(account)}")',
     '            data = self._call("GET", f"user?accountId={account}")'),

    ("a Jira lookup that fails takes the message down", JIRA,
     "        except Exception as exc:  # noqa: BLE001 — a mention is never worth failing a "
     "message for\n"
     '            log.info("could not look up %s in Jira (%s) — they will be named, '
     'not notified",\n'
     "                     account, exc)\n"
     '            return {"id": account}',
     "        except ZeroDivisionError:\n            return {}"),

    ("…and a hidden email becomes a missing NAME too", JIRA,
     '        return {"id": account, "name": data.get("displayName") or "",\n'
     '                "email": (data.get("emailAddress") or "").lower()}',
     '        if not data.get("emailAddress"):\n            return {"id": account}\n'
     '        return {"id": account, "name": data.get("displayName") or "",\n'
     '                "email": (data.get("emailAddress") or "").lower()}'),

    ("GitHub reports a private profile as NOBODY", GH,
     '            return {"id": login}\n        if p.returncode != 0:',
     '            return {"id": login}\n        if False:'),

    ("…and malformed output raises inside a message composer", GH,
     "        try:\n            data = json.loads(p.stdout or \"{}\")\n"
     "        except ValueError:\n            return {\"id\": login}",
     '        data = json.loads(p.stdout or "{}")'),

    # ── the wiring ──────────────────────────────────────────────────────────────────────────────
    ("the channel drops the project again, so nothing can be asked", CHANNEL,
     "known=dict(getattr(project, \"people\", None) or {}), project=project)",
     'known=dict(getattr(project, "people", None) or {}))'),

    # ── what the adversarial review measured (2026-08-20) ───────────────────────────────────────
    ("the caller's token wins over the tracker axis — a forge credential reaches Jira", PEOPLE,
     "        tracker = build_tracker(project, token=tracker_token_for(project)\n"
     "                                or deployment_tracker_token(project))",
     "        tracker = build_tracker(project, token=_CALLER or tracker_token_for(project)\n"
     "                                or deployment_tracker_token(project))"),

    ("…and a caller can hand one in again", PEOPLE,
     "def tracker_person(login: str, *, project=None) -> dict:",
     "def tracker_person(login: str, *, project=None, token=None) -> dict:"),

    ("`mention` takes a credential it would silently drop", PEOPLE,
     "def mention(login: str, *, web_client=None,\n"
     "            known: dict[str, str] | None = None, project=None) -> str:",
     "def mention(login: str, *, web_client=None, token=None,\n"
     "            known: dict[str, str] | None = None, project=None) -> str:"),

    ("the activity hands the FORGE token to a person lookup again", ACT,
     "        return channel.mention(login, web_client=web_client, project=project) "
     'if login else ""',
     "        return channel.mention(login, web_client=web_client, token=module.token,\n"
     '                               project=project) if login else ""'),

    ("an unmatched person is rendered as the opaque ref, not the name", PEOPLE,
     '    named = str(person.get("name") or "").strip() or login',
     "    named = login"),

    ("…and the reverse: a ref with no name renders as nothing", PEOPLE,
     '    named = str(person.get("name") or "").strip() or login',
     '    named = str(person.get("name") or "").strip()'),

    ("`mention` stops passing the project down — every vendor loses its mentions", PEOPLE,
     "    person = tracker_person(login, project=project)",
     "    person = tracker_person(login)"),

    ("a GitHub lookup raises when `gh` is absent, mid-message", GH,
     "        try:\n            p = self._gh([\"api\", f\"users/{login}\"])\n"
     "        except Exception as exc:  # noqa: BLE001 — the contract says NEVER RAISES, "
     "and it means it",
     "        if True:\n            p = self._gh([\"api\", f\"users/{login}\"])\n"
     "        except_disabled = lambda exc: None  # noqa: E731\n        if False:"),

    ("the retired key is read again, keeping a shape nothing produces alive", PEOPLE,
     '    handle = _normalise(person.get("id") or "")',
     '    handle = _normalise(person.get("id") or person.get("login") or "")'),

    ("no project becomes a guess rather than a plain name", PEOPLE,
     "    if not ref or project is None:\n        return {}",
     "    if not ref:\n        return {}"),

    ("the handle heuristic stops reading the provider's ref", PEOPLE,
     '    handle = _normalise(person.get("id") or "")',
     '    handle = _normalise(person.get("login") or "")', SLACK),

    # ── the walk ────────────────────────────────────────────────────────────────────────────────
    ("the registry walk resolves whatever a row imports first", TEST,
     '             if m.group(2).endswith(("Tracker", "Issues", "Boards"))]',
     "             ]"),
]
